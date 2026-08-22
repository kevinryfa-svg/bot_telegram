import os
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import conn
from bot_config import ADMIN_ID
from audit_log_service import log_event


# =========================
# REENGANCHE — USUARIOS SIN COMPRAS
# =========================
# Envía cada N días un mensaje a los usuarios que han pasado por el bot pero
# nunca han contratado nada, explicando qué hay disponible y cómo funciona.
#
# Salvaguardas (protegen la cuenta del bot y evitan que se marque como spam):
#   - Se para solo si el usuario compra, se da de baja o bloquea el bot.
#   - Tope de mensajes por usuario (no se insiste indefinidamente).
#   - Envíos en tandas con pausa entre mensajes (límites de Telegram).
#   - Nunca se envía a admins, propietarios ni usuarios baneados.

# Cada 7 días, no cada 3. El dato que lo cambió: de 306 personas a las que este
# bot había escrito, 176 —el 58%— habían bloqueado el bot. Seis mensajes en
# dieciocho días a alguien que no compró, y encima durante meses en los que el
# botón de pagar estaba roto, es exactamente la receta para que te bloqueen.
# Una audiencia quemada no se recupera: cada bloqueo es una persona que ya no
# puede recibir nada nunca más.
REENGAGEMENT_INTERVAL_DAYS = int(
    os.environ.get("REENGAGEMENT_INTERVAL_DAYS", "7")
)

REENGAGEMENT_MAX_MESSAGES = int(
    os.environ.get("REENGAGEMENT_MAX_MESSAGES", "6")
)

REENGAGEMENT_BATCH_SIZE = int(
    os.environ.get("REENGAGEMENT_BATCH_SIZE", "25")
)

REENGAGEMENT_SEND_DELAY_SECONDS = float(
    os.environ.get("REENGAGEMENT_SEND_DELAY_SECONDS", "0.6")
)

REENGAGEMENT_ENABLED = os.environ.get(
    "REENGAGEMENT_ENABLED",
    "true"
).strip().lower() not in ("0", "false", "no", "off")


# =========================
# EL RELANZAMIENTO: UN AVISO MÁS, Y UNO SOLO
# =========================
# Las personas que gastaron el tope de avisos lo gastaron cuando esto NO PODÍA
# COBRAR: el único plan a la venta se pagaba por un método deshabilitado, sin
# identificador de precio y con la moneda escrita de una forma que Stripe
# rechaza. Su «no» fue a una tienda rota, no a esta.
#
# Eso justifica UN aviso más, y solo uno, con estas tres condiciones:
#
#   HAY QUE TENER ALGO   Si el escaparate está vacío no se manda nada. Escribir
#                        «ya funciona» sin nada que vender es la última vez que
#                        alguien abre un mensaje de este bot.
#
#   UNO POR CLAVE        Cada relanzamiento tiene un nombre y se anota en la
#                        persona. Con el nombre anotado ya no vuelve a entrar:
#                        esto no es una forma de saltarse el tope, es una
#                        excepción con nombre y fecha.
#
#   SE SIGUE RESPETANDO  Quien se dio de baja, bloqueó el bot o está baneado no
#   EL «NO»              recibe nada, igual que siempre.
REENGAGEMENT_RELAUNCH_KEY = (
    os.environ.get("REENGAGEMENT_RELAUNCH_KEY") or ""
).strip()


def hay_algo_que_vender():
    """¿El escaparate tiene algo? Sin esto no se relanza nada."""

    try:

        from start_offer_service import fetch_sellable_communities

        return bool(fetch_sellable_communities(0, limit=1))

    except Exception as e:

        print("Reenganche: no se pudo mirar el escaparate:", str(e)[:160])

        return False


def se_puede_cobrar_ahora():
    """¿El servidor que crea los cobros contesta? Una petición, no más.

    Va aquí y no solo en el arranque porque de esto depende si tiene sentido
    escribir a nadie: durante meses este bot escribió cada tres días a gente que,
    al pulsar comprar, se encontraba «No he podido abrir la pasarela de pago».
    De 306 personas avisadas, 176 acabaron bloqueando el bot.
    """

    try:

        from sale_readiness_service import check_checkout_endpoint

        ok, _detalle = check_checkout_endpoint()

        return bool(ok)

    except Exception as e:

        print("Reenganche: no se pudo comprobar el cobro:", str(e)[:160])

        # Ante la duda NO se escribe: el coste de callarse una tanda es cero, y
        # el de escribir con el cobro roto es una audiencia bloqueada.
        return False


