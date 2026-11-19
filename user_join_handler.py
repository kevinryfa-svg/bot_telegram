from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import ContextTypes

from audit_log_service import log_event
from bot_config import TOKEN, ADMIN_ID
from db import conn
from guardian_service import send_guardian_event_log
from invite_link_service import mask_invite_link
from message_templates import unauthorized_access_detected_text
from payment_access_service import get_user_group_access_state
from publicity_invite_link_service import (
    has_active_publicity_invite_links_for_group,
    is_active_publicity_invite_link,
    normalize_telegram_invite_url
)
from telegram_group_actions import kick_chat_member


# =========================
# POR DÓNDE SE ENTERA EL BOT DE QUE ALGUIEN HA ENTRADO
# =========================
# Dos vías, y dicen cosas distintas:
#
#   ORIGEN_MENSAJE       el mensaje de servicio «X se ha unido». Llega siempre
#                        que el grupo no oculte esos mensajes, pero NO dice con
#                        qué enlace se entró.
#   ORIGEN_CHAT_MEMBER   la actualización chat_member. Trae el enlace usado
#                        (ChatMemberUpdated.invite_link), y llega aunque el
#                        grupo oculte los mensajes de entrada. Necesita que el
#                        bot sea administrador y que se pida al arrancar.
#
# Las dos pueden llegar por la misma entrada: la primera que decide, decide, y
# la otra se ignora durante un rato.
ORIGEN_MENSAJE = "mensaje"
ORIGEN_CHAT_MEMBER = "chat_member"

SEGUNDOS_PARA_NO_EVALUAR_DOS_VECES = 120

_ENTRADAS_RECIENTES = {}


def _clave_de_entrada(telegram_group_id, user_id):

    return (int(telegram_group_id), int(user_id))


def ya_evaluada(telegram_group_id, user_id, ahora=None):
    """True si esta entrada se evaluó hace menos de dos minutos."""

    import time

    ahora = time.monotonic() if ahora is None else ahora

    # Limpieza perezosa: sin esto el diccionario crecería con cada entrada.
    for clave, cuando in list(_ENTRADAS_RECIENTES.items()):
        if ahora - cuando > SEGUNDOS_PARA_NO_EVALUAR_DOS_VECES:
            _ENTRADAS_RECIENTES.pop(clave, None)

    cuando = _ENTRADAS_RECIENTES.get(_clave_de_entrada(telegram_group_id, user_id))

    return cuando is not None and ahora - cuando <= SEGUNDOS_PARA_NO_EVALUAR_DOS_VECES


def marcar_entrada(telegram_group_id, user_id, ahora=None):

    import time

    _ENTRADAS_RECIENTES[_clave_de_entrada(telegram_group_id, user_id)] = (
        time.monotonic() if ahora is None else ahora
    )


def olvidar_entrada(telegram_group_id, user_id):
    """Para cuando una vía decide NO decidir y se la deja a la otra."""

    _ENTRADAS_RECIENTES.pop(_clave_de_entrada(telegram_group_id, user_id), None)


# =========================
# EXPULSAR, Y COMPROBAR QUE DE VERDAD SE HA EXPULSADO
# =========================
# kick_chat_member devolvía la respuesta de Telegram y nadie la miraba. Si al
# bot le falta el permiso de expulsar en el grupo, Telegram contesta «not
# enough rights», el bot apuntaba «Usuario expulsado» y la persona se quedaba
# dentro. Ahora se mira, y si no ha funcionado se avisa al administrador con
# el motivo que da Telegram.

def expulsion_fallida(resultado):
    """None si la expulsión funcionó; si no, el motivo en palabras."""

    ban = (resultado or {}).get("ban") if isinstance(resultado, dict) else None

    if not ban:
        return "no se pudo hablar con Telegram"

    if ban.get("ok"):
        return None

    return str(ban.get("description") or "Telegram la rechazó sin decir por qué")


