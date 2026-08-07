"""
Idioma del usuario y textos traducidos.

Dos cosas que faltaban y se notaban:

  - el idioma elegido vivía en un diccionario en memoria (help_handler), así
    que cualquier reinicio devolvía a todo el mundo al español. Elegir idioma
    no servía de nada más allá de un rato.
  - nadie preguntaba a Telegram. Telegram ya envía el idioma del cliente en
    cada mensaje, así que un comprador inglés podía atenderse en inglés desde
    su primer /start sin saber que existe un menú de idiomas.

Ahora la preferencia se guarda en la base de datos y, si no hay ninguna, se
deduce del idioma de Telegram.
"""


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


def language_from_telegram_code(language_code):
    """
    Traduce el language_code de Telegram a uno de los idiomas soportados.

    Telegram manda cosas como "en", "en-US", "pt-BR" o "es-ES": basta la parte
    anterior al guion. Si el idioma no está soportado, se devuelve None para
    que quien llama decida (normalmente, el idioma por defecto).
    """

    code = str(language_code or "").strip().lower()

    if not code:

        return None


    base = code.split("-")[0].split("_")[0]

    if base in SUPPORTED_LANGUAGES:

        return base


    return None


# =========================
# I18N SERVICE — PREFERENCIA DEL USUARIO
# =========================
# Se guarda en la base de datos: antes era un diccionario en memoria y cada
# reinicio devolvía a todo el mundo al español.

_LANGUAGE_CACHE = {}


def load_user_language(user_id, telegram_language_code=None):
    """
    Idioma del usuario: lo elegido, si no lo que dice Telegram, si no español.

    Nunca lanza: un problema de base de datos no debe impedir contestar.
    """

    if user_id in _LANGUAGE_CACHE:

        return _LANGUAGE_CACHE[user_id]


    stored = None

    try:

        from db import conn

        with conn.cursor() as cur:

            cur.execute(
                "SELECT language FROM user_preferences WHERE user_id=%s",
                (int(user_id),)
            )

            row = cur.fetchone()

            if row and row[0]:

                stored = normalize_language(row[0])

    except Exception as e:

        print("Idioma: no se pudo leer la preferencia:", e)


    if stored:

        _LANGUAGE_CACHE[user_id] = stored

        return stored


    detected = language_from_telegram_code(telegram_language_code)

    if detected:

        # Se guarda lo detectado para que no dependa de que Telegram lo mande
        # en cada actualización, y para poder cambiarlo luego a mano.
        save_user_language(user_id, detected, detected=True)

        return detected


    return DEFAULT_LANGUAGE


