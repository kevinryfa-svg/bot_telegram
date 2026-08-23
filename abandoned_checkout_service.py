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

# EL RESCATE DE LOS ANTIGUOS. En producción hay 72 intentos de pago que se
# quedaron a medias y a los que NUNCA se les escribió: son anteriores a que
# existiera este recuperador, así que cayeron fuera de la ventana de siete días
# y ahí siguen. Es la mayor intención de compra que hay en esta base de datos —
# gente que llegó a la pantalla de Stripe con la tarjeta fuera— y encima
# abandonaron cuando el cobro estaba roto.
#
# Con esta variable la ventana se abre una vez hasta esos días. No hace falta
# cerrarla a mano: la tabla de recordatorios tiene clave única por intento, así
# que cada uno recibe UNO y nunca más.
ABANDONED_RESCUE_DAYS = int(
    os.environ.get("ABANDONED_RESCUE_DAYS", "0")
)


def ventana_de_dias():
    """Hasta qué antigüedad se persigue un intento, con el rescate incluido."""

    return max(ABANDONED_MAX_AGE_DAYS, ABANDONED_RESCUE_DAYS)

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


# =========================
# SEGUNDO TOQUE: EL DESCUENTO
# =========================
# Si 24 horas después del recordatorio sigue sin pagar, un empujón con
# dientes: cupón personal (un solo uso, caduca en 24 h) del 20%. Solo en
# comunidades con planes de Stripe — sin cupón posible, un segundo aviso
# sin nada nuevo que ofrecer es ruido, y no se manda.

ABANDONED_DISCOUNT_AFTER_HOURS = float(
    os.environ.get("ABANDONED_DISCOUNT_AFTER_HOURS", "24")
)

ABANDONED_DISCOUNT_PERCENT = int(
    os.environ.get("ABANDONED_DISCOUNT_PERCENT", "20")
)

ABANDONED_DISCOUNT_ENABLED = os.environ.get(
    "ABANDONED_DISCOUNT_ENABLED",
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
            "days": ventana_de_dias(),
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


def fetch_discount_candidates(limit=None):
    """
    Intentos que ya recibieron el primer recordatorio hace 24 h y siguen sin
    pagar. Mismas exclusiones que el primero, más: la comunidad tiene que
    tener planes de Stripe (sin cupón posible no hay segundo aviso) y el
    descuento solo se ofrece una vez por intento.
    """

    limit = int(limit or ABANDONED_BATCH_SIZE)

    with conn.cursor() as cur:

        cur.execute("""

            SELECT t.id,
                   t.user_id,
                   t.group_id,
                   COALESCE(g.name, 'la comunidad')
            FROM payment_transactions t
            JOIN groups g ON g.id = t.group_id
            WHERE LOWER(COALESCE(t.status, '')) = 'pending'
              AND t.user_id IS NOT NULL
              AND t.group_id IS NOT NULL
              AND COALESCE(g.is_active, TRUE) = TRUE

              AND t.created_at >= NOW() - (%(days)s || ' days')::interval

              AND EXISTS (
                  SELECT 1
                  FROM abandoned_checkout_reminders a
                  WHERE a.transaction_id = t.id
                    AND a.sent_at <= NOW() - (%(hours)s || ' hours')::interval
              )

              AND NOT EXISTS (
                  SELECT 1
                  FROM abandoned_discount_reminders d
                  WHERE d.transaction_id = t.id
              )

              AND EXISTS (
                  SELECT 1
                  FROM plans pl
                  WHERE pl.group_id = t.group_id
                    AND COALESCE(pl.is_active, TRUE) = TRUE
                    AND COALESCE(NULLIF(pl.payment_provider, ''), 'stripe') = 'stripe'
                    AND pl.stripe_product_id IS NOT NULL
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

            ORDER BY t.created_at DESC
            LIMIT %(limit)s

        """, {
            "hours": ABANDONED_DISCOUNT_AFTER_HOURS,
            "days": ABANDONED_MAX_AGE_DAYS,
            "paid": list(PAID_STATUSES),
            "limit": limit
        })

        return cur.fetchall() or []


def mark_abandoned_discount_sent(transaction_id, user_id, group_id, code):
    """True si quedó registrado (y por tanto toca enviarlo)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO abandoned_discount_reminders
                    (transaction_id, user_id, group_id, code)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (transaction_id) DO NOTHING

            """, (transaction_id, user_id, group_id, code))

            return cur.rowcount > 0

    except Exception as e:

        print("Descuento de recuperación: error registrando:", e)
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


def es_rescate(created_at):
    """¿Este intento es de los antiguos, fuera de la ventana normal?"""

    if not created_at or ABANDONED_RESCUE_DAYS <= ABANDONED_MAX_AGE_DAYS:
        return False

    from datetime import datetime, timedelta

    return created_at < datetime.now() - timedelta(days=ABANDONED_MAX_AGE_DAYS)


def cabecera_de_oferta_del_dia():
    """La línea de la oferta viva, o None. Se lee UNA vez por tanda.

    No la lee el texto: un constructor de mensajes que consulta la base de
    datos no se puede probar sin base de datos, y hace una consulta por
    persona para responder siempre lo mismo.
    """

    try:

        from reengagement_service import cabecera_de_oferta, fetch_offer_snapshot

        return cabecera_de_oferta(fetch_offer_snapshot())

    except Exception as e:

        print("Pago abandonado: sin cabecera de oferta:", str(e)[:120])

        return None


