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
from invite_link_service import mask_invite_link
from message_templates import unauthorized_access_detected_text
from publicity_invite_link_service import (
    is_active_publicity_invite_link,
    normalize_telegram_invite_url
)
from telegram_group_actions import kick_chat_member


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


async def send_publicity_invite_welcome(update, context, member, group_id, telegram_group_id):

    group_title = getattr(update.message.chat, "title", None) or "esta comunidad"
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

        return

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


    try:

        display_name = member.first_name or "bienvenido"

        await update.message.reply_text(
            f"👋 Bienvenido/a, {display_name}. Este grupo forma parte de nuestra red de comunidades. Abre el bot para descubrir grupos gratuitos y premium.",
            reply_markup=keyboard
        )

        log_event(
            "publicity_invite_welcome_group_fallback_sent",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=member.id,
            target_user_id=member.id,
            message="Bienvenida de publicidad enviada como fallback en grupo.",
            metadata={}
        )

    except Exception as e:

        log_event(
            "publicity_invite_welcome_group_fallback_failed",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=member.id,
            target_user_id=member.id,
            message="No se pudo enviar bienvenida de publicidad como fallback en grupo.",
            metadata={
                "error": str(e)[:300]
            }
        )


async def detect_user_join(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    if not update.message.new_chat_members:
        return


    telegram_group_id = update.message.chat.id


    for member in update.message.new_chat_members:

        user_id = member.id
        username = member.username
        first_name = member.first_name


        # Evitar verificar al propio bot

        if user_id == context.bot.id:
            continue


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

                    invite_link_used = None


                    try:

                        if update.message.invite_link:

                            invite_link_used = update.message.invite_link.invite_link

                    except Exception:

                        invite_link_used = None


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


                invite_link_used = None


                try:

                    if update.message.invite_link:

                        invite_link_used = update.message.invite_link.invite_link

                except Exception:

                    invite_link_used = None


                normalized_publicity_invite_link = normalize_telegram_invite_url(invite_link_used)
                publicity_link_matched = False
                publicity_check_reason = "no_invite_link_reported" if not invite_link_used else "invite_link_not_authorized"


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

                    await send_publicity_invite_welcome(
                        update,
                        context,
                        member,
                        group_id,
                        telegram_group_id
                    )

                    continue


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

                    await send_publicity_invite_welcome(
                        update,
                        context,
                        member,
                        group_id,
                        telegram_group_id
                    )

                    continue


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


                if not access_is_active:

                    print(
                        "Usuario sin acceso válido:",
                        user_id
                    )


                    kick_chat_member(

                        TOKEN,

                        telegram_group_id,

                        user_id

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


                    continue


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


                # =========================
                # SI EXPIRADO → EXPULSAR
                # =========================

                if expiration and datetime.now() > expiration:

                    print(
                        "Usuario expirado detectado:",
                        user_id
                    )


                    kick_chat_member(

                        TOKEN,

                        telegram_group_id,

                        user_id

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


                    continue


        except Exception as e:

            print(
                "Error verificando usuario:",
                e
            )   