def save_user_language(user_id, language, detected=False):
    """Guarda la preferencia. Devuelve el idioma normalizado que queda."""

    language = normalize_language(language)

    _LANGUAGE_CACHE[user_id] = language

    try:

        from db import conn

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO user_preferences
                (user_id, language, language_is_detected, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET language=EXCLUDED.language,
                              language_is_detected=EXCLUDED.language_is_detected,
                              updated_at=NOW()

            """, (int(user_id), language, bool(detected)))

    except Exception as e:

        print("Idioma: no se pudo guardar la preferencia:", e)


    return language


def forget_cached_language(user_id):
    """Para tests y para forzar una relectura."""

    _LANGUAGE_CACHE.pop(user_id, None)


# =========================
# I18N SERVICE — TRANSLATIONS
# =========================

TRANSLATIONS = {

    # =========================
    # MENSAJES DE CLIENTE
    # =========================
    # Solo el camino del cliente está traducido: avisos de renovación,
    # caducidad, pago sin completar y los botones que llevan a comprar o a
    # pedir ayuda. Son los mensajes que deciden si un comprador extranjero
    # termina la compra.
    #
    # El panel de administración sigue en español a propósito: lo usa el
    # propietario, y traducir 50.000 líneas de panel a medias sería peor que
    # no traducirlo.

    "renewal.expired_title": {
        "es": "⌛ Tu acceso ha caducado",
        "en": "⌛ Your access has expired",
    },

    "renewal.expired_body": {
        "es": "Se ha terminado tu acceso a {group}.",
        "en": "Your access to {group} has ended.",
    },

    "renewal.expired_price": {
        "es": "Puedes volver a entrar desde {price}.",
        "en": "You can join again from {price}.",
    },

    "renewal.expired_no_price": {
        "es": "Puedes volver a entrar cuando quieras.",
        "en": "You can join again whenever you like.",
    },

    "renewal.expired_footer": {
        "es": "Recuperas el acceso al instante tras el pago.",
        "en": "You get your access back instantly after paying.",
    },

    "renewal.soon_title": {
        "es": "⏳ Tu acceso caduca pronto",
        "en": "⏳ Your access expires soon",
    },

    "renewal.early_title": {
        "es": "🔔 Aviso de renovación",
        "en": "🔔 Renewal reminder",
    },

    "renewal.body": {
        "es": "Tu acceso a {group} termina {when}.",
        "en": "Your access to {group} ends {when}.",
    },

    "renewal.price": {
        "es": "Renovar cuesta {price}.",
        "en": "Renewing costs {price}.",
    },

    "renewal.footer": {
        "es": (
            "Si renuevas antes de que caduque, no pierdes el acceso ni tienes "
            "que volver a entrar desde cero."
        ),
        "en": (
            "If you renew before it expires you keep your access and do not "
            "have to start over."
        ),
    },

    "time.under_an_hour": {
        "es": "en menos de una hora",
        "en": "in less than an hour",
    },

    "time.very_soon": {
        "es": "muy pronto",
        "en": "very soon",
    },

    "time.in_hours": {
        "es": "en {hours} horas",
        "en": "in {hours} hours",
    },

    "time.in_one_day": {
        "es": "en 1 día",
        "en": "in 1 day",
    },

    "time.in_days": {
        "es": "en {days} días",
        "en": "in {days} days",
    },

    # El español es exactamente el texto que ya se enviaba: traducir no debe
    # cambiar de paso los mensajes que los clientes españoles ya reciben.

    "abandoned.title": {
        "es": "🛒 ¿Te quedaste a medias?",
        "en": "🛒 Did you get interrupted?",
    },

    "abandoned.body": {
        "es": "Empezaste a entrar en {group} pero el pago no se completó.",
        "en": "You started joining {group} but the payment was not completed.",
    },

    "abandoned.price": {
        "es": "Sigue disponible desde {price}.",
        "en": "It is still available from {price}.",
    },

    "abandoned.footer": {
        "es": (
            "Puedes retomarlo desde donde lo dejaste: al confirmar el pago "
            "recibes tu enlace de acceso al instante."
        ),
        "en": (
            "You can pick up where you left off: as soon as the payment goes "
            "through you get your access link instantly."
        ),
    },

    "abandoned.help": {
        "es": "🛟 Si algo te dio problemas, escríbenos y lo miramos.",
        "en": "🛟 If something gave you trouble, write to us and we'll look into it.",
    },

    "button.resume_payment": {
        "es": "💳 Retomar el pago",
        "en": "💳 Resume the payment",
    },

    "button.i_had_a_problem": {
        "es": "🛟 Tuve un problema",
        "en": "🛟 I had a problem",
    },

    "button.renew": {
        "es": "💳 Renovar mi acceso",
        "en": "💳 Renew my access",
    },

    "button.join_again": {
        "es": "🔓 Volver a entrar",
        "en": "🔓 Join again",
    },

    "button.finish_payment": {
        "es": "💳 Terminar mi compra",
        "en": "💳 Finish my purchase",
    },

    "button.my_accesses": {
        "es": "🎟 Mis accesos",
        "en": "🎟 My accesses",
    },

    "button.i_have_a_question": {
        "es": "🛟 Tengo una duda",
        "en": "🛟 I have a question",
    },

    "button.support": {
        "es": "🛟 Contactar soporte",
        "en": "🛟 Contact support",
    },

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
