from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import ContextTypes

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
                    AND group_id IN (%s, %s)
                    AND is_active=TRUE
                    ORDER BY created_at DESC
                    LIMIT 1

                """, (
                    user_id,
                    group_id,
                    telegram_group_id
                ))

                invite_row = cur.fetchone()


                link_is_valid = invite_row is not None


                if invite_link_used and invite_row:

                    link_is_valid = invite_link_used == invite_row[0]


                # =========================
                # SI NO EXISTE O NO TIENE LINK VÁLIDO → EXPULSAR
                # =========================

                if not user_row or not user_row[1] or not link_is_valid:

                    print(
                        "Usuario sin acceso válido:",
                        user_id
                    )


                    kick_chat_member(

                        TOKEN,

                        telegram_group_id,

                        user_id

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


                    return


                expiration = user_row[0]


                if invite_row:

                    cur.execute("""

                        UPDATE invite_links
                        SET is_active=FALSE,
                            revoked_at=NOW()
                        WHERE invite_link=%s

                    """, (invite_row[0],))


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


                    return


        except Exception as e:

            print(
                "Error verificando usuario:",
                e
            )   
