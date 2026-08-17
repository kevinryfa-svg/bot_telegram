"""
El socio que paga y se queda fuera: devolverle la entrada, en el momento.

Cuando alguien sale de la comunidad —o lo saca otro administrador por error,
o se va con el dedo gordo desde el móvil— Guardian ya lo detecta y se lo
cuenta al propietario. Al que se queda fuera, en cambio, no se le decía
nada. Y si esa persona tiene acceso pagado en vigor, acaba de perder lo que
está pagando y solo se enterará cuando le apetezca mirar: mientras tanto es
una devolución esperando a pasar.

Aquí se le manda un enlace nuevo en cuanto ocurre. Las reglas:

  SOLO CON ACCESO VIVO   Si su acceso ya había caducado, salir del grupo es
                         el final normal de la historia y no se le escribe.
                         Perseguir a un excliente con enlaces es ganarse un
                         bloqueo.

  UNA VEZ POR EPISODIO   Con enfriamiento (RETURN_OFFER_COOLDOWN_DAYS, 7 por
                         defecto): quien entra y sale a propósito no recibe
                         un mensaje cada vez.

  SIN JUZGAR EL MOTIVO   No se puede saber si salió queriendo o si lo sacaron.
                         El mensaje vale para los dos casos: "tu acceso sigue
                         activo hasta X; si ha sido un error, aquí tienes tu
                         enlace". Nada de reproches ni de preguntas.

El enlace es de un solo uso y caduca, como todos los del bot: si se filtra,
no sirve para nadie más.
"""

import os

from audit_log_service import log_event
from bot_config import TOKEN
from db import conn
from invite_link_service import create_telegram_invite_link


RETURN_OFFER_ENABLED = os.environ.get(
    "RETURN_OFFER_ENABLED", "true"
).strip().lower() not in ("0", "false", "no", "off")

RETURN_OFFER_COOLDOWN_DAYS = int(
    os.environ.get("RETURN_OFFER_COOLDOWN_DAYS", "7")
)

# 24 horas: el socio puede estar durmiendo cuando pasa esto.
RETURN_LINK_EXPIRE_SECONDS = int(
    os.environ.get("RETURN_LINK_EXPIRE_SECONDS", "86400")
)


def fetch_live_access(user_id, group_id):
    """(expiration, telegram_group_id, group_name) si su acceso sigue vivo.

    None cuando ya había caducado: ahí salir del grupo es el final normal.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT u.expiration,
                       g.telegram_group_id,
                       COALESCE(g.name, 'la comunidad')
                FROM users u
                JOIN groups g ON g.id = u.group_id
                WHERE u.user_id = %s
                  AND u.group_id = %s
                  AND (u.expiration IS NULL OR u.expiration > NOW())

            """, (user_id, group_id))

            return cur.fetchone()

    except Exception as e:

        print("Recuperación de socio: error leyendo el acceso:", e)

        return None


def mark_return_offer(user_id, group_id):
    """True si toca ofrecer (marca primero). False dentro del enfriamiento.

    El registro es de UNA fila por socio y comunidad que se va actualizando:
    interesa cuándo fue la última vez, no un histórico que nadie lee.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO member_return_offers (user_id, group_id, sent_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (user_id, group_id) DO UPDATE
                    SET sent_at = NOW()
                WHERE member_return_offers.sent_at
                      < NOW() - (%s || ' days')::interval

            """, (user_id, group_id, RETURN_OFFER_COOLDOWN_DAYS))

            hecho = cur.rowcount > 0
            conn.commit()

            return hecho

    except Exception as e:

        conn.rollback()

        print("Recuperación de socio: error marcando la oferta:", e)

        # Sin poder marcar, no se envía: repetir el mensaje cada vez que
        # alguien entra y sale es la forma más rápida de que te bloqueen.
        return False


