# =========================
# I18N SERVICE — SUPPORTED LANGUAGES
# =========================

DEFAULT_LANGUAGE = "es"

SUPPORTED_LANGUAGES = {

    "es": "Español",
    "en": "English",
    "pt": "Português",
    "fr": "Français",
    "it": "Italiano"
}


# =========================
# I18N SERVICE — HELPERS
# =========================

def normalize_language(language):

    language = str(language or DEFAULT_LANGUAGE).strip().lower()

    if language in SUPPORTED_LANGUAGES:

        return language


    return DEFAULT_LANGUAGE



def get_language_name(language):

    language = normalize_language(language)

    return SUPPORTED_LANGUAGES.get(
        language,
        SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE]
    )



def list_supported_languages():

    return SUPPORTED_LANGUAGES


# =========================
# I18N SERVICE — TRANSLATIONS
# =========================

TRANSLATIONS = {

    "help.main_title": {
        "es": "📘 Manual del bot",
        "en": "📘 Bot manual",
        "pt": "📘 Manual do bot",
        "fr": "📘 Manuel du bot",
        "it": "📘 Manuale del bot"
    },

    "help.choose_section": {
        "es": "Elige una sección:",
        "en": "Choose a section:",
        "pt": "Escolhe uma secção:",
        "fr": "Choisis une section :",
        "it": "Scegli una sezione:"
    },

    "help.commands": {
        "es": "Comandos",
        "en": "Commands",
        "pt": "Comandos",
        "fr": "Commandes",
        "it": "Comandi"
    },

    "help.buttons": {
        "es": "Botones y opciones",
        "en": "Buttons and options",
        "pt": "Botões e opções",
        "fr": "Boutons et options",
        "it": "Pulsanti e opzioni"
    },

    "help.subscriptions": {
        "es": "Suscripciones",
        "en": "Subscriptions",
        "pt": "Subscrições",
        "fr": "Abonnements",
        "it": "Abbonamenti"
    },

    "help.ai": {
        "es": "IA del bot",
        "en": "Bot AI",
        "pt": "IA do bot",
        "fr": "IA du bot",
        "it": "IA del bot"
    },

    "help.admin": {
        "es": "Administración",
        "en": "Administration",
        "pt": "Administração",
        "fr": "Administration",
        "it": "Amministrazione"
    },

    "help.language": {
        "es": "Idioma",
        "en": "Language",
        "pt": "Idioma",
        "fr": "Langue",
        "it": "Lingua"
    },

    "help.back": {
        "es": "⬅️ Volver",
        "en": "⬅️ Back",
        "pt": "⬅️ Voltar",
        "fr": "⬅️ Retour",
        "it": "⬅️ Indietro"
    },

    "help.not_available": {
        "es": "Esta sección todavía no está disponible.",
        "en": "This section is not available yet.",
        "pt": "Esta secção ainda não está disponível.",
        "fr": "Cette section n'est pas encore disponible.",
        "it": "Questa sezione non è ancora disponibile."
    }
}


# =========================
# I18N SERVICE — TRANSLATE
# =========================

def t(key, language="es", **kwargs):

    language = normalize_language(language)

    translations = TRANSLATIONS.get(key)

    if not translations:

        return key


    text = translations.get(
        language,
        translations.get(DEFAULT_LANGUAGE, key)
    )


    if kwargs:

        try:

            return text.format(**kwargs)

        except Exception:

            return text


    return text
