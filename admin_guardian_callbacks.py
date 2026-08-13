"""
admin_guardian_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_guardian_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import log_event
from db import conn
from owner_addon_service import activate_owner_addon_manual_trial
from rbac_helpers import is_super_admin
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

def build_admin_guardian_trial_cancel_keyboard(*args, **kwargs):
    from callback_router import build_admin_guardian_trial_cancel_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def fetch_admin_guardian_trial_groups(*args, **kwargs):
    from callback_router import fetch_admin_guardian_trial_groups as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def fetch_admin_guardian_trial_group(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT g.id,
                   g.name,
                   g.telegram_group_id,
                   a.user_id AS owner_user_id,
                   COALESCE(g.is_active, TRUE)
            FROM groups g
            LEFT JOIN admins a
              ON a.group_id = g.id
             AND a.role = 'GROUP_OWNER'
             AND COALESCE(a.is_active, TRUE)=TRUE
            WHERE g.id=%s
            LIMIT 1

        """, (group_id,))

        return cur.fetchone()


def build_admin_guardian_trial_groups_text(page=0, query=None):

    query_text = (query or "").strip()
    lines = [
        "🎁 Activar Guardian 30 días",
        "",
        "Elige el grupo al que quieres activar Guardian."
    ]

    if query_text:

        lines.extend([
            "",
            f"Búsqueda: {query_text}"
        ])


    lines.extend([
        "",
        "Solo aparecen grupos activos con owner asignado."
    ])

    return "\n".join(lines)


def build_admin_guardian_trial_groups_keyboard(page=0, query=None):

    rows, has_next = fetch_admin_guardian_trial_groups(page=page, query=query)
    keyboard = []

    for group_id, name, telegram_group_id, owner_user_id, _is_active in rows:

        label = name or f"Grupo {group_id}"
        keyboard.append([
            InlineKeyboardButton(
                f"{label} · #{group_id}",
                callback_data=f"admin_guardian_trial_group_{group_id}"
            )
        ])


    nav_row = []

    if page > 0:

        nav_row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"admin_guardian_trial_groups_{page - 1}"))

    if has_next:

        nav_row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"admin_guardian_trial_groups_{page + 1}"))

    if nav_row:

        keyboard.append(nav_row)


    keyboard.append([InlineKeyboardButton("🔎 Buscar grupo", callback_data="admin_guardian_trial_search")])
    keyboard.append([InlineKeyboardButton("✍️ Introducir IDs manualmente", callback_data="admin_guardian_trial_manual_input")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_guardian_callbacks(update, context, query, user_id, data):

    if data == "admin_guardian_trial_start":

        if not is_super_admin(user_id):

            log_event(
                "admin_guardian_trial_permission_denied",
                category="guardian",
                severity="warning",
                scope="global",
                actor_user_id=user_id,
                message="Usuario no superadmin intentó abrir activación manual Guardian.",
                metadata={
                    "callback": data
                }
            )

            await query.message.reply_text(
                "⛔ Solo superadmin puede activar Guardian manualmente.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data.pop("admin_guardian_trial_waiting", None)
        context.user_data.pop("admin_guardian_trial_search_waiting", None)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_admin_guardian_trial_groups_text(page=0),
            reply_markup=build_admin_guardian_trial_groups_keyboard(page=0)
        )

        return

    if data.startswith("admin_guardian_trial_groups_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Solo superadmin puede activar Guardian manualmente.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        try:

            page = int(data.replace("admin_guardian_trial_groups_", "", 1))

        except Exception:

            page = 0


        await send_clean_message(
            context,
            query.message.chat_id,
            build_admin_guardian_trial_groups_text(page=page),
            reply_markup=build_admin_guardian_trial_groups_keyboard(page=page)
        )

        return

    if data == "admin_guardian_trial_search":

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Solo superadmin puede activar Guardian manualmente.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data.pop("admin_guardian_trial_waiting", None)
        context.user_data["admin_guardian_trial_search_waiting"] = True

        await send_clean_message(
            context,
            query.message.chat_id,
            "🔎 Buscar grupo para Guardian\n\n"
            "Envía el nombre del grupo, group_id o telegram_group_id.",
            reply_markup=build_admin_guardian_trial_cancel_keyboard()
        )

        return

    if data == "admin_guardian_trial_manual_input":

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Solo superadmin puede activar Guardian manualmente.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data.pop("admin_guardian_trial_search_waiting", None)
        context.user_data["admin_guardian_trial_waiting"] = True

        await send_clean_message(
            context,
            query.message.chat_id,
            "✍️ Introducir IDs manualmente\n\n"
            "Envía owner_user_id y group_id separados por espacio.\n\n"
            "Ejemplo:\n"
            "123456789 1159",
            reply_markup=build_admin_guardian_trial_cancel_keyboard()
        )

        return

    if data.startswith("admin_guardian_trial_group_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Solo superadmin puede activar Guardian manualmente.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        try:

            group_id = int(data.replace("admin_guardian_trial_group_", "", 1))

        except Exception:

            await query.message.reply_text(
                "⚠️ Grupo no válido.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_row = fetch_admin_guardian_trial_group(group_id)

        if not group_row:

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚠️ No he encontrado ese grupo.",
                reply_markup=build_admin_guardian_trial_groups_keyboard(page=0)
            )

            return


        _group_id, group_name, _telegram_group_id, owner_user_id, is_active = group_row

        if not is_active or not owner_user_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚠️ Este grupo no está activo o no tiene owner asignado.",
                reply_markup=build_admin_guardian_trial_groups_keyboard(page=0)
            )

            return


        result = activate_owner_addon_manual_trial(
            owner_user_id,
            group_id,
            "guardian",
            days=30,
            activated_by_user_id=user_id
        )

        if not result.get("ok"):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚠️ No he podido activar Guardian manualmente.\n\n"
                f"Motivo: {result.get('reason') or 'unknown'}",
                reply_markup=build_admin_guardian_trial_groups_keyboard(page=0)
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Guardian activado 30 días\n\n"
            f"Grupo: {group_name or f'Grupo {group_id}'}\n"
            f"Group ID: {group_id}\n"
            f"Owner ID: {owner_user_id}\n"
            f"Hasta: {format_commercial_datetime(result.get('current_period_end'))}\n"
            f"Subscription ID: {result.get('subscription_id')}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛡 Abrir Guardian del grupo", callback_data="owner_panel_guardian")],
                [InlineKeyboardButton("🎁 Activar otro grupo", callback_data="admin_guardian_trial_groups_0")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data == "admin_guardian_trial_cancel":

        context.user_data.pop("admin_guardian_trial_waiting", None)
        context.user_data.pop("admin_guardian_trial_search_waiting", None)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Activación manual de Guardian cancelada.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return

    return NOT_HANDLED
