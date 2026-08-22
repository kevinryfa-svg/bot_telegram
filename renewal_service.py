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


# =========================
# RECUPERAR AL QUE SE FUE
# =========================
# Había avisos ANTES de caducar y uno AL caducar. Después, nada: quien no
# renovaba en el momento desaparecía para siempre, y es la persona más barata de
# recuperar que existe —ya conoce la comunidad y ya pagó una vez.
#
# Vive en este fichero y no en uno nuevo a propósito: reutiliza la tabla de
# avisos con su clave única, el marcador que hace todo idempotente, el lector de
# precio y el bucle de envío. Un módulo aparte habría sido la quinta copia de lo
# mismo.

WINBACK_STAGE_WEEK = "winback_7d"
WINBACK_STAGE_MONTH = "winback_30d"

WINBACK_STAGES = (WINBACK_STAGE_WEEK, WINBACK_STAGE_MONTH)

WINBACK_WEEK_DAYS = int(os.environ.get("WINBACK_WEEK_DAYS", "7"))
WINBACK_MONTH_DAYS = int(os.environ.get("WINBACK_MONTH_DAYS", "30"))

# Más allá de esto no se insiste: alguien que se fue hace medio año y no ha
# vuelto no quiere volver, y escribirle es ganarse un bloqueo.
WINBACK_MAX_AGE_DAYS = int(os.environ.get("WINBACK_MAX_AGE_DAYS", "120"))

WINBACK_ENABLED = os.environ.get(
    "WINBACK_ENABLED",
    "true"
).strip().lower() not in ("0", "false", "no", "off")

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
# AVISO PRE-RENOVACIÓN (suscripciones)
# =========================
# Con la renovación automática, "tu acceso caduca, renueva" es el aviso
# EQUIVOCADO: a ese cliente se le va a cobrar solo. Lo correcto —y lo que
# reduce disputas y chargebacks, y es obligatorio en varios países— es avisar
# ANTES del cobro: cuánto, cuándo, y dónde cancelar si no quiere seguir.
#
# Vive aquí por lo mismo que el reenganche: reutiliza la tabla de avisos con
# su clave única, el marcador idempotente y el bucle de envío.

PRERENEWAL_STAGE = "prerenewal"

PRERENEWAL_DAYS = int(os.environ.get("PRERENEWAL_DAYS", "3"))

PRERENEWAL_ENABLED = os.environ.get(
    "PRERENEWAL_ENABLED",
    "true"
).strip().lower() not in ("0", "false", "no", "off")


def renewal_is_really_active(user_id, group_id):
    """
    ¿Este socio tiene una renovación automática QUE VA A COBRAR? Se pregunta a
    la fuente (Stripe/PayPal) solo para los pocos candidatos en ventana: si el
    socio la canceló, avisarle del cobro sería mentirle.

    Imports diferidos para no atar este módulo a los proveedores en el
    arranque.
    """

    try:

        from group_subscription_service import fetch_renewal_state

        estado = fetch_renewal_state(user_id, group_id)

        if estado is not None:
            # Ni cancelada ni EN PAUSA: a un suscriptor pausado anunciarle un
            # cobro sería mentirle — su factura se anula sola.
            return not estado.get("cancel_at_period_end") \
                and not estado.get("paused")

    except Exception as e:

        print("Pre-renovación: error leyendo estado Stripe:", str(e)[:200])


    try:

        from paypal_subscription_controls import fetch_paypal_renewal_state

        estado = fetch_paypal_renewal_state(user_id, group_id)

        if estado is not None:
            return bool(estado.get("activa"))

    except Exception as e:

        print("Pre-renovación: error leyendo estado PayPal:", str(e)[:200])


    return False


# =========================
# CONSULTAS
# =========================

