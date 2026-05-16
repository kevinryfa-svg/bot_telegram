import os

from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import ContextTypes

from db import conn

from telegram_group_actions import kick_chat_member


TOKEN = os.environ.get("TOKEN")
ADMIN_ID = 8761243211


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
                # VERIFICAR SUSCRIPCIÓN
                # =========================

                cur.execute("""

                    SELECT expiration

                    FROM users

                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    group_id

                ))

                user_row = cur.fetchone()


                # =========================
                # SI NO EXISTE → LINK NO REGISTRADO
                # =========================

                if not user_row:

                    print(
                        "Usuario sin suscripción:",
                        user_id
                    )


                    keyboard = [

                        [

                            InlineKeyboardButton(
                                "✅ ACEPTAR",
                                callback_data=
                                f"allow_user_{user_id}_{group_id}"
                            )

                        ],

                        [

                            InlineKeyboardButton(
                                "❌ EXPULSAR",
                                callback_data=
                                f"deny_user_{user_id}_{group_id}"
                            )

                        ]

                    ]


                    try:

                        await context.bot.send_message(

                            chat_id=ADMIN_ID,

                            text=

                            "🚨 ACCESO NO AUTORIZADO DETECTADO\n\n"

                            f"Usuario: {first_name}\n"

                            f"Username: @{username}\n"

                            f"ID: {user_id}\n\n"

                            "Ha entrado con un link no registrado.\n\n"

                            "¿Deseas permitirlo o expulsarlo?",

                            reply_markup=
                            InlineKeyboardMarkup(keyboard)

                        )

                    except Exception as e:

                        print(
                            "Error enviando aviso admin:",
                            e
                        )


                    return


                expiration = user_row[0]


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
