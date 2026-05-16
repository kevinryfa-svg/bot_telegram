from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from help_catalog import (
    get_help_sections_for_role,
    get_help_section_text,
    SECTION_START,
    SECTION_SUBSCRIPTIONS,
    SECTION_ACCESS,
    SECTION_COMMANDS,
    SECTION_BUTTONS,
    SECTION_AI,
    SECTION_ADMIN,
    SECTION_GROUP_MANAGEMENT,
    SECTION_EXCLUSIVE_BOT,
    SECTION_LANGUAGE,
    SECTION_SUPPORT
)

from help_roles import get_role_label
from i18n_service import t


# =========================
# HELP MENU SERVICE — SECTION BUTTON LABELS
# =========================

SECTION_BUTTON_LABELS = {

    SECTION_START: {
        "es": "🚀 Primeros pasos",
        "en": "🚀 Getting started"
    },

    SECTION_SUBSCRIPTIONS: {
        "es": "💳 Suscripciones",
        "en": "💳 Subscriptions"
    },

    SECTION_ACCESS: {
        "es": "🔐 Acceso",
        "en": "🔐 Access"
    },

    SECTION_COMMANDS: {
        "es": "⌨️ Comandos",
        "en": "⌨️ Commands"
    },

    SECTION_BUTTONS: {
        "es": "🔘 Botones",
        "en": "🔘 Buttons"
    },

    SECTION_AI: {
        "es": "🤖 IA",
        "en": "🤖 AI"
    },

    SECTION_ADMIN: {
        "es": "🛠️ Super admin",
        "en": "🛠️ Super admin"
    },

    SECTION_GROUP_MANAGEMENT: {
        "es": "👥 Gestión grupo",
        "en": "👥 Group management"
    },

    SECTION_EXCLUSIVE_BOT: {
        "es": "⭐ Bot exclusivo",
        "en": "⭐ Exclusive bot"
    },

    SECTION_LANGUAGE: {
        "es": "🌍 Idioma",
        "en": "🌍 Language"
    },

    SECTION_SUPPORT: {
        "es": "🆘 Soporte",
        "en": "🆘 Support"
    }
}


# =========================
# HELP MENU SERVICE — HELPERS
# =========================

def get_section_button_label(section, language="es"):

    labels = SECTION_BUTTON_LABELS.get(section, {})

    return labels.get(
        language,
        labels.get("es", section)
    )


# =========================
# HELP MENU SERVICE — MAIN MENU
# =========================

def build_help_main_text(role, language="es"):

    return (
        f"{t('help.main_title', language)}\n\n"
        f"Rol: {get_role_label(role, language)}\n\n"
        f"{t('help.choose_section', language)}"
    )



def build_help_main_keyboard(role, language="es"):

    sections = get_help_sections_for_role(role)

    keyboard = []


    for section in sections:

        keyboard.append([
            InlineKeyboardButton(
                get_section_button_label(section, language),
                callback_data=f"help_section_{section}"
            )
        ])


    return InlineKeyboardMarkup(keyboard)


# =========================
# HELP MENU SERVICE — SECTION VIEW
# =========================

def build_help_section_text(section, language="es"):

    text = get_help_section_text(
        section,
        language
    )

    if text:

        return text


    return t(
        "help.not_available",
        language
    )



def build_help_section_keyboard(role, language="es"):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                t("help.back", language),
                callback_data=f"help_main_{role}"
            )
        ]
    ])
