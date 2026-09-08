"""
La salud de TODAS las comunidades en una pantalla, para la plataforma.

Cada avería avisa a su propietario, y ahí está el problema: depende de que
ese propietario lea, entienda y actúe. Una comunidad con el bot degradado
lleva semanas sin poder vender y nadie de la plataforma lo sabe, porque el
único aviso fue a la persona que menos mira el bot.

Esta pantalla es la foto agregada de lo que está roto AHORA, ordenada por
lo que cuesta dinero, y con el nombre de la comunidad delante para poder
llamar a su dueño.

Cuatro cosas, en este orden:

  NO PUEDE ENTREGAR   El bot ya no puede crear enlaces. Es lo más grave: la
                      comunidad está en el mercado y sus compras se
                      bloquean, o peor, cobra y no entrega.

  COBROS SIN ACCESO   Incidencias de pago abiertas. Dinero cobrado sin
                      acceso concedido, esperando a una persona.

  EN VENTA SIN PLANES  Visible en el mercado y sin un plan usable: el
                      comprador entra, pulsa y no hay nada que comprar.

  RACHA DE FALLIDOS   Cobros de renovación fallando en las últimas 24 h.
                      Puede ser la cuenta de pagos de esa comunidad.

Y cuando no hay nada roto, lo dice en una línea. Una pantalla de salud que
siempre enseña algo enseña a ignorarla.
"""

import os

from db import conn


# Cuántas comunidades se listan por sección: la pantalla es para actuar hoy,
# no un inventario. El recuento total siempre se dice.
HEALTH_LIST_LIMIT = int(os.environ.get("PLATFORM_HEALTH_LIST_LIMIT", "8"))

# Misma vara que las alertas de negocio: por debajo de esto son tarjetas
# concretas, no un problema de la comunidad.
FAILED_STREAK_THRESHOLD = int(
    os.environ.get("BUSINESS_ALERT_FAILED_CHARGES", "3")
)


def fetch_broken_delivery():
    """[(group_id, nombre, dias_roto, bot_status)] de las que no entregan."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT h.group_id,
                       COALESCE(g.name, 'sin nombre'),
                       GREATEST(
                           EXTRACT(DAY FROM (NOW() - h.broken_since))::int, 0
                       ),
                       COALESCE(h.bot_status, 'sin estado')
                FROM group_delivery_health h
                JOIN groups g ON g.id = h.group_id
                WHERE h.can_deliver = FALSE
                  AND COALESCE(g.is_active, TRUE) = TRUE
                ORDER BY h.broken_since ASC NULLS LAST

            """)

            return cur.fetchall() or []

    except Exception as e:

        print("Salud de plataforma: error leyendo la entrega:", e)

        return None


def fetch_open_incidents():
    """[(group_id, nombre, abiertas, dias_la_mas_vieja)]."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT i.group_id,
                       COALESCE(g.name, 'sin nombre'),
                       COUNT(*),
                       GREATEST(
                           EXTRACT(DAY FROM (NOW() - MIN(i.created_at)))::int, 0
                       )
                FROM payment_incidents i
                LEFT JOIN groups g ON g.id = i.group_id
                WHERE i.resolved_at IS NULL
                GROUP BY i.group_id, g.name
                ORDER BY MIN(i.created_at) ASC

            """)

            return cur.fetchall() or []

    except Exception as e:

        print("Salud de plataforma: error leyendo incidencias:", e)

        return None


def fetch_unsellable_but_visible():
    """[(group_id, nombre)] visibles en el mercado y sin plan que vender.

    Las gratuitas quedan fuera: no necesitan plan para funcionar.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT g.id, COALESCE(g.name, 'sin nombre')
                FROM groups g
                WHERE COALESCE(g.is_active, TRUE) = TRUE
                  AND (
                      COALESCE(g.is_marketplace_visible, FALSE) = TRUE
                      OR COALESCE(g.is_main_menu_visible, FALSE) = TRUE
                  )
                  AND COALESCE(g.is_free_group, FALSE) = FALSE
                  AND COALESCE(g.is_free, FALSE) = FALSE
                  AND NOT EXISTS (
                      SELECT 1 FROM plans p
                      WHERE p.group_id = g.id
                        AND COALESCE(p.is_active, TRUE) = TRUE
                        AND p.amount IS NOT NULL AND p.amount > 0
                        AND p.duration_days IS NOT NULL AND p.duration_days > 0
                  )
                ORDER BY g.id ASC

            """)

            return cur.fetchall() or []

    except Exception as e:

        print("Salud de plataforma: error buscando comunidades sin planes:", e)

        return None


def fetch_failed_charge_streaks():
    """[(group_id, nombre, fallidos_24h)] por encima del umbral."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT l.group_id,
                       COALESCE(g.name, 'sin nombre'),
                       COUNT(*)
                FROM audit_logs l
                -- JOIN, no LEFT JOIN: los registros sobreviven al borrado de
                -- una comunidad, y listar una que ya no existe es ruido que
                -- nadie puede arreglar.
                JOIN groups g
                  ON g.id = l.group_id
                 AND COALESCE(g.is_active, TRUE) = TRUE
                WHERE l.event_type = 'group_subscription_payment_failed'
                  AND l.created_at >= NOW() - INTERVAL '24 hours'
                  AND l.group_id IS NOT NULL
                GROUP BY l.group_id, g.name
                HAVING COUNT(*) >= %s
                ORDER BY COUNT(*) DESC

            """, (FAILED_STREAK_THRESHOLD,))

            return cur.fetchall() or []

    except Exception as e:

        print("Salud de plataforma: error contando cobros fallidos:", e)

        return None


