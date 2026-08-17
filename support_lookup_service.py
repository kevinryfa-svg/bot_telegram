"""
La ficha de un comprador, para poder atenderle sin abrir la base de datos.

El buscador de usuarios contestaba esto:

    👤 Usuario 123456
    Grupo: VIP Fitness
    Expira: 2026-09-14 08:31:22.184000

Con eso no se puede atender a nadie. Las preguntas que llegan a soporte son
«pagué y no entro», «me habéis cobrado dos veces», «cancelé y me seguís
cobrando», y ninguna se responde con una fecha en formato de base de datos.

Esta ficha junta, por cada comunidad de la persona: en qué estado está su
acceso y hasta cuándo en formato humano, si tiene renovación automática y de
qué proveedor, cuánto ha pagado y cuándo fue la última vez, si está vetado,
y si tiene alguna incidencia de cobro abierta — con su id, porque el aviso
de incidencia ya trae botón para resolverla.

Dos decisiones:

  SOLO DATOS PROPIOS   Nada de preguntar a Stripe o a PayPal aquí. Una
                       pantalla de soporte que depende de una API ajena falla
                       justo cuando hay un cliente esperando. El estado de la
                       renovación se lee del ancla local, que es la que
                       gobierna nuestras decisiones.

  ALCANCE RESPETADO    Un administrador de una comunidad ve lo de SU
                       comunidad. La plataforma lo ve todo. Es el mismo
                       alcance que ya tenía el buscador; lo que cambia es lo
                       que se enseña, no quién puede verlo.
"""

from db import conn


def formato_fecha_humana(valor):
    """'14/09/2026' en vez de '2026-09-14 08:31:22.184000'."""

    try:

        return valor.strftime("%d/%m/%Y")

    except Exception:

        return "—"


def formato_importe(cents, currency):

    try:

        return f"{int(cents) / 100:.2f} {(currency or 'EUR').upper()}"

    except Exception:

        return "—"


def fetch_member_rows(user_id, group_ids=None):
    """Una fila por comunidad de esa persona, con todo lo que soporte necesita.

    group_ids None = alcance total (plataforma). Lista vacía = sin alcance.
    """

    condicion = "" if group_ids is None else " AND u.group_id = ANY(%(ids)s)"

    consulta = f"""

        SELECT u.group_id,
               COALESCE(g.name, 'comunidad borrada'),
               u.expiration,
               u.stripe_subscription_id IS NOT NULL,
               EXISTS (
                   SELECT 1 FROM payment_transactions pt
                   WHERE pt.provider = 'paypal'
                     AND pt.user_id = u.user_id
                     AND pt.group_id = u.group_id
                     AND pt.external_checkout_id IS NOT NULL
               ),
               EXISTS (
                   SELECT 1 FROM banned_users b
                   WHERE b.user_id = u.user_id
                     AND b.group_id = u.group_id
               ),
               COALESCE(hist.veces, 0),
               hist.total,
               hist.currency,
               hist.ultimo,
               COALESCE(inc.abiertas, 0),
               inc.primera_id
        FROM users u
        LEFT JOIN groups g ON g.id = u.group_id
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS veces,
                   SUM(p.amount) AS total,
                   MIN(p.currency) AS currency,
                   MAX(p.payment_date) AS ultimo
            FROM payments p
            WHERE p.user_id = u.user_id
              AND p.group_id = u.group_id
              AND LOWER(COALESCE(p.status, '')) IN ('paid', 'completed')
        ) hist ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS abiertas, MIN(i.id) AS primera_id
            FROM payment_incidents i
            WHERE i.user_id = u.user_id
              AND i.group_id = u.group_id
              AND i.resolved_at IS NULL
        ) inc ON TRUE
        WHERE u.user_id = %(uid)s{condicion}
        ORDER BY u.expiration DESC NULLS FIRST

    """

    try:

        with conn.cursor() as cur:

            cur.execute(consulta, {"uid": user_id, "ids": group_ids})

            return cur.fetchall() or []

    except Exception as e:

        print("Ficha de soporte: error leyendo al comprador:", e)

        return []


def estado_de_acceso(expiration):
    """('activo'|'caducado'|'permanente', texto) tal como se lo diría a alguien."""

    if expiration is None:

        return ("permanente", "Acceso permanente (sin fecha de fin)")

    try:

        from datetime import datetime

        if expiration > datetime.now():

            return ("activo",
                    f"Acceso activo hasta el {formato_fecha_humana(expiration)}")

        return ("caducado",
                f"Caducado el {formato_fecha_humana(expiration)}")

    except Exception:

        return ("desconocido", "Estado de acceso desconocido")


def build_member_dossier(user_id, group_ids=None):
    """El texto de la ficha. En español: es una pantalla de administración."""

    filas = fetch_member_rows(user_id, group_ids=group_ids)

    if not filas:

        return (
            f"👤 Usuario {user_id}\n\n"
            "No tiene acceso registrado en ninguna comunidad de tu alcance.\n\n"
            "Si dice que ha pagado, busca el pago por su id: puede ser un "
            "cobro sin acceso concedido, y eso sale en las incidencias."
        )


    lineas = [f"👤 Usuario {user_id}", ""]

    for fila in filas:

        (group_id, group_name, expiration, tiene_stripe, tiene_paypal,
         vetado, veces, total, currency, ultimo, incidencias,
         incidencia_id) = fila

        _clave, texto_estado = estado_de_acceso(expiration)

        lineas.append(f"🏠 {group_name} (id {group_id})")
        lineas.append(f"   {texto_estado}")

        if tiene_stripe:

            lineas.append("   Renovación automática: sí (Stripe)")

        elif tiene_paypal:

            lineas.append("   Renovación automática: sí (PayPal)")

        else:

            lineas.append("   Renovación automática: no")


        if int(veces or 0):

            lineas.append(
                f"   Ha pagado {int(veces)} veces · "
                f"{formato_importe(total, currency)} en total · "
                f"último el {formato_fecha_humana(ultimo)}"
            )

        else:

            # Acceso sin un solo pago: código promocional, prueba, o un
            # arreglo a mano. Saberlo evita buscar un pago que no existe.
            lineas.append("   Sin pagos registrados (código, prueba o manual)")


        if vetado:

            lineas.append("   ⛔ VETADO en esta comunidad")


        if int(incidencias or 0):

            lineas.append(
                f"   🚨 {int(incidencias)} incidencia(s) de cobro ABIERTA(S) "
                f"— la primera es la #{incidencia_id}"
            )


        lineas.append("")


    lineas.append(
        "Los datos son los nuestros: no se consulta a Stripe ni a PayPal, "
        "para que esta ficha no falle justo cuando hay alguien esperando."
    )

    return "\n".join(lineas)
