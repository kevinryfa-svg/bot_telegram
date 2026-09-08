"""
El interruptor del idioma, que no existía.

El idioma se detectaba del `language_code` de Telegram y se guardaba, y ahí
acababa la historia: NO había forma de cambiarlo. La única pantalla que lo
hacía vivía en `help_handler.py`, un módulo entero al que no apunta un solo
handler —ni `/ayuda`, ni `/idioma`, ni `/manual` están registrados— y su
callback `set_language_` está además en la lista de callbacks legacy, que
contesta «esta opción ya no está disponible».

Y eso, con portugués, francés e italiano al 6%, es un comprador con el móvil en
italiano leyendo la pantalla de pago en español y sin manera de arreglarlo.

Aquí vive el texto y el teclado, una sola vez, y los usa tanto el panel vivo
como `/idioma`.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from i18n_service import (
    aviso_de_idioma_parcial,
    get_language_name,
    idioma_esta_completo,
    list_supported_languages,
    nombre_de_idioma_con_aviso,
    normalize_language,
    save_user_language
)


CALLBACK_MENU = "lang_menu"
CALLBACK_PREFIX = "lang_set_"


def build_language_menu_text(language=None):

    language = normalize_language(language)

    lineas = [
        "🌍 Elige tu idioma / Choose your language",
        "",
        f"Ahora mismo: {get_language_name(language)}",
    ]

    if any(
        not idioma_esta_completo(codigo)
        for codigo in list_supported_languages()
    ):

        lineas += [
            "",
            "El % es lo que hay traducido de verdad. Los mensajes del pago "
            "están en todos los idiomas; el resto, en los que no llegan al "
            "100%, te llega en español.",
        ]

    return "\n".join(lineas)


def build_language_menu_keyboard(language=None, volver_a=None):

    language = normalize_language(language)

    filas = []

    for codigo in list_supported_languages():

        marca = "✅ " if codigo == language else "🌍 "

        filas.append([InlineKeyboardButton(
            f"{marca}{nombre_de_idioma_con_aviso(codigo)}",
            callback_data=f"{CALLBACK_PREFIX}{codigo}"
        )])

    # Nunca un callejón: esta pantalla se abre desde /start y desde /idioma, y
    # desde la segunda no hay a dónde volver.
    filas.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data=volver_a or "public_back_start"
    )])

    return InlineKeyboardMarkup(filas)


def parse_language_callback(data):
    """El código de idioma de un `lang_set_xx`, o None si no es uno."""

    if not isinstance(data, str) or not data.startswith(CALLBACK_PREFIX):
        return None

    codigo = data[len(CALLBACK_PREFIX):].strip().lower()

    if codigo not in list_supported_languages():
        return None

    return codigo


def aplicar_idioma(user_id, codigo):
    """
    Guarda el idioma y devuelve (idioma, confirmacion, aviso_o_None).

    La confirmación va en el idioma NUEVO cuando se puede: es la primera
    prueba de que el cambio ha surtido efecto.
    """

    idioma = save_user_language(user_id, codigo)

    confirmacion = f"✅ {get_language_name(idioma)}"

    return idioma, confirmacion, aviso_de_idioma_parcial(idioma)


def build_partial_warning_keyboard():
    """El inglés a un toque, que es el otro idioma completo."""

    return InlineKeyboardMarkup([[InlineKeyboardButton(
        "🌍 English",
        callback_data=f"{CALLBACK_PREFIX}en"
    )]])