def build_rescue_text(group_name, price=None, cabecera=None):
    """Para los intentos antiguos. Empieza reconociendo lo que pasó.

    A esta persona se le escribe meses después. Mandarle el recordatorio normal
    —«te has dejado el pago a medias»— suena a que el bot acaba de despertarse.
    Y hay algo mejor que decir: cuando lo intentó, el cobro de este bot estaba
    roto. Eso explica por qué no llegó a pagar y por qué se le escribe ahora.
    """

    # format_amount ya está importado arriba: repetirlo aquí lo haría local de
    # toda la función. La prueba de imports en la sombra lo cazó al escribirlo.
    lineas = []

    if cabecera:
        lineas.extend([cabecera, ""])

    lineas.extend([
        f"🔧 Intentaste entrar en {group_name} y no llegó a completarse",
        "",
        "Siendo sincero: por aquel entonces el cobro de este bot estaba roto. "
        "No fue cosa tuya.",
        "",
        "Ya está arreglado y comprobado.",
    ])

    if price:

        importe = format_amount(price[0], price[1])

        if importe:

            lineas.extend(["", f"Entrar cuesta {importe}."])

    lineas.extend([
        "",
        "Pagas con tarjeta y el enlace de entrada te llega al momento, "
        "automático.",
    ])

    return "\n".join(lineas)


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


def build_discount_text(group_name, code, percent, language=DEFAULT_LANGUAGE):

    return "\n".join([
        t("abandoned.discount_title", language),
        "",
        t("abandoned.discount_body", language,
          group=group_name, percent=percent, code=code),
        "",
        t("abandoned.discount_expiry", language),
    ])


async def process_abandoned_discounts(context):
    """El segundo toque, con el cupón personal. Si el cupón no se puede crear
    NO se marca ni se manda nada: se reintenta en la siguiente pasada."""

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    if not ABANDONED_DISCOUNT_ENABLED:

        return summary


    try:

        rows = fetch_discount_candidates()

    except Exception as e:

        print("Descuento de recuperación: error seleccionando:", e)
        return summary


    summary["targets"] = len(rows)


    from stripe_coupon_service import create_recovery_promotion_code

    for transaction_id, user_id, group_id, group_name in rows:

        code = create_recovery_promotion_code(
            group_id,
            transaction_id,
            percent_off=ABANDONED_DISCOUNT_PERCENT,
        )

        if not code:

            summary["skipped"] += 1
            continue


        if not mark_abandoned_discount_sent(transaction_id, user_id,
                                            group_id, code):

            summary["skipped"] += 1
            continue


        language = load_user_language(user_id)

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=build_discount_text(
                    group_name,
                    code,
                    ABANDONED_DISCOUNT_PERCENT,
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
                    f"Descuento de recuperación: no se pudo avisar a {user_id}:",
                    str(e)[:200]
                )


        await asyncio.sleep(ABANDONED_SEND_DELAY_SECONDS)


    if summary["sent"] or summary["failed"]:

        log_event(
            "abandoned_discount_reminders_sent",
            category="billing",
            severity="info",
            scope="global",
            message="Segundos avisos con descuento de recuperación.",
            metadata=summary
        )


    return summary


# =========================
# ENVÍO PROGRAMADO
# =========================

async def process_abandoned_checkouts(context):

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}


    if not ABANDONED_ENABLED:

        return summary


    # La misma puerta que el reenganche: si no hay nada vendible o el cobro no
    # contesta, no se escribe. Perseguir un carrito para mandar a la gente otra
    # vez al mismo error es como se gana un bloqueo.
    try:

        from reengagement_service import merece_la_pena_escribir

        ok_para_escribir, motivo = merece_la_pena_escribir()

    except Exception as e:

        ok_para_escribir, motivo = False, f"no se pudo comprobar ({str(e)[:80]})"

    if not ok_para_escribir:

        print("Pago abandonado: no se persigue a nadie —", motivo)

        return summary


    try:

        rows = fetch_abandoned_checkouts()

    except Exception as e:

        print("Pago abandonado: error seleccionando intentos:", e)
        return summary


    summary["targets"] = len(rows)

    # Una sola lectura para toda la tanda: la oferta es la misma para todos.
    cabecera_oferta = cabecera_de_oferta_del_dia()

    for transaction_id, user_id, group_id, group_name, created_at in rows:

        if not mark_abandoned_reminder_sent(transaction_id, user_id, group_id):

            summary["skipped"] += 1
            continue


        price = fetch_group_entry_price(group_id)
        language = load_user_language(user_id)

        rescate = es_rescate(created_at)

        if rescate:
            summary["rescatados"] = summary.get("rescatados", 0) + 1

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    build_rescue_text(
                        group_name, price=price, cabecera=cabecera_oferta
                    ) if rescate
                    else build_abandoned_text(
                        group_name,
                        price=price,
                        language=language
                    )
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


    # El segundo toque (24 h, con cupón) viaja en el mismo job.
    descuentos = await process_abandoned_discounts(context)

    summary["sent"] += descuentos["sent"]
    summary["failed"] += descuentos["failed"]

    return summary