def count_failed_notices_without_portal(days=30):
    """Cuántos avisos de "revisa tu tarjeta" salieron SIN botón para revisarla.

    El portal de facturación de Stripe se activa una vez, en el panel de
    Stripe. Sin él, el aviso de cobro fallido sigue saliendo —eso nunca se
    degrada al silencio— pero sin el botón que arregla el problema en un
    toque. Ese coste no se veía en ningún sitio: aquí se cuenta, con datos
    reales, para que la activación deje de ser una tarea sin dueño.

    Devuelve (sin_portal, total) del periodo.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*) FILTER (
                           WHERE COALESCE(metadata->>'portal_ok', 'false') != 'true'
                       ),
                       COUNT(*)
                FROM audit_logs
                WHERE event_type = 'group_subscription_payment_failed'
                  AND created_at >= NOW() - (%s || ' days')::interval
                  AND metadata ? 'portal_ok'

            """, (int(days),))

            sin_portal, total = cur.fetchone() or (0, 0)

            return (int(sin_portal or 0), int(total or 0))

    except Exception as e:

        print("Salud de plataforma: error contando avisos sin portal:", e)

        return None


def _seccion(lineas, titulo, filas, formatear):
    """Añade una sección con tope y, si hay más, dice cuántas se callan."""

    if not filas:
        return False

    lineas.append(titulo)

    for fila in filas[:HEALTH_LIST_LIMIT]:

        lineas.append("   " + formatear(fila))

    sobrantes = len(filas) - HEALTH_LIST_LIMIT

    if sobrantes > 0:

        # Un tope que no se dice se lee como "esto es todo".
        lineas.append(f"   …y {sobrantes} más")

    lineas.append("")

    return True


def build_platform_health_text():
    """La pantalla entera. En español, como el resto del panel de plataforma."""

    # «VACÍO» Y «NO SE PUDO PREGUNTAR» NO SON LO MISMO. Cada consulta devolvía
    # lista vacía también cuando fallaba, y esta pantalla remataba con «✅ Nada
    # roto». O sea que un error de base de datos se leía IGUAL que una
    # plataforma sana, en la única pantalla que existe para decir qué está roto.
    consultas = {
        "entrega de accesos": fetch_broken_delivery(),
        "cobros sin acceso": fetch_open_incidents(),
        "comunidades sin plan": fetch_unsellable_but_visible(),
        "rachas de cobros fallidos": fetch_failed_charge_streaks(),
    }

    no_comprobado = [
        nombre for nombre, filas in consultas.items() if filas is None
    ]

    entrega = consultas["entrega de accesos"] or []
    incidencias = consultas["cobros sin acceso"] or []
    sin_planes = consultas["comunidades sin plan"] or []
    fallidos = consultas["rachas de cobros fallidos"] or []

    lineas = ["🩺 Salud de las comunidades", ""]

    hay_algo = False

    hay_algo |= _seccion(
        lineas,
        f"🚨 No pueden entregar accesos ({len(entrega)})",
        entrega,
        lambda f: f"{f[1]} (id {f[0]}) — {f[2]} días, estado: {f[3]}"
    )

    hay_algo |= _seccion(
        lineas,
        f"💸 Cobros sin acceso abiertos ({len(incidencias)} comunidades)",
        incidencias,
        lambda f: f"{f[1]} (id {f[0]}) — {f[2]} abiertas, la más vieja hace "
                  f"{f[3]} días"
    )

    hay_algo |= _seccion(
        lineas,
        f"🛒 En venta y sin plan que vender ({len(sin_planes)})",
        sin_planes,
        lambda f: f"{f[1]} (id {f[0]})"
    )

    hay_algo |= _seccion(
        lineas,
        f"⚠️ Racha de cobros fallidos en 24 h ({len(fallidos)})",
        fallidos,
        lambda f: f"{f[1]} (id {f[0]}) — {f[2]} fallidos"
    )

    portal = count_failed_notices_without_portal()

    if portal is None:

        no_comprobado.append("portal de facturación")

    sin_portal, total_fallidos = portal or (0, 0)

    if sin_portal:

        hay_algo = True

        lineas.extend([
            f"💳 Portal de facturación sin activar ({sin_portal} de "
            f"{total_fallidos} avisos)",
            f"   {sin_portal} compradores recibieron el aviso de cobro "
            "fallido SIN botón para cambiar la tarjeta (últimos 30 días).",
            "   Se activa una vez en el panel de Stripe → Configuración del "
            "portal de cliente. Cada uno de esos avisos es un cobro que se "
            "puede perder por una tarjeta caducada.",
            "",
        ])


    if no_comprobado:

        lineas.extend([
            "⚠️ No se ha podido comprobar: " + ", ".join(no_comprobado) + ".",
            "   La base de datos no ha contestado a esa parte, así que de eso "
            "esta pantalla NO dice nada. Vuelve a abrirla con «🔄 Actualizar».",
            "",
        ])


    if not hay_algo:

        if no_comprobado:

            lineas.append(
                "De lo que sí se ha podido comprobar, no hay nada roto."
            )

            return "\n".join(lineas).rstrip()

        lineas.append(
            "✅ Nada roto: todas las comunidades activas pueden entregar, no "
            "hay cobros sin acceso pendientes y ninguna está en venta sin "
            "planes."
        )

        return "\n".join(lineas)


    lineas.append(
        "Cada línea lleva el id de la comunidad para poder abrirla y hablar "
        "con su propietario."
    )

    return "\n".join(lineas).rstrip()
