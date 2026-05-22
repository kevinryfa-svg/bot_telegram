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
from message_templates import unauthorized_access_detected_text
from telegram_group_actions import kick_chat_member


# =========================
# DETECTAR USUARIO ENTRANDO AL GRUPO
# =========================

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
            return


        print(
            "Usuario detectado entrando:",
            user_id
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


                    return


        except Exception as e:

            print(
                "Error verificando usuario:",
                e
            )   