async def expulsar_y_comprobar(context, telegram_group_id, group_id, member, motivo):
    """Expulsa y devuelve True si Telegram lo confirma. Avisa si no."""

    resultado = kick_chat_member(TOKEN, telegram_group_id, member.id)

    fallo = expulsion_fallida(resultado)

    if not fallo:
        return True

    print(
        f"Expulsión FALLIDA de {member.id} en {telegram_group_id}:", fallo
    )

    log_event(
        "access_kick_failed",
        category="access",
        severity="error",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=member.id,
        target_user_id=member.id,
        message="El bot intentó expulsar a alguien sin acceso y Telegram no lo permitió.",
        metadata={"motivo": motivo, "telegram": fallo[:300]},
    )

    try:

        sin_permiso = "rights" in fallo.lower() or "admin" in fallo.lower()

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🚨 Alguien ha entrado SIN ACCESO y NO he podido expulsarlo.\n\n"
                f"Usuario: {member.first_name or ''} "
                f"(@{member.username or '-'}, {member.id})\n"
                f"Grupo: {telegram_group_id}\n"
                f"Telegram dice: {fallo[:200]}\n\n"
                + (
                    "Al bot le falta el permiso de expulsar en ese grupo. "
                    "Hazlo administrador con «Expulsar usuarios» y expúlsalo "
                    "a mano esta vez."
                    if sin_permiso else
                    "Expúlsalo a mano y revisa los permisos del bot en el grupo."
                )
            ),
        )

    except Exception as e:

        print("Expulsión fallida: no se pudo avisar al admin:", str(e)[:200])

    return False


# =========================
# DETECTAR USUARIO ENTRANDO AL GRUPO
# =========================

def is_free_community_group(group_id, telegram_group_id):

    if not group_id or not telegram_group_id:

        return False


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(is_free_group, FALSE)
                FROM groups
                WHERE id=%s
                AND telegram_group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                LIMIT 1

            """, (
                group_id,
                telegram_group_id
            ))

            row = cur.fetchone()

            return bool(row and row[0] is True)

    except Exception as e:

        try:

            conn.rollback()

        except Exception:

            pass

        log_event(
            "free_community_user_access_upsert_failed",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            message="No se pudo comprobar si la comunidad es gratuita.",
            metadata={
                "error": str(e)[:300]
            }
        )

        return False


def ensure_free_community_user_access(user_id, group_id, username, first_name, invite_link_used=None):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET username=%s,
                    first_name=%s,
                    expiration=NULL,
                    subscription_active=TRUE,
                    last_invite_link=COALESCE(%s, last_invite_link)
                WHERE user_id=%s
                AND group_id=%s

            """, (
                username,
                first_name,
                invite_link_used,
                user_id,
                group_id
            ))

            if cur.rowcount == 0:

                cur.execute("""

                    INSERT INTO users
                    (
                        user_id,
                        group_id,
                        username,
                        first_name,
                        expiration,
                        subscription_active,
                        last_invite_link
                    )
                    VALUES (%s, %s, %s, %s, NULL, TRUE, %s)

                """, (
                    user_id,
                    group_id,
                    username,
                    first_name,
                    invite_link_used
                ))

            cur.execute("""

                SELECT user_id,
                       group_id,
                       COALESCE(subscription_active, FALSE),
                       expiration
                FROM users
                WHERE user_id=%s
                AND group_id=%s
                LIMIT 1

            """, (
                user_id,
                group_id
            ))

            verify_row = cur.fetchone()

            conn.commit()

        if verify_row:

            log_event(
                "free_community_user_access_verified",
                category="access",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Registro de acceso gratuito/permanente verificado en users.",
                metadata={
                    "user_id": verify_row[0],
                    "group_id": verify_row[1],
                    "subscription_active": verify_row[2],
                    "expiration": str(verify_row[3]) if verify_row[3] else None
                }
            )

        else:

            log_event(
                "free_community_user_access_verify_missing",
                category="access",
                severity="error",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="No se encontró en users el registro gratuito tras guardarlo.",
                metadata={
                    "user_id": user_id,
                    "group_id": group_id
                }
            )

        log_event(
            "free_community_user_access_upserted",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Usuario registrado con acceso gratuito/permanente.",
            metadata={
                "user_id": user_id,
                "group_id": group_id,
                "username": username,
                "first_name": first_name,
                "invite_link_present": invite_link_used is not None
            }
        )

        return True

    except Exception as e:

        try:

            conn.rollback()

        except Exception:

            pass

        log_event(
            "free_community_user_access_upsert_failed",
            category="access",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="No se pudo registrar acceso gratuito/permanente.",
            metadata={
                "user_id": user_id,
                "group_id": group_id,
                "username": username,
                "first_name": first_name,
                "invite_link_present": invite_link_used is not None,
                "error": str(e)[:500]
            }
        )

        return False


