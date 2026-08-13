"""
owner_publicity_callbacks: tramo extraído de callback_router.py.

Prefijos: owner_publicity_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import os

from publicity_invite_link_service import (
    create_publicity_invite_link,
    get_active_publicity_invite_link,
    get_publicity_invite_link_by_id,
    list_publicity_invite_links,
    revoke_publicity_invite_link,
    revoke_publicity_invite_link_by_id,
)
from rbac_helpers import (
    get_group_owner_user_id,
    is_super_admin,
)
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

TOKEN = os.environ.get("TOKEN")



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):
    from callback_router import fetch_group_basic_info as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def user_can_manage_publicity_invite_links(user_id, group_id):

    if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:

        return True


    return user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups"]
    )


def build_owner_publicity_group_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    telegram_group_id = group[2] if group else None
    active_link = get_active_publicity_invite_link(
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        source="bot"
    )
    active_links = list_publicity_invite_links(group_id, telegram_group_id, active_only=True)
    manual_links = [link for link in active_links if link.get("source") == "manual"]
    status_text = "✅ Desbloqueado para publicidad" if active_links else "🔒 Sin link público activo"
    link_text = active_link.get("invite_link") if active_link else "-"

    return (
        "📢 Grupo de publicidad\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n"
        f"ID interno: {group_id}\n"
        f"Telegram chat ID: {telegram_group_id or '-'}\n\n"
        f"Estado: {status_text}\n"
        f"Link generado por bot:\n{link_text}\n\n"
        f"Links manuales autorizados: {len(manual_links)}\n\n"
        "Este link está pensado para publicar el grupo en webs/listados de Telegram. "
        "Los usuarios que entren por este link no serán expulsados por el anti-intrusos.\n\n"
        "Para que el bot no expulse usuarios, deben entrar por un link autorizado de publicidad. "
        "Si usas un link antiguo publicado en una web, autorízalo aquí con 🔗 Autorizar link existente. "
        "Si Telegram no informa el link al bot, no se podrá validar automáticamente. "
        "En ese caso, usa el link generado por el bot y reemplázalo en la web."
    )


def build_owner_publicity_group_keyboard(group_id):

    group = fetch_group_basic_info(group_id)
    telegram_group_id = group[2] if group else None
    active_link = get_active_publicity_invite_link(
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        source="bot"
    )
    keyboard = [
        [InlineKeyboardButton("🔓 Desbloquear grupo para publicidad", callback_data=f"owner_publicity_unlock_{group_id}")],
        [InlineKeyboardButton("🔁 Crear nuevo link público", callback_data=f"owner_publicity_new_{group_id}")],
        [InlineKeyboardButton("🔗 Autorizar link existente", callback_data=f"owner_publicity_authorize_existing_{group_id}")],
        [InlineKeyboardButton("📋 Ver links autorizados", callback_data=f"owner_publicity_links_{group_id}")]
    ]


    if active_link:

        keyboard.append([InlineKeyboardButton("🚫 Revocar link actual", callback_data=f"owner_publicity_revoke_{group_id}")])


    keyboard.append([InlineKeyboardButton("⬅️ Volver a seguridad", callback_data="owner_panel_security")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def build_owner_publicity_links_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    telegram_group_id = group[2] if group else None
    links = list_publicity_invite_links(group_id, telegram_group_id, active_only=False)
    text = (
        "📋 Links autorizados para publicidad\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
    )


    if not links:

        return text + "No hay links públicos registrados todavía."


    for link in links:

        source_label = "Bot" if link.get("source") == "bot" else "Manual"
        status_label = "activo" if link.get("is_active") else "inactivo"
        label = link.get("label") or "-"
        text += (
            f"#{link.get('id')} · {source_label} · {status_label}\n"
            f"Etiqueta: {label}\n"
            f"{link.get('invite_link')}\n\n"
        )


    return text


def build_owner_publicity_links_keyboard(group_id):

    group = fetch_group_basic_info(group_id)
    telegram_group_id = group[2] if group else None
    links = list_publicity_invite_links(group_id, telegram_group_id, active_only=True)
    keyboard = []


    for link in links:

        keyboard.append([InlineKeyboardButton(
            f"🚫 Revocar #{link.get('id')} · {'Bot' if link.get('source') == 'bot' else 'Manual'}",
            callback_data=f"owner_publicity_link_revoke_{link.get('id')}"
        )])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=f"owner_publicity_group_{group_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_owner_publicity_callbacks(update, context, query, user_id, data):

    if data.startswith("owner_publicity_group_"):

        group_id = extract_commercial_request_id(data, "owner_publicity_group_")
        context.user_data.pop("publicity_authorize_existing_group_id", None)


        if not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar links públicos de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_publicity_group_text(group_id),
            reply_markup=build_owner_publicity_group_keyboard(group_id)
        )

        return


    if data.startswith("owner_publicity_authorize_existing_"):

        group_id = extract_commercial_request_id(data, "owner_publicity_authorize_existing_")


        if not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para autorizar links públicos de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        telegram_group_id = group[2] if group else None


        if not telegram_group_id:

            await query.message.reply_text(
                "⚠️ Esta comunidad no tiene telegram_group_id configurado.",
                reply_markup=build_owner_publicity_group_keyboard(group_id)
            )

            return


        context.user_data["publicity_authorize_existing_group_id"] = group_id
        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "🔗 Autorizar link existente\n\n"
                "Pega aquí el link de invitación existente que ya tienes publicado en webs/listados de Telegram.\n\n"
                "Ejemplos válidos:\n"
                "https://t.me/+xxxx\n"
                "https://t.me/joinchat/xxxx\n"
                "https://t.me/nombregrupo\n\n"
                "Importante: para detección más fiable se recomiendan links de invitación tipo t.me/+..."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_publicity_group_{group_id}")]
            ])
        )

        return


    if data.startswith("owner_publicity_links_"):

        group_id = extract_commercial_request_id(data, "owner_publicity_links_")


        if not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver links públicos de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_publicity_links_text(group_id),
            reply_markup=build_owner_publicity_links_keyboard(group_id)
        )

        return


    if data.startswith("owner_publicity_link_revoke_yes_"):

        link_id = extract_commercial_request_id(data, "owner_publicity_link_revoke_yes_")
        link = get_publicity_invite_link_by_id(link_id)
        group_id = link.get("group_id") if link else None


        if not link or not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para revocar este link público.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        revoke_publicity_invite_link_by_id(TOKEN, link_id, user_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_publicity_links_text(group_id),
            reply_markup=build_owner_publicity_links_keyboard(group_id)
        )

        return


    if data.startswith("owner_publicity_link_revoke_"):

        link_id = extract_commercial_request_id(data, "owner_publicity_link_revoke_")
        link = get_publicity_invite_link_by_id(link_id)
        group_id = link.get("group_id") if link else None


        if not link or not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para revocar este link público.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚠️ ¿Seguro que quieres revocar este link público de publicidad?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, revocar link", callback_data=f"owner_publicity_link_revoke_yes_{link_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_publicity_links_{group_id}")]
            ])
        )

        return


    if data.startswith("owner_publicity_unlock_"):

        group_id = extract_commercial_request_id(data, "owner_publicity_unlock_")


        if not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para desbloquear este grupo para publicidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        telegram_group_id = group[2] if group else None


        if not telegram_group_id:

            await query.message.reply_text(
                "⚠️ Esta comunidad no tiene telegram_group_id configurado.",
                reply_markup=build_owner_publicity_group_keyboard(group_id)
            )

            return


        current = get_active_publicity_invite_link(
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            source="bot"
        )


        if not current:

            current = create_publicity_invite_link(
                TOKEN,
                group_id,
                telegram_group_id,
                user_id,
                community_type=group[3] if group else None
            )


        if not current:

            await query.message.reply_text(
                "❌ No he podido crear el link público. Asegúrate de que el bot es administrador y puede gestionar enlaces.",
                reply_markup=build_owner_publicity_group_keyboard(group_id)
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_publicity_group_text(group_id),
            reply_markup=build_owner_publicity_group_keyboard(group_id)
        )

        return


    if data.startswith("owner_publicity_new_") and not data.startswith("owner_publicity_new_yes_"):

        group_id = extract_commercial_request_id(data, "owner_publicity_new_")


        if not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para crear un nuevo link público.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        telegram_group_id = group[2] if group else None


        if not telegram_group_id:

            await query.message.reply_text(
                "⚠️ Esta comunidad no tiene telegram_group_id configurado.",
                reply_markup=build_owner_publicity_group_keyboard(group_id)
            )

            return


        active_link = get_active_publicity_invite_link(
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            source="bot"
        )


        if not active_link:

            created = create_publicity_invite_link(
                TOKEN,
                group_id,
                telegram_group_id,
                user_id,
                community_type=group[3] if group else None
            )


            if not created:

                await query.message.reply_text(
                    "❌ No he podido crear el link público. Revisa permisos de administrador del bot.",
                    reply_markup=build_owner_publicity_group_keyboard(group_id)
                )

                return


            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_publicity_group_text(group_id),
                reply_markup=build_owner_publicity_group_keyboard(group_id)
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚠️ Esto revocará el link público actual y creará uno nuevo. ¿Continuar?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, crear nuevo link", callback_data=f"owner_publicity_new_yes_{group_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_publicity_group_{group_id}")]
            ])
        )

        return


    if data.startswith("owner_publicity_new_yes_"):

        group_id = extract_commercial_request_id(data, "owner_publicity_new_yes_")


        if not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para crear un nuevo link público.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        telegram_group_id = group[2] if group else None


        if not telegram_group_id:

            await query.message.reply_text(
                "⚠️ Esta comunidad no tiene telegram_group_id configurado.",
                reply_markup=build_owner_publicity_group_keyboard(group_id)
            )

            return


        created = create_publicity_invite_link(
            TOKEN,
            group_id,
            telegram_group_id,
            user_id,
            community_type=group[3] if group else None
        )


        if not created:

            await query.message.reply_text(
                "❌ No he podido crear el link público. Revisa permisos de administrador del bot.",
                reply_markup=build_owner_publicity_group_keyboard(group_id)
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_publicity_group_text(group_id),
            reply_markup=build_owner_publicity_group_keyboard(group_id)
        )

        return


    if data.startswith("owner_publicity_revoke_") and not data.startswith("owner_publicity_revoke_yes_"):

        group_id = extract_commercial_request_id(data, "owner_publicity_revoke_")


        if not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para revocar este link público.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚠️ ¿Seguro que quieres revocar el link público de publicidad? Los usuarios nuevos ya no podrán entrar por ese link.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, revocar link", callback_data=f"owner_publicity_revoke_yes_{group_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_publicity_group_{group_id}")]
            ])
        )

        return


    if data.startswith("owner_publicity_revoke_yes_"):

        group_id = extract_commercial_request_id(data, "owner_publicity_revoke_yes_")


        if not user_can_manage_publicity_invite_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para revocar este link público.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        telegram_group_id = group[2] if group else None
        current = get_active_publicity_invite_link(
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            source="bot"
        )


        if current:

            revoke_publicity_invite_link(
                TOKEN,
                group_id,
                telegram_group_id,
                current.get("invite_link"),
                user_id
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_publicity_group_text(group_id),
            reply_markup=build_owner_publicity_group_keyboard(group_id)
        )

        return

    return NOT_HANDLED
