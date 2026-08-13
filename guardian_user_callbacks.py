"""
guardian_user_callbacks: tramo extraído de callback_router.py.

Prefijos: guardian_user_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from db import conn
from guardian_callbacks import (
    build_owner_guardian_addon_required_keyboard,
    build_owner_guardian_addon_required_text,
    owner_can_use_guardian,
    user_can_view_guardian_warnings,
)
from guardian_service import (
    add_guardian_warning,
    count_guardian_warnings,
    list_guardian_warnings,
    reset_guardian_warnings,
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
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)


def parse_community_user_callback(*args, **kwargs):
    from callback_router import parse_community_user_callback as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_guardian_user_warnings_text(group_id, target_user_id):

    warnings = list_guardian_warnings(group_id, target_user_id=target_user_id, limit=10)
    active_count = count_guardian_warnings(group_id, target_user_id)

    lines = [
        "⚠️ Guardian warnings de usuario",
        "",
        f"Usuario: {target_user_id}",
        f"Warnings activos: {active_count}",
        "",
        "Últimos warnings:"
    ]


    if not warnings:

        lines.append("- Todavía no hay warnings registrados.")

    else:

        for warning in warnings:

            status = "activo" if warning.get("is_active") else "reseteado"
            created_at = format_commercial_datetime(warning.get("created_at"))
            lines.append(
                f"- #{warning.get('id')} · {status} · {created_at} · {warning.get('reason') or '-'}"
            )


    return "\n".join(lines)


def build_guardian_user_warnings_keyboard(group_id, target_user_id, user_id):

    keyboard = []

    if user_can_add_guardian_warning(user_id, group_id):

        keyboard.append([InlineKeyboardButton("➕ Añadir warning manual", callback_data=f"guardian_user_warn_add_{group_id}_{target_user_id}")])

    if user_can_reset_guardian_warnings(user_id, group_id):

        keyboard.append([InlineKeyboardButton("🧹 Resetear warnings", callback_data=f"guardian_user_warn_reset_{group_id}_{target_user_id}")])

    keyboard.append([InlineKeyboardButton("⬅️ Volver al usuario", callback_data=f"community_user_manage_{group_id}_{target_user_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def user_can_add_guardian_warning(user_id, group_id):

    if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:

        return True


    return user_has_group_permission_any(
        user_id,
        group_id,
        ["can_warn_users", "can_manage_users"]
    )


def user_can_reset_guardian_warnings(user_id, group_id):

    if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:

        return True


    return user_has_group_permission_any(
        user_id,
        group_id,
        ["can_reset_warnings", "can_manage_users"]
    )



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_guardian_user_callbacks(update, context, query, user_id, data):

    if data.startswith("guardian_user_warnings_"):

        parsed = parse_community_user_callback(data, "guardian_user_warnings_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_view_guardian_warnings(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para ver warnings Guardian de este usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        allowed, _ = owner_can_use_guardian(user_id, group_id)

        if not allowed:

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_guardian_addon_required_text(group_id),
                reply_markup=build_owner_guardian_addon_required_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_guardian_user_warnings_text(group_id, target_user_id),
            reply_markup=build_guardian_user_warnings_keyboard(group_id, target_user_id, user_id)
        )

        return

    if data.startswith("guardian_user_warn_add_"):

        parsed = parse_community_user_callback(data, "guardian_user_warn_add_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_add_guardian_warning(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para añadir warnings Guardian.", reply_markup=build_owner_panel_nav_keyboard())
            return


        allowed, _ = owner_can_use_guardian(user_id, group_id)

        if not allowed:

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_guardian_addon_required_text(group_id),
                reply_markup=build_owner_guardian_addon_required_keyboard()
            )

            return


        try:

            add_guardian_warning(
                group_id,
                target_user_id,
                user_id,
                reason="Warning manual desde panel",
                source="manual"
            )

        except Exception as e:

            try:

                conn.rollback()

            except Exception:

                pass

            await query.message.reply_text(
                f"❌ No he podido añadir el warning: {str(e)[:300]}",
                reply_markup=build_guardian_user_warnings_keyboard(group_id, target_user_id, user_id)
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            f"{build_guardian_user_warnings_text(group_id, target_user_id)}\n\n✅ Warning manual añadido.",
            reply_markup=build_guardian_user_warnings_keyboard(group_id, target_user_id, user_id)
        )

        return

    if data.startswith("guardian_user_warn_reset_") and not data.startswith("guardian_user_warn_reset_yes_"):

        parsed = parse_community_user_callback(data, "guardian_user_warn_reset_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_reset_guardian_warnings(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para resetear warnings Guardian.", reply_markup=build_owner_panel_nav_keyboard())
            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚠️ ¿Seguro que quieres resetear los warnings activos de este usuario?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, resetear warnings", callback_data=f"guardian_user_warn_reset_yes_{group_id}_{target_user_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"guardian_user_warnings_{group_id}_{target_user_id}")]
            ])
        )

        return

    if data.startswith("guardian_user_warn_reset_yes_"):

        parsed = parse_community_user_callback(data, "guardian_user_warn_reset_yes_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_reset_guardian_warnings(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para resetear warnings Guardian.", reply_markup=build_owner_panel_nav_keyboard())
            return


        allowed, _ = owner_can_use_guardian(user_id, group_id)

        if not allowed:

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_guardian_addon_required_text(group_id),
                reply_markup=build_owner_guardian_addon_required_keyboard()
            )

            return


        try:

            reset_count = reset_guardian_warnings(
                group_id,
                target_user_id,
                user_id,
                reason="Reset manual desde panel"
            )

        except Exception as e:

            try:

                conn.rollback()

            except Exception:

                pass

            await query.message.reply_text(
                f"❌ No he podido resetear los warnings: {str(e)[:300]}",
                reply_markup=build_guardian_user_warnings_keyboard(group_id, target_user_id, user_id)
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            f"{build_guardian_user_warnings_text(group_id, target_user_id)}\n\n✅ Warnings reseteados: {reset_count}.",
            reply_markup=build_guardian_user_warnings_keyboard(group_id, target_user_id, user_id)
        )

        return

    return NOT_HANDLED
