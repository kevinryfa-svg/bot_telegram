"""
Migraciones numeradas, que se aplican una sola vez.

Por qué hacía falta: create_tables() prepara el esquema en cada arranque a
base de CREATE TABLE IF NOT EXISTS y ADD COLUMN IF NOT EXISTS. Eso funciona
para "que exista", pero no sirve para nada que deba ejecutarse exactamente una
vez: corregir datos mal guardados, crear un índice, renombrar una columna,
añadir una restricción. Tampoco había forma de saber en qué versión de esquema
está producción.

Este módulo añade eso, sin tocar lo que ya funciona: create_tables() sigue
asegurando el esquema y, después, aquí se aplican los cambios pendientes en
orden y una sola vez.

Detalles que importan en producción:
  - un lock de PostgreSQL evita que dos instancias migren a la vez. No es
    teórico: en los despliegues han convivido dos contenedores un momento (se
    vio en los avisos de "terminated by other getUpdates").
  - cada migración va en su propia transacción: si falla, no deja el cambio a
    medias ni se marca como aplicada.
  - si una migración falla, no se aplican las siguientes: el orden es parte
    del contrato.
"""

import time

from db import conn


# Identificador del lock de asesoramiento. Cualquier número constante sirve;
# solo tiene que ser el mismo en todas las instancias.
MIGRATION_LOCK_ID = 918273645

MIGRATION_LOCK_ATTEMPTS = 30
MIGRATION_LOCK_WAIT_SECONDS = 2


# =========================
# MIGRACIONES
# =========================
# Cada entrada: (versión, nombre, lista de sentencias SQL).
# Las versiones no se reutilizan ni se reordenan nunca: una vez aplicada en
# producción, una migración es historia y se corrige con otra nueva.

MIGRATIONS = [

    (
        1,
        "indices_camino_del_dinero",
        [
            # payments solo tenía clave primaria por id, y el bot la consulta
            # constantemente por usuario y grupo (historial, recibos,
            # estadísticas): era un recorrido de tabla completa que empeora a
            # medida que entran pagos.
            "CREATE INDEX IF NOT EXISTS idx_payments_user_group "
            "ON payments (user_id, group_id)",

            # payments no tiene created_at: la fecha del cobro es payment_date.
            "CREATE INDEX IF NOT EXISTS idx_payments_payment_date "
            "ON payments (payment_date DESC)",

            # payment_transactions solo estaba indexada por idempotency_key.
            # La detección de pagos sin completar cruza la tabla consigo misma
            # por external_checkout_id cada media hora, y el webhook busca por
            # ese mismo campo: sin índice, ambos recorrían la tabla entera.
            "CREATE INDEX IF NOT EXISTS idx_payment_transactions_checkout "
            "ON payment_transactions (external_checkout_id)",

            "CREATE INDEX IF NOT EXISTS idx_payment_transactions_user_group "
            "ON payment_transactions (user_id, group_id)",

            "CREATE INDEX IF NOT EXISTS idx_payment_transactions_status "
            "ON payment_transactions (status)",

            # subscriptions se consulta por usuario y grupo al comprobar
            # accesos, y tampoco tenía índice.
            "CREATE INDEX IF NOT EXISTS idx_subscriptions_user_group "
            "ON subscriptions (user_id, group_id)",

            # invite_links se consulta por grupo al revisar accesos emitidos.
            "CREATE INDEX IF NOT EXISTS idx_invite_links_group "
            "ON invite_links (group_id)",
        ]
    ),

    (
        2,
        "borrar_claves_stripe_de_creadores_en_claro",
        [
            # El alta de creadores pedía la STRIPE_SECRET_KEY del creador y la
            # guardaba en claro en estas columnas, para no usarla en ningún
            # cobro. Ese paso se ha retirado; esto limpia lo que pudiera haber
            # quedado guardado de versiones anteriores.
            #
            # Las columnas se dejan (vaciarlas es reversible, borrarlas no) pero
            # ya no las escribe ni las lee nadie.
            "UPDATE group_payment_settings "
            "SET owner_stripe_secret_key = NULL, "
            "    owner_stripe_webhook_secret = NULL "
            "WHERE owner_stripe_secret_key IS NOT NULL "
            "   OR owner_stripe_webhook_secret IS NOT NULL",
        ]
    ),

]


# =========================
# REGISTRO DE VERSIONES
# =========================

def ensure_migrations_table():

    try:

        with conn.cursor() as cur:

            cur.execute("""

                CREATE TABLE IF NOT EXISTS schema_migrations (

                    version INTEGER PRIMARY KEY,

                    name TEXT NOT NULL,

                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    duration_ms INTEGER

                )

            """)

        return True

    except Exception as e:

        print("Migraciones: no se pudo crear schema_migrations:", e)

        return False


def fetch_applied_versions():

    try:

        with conn.cursor() as cur:

            cur.execute("SELECT version FROM schema_migrations")

            return {int(row[0]) for row in cur.fetchall()}

    except Exception as e:

        print("Migraciones: no se pudieron leer las versiones aplicadas:", e)

        return None


