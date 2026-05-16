from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from help_menu_service import (
    build_help_main_text,
    build_help_main_keyboard,
    build_help_section_text,
    build_help_section_keyboard
)

from help_roles import (
    ROLE_PUBLIC_BUYER,
    normalize_help_role
)

from i18n_service import (
    DEFAULT_LANGUAGE,
    list_supported_languages,
    normalize_language,
    get_language_name
)


# =========================
# HELP HANDLER — TEMP USER SETTINGS
# =========================

USER_LANGUAGE_CACHE = {}
USER_ROLE_CACHE = {}


# =========================
# HELP HANDLER — USER PREFERENCES
# =========================

def get_user_language(user_id):

    return USER_LANGUAGE_CACHE.get(
        user_id,
        DEFAULT_LANGUAGE
    )



def set_user_language(user_id, language):

    USER_LANGUAGE_CACHE[user_id] = normalize_language(
        language
    )



def get_user_help_role(user_id):

    return USER_ROLE_CACHE.get(
        user_id,
        ROLE_PUBLIC_BUYER
    )



def set_user_help_role(user_id, role):

    USER_ROLE_CACHE[user_id] = normalize_help_role(
        role
    )


# =========================
# HELP HANDLER — COMMANDS
# =========================

async def ayuda_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    language = get_user_language(user_id)
    role = get_user_help_role(user_id)

    await update.message.reply_text(
        build_help_main_text(
            role,
            language
        ),
        reply_markup=build_help_main_keyboard(
            role,
            language
        )
    )


async def manual_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await ayuda_command(
        update,
        context
    )


async def idioma_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    language = get_user_language(user_id)

    keyboard = []

    for lang_code, lang_name in list_supported_languages().items():

        prefix = "✅ " if lang_code == language else "🌍 "

        keyboard.append([
            InlineKeyboardButton(
                f"{prefix}{lang_name}",
                callback_data=f"set_language_{lang_code}"
            )
        ])


    await update.message.reply_text(
        "🌍 Elige tu idioma / Choose your language:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# HELP HANDLER — CALLBACKS
# =========================

async def handle_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    if not query:

        return False


    data = query.data or ""
    user_id = query.from_user.id
    language = get_user_language(user_id)
    role = get_user_help_role(user_id)


    if data.startswith("help_main_"):

        role_from_callback = data.replace(
            "help_main_",
            "",
            1
        )

        role = normalize_help_role(
            role_from_callback
        )

        set_user_help_role(
            user_id,
            role
        )

        await query.answer()

        await query.edit_message_text(
            build_help_main_text(
                role,
                language
            ),
            reply_markup=build_help_main_keyboard(
                role,
                language
            )
        )

        return True


    if data.startswith("help_section_"):

        section = data.replace(
            "help_section_",
            "",
            1
        )

        await query.answer()

        await query.edit_message_text(
            build_help_section_text(
                section,
                language
            ),
            reply_markup=build_help_section_keyboard(
                role,
                language
            )
        )

        return True


    if data.startswith("set_language_"):

        language = data.replace(
            "set_language_",
            "",
            1
        )

        set_user_language(
            user_id,
            language
        )

        language = get_user_language(user_id)

        await query.answer(
            f"Idioma: {get_language_name(language)}"
        )

        await query.edit_message_text(
            build_help_main_text(
                role,
                language
            ),
            reply_markup=build_help_main_keyboard(
                role,
                language
            )
        )

        return True


    return False