async def send_publicity_invite_welcome(group_title, context, member, group_id, telegram_group_id):

    group_title = group_title or "esta comunidad"
    bot_username = getattr(context.bot, "username", None) or "TheStarVipBOT"
    bot_url = f"https://t.me/{bot_username}?start=publicity_{telegram_group_id}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Abrir menú principal", url=bot_url)]
    ])
    text = (
        f"👋 ¡Bienvenido/a a {group_title}!\n\n"
        "Has entrado en una comunidad conectada a nuestro bot.\n\n"
        "Aquí podrás descubrir grupos gratuitos y también comunidades premium con contenido exclusivo, "
        "accesos privados y experiencias más cuidadas.\n\n"
        "Desde el menú principal puedes:\n"
        "• Ver comunidades disponibles\n"
        "• Entrar en grupos gratuitos\n"
        "• Suscribirte a grupos premium\n"
        "• Gestionar tus accesos\n\n"
        "Pulsa el botón de abajo para abrir el menú principal 👇"
    )


    try:

        await context.bot.send_message(
            chat_id=member.id,
            text=text,
            reply_markup=keyboard
        )

        return True

    except Exception as e:

        log_event(
            "publicity_invite_welcome_dm_failed",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=member.id,
            target_user_id=member.id,
            message="No se pudo enviar bienvenida privada por link público de publicidad.",
            metadata={
                "error": str(e)[:300]
            }
        )

    # No enviamos fallback en grupo para no ensuciar comunidades públicas.
    return False


