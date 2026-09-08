from telegram import Update
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
    load_user_language,
    normalize_language,
    save_user_language
)


# =========================
# HELP HANDLER — TEMP USER SETTINGS
# =========================

USER_ROLE_CACHE = {}


# =========================
# HELP HANDLER — USER PREFERENCES
# =========================

def get_user_language(user_id, telegram_language_code=None):
    """
    Idioma del usuario, desde la base de datos.

    Antes esto leía un diccionario en memoria: elegir idioma solo duraba hasta
    el siguiente reinicio.
    """

    return load_user_language(
        user_id,
        telegram_language_code=telegram_language_code
    )



def set_user_language(user_id, language):

    return save_user_language(user_id, language)



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
    # Telegram manda el idioma del cliente: así un comprador inglés se atiende
    # en inglés desde el primer mensaje, sin tocar el menú de idiomas.
    language = get_user_language(
        user_id,
        telegram_language_code=getattr(update.effective_user, "language_code", None)
    )
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
    """
    UNA sola pantalla de idioma en todo el bot.

    Aquí vivía su propia copia, con sus propios botones `set_language_` —que
    además están en la lista de callbacks legacy y contestan «esta opción ya no
    está disponible»—. El texto y el teclado viven ahora en
    `language_menu_service`, que es lo que usa el panel vivo: así este comando
    —que además ahora SÍ está registrado en main.py, que era la otra mitad del
    problema— abre la MISMA pantalla que el botón de /start y no una segunda
    que se queda atrás.
    """

    from language_menu_service import (
        build_language_menu_keyboard,
        build_language_menu_text
    )

    user_id = update.effective_user.id

    language = get_user_language(
        user_id,
        telegram_language_code=getattr(
            update.effective_user, "language_code", None
        )
    )

    await update.message.reply_text(
        build_language_menu_text(language),
        reply_markup=build_language_menu_keyboard(language)
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
    language = get_user_language(
        user_id,
        telegram_language_code=getattr(query.from_user, "language_code", None)
    )
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


    # `set_language_` ya no se despacha aquí: el idioma se cambia en
    # `language_menu_service` con el prefijo `lang_set_`, que sí llega al
    # router vivo. Este prefijo sigue en la lista de legacy y contesta que la
    # opción no está disponible, que es la verdad para los mensajes viejos.



    return False
