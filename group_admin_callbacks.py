"""
group_admin_callbacks: tramo extraído de callback_router.py.

Prefijos: group_admin_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from add_group_callbacks import GROUP_ADMIN_PERMISSION_OPTIONS
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

def build_group_admin_error_keyboard(*args, **kwargs):
    from callback_router import build_group_admin_error_keyboard as impl
    return impl(*args, **kwargs)


def build_group_admin_panel_keyboard(*args, **kwargs):
    from callback_router import build_group_admin_panel_keyboard as impl
    return impl(*args, **kwargs)


def can_manage_group_admins(*args, **kwargs):
    from callback_router import can_manage_group_admins as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_admin_groups_for_permissions(*args, **kwargs):
    from callback_router import fetch_admin_groups_for_permissions as impl
    return impl(*args, **kwargs)


def fetch_group_name(*args, **kwargs):
    from callback_router import fetch_group_name as impl
    return impl(*args, **kwargs)


def format_group_admin_permission_list(*args, **kwargs):
    from callback_router import format_group_admin_permission_list as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def fetch_group_admin_manageable_groups(user_id):

    return fetch_admin_groups_for_permissions(
        user_id,
        ["can_manage_admins"]
    )


def fetch_group_admin_context_groups(context, user_id):

    focused_group_id = context.user_data.get("selected_owner_group")


    if focused_group_id and can_manage_group_admins(user_id, focused_group_id):

        return [
            (
                focused_group_id,
                fetch_group_name(focused_group_id),
                None
            )
        ]


    return fetch_group_admin_manageable_groups(user_id)


def build_group_admin_group_select_keyboard(groups, callback_prefix, back_callback="group_admin_panel"):

    keyboard = []


    for group_id, name, _telegram_group_id in groups:

        keyboard.append([InlineKeyboardButton(
            name or f"Grupo {group_id}",
            callback_data=f"{callback_prefix}{group_id}"
        )])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)


def fetch_group_admins(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT user_id,
                   role,
                   can_view_users,
                   can_manage_users,
                   can_kick_users,
                   can_ban_users,
                   can_unban_users,
                   can_warn_users,
                   can_reset_warnings,
                   can_resend_links,
                   can_view_stats,
                   can_manage_plans,
                   can_edit_group_texts,
                   can_edit_marketplace_preview,
                   can_respond_group_support,
                   can_view_logs,
                   is_active
            FROM admins
            WHERE group_id=%s
            AND is_super_admin=FALSE
            ORDER BY role DESC, user_id ASC

        """, (group_id,))

        return cur.fetchall()