def fetch_stranded_buyers(group_id, since):
    """Quién se quedó sin enlace mientras la entrega estaba averiada.

    Los tres eventos que lo delatan ya se registraban: el enlace que no se
    pudo crear al pagar, el acceso guardado sin enlace, y el socio que pidió
    el suyo y no lo recibió. Con la entrega recuperada, esa gente sigue
    fuera con el acceso pagado — y nadie les avisa de que ya se puede
    entrar.

    Solo los que TODAVÍA tienen acceso vivo: a quien ya le caducó durante la
    avería no se le manda un enlace que no serviría.
    """

    if not since:
        return []

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT l.target_user_id
                FROM audit_logs l
                JOIN users u
                  ON u.user_id = l.target_user_id
                 AND u.group_id = l.group_id
                WHERE l.group_id = %s
                  AND l.created_at >= %s
                  AND l.event_type IN (
                      'payment_invite_link_error',
                      'payment_access_recorded_invite_link_pending',
                      'access_link_unavailable_for_paid_user'
                  )
                  AND l.target_user_id IS NOT NULL
                  AND (u.expiration IS NULL OR u.expiration > NOW())

            """, (group_id, since))

            return [fila[0] for fila in cur.fetchall() or []]

    except Exception as e:

        print("Recuperación de socio: error buscando a los que se quedaron "
              "fuera:", e)

        return []


def mark_recovery_notice(group_id, user_id, episode):
    """True si toca avisar. La clave es el episodio de avería, no el día:
    dos averías distintas merecen dos avisos, la misma no merece dos."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO delivery_recovery_notices
                    (group_id, user_id, episode)
                VALUES (%s, %s, %s)
                ON CONFLICT (group_id, user_id, episode) DO NOTHING

            """, (group_id, user_id, str(episode)))

            hecho = cur.rowcount > 0
            conn.commit()

            return hecho

    except Exception as e:

        conn.rollback()

        print("Recuperación de socio: error marcando el aviso de "
              "recuperación:", e)

        return False


def notify_stranded_buyers_after_recovery(group_id, group_name, since):
    """Manda enlace nuevo a quien se quedó fuera durante la avería.

    Es síncrono a propósito: se llama desde la comprobación de salud de
    entrega, que no vive en el bucle de asyncio del bot.
    """

    resumen = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    if not RETURN_OFFER_ENABLED:
        return resumen


    from i18n_service import load_user_language, t
    from notification_service import send_telegram_message

    # El id de Telegram se resuelve aquí: quien llama es la comprobación de
    # salud, que trabaja con el id interno.
    try:

        with conn.cursor() as cur:

            cur.execute(
                "SELECT telegram_group_id FROM groups WHERE id=%s",
                (group_id,)
            )
            fila = cur.fetchone()

        telegram_group_id = fila[0] if fila else None

    except Exception as e:

        print("Recuperación de socio: error resolviendo el grupo:", e)

        return resumen


    if not telegram_group_id:
        return resumen


    afectados = fetch_stranded_buyers(group_id, since)
    resumen["targets"] = len(afectados)

    for user_id in afectados:

        if not mark_recovery_notice(group_id, user_id, since):

            resumen["skipped"] += 1
            continue

        language = load_user_language(user_id)

        enlace = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=RETURN_LINK_EXPIRE_SECONDS,
            member_limit=1,
        )

        teclado = None

        if enlace:

            teclado = {"inline_keyboard": [[{
                "text": t("recovery.return_button", language),
                "url": enlace
            }]]}

        respuesta = send_telegram_message(
            TOKEN,
            user_id,
            t("recovery.delivery_fixed", language, group=group_name),
            reply_markup=teclado
        )

        if respuesta and respuesta.get("ok"):

            resumen["sent"] += 1

        else:

            resumen["failed"] += 1


    if resumen["sent"] or resumen["failed"]:

        log_event(
            "delivery_recovery_buyers_notified",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            message="Avisados los socios que se quedaron sin enlace.",
            metadata=resumen
        )

    return resumen


def build_return_message(group_name, expiration, language="es"):

    from group_subscription_service import formato_fecha
    from i18n_service import t

    hasta = formato_fecha(expiration) if expiration else None

    if hasta:

        return t("recovery.left_with_access_until", language,
                 group=group_name, until=hasta)

    return t("recovery.left_with_access", language, group=group_name)


async def offer_return_link(context, user_id, group_id):
    """Le manda un enlace nuevo si su acceso sigue vivo. True si se envió."""

    if not RETURN_OFFER_ENABLED:
        return False

    acceso = fetch_live_access(user_id, group_id)

    if not acceso:
        return False

    expiration, telegram_group_id, group_name = acceso

    if not mark_return_offer(user_id, group_id):
        return False


    from i18n_service import load_user_language, t
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    language = load_user_language(user_id)

    enlace = create_telegram_invite_link(
        TOKEN,
        telegram_group_id,
        expire_seconds=RETURN_LINK_EXPIRE_SECONDS,
        member_limit=1,
    )

    teclado = None

    if enlace:

        teclado = InlineKeyboardMarkup([[InlineKeyboardButton(
            t("recovery.return_button", language),
            url=enlace
        )]])

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=build_return_message(group_name, expiration, language),
            reply_markup=teclado,
        )

    except Exception as e:

        # Quien nunca abrió el bot no puede recibir el mensaje. Queda escrito
        # para que el propietario sepa que hay alguien pagando y fuera.
        log_event(
            "member_return_offer_failed",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Socio con acceso vivo fuera del grupo y sin poder avisarle.",
            metadata={"error": str(e)[:200], "link_ok": bool(enlace)}
        )

        return False


    log_event(
        "member_return_offer_sent",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Enlace de vuelta enviado a un socio con acceso vivo.",
        metadata={"link_ok": bool(enlace), "expiration": str(expiration)}
    )

    return True
