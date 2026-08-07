import os
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import conn
from audit_log_service import log_event
from i18n_service import DEFAULT_LANGUAGE, load_user_language, t


# =========================
# AVISOS DE RENOVACIÓN
# =========================
# Un cliente al que le caduca el acceso era expulsado sin recibir nada: ni
# aviso previo, ni explicación, ni forma de volver. Solo se avisaba al
# administrador. Aquí se le avisa antes de caducar y se le da un botón para
# renovar en un toque.

RENEWAL_STAGE_EARLY = "3d"
RENEWAL_STAGE_LAST = "1d"
RENEWAL_STAGE_EXPIRED = "expired"

RENEWAL_EARLY_DAYS = int(
    os.environ.get("RENEWAL_EARLY_DAYS", "3")
)

RENEWAL_BATCH_SIZE = int(
    os.environ.get("RENEWAL_BATCH_SIZE", "40")
)

RENEWAL_SEND_DELAY_SECONDS = float(
    os.environ.get("RENEWAL_SEND_DELAY_SECONDS", "0.5")
)

RENEWAL_ENABLED = os.environ.get(
    "RENEWAL_ENABLED",
    "true"
).strip().lower() not in ("0", "false", "no", "off")


# =========================
# CONSULTAS
# =========================

def fetch_group_entry_price(group_id):
    """Precio activo más bajo del grupo, para poder decir cuánto cuesta."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT amount,
                       COALESCE(NULLIF(currency, ''), 'EUR')
                FROM plans
                WHERE group_id=%s
                  AND COALESCE(is_active, TRUE)=TRUE
                  AND amount IS NOT NULL
                  AND amount > 0
                ORDER BY amount ASC
                LIMIT 1

            """, (group_id,))

            return cur.fetchone()

    except Exception as e:

        print("Renovación: error leyendo precio del grupo:", e)
        return None


