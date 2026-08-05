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

REENGAGEMENT_INTERVAL_DAYS = int(
    os.environ.get("REENGAGEMENT_INTERVAL_DAYS", "3")
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


CALLBACK_REENGAGEMENT_STOP = "reengagement_stop"


# =========================
# SELECCIÓN DE DESTINATARIOS
# =========================

def fetch_reengagement_targets(limit=None):
    """
    Usuarios que han usado el bot y NO han contratado nada:
    sin pagos, sin acceso activo, no baneados, no admins,
    no dados de baja, sin haber bloqueado el bot y respetando
    el intervalo y el tope de mensajes.
    """

    limit = int(limit or REENGAGEMENT_BATCH_SIZE)

    with conn.cursor() as cur:

        cur.execute("""

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
                   COALESCE(r.sent_count, 0)
            FROM visitors e
            LEFT JOIN user_reengagement r
                   ON r.user_id = e.user_id
            WHERE e.user_id <> %s

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

              AND COALESCE(r.opted_out, FALSE) = FALSE
              AND COALESCE(r.is_blocked, FALSE) = FALSE
              AND COALESCE(r.sent_count, 0) < %s
              AND (
                  r.last_sent_at IS NULL
                  OR r.last_sent_at < NOW() - (%s || ' days')::interval
              )

            ORDER BY 1
            LIMIT %s

        """, (
            int(ADMIN_ID),
            REENGAGEMENT_MAX_MESSAGES,
            REENGAGEMENT_INTERVAL_DAYS,
            limit
        ))

        # (user_id, avisos_ya_recibidos) — el contador elige la variante.
        return [
            (row[0], int(row[1] or 0))
            for row in cur.fetchall()
            if row[0]
        ]


_logged_empty_run = False


def count_reengagement_candidates():
    """Cuántas personas cumplen el perfil (visitó y no compró), sin filtrar
    por intervalo ni tope: sirve para saber el alcance real de la campaña."""

    with conn.cursor() as cur:

        cur.execute("""

            WITH visitors AS (
                SELECT DISTINCT user_id
                FROM bot_user_events
                WHERE user_id IS NOT NULL AND user_id > 0

                UNION

                SELECT DISTINCT user_id
                FROM users
                WHERE user_id IS NOT NULL AND user_id > 0
            )
            SELECT COUNT(*)
            FROM visitors e
            WHERE e.user_id <> %s

              AND NOT EXISTS (
                  SELECT 1 FROM payments p
                  WHERE p.user_id = e.user_id
                    AND LOWER(COALESCE(p.status, '')) IN ('paid', 'completed', 'succeeded')
              )

              AND NOT EXISTS (
                  SELECT 1 FROM payment_transactions t
                  WHERE t.user_id = e.user_id
                    AND LOWER(COALESCE(t.status, '')) IN ('paid', 'completed', 'succeeded')
              )

              AND NOT EXISTS (
                  SELECT 1 FROM users u
                  WHERE u.user_id = e.user_id
                    AND (
                        COALESCE(u.subscription_active, FALSE) = TRUE
                        OR (u.expiration IS NOT NULL AND u.expiration > NOW())
                    )
              )

              AND NOT EXISTS (
                  SELECT 1 FROM banned_users b WHERE b.user_id = e.user_id
              )

              AND NOT EXISTS (
                  SELECT 1 FROM admins a WHERE a.user_id = e.user_id
              )

        """, (int(ADMIN_ID),))

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

def mark_reengagement_sent(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO user_reengagement
                (user_id, sent_count, last_sent_at, updated_at)
            VALUES (%s, 1, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                sent_count = COALESCE(user_reengagement.sent_count, 0) + 1,
                last_sent_at = NOW(),
                last_error = NULL,
                updated_at = NOW()

        """, (user_id,))


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

        # Precio de entrada más bajo (con su moneda, sin mezclar divisas)
        cur.execute(f"""

            SELECT p.amount,
                   COALESCE(NULLIF(p.currency, ''), 'EUR')
            FROM plans p
            JOIN groups g ON g.id = p.group_id
            WHERE {VISIBLE_GROUP_CONDITIONS}
              AND COALESCE(p.is_active, TRUE) = TRUE
              AND p.amount IS NOT NULL
              AND p.amount > 0
            ORDER BY p.amount ASC
            LIMIT 1

        """)

        cheapest = cur.fetchone()

        cur.execute(f"""

            SELECT g.name,
                   COALESCE(g.category, ''),
                   (COALESCE(g.is_free_group, FALSE) OR COALESCE(g.is_free, FALSE)),
                   (
                       SELECT MIN(p.amount)
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


    return {
        "total": total,
        "free_total": free_total,
        "cheapest_amount": cheapest[0] if cheapest else None,
        "cheapest_currency": cheapest[1] if cheapest else None,
        "examples": examples
    }


def format_price(amount, currency):

    if amount is None:

        return None


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


def build_reengagement_text(offer=None, variant=0):
    """
    Texto del aviso. Rota entre variantes según cuántos avisos ha recibido ya
    la persona: repetir seis veces el mismo mensaje quema al usuario y hace que
    lo perciba como spam. Todos los datos (número de comunidades, precios,
    ejemplos) salen de la base de datos.
    """

    offer = offer or fetch_offer_snapshot()
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
    lines.append("Mira lo que hay disponible 👇")

    return "\n".join(lines)


def build_reengagement_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔎 Ver comunidades disponibles",
            callback_data="start_explore_groups"
        )],
        [InlineKeyboardButton(
            "🛟 Tengo una duda",
            callback_data="public_support"
        )],
        [InlineKeyboardButton(
            "🔔 No quiero más avisos",
            callback_data=CALLBACK_REENGAGEMENT_STOP
        )]
    ])


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

            try:

                candidates = count_reengagement_candidates()

            except Exception:

                candidates = None

            print(
                "Reenganche: ninguna persona pendiente en esta pasada "
                f"(candidatos sin compras en total: {candidates})."
            )


        return summary


    summary["targets"] = len(targets)

    try:

        offer = fetch_offer_snapshot()

    except Exception:

        offer = None

    keyboard = build_reengagement_keyboard()
    texts_by_variant = {}

    for user_id, already_sent in targets:

        # Cada persona recibe una variante distinta según los avisos previos.
        variant = int(already_sent or 0) % 4

        if variant not in texts_by_variant:

            texts_by_variant[variant] = build_reengagement_text(offer, variant)


        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=texts_by_variant[variant],
                parse_mode="Markdown",
                reply_markup=keyboard
            )

            mark_reengagement_sent(user_id)
            summary["sent"] += 1

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
