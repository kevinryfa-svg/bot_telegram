import os
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import conn
from audit_log_service import log_event
from i18n_service import DEFAULT_LANGUAGE, load_user_language, t
from renewal_service import fetch_group_entry_price, format_amount, is_unreachable_error


# =========================
# PAGOS ABANDONADOS
# =========================
# Cuando alguien abre un checkout se registra una transacción 'pending'. Si no
# completa el pago, esa fila se queda ahí para siempre y nadie le dice nada:
# son ventas casi hechas que se pierden en silencio. Aquí se le ofrece retomar.

ABANDONED_AFTER_HOURS = float(
    os.environ.get("ABANDONED_AFTER_HOURS", "2")
)

# No se persigue un intento antiguo: a los pocos días ya no tiene sentido.
ABANDONED_MAX_AGE_DAYS = int(
    os.environ.get("ABANDONED_MAX_AGE_DAYS", "7")
)

ABANDONED_BATCH_SIZE = int(
    os.environ.get("ABANDONED_BATCH_SIZE", "30")
)

ABANDONED_SEND_DELAY_SECONDS = float(
    os.environ.get("ABANDONED_SEND_DELAY_SECONDS", "0.5")
)

ABANDONED_ENABLED = os.environ.get(
    "ABANDONED_ENABLED",
    "true"
).strip().lower() not in ("0", "false", "no", "off")


PAID_STATUSES = ("paid", "completed", "succeeded")


# =========================
# SELECCIÓN
# =========================

def fetch_abandoned_checkouts(limit=None):
    """
    Intentos de pago sin completar. Se excluye a quien:
      - completó ese mismo checkout (mismo external_checkout_id),
      - pagó por otra vía para ese grupo después,
      - ya tiene acceso activo,
      - está baneado o se dio de baja de avisos,
      - ya recibió el recordatorio de ese intento.
    """

    limit = int(limit or ABANDONED_BATCH_SIZE)

    with conn.cursor() as cur:

        cur.execute("""

            SELECT t.id,
                   t.user_id,
                   t.group_id,
                   COALESCE(g.name, 'la comunidad'),
                   t.created_at
            FROM payment_transactions t
            JOIN groups g ON g.id = t.group_id
            WHERE LOWER(COALESCE(t.status, '')) = 'pending'
              AND t.user_id IS NOT NULL
              AND t.group_id IS NOT NULL
              AND COALESCE(g.is_active, TRUE) = TRUE

              AND t.created_at <= NOW() - (%(hours)s || ' hours')::interval
              AND t.created_at >= NOW() - (%(days)s || ' days')::interval

              AND NOT EXISTS (
                  SELECT 1
                  FROM payment_transactions p
                  WHERE p.external_checkout_id = t.external_checkout_id
                    AND p.external_checkout_id IS NOT NULL
                    AND LOWER(COALESCE(p.status, '')) = ANY(%(paid)s)
              )

              AND NOT EXISTS (
                  SELECT 1
                  FROM payment_transactions p2
                  WHERE p2.user_id = t.user_id
                    AND p2.group_id = t.group_id
                    AND LOWER(COALESCE(p2.status, '')) = ANY(%(paid)s)
                    AND p2.created_at >= t.created_at
              )

              AND NOT EXISTS (
                  SELECT 1
                  FROM users u
                  WHERE u.user_id = t.user_id
                    AND u.group_id = t.group_id
                    AND (
                        COALESCE(u.subscription_active, FALSE) = TRUE
                        OR (u.expiration IS NOT NULL AND u.expiration > NOW())
                    )
              )

              AND NOT EXISTS (
                  SELECT 1 FROM banned_users b WHERE b.user_id = t.user_id
              )

              AND NOT EXISTS (
                  SELECT 1
                  FROM user_reengagement r
                  WHERE r.user_id = t.user_id
                    AND (
                        COALESCE(r.opted_out, FALSE) = TRUE
                        OR COALESCE(r.is_blocked, FALSE) = TRUE
                    )
              )

              AND NOT EXISTS (
                  SELECT 1
                  FROM abandoned_checkout_reminders a
                  WHERE a.transaction_id = t.id
              )

            ORDER BY t.created_at DESC
            LIMIT %(limit)s

        """, {
            "hours": ABANDONED_AFTER_HOURS,
            "days": ABANDONED_MAX_AGE_DAYS,
            "paid": list(PAID_STATUSES),
            "limit": limit
        })

        return cur.fetchall() or []


def mark_abandoned_reminder_sent(transaction_id, user_id, group_id):
    """True si quedó registrado (y por tanto toca enviarlo)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO abandoned_checkout_reminders
                    (transaction_id, user_id, group_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (transaction_id) DO NOTHING

            """, (
                transaction_id,
                user_id,
                group_id
            ))

            return cur.rowcount > 0

    except Exception as e:

        print("Pago abandonado: error registrando recordatorio:", e)
        return False


# =========================
# MENSAJE
# =========================

def build_abandoned_text(group_name, price=None, language=DEFAULT_LANGUAGE):

    price_text = format_amount(price[0], price[1]) if price else None

    lines = [
        t("abandoned.title", language),
        "",
        t("abandoned.body", language, group=group_name)
    ]


    if price_text:

        lines.append("")
        lines.append(t("abandoned.price", language, price=price_text))


    lines.extend([
        "",
        t("abandoned.footer", language),
        "",
        t("abandoned.help", language)
    ])

    return "\n".join(lines)


def build_abandoned_keyboard(group_id, language=DEFAULT_LANGUAGE):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("button.resume_payment", language),
            callback_data=f"marketplace_group_{group_id}"
        )],
        [InlineKeyboardButton(
            t("button.i_had_a_problem", language),
            callback_data="public_support"
        )]
    ])


# =========================
# ENVÍO PROGRAMADO
# =========================

async def process_abandoned_checkouts(context):

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}


    if not ABANDONED_ENABLED:

        return summary


    try:

        rows = fetch_abandoned_checkouts()

    except Exception as e:

        print("Pago abandonado: error seleccionando intentos:", e)
        return summary


    summary["targets"] = len(rows)


    for transaction_id, user_id, group_id, group_name, _created_at in rows:

        if not mark_abandoned_reminder_sent(transaction_id, user_id, group_id):

            summary["skipped"] += 1
            continue


        price = fetch_group_entry_price(group_id)
        language = load_user_language(user_id)

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=build_abandoned_text(
                    group_name,
                    price=price,
                    language=language
                ),
                reply_markup=build_abandoned_keyboard(
                    group_id,
                    language=language
                )
            )

            summary["sent"] += 1

        except Exception as e:

            summary["failed"] += 1

            if not is_unreachable_error(e):

                print(
                    f"Pago abandonado: no se pudo avisar a {user_id}:",
                    str(e)[:200]
                )


        await asyncio.sleep(ABANDONED_SEND_DELAY_SECONDS)


    if summary["sent"] or summary["failed"]:

        print(
            "Pagos abandonados:",
            f"{summary['sent']} recordatorios enviados,",
            f"{summary['failed']} fallidos"
        )

        log_event(
            "abandoned_checkout_reminders_sent",
            category="billing",
            severity="info",
            scope="global",
            message="Recordatorios de pagos sin completar.",
            metadata=summary
        )


    return summary