async def detect_user_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entrada por el MENSAJE DE SERVICIO «X se ha unido al grupo».

    Ese mensaje no dice con qué enlace entró la persona: el campo invite_link
    no existe en un Message de Telegram, solo en las actualizaciones
    chat_member. Este manejador lo leía igualmente, siempre le salía vacío, y
    eso abría la puerta de abajo. Ahora le pasa a `evaluar_entrada` que no
    sabe el enlace, y la decisión que depende del enlace la toma
    `detect_user_join_chat_member`, que sí lo tiene.
    """

    if not update.message:
        return

    if not update.message.new_chat_members:
        return


    telegram_group_id = update.message.chat.id
    group_title = getattr(update.message.chat, "title", None)


    for member in update.message.new_chat_members:

        await evaluar_entrada(
            context,
            telegram_group_id,
            member,
            invite_link_used=None,
            origen=ORIGEN_MENSAJE,
            group_title=group_title
        )


async def evaluar_entrada(context, telegram_group_id, member,
                          invite_link_used=None, origen=ORIGEN_MENSAJE,
                          group_title=None):
    """Decide si una persona que acaba de entrar se queda o se va."""

    user_id = member.id
    username = member.username
    first_name = member.first_name


    # Evitar verificar al propio bot

    if user_id == context.bot.id:
        return


    # La misma entrada puede llegar por el mensaje de servicio y por
    # chat_member: se decide una vez.
    if ya_evaluada(telegram_group_id, user_id):
        return

    marcar_entrada(telegram_group_id, user_id)


    log_event(
        "user_join_detected",
        category="access",
        severity="info",
        scope="group",
        telegram_group_id=telegram_group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Entrada de usuario registrada.",
        metadata={
            "username": username,
            "first_name": first_name
        }
    )


    try:

        with conn.cursor() as cur:

            # =========================
            # OBTENER group_id REAL
            # =========================

            cur.execute("""

                SELECT id

                FROM groups

                WHERE telegram_group_id=%s

            """, (telegram_group_id,))

            group_row = cur.fetchone()


            if not group_row:


                print(
                    "Grupo no encontrado en DB:",
                    telegram_group_id
                )

                log_event(
                    "user_join_group_not_found",
                    category="access",
                    severity="warning",
                    scope="group",
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Usuario entró en un grupo no registrado."
                )

                log_event(
                    "publicity_invite_link_not_matched",
                    category="access",
                    severity="warning",
                    scope="group",
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="No se pudo validar link de publicidad porque no se resolvió group_id.",
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "invite_link_present": invite_link_used is not None,
                        "invite_link": mask_invite_link(invite_link_used),
                        "reason": "group_id_not_resolved"
                    }
                )

                return


            group_id = group_row[0]


            # =========================
            # VERIFICAR SUSCRIPCIÓN Y LINK DEL BOT
            # =========================

            cur.execute("""

                SELECT expiration,
                       subscription_active

                FROM users

                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                group_id

            ))

            user_row = cur.fetchone()



            normalized_publicity_invite_link = normalize_telegram_invite_url(invite_link_used)
            publicity_link_matched = False
            publicity_check_reason = "no_invite_link_reported" if not invite_link_used else "invite_link_not_authorized"
            publicity_group_enabled = False


            try:

                publicity_group_enabled = has_active_publicity_invite_links_for_group(
                    group_id,
                    telegram_group_id
                )

            except Exception as e:

                try:

                    conn.rollback()

                except Exception:

                    pass

                publicity_group_enabled = False
                log_event(
                    "publicity_invite_group_check_error",
                    category="access",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="No se pudo comprobar si el grupo tiene publicidad activa.",
                    metadata={
                        "error": str(e)[:300]
                    }
                )


            if invite_link_used:

                try:

                    publicity_link_matched = is_active_publicity_invite_link(invite_link_used, telegram_group_id)
                    publicity_check_reason = "matched" if publicity_link_matched else "invite_link_not_authorized"

                except Exception as e:

                    try:

                        conn.rollback()

                    except Exception:

                        pass

                    publicity_link_matched = False
                    publicity_check_reason = "publicity_check_error"
                    log_event(
                        "publicity_invite_link_not_matched",
                        category="access",
                        severity="warning",
                        scope="group",
                        group_id=group_id,
                        telegram_group_id=telegram_group_id,
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        message="Error comprobando link autorizado de publicidad.",
                        metadata={
                            "user_id": user_id,
                            "username": username,
                            "first_name": first_name,
                            "invite_link_present": True,
                            "invite_link": mask_invite_link(invite_link_used),
                            "normalized_invite_link": mask_invite_link(normalized_publicity_invite_link),
                            "reason": publicity_check_reason,
                            "error": str(e)[:300]
                        }
                    )


            log_event(
                "publicity_invite_join_detected",
                category="access",
                severity="info",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Entrada evaluada contra links autorizados de publicidad.",
                metadata={
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "invite_link_present": invite_link_used is not None,
                    "invite_link": mask_invite_link(invite_link_used),
                    "normalized_invite_link": mask_invite_link(normalized_publicity_invite_link),
                    "publicity_link_matched": publicity_link_matched,
                    "publicity_group_enabled": publicity_group_enabled,
                    "reason": publicity_check_reason
                }
            )


            if not invite_link_used:

                log_event(
                    "publicity_invite_link_missing_on_join",
                    category="access",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Telegram no informó invite_link en una entrada al grupo.",
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "reason": "no_invite_link_reported"
                    }
                )

            elif publicity_link_matched:

                log_event(
                    "publicity_invite_link_matched",
                    category="access",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Usuario entró con link autorizado de publicidad.",
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "invite_link": mask_invite_link(invite_link_used),
                        "normalized_invite_link": mask_invite_link(normalized_publicity_invite_link)
                    }
                )

            else:

                log_event(
                    "publicity_invite_link_not_matched",
                    category="access",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Usuario entró con invite_link no autorizado como publicidad.",
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "invite_link": mask_invite_link(invite_link_used),
                        "normalized_invite_link": mask_invite_link(normalized_publicity_invite_link),
                        "reason": publicity_check_reason
                    }
                )


            if publicity_link_matched:

                log_event(
                    "publicity_invite_link_used",
                    category="access",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Usuario entró usando link público de publicidad activo.",
                    metadata={
                        "username": username,
                        "first_name": first_name
                    }
                )

                await send_guardian_event_log(
                    context,
                    group_id,
                    "guardian_user_join_allowed",
                    "Entrada permitida por link autorizado de publicidad.",
                    telegram_group_id=telegram_group_id,
                    severity="info",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "access_type": "publicity_invite"
                    }
                )

                await send_publicity_invite_welcome(
                    group_title,
                    context,
                    member,
                    group_id,
                    telegram_group_id
                )

                return


            # =========================
            # LA PUERTA QUE DEJABA ENTRAR A CUALQUIERA
            # =========================
            # Aquí ponía: «si la comunidad tiene publicidad activa y Telegram
            # no informó el enlace, se deja entrar». Pero el mensaje de
            # servicio de entrada NO trae el enlace nunca —el campo no existe
            # en un Message—, así que en cuanto una comunidad tenía un solo
            # enlace de publicidad activo, CUALQUIER enlace dejaba entrar a
            # cualquiera, sin pagar y sin que el bot expulsara a nadie.
            #
            # Ahora:
            #   - por el mensaje de servicio, en un grupo con publicidad, no
            #     se decide: lo decide la actualización chat_member, que sí
            #     trae el enlace y llega a la vez;
            #   - por chat_member, sin enlace (alguien añadido a mano, o un
            #     grupo público por su @usuario) ya no se da por bueno: pasa a
            #     comprobar el acceso como cualquier otro.
            if publicity_group_enabled and origen == ORIGEN_MENSAJE:

                olvidar_entrada(telegram_group_id, user_id)

                log_event(
                    "publicity_join_deferred_to_chat_member",
                    category="access",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Entrada en grupo con publicidad: la decide chat_member, que trae el enlace.",
                    metadata={
                        "username": username,
                        "first_name": first_name,
                    }
                )

                return


            if is_free_community_group(group_id, telegram_group_id):

                free_access_saved = ensure_free_community_user_access(
                    user_id,
                    group_id,
                    username,
                    first_name,
                    invite_link_used
                )

                log_event(
                    "free_community_join_allowed",
                    category="access",
                    severity="info" if free_access_saved else "warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Entrada permitida en comunidad gratuita.",
                    metadata={
                        "username": username,
                        "first_name": first_name,
                        "invite_link_present": invite_link_used is not None,
                        "access_saved": free_access_saved
                    }
                )

                await send_guardian_event_log(
                    context,
                    group_id,
                    "guardian_user_join_allowed",
                    "Entrada permitida en comunidad gratuita.",
                    telegram_group_id=telegram_group_id,
                    severity="info" if free_access_saved else "warning",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "access_type": "free_community",
                        "access_saved": free_access_saved
                    }
                )

                await send_publicity_invite_welcome(
                    group_title,
                    context,
                    member,
                    group_id,
                    telegram_group_id
                )

                return


            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )
                AND is_active=TRUE
                ORDER BY created_at DESC
                LIMIT 1

            """, (
                user_id,
                group_id,
                telegram_group_id,
                telegram_group_id
            ))

            invite_row = cur.fetchone()


            if invite_link_used:

                cur.execute("""

                    SELECT invite_link
                    FROM invite_links
                    WHERE user_id=%s
                    AND invite_link=%s
                    AND (
                        group_id=%s
                        OR telegram_group_id=%s
                        OR group_id=%s
                    )
                    AND is_active=TRUE
                    LIMIT 1

                """, (
                    user_id,
                    invite_link_used,
                    group_id,
                    telegram_group_id,
                    telegram_group_id
                ))

                exact_invite_row = cur.fetchone()


                if exact_invite_row:

                    invite_row = exact_invite_row


            link_is_valid = invite_row is not None


            if invite_link_used and invite_row:

                link_is_valid = invite_link_used == invite_row[0]


            # =========================
            # SI NO EXISTE ACCESO ACTIVO → EXPULSAR
            # =========================

            expiration = user_row[0] if user_row else None
            subscription_active = user_row[1] is True if user_row else False
            access_is_active = (
                subscription_active
                and (
                    expiration is None
                    or datetime.now() <= expiration
                )
            )

            access_state = None

            if not access_is_active:

                try:

                    access_state = get_user_group_access_state(user_id, group_id)

                except Exception as e:

                    try:

                        conn.rollback()

                    except Exception:

                        pass

                    print("access_guard_state_check_error:", str(e)[:300])
                    access_state = None


                if (
                    access_state
                    and (
                        access_state.get("has_active_access")
                        or access_state.get("subscription_status") == "paid_without_access_record"
                    )
                ):

                    log_event(
                        "access_guard_allowed_by_access_state",
                        category="access",
                        severity="info",
                        scope="group",
                        group_id=group_id,
                        telegram_group_id=telegram_group_id,
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        message="Entrada permitida por estado agregado de acceso.",
                        metadata={
                            "username": username,
                            "first_name": first_name,
                            "access_source": access_state.get("access_source"),
                            "subscription_status": access_state.get("subscription_status"),
                            "reason": access_state.get("reason")
                        }
                    )

                    await send_guardian_event_log(
                        context,
                        group_id,
                        "guardian_user_join_allowed",
                        "Entrada permitida por estado agregado de acceso.",
                        telegram_group_id=telegram_group_id,
                        severity="info",
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        metadata={
                            "user_id": user_id,
                            "username": username,
                            "first_name": first_name,
                            "access_type": access_state.get("access_source"),
                            "subscription_status": access_state.get("subscription_status"),
                            "reason": access_state.get("reason")
                        }
                    )

                    return


            if not access_is_active:

                print(
                    "Usuario sin acceso válido:",
                    user_id
                )


                await expulsar_y_comprobar(
                    context, telegram_group_id, group_id, member, "sin_acceso"
                )

                log_event(
                    "access_unauthorized",
                    category="access",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Acceso no autorizado detectado. Usuario expulsado.",
                    metadata={
                        "username": username,
                        "first_name": first_name,
                        "has_user_row": user_row is not None,
                        "subscription_active": subscription_active,
                        "link_is_valid": link_is_valid,
                        "invite_link_present": invite_link_used is not None
                    }
                )

                await send_guardian_event_log(
                    context,
                    group_id,
                    "guardian_user_join_blocked",
                    "Acceso no autorizado detectado. Se mantuvo el comportamiento actual del access guard.",
                    telegram_group_id=telegram_group_id,
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "has_user_row": user_row is not None,
                        "subscription_active": subscription_active,
                        "link_is_valid": link_is_valid,
                        "invite_link_present": invite_link_used is not None,
                        "invite_link_masked": mask_invite_link(invite_link_used)
                    }
                )


                try:

                    await context.bot.send_message(

                        chat_id=ADMIN_ID,

                        text=unauthorized_access_detected_text(
                            first_name,
                            username,
                            user_id
                        )

                    )

                except Exception as e:

                    print(
                        "Error enviando aviso admin:",
                        e
                    )

                    log_event(
                        "unauthorized_access_admin_notification_error",
                        category="notification",
                        severity="warning",
                        scope="group",
                        group_id=group_id,
                        telegram_group_id=telegram_group_id,
                        actor_user_id=user_id,
                        target_user_id=ADMIN_ID,
                        message="No se pudo avisar al admin de acceso no autorizado.",
                        metadata={
                            "error": str(e)
                        }
                    )


                return


            if not link_is_valid:

                print(
                    "WARNING: usuario con acceso activo entró sin link registrado:",
                    user_id,
                    "group_id:",
                    group_id,
                    "telegram_group_id:",
                    telegram_group_id
                )


                if invite_link_used:

                    cur.execute("""

                        UPDATE invite_links
                        SET telegram_group_id=%s,
                            invite_link=%s,
                            is_active=TRUE,
                            revoked_at=NULL
                        WHERE user_id=%s
                        AND group_id=%s

                    """, (
                        telegram_group_id,
                        invite_link_used,
                        user_id,
                        group_id
                    ))


                    if cur.rowcount == 0:

                        cur.execute("""

                            INSERT INTO invite_links
                            (
                                user_id,
                                group_id,
                                telegram_group_id,
                                invite_link,
                                is_active
                            )
                            VALUES (%s, %s, %s, %s, TRUE)

                        """, (
                            user_id,
                            group_id,
                            telegram_group_id,
                            invite_link_used
                        ))


                    conn.commit()


                log_event(
                    "access_allowed_active_payment_fallback",
                    category="access",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Entrada permitida por pago activo aunque faltaba link registrado.",
                    metadata={
                        "invite_link_present": invite_link_used is not None
                    }
                )

                await send_guardian_event_log(
                    context,
                    group_id,
                    "guardian_user_join_allowed",
                    "Entrada permitida por pago/acceso activo aunque faltaba link registrado.",
                    telegram_group_id=telegram_group_id,
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "access_type": "active_payment_fallback",
                        "invite_link_present": invite_link_used is not None
                    }
                )


            if invite_row:

                cur.execute("""

                    UPDATE invite_links
                    SET is_active=FALSE,
                        revoked_at=NOW()
                    WHERE invite_link=%s

                """, (invite_row[0],))


                conn.commit()


                log_event(
                    "access_join_valid_link",
                    category="access",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Usuario entró con link registrado válido."
                )

                await send_guardian_event_log(
                    context,
                    group_id,
                    "guardian_user_join_allowed",
                    "Usuario entró con link registrado válido.",
                    telegram_group_id=telegram_group_id,
                    severity="info",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "access_type": "registered_invite_link"
                    }
                )


            # =========================
            # SI EXPIRADO → EXPULSAR
            # =========================

            if expiration and datetime.now() > expiration:

                print(
                    "Usuario expirado detectado:",
                    user_id
                )


                await expulsar_y_comprobar(
                    context, telegram_group_id, group_id, member, "caducado"
                )


                log_event(
                    "access_expired",
                    category="access",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Usuario expulsado por acceso expirado."
                )

                await send_guardian_event_log(
                    context,
                    group_id,
                    "guardian_user_join_blocked",
                    "Usuario expulsado por acceso expirado.",
                    telegram_group_id=telegram_group_id,
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    metadata={
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "access_type": "expired",
                        "expiration": expiration
                    }
                )


                return


    except Exception as e:

        print(
            "Error verificando usuario:",
            e
        )   



# =========================
# LA ENTRADA POR chat_member, QUE SÍ TRAE EL ENLACE
# =========================

ESTADOS_DE_ESTAR_DENTRO = ("member", "restricted", "administrator", "creator")


def _esta_dentro(chat_member):

    if chat_member is None:
        return False

    estado = getattr(chat_member, "status", None)

    if estado == "restricted":
        # Restringido puede ser «dentro con limitaciones» o «fuera»: lo dice
        # is_member.
        return bool(getattr(chat_member, "is_member", False))

    return estado in ESTADOS_DE_ESTAR_DENTRO


def es_una_entrada(actualizacion):
    """
    True si esta actualización chat_member es alguien que ENTRA como miembro.

    No cuentan: los cambios de quien ya estaba dentro (ascensos, permisos),
    las salidas, ni quien entra directamente como administrador —a ese lo ha
    puesto el dueño y no se le expulsa—.
    """

    if actualizacion is None:
        return False

    antes = getattr(actualizacion, "old_chat_member", None)
    ahora = getattr(actualizacion, "new_chat_member", None)

    if _esta_dentro(antes) or not _esta_dentro(ahora):
        return False

    return getattr(ahora, "status", None) in ("member", "restricted")


def enlace_de_la_entrada(actualizacion):
    """El enlace con el que entró, o None (añadido a mano, grupo público…)."""

    enlace = getattr(actualizacion, "invite_link", None)

    return getattr(enlace, "invite_link", None) if enlace else None


async def detect_user_join_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entrada por la actualización chat_member.

    Es la única vía que sabe con qué enlace entró la persona, así que es la que
    decide en las comunidades con publicidad. Y llega aunque el grupo tenga
    ocultos los mensajes de «X se ha unido».

    Solo grupos y supergrupos: los canales no han tenido nunca este control, y
    encenderlo de golpe ahí cambiaría qué les pasa a sus suscriptores, que es
    otra decisión.
    """

    actualizacion = getattr(update, "chat_member", None)

    if not es_una_entrada(actualizacion):
        return

    chat = actualizacion.chat

    if getattr(chat, "type", None) not in ("group", "supergroup"):
        return

    await evaluar_entrada(
        context,
        chat.id,
        actualizacion.new_chat_member.user,
        invite_link_used=enlace_de_la_entrada(actualizacion),
        origen=ORIGEN_CHAT_MEMBER,
        group_title=getattr(chat, "title", None)
    )
