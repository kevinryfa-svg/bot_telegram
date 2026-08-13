"""
creator_dynamic_callbacks: tramo extraído de callback_router.py.

Prefijos: creator_dynamic_

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


def fetch_dynamic_preview_videos(*args, **kwargs):
    from callback_router import fetch_dynamic_preview_videos as impl
    return impl(*args, **kwargs)


def get_marketplace_group_id_for_request(*args, **kwargs):
    from callback_router import get_marketplace_group_id_for_request as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def deactivate_dynamic_preview_video(video_id, group_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE group_preview_videos
            SET is_active=FALSE
            WHERE id=%s
            AND group_id=%s
            RETURNING id

        """, (
            video_id,
            group_id
        ))

        return cur.fetchone() is not None


def set_group_preview_mode(group_id, preview_mode):

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


def format_owner_dynamic_videos_text(group_id):

    videos = fetch_dynamic_preview_videos(group_id, limit=10)


    if not videos:

        return (
            "🎬 Vídeos guardados\n\n"
            "Todavía no hay vídeos guardados. Solo se guardarán vídeos publicados en el grupo después de activar el preview dinámico."
        )


    lines = ["🎬 Vídeos guardados"]


    for index, video in enumerate(videos, start=1):

        caption = video.get("caption") or "sin caption"


        if len(caption) > 80:

            caption = caption[:77] + "..."


        lines.append(
            "\n"
            f"{index}. ID interno: {video.get('id')}\n"
            f"Mensaje: {video.get('message_id') or '-'}\n"
            f"Caption: {caption}"
        )


    return "\n".join(lines)


def build_dynamic_video_delete_keyboard(request_id, group_id):

    videos = fetch_dynamic_preview_videos(group_id, limit=10)
    keyboard = []


    for index, video in enumerate(videos, start=1):

        keyboard.append([InlineKeyboardButton(
            f"🗑 Borrar vídeo {index}",
            callback_data=f"creator_dynamic_preview_delete_video_{request_id}_{video.get('id')}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_marketplace_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_creator_dynamic_callbacks(update, context, query, user_id, data):

    if (
        data.startswith("creator_dynamic_preview_enable_")
        or data.startswith("creator_dynamic_preview_disable_")
        or data.startswith("creator_dynamic_preview_videos_")
        or data.startswith("creator_dynamic_preview_delete_")
    ):

        if data.startswith("creator_dynamic_preview_enable_"):

            request_id = extract_commercial_request_id(
                data,
                "creator_dynamic_preview_enable_"
            )
            action = "enable"

        elif data.startswith("creator_dynamic_preview_disable_"):

            request_id = extract_commercial_request_id(
                data,
                "creator_dynamic_preview_disable_"
            )
            action = "disable"

        elif data.startswith("creator_dynamic_preview_videos_"):

            request_id = extract_commercial_request_id(
                data,
                "creator_dynamic_preview_videos_"
            )
            action = "videos"

        elif data.startswith("creator_dynamic_preview_delete_video_"):

            payload = data.replace(
                "creator_dynamic_preview_delete_video_",
                "",
                1
            )

            try:

                request_id_text, video_id_text = payload.rsplit("_", 1)
                request_id = int(request_id_text)
                video_id = int(video_id_text)

            except Exception:

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "❌ Vídeo no válido."
                )

                return

            action = "delete_video"

        else:

            request_id = extract_commercial_request_id(
                data,
                "creator_dynamic_preview_delete_"
            )
            action = "delete"


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
                "👁 Preview marketplace\n\nPrimero vincula un grupo/canal real para gestionar el preview dinámico.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        if action == "enable":

            set_group_preview_mode(group_id, "dynamic")

            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Preview dinámico activado.\n\n"
                "A partir de ahora se guardarán los vídeos que se publiquen en el grupo mientras el bot los reciba.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        if action == "disable":

            set_group_preview_mode(group_id, "manual")

            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Preview dinámico desactivado.\n\n"
                "Los vídeos guardados no se borran, pero ya no se capturarán nuevos vídeos para el preview dinámico.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        if action == "videos":

            await send_clean_message(
                context,
                query.message.chat_id,
                format_owner_dynamic_videos_text(group_id),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"creator_setup_marketplace_{request_id}"
                    )]
                ])
            )

            return


        if action == "delete":

            await send_clean_message(
                context,
                query.message.chat_id,
                format_owner_dynamic_videos_text(group_id),
                reply_markup=build_dynamic_video_delete_keyboard(
                    request_id,
                    group_id
                )
            )

            return


        if action == "delete_video":

            deleted = deactivate_dynamic_preview_video(
                video_id,
                group_id
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                (
                    "✅ Vídeo eliminado del preview."
                    if deleted
                    else "❌ Vídeo no encontrado."
                ),
                reply_markup=build_dynamic_video_delete_keyboard(
                    request_id,
                    group_id
                )
            )

            return

    return NOT_HANDLED