def fetch_group_entry_price(group_id):
    """Precio activo más bajo del grupo, para poder decir cuánto cuesta.

    Con el importe VIGENTE: si hay una oferta viva, es ese. Todo lo que este
    bot le escribe a alguien —el carrito abandonado, el aviso al interesado, el
    de renovación— pasa por aquí, y decir 9 EUR mientras la tienda vende a 3,60
    es perder la venta y quedar mal a la vez.
    """

    from weekly_offer_service import sql_importe_vigente

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT """ + sql_importe_vigente("p") + """,
                       COALESCE(NULLIF(p.currency, ''), 'EUR')
                FROM plans p
                WHERE p.group_id=%s
                  AND COALESCE(p.is_active, TRUE)=TRUE
                  AND p.amount IS NOT NULL
                  AND p.amount > 0
                ORDER BY 1 ASC
                LIMIT 1

            """, (group_id,))

            return cur.fetchone()

    except Exception as e:

        print("Renovación: error leyendo precio del grupo:", e)
        return None


def fetch_same_plan_for_member(user_id, group_id):
    """El plan que esta persona compró la última vez, si sigue activo.

    Renovar costaba tres toques: aviso → tarjeta de la comunidad → lista de
    planes → pagar. Con esto es uno: el botón lleva directo al plan de
    siempre, al precio de siempre.

    La atadura es el NOMBRE del plan guardado en payments (es lo que hay), y
    se exige coincidencia exacta con un plan activo: mandar a alguien a un
    plan que no es el suyo —otro precio, otra duración— es peor que
    enseñarle el menú. Sin coincidencia, devuelve None y el aviso lleva los
    botones de siempre.

    Devuelve (plan_id, nombre, amount, currency, price_id, provider).
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT pl.id,
                       pl.name,
                       pl.amount,
                       COALESCE(NULLIF(pl.currency, ''), 'EUR'),
                       pl.price_id,
                       COALESCE(NULLIF(pl.payment_provider, ''), 'stripe')
                FROM payments p
                JOIN plans pl
                  ON pl.group_id = p.group_id
                 AND pl.name = p.plan
                 AND COALESCE(pl.is_active, TRUE) = TRUE
                 AND pl.amount IS NOT NULL
                 AND pl.amount > 0
                WHERE p.user_id = %s
                  AND p.group_id = %s
                  AND LOWER(COALESCE(p.status, '')) IN ('paid', 'completed')
                ORDER BY p.payment_date DESC NULLS LAST, p.id DESC
                LIMIT 1

            """, (user_id, group_id))

            return cur.fetchone()

    except Exception as e:

        print("Renovación: error buscando el plan de siempre:", e)

        return None


def same_plan_callback(group_id, plan_id, price_id, provider):
    """El callback exacto que pulsaría esa persona en la lista de planes.

    Stripe usa el price_id como callback (así está el resto del bot); los
    demás proveedores tienen su propio prefijo. Si faltara el dato que hace
    falta, None: mejor el menú que un botón muerto.
    """

    proveedor = (provider or "stripe").strip().lower()

    if proveedor == "stripe":

        return price_id or None

    if proveedor in ("paypal", "revolut", "changenow", "guardarian"):

        return f"{proveedor}_group_plan_{group_id}_{plan_id}"

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

              -- Renovación automática: a estos NO se les pide renovar a mano
              -- (se les va a cobrar solo); tienen su propio aviso pre-cobro.
              -- El ancla de Stripe se limpia cuando la suscripción muere, y la
              -- transacción de PayPal deja de estar 'paid' al cancelarse, así
              -- que quien apagó la renovación vuelve a recibir estos avisos.
              AND u.stripe_subscription_id IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM payment_transactions pt
                  WHERE pt.provider = 'paypal'
                    AND pt.user_id = u.user_id
                    AND pt.group_id = u.group_id
                    AND pt.purchase_type = 'group_access'
                    AND pt.status = 'paid'
                    AND pt.external_checkout_id IS NOT NULL
              )

            ORDER BY u.expiration ASC
            LIMIT %(limit)s

        """, params)

        return cur.fetchall() or []


