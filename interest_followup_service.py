"""
Seguimiento a quien miró una comunidad y no compró.

El bot ya escribía en dos momentos: a quien nunca ha comprado nada
(reengagement_service) y a quien empezó un pago y no lo terminó
(abandoned_checkout_service). Entre esos dos casos quedaba el hueco más grande
del embudo: alguien abre la ficha de una comunidad concreta, ve el precio, y se
va sin llegar a pulsar comprar. Es la persona con más intención de todas las que
no han pagado, y nadie le decía nada.

Ahora la apertura de una ficha se registra (community_viewed) y este servicio
escribe una sola vez por comunidad, con el precio y un botón directo.

Reglas para que esto sea un recordatorio y no spam:
  - un único aviso por persona y comunidad, para siempre;
  - nada antes de unas horas: si acaba de mirarlo, está mirándolo;
  - nada si ya tiene acceso, si ya empezó a pagar (de eso se encarga el aviso de
    pago sin completar), si está baneado, o si pidió no recibir más mensajes;
  - se respeta el mismo opt-out que el resto de avisos, así que "no me escribas
    más" vale para todo.
"""

import asyncio
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import conn
from audit_log_service import log_event
from i18n_service import DEFAULT_LANGUAGE, load_user_language, t
from renewal_service import (
    fetch_group_entry_price,
    format_amount,
    is_unreachable_error
)


# =========================
# CONFIGURACIÓN
# =========================

INTEREST_ENABLED = os.environ.get(
    "INTEREST_FOLLOWUP_ENABLED", "true"
).strip().lower() not in ("0", "false", "no")

# Ni tan pronto que interrumpa a quien está decidiendo, ni tan tarde que ya se
# haya olvidado de qué iba.
INTEREST_AFTER_HOURS = float(
    os.environ.get("INTEREST_FOLLOWUP_AFTER_HOURS", "6")
)

# Pasada una semana, escribir sobre algo que miró de pasada es ruido.
INTEREST_MAX_AGE_DAYS = int(
    os.environ.get("INTEREST_FOLLOWUP_MAX_AGE_DAYS", "7")
)

INTEREST_BATCH_SIZE = int(
    os.environ.get("INTEREST_FOLLOWUP_BATCH_SIZE", "20")
)

INTEREST_SEND_DELAY_SECONDS = float(
    os.environ.get("INTEREST_FOLLOWUP_SEND_DELAY_SECONDS", "0.5")
)

PAID_STATUSES = ("paid", "completed", "succeeded")


# =========================
# A QUIÉN ESCRIBIR
# =========================