def disable_group_admin(group_id, target_user_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE admins
            SET is_active=FALSE
            WHERE group_id=%s
            AND user_id=%s
            AND is_super_admin=FALSE
            AND COALESCE(role, '') != 'GROUP_OWNER'
            RETURNING id

        """, (
            group_id,
            target_user_id
        ))

        return cur.fetchone() is not None


def build_group_admins_text(group_id):

    rows = fetch_group_admins(group_id)
    group_name = fetch_group_name(group_id)


    if not rows:

        return f"👥 Admins de mi grupo\n\nGrupo: {group_name}\n\nNo hay admins activos."


    lines = [
        f"👥 Admins de mi grupo\n\nGrupo: {group_name}"
    ]


    for row in rows:

        target_user_id = row[0]
        role = row[1] or "GROUP_ADMIN"
        is_active = row[-1] is True
        permissions = {
            permission: row[index + 2] is True
            for index, (_key, _label, permission) in enumerate(GROUP_ADMIN_PERMISSION_OPTIONS)
        }
        status = "activo" if is_active else "inactivo"
        lines.append(
            "\n"
            f"Usuario: {target_user_id}\n"
            f"Rol: {role}\n"
            f"Estado: {status}\n"
            f"{format_group_admin_permission_list(permissions)}"
        )


    return "\n".join(lines)


def build_group_admin_user_select_keyboard(group_id, callback_prefix, include_owner=False):

    rows = fetch_group_admins(group_id)
    keyboard = []


    for row in rows:

        target_user_id = row[0]
        role = row[1] or "GROUP_ADMIN"
        is_active = row[-1] is True


        if not include_owner and role == "GROUP_OWNER":

            continue


        if not is_active:

            continue


        keyboard.append([InlineKeyboardButton(
            f"{target_user_id} — {role}",
            callback_data=f"{callback_prefix}{group_id}_{target_user_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="group_admin_panel"
    )])

    return InlineKeyboardMarkup(keyboard)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_group_admin_callbacks(update, context, query, user_id, data):

    if data == "group_admin_panel":

        context.user_data["adding_group_admin"] = False
        context.user_data.pop("group_admin_target_user_id", None)
        context.user_data.pop("group_admin_target_display", None)
        context.user_data.pop("group_admin_selected_group_id", None)
        context.user_data.pop("group_admin_permissions", None)

        groups = fetch_group_admin_manageable_groups(user_id)


        if not groups:

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)"
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "👥 Admins de mi grupo\n\nGestiona admins y permisos por comunidad.",
            reply_markup=build_group_admin_panel_keyboard()
        )

        return

    if data == "group_admin_permissions_info":

        text = (
            "📖 Permisos disponibles\n\n"
            "Estos permisos se aplican solo al group_id interno de la comunidad seleccionada.\n\n"
            + "\n".join(
                f"• {label}"
                for _key, label, _permission in GROUP_ADMIN_PERMISSION_OPTIONS
            )
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=build_group_admin_panel_keyboard()
        )

        return

    if data == "group_admin_add":

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        context.user_data["adding_group_admin"] = True
        context.user_data.pop("group_admin_target_user_id", None)
        context.user_data.pop("group_admin_target_display", None)
        context.user_data.pop("group_admin_permissions", None)

        await send_clean_message(
            context,
            query.message.chat_id,
            "➕ Añadir admin\n\n"
            "Envía el user_id del usuario.\n\n"
            "También puedes enviar @username si ese usuario ya existe en la base de datos.",
            reply_markup=build_group_admin_error_keyboard()
        )

        return

    if data == "group_admin_view":

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if len(groups) == 1:

            group_id = groups[0][0]

            await send_clean_message(
                context,
                query.message.chat_id,
                build_group_admins_text(group_id),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Volver", callback_data="group_admin_panel")
                ]])
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "📋 Ver admins\n\nSelecciona una comunidad.",
            reply_markup=build_group_admin_group_select_keyboard(
                groups,
                "group_admin_view_group_"
            )
        )

        return

    if data.startswith("group_admin_view_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_admin_view_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_group_admins_text(group_id),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Volver", callback_data="group_admin_panel")
            ]])
        )

        return

    if data == "group_admin_edit":

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if len(groups) == 1:

            data = f"group_admin_edit_group_{groups[0][0]}"

        else:

            await send_clean_message(
                context,
                query.message.chat_id,
                "✏️ Editar permisos\n\nSelecciona una comunidad.",
                reply_markup=build_group_admin_group_select_keyboard(
                    groups,
                    "group_admin_edit_group_"
                )
            )

            return

    if data.startswith("group_admin_edit_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_admin_edit_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "✏️ Editar permisos\n\nSelecciona el admin.",
            reply_markup=build_group_admin_user_select_keyboard(
                group_id,
                "edit_admin_permissions_user_"
            )
        )

        return

    if data == "group_admin_remove":

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if len(groups) == 1:

            data = f"group_admin_remove_group_{groups[0][0]}"

        else:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Quitar admin\n\nSelecciona una comunidad.",
                reply_markup=build_group_admin_group_select_keyboard(
                    groups,
                    "group_admin_remove_group_"
                )
            )

            return

    if data.startswith("group_admin_remove_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_admin_remove_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "❌ Quitar admin\n\nSelecciona el admin.",
            reply_markup=build_group_admin_user_select_keyboard(
                group_id,
                "group_admin_remove_user_"
            )
        )

        return

    if data.startswith("group_admin_remove_user_"):

        payload = data.replace("group_admin_remove_user_", "", 1)

        try:

            group_id_text, target_user_id_text = payload.split("_", 1)
            group_id = int(group_id_text)
            target_user_id = int(target_user_id_text)

        except Exception:

            await query.message.reply_text("❌ Admin no válido.")

            return


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        removed = disable_group_admin(group_id, target_user_id)


        if not removed:

            await query.message.reply_text("❌ Admin no encontrado o no editable.")

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Admin quitado correctamente.",
            reply_markup=build_group_admin_panel_keyboard()
        )

        return

    return NOT_HANDLED
