from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from commercial_catalog import (
    PUBLIC_START_TEXT_ES,
    CALLBACK_MONETIZE_COMMUNITY,
    CALLBACK_SUPPORT,
    CALLBACK_AI_HELP,
    CALLBACK_ADMIN_PANEL
)
from db import conn
from formatters import (
    format_tiempo_restante
)
from rbac_helpers import is_super_admin


# =========================
# START BOT — MENÚ COMERCIAL
# =========================

async def send_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id=None):

    user_id = update.effective_user.id


    # =========================
    # OBTENER GRUPOS ACTIVOS
    # =========================

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name

                FROM groups

                WHERE is_active=TRUE
                AND telegram_group_id != 0

                ORDER BY id ASC

            """)

            groups = cur.fetchall()

    except Exception as e:

        print("Error cargando grupos:", e)

        message = update.message or (
            update.callback_query.message
            if update.callback_query
            else None
        )

        if chat_id:

            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Error cargando comunidades disponibles."
            )

        elif message:

            await message.reply_text(
                "❌ Error cargando comunidades disponibles."
            )

        return


    # =========================
    # CREAR BOTONES PRINCIPALES
    # =========================

    keyboard = []


    if groups:

        keyboard.append([

            InlineKeyboardButton(

                "🔥 Explorar comunidades privadas",

                callback_data="start_explore_groups"

            )

        ])


        for group_id, group_name in groups:

            keyboard.append([

                InlineKeyboardButton(

                    group_name,

                    callback_data=f"group_{group_id}"

                )

            ])

    else:

        keyboard.append([

            InlineKeyboardButton(

                "🔥 Comunidades privadas próximamente",

                callback_data="start_no_groups"

            )

        ])


    # =========================
    # BOTÓN MIS SUSCRIPCIONES
    # =========================

    has_subscriptions = False

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1

                FROM users

                WHERE user_id=%s
                AND (
                    expiration IS NULL
                    OR expiration > %s
                )

                LIMIT 1

            """, (user_id, datetime.now()))

            has_subscriptions = cur.fetchone() is not None

    except Exception as e:

        print("Error verificando suscripciones:", e)


    if has_subscriptions:

        keyboard.append([

            InlineKeyboardButton(

                "🎟 Gestionar mi acceso",

                callback_data="mis_subs"

            )

        ])

    else:

        keyboard.append([

            InlineKeyboardButton(

                "🎟 Ya tengo acceso / recuperar enlace",

                callback_data="mis_subs"

            )

        ])


    # =========================
    # BOTONES COMERCIALES PÚBLICOS
    # =========================

    keyboard.append([

        InlineKeyboardButton(

            "🚀 Soluciones para mi comunidad",

            callback_data=CALLBACK_MONETIZE_COMMUNITY

        )

    ])


    keyboard.append([

        InlineKeyboardButton(

            "🛟 Soporte",

            callback_data=CALLBACK_SUPPORT

        ),

        InlineKeyboardButton(

            "💬 Ayuda sobre este menú",

            callback_data=CALLBACK_AI_HELP

        )

    ])


    # =========================
    # PANEL SEGÚN JERARQUÍA REAL
    # =========================

    try:

        if is_super_admin(user_id):

            keyboard.append([

                InlineKeyboardButton(

                    "⚙️ Panel global",

                    callback_data=CALLBACK_ADMIN_PANEL

                )

            ])

        else:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT 1

                    FROM admins

                    WHERE user_id=%s
                    AND is_active=TRUE

                    LIMIT 1

                """, (user_id,))

                admin_row = cur.fetchone()


            if admin_row:

                keyboard.append([

                    InlineKeyboardButton(

                        "⚙️ Mi panel de gestión",

                        callback_data=CALLBACK_ADMIN_PANEL

                    )

                ])

    except Exception as e:

        print("Error verificando panel admin:", e)


    # =========================
    # COMPROBAR SUSCRIPCIONES ACTIVAS
    # =========================

    suscripciones_texto = ""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT g.name, u.expiration

                FROM users u

                JOIN groups g
                ON u.group_id = g.id

                WHERE u.user_id=%s

                ORDER BY g.name ASC

            """, (user_id,))

            subs = cur.fetchall()


        if subs:

            for group_name, expiration in subs:

                if expiration is None or expiration > datetime.now():

                    tiempo_texto = format_tiempo_restante(
                        expiration
                    )

                    suscripciones_texto += (

                        f"⏳ Tu acceso actual a "
                        f"{group_name}:\n"

                        f"{tiempo_texto}\n\n"

                    )

    except Exception as e:

        print(
            "Error cargando suscripciones:",
            e
        )


    # =========================
    # MENSAJE BIENVENIDA
    # =========================

    if suscripciones_texto:

        mensaje = (

            f"{PUBLIC_START_TEXT_ES}\n\n"

            f"{suscripciones_texto}"

        )

    else:

        mensaje = PUBLIC_START_TEXT_ES


    message = update.message or (
        update.callback_query.message
        if update.callback_query
        else None
    )


    if chat_id:

        await context.bot.send_message(

            chat_id=chat_id,

            text=mensaje,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    await message.reply_text(

        mensaje,

        reply_markup=InlineKeyboardMarkup(keyboard)

    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await send_start_menu(update, context)
