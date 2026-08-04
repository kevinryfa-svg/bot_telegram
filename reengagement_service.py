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

            SELECT DISTINCT e.user_id
            FROM bot_user_events e
            LEFT JOIN user_reengagement r
                   ON r.user_id = e.user_id
            WHERE e.user_id IS NOT NULL
              AND e.user_id > 0
              AND e.user_id <> %s

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

        return [row[0] for row in cur.fetchall() if row[0]]


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

def fetch_offer_snapshot(limit=4):
    """Comunidades realmente disponibles, para que el mensaje nunca mienta."""

    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*)
            FROM groups
            WHERE COALESCE(is_active, TRUE) = TRUE
              AND COALESCE(telegram_group_id, 0) <> 0
              AND (
                  COALESCE(is_marketplace_visible, FALSE) = TRUE
                  OR COALESCE(public_visibility, 'start_home') IN ('explore_only', 'both')
              )

        """)

        total = (cur.fetchone() or [0])[0] or 0

        cur.execute("""

            SELECT name,
                   COALESCE(category, ''),
                   COALESCE(is_free_group, FALSE) OR COALESCE(is_free, FALSE)
            FROM groups
            WHERE COALESCE(is_active, TRUE) = TRUE
              AND COALESCE(telegram_group_id, 0) <> 0
              AND (
                  COALESCE(is_marketplace_visible, FALSE) = TRUE
                  OR COALESCE(public_visibility, 'start_home') IN ('explore_only', 'both')
              )
            ORDER BY created_at DESC
            LIMIT %s

        """, (int(limit),))

        examples = cur.fetchall() or []


    return {
        "total": total,
        "examples": examples
    }


def build_reengagement_text(offer=None):

    offer = offer or fetch_offer_snapshot()
    total = offer.get("total") or 0
    examples = offer.get("examples") or []

    lines = ["✨ Esto es lo que puedes conseguir aquí"]
    lines.append("")

    if total:

        noun = "comunidad" if total == 1 else "comunidades"

        lines.append(
            f"Ahora mismo hay *{total} {noun}* disponible"
            f"{'' if total == 1 else 's'} en el bot."
        )

    else:

        lines.append(
            "Tenemos comunidades privadas disponibles en el bot."
        )

    if examples:

        lines.append("")
        lines.append("Algunas de ellas:")

        for name, category, is_free in examples:

            tag = " · gratis" if is_free else ""
            cat = f" ({category})" if category else ""
            lines.append(f"• {name or 'Comunidad'}{cat}{tag}")

    lines.append("")
    lines.append("*Cómo funciona* (2 minutos):")
    lines.append("1️⃣ Eliges la comunidad que te interesa.")
    lines.append("2️⃣ Pagas de forma segura con tarjeta (Stripe).")
    lines.append("3️⃣ Recibes al instante tu enlace de acceso privado.")
    lines.append("")
    lines.append("🔒 Tu enlace es personal y de un solo uso.")
    lines.append("⏱ El acceso se activa automáticamente, sin esperas.")
    lines.append("🛟 Si algo no encaja, tienes soporte directo en el bot.")
    lines.append("")
    lines.append("Échale un ojo y quédate solo si te convence 👇")

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

        return summary


    summary["targets"] = len(targets)

    try:

        offer = fetch_offer_snapshot()

    except Exception:

        offer = None

    text = build_reengagement_text(offer)
    keyboard = build_reengagement_keyboard()

    for user_id in targets:

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=text,
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