def fetch_interested_users(limit=None):
    """
    Personas que abrieron la ficha de una comunidad y no compraron.

    Se descarta a quien ya tiene acceso, a quien empezó un pago (ese caso lo
    cubre el aviso de pago sin completar), a quien está baneado en esa
    comunidad, a quien pidió no recibir más mensajes y a quien ya recibió este
    aviso para esa misma comunidad.
    """

    limit = limit or INTEREST_BATCH_SIZE

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT e.user_id,
                       e.group_id,
                       g.name,
                       MAX(e.created_at) AS visto

                FROM bot_user_events e

                JOIN groups g
                ON g.id = e.group_id

                WHERE e.event_type = 'community_viewed'
                  AND e.group_id IS NOT NULL
                  AND e.user_id IS NOT NULL
                  AND g.is_active = TRUE
                  AND COALESCE(g.is_free_group, FALSE) = FALSE
                  AND COALESCE(g.is_free, FALSE) = FALSE

                  -- Ya tiene acceso: no hay nada que ofrecerle.
                  AND NOT EXISTS (
                      SELECT 1 FROM users u
                      WHERE u.user_id = e.user_id
                        AND u.group_id = e.group_id
                        AND COALESCE(u.subscription_active, FALSE) = TRUE
                        AND (u.expiration IS NULL OR u.expiration > NOW())
                  )

                  -- Ya pagó alguna vez por esta comunidad.
                  AND NOT EXISTS (
                      SELECT 1 FROM payments p
                      WHERE p.user_id = e.user_id
                        AND p.group_id = e.group_id
                        AND LOWER(COALESCE(p.status, '')) = ANY(%(paid)s)
                  )

                  -- Empezó un pago: de eso avisa el recordatorio de pago sin
                  -- completar, y dos mensajes por lo mismo sobran.
                  AND NOT EXISTS (
                      SELECT 1 FROM payment_transactions tx
                      WHERE tx.user_id = e.user_id
                        AND tx.group_id = e.group_id
                  )

                  AND NOT EXISTS (
                      SELECT 1 FROM banned_users b
                      WHERE b.user_id = e.user_id
                        AND b.group_id = e.group_id
                  )

                  -- Mismo opt-out que el resto de avisos del bot.
                  AND NOT EXISTS (
                      SELECT 1 FROM user_reengagement r
                      WHERE r.user_id = e.user_id
                        AND (
                            COALESCE(r.opted_out, FALSE) = TRUE
                            OR COALESCE(r.is_blocked, FALSE) = TRUE
                        )
                  )

                  -- Un único aviso por persona y comunidad.
                  AND NOT EXISTS (
                      SELECT 1 FROM interest_followups f
                      WHERE f.user_id = e.user_id
                        AND f.group_id = e.group_id
                  )

                GROUP BY e.user_id, e.group_id, g.name

                HAVING MAX(e.created_at) < NOW() - (%(horas)s || ' hours')::INTERVAL
                   AND MAX(e.created_at) > NOW() - (%(dias)s || ' days')::INTERVAL

                ORDER BY MAX(e.created_at) ASC

                LIMIT %(limite)s

            """, {
                "paid": list(PAID_STATUSES),
                "horas": str(max(INTEREST_AFTER_HOURS, 1)),
                "dias": str(max(INTEREST_MAX_AGE_DAYS, 1)),
                "limite": limit
            })

            return cur.fetchall()

    except Exception as e:

        print("Seguimiento de interés: error buscando destinatarios:", e)

        return []


def mark_followup_sent(user_id, group_id):
    """
    Registra el aviso antes de enviarlo.

    Antes de enviar, a propósito: si el envío falla no se reintenta en bucle, y
    nadie recibe el mismo mensaje dos veces. Devuelve False si ya estaba.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO interest_followups (user_id, group_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, group_id) DO NOTHING

            """, (user_id, group_id))

            return cur.rowcount > 0

    except Exception as e:

        print("Seguimiento de interés: error registrando el aviso:", e)

        return False


# =========================
# EL MENSAJE
# =========================

def build_interest_text(group_name, price=None, language=DEFAULT_LANGUAGE):

    price_text = format_amount(price[0], price[1]) if price else None

    lines = [
        t("interest.title", language),
        "",
        t("interest.body", language, group=group_name)
    ]


    if price_text:

        lines.append("")
        lines.append(t("interest.price", language, price=price_text))


    lines.extend([
        "",
        t("interest.footer", language),
        "",
        t("interest.opt_out", language)
    ])

    return "\n".join(lines)


def build_interest_keyboard(group_id, language=DEFAULT_LANGUAGE):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("button.see_access", language),
            callback_data=f"marketplace_group_{group_id}"
        )],
        [InlineKeyboardButton(
            t("button.support", language),
            callback_data="public_support"
        )],
        [InlineKeyboardButton(
            t("button.no_more_messages", language),
            callback_data="reengagement_stop"
        )]
    ])


# =========================
# ENVÍO PROGRAMADO
# =========================

async def process_interest_followups(context):

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}


    if not INTEREST_ENABLED:

        return summary


    rows = fetch_interested_users()
    summary["targets"] = len(rows)


    for user_id, group_id, group_name, _visto in rows:

        if not mark_followup_sent(user_id, group_id):

            summary["skipped"] += 1
            continue


        price = fetch_group_entry_price(group_id)
        language = load_user_language(user_id)

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=build_interest_text(
                    group_name,
                    price=price,
                    language=language
                ),
                reply_markup=build_interest_keyboard(
                    group_id,
                    language=language
                )
            )

            summary["sent"] += 1

        except Exception as e:

            summary["failed"] += 1

            if not is_unreachable_error(e):

                print(
                    f"Seguimiento de interés: no se pudo escribir a {user_id}:",
                    str(e)[:200]
                )


        if INTEREST_SEND_DELAY_SECONDS > 0:

            await asyncio.sleep(INTEREST_SEND_DELAY_SECONDS)


    if summary["sent"] or summary["failed"]:

        log_event(
            "interest_followup_batch",
            category="marketing",
            severity="info",
            message="Avisos a interesados que no compraron.",
            metadata=summary
        )

    return summary


def count_interest_candidates():
    """Cuántos avisos se podrían enviar ahora, para el panel."""

    return len(fetch_interested_users(limit=1000))