def fetch_expired_accesses(stage, limit=None):
    """
    Gente a la que se le caducó el acceso y no ha vuelto.

    Las ventanas no se solapan, para que nadie reciba los dos avisos: la de una
    semana coge lo caducado entre WINBACK_WEEK_DAYS y WINBACK_MONTH_DAYS días
    atrás, y la de un mes desde ahí hasta WINBACK_MAX_AGE_DAYS.

    Se excluye a quien:
      - ha vuelto: al recomprar, su caducidad pasa a ser futura y la ventana ya
        lo excluye. Escribirle "vuelve" a alguien que ya está dentro sería lo
        peor que podría hacer esto, así que hay una prueba que lo fija;
      - está vetado, se ha dado de baja de los avisos o tiene el bot bloqueado;
      - ya recibió este aviso para esta misma caducidad;
      - pertenece a una comunidad gratuita, apagada, o sin ningún plan de pago
        activo: no se puede invitar a volver a algo que no se vende;
      - pertenece a una comunidad que consta SIN PODER dar acceso. Mandar a
        alguien a comprar donde la compra se va a rechazar es peor que no
        escribirle.
    """

    limit = int(limit or RENEWAL_BATCH_SIZE)

    if stage == WINBACK_STAGE_WEEK:

        desde, hasta = WINBACK_WEEK_DAYS, WINBACK_MONTH_DAYS

    else:

        desde, hasta = WINBACK_MONTH_DAYS, WINBACK_MAX_AGE_DAYS


    params = {
        "stage": stage,
        "limit": limit,
        "desde": desde,
        "hasta": hasta
    }

    with conn.cursor() as cur:

        cur.execute("""

            SELECT u.user_id,
                   u.group_id,
                   u.expiration,
                   COALESCE(g.name, 'la comunidad')
            FROM users u
            JOIN groups g ON g.id = u.group_id
            WHERE u.expiration IS NOT NULL
              AND u.expiration < NOW() - (%(desde)s || ' days')::interval
              AND u.expiration >= NOW() - (%(hasta)s || ' days')::interval
              AND COALESCE(g.is_active, TRUE) = TRUE
              AND COALESCE(g.is_free_group, FALSE) = FALSE

              -- Quien ha vuelto queda fuera por la propia ventana: la clave
              -- primaria de users es (user_id, group_id), así que solo hay una
              -- fila por persona y comunidad, y al volver a comprar esa misma
              -- fila pasa a tener caducidad futura. Aquí había además un NOT
              -- EXISTS comprobándolo que era imposible de satisfacer: aparentaba
              -- una protección que no hacía nada.

              -- La comunidad tiene que seguir vendiendo algo.
              AND EXISTS (
                  SELECT 1
                  FROM plans p
                  WHERE p.group_id = u.group_id
                    AND COALESCE(p.is_active, TRUE) = TRUE
                    AND p.amount IS NOT NULL
                    AND p.amount > 0
              )

              -- Y tiene que poder entregar: si consta que no, la compra se
              -- rechazaría y el aviso sería una tomadura de pelo.
              AND NOT EXISTS (
                  SELECT 1
                  FROM group_delivery_health h
                  WHERE h.group_id = u.group_id
                    AND h.can_deliver IS FALSE
              )

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

              -- El mismo opt-out que el resto de avisos del bot.
              AND NOT EXISTS (
                  SELECT 1 FROM user_reengagement re
                  WHERE re.user_id = u.user_id
                    AND (
                        COALESCE(re.opted_out, FALSE) = TRUE
                        OR COALESCE(re.is_blocked, FALSE) = TRUE
                    )
              )

            ORDER BY u.expiration DESC
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

    if stage in WINBACK_STAGES:

        return build_winback_text(
            group_name, expiration, price=price, stage=stage, language=language
        )


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


def format_time_since(expiration, stage, language=DEFAULT_LANGUAGE):
    """
    Cuánto hace que se fue, en palabras.

    Se dice por la etapa y no calculando los días exactos: "hace 34 días" suena
    a base de datos, y "hace un mes" a persona.
    """

    if stage == WINBACK_STAGE_WEEK:

        return t("winback.since_week", language)


    return t("winback.since_month", language)


def build_winback_text(group_name, expiration, price=None,
                       stage=WINBACK_STAGE_WEEK, language=DEFAULT_LANGUAGE):
    """
    Lo que se le dice a quien se fue.

    Sin culpar y sin urgencia falsa: se le recuerda dónde estaba, cuánto cuesta
    volver, y se le deja marchar en paz si no quiere saber más.
    """

    price_text = format_amount(price[0], price[1]) if price else None

    lines = [
        t("winback.title", language),
        "",
        t(
            "winback.body",
            language,
            group=group_name,
            when=format_time_since(expiration, stage, language=language)
        )
    ]


    if price_text:

        lines.append("")
        lines.append(t("winback.price", language, price=price_text))


    lines.append("")
    lines.append(t("winback.footer", language))

    return "\n".join(lines)


def build_winback_keyboard(group_id, language=DEFAULT_LANGUAGE):
    """
    Con baja voluntaria, que los avisos de renovación no llevan.

    La diferencia importa: un aviso de renovación va a un cliente que tiene algo
    contratado; esto va a alguien que ya no es cliente. Si no quiere que le
    escribamos, tiene que poder decirlo en el mismo mensaje.
    """

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("button.join_again", language),
            callback_data=f"marketplace_group_{group_id}"
        )],
        [InlineKeyboardButton(
            t("button.i_have_a_question", language),
            callback_data="public_support"
        )],
        [InlineKeyboardButton(
            t("button.no_more_messages", language),
            callback_data="reengagement_stop"
        )]
    ])


def build_renewal_keyboard(group_id, stage=RENEWAL_STAGE_EARLY,
                           language=DEFAULT_LANGUAGE, user_id=None):

    if stage in WINBACK_STAGES:

        return build_winback_keyboard(group_id, language=language)


    label = t(
        "button.join_again" if stage == RENEWAL_STAGE_EXPIRED
        else "button.renew",
        language
    )

    filas = []

    # EL AÑO CON DESCUENTO, PRIMERO. Quien está a punto de perder el acceso de
    # una semana es la persona más fácil de convertir en anual que existe: ya
    # está dentro y ya sabe lo que hay. La oferta es SUYA —lleva su user_id— y
    # por eso no le baja el precio anual a todo el mundo.
    if user_id and group_id:

        try:

            from weekly_offer_service import (
                asegurar_oferta_anual,
                frase_oferta_anual,
                tiene_plan_corto,
            )

            if tiene_plan_corto(user_id, group_id):

                anual = asegurar_oferta_anual(user_id, group_id)

                etiqueta = frase_oferta_anual(anual)

                if anual and etiqueta:

                    filas.append([InlineKeyboardButton(
                        etiqueta,
                        callback_data=(
                            f"startbuy_{group_id}_{anual['plan_id']}"
                        )
                    )])

        except Exception as e:

            # Un fallo preparando la oferta no puede dejar sin aviso de
            # renovación a quien está a punto de caducar.
            print("Aviso de renovación: sin oferta anual:", str(e)[:160])


    # UN TOQUE: si se sabe qué plan compró y sigue activo, el primer botón
    # va directo a pagarlo, con nombre y precio en la etiqueta. Cada
    # pantalla intermedia es gente que se cae por el camino.
    if user_id:

        plan = fetch_same_plan_for_member(user_id, group_id)

        if plan:

            plan_id, nombre, amount, currency, price_id, provider = plan
            callback = same_plan_callback(group_id, plan_id, price_id, provider)

            if callback:

                filas.append([InlineKeyboardButton(
                    t(
                        "button.renew_same_plan", language,
                        plan=nombre,
                        price=f"{amount} {currency}"
                    ),
                    callback_data=callback
                )])


    return InlineKeyboardMarkup(filas + [
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

        if stage in WINBACK_STAGES:

            rows = fetch_expired_accesses(stage)

        else:

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
                    language=language,
                    user_id=user_id
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


def fetch_upcoming_autorenewals(limit=None):
    """
    Socios con renovación automática cuyo próximo cobro cae dentro de la
    ventana de aviso. La expiración ES la fecha de cobro: cada ciclo cobrado la
    mueve al final del periodo siguiente.
    """

    limit = int(limit or RENEWAL_BATCH_SIZE)

    with conn.cursor() as cur:

        cur.execute("""

            SELECT u.user_id,
                   u.group_id,
                   u.expiration,
                   COALESCE(g.name, 'la comunidad'),
                   g.telegram_group_id
            FROM users u
            JOIN groups g ON g.id = u.group_id
            WHERE u.expiration IS NOT NULL
              AND u.expiration > NOW()
              AND u.expiration <= NOW() + (%(days)s || ' days')::interval
              AND COALESCE(u.subscription_active, TRUE) = TRUE
              AND COALESCE(g.is_active, TRUE) = TRUE

              AND (
                  u.stripe_subscription_id IS NOT NULL
                  OR EXISTS (
                      SELECT 1
                      FROM payment_transactions pt
                      WHERE pt.provider = 'paypal'
                        AND pt.user_id = u.user_id
                        AND pt.group_id = u.group_id
                        AND pt.purchase_type = 'group_access'
                        AND pt.status = 'paid'
                        AND pt.external_checkout_id IS NOT NULL
                  )
              )

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

        """, {"days": PRERENEWAL_DAYS, "stage": PRERENEWAL_STAGE,
              "limit": limit})

        return cur.fetchall() or []


def fetch_member_last_price(user_id, group_id):
    """Lo que este socio paga de verdad (su último cobro), no el precio de
    lista: quien se suscribió antes de una subida conserva el suyo."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT amount, currency
                FROM payments
                WHERE user_id=%s AND group_id=%s
                  AND LOWER(COALESCE(status, '')) IN ('paid', 'completed')
                ORDER BY payment_date DESC NULLS LAST, id DESC
                LIMIT 1

            """, (user_id, group_id))

            row = cur.fetchone()

        if not row or row[0] is None:
            return None

        return f"{int(row[0]) / 100:.2f} {(row[1] or 'EUR').upper()}"

    except Exception as e:

        print("Pre-renovación: error leyendo el último cobro:", e)

        return None


def build_prerenewal_text(group_name, expiration, price, language=DEFAULT_LANGUAGE):

    try:
        fecha = expiration.strftime("%d/%m/%Y")
    except Exception:
        fecha = "-"

    if price:

        return t("renewal.upcoming_priced", language,
                 group=group_name, until=fecha, price=price)

    return t("renewal.upcoming", language, group=group_name, until=fecha)


def build_prerenewal_keyboard(telegram_group_id, language=DEFAULT_LANGUAGE):
    """Directo a «Mis suscripciones», donde vive el interruptor."""

    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            t("renewal.upcoming_button", language),
            callback_data=f"mysub_{telegram_group_id}"
        )
    ]])


# =========================
# UPSELL AL PLAN ANUAL
# =========================
# A un suscriptor mensual que ya renovó dos veces (3+ pagos) se le ofrece UNA
# VEZ el plan anual de su comunidad — solo si existe, es suscripción, está en
# su misma moneda y de verdad ahorra frente a 12 meses. El cliente que ya
# demostró que se queda es el momento exacto de subirle el valor; el upsell
# repetido es spam que devalúa la oferta.

ANNUAL_UPSELL_ENABLED = os.environ.get(
    "ANNUAL_UPSELL_ENABLED", "true"
).strip().lower() not in ("0", "false", "no", "off")

ANNUAL_UPSELL_MIN_PAYMENTS = int(
    os.environ.get("ANNUAL_UPSELL_MIN_PAYMENTS", "3")
)


def fetch_annual_upsell_candidates(limit=None):
    """
    [(user_id, group_id, group_name, ultimo_pago_minor, currency,
      anual_amount_major, anual_minor)]
    """

    from payment_gateway_config import amount_to_minor_units

    limit = int(limit or RENEWAL_BATCH_SIZE)

    with conn.cursor() as cur:

        cur.execute("""

            SELECT u.user_id,
                   u.group_id,
                   COALESCE(g.name, 'la comunidad'),
                   ultimo.amount,
                   COALESCE(NULLIF(UPPER(ultimo.currency), ''), 'EUR'),
                   anual.amount
            FROM users u
            JOIN groups g ON g.id = u.group_id
            JOIN LATERAL (
                SELECT p.amount, p.currency
                FROM payments p
                WHERE p.user_id = u.user_id
                  AND p.group_id = u.group_id
                  AND LOWER(COALESCE(p.status, '')) IN ('paid', 'completed')
                ORDER BY p.payment_date DESC NULLS LAST, p.id DESC
                LIMIT 1
            ) ultimo ON TRUE
            JOIN LATERAL (
                SELECT pl.amount, pl.currency
                FROM plans pl
                WHERE pl.group_id = u.group_id
                  AND COALESCE(pl.is_active, TRUE) = TRUE
                  AND COALESCE(pl.is_recurring, FALSE) = TRUE
                  AND pl.duration_days IN (365, 366)
                  AND COALESCE(NULLIF(pl.payment_provider, ''), 'stripe') = 'stripe'
                  AND UPPER(COALESCE(pl.currency, 'EUR')) =
                      COALESCE(NULLIF(UPPER(ultimo.currency), ''), 'EUR')
                ORDER BY pl.amount ASC
                LIMIT 1
            ) anual ON TRUE
            WHERE u.stripe_subscription_id IS NOT NULL
              AND COALESCE(u.subscription_active, FALSE) = TRUE
              AND COALESCE(g.is_active, TRUE) = TRUE

              AND (
                  SELECT COUNT(*) FROM payments p2
                  WHERE p2.user_id = u.user_id
                    AND p2.group_id = u.group_id
                    AND LOWER(COALESCE(p2.status, '')) IN ('paid', 'completed')
              ) >= %(minimo)s

              AND NOT EXISTS (
                  SELECT 1 FROM upsell_offers o
                  WHERE o.user_id = u.user_id AND o.group_id = u.group_id
              )

              AND NOT EXISTS (
                  SELECT 1 FROM banned_users b WHERE b.user_id = u.user_id
              )

            ORDER BY u.user_id
            LIMIT %(limit)s

        """, {"minimo": ANNUAL_UPSELL_MIN_PAYMENTS, "limit": limit})

        candidatos = []

        for user_id, group_id, nombre, ultimo, currency, anual_major in \
                cur.fetchall() or []:

            try:

                anual_minor = amount_to_minor_units(anual_major, currency)

            except Exception:

                continue

            # Solo si el anual AHORRA de verdad frente a 12 meses del precio
            # que este socio paga. Ofrecer un "ahorro" que no existe quema la
            # confianza que el resto del sistema construye.
            if ultimo and anual_minor < int(ultimo) * 12:

                candidatos.append((user_id, group_id, nombre, int(ultimo),
                                   currency, anual_major, anual_minor))

        return candidatos


def mark_upsell_sent(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO upsell_offers (user_id, group_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, group_id) DO NOTHING

            """, (user_id, group_id))

            hecho = cur.rowcount > 0
            conn.commit()

            return hecho

    except Exception as e:

        print("Upsell anual: error registrando:", e)

        return False