def merece_la_pena_escribir():
    """(ok, motivo). Las dos condiciones para molestar a alguien hoy.

    Un aviso comercial solo se justifica si al otro lado hay algo que se puede
    comprar de verdad. Sin esto, la campaña seguía funcionando perfectamente
    mientras la tienda estaba rota: repartía el daño en silencio, tres días tras
    tres días.
    """

    if not hay_algo_que_vender():

        return (
            False,
            "no hay ni una comunidad vendible: escribir sin nada que ofrecer "
            "solo gasta la paciencia de la gente"
        )

    if not se_puede_cobrar_ahora():

        return (
            False,
            "el servidor de cobro no contesta: quien pulse comprar se llevará "
            "un error, y eso es lo que hace que bloqueen el bot"
        )

    return (True, "")


def relanzamiento_activo():
    """Hay clave de relanzamiento Y hay algo que vender."""

    return bool(REENGAGEMENT_RELAUNCH_KEY) and hay_algo_que_vender()


CALLBACK_REENGAGEMENT_STOP = "reengagement_stop"


# =========================
# SELECCIÓN DE DESTINATARIOS
# =========================

# =========================
# QUIÉN ES UN CANDIDATO: UNA SOLA DEFINICIÓN
# =========================
# «Ha pasado por el bot y no ha contratado nada» estaba escrito tres veces, con
# cuarenta líneas cada una. Tres copias de una regla son tres reglas: basta con
# arreglar una para que el recuento diga una cosa y el envío haga otra.

SQL_CANDIDATOS = """

    WITH visitors AS (
        -- Eventos registrados (visitantes recientes)
        SELECT DISTINCT user_id
        FROM bot_user_events
        WHERE user_id IS NOT NULL AND user_id > 0

        UNION

        -- Usuarios que el bot ya conoce (incluye visitantes antiguos,
        -- anteriores al registro de eventos)
        SELECT DISTINCT user_id
        FROM users
        WHERE user_id IS NOT NULL AND user_id > 0
    )
    SELECT e.user_id,
           COALESCE(r.sent_count, 0) AS avisos,
           r.last_sent_at,
           COALESCE(r.opted_out, FALSE) AS de_baja,
           COALESCE(r.is_blocked, FALSE) AS bloqueado,
           COALESCE(r.relaunch_key, '') AS relanzamiento
    FROM visitors e
    LEFT JOIN user_reengagement r ON r.user_id = e.user_id
    WHERE e.user_id <> %(admin)s

      AND NOT EXISTS (
          SELECT 1
          FROM payments p
          WHERE p.user_id = e.user_id
            AND LOWER(COALESCE(p.status, '')) IN ('paid', 'completed', 'succeeded')
      )

      AND NOT EXISTS (
          SELECT 1
          FROM payment_transactions t
          WHERE t.user_id = e.user_id
            AND LOWER(COALESCE(t.status, '')) IN ('paid', 'completed', 'succeeded')
      )

      AND NOT EXISTS (
          SELECT 1
          FROM users u
          WHERE u.user_id = e.user_id
            AND (
                COALESCE(u.subscription_active, FALSE) = TRUE
                OR (u.expiration IS NOT NULL AND u.expiration > NOW())
            )
      )

      AND NOT EXISTS (
          SELECT 1
          FROM banned_users b
          WHERE b.user_id = e.user_id
      )

      AND NOT EXISTS (
          SELECT 1
          FROM admins a
          WHERE a.user_id = e.user_id
      )

"""


