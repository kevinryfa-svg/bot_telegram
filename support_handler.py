from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot_config import TOKEN, ADMIN_ID
from notification_service import send_telegram_message

from support_service import (
    SUPPORT_NO_LINK,
    SUPPORT_LINK_NOT_WORKING,
    SUPPORT_PAID_NO_ACCESS,
    SUPPORT_RENEWAL_HELP,
    SUPPORT_OTHER,
    get_support_issue_label,
    build_support_intro_text,
    build_support_issue_text,
    build_support_admin_alert_text,
    create_support_ticket,
    normalize_support_issue
)


# =========================
# SUPPORT HANDLER — KEYBOARDS
# =========================

def build_support_main_keyboard():

    issues = [
        SUPPORT_NO_LINK,
        SUPPORT_LINK_NOT_WORKING,
        SUPPORT_PAID_NO_ACCESS,
        SUPPORT_RENEWAL_HELP,
        SUPPORT_OTHER
    ]

    keyboard = []

    for issue_type in issues:

        keyboard.append([
            InlineKeyboardButton(
                get_support_issue_label(issue_type),
                callback_data=f"support_issue_{issue_type}"
            )
        ])


    return InlineKeyboardMarkup(keyboard)



def build_support_issue_keyboard(issue_type):

    issue_type = normalize_support_issue(issue_type)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📩 Contactar soporte",
                callback_data=f"support_contact_{issue_type}"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="support_main"
            )
        ]
    ])



def build_support_back_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬅️ Volver a soporte",
                callback_data="support_main"
            )
        ]
    ])


# =========================
# SUPPORT HANDLER — COMMANDS
# =========================

async def soporte_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        build_support_intro_text(),
        reply_markup=build_support_main_keyboard()
    )


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await soporte_command(
        update,
        context
    )


# =========================
# SUPPORT HANDLER — CALLBACKS
# =========================

async def handle_support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    if not query:

        return False


    data = query.data or ""
    user_id = query.from_user.id


    if data == "support_main":

        await query.answer()

        await query.edit_message_text(
            build_support_intro_text(),
            reply_markup=build_support_main_keyboard()
        )

        return True


    if data.startswith("support_issue_"):

        issue_type = data.replace(
            "support_issue_",
            "",
            1
        )

        await query.answer()

        await query.edit_message_text(
            build_support_issue_text(
                issue_type
            ),
            reply_markup=build_support_issue_keyboard(
                issue_type
            )
        )

        return True


    if data.startswith("support_contact_"):

        issue_type = data.replace(
            "support_contact_",
            "",
            1
        )

        ticket = create_support_ticket(
            user_id,
            issue_type
        )

        send_telegram_message(
            TOKEN,
            ADMIN_ID,
            build_support_admin_alert_text(
                ticket["user_id"],
                ticket["issue_type"],
                ticket.get("extra_text")
            )
        )

        await query.answer(
            "Soporte avisado"
        )

        await query.edit_message_text(
            "📩 Hemos avisado al soporte.\n\n"
            "Te contactaremos lo antes posible.",
            reply_markup=build_support_back_keyboard()
        )

        return True


    return False