def fetch_accesses_expiring(stage, limit=None):
    """
    Accesos activos que entran en la ventana de aviso y a los que todavía no
    se ha enviado ese aviso para esta misma caducidad.

    Ventanas separadas para que nadie reciba los dos avisos a la vez:
      - '3d': entre 1 y RENEWAL_EARLY_DAYS días
      - '1d': menos de 1 día
    """

    limit = int(limit or RENEWAL_BATCH_SIZE)

    if stage == RENEWAL_STAGE_LAST:

        window = "u.expiration <= NOW() + INTERVAL '1 day'"

    else:

        window = (
            "u.expiration > NOW() + INTERVAL '1 day' "
            f"AND u.expiration <= NOW() + (%(days)s || ' days')::interval"
        )

    params = {"stage": stage, "limit": limit, "days": RENEWAL_EARLY_DAYS}

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT u.user_id,
                   u.group_id,
                   u.expiration,
                   COALESCE(g.name, 'la comunidad')
            FROM users u
            JOIN groups g ON g.id = u.group_id
            WHERE u.expiration IS NOT NULL
              AND u.expiration > NOW()
              AND {window}
              AND COALESCE(u.subscription_active, TRUE) = TRUE
              AND COALESCE(g.is_active, TRUE) = TRUE

              AND NOT EXISTS (
                  SELECT 1
                  FROM access_renewal_reminders r
                  WHERE r.user_id = u.user_id
                    AND r.group_id = u.group_id
                    AND r.stage = %(stage)s
                    AND r.expiration = u.expiration
              )

              AND NOT EXISTS (
                  SELECT 1 FROM banned_users b WHERE b.user_id = u.user_id
              )

            ORDER BY u.expiration ASC
            LIMIT %(limit)s

        """, params)

        return cur.fetchall() or []


def mark_renewal_reminder_sent(user_id, group_id, stage, expiration):
    """Devuelve True si el aviso se registró (y por tanto toca enviarlo)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO access_renewal_reminders
                    (user_id, group_id, stage, expiration)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, group_id, stage, expiration)
                DO NOTHING

            """, (
                user_id,
                group_id,
                stage,
                expiration
            ))

            return cur.rowcount > 0

    except Exception as e:

        print("Renovación: error registrando aviso:", e)
        return False


# =========================
# MENSAJES
# =========================

def format_amount(amount, currency):

    if amount is None:

        return None


    try:

        value = float(amount)

    except Exception:

        return None


    text = f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")

    return f"{text} {currency or 'EUR'}"


def format_days_left(expiration, language=DEFAULT_LANGUAGE):
    """Texto humano del tiempo que queda, sin prometer precisión falsa."""

    from datetime import datetime

    try:

        remaining = expiration - datetime.now()

    except Exception:

        return t("time.very_soon", language)


    import math

    # Se redondea al alza: un acceso creado a 2 días exactos se calcula como
    # 47,99 horas, y truncar diría "1 día", que es engañoso.
    hours = math.ceil(remaining.total_seconds() / 3600)


    if hours <= 1:

        return t("time.under_an_hour", language)


    if hours < 24:

        return t("time.in_hours", language, hours=hours)


    days = math.ceil(hours / 24)

    if days == 1:

        return t("time.in_one_day", language)


    return t("time.in_days", language, days=days)


def build_renewal_text(group_name, expiration, price=None,
                       stage=RENEWAL_STAGE_EARLY, language=DEFAULT_LANGUAGE):

    price_text = format_amount(price[0], price[1]) if price else None


    if stage == RENEWAL_STAGE_EXPIRED:

        lines = [
            t("renewal.expired_title", language),
            "",
            t("renewal.expired_body", language, group=group_name),
            ""
        ]

        if price_text:

            lines.append(
                t("renewal.expired_price", language, price=price_text)
            )

        else:

            lines.append(t("renewal.expired_no_price", language))

        lines.append("")
        lines.append(t("renewal.expired_footer", language))

        return "\n".join(lines)


    header = t(
        "renewal.soon_title" if stage == RENEWAL_STAGE_LAST
        else "renewal.early_title",
        language
    )

    lines = [
        header,
        "",
        t(
            "renewal.body",
            language,
            group=group_name,
            when=format_days_left(expiration, language=language)
        )
    ]


    if price_text:

        lines.append("")
        lines.append(t("renewal.price", language, price=price_text))


    lines.append("")
    lines.append(t("renewal.footer", language))

    return "\n".join(lines)


def build_renewal_keyboard(group_id, stage=RENEWAL_STAGE_EARLY,
                           language=DEFAULT_LANGUAGE):

    label = t(
        "button.join_again" if stage == RENEWAL_STAGE_EXPIRED
        else "button.renew",
        language
    )

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            label,
            callback_data=f"marketplace_group_{group_id}"
        )],
        [InlineKeyboardButton(
            t("button.my_accesses", language),
            callback_data="mis_subs"
        )],
        [InlineKeyboardButton(
            t("button.i_have_a_question", language),
            callback_data="public_support"
        )]
    ])


# =========================
# ENVÍO PROGRAMADO
# =========================

def is_unreachable_error(error):

    text = str(error or "").lower()

    return any(
        marker in text
        for marker in (
            "bot was blocked",
            "user is deactivated",
            "chat not found",
            "bot can't initiate conversation",
            "forbidden"
        )
    )


async def send_renewal_stage(context, stage):

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    try:

        rows = fetch_accesses_expiring(stage)

    except Exception as e:

        print(f"Renovación ({stage}): error seleccionando accesos:", e)
        return summary


    summary["targets"] = len(rows)


    for user_id, group_id, expiration, group_name in rows:

        # Se registra antes de enviar: si el envío falla no se reintenta en
        # bucle, y nunca se manda el mismo aviso dos veces.
        if not mark_renewal_reminder_sent(user_id, group_id, stage, expiration):

            summary["skipped"] += 1
            continue


        price = fetch_group_entry_price(group_id)

        # En el idioma del cliente: un comprador inglés que recibe el aviso en
        # español es un comprador que no renueva.
        language = load_user_language(user_id)

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=build_renewal_text(
                    group_name,
                    expiration,
                    price=price,
                    stage=stage,
                    language=language
                ),
                reply_markup=build_renewal_keyboard(
                    group_id,
                    stage=stage,
                    language=language
                )
            )

            summary["sent"] += 1

        except Exception as e:

            summary["failed"] += 1

            if not is_unreachable_error(e):

                print(
                    f"Renovación ({stage}): no se pudo avisar a {user_id}:",
                    str(e)[:200]
                )


        await asyncio.sleep(RENEWAL_SEND_DELAY_SECONDS)


    return summary


async def process_renewal_reminders(context):
    """Job programado: avisa primero a los más urgentes."""

    total = {"sent": 0, "failed": 0}


    if not RENEWAL_ENABLED:

        return total


    for stage in (RENEWAL_STAGE_LAST, RENEWAL_STAGE_EARLY):

        summary = await send_renewal_stage(context, stage)

        total["sent"] += summary["sent"]
        total["failed"] += summary["failed"]


    if total["sent"] or total["failed"]:

        print(
            "Renovación:",
            f"{total['sent']} avisos enviados,",
            f"{total['failed']} fallidos"
        )

        log_event(
            "access_renewal_reminders_sent",
            category="billing",
            severity="info",
            scope="global",
            message="Avisos de renovación enviados a usuarios con acceso por caducar.",
            metadata=total
        )


    return total


# =========================
# AVISO AL CADUCAR
# =========================

def build_expired_notice(group_id, group_name, language=DEFAULT_LANGUAGE):
    """Mensaje y teclado para quien acaba de perder el acceso."""

    price = fetch_group_entry_price(group_id)

    return (
        build_renewal_text(
            group_name,
            None,
            price=price,
            stage=RENEWAL_STAGE_EXPIRED,
            language=language
        ),
        build_renewal_keyboard(
            group_id,
            stage=RENEWAL_STAGE_EXPIRED,
            language=language
        )
    )