def current_schema_version():
    """Versión más alta aplicada, o 0 si ninguna."""

    applied = fetch_applied_versions()

    if not applied:

        return 0


    return max(applied)


def pending_migrations():

    applied = fetch_applied_versions()

    if applied is None:

        return []


    return [
        migration
        for migration in sorted(MIGRATIONS, key=lambda item: item[0])
        if migration[0] not in applied
    ]


# =========================
# LOCK ENTRE INSTANCIAS
# =========================

def acquire_lock():
    """
    Intenta tomar el lock. Devuelve True si se consiguió.

    Se usa try_advisory_lock con reintentos en vez de advisory_lock a secas
    para no quedarse bloqueado indefinidamente si otra instancia se cuelga.
    """

    for attempt in range(1, MIGRATION_LOCK_ATTEMPTS + 1):

        try:

            with conn.cursor() as cur:

                cur.execute(
                    "SELECT pg_try_advisory_lock(%s)",
                    (MIGRATION_LOCK_ID,)
                )

                if cur.fetchone()[0]:

                    return True

        except Exception as e:

            print("Migraciones: error pidiendo el lock:", e)

            return False


        if attempt == 1:

            print(
                "Migraciones: otra instancia está migrando, esperando…"
            )


        time.sleep(MIGRATION_LOCK_WAIT_SECONDS)


    print(
        "Migraciones: no se pudo obtener el lock; otra instancia se encarga."
    )

    return False


def release_lock():

    try:

        with conn.cursor() as cur:

            cur.execute(
                "SELECT pg_advisory_unlock(%s)",
                (MIGRATION_LOCK_ID,)
            )

    except Exception as e:

        print("Migraciones: error liberando el lock:", e)


# =========================
# APLICAR
# =========================

def apply_migration(version, name, statements):
    """
    Aplica una migración en una única transacción.

    La marca de aplicada entra en la misma transacción que los cambios: si algo
    falla, no queda ni el cambio a medias ni la marca.
    """

    started = time.monotonic()

    try:

        with conn.cursor() as cur:

            cur.execute("BEGIN")

            for statement in statements:

                cur.execute(statement)


            duration_ms = int((time.monotonic() - started) * 1000)

            cur.execute(
                "INSERT INTO schema_migrations (version, name, duration_ms) "
                "VALUES (%s, %s, %s)",
                (version, name, duration_ms)
            )

            cur.execute("COMMIT")


        return True, duration_ms

    except Exception as e:

        try:

            with conn.cursor() as cur:

                cur.execute("ROLLBACK")

        except Exception:

            pass


        return False, f"{type(e).__name__}: {e}"


def run_migrations():
    """
    Aplica las migraciones pendientes. Devuelve un resumen y no lanza nunca:
    el bot debe arrancar aunque una migración falle.
    """

    summary = {
        "applied": [],
        "failed": None,
        "skipped": False,
        "version": 0
    }


    if not ensure_migrations_table():

        summary["skipped"] = True

        return summary


    if not pending_migrations():

        summary["version"] = current_schema_version()

        return summary


    if not acquire_lock():

        summary["skipped"] = True

        return summary


    try:

        # Se vuelve a consultar con el lock en la mano: otra instancia puede
        # haberlas aplicado mientras esperábamos.
        for version, name, statements in pending_migrations():

            ok, detail = apply_migration(version, name, statements)

            if not ok:

                # Se corta aquí: aplicar las siguientes fuera de orden es peor
                # que quedarse en esta versión.
                summary["failed"] = {
                    "version": version,
                    "name": name,
                    "detail": detail
                }

                print(
                    f"Migraciones: falló la {version} ({name}):",
                    detail
                )

                break


            summary["applied"].append(
                {"version": version, "name": name, "duration_ms": detail}
            )

            print(f"Migraciones: aplicada {version} ({name}) en {detail} ms.")

    finally:

        release_lock()


    summary["version"] = current_schema_version()

    return summary


def describe_migrations():
    """Estado de las migraciones, para el panel de administración."""

    # Sin esto, abrir el panel antes de la primera migración decía "no se pudo
    # leer el estado" en vez de listar las pendientes: la tabla del registro
    # todavía no existía y eso no es un error.
    applied = fetch_applied_versions() if ensure_migrations_table() else None

    if applied is None:

        return (
            "🧱 Migraciones de base de datos\n\n"
            "No se pudo leer el estado."
        )


    pending = [
        migration
        for migration in sorted(MIGRATIONS, key=lambda item: item[0])
        if migration[0] not in applied
    ]

    lines = [
        "🧱 Migraciones de base de datos",
        "",
        f"Versión actual: {max(applied) if applied else 0}",
        f"Aplicadas: {len(applied)} de {len(MIGRATIONS)}"
    ]

    if pending:

        lines.append("")
        lines.append("Pendientes:")

        for version, name, _ in pending:

            lines.append(f"  • {version} · {name}")

    else:

        lines.append("")
        lines.append("✅ No hay migraciones pendientes.")


    return "\n".join(lines)
