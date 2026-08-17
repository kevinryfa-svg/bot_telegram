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
