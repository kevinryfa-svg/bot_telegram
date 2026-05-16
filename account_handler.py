from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from account_service import (
    build_account_summary_text,
    build_subscription_detail_text,
    get_user_subscriptions
)


# =========================
# ACCOUNT HANDLER — KEYBOARDS
# =========================

def build_account_main_keyboard(user_id):

    subscriptions = get_user_subscriptions(
        user_id
    )

    keyboard = []


    for group_id, expiration, group_name, telegram_group_id in subscriptions:

        group_label = group_name or f"Grupo {group_id}"

        keyboard.append([
            InlineKeyboardButton(
                f"📌 {group_label}",
                callback_data=f"account_group_{group_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "🔄 Renovar suscripción",
            callback_data="account_renew"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🔗 Recuperar acceso",
            callback_data="account_recover_access"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🌍 Idioma",
            callback_data="account_language"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🆘 Soporte",
            callback_data="account_support"
        )
    ])


    return InlineKeyboardMarkup(keyboard)



def build_account_back_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬅️ Volver a Mi cuenta",
                callback_data="account_main"
            )
        ]
    ])


# =========================
# ACCOUNT HANDLER — COMMANDS
# =========================

async def cuenta_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    await update.message.reply_text(
        build_account_summary_text(
            user_id
        ),
        reply_markup=build_account_main_keyboard(
            user_id
        )
    )


async def mi_cuenta_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await cuenta_command(
        update,
        context
    )


# =========================
# ACCOUNT HANDLER — CALLBACKS
# =========================

async def handle_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    if not query:

        return False


    data = query.data or ""
    user_id = query.from_user.id


    if data == "account_main":

        await query.answer()

        await query.edit_message_text(
            build_account_summary_text(
                user_id
            ),
            reply_markup=build_account_main_keyboard(
                user_id
            )
        )

        return True


    if data.startswith("account_group_"):

        group_id = int(
            data.replace(
                "account_group_",
                "",
                1
            )
        )

        await query.answer()

        await query.edit_message_text(
            build_subscription_detail_text(
                user_id,
                group_id
            ),
            reply_markup=build_account_back_keyboard()
        )

        return True


    if data == "account_renew":

        await query.answer()

        await query.edit_message_text(
            "🔄 Renovación\n\n"
            "Esta opción permitirá renovar la suscripción desde el bot.",
            reply_markup=build_account_back_keyboard()
        )

        return True


    if data == "account_recover_access":

        await query.answer()

        await query.edit_message_text(
            "🔗 Recuperar acceso\n\n"
            "Esta opción permitirá generar o recuperar un link de acceso.",
            reply_markup=build_account_back_keyboard()
        )

        return True


    if data == "account_language":

        await query.answer()

        await query.edit_message_text(
            "🌍 Idioma\n\n"
            "Esta opción permitirá cambiar el idioma del bot.",
            reply_markup=build_account_back_keyboard()
        )

        return True


    if data == "account_support":

        await query.answer()

        await query.edit_message_text(
            "🆘 Soporte\n\n"
            "Esta opción permitirá pedir ayuda desde el bot.",
            reply_markup=build_account_back_keyboard()
        )

        return True


    return False