def explica_por_que_no_hay_nadie():
    """Por qué una pasada no tiene a nadie a quien escribir.

    Sin esto, una pasada vacía y una campaña agotada se leen igual: «ninguna
    persona pendiente». Y son dos cosas distintas con arreglos distintos —una se
    resuelve esperando y la otra no se resuelve sola—. Esto lo dice en números.
    """

    clave = REENGAGEMENT_RELAUNCH_KEY if relanzamiento_activo() else ""

    try:

        with conn.cursor() as cur:

            cur.execute(
                "SELECT COUNT(*) FILTER (WHERE de_baja), "
                "COUNT(*) FILTER (WHERE bloqueado AND NOT de_baja), "
                "COUNT(*) FILTER (WHERE NOT de_baja AND NOT bloqueado "
                "                 AND last_sent_at IS NOT NULL "
                "                 AND last_sent_at >= NOW() - "
                "                     (%(dias)s || ' days')::interval), "
                "COUNT(*) FILTER (WHERE NOT de_baja AND NOT bloqueado "
                "                 AND avisos >= %(tope)s "
                "                 AND (%(clave)s = '' OR relanzamiento = %(clave)s)), "
                "COUNT(*) "
                "FROM (" + SQL_CANDIDATOS + ") AS candidatos",
                {
                    "admin": int(ADMIN_ID),
                    "dias": REENGAGEMENT_INTERVAL_DAYS,
                    "tope": REENGAGEMENT_MAX_MESSAGES,
                    "clave": clave,
                },
            )

            fila = cur.fetchone() or (0, 0, 0, 0, 0)

    except Exception as e:

        return f"no se pudo averiguar por qué ({str(e)[:120]})"

    de_baja, bloqueados, recientes, agotados, total = [int(x or 0) for x in fila]

    partes = [f"{total} candidatos"]

    # El número que más importa de todos: quien bloquea el bot no vuelve. Si es
    # una parte grande de la audiencia, el problema no es a quién se escribe
    # esta semana, es que se ha escrito demasiado y sin nada que vender.
    if total and bloqueados * 100 >= total * 30:

        partes.append(
            f"⚠️ {bloqueados * 100 // total}% de la audiencia ha bloqueado el "
            "bot: se ha escrito demasiado, o se escribió cuando no se podía "
            "comprar"
        )

    if de_baja:
        partes.append(f"{de_baja} se dieron de baja")

    if bloqueados:
        partes.append(f"{bloqueados} bloquearon el bot")

    if recientes:
        partes.append(
            f"{recientes} avisados hace menos de {REENGAGEMENT_INTERVAL_DAYS} días"
        )

    if agotados:

        partes.append(
            f"{agotados} gastaron el tope de {REENGAGEMENT_MAX_MESSAGES} avisos"
            + (" y ya recibieron el relanzamiento" if clave else
               " (no hay relanzamiento activo)")
        )

    return ", ".join(partes)


def fetch_reengagement_targets(limit=None):
    """
    Usuarios que han usado el bot y NO han contratado nada:
    sin pagos, sin acceso activo, no baneados, no admins,
    no dados de baja, sin haber bloqueado el bot y respetando
    el intervalo y el tope de mensajes.
    """

    limit = int(limit or REENGAGEMENT_BATCH_SIZE)

    # Se resuelve UNA vez por tanda: mirar el escaparate por persona sería la
    # misma respuesta repetida cientos de veces.
    clave_de_relanzamiento = (
        REENGAGEMENT_RELAUNCH_KEY if relanzamiento_activo() else ""
    )

    with conn.cursor() as cur:

        cur.execute(
            "SELECT user_id, avisos FROM (" + SQL_CANDIDATOS + ") AS candidatos "
            "WHERE NOT de_baja AND NOT bloqueado "

            # El tope de siempre, más la excepción con nombre: quien lo gastó
            # cuando esto no podía cobrar entra UNA vez, y al anotarle la clave
            # deja de entrar.
            "AND (avisos < %(tope)s "
            "     OR (%(clave)s <> '' AND relanzamiento <> %(clave)s)) "

            "AND (last_sent_at IS NULL "
            "     OR last_sent_at < NOW() - (%(dias)s || ' days')::interval) "
            "ORDER BY user_id LIMIT %(limite)s",
            {
                "admin": int(ADMIN_ID),
                "tope": REENGAGEMENT_MAX_MESSAGES,
                "clave": clave_de_relanzamiento,
                "dias": REENGAGEMENT_INTERVAL_DAYS,
                "limite": limit,
            },
        )

        # (user_id, avisos_ya_recibidos) — el contador elige la variante.
        return [
            (row[0], int(row[1] or 0))
            for row in cur.fetchall()
            if row[0]
        ]


_logged_empty_run = False

# Una vez por proceso, igual que el anterior: el motivo no cambia entre pasadas.
_logged_no_vale_la_pena = False


def count_reengagement_candidates():
    """Cuántas personas cumplen el perfil (visitó y no compró), sin filtrar
    por intervalo ni tope: sirve para saber el alcance real de la campaña."""

    with conn.cursor() as cur:

        cur.execute(
            "SELECT COUNT(*) FROM (" + SQL_CANDIDATOS + ") AS candidatos",
            {"admin": int(ADMIN_ID)},
        )

        return (cur.fetchone() or [0])[0] or 0