async def send_annual_upsell_stage(context):

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    if not ANNUAL_UPSELL_ENABLED:

        return summary


    try:

        filas = fetch_annual_upsell_candidates()

    except Exception as e:

        print("Upsell anual: error seleccionando:", e)
        return summary


    summary["targets"] = len(filas)

    for user_id, group_id, nombre, ultimo, currency, anual_major, anual_minor \
            in filas:

        if not mark_upsell_sent(user_id, group_id):

            summary["skipped"] += 1
            continue

        language = load_user_language(user_id)

        ahorro = (int(ultimo) * 12 - anual_minor) * 100 // (int(ultimo) * 12)
        precio_anual = f"{anual_minor / 100:.2f} {currency}"

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=t("renewal.upsell_annual", language,
                       group=nombre, price=precio_anual, saving=ahorro),
                # Al cambio de plan, NO a la tarjeta de la comunidad: quien
                # ya tiene acceso aterrizaba en «ya tienes acceso a esta
                # comunidad» y el upsell no se podía completar.
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        t("renewal.upsell_annual_button", language),
                        callback_data=f"mysub_switch_{group_id}"
                    )
                ]])
            )

            summary["sent"] += 1

        except Exception as e:

            print(f"Upsell anual: fallo avisando a {user_id}:", str(e)[:200])
            summary["failed"] += 1

        await asyncio.sleep(RENEWAL_SEND_DELAY_SECONDS)


    return summary


