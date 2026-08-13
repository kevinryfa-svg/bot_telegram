"""
creator_preview_callbacks: tramo extraído de callback_router.py.

Prefijos: creator_preview_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from db import conn
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from ui_menu_helpers import send_clean_message


# =========================
# CONSTANTES DE ESTE TRAMO
# =========================
# Viven aquí y las importa callback_router, no al revés: un envoltorio
# diferido no sirve para una constante, devolvería una función.

MARKETPLACE_CATEGORIES = [
    ("Trading", "trading"),
    ("Cripto", "cripto"),
    ("IA", "ia"),
    ("Cursos", "cursos"),
    ("Fitness", "fitness"),
    ("Gaming", "gaming"),
    ("VIP", "vip"),
    ("Otros", "otros")
]


MARKETPLACE_CATEGORY_LABELS = {
    slug: label
    for label, slug in MARKETPLACE_CATEGORIES
}


PREVIEW_MODE_LABELS = {
    "private": "sin preview público",
    "manual": "preview fijo/manual",
    "dynamic": "preview dinámico",
    "hybrid": "preview mixto"
}



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_creator_marketplace_keyboard(*args, **kwargs):
    from callback_router import build_creator_marketplace_keyboard as impl
    return impl(*args, **kwargs)


def can_edit_marketplace_preview(*args, **kwargs):
    from callback_router import can_edit_marketplace_preview as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_commercial_request(*args, **kwargs):
    from callback_router import fetch_commercial_request as impl
    return impl(*args, **kwargs)


def fetch_marketplace_group(*args, **kwargs):
    from callback_router import fetch_marketplace_group as impl
    return impl(*args, **kwargs)


def get_marketplace_group_id_for_request(*args, **kwargs):
    from callback_router import get_marketplace_group_id_for_request as impl
    return impl(*args, **kwargs)


def send_marketplace_preview(*args, **kwargs):
    from callback_router import send_marketplace_preview as impl
    return impl(*args, **kwargs)


def start_creator_setup_state(*args, **kwargs):
    from callback_router import start_creator_setup_state as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_preview_mode_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📝 Preview fijo/manual",
            callback_data=f"creator_preview_mode_set_{request_id}_manual"
        )],
        [InlineKeyboardButton(
            "⚡ Preview dinámico: últimos 3 vídeos",
            callback_data=f"creator_preview_mode_set_{request_id}_dynamic"
        )],
        [InlineKeyboardButton(
            "💎 Preview mixto",
            callback_data=f"creator_preview_mode_set_{request_id}_hybrid"
        )],
        [InlineKeyboardButton(
            "🔒 Sin preview público",
            callback_data=f"creator_preview_mode_set_{request_id}_private"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"creator_setup_marketplace_{request_id}"
        )]
    ])


def build_preview_category_keyboard(request_id):

    keyboard = [
        [InlineKeyboardButton(
            label,
            callback_data=f"creator_preview_category_set_{request_id}_{slug}"
        )]
        for label, slug in MARKETPLACE_CATEGORIES
    ]

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_marketplace_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def group_has_manual_preview(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT preview_text,
                   preview_file_id,
                   preview_image_file_id,
                   preview_video_file_id
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    if not row:

        return False


    return any(row)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_creator_preview_callbacks(update, context, query, user_id, data):

    if (
        data.startswith("creator_preview_mode_")
        and not data.startswith("creator_preview_mode_set_")
    ):

        request_id = extract_commercial_request_id(data, "creator_preview_mode_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "¿Qué tipo de preview quieres mostrar?\n\n"
            "📝 Preview fijo/manual: enseña un texto, imagen o vídeo teaser que tú configuras.\n\n"
            "⚡ Preview dinámico: enseña los últimos 3 vídeos publicados después de activar este modo. El bot no descarga vídeos, solo usa file_id.\n\n"
            "💎 Preview mixto: combina tu teaser manual con vídeos dinámicos recientes.\n\n"
            "🔒 Sin preview público: solo muestra información mínima de la comunidad.",
            reply_markup=build_preview_mode_keyboard(request_id)
        )

        return


    if data.startswith("creator_preview_mode_set_"):

        prefix = "creator_preview_mode_set_"
        remainder = data.replace(prefix, "", 1)

        try:

            request_id_text, preview_mode = remainder.rsplit("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Nivel de preview no válido."
            )

            return


        if preview_mode not in PREVIEW_MODE_LABELS:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Nivel de preview no válido."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "👁 Preview marketplace\n\n"
                "Primero vincula un grupo/canal real para guardar el nivel de preview.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET preview_mode=%s
                WHERE id=%s

            """, (
                preview_mode,
                group_id
            ))

            conn.commit()


        message = "✅ Tipo de preview actualizado."

        if preview_mode == "dynamic":

            message += (
                "\n\n"
                "A partir de ahora se guardarán los vídeos nuevos que se publiquen en el grupo mientras el bot los reciba. Solo se mostrarán los últimos 3."
            )

        elif preview_mode == "hybrid":

            if not group_has_manual_preview(group_id):

                context.user_data["marketplace_preview_media"] = True
                context.user_data["marketplace_preview_request_id"] = request_id
                context.user_data["marketplace_preview_media_type"] = "hybrid_manual"
                context.user_data["marketplace_preview_target_mode"] = "hybrid"

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "✅ Preview mixto activado.\n\n"
                    "Muestra primero el preview manual y además permite ver los últimos vídeos dinámicos.\n\n"
                    "Ahora envía una foto o vídeo fijo para el preview manual."
                )

                return


            message += (
                "\n\n"
                "Tu preview combinará el teaser manual con los últimos vídeos dinámicos disponibles."
            )

        elif preview_mode == "manual":

            context.user_data["marketplace_preview_media"] = True
            context.user_data["marketplace_preview_request_id"] = request_id
            context.user_data["marketplace_preview_media_type"] = "manual"
            context.user_data["marketplace_preview_target_mode"] = "manual"

            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Preview manual activado.\n\n"
                "Manual: subes una imagen o vídeo fijo que verán los usuarios antes de entrar.\n\n"
                "Envía ahora una foto o vídeo para guardarlo como preview manual."
            )

            return

        elif preview_mode == "private":

            message += (
                "\n\n"
                "La ficha pública mostrará solo información mínima."
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            message,
            reply_markup=InlineKeyboardMarkup(
                build_creator_marketplace_keyboard(request_id)
            )
        )

        return


    if data.startswith("creator_preview_text_"):

        request_id = extract_commercial_request_id(data, "creator_preview_text_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "marketplace_preview_text")

        await send_clean_message(
            context,
            query.message.chat_id,
            "📝 Editar texto preview\n\n"
            "Escribe el preview corto que quieres mostrar en el marketplace."
        )

        return


    if data.startswith("creator_preview_image_"):

        request_id = extract_commercial_request_id(data, "creator_preview_image_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if not get_marketplace_group_id_for_request(request_row):

            await send_clean_message(
                context,
                query.message.chat_id,
                "🖼 Añadir imagen preview\n\n"
                "Primero vincula un grupo/canal real para guardar la imagen preview.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        context.user_data["marketplace_preview_media"] = True
        context.user_data["marketplace_preview_request_id"] = request_id
        context.user_data["marketplace_preview_media_type"] = "image"

        await send_clean_message(
            context,
            query.message.chat_id,
            "🖼 Añadir imagen preview\n\n"
            "Envía ahora la foto que quieres usar como preview del marketplace."
        )

        return


    if data.startswith("creator_preview_video_"):

        request_id = extract_commercial_request_id(data, "creator_preview_video_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if not get_marketplace_group_id_for_request(request_row):

            await send_clean_message(
                context,
                query.message.chat_id,
                "🎬 Añadir vídeo preview\n\n"
                "Primero vincula un grupo/canal real para guardar el vídeo preview.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        context.user_data["marketplace_preview_media"] = True
        context.user_data["marketplace_preview_request_id"] = request_id
        context.user_data["marketplace_preview_media_type"] = "video"

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎬 Añadir vídeo preview\n\n"
            "Envía ahora el vídeo corto que quieres usar como preview del marketplace."
        )

        return


    if data.startswith("creator_preview_category_set_"):

        prefix = "creator_preview_category_set_"
        remainder = data.replace(prefix, "", 1)

        try:

            request_id_text, category = remainder.rsplit("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Categoría no válida."
            )

            return


        if category not in MARKETPLACE_CATEGORY_LABELS:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Categoría no válida."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📂 Elegir categoría\n\n"
                "Primero vincula un grupo/canal real para guardar la categoría.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET category=%s
                WHERE id=%s

            """, (
                category,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            f"✅ Categoría guardada: {MARKETPLACE_CATEGORY_LABELS.get(category)}",
            reply_markup=InlineKeyboardMarkup(
                build_creator_marketplace_keyboard(request_id)
            )
        )

        return


    if data.startswith("creator_preview_category_"):

        request_id = extract_commercial_request_id(data, "creator_preview_category_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "📂 Elegir categoría\n\n"
            "Selecciona la categoría principal de tu comunidad.",
            reply_markup=build_preview_category_keyboard(request_id)
        )

        return


    if data.startswith("creator_preview_tags_"):

        request_id = extract_commercial_request_id(data, "creator_preview_tags_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if not get_marketplace_group_id_for_request(request_row):

            await send_clean_message(
                context,
                query.message.chat_id,
                "🏷 Editar tags\n\n"
                "Primero vincula un grupo/canal real para guardar tags.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        start_creator_setup_state(context, request_id, "marketplace_tags")

        await send_clean_message(
            context,
            query.message.chat_id,
            "🏷 Editar tags\n\n"
            "Escribe los tags separados por comas. Ejemplo: señales, trading, vip"
        )

        return


    if data.startswith("creator_preview_show_"):

        request_id = extract_commercial_request_id(data, "creator_preview_show_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "👁 Ver cómo quedará\n\n"
                "Primero vincula un grupo/canal real para previsualizar la ficha.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        group = fetch_marketplace_group(group_id)

        if not group:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        await send_marketplace_preview(
            context,
            query.message.chat_id,
            group
        )

        return

    return NOT_HANDLED