def count_reengagement_pending():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT
                COUNT(*) FILTER (WHERE COALESCE(opted_out, FALSE) = TRUE),
                COUNT(*) FILTER (WHERE COALESCE(is_blocked, FALSE) = TRUE),
                COALESCE(SUM(sent_count), 0)
            FROM user_reengagement

        """)

        row = cur.fetchone() or (0, 0, 0)


    return {
        "opted_out": row[0] or 0,
        "blocked": row[1] or 0,
        "messages_sent": row[2] or 0
    }


# =========================
# ESTADO POR USUARIO
# =========================

def mark_reengagement_sent(user_id, relaunch_key=None):
    """Anota el envío. Con clave de relanzamiento, la deja anotada.

    Anotarla es lo que convierte el relanzamiento en UNO: con la clave puesta,
    esa persona ya no vuelve a entrar por esa excepción.
    """

    clave = (relaunch_key or "").strip() or None

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO user_reengagement
                (user_id, sent_count, last_sent_at, relaunch_key, updated_at)
            VALUES (%s, 1, NOW(), %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                sent_count = COALESCE(user_reengagement.sent_count, 0) + 1,
                last_sent_at = NOW(),
                relaunch_key = COALESCE(%s, user_reengagement.relaunch_key),
                last_error = NULL,
                updated_at = NOW()

        """, (user_id, clave, clave))


def mark_reengagement_blocked(user_id, error_text=None):
    """El usuario bloqueó el bot o el chat no existe: no volver a escribirle."""

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO user_reengagement
                (user_id, is_blocked, last_error, updated_at)
            VALUES (%s, TRUE, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                is_blocked = TRUE,
                last_error = EXCLUDED.last_error,
                updated_at = NOW()

        """, (
            user_id,
            str(error_text or "")[:300]
        ))


def mark_reengagement_error(user_id, error_text):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO user_reengagement
                (user_id, last_error, last_sent_at, updated_at)
            VALUES (%s, %s, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                last_error = EXCLUDED.last_error,
                last_sent_at = NOW(),
                updated_at = NOW()

        """, (
            user_id,
            str(error_text or "")[:300]
        ))