async def send_prerenewal_stage(context):

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    if not PRERENEWAL_ENABLED:

        return summary


    try:

        rows = fetch_upcoming_autorenewals()

    except Exception as e:

        print("Pre-renovación: error seleccionando socios:", e)
        return summary


    summary["targets"] = len(rows)


    for user_id, group_id, expiration, group_name, telegram_group_id in rows:

        # Si el socio ya canceló, avisarle del cobro sería mentirle. NO se
        # marca: si reactiva antes de la fecha, el aviso saldrá entonces.
        if not renewal_is_really_active(user_id, group_id):

            summary["skipped"] += 1
            continue


        if not mark_renewal_reminder_sent(
            user_id, group_id, PRERENEWAL_STAGE, expiration
        ):

            summary["skipped"] += 1
            continue


        language = load_user_language(user_id)
        price = fetch_member_last_price(user_id, group_id)

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=build_prerenewal_text(
                    group_name, expiration, price, language=language
                ),
                reply_markup=build_prerenewal_keyboard(
                    telegram_group_id, language=language
                )
            )

            summary["sent"] += 1

        except Exception as e:

            print(f"Pre-renovación: fallo avisando a {user_id}:", str(e)[:200])
            summary["failed"] += 1


        await asyncio.sleep(RENEWAL_SEND_DELAY_SECONDS)


    return summary