def opt_out_reengagement(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO user_reengagement
                (user_id, opted_out, updated_at)
            VALUES (%s, TRUE, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                opted_out = TRUE,
                updated_at = NOW()

        """, (user_id,))


# =========================
# CONTENIDO DEL MENSAJE
# =========================

VISIBLE_GROUP_CONDITIONS = """
    COALESCE(g.is_active, TRUE) = TRUE
    AND COALESCE(g.telegram_group_id, 0) <> 0
    AND (
        COALESCE(g.is_marketplace_visible, FALSE) = TRUE
        OR COALESCE(g.public_visibility, 'start_home') IN ('explore_only', 'both')
    )
"""


def fetch_offer_snapshot(limit=3):
    """
    Foto de la oferta real: cuántas comunidades hay, cuántas son gratis, el
    precio de entrada más bajo y unos ejemplos con su precio. Todo sale de la
    base de datos para que el mensaje nunca prometa algo que no existe.
    """

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT COUNT(*)
            FROM groups g
            WHERE {VISIBLE_GROUP_CONDITIONS}

        """)

        total = (cur.fetchone() or [0])[0] or 0

        cur.execute(f"""

            SELECT COUNT(*)
            FROM groups g
            WHERE {VISIBLE_GROUP_CONDITIONS}
              AND (
                  COALESCE(g.is_free_group, FALSE) = TRUE
                  OR COALESCE(g.is_free, FALSE) = TRUE
              )

        """)

        free_total = (cur.fetchone() or [0])[0] or 0

        # Precio de entrada más bajo (con su moneda, sin mezclar divisas).
        # Con el importe VIGENTE: si hay una oferta viva, el mensaje tiene que
        # decir el precio de la oferta. Decir 9 EUR mientras la tienda vende a
        # 3,60 es perder la venta y quedar mal a la vez.
        from weekly_offer_service import sql_importe_vigente

        cur.execute(f"""

            SELECT {sql_importe_vigente("p")},
                   COALESCE(NULLIF(p.currency, ''), 'EUR')
            FROM plans p
            JOIN groups g ON g.id = p.group_id
            WHERE {VISIBLE_GROUP_CONDITIONS}
              AND COALESCE(p.is_active, TRUE) = TRUE
              AND p.amount IS NOT NULL
              AND p.amount > 0
            ORDER BY 1 ASC
            LIMIT 1

        """)

        cheapest = cur.fetchone()

        cur.execute(f"""

            SELECT g.name,
                   COALESCE(g.category, ''),
                   (COALESCE(g.is_free_group, FALSE) OR COALESCE(g.is_free, FALSE)),
                   (
                       SELECT MIN({sql_importe_vigente("p")})
                       FROM plans p
                       WHERE p.group_id = g.id
                         AND COALESCE(p.is_active, TRUE) = TRUE
                         AND p.amount IS NOT NULL
                         AND p.amount > 0
                   ),
                   (
                       SELECT COALESCE(NULLIF(p.currency, ''), 'EUR')
                       FROM plans p
                       WHERE p.group_id = g.id
                         AND COALESCE(p.is_active, TRUE) = TRUE
                         AND p.amount IS NOT NULL
                         AND p.amount > 0
                       ORDER BY p.amount ASC
                       LIMIT 1
                   )
            FROM groups g
            WHERE {VISIBLE_GROUP_CONDITIONS}
            ORDER BY g.created_at DESC
            LIMIT %s

        """, (int(limit),))

        examples = cur.fetchall() or []


        # La mejor oferta viva del escaparate: es con lo que hay que empezar
        # el mensaje. Un aviso que entierra el -60% en la tercera línea es un
        # aviso sin descuento.
        cur.execute(f"""

            SELECT po.percent, po.ends_at, g.name
            FROM plan_offers po
            JOIN plans p ON p.id = po.plan_id
            JOIN groups g ON g.id = p.group_id
            WHERE {VISIBLE_GROUP_CONDITIONS}
              AND po.user_id IS NULL
              AND po.starts_at <= NOW()
              AND po.ends_at > NOW()
              AND COALESCE(NULLIF(po.stripe_price_id, ''), '') <> ''
              AND COALESCE(p.is_active, TRUE) = TRUE
            ORDER BY po.percent DESC, po.ends_at ASC
            LIMIT 1

        """)

        mejor_oferta = cur.fetchone()


    return {
        "total": total,
        "free_total": free_total,
        "cheapest_amount": cheapest[0] if cheapest else None,
        "cheapest_currency": cheapest[1] if cheapest else None,
        "examples": examples,
        "offer_percent": mejor_oferta[0] if mejor_oferta else None,
        "offer_ends_at": mejor_oferta[1] if mejor_oferta else None,
        "offer_group": mejor_oferta[2] if mejor_oferta else None,
    }


def format_price(amount, currency):
    """El dinero se escribe en UN sitio. Aquí había una tercera manera, y con
    los céntimos de una oferta se notaba: «3,6 EUR» en vez de «3,60 EUR»."""

    if amount is None:

        return None

    try:

        from start_offer_service import formato_importe

        escrito = formato_importe(amount, currency)

        if escrito:
            return escrito

    except Exception:

        pass


    try:

        value = float(amount)

    except Exception:

        return None


    text = f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")

    return f"{text} {currency or 'EUR'}"


def describe_catalog(offer):
    """Una línea honesta con el tamaño del catálogo y el precio de entrada."""

    total = offer.get("total") or 0
    price = format_price(
        offer.get("cheapest_amount"),
        offer.get("cheapest_currency")
    )

    if not total:

        return "Tenemos comunidades privadas disponibles en el bot."


    noun = "comunidad" if total == 1 else "comunidades"
    plural = "" if total == 1 else "s"
    line = f"Hay *{total} {noun}* disponible{plural}"


    if price:

        line += f", desde *{price}*"


    return line + "."


def describe_examples(offer, max_items=3):

    lines = []

    for row in (offer.get("examples") or [])[:max_items]:

        name = row[0] or "Comunidad"
        category = row[1] if len(row) > 1 else ""
        is_free = bool(row[2]) if len(row) > 2 else False
        amount = row[3] if len(row) > 3 else None
        currency = row[4] if len(row) > 4 else None

        detail = ""

        if is_free:

            detail = " — gratis"

        else:

            price = format_price(amount, currency)

            if price:

                detail = f" — {price}"


        cat = f" ({category})" if category else ""
        lines.append(f"• {name}{cat}{detail}")


    return lines


def cabecera_de_oferta(offer):
    """«🔥 -60% esta semana · quedan 3 días». None si no hay oferta viva.

    Va la PRIMERA línea de cualquier aviso: es lo único que hace abrir un
    mensaje de un bot al que ya se le ha dicho que no. Un -60% enterrado en la
    tercera línea es un mensaje sin descuento.
    """

    percent = (offer or {}).get("offer_percent")

    if not percent:
        return None

    partes = [f"🔥 *-{int(percent)}% esta semana*"]

    from weekly_offer_service import frase_cuenta_atras

    cuenta = frase_cuenta_atras((offer or {}).get("offer_ends_at"))

    if cuenta:
        partes.append(f"· {cuenta}")

    return " ".join(partes)


def build_relaunch_text(offer=None):
    """El aviso extra: empieza reconociendo lo que pasó.

    A esta persona ya se le escribieron seis veces cuando el bot no podía
    cobrar. Volver con el mismo «✨ esto es lo que puedes conseguir» sería el
    séptimo mensaje idéntico. Lo único que justifica escribir otra vez es que
    algo cambió de verdad, así que eso es lo que dice, en ese orden y sin
    adornos.
    """

    offer = offer or fetch_offer_snapshot()

    cabecera = cabecera_de_oferta(offer)

    lineas = ([cabecera, ""] if cabecera else []) + [
        "🔧 Te escribí hace tiempo y no funcionaba",
        "",
        "Siendo sincero: cuando te avisé, el botón de pagar de este bot "
        "estaba roto. Quien lo intentaba se encontraba un error.",
        "",
        "Ya está arreglado y comprobado.",
        "",
        describe_catalog(offer),
    ]

    ejemplos = describe_examples(offer)

    if ejemplos:

        lineas.append("")
        lineas.extend(ejemplos)

    lineas += [
        "",
        "Pagas con tarjeta y el enlace de entrada te llega al momento.",
        "",
        "Si no te interesa, pulsa «No quiero más avisos» aquí abajo y no "
        "vuelvo a escribirte.",
    ]

    return "\n".join(lineas)


def build_reengagement_text(offer=None, variant=0, con_ofertas=False,
                            relanzamiento=False):
    """
    Texto del aviso. Rota entre variantes según cuántos avisos ha recibido ya
    la persona: repetir seis veces el mismo mensaje quema al usuario y hace que
    lo perciba como spam. Todos los datos (número de comunidades, precios,
    ejemplos) salen de la base de datos.
    """

    offer = offer or fetch_offer_snapshot()

    if relanzamiento:
        return build_relaunch_text(offer)

    variant = int(variant or 0) % 4

    catalog = describe_catalog(offer)
    examples = describe_examples(offer)
    free_total = offer.get("free_total") or 0
    cheapest = format_price(
        offer.get("cheapest_amount"),
        offer.get("cheapest_currency")
    )

    lines = []


    # 1er aviso: qué hay y cómo funciona
    if variant == 0:

        lines.append("✨ Esto es lo que puedes conseguir aquí")
        lines.append("")
        lines.append(catalog)

        if examples:

            lines.append("")
            lines.extend(examples)

        lines.append("")
        lines.append("*Cómo funciona* (2 minutos):")
        lines.append("1️⃣ Eliges la comunidad que te interesa.")
        lines.append("2️⃣ Pagas con tarjeta de forma segura (Stripe).")
        lines.append("3️⃣ Recibes al instante tu enlace de acceso privado.")
        lines.append("")
        lines.append("🔒 Enlace personal y de un solo uso.")
        lines.append("⏱ Acceso automático, sin esperas.")
        lines.append("🛟 Soporte directo en el bot.")


    # 2º aviso: al grano con el precio
    elif variant == 1:

        lines.append("💳 Entrar cuesta menos de lo que crees")
        lines.append("")
        lines.append(catalog)

        if cheapest:

            lines.append("")
            lines.append(
                f"Por *{cheapest}* ya entras a una comunidad privada, "
                "con acceso inmediato."
            )

        if examples:

            lines.append("")
            lines.extend(examples)

        lines.append("")
        lines.append("Pagas, recibes tu enlace y entras. Sin más pasos.")


    # 3er aviso: puerta de entrada sin coste / lo fácil que es
    elif variant == 2:

        if free_total:

            lines.append("🎁 Puedes empezar sin pagar nada")
            lines.append("")
            lines.append(catalog)
            lines.append("")
            if free_total == 1:

                lines.append(
                    "Hay *1 comunidad* de acceso gratuito: "
                    "échale un ojo y decide después."
                )

            else:

                lines.append(
                    f"Hay *{free_total} comunidades* de acceso gratuito: "
                    "míralas y decide después."
                )

        else:

            lines.append("👀 Échale un ojo sin compromiso")
            lines.append("")
            lines.append(catalog)
            lines.append("")
            lines.append(
                "Puedes ver el catálogo completo sin pagar y decidir con calma."
            )

        if examples:

            lines.append("")
            lines.extend(examples)

        lines.append("")
        lines.append("🛟 Si tienes dudas, escríbenos por el bot.")


    # 4º aviso y siguientes: corto y sin presión
    else:

        lines.append("👋 Seguimos aquí cuando quieras")
        lines.append("")
        lines.append(catalog)
        lines.append("")
        lines.append(
            "Si te interesa, el catálogo está a un toque. "
            "Y si no, puedes desactivar estos avisos abajo."
        )


    lines.append("")

    if con_ofertas:

        # Debajo hay botones de COMPRA con su precio, no un catálogo: mandar a
        # «mirar lo disponible» después de ponerle el precio delante es pedirle
        # que empiece de nuevo la búsqueda que ya has hecho tú por él.
        lines.append("Elige la tuya y entras en cuanto se confirme el pago 👇")

    else:

        lines.append("Mira lo que hay disponible 👇")

    texto = "\n".join(lines)

    # La oferta manda: si la hay, encabeza el aviso sea cual sea la variante.
    cabecera = cabecera_de_oferta(offer)

    if cabecera:
        texto = cabecera + "\n\n" + texto

    return texto


# Cuántas ofertas caben en un aviso: tres. Un aviso con seis botones de compra
# no es una oferta, es un catálogo, y un catálogo no se lee en una notificación.
REENGAGEMENT_MAX_OFFERS = int(
    os.environ.get("REENGAGEMENT_MAX_OFFERS", "3")
)


def fetch_reengagement_offers(user_id):
    """Lo que se le puede VENDER a esta persona, de lo más barato a lo más caro.

    Se le quitan dos cosas a la lista de /start: las comunidades en las que ya
    está dentro (ofrecerle comprar lo que tiene es la forma más rápida de
    perder credibilidad) y las que no tienen precio legible, porque un botón
    de compra sin precio es el problema que este cambio viene a arreglar.

    Ante cualquier error, lista vacía: el aviso se envía con el botón del
    catálogo de siempre. Un aviso sin salida sería peor que un aviso genérico.
    """

    if not user_id:
        return []

    try:

        from start_offer_service import fetch_sellable_communities

        return [
            oferta
            for oferta in fetch_sellable_communities(
                user_id, limit=REENGAGEMENT_MAX_OFFERS
            )
            if not oferta["ya_dentro"] and oferta["precio"]
        ][:REENGAGEMENT_MAX_OFFERS]

    except Exception as e:

        print("Reenganche: error montando la oferta, se usa el listado:", e)

        return []


def build_reengagement_keyboard(user_id=None, ofertas=None):
    """Los botones del aviso: la compra primero, con su precio.

    El texto del aviso ya decía «desde 15 EUR» y el botón llevaba a un
    LISTADO: después de leer el precio quedaban tres toques más hasta pagar.
    Ahora cada comunidad vendible es un botón con su precio y, con un solo
    plan, lleva directo al enlace de pago.

    Sin user_id o sin nada que ofrecer, los botones de siempre: un aviso sin
    salida sería peor que el listado.

    El botón de no recibir más avisos está SIEMPRE, en cualquier variante:
    quitarlo para dejar hueco a otra oferta es cómo se gana un bloqueo.
    """

    filas = []

    if ofertas is None:
        ofertas = fetch_reengagement_offers(user_id)

    try:

        from start_offer_service import callback_de_oferta, etiqueta_de_oferta

        for oferta in ofertas:

            filas.append([InlineKeyboardButton(
                etiqueta_de_oferta(oferta),
                callback_data=callback_de_oferta(oferta)
            )])

    except Exception as e:

        print("Reenganche: error montando los botones de compra:", e)
        filas = []


    if not filas:

        filas.append([InlineKeyboardButton(
            "🔎 Ver comunidades disponibles",
            callback_data="start_explore_groups"
        )])


    filas.append([InlineKeyboardButton(
        "🛟 Tengo una duda",
        callback_data="public_support"
    )])

    filas.append([InlineKeyboardButton(
        "🔔 No quiero más avisos",
        callback_data=CALLBACK_REENGAGEMENT_STOP
    )])

    return InlineKeyboardMarkup(filas)


# =========================
# ENVÍO PROGRAMADO
# =========================

def is_blocked_error(error):

    text = str(error or "").lower()

    return any(
        marker in text
        for marker in (
            "bot was blocked",
            "user is deactivated",
            "chat not found",
            "bot can't initiate conversation",
            "peer_id_invalid",
            "forbidden"
        )
    )


async def process_reengagement_batch(context):
    """Job programado: escribe a una tanda de usuarios sin compras."""

    summary = {"targets": 0, "sent": 0, "blocked": 0, "failed": 0}

    if not REENGAGEMENT_ENABLED:

        return summary


    # Antes de mirar a quién escribir: ¿hay algo que ofrecerle y se le puede
    # cobrar? Si no, esta tanda no sale. Es la lección más cara de todo esto.
    ok_para_escribir, motivo = merece_la_pena_escribir()

    if not ok_para_escribir:

        global _logged_no_vale_la_pena

        if not _logged_no_vale_la_pena:

            _logged_no_vale_la_pena = True

            print("Reenganche: no se escribe a nadie —", motivo)

            log_event(
                "reengagement_paused",
                category="marketing",
                severity="warning",
                scope="global",
                message="Campaña de reenganche detenida: no hay nada vendible.",
                metadata={"motivo": motivo},
            )

        return summary


    try:

        targets = fetch_reengagement_targets()

    except Exception as e:

        print("Reenganche: error seleccionando destinatarios:", e)
        return summary


    if not targets:

        # Silencioso en la operación normal, pero deja rastro la primera vez
        # para poder distinguir "no toca a nadie" de "no encuentra a nadie".
        global _logged_empty_run

        if not _logged_empty_run:

            _logged_empty_run = True

            # Con el desglose: «306 candidatos» y cero envíos se leía igual
            # tanto si la campaña estaba agotada como si simplemente no tocaba
            # todavía, y son dos cosas con arreglos distintos.
            print(
                "Reenganche: ninguna persona pendiente en esta pasada — "
                + explica_por_que_no_hay_nadie()
            )


        return summary


    summary["targets"] = len(targets)

    try:

        offer = fetch_offer_snapshot()

    except Exception:

        offer = None

    texts_by_variant = {}

    clave_de_relanzamiento = (
        REENGAGEMENT_RELAUNCH_KEY if relanzamiento_activo() else ""
    )

    for user_id, already_sent in targets:

        # Quien ya gastó el tope solo puede estar aquí por el relanzamiento.
        es_relanzamiento = bool(clave_de_relanzamiento) and (
            int(already_sent or 0) >= REENGAGEMENT_MAX_MESSAGES
        )

        # La oferta se lee POR PERSONA, no una vez para toda la tanda: excluye
        # las comunidades en las que ya está dentro, así que una lista
        # compartida le ofrecería a alguien comprar lo que ya tiene.
        ofertas = fetch_reengagement_offers(user_id)
        keyboard = build_reengagement_keyboard(user_id=user_id, ofertas=ofertas)

        # Cada persona recibe una variante distinta según los avisos previos.
        variant = int(already_sent or 0) % 4

        # La clave lleva el flag porque el texto CIERRA distinto según lo que
        # tenga debajo: con botones de compra no se le manda a mirar nada.
        clave = (variant, bool(ofertas), es_relanzamiento)

        if clave not in texts_by_variant:

            texts_by_variant[clave] = build_reengagement_text(
                offer, variant, con_ofertas=bool(ofertas),
                relanzamiento=es_relanzamiento
            )


        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=texts_by_variant[clave],
                parse_mode="Markdown",
                reply_markup=keyboard
            )

            mark_reengagement_sent(
                user_id,
                relaunch_key=clave_de_relanzamiento if es_relanzamiento else None
            )

            summary["sent"] += 1

            if es_relanzamiento:
                summary["relanzados"] = summary.get("relanzados", 0) + 1

        except Exception as e:

            if is_blocked_error(e):

                mark_reengagement_blocked(user_id, e)
                summary["blocked"] += 1

            else:

                mark_reengagement_error(user_id, e)
                summary["failed"] += 1


        await asyncio.sleep(REENGAGEMENT_SEND_DELAY_SECONDS)


    print(
        "Reenganche:",
        f"{summary['sent']} enviados,",
        f"{summary['blocked']} bloqueados,",
        f"{summary['failed']} fallidos"
        # Los del relanzamiento aparte: son gente a la que se le había dejado
        # de escribir, y saber cuántos han vuelto a recibir algo es el único
        # número que dice si esa excepción sirvió para algo.
        + (f", de ellos {summary['relanzados']} del relanzamiento"
           if summary.get("relanzados") else "")
    )

    if summary["sent"] or summary["blocked"] or summary["failed"]:

        log_event(
            "reengagement_batch_sent",
            category="marketing",
            severity="info",
            scope="global",
            message="Tanda de reenganche a usuarios sin compras.",
            metadata=summary
        )


    return summary