async def process_renewal_reminders(context):
    """Job programado: avisa primero a los más urgentes."""

    total = {"sent": 0, "failed": 0}


    if not RENEWAL_ENABLED:

        return total


    # El aviso pre-cobro va el primero: es el único con fecha límite dura (el
    # cobro sale igual) y el único que evita disputas en vez de perseguirlas.
    prerenewal = await send_prerenewal_stage(context)
    total["sent"] += prerenewal["sent"]
    total["failed"] += prerenewal["failed"]

    # Y el upsell anual después: al que ya demostró quedarse, más valor.
    upsell = await send_annual_upsell_stage(context)
    total["sent"] += upsell["sent"]
    total["failed"] += upsell["failed"]


    etapas = [RENEWAL_STAGE_LAST, RENEWAL_STAGE_EARLY]

    # La recuperación va al final: primero los clientes que todavía lo son, que
    # es donde el aviso vale más y donde no hay que gastar la cuota de envío.
    if WINBACK_ENABLED:

        etapas.extend(WINBACK_STAGES)


    for stage in etapas:

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

def build_expired_notice(group_id, group_name, language=DEFAULT_LANGUAGE,
                         user_id=None):
    """Mensaje y teclado para quien acaba de perder el acceso.

    Con user_id, el teclado lleva el botón directo a su plan de siempre: es
    el momento de más intención de volver que va a haber.
    """

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
            language=language,
            user_id=user_id
        )
    )
