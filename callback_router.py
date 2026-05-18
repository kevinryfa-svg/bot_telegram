import os
import requests
import secrets
import string
import time

from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from admin_permission_map import (
    callback_requires_super_admin,
    get_required_permissions_for_callback,
    is_admin_callback
)
from admin_menu_catalog import build_admin_menu_button_rows
from ai_handler import activate_ai_help_context
from code_admin_handler import crear_codigo_callback
from bot_config import ADMIN_ID
from commercial_catalog import (
    COMMERCIAL_MENU_TEXT_ES,
    COMMERCIAL_PRODUCTS,
    PRODUCT_SHARED_BOT_SPACE,
    PRODUCT_CUSTOM_BOT,
    CALLBACK_SHARED_BOT_SPACE,
    CALLBACK_CUSTOM_BOT,
    CALLBACK_COMMERCIAL_CONTACT,
    CALLBACK_COMMERCIAL_BACK,
    CALLBACK_COMMERCIAL_BACK_START,
    CALLBACK_COMMERCIAL_BACK_SOLUTIONS,
    CALLBACK_SHARED_TRIAL_START,
    CALLBACK_CUSTOM_BOT_START,
    CALLBACK_COMMERCIAL_HELP,
    CALLBACK_SUBSCRIPTIONS_HELP,
    CALLBACK_GROUP_PLANS_HELP,
    CALLBACK_SUPPORT_HELP,
    CALLBACK_ADMIN_USERS_HELP,
    CALLBACK_ADMIN_GROUPS_HELP,
    CALLBACK_ADMIN_PAYMENTS_HELP,
    CALLBACK_ADMIN_LOGS_HELP
)
from commercial_form_handler import (
    create_commercial_request,
    notify_commercial_request
)
from db import conn
from formatters import format_tiempo_restante
from invite_link_service import (
    create_telegram_invite_link,
    revoke_telegram_invite_link
)
from rbac_helpers import (
    assign_group_owner_permissions,
    get_admin_group_ids,
    has_any_permission_any_group,
    has_group_permission,
    has_permission,
    is_super_admin
)
from start_handler import start, send_start_menu
from telegram_group_actions import kick_chat_member
from ui_menu_helpers import (
    make_button,
    send_clean_message
)


TOKEN = os.environ.get("TOKEN")
SERVER_URL = os.environ.get("SERVER_URL")

revoke_link = None
get_group_id = None


async def delete_query_message_safely(query):

    try:

        if int(query.message.chat_id) < 0:

            return


        await query.message.delete()

    except Exception:

        pass


def build_recover_navigation_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Volver al inicio",
            callback_data="public_back_start"
        )],
        [InlineKeyboardButton(
            "🔎 Ver comunidades",
            callback_data="start_explore_groups"
        )]
    ])


async def reply_with_recover_navigation(query, text):

    await query.message.reply_text(
        text,
        reply_markup=build_recover_navigation_keyboard()
    )


ADMIN_PERMISSION_COLUMNS = [
    "can_manage_users",
    "can_kick_users",
    "can_ban_users",
    "can_unban_users",
    "can_warn_users",
    "can_reset_warnings",
    "can_manage_plans",
    "can_manage_codes",
    "can_manage_groups",
    "can_manage_payments",
    "can_manage_admins",
    "can_view_users",
    "can_view_payments",
    "can_view_stats",
    "can_view_logs",
    "can_edit_group_texts",
    "can_edit_marketplace_preview",
    "can_respond_group_support",
    "can_resend_links"
]


def get_admin_permissions(user_id):

    permissions = {
        column: False
        for column in ADMIN_PERMISSION_COLUMNS
    }


    if is_super_admin(user_id):

        return {
            column: True
            for column in ADMIN_PERMISSION_COLUMNS
        }


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT {", ".join(ADMIN_PERMISSION_COLUMNS)}

                FROM admins

                WHERE user_id=%s
                AND is_active=TRUE

            """, (user_id,))

            rows = cur.fetchall()


        for row in rows:

            for index, column in enumerate(ADMIN_PERMISSION_COLUMNS):

                permissions[column] = permissions[column] or row[index] is True

    except Exception as e:

        print("Error cargando permisos admin:", e)


    return permissions


def has_any_permission(permissions, names):

    return any(
        permissions.get(name) is True
        for name in names
    )


def has_any_admin_permission(user_id):

    permissions = get_admin_permissions(user_id)

    return any(
        value is True
        for value in permissions.values()
    )


def can_access_admin_callback(user_id, data):

    if is_super_admin(user_id):

        return True


    permissions = get_admin_permissions(user_id)


    if data == "admin_back_main":

        return any(
            value is True
            for value in permissions.values()
        )


    users_callbacks = {
        "menu_users",
        "admin_users",
        "admin_search_user"
    }

    manage_users_callbacks = {
        "admin_move_user"
    }

    codes_callbacks = {
        "menu_codes",
        "admin_create_code",
        "admin_codes",
        "admin_delete_code"
    }

    groups_callbacks = {
        "menu_groups",
        "admin_add_group",
        "admin_edit_group",
        "admin_view_groups",
        "cancel_create_group",
        "view_group_plans",
        "add_group_plan",
        "edit_group_plan_select",
        "delete_group_plan_select"
    }

    payments_callbacks = {
        "menu_payments",
        "admin_view_payments",
        "admin_search_payment"
    }

    manage_payments_callbacks = {
        "admin_resend_access",
        "admin_cancel_subscription"
    }

    stats_callbacks = {
        "menu_business",
        "admin_stats",
        "admin_income",
        "admin_active_users"
    }

    logs_callbacks = {
        "menu_logs",
        "admin_logs",
        "admin_logs_users",
        "admin_logs_payments",
        "admin_logs_security"
    }


    if data in users_callbacks:

        return has_any_permission(
            permissions,
            ["can_view_users", "can_manage_users"]
        )


    if data in manage_users_callbacks:

        return has_any_permission(
            permissions,
            ["can_manage_users"]
        )


    if data == "admin_kick_user":

        return has_any_permission(
            permissions,
            ["can_kick_users", "can_manage_users"]
        )


    if data == "admin_ban_user":

        return has_any_permission(
            permissions,
            ["can_ban_users", "can_manage_users"]
        )


    if data == "admin_unban_user":

        return has_any_permission(
            permissions,
            ["can_unban_users", "can_manage_users"]
        )


    if data == "admin_reset_warnings":

        return has_any_permission(
            permissions,
            ["can_reset_warnings", "can_manage_users"]
        )


    if data in codes_callbacks or data.startswith("gen_"):

        return has_any_permission(
            permissions,
            ["can_manage_codes"]
        )


    if (
        data in groups_callbacks
        or data.startswith("edit_group")
        or data.startswith("edit_plan_")
        or data.startswith("delete_group")
        or data.startswith("delete_plan_")
        or data.startswith("save_preview")
        or data.startswith("cancel_preview")
        or data.startswith("skip_preview")
    ):

        return has_any_permission(
            permissions,
            ["can_manage_groups"]
        )


    if data in payments_callbacks:

        return has_any_permission(
            permissions,
            ["can_view_payments", "can_manage_payments"]
        )


    if data in manage_payments_callbacks:

        return has_any_permission(
            permissions,
            ["can_manage_payments"]
        )


    if data in stats_callbacks:

        return has_any_permission(
            permissions,
            ["can_view_stats"]
        )


    if data in logs_callbacks:

        return has_any_permission(
            permissions,
            ["can_view_logs"]
        )


    if data.startswith("allow_user_"):

        return has_any_permission(
            permissions,
            ["can_manage_users"]
        )


    if data.startswith("deny_user_"):

        return has_any_permission(
            permissions,
            ["can_kick_users", "can_manage_users"]
        )


    return False


def build_commercial_menu_keyboard():

    return [

        [InlineKeyboardButton(
            COMMERCIAL_PRODUCTS[PRODUCT_SHARED_BOT_SPACE]["title_es"],
            callback_data=CALLBACK_SHARED_BOT_SPACE
        )],

        [InlineKeyboardButton(
            COMMERCIAL_PRODUCTS[PRODUCT_CUSTOM_BOT]["title_es"],
            callback_data=CALLBACK_CUSTOM_BOT
        )],

        [InlineKeyboardButton(
            "📩 Hablar con un asesor",
            callback_data=CALLBACK_COMMERCIAL_CONTACT
        )],

        [InlineKeyboardButton(
            "💬 Ayuda sobre este menú",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="public_back_start"
        )]

    ]


def build_admin_panel_keyboard(user_id):

    permissions = get_admin_permissions(user_id)

    button_rows = build_admin_menu_button_rows(
        permissions=permissions,
        is_super_admin=is_super_admin(user_id)
    )

    return [
        [
            make_button(
                button["text"],
                button["callback_data"]
            )
            for button in row
        ]
        for row in button_rows
    ]


def user_has_group_permission_any(user_id, group_id, permissions):

    if is_super_admin(user_id):

        return True


    return any(
        has_permission(user_id, group_id, permission)
        for permission in permissions
    )


GROUP_ADMIN_PERMISSION_OPTIONS = [
    ("view_users", "Ver usuarios", "can_view_users"),
    ("kick_users", "Expulsar usuarios", "can_kick_users"),
    ("ban_users", "Banear usuarios", "can_ban_users"),
    ("unban_users", "Desbanear usuarios", "can_unban_users"),
    ("warn_users", "Dar warnings", "can_warn_users"),
    ("manage_links", "Gestionar enlaces", "can_resend_links"),
    ("view_stats", "Ver estadísticas", "can_view_stats"),
    ("manage_plans", "Gestionar planes", "can_manage_plans"),
    ("edit_texts", "Editar textos del grupo", "can_edit_group_texts"),
    ("edit_preview", "Editar preview marketplace", "can_edit_marketplace_preview"),
    ("support", "Responder soporte del grupo", "can_respond_group_support"),
    ("view_logs", "Ver logs del grupo", "can_view_logs")
]


GROUP_ADMIN_PERMISSION_BY_KEY = {
    key: permission
    for key, _label, permission in GROUP_ADMIN_PERMISSION_OPTIONS
}


def can_manage_group_admins(user_id, group_id):

    return has_group_permission(
        user_id,
        group_id,
        "can_manage_admins"
    )


def fetch_group_admin_manageable_groups(user_id):

    return fetch_admin_groups_for_permissions(
        user_id,
        ["can_manage_admins"]
    )


def format_group_admin_permission_list(selected_permissions=None):

    selected_permissions = selected_permissions or {}
    lines = []


    for key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        enabled = selected_permissions.get(permission) is True
        marker = "✅" if enabled else "▫️"
        lines.append(f"{marker} {label}")


    return "\n".join(lines)


def build_group_admin_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Añadir admin", callback_data="group_admin_add")],
        [InlineKeyboardButton("📋 Ver admins", callback_data="group_admin_view")],
        [InlineKeyboardButton("✏️ Editar permisos", callback_data="group_admin_edit")],
        [InlineKeyboardButton("❌ Quitar admin", callback_data="group_admin_remove")],
        [InlineKeyboardButton("📖 Ver permisos disponibles", callback_data="group_admin_permissions_info")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


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
                   can_kick_users,
                   can_ban_users,
                   can_unban_users,
                   can_warn_users,
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


def fetch_group_admin_permissions(group_id, target_user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT can_view_users,
                   can_kick_users,
                   can_ban_users,
                   can_unban_users,
                   can_warn_users,
                   can_resend_links,
                   can_view_stats,
                   can_manage_plans,
                   can_edit_group_texts,
                   can_edit_marketplace_preview,
                   can_respond_group_support,
                   can_view_logs,
                   role,
                   is_active
            FROM admins
            WHERE group_id=%s
            AND user_id=%s
            AND is_super_admin=FALSE
            LIMIT 1

        """, (
            group_id,
            target_user_id
        ))

        row = cur.fetchone()


    if not row:

        return None


    permissions = {}

    for index, (_key, _label, permission) in enumerate(GROUP_ADMIN_PERMISSION_OPTIONS):

        permissions[permission] = row[index] is True


    return {
        "permissions": permissions,
        "role": row[12],
        "is_active": row[13] is True
    }


def build_group_admin_permissions_keyboard(group_id, target_user_id, permissions, toggle_callback_prefix):

    keyboard = []


    for key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        enabled = permissions.get(permission) is True
        prefix = "✅" if enabled else "▫️"
        keyboard.append([InlineKeyboardButton(
            f"{prefix} {label}",
            callback_data=f"{toggle_callback_prefix}_{group_id}_{target_user_id}_{key}"
        )])


    keyboard.append([InlineKeyboardButton(
        "💾 Guardar admin",
        callback_data=f"add_group_admin_save_{group_id}"
    )])
    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="group_admin_panel"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_group_admin_edit_permissions_keyboard(group_id, target_user_id, permissions):

    keyboard = []


    for key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        enabled = permissions.get(permission) is True
        prefix = "✅" if enabled else "▫️"
        keyboard.append([InlineKeyboardButton(
            f"{prefix} {label}",
            callback_data=f"gap_t_{group_id}_{target_user_id}_{key}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"group_admin_edit_group_{group_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def save_group_admin_permissions(group_id, target_user_id, permissions):

    columns = [
        "user_id",
        "group_id",
        "role",
        "is_super_admin",
        "can_manage_users",
        "can_kick_users",
        "can_ban_users",
        "can_unban_users",
        "can_warn_users",
        "can_reset_warnings",
        "can_resend_links",
        "can_recover_access",
        "can_manage_codes",
        "can_manage_groups",
        "can_manage_plans",
        "can_manage_payments",
        "can_manage_admins",
        "can_view_users",
        "can_view_payments",
        "can_view_stats",
        "can_view_logs",
        "can_edit_group_texts",
        "can_edit_marketplace_preview",
        "can_respond_group_support",
        "is_active"
    ]
    values_by_permission = {
        permission: permissions.get(permission) is True
        for _key, _label, permission in GROUP_ADMIN_PERMISSION_OPTIONS
    }
    values = [
        target_user_id,
        group_id,
        "GROUP_ADMIN",
        False,
        False,
        values_by_permission.get("can_kick_users", False),
        values_by_permission.get("can_ban_users", False),
        values_by_permission.get("can_unban_users", False),
        values_by_permission.get("can_warn_users", False),
        False,
        values_by_permission.get("can_resend_links", False),
        False,
        False,
        False,
        values_by_permission.get("can_manage_plans", False),
        False,
        False,
        values_by_permission.get("can_view_users", False),
        False,
        values_by_permission.get("can_view_stats", False),
        values_by_permission.get("can_view_logs", False),
        values_by_permission.get("can_edit_group_texts", False),
        values_by_permission.get("can_edit_marketplace_preview", False),
        values_by_permission.get("can_respond_group_support", False),
        True
    ]
    placeholders = ", ".join(["%s"] * len(columns))
    update_columns = columns[2:]
    update_set = ", ".join(
        f"{column}=EXCLUDED.{column}"
        for column in update_columns
    )


    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO admins
            ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (user_id, group_id)
            DO UPDATE SET {update_set}

        """, values)


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


def fetch_group_name(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT name
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    return row[0] if row else f"Grupo {group_id}"


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


def fetch_admin_groups_for_permissions(user_id, permissions):

    group_ids = get_admin_group_ids(user_id, permissions)


    try:

        with conn.cursor() as cur:

            if group_ids is None:

                cur.execute("""

                    SELECT id, name, telegram_group_id
                    FROM groups
                    WHERE telegram_group_id != 0
                    ORDER BY id ASC

                """)

            elif not group_ids:

                return []

            else:

                cur.execute("""

                    SELECT id, name, telegram_group_id
                    FROM groups
                    WHERE telegram_group_id != 0
                    AND id = ANY(%s)
                    ORDER BY id ASC

                """, (group_ids,))


            return cur.fetchall()

    except Exception as e:

        print("Error cargando grupos permitidos:", e)

        raise


def build_group_settings_keyboard(user_id, group_id):

    keyboard = []


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_edit_group_texts"]
    ):

        keyboard.append([
            InlineKeyboardButton("✏️ Editar nombre", callback_data="edit_group_name")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_edit_marketplace_preview"]
    ):

        keyboard.append([
            InlineKeyboardButton("🎬 Editar preview", callback_data="edit_group_preview")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups"]
    ):

        keyboard.append([
            InlineKeyboardButton("🔗 Editar Stripe", callback_data="edit_group_stripe")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_plans", "can_manage_groups"]
    ):

        keyboard.append([
            InlineKeyboardButton("💳 Editar planes", callback_data="edit_group_plans")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_admins"]
    ):

        keyboard.append([
            InlineKeyboardButton("👑 Administradores", callback_data="edit_group_admins")
        ])


    if is_super_admin(user_id):

        keyboard.append([
            InlineKeyboardButton("❌ Eliminar grupo", callback_data="delete_group_confirm")
        ])


    keyboard.append([
        InlineKeyboardButton("⬅️ Volver", callback_data="admin_edit_group")
    ])

    return keyboard


def get_selected_group_for_permissions(context, user_id, permissions):

    group_id = context.user_data.get("selected_group_admin")


    if not group_id:

        return None


    if not user_has_group_permission_any(user_id, group_id, permissions):

        return None


    return group_id


COMMERCIAL_REQUEST_FIELDS = [

    "id",
    "user_id",
    "username",
    "first_name",
    "request_type",
    "status",
    "community_name",
    "community_description",
    "telegram_group_link",
    "bot_name",
    "bot_username",
    "project_description",
    "contact_text",
    "created_at",
    "updated_at",
    "reviewed_by",
    "reviewed_at",
    "admin_notes",
    "trial_starts_at",
    "trial_ends_at",
    "payment_mode",
    "stripe_mode",
    "is_free_group",
    "approved_group_id",
    "approved_telegram_group_id",
    "approved_bot_username",
    "selected_commercial_plan_id",
    "commercial_subscription_status",
    "commercial_subscription_until",
    "requested_public_visibility",
    "creator_setup_status",
    "creator_preview_text",
    "max_groups_allowed"

]


COMMERCIAL_PLAN_FIELDS = [

    "id",
    "product_type",
    "name",
    "duration_days",
    "amount",
    "currency",
    "stripe_price_id",
    "is_active",
    "created_at"

]


LEGACY_USER_PLATFORM_STRIPE_CALLBACK_PREFIX = (
    "user_trial_setup_"
    "platform_stripe_"
)

LEGACY_ADMIN_PLATFORM_STRIPE_CALLBACK_PREFIX = (
    "commercial_setup_"
    "platform_stripe_"
)


def row_to_commercial_request(row):

    if not row:

        return None


    return dict(zip(COMMERCIAL_REQUEST_FIELDS, row))


def row_to_commercial_plan(row):

    if not row:

        return None


    return dict(zip(COMMERCIAL_PLAN_FIELDS, row))


def format_commercial_request_type(request_type):

    labels = {
        "shared_trial": "prueba comunidad compartida",
        "custom_bot": "bot personalizado",
        "support_contact": "contacto comercial"
    }

    return labels.get(request_type, request_type or "-")


def format_public_visibility(public_visibility):

    labels = {
        "start_home": "inicio",
        "explore_only": "explorar",
        "hidden": "oculta/borrador"
    }

    return labels.get(public_visibility, public_visibility or "-")


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
    "private": "privado / mínimo",
    "manual": "manual",
    "dynamic": "dinámico",
    "hybrid": "mixto"
}


MARKETPLACE_FILTERS = [
    ("🔥 Tendencias", "trending"),
    ("⭐ Más populares", "popular"),
    ("🆕 Nuevas", "new"),
    ("🔓 Gratis", "free"),
    ("💎 Premium", "premium")
]

MARKETPLACE_FILTER_LABELS = {
    slug: label
    for label, slug in MARKETPLACE_FILTERS
}

COMMUNITY_STATS_COLUMNS = {
    "preview_views",
    "access_clicks"
}


def marketplace_trial_visibility_filter():

    return """
        NOT EXISTS (
            SELECT 1
            FROM commercial_requests cr
            WHERE (
                cr.approved_group_id = g.id
                OR cr.approved_telegram_group_id = g.telegram_group_id
            )
            AND cr.status='trial_active'
            AND cr.trial_ends_at IS NOT NULL
            AND cr.trial_ends_at < NOW()
            AND COALESCE(cr.commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
        )
    """


def build_expired_trial_recovery_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "🎟 Tengo un código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "💳 Activar suscripción",
            callback_data=f"expired_trial_activate_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Ver configuración de mi comunidad",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "🗑 Eliminar comunidad definitivamente",
            callback_data=f"expired_trial_delete_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏠 Volver al inicio",
            callback_data="public_back_start"
        )]

    ])


async def expire_expired_commercial_trials(context):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT cr.id,
                   cr.user_id,
                   cr.approved_group_id,
                   cr.approved_telegram_group_id
            FROM commercial_requests cr
            WHERE cr.status='trial_active'
            AND cr.trial_ends_at IS NOT NULL
            AND cr.trial_ends_at < NOW()
            AND COALESCE(cr.commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
            AND (
                cr.approved_group_id IS NOT NULL
                OR cr.approved_telegram_group_id IS NOT NULL
            )

        """)

        rows = cur.fetchall()


        for request_id, owner_user_id, approved_group_id, approved_telegram_group_id in rows:

            cur.execute("""

                UPDATE commercial_requests
                SET status='trial_expired',
                    requested_public_visibility='hidden',
                    updated_at=NOW()
                WHERE id=%s
                AND status='trial_active'

            """, (request_id,))


            if approved_group_id:

                cur.execute("""

                    UPDATE groups
                    SET public_visibility='hidden'
                    WHERE id=%s

                """, (approved_group_id,))


            elif approved_telegram_group_id:

                cur.execute("""

                    UPDATE groups
                    SET public_visibility='hidden'
                    WHERE telegram_group_id=%s

                """, (approved_telegram_group_id,))


            try:

                await context.bot.send_message(
                    chat_id=owner_user_id,
                    text=(
                        "Tu prueba ha finalizado. Para volver a publicar tu comunidad, "
                        "activa una suscripción."
                    ),
                    reply_markup=build_expired_trial_recovery_keyboard(request_id)
                )

            except Exception as e:

                print("Error avisando fin de trial comercial:", e)


def marketplace_access_text(group):

    if group.get("is_free_group"):

        return "🔓 Entrar gratis"


    return "💳 Ver acceso"


def format_marketplace_number(value):

    try:

        value = int(value or 0)

    except Exception:

        value = 0


    return f"{value:,}".replace(",", ".")


def favorite_button_text(is_favorite):

    if is_favorite:

        return "💔 Quitar favorito"


    return "⭐ Guardar favorito"


def favorite_callback_data(group_id, is_favorite):

    if is_favorite:

        return f"unfavorite_group_{group_id}"


    return f"favorite_group_{group_id}"


def build_marketplace_filter_keyboard(active_filter="trending"):

    keyboard = []


    for label, slug in MARKETPLACE_FILTERS:

        text = label

        if slug == active_filter:

            text = f"• {label}"


        keyboard.append([InlineKeyboardButton(
            text,
            callback_data=f"marketplace_filter_{slug}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="public_back_start"
    )])

    return keyboard


def build_marketplace_access_keyboard(
    group_id,
    is_free_group,
    back_callback="start_explore_groups",
    user_id=None
):

    keyboard = []


    if user_id:

        is_favorite = is_group_favorite(user_id, group_id)

        keyboard.append([InlineKeyboardButton(
            favorite_button_text(is_favorite),
            callback_data=favorite_callback_data(group_id, is_favorite)
        )])


    keyboard.append([InlineKeyboardButton(
        "🔓 Entrar gratis" if is_free_group else "💳 Ver acceso",
        callback_data=f"free_access_{group_id}" if is_free_group else f"group_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=back_callback
    )])

    return InlineKeyboardMarkup(keyboard)


def build_marketplace_cards_keyboard(groups, user_id, active_filter="trending"):

    keyboard = []


    for group in groups:

        group_id = group.get("id")
        group_name = group.get("name") or "Comunidad privada"

        keyboard.append([InlineKeyboardButton(
            f"➡️ Ver comunidad — {group_name}",
            callback_data=f"marketplace_group_{group_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "💬 Ayuda sobre este menú",
        callback_data=CALLBACK_GROUP_PLANS_HELP
    )])

    keyboard.extend(build_marketplace_filter_keyboard(active_filter))

    return keyboard


def row_to_marketplace_group(row):

    if not row:

        return None


    fields = [
        "id",
        "name",
        "is_free_group",
        "preview_text",
        "preview_image_file_id",
        "preview_video_file_id",
        "category",
        "tags",
        "marketplace_badge",
        "preview_mode",
        "preview_views",
        "access_clicks",
        "favorites_count",
        "member_count",
        "created_at"
    ]

    return dict(zip(fields, row))


def get_marketplace_group_select():

    return """
        SELECT g.id,
               g.name,
               COALESCE(g.is_free_group, FALSE),
               g.preview_text,
               g.preview_image_file_id,
               g.preview_video_file_id,
               g.category,
               g.tags,
               g.marketplace_badge,
               COALESCE(g.preview_mode, 'manual'),
               COALESCE(cs.preview_views, 0),
               COALESCE(cs.access_clicks, 0),
               COALESCE(cs.favorites_count, 0),
               (
                   SELECT COUNT(*)
                   FROM users u
                   WHERE u.group_id = g.id
                   AND COALESCE(u.subscription_active, FALSE)=TRUE
                   AND (
                       u.expiration IS NULL
                       OR u.expiration > NOW()
                   )
               ) AS member_count,
               g.created_at
        FROM groups g
        LEFT JOIN community_stats cs
        ON cs.group_id = g.id
    """


def fetch_marketplace_group(group_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            {get_marketplace_group_select()}
            WHERE g.id=%s
            AND g.is_active=TRUE
            AND g.telegram_group_id != 0
            AND {marketplace_trial_visibility_filter()}
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    return row_to_marketplace_group(row)


def get_marketplace_order_clause(filter_kind):

    if filter_kind == "popular":

        return "ORDER BY COALESCE(cs.favorites_count, 0) DESC, COALESCE(cs.preview_views, 0) DESC, g.id DESC"


    if filter_kind == "new":

        return "ORDER BY g.created_at DESC, g.id DESC"


    return """
        ORDER BY (
            COALESCE(cs.favorites_count, 0) * 3
            + COALESCE(cs.preview_views, 0)
            + COALESCE(cs.access_clicks, 0) * 2
        ) DESC,
        g.id DESC
    """


def fetch_marketplace_groups(filter_kind="trending", limit=8):

    filters = [
        "g.is_active=TRUE",
        "g.telegram_group_id != 0",
        "COALESCE(g.public_visibility, 'start_home')='explore_only'",
        marketplace_trial_visibility_filter()
    ]


    if filter_kind == "free":

        filters.append("COALESCE(g.is_free_group, FALSE)=TRUE")


    if filter_kind == "premium":

        filters.append("COALESCE(g.is_free_group, FALSE)=FALSE")


    where_clause = " AND ".join(filters)
    order_clause = get_marketplace_order_clause(filter_kind)


    with conn.cursor() as cur:

        cur.execute(f"""

            {get_marketplace_group_select()}
            WHERE {where_clause}
            {order_clause}
            LIMIT %s

        """, (limit,))

        rows = cur.fetchall()


    return [
        row_to_marketplace_group(row)
        for row in rows
    ]


def get_user_favorite_group_ids(user_id, group_ids):

    if not user_id or not group_ids:

        return set()


    with conn.cursor() as cur:

        cur.execute("""

            SELECT group_id
            FROM community_favorites
            WHERE user_id=%s
            AND group_id = ANY(%s)

        """, (
            user_id,
            group_ids
        ))

        rows = cur.fetchall()


    return {
        row[0]
        for row in rows
    }


def is_group_favorite(user_id, group_id):

    if not user_id or not group_id:

        return False


    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM community_favorites
            WHERE user_id=%s
            AND group_id=%s
            LIMIT 1

        """, (
            user_id,
            group_id
        ))

        return cur.fetchone() is not None


def attach_favorite_state(groups, user_id):

    group_ids = [
        group.get("id")
        for group in groups
        if group.get("id")
    ]
    favorite_group_ids = get_user_favorite_group_ids(user_id, group_ids)


    for group in groups:

        group["is_favorite"] = group.get("id") in favorite_group_ids


    return groups


def ensure_community_stats(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO community_stats (group_id)
            VALUES (%s)
            ON CONFLICT (group_id) DO NOTHING

        """, (group_id,))

        conn.commit()


def increment_community_stat(group_id, column_name):

    if column_name not in COMMUNITY_STATS_COLUMNS:

        return


    if not group_id:

        return


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO community_stats (group_id)
            VALUES (%s)
            ON CONFLICT (group_id) DO NOTHING

        """, (group_id,))

        cur.execute(f"""

            UPDATE community_stats
            SET {column_name}=GREATEST(COALESCE({column_name}, 0) + 1, 0),
                updated_at=NOW()
            WHERE group_id=%s

        """, (group_id,))

        conn.commit()


def refresh_community_favorites_count(group_id):

    if not group_id:

        return 0


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO community_stats (group_id)
            VALUES (%s)
            ON CONFLICT (group_id) DO NOTHING

        """, (group_id,))

        cur.execute("""

            UPDATE community_stats
            SET favorites_count=(
                    SELECT COUNT(*)
                    FROM community_favorites
                    WHERE group_id=%s
                ),
                updated_at=NOW()
            WHERE group_id=%s
            RETURNING favorites_count

        """, (
            group_id,
            group_id
        ))

        row = cur.fetchone()
        conn.commit()


    if not row:

        return 0


    return row[0]


def format_marketplace_kind(group):

    if group.get("is_free_group"):

        return "🔓 Gratis"


    return group.get("marketplace_badge") or "💎 Premium"


def format_marketplace_category(group):

    category = group.get("category")

    if not category:

        return "Otros"


    return MARKETPLACE_CATEGORY_LABELS.get(category, category)


def format_marketplace_card(group):

    return (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"{format_marketplace_kind(group)}"
    )


def format_marketplace_group_caption(group):

    return (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"⭐ {format_marketplace_number(group.get('favorites_count'))} favoritos\n"
        f"👥 {format_marketplace_number(group.get('member_count'))} miembros\n"
        f"{format_marketplace_kind(group)}\n\n"
        f"📝 {group.get('preview_text') or 'Preview manual pendiente de configurar.'}"
    )


def build_marketplace_group_keyboard(group, user_id=None):

    group_id = group.get("id")
    is_free_group = group.get("is_free_group")
    keyboard = []


    keyboard.append([InlineKeyboardButton(
        "👁 Ver preview",
        callback_data=f"marketplace_preview_{group_id}"
    )])


    if (group.get("preview_mode") or "manual") in ("dynamic", "hybrid"):

        keyboard.append([InlineKeyboardButton(
            "⚡ Preview dinámico",
            callback_data=f"marketplace_dynamic_preview_{group_id}"
        )])


    if user_id:

        is_favorite = is_group_favorite(user_id, group_id)
        keyboard.append([InlineKeyboardButton(
            favorite_button_text(is_favorite),
            callback_data=favorite_callback_data(group_id, is_favorite)
        )])


    keyboard.append([InlineKeyboardButton(
        "🔓 Entrar gratis" if is_free_group else "💳 Comprar acceso",
        callback_data=f"free_access_{group_id}" if is_free_group else f"group_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a explorar",
        callback_data="start_explore_groups"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(keyboard)


def format_marketplace_preview_caption(group):

    preview_mode = group.get("preview_mode") or "manual"
    stats_text = (
        f"⭐ {format_marketplace_number(group.get('favorites_count'))} favoritos\n"
        f"👥 {format_marketplace_number(group.get('member_count'))} miembros"
    )


    if preview_mode == "private":

        return (
            f"🔥 {group.get('name') or 'Comunidad privada'}\n"
            f"📂 {format_marketplace_category(group)}\n"
            f"{stats_text}\n"
            f"{format_marketplace_kind(group)}"
        )


    if preview_mode in ("dynamic", "hybrid"):

        return (
            f"🔥 {group.get('name') or 'Comunidad privada'}\n"
            f"📂 {format_marketplace_category(group)}\n"
            f"{stats_text}\n"
            f"{format_marketplace_kind(group)}\n\n"
            "El preview dinámico estará disponible en una fase posterior. "
            "Por ahora puedes configurar un preview manual."
        )


    text = (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"{stats_text}\n"
        f"{format_marketplace_kind(group)}\n\n"
        f"📝 {group.get('preview_text') or 'Preview manual pendiente de configurar.'}"
    )


    if group.get("tags"):

        text += f"\n🏷 {group.get('tags')}"


    return text


async def send_marketplace_group_card(context, chat_id, group, user_id=None):

    caption = format_marketplace_group_caption(group)
    keyboard = build_marketplace_group_keyboard(group, user_id=user_id)


    if group.get("preview_video_file_id"):

        await context.bot.send_video(
            chat_id=chat_id,
            video=group.get("preview_video_file_id"),
            caption=caption,
            reply_markup=keyboard
        )

        return


    if group.get("preview_image_file_id"):

        await context.bot.send_photo(
            chat_id=chat_id,
            photo=group.get("preview_image_file_id"),
            caption=caption,
            reply_markup=keyboard
        )

        return


    await send_clean_message(
        context,
        chat_id,
        caption,
        reply_markup=keyboard
    )


async def send_marketplace_preview(context, chat_id, group, user_id=None):

    caption = format_marketplace_preview_caption(group)
    keyboard = build_marketplace_access_keyboard(
        group.get("id"),
        group.get("is_free_group"),
        f"marketplace_group_{group.get('id')}",
        user_id=user_id
    )
    preview_mode = group.get("preview_mode") or "manual"


    if preview_mode == "manual" and group.get("preview_video_file_id"):

        await context.bot.send_video(
            chat_id=chat_id,
            video=group.get("preview_video_file_id"),
            caption=caption,
            reply_markup=keyboard
        )

        return


    if preview_mode == "manual" and group.get("preview_image_file_id"):

        await context.bot.send_photo(
            chat_id=chat_id,
            photo=group.get("preview_image_file_id"),
            caption=caption,
            reply_markup=keyboard
        )

        return


    await send_clean_message(
        context,
        chat_id,
        caption,
        reply_markup=keyboard
    )


async def send_marketplace_list(context, chat_id, user_id, filter_kind="trending"):

    groups = attach_favorite_state(
        fetch_marketplace_groups(filter_kind),
        user_id
    )
    title = MARKETPLACE_FILTER_LABELS.get(
        filter_kind,
        MARKETPLACE_FILTER_LABELS.get("trending")
    )


    if not groups:

        await send_clean_message(
            context,
            chat_id,
            "Todavía no hay comunidades publicadas.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🚀 Publicar mi comunidad",
                    callback_data="public_monetize_community"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return


    text_parts = [
        f"{title}\n\nElige una comunidad para abrir su ficha."
    ]


    for group in groups:

        text_parts.append(format_marketplace_card(group))


    await send_clean_message(
        context,
        chat_id,
        "\n\n".join(text_parts),
        reply_markup=InlineKeyboardMarkup(
            build_marketplace_cards_keyboard(groups, user_id, filter_kind)
        )
    )


def can_edit_marketplace_preview(request_row, user_id):

    return (
        is_super_admin(user_id)
        or commercial_request_belongs_to_user(request_row, user_id)
    )


def get_marketplace_group_id_for_request(request_row):

    group_row = resolve_commercial_request_group(request_row)

    if not group_row:

        return None


    return group_row[0]


def build_creator_marketplace_keyboard(request_id):

    return [
        [InlineKeyboardButton(
            "⚙️ Nivel de preview",
            callback_data=f"creator_preview_mode_{request_id}"
        )],
        [InlineKeyboardButton(
            "📝 Editar texto preview",
            callback_data=f"creator_preview_text_{request_id}"
        )],
        [InlineKeyboardButton(
            "🖼 Añadir imagen preview",
            callback_data=f"creator_preview_image_{request_id}"
        )],
        [InlineKeyboardButton(
            "🎬 Añadir vídeo preview",
            callback_data=f"creator_preview_video_{request_id}"
        )],
        [InlineKeyboardButton(
            "📂 Elegir categoría",
            callback_data=f"creator_preview_category_{request_id}"
        )],
        [InlineKeyboardButton(
            "🏷 Editar tags",
            callback_data=f"creator_preview_tags_{request_id}"
        )],
        [InlineKeyboardButton(
            "👁 Ver cómo quedará",
            callback_data=f"creator_preview_show_{request_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"configure_community_{request_id}"
        )]
    ]


def build_preview_mode_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔒 Privado / mínimo",
            callback_data=f"creator_preview_mode_set_{request_id}_private"
        )],
        [InlineKeyboardButton(
            "📝 Manual",
            callback_data=f"creator_preview_mode_set_{request_id}_manual"
        )],
        [InlineKeyboardButton(
            "⚡ Dinámico",
            callback_data=f"creator_preview_mode_set_{request_id}_dynamic"
        )],
        [InlineKeyboardButton(
            "💎 Mixto",
            callback_data=f"creator_preview_mode_set_{request_id}_hybrid"
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


def build_creator_marketplace_text(group_id):

    text = (
        "👁 Preview marketplace\n\n"
        "Configura cómo se verá tu comunidad en Explorar comunidades privadas."
    )


    if not group_id:

        return (
            f"{text}\n\n"
            "Estado: pendiente de grupo/canal vinculado.\n"
            "Primero vincula un grupo real para guardar imagen, vídeo, categoría y tags."
        )


    group = fetch_marketplace_group(group_id)


    if not group:

        return f"{text}\n\nEstado: comunidad no disponible o pendiente de publicación."


    return (
        f"{text}\n\n"
        f"Nivel de preview: {PREVIEW_MODE_LABELS.get(group.get('preview_mode'), group.get('preview_mode') or 'manual')}\n"
        f"Texto preview: {'configurado' if group.get('preview_text') else 'pendiente'}\n"
        f"Imagen preview: {'configurada' if group.get('preview_image_file_id') else 'pendiente'}\n"
        f"Vídeo preview: {'configurado' if group.get('preview_video_file_id') else 'pendiente'}\n"
        f"Categoría: {format_marketplace_category(group)}\n"
        f"Tags: {group.get('tags') or 'pendiente'}"
    )


def format_commercial_datetime(value):

    if not value:

        return "-"


    try:

        return value.strftime("%Y-%m-%d %H:%M")

    except Exception:

        return str(value)


def get_commercial_request_title(request_row):

    return (
        request_row.get("community_name")
        or request_row.get("bot_name")
        or request_row.get("project_description")
        or "-"
    )


def fetch_pending_commercial_requests():

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status='pending'
            ORDER BY created_at ASC
            LIMIT 10

        """)

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def fetch_commercial_request(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE id=%s

            LIMIT 1

        """, (request_id,))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def fetch_active_commercial_plans(product_type):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_PLAN_FIELDS)}
            FROM commercial_plans
            WHERE product_type=%s
            AND is_active=TRUE
            ORDER BY duration_days ASC

        """, (product_type,))

        rows = cur.fetchall()


    return [
        row_to_commercial_plan(row)
        for row in rows
    ]


def fetch_commercial_plan(plan_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_PLAN_FIELDS)}
            FROM commercial_plans
            WHERE id=%s
            AND is_active=TRUE

            LIMIT 1

        """, (plan_id,))

        row = cur.fetchone()


    return row_to_commercial_plan(row)


def commercial_request_belongs_to_user(request_row, user_id):

    if not request_row:

        return False


    return int(request_row.get("user_id") or 0) == int(user_id)


def format_commercial_plan_price(plan):

    if plan.get("amount") is None:

        return "pendiente de precio"


    currency = plan.get("currency") or "EUR"
    amount = plan.get("amount")

    return f"{amount / 100:.2f} {currency}"


def resolve_commercial_request_group(request_row):

    if not request_row:

        return None


    approved_group_id = request_row.get("approved_group_id")
    approved_telegram_group_id = request_row.get("approved_telegram_group_id")


    try:

        with conn.cursor() as cur:

            if approved_group_id:

                cur.execute("""

                    SELECT id,
                           telegram_group_id
                    FROM groups
                    WHERE id=%s
                    LIMIT 1

                """, (approved_group_id,))

                row = cur.fetchone()


                if row:

                    return row


            if approved_telegram_group_id:

                cur.execute("""

                    SELECT id,
                           telegram_group_id
                    FROM groups
                    WHERE telegram_group_id=%s
                    LIMIT 1

                """, (approved_telegram_group_id,))

                row = cur.fetchone()


                if row:

                    return row

    except Exception as e:

        print("Error resolviendo grupo comercial:", e)


    return None


def assign_owner_for_commercial_request(request_row):

    group_row = resolve_commercial_request_group(request_row)


    if not group_row:

        return False, None


    group_id, telegram_group_id = group_row
    owner_user_id = request_row.get("user_id")


    if not owner_user_id:

        return False, group_id


    assigned = assign_group_owner_permissions(
        owner_user_id,
        group_id
    )


    if assigned:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE commercial_requests
                SET approved_group_id=%s,
                    approved_telegram_group_id=%s,
                    updated_at=NOW()
                WHERE id=%s

            """, (
                group_id,
                telegram_group_id,
                request_row.get("id")
            ))

            cur.execute("""

                UPDATE group_payment_settings
                SET group_id=%s,
                    updated_at=NOW()
                WHERE commercial_request_id=%s

            """, (
                group_id,
                request_row.get("id")
            ))


        public_visibility = request_row.get("requested_public_visibility")


        if public_visibility:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups
                    SET public_visibility=%s,
                        is_free_group=%s
                    WHERE id=%s

                """, (
                    public_visibility,
                    request_row.get("is_free_group") is True
                    or request_row.get("payment_mode") == "free",
                    group_id
                ))


        else:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups
                    SET is_free_group=%s
                    WHERE id=%s

                """, (
                    request_row.get("is_free_group") is True
                    or request_row.get("payment_mode") == "free",
                    group_id
                ))


    return assigned, group_id


def get_group_payment_settings(request_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT is_configured,
                   owner_stripe_secret_key,
                   owner_stripe_webhook_secret,
                   owner_stripe_publishable_key
            FROM group_payment_settings
            WHERE commercial_request_id=%s
            LIMIT 1

        """, (request_id,))

        return cur.fetchone()


def get_creator_plan_count(group_id):

    if not group_id:

        return 0


    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*)
            FROM plans
            WHERE group_id=%s
            AND is_active=TRUE

        """, (group_id,))

        return cur.fetchone()[0]


def build_creator_setup_keyboard(request_id, payment_mode=None):

    keyboard = [

        [InlineKeyboardButton(
            "📡 Grupo o canal",
            callback_data=f"creator_setup_group_{request_id}"
        )],

        [InlineKeyboardButton(
            "📝 Textos y descripción",
            callback_data=f"creator_setup_texts_{request_id}"
        )],

        [InlineKeyboardButton(
            "💳 Tipo de acceso",
            callback_data=f"creator_setup_access_type_{request_id}"
        )]

    ]


    if payment_mode == "paid":

        keyboard.append([
            InlineKeyboardButton(
                "💳 Cobros / Stripe propio",
                callback_data=f"creator_setup_stripe_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "💰 Planes de acceso",
                callback_data=f"creator_setup_plans_{request_id}"
            )
        ])

    elif payment_mode == "free":

        keyboard.append([
            InlineKeyboardButton(
                "💰 Planes de acceso",
                callback_data=f"creator_setup_plans_not_applicable_{request_id}"
            )
        ])

    else:

        keyboard.append([
            InlineKeyboardButton(
                "💳 Cobros / Stripe propio",
                callback_data=f"creator_setup_stripe_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "💰 Planes de acceso",
                callback_data=f"creator_setup_plans_{request_id}"
            )
        ])


    keyboard.extend([

        [InlineKeyboardButton(
            "👁 Visibilidad pública",
            callback_data=f"creator_setup_visibility_{request_id}"
        )],

        [InlineKeyboardButton(
            "👁 Preview marketplace",
            callback_data=f"creator_setup_marketplace_{request_id}"
        )],

        [InlineKeyboardButton(
            "✅ Revisar configuración",
            callback_data=f"creator_setup_review_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Tengo un código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "🧭 Tutorial paso a paso",
            callback_data=f"creator_setup_tutorial_{request_id}"
        )],

        [InlineKeyboardButton(
            "🤖 Ayuda IA de configuración",
            callback_data=f"creator_setup_ai_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver al inicio",
            callback_data="public_back_start"
        )]

    ])

    return keyboard


def build_creator_setup_panel_text(group_id=None):

    text = (
        "📦 Configuración de tu comunidad\n\n"
        "Desde aquí puedes dejar preparada tu comunidad durante la prueba."
    )


    if not group_id:

        text += (
            "\n\n"
            "Estado del grupo: pendiente de crear/publicar grupo.\n\n"
            "Para vincular tu grupo:\n\n"
            "1. Pulsa 📡 Grupo o canal.\n"
            "2. Añade el bot a tu grupo como administrador.\n"
            "3. Espera 30 segundos.\n"
            "4. El bot te enviará el ID por privado.\n"
            "5. Vuelve a 📡 Grupo o canal.\n"
            "6. Pega ahí el ID recibido si no se vinculó automáticamente."
        )


    return text


def start_creator_setup_state(context, request_id, action):

    waiting_states = {
        "group": "creator_setup_waiting_group_id",
        "texts": "creator_setup_waiting_text_name",
        "marketplace_preview_text": "creator_setup_waiting_preview_text",
        "marketplace_tags": "creator_setup_waiting_tags",
        "stripe": "creator_setup_waiting_stripe_secret",
        "plan": "creator_setup_waiting_plan_name",
        "promo_code": "creator_setup_waiting_promo_code"
    }

    context.user_data["creator_setup"] = True
    context.user_data["creator_setup_request_id"] = request_id
    context.user_data["creator_setup_action"] = action
    context.user_data["creator_setup_step"] = 1
    context.user_data["creator_setup_data"] = {}
    context.user_data["creator_setup_waiting"] = waiting_states.get(action)


def build_creator_setup_summary(request_row):

    request_id = request_row.get("id")
    assigned, group_id = assign_owner_for_commercial_request(request_row)


    if group_id and not assigned:

        owner_status = "pendiente"

    elif group_id:

        owner_status = "asignado"

    else:

        owner_status = "pendiente"


    payment_settings = get_group_payment_settings(request_id)
    stripe_status = "configurado" if payment_settings and payment_settings[0] else "pendiente"
    plan_count = get_creator_plan_count(group_id)
    group_status = "configurado" if group_id else "pendiente"
    texts_status = (
        "configurado"
        if request_row.get("community_name")
        and request_row.get("community_description")
        else "pendiente"
    )
    visibility = format_public_visibility(
        request_row.get("requested_public_visibility")
    )
    setup_ready = (
        group_status == "configurado"
        and texts_status == "configurado"
        and (
            request_row.get("payment_mode") != "paid"
            or (
                stripe_status == "configurado"
                and plan_count > 0
            )
        )
    )
    setup_status = "setup_ready" if setup_ready else "setup_in_progress"


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE commercial_requests
            SET creator_setup_status=%s,
                updated_at=NOW()
            WHERE id=%s

        """, (
            setup_status,
            request_id
        ))


    return (
        "✅ Revisar configuración\n\n"
        f"Grupo/canal: {group_status}\n"
        f"Textos: {texts_status}\n"
        f"Stripe propio: {stripe_status}\n"
        f"Planes: {plan_count}\n"
        f"Visibilidad: {visibility}\n"
        f"Estado owner: {owner_status}\n"
        f"Estado setup: {setup_status}\n\n"
        "El checkout real con Stripe del creador todavía está pendiente de conectar."
    )


def build_user_activation_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "📦 Configurar comunidad",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Tengo un código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "💬 Ayuda",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )]

    ]


def build_user_trial_payment_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🏦 Configurar mi propio Stripe/cobro",
            callback_data=f"user_trial_setup_owner_stripe_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Configurar comunidad",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "💬 Ayuda",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )]

    ]


def build_user_trial_choice_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🆓 Mi comunidad será gratuita",
            callback_data=f"user_trial_setup_free_{request_id}"
        )],

        [InlineKeyboardButton(
            "💳 Mi comunidad será de pago",
            callback_data=f"user_trial_setup_paid_{request_id}"
        )],

        [InlineKeyboardButton(
            "💬 Ayuda",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )]

    ]


def build_commercial_plan_keyboard(request_id, plans):

    keyboard = []


    for plan in plans:

        plan_id = plan.get("id")
        label = (
            f"{plan.get('name') or '-'} — "
            f"{format_commercial_plan_price(plan)}"
        )

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"user_commercial_plan_{request_id}_{plan_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "💬 Ayuda",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )
    ])

    return keyboard


def build_direct_activation_plan_keyboard(plans):

    keyboard = []


    for plan in plans:

        plan_id = plan.get("id")
        label = (
            f"{plan.get('name') or '-'} — "
            f"{format_commercial_plan_price(plan)}"
        )

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"commercial_direct_plan_{plan_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=CALLBACK_SHARED_BOT_SPACE
        )
    ])

    return keyboard


def build_admin_trial_visibility_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🏠 Publicar en inicio",
            callback_data=f"admin_trial_visibility_start_home_{request_id}"
        )],

        [InlineKeyboardButton(
            "🔎 Publicar en explorar",
            callback_data=f"admin_trial_visibility_explore_only_{request_id}"
        )],

        [InlineKeyboardButton(
            "🙈 Dejar oculta/borrador",
            callback_data=f"admin_trial_visibility_hidden_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"admin_commercial_review_{request_id}"
        )]

    ]


def build_commercial_requests_text(requests):

    if not requests:

        return (
            "📩 Solicitudes comerciales\n\n"
            "No hay solicitudes pendientes."
        )


    lines = [
        "📩 Solicitudes comerciales pendientes"
    ]


    for request_row in requests:

        username = request_row.get("username") or "-"

        if username != "-" and not username.startswith("@"):

            username = f"@{username}"


        lines.append(
            "\n"
            f"ID: {request_row.get('id')}\n"
            f"Tipo: {format_commercial_request_type(request_row.get('request_type'))}\n"
            f"Usuario: {request_row.get('user_id') or '-'}\n"
            f"Username: {username}\n"
            f"Nombre: {get_commercial_request_title(request_row)}\n"
            f"Contacto: {request_row.get('contact_text') or '-'}\n"
            f"Fecha: {format_commercial_datetime(request_row.get('created_at'))}"
        )


    return "\n".join(lines)


def build_commercial_requests_keyboard(requests):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                f"✅ Revisar #{request_id}",
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_back_main"
        )
    ])

    return keyboard


def build_commercial_request_detail_text(request_row):

    username = request_row.get("username") or "-"

    if username != "-" and not username.startswith("@"):

        username = f"@{username}"


    return (
        "📩 Solicitud comercial\n\n"
        f"ID: {request_row.get('id')}\n"
        f"Estado: {request_row.get('status') or '-'}\n"
        f"Tipo: {format_commercial_request_type(request_row.get('request_type'))}\n"
        f"Usuario: {request_row.get('user_id') or '-'}\n"
        f"Username: {username}\n"
        f"Nombre Telegram: {request_row.get('first_name') or '-'}\n\n"
        f"Comunidad/proyecto: {request_row.get('community_name') or '-'}\n"
        f"Descripción comunidad: {request_row.get('community_description') or '-'}\n"
        f"Link grupo/canal: {request_row.get('telegram_group_link') or '-'}\n"
        f"Nombre bot: {request_row.get('bot_name') or '-'}\n"
        f"Username bot: {request_row.get('bot_username') or '-'}\n"
        f"Descripción proyecto: {request_row.get('project_description') or '-'}\n"
        f"Contacto: {request_row.get('contact_text') or '-'}\n\n"
        f"Creada: {format_commercial_datetime(request_row.get('created_at'))}\n"
        f"Revisada por: {request_row.get('reviewed_by') or '-'}\n"
        f"Revisada: {format_commercial_datetime(request_row.get('reviewed_at'))}\n"
        f"Inicio prueba: {format_commercial_datetime(request_row.get('trial_starts_at'))}\n"
        f"Fin prueba: {format_commercial_datetime(request_row.get('trial_ends_at'))}\n"
        f"Modo pago: {request_row.get('payment_mode') or '-'}\n"
        f"Modo Stripe: {request_row.get('stripe_mode') or '-'}\n"
        f"Ubicación pública solicitada: {format_public_visibility(request_row.get('requested_public_visibility'))}\n"
        f"Estado configuración creador: {request_row.get('creator_setup_status') or '-'}\n"
        f"Preview creador: {request_row.get('creator_preview_text') or '-'}\n"
        f"Cupo máximo grupos: {request_row.get('max_groups_allowed') or 1}\n"
        f"Plan comercial: {request_row.get('selected_commercial_plan_id') or '-'}\n"
        f"Estado suscripción comercial: {request_row.get('commercial_subscription_status') or '-'}\n"
        f"Suscripción comercial hasta: {format_commercial_datetime(request_row.get('commercial_subscription_until'))}"
    )


def build_commercial_review_keyboard(request_row):

    request_id = request_row.get("id")
    request_type = request_row.get("request_type")
    keyboard = []


    if request_type == "shared_trial":

        keyboard.append([
            InlineKeyboardButton(
                "✅ Aprobar prueba 1 día",
                callback_data=f"admin_commercial_approve_trial_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "❌ Rechazar",
                callback_data=f"admin_commercial_reject_{request_id}"
            )
        ])

    elif request_type == "custom_bot":

        keyboard.append([
            InlineKeyboardButton(
                "✅ Aprobar configuración",
                callback_data=f"admin_commercial_approve_custom_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "❌ Rechazar",
                callback_data=f"admin_commercial_reject_{request_id}"
            )
        ])

    else:

        keyboard.append([
            InlineKeyboardButton(
                "❌ Rechazar",
                callback_data=f"admin_commercial_reject_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "🔢 Cupo de grupos",
            callback_data=f"admin_commercial_group_limit_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_commercial_requests"
        )
    ])

    return keyboard


def build_commercial_group_limit_text(request_row):

    return (
        "🔢 Cupo de grupos\n\n"
        f"Solicitud: #{request_row.get('id')}\n"
        f"Creador: {request_row.get('user_id') or '-'}\n"
        f"Cupo actual: {request_row.get('max_groups_allowed') or 1}\n\n"
        "Elige el máximo de comunidades que este creador puede añadir."
    )


def build_commercial_group_limit_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "1 grupo",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_1"
        )],

        [InlineKeyboardButton(
            "2 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_2"
        )],

        [InlineKeyboardButton(
            "5 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_5"
        )],

        [InlineKeyboardButton(
            "10 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_10"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"admin_commercial_review_{request_id}"
        )]

    ]


COMMERCIAL_PROMO_DURATIONS = {
    "15d": (15, "15 días"),
    "1m": (30, "1 mes"),
    "3m": (90, "3 meses"),
    "1y": (365, "1 año")
}


def generate_commercial_promo_code():

    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(
        secrets.choice(alphabet)
        for _ in range(8)
    )

    return f"OWNER-{suffix}"


def create_commercial_promo_code(duration_days, created_by):

    for _ in range(5):

        code = generate_commercial_promo_code()

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO commercial_promo_codes
                    (
                        code,
                        duration_days,
                        max_uses,
                        uses_count,
                        is_active,
                        created_by,
                        updated_at
                    )
                    VALUES (%s, %s, 1, 0, TRUE, %s, NOW())
                    RETURNING id, code, duration_days

                """, (
                    code,
                    duration_days,
                    created_by
                ))

                return cur.fetchone()

        except Exception as e:

            print("Error creando código promocional comercial:", e)


    return None


def fetch_active_commercial_promo_codes():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   code,
                   duration_days,
                   max_uses,
                   uses_count,
                   created_by,
                   created_at
            FROM commercial_promo_codes
            WHERE is_active=TRUE
            AND uses_count < max_uses
            ORDER BY created_at DESC
            LIMIT 20

        """)

        return cur.fetchall()


def deactivate_commercial_promo_code(code_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE commercial_promo_codes
            SET is_active=FALSE,
                updated_at=NOW()
            WHERE id=%s
            RETURNING code

        """, (code_id,))

        row = cur.fetchone()

    return row[0] if row else None


def format_commercial_promo_duration(days):

    if days == 15:

        return "15 días"

    if days == 30:

        return "1 mes"

    if days == 90:

        return "3 meses"

    if days == 365:

        return "1 año"

    return f"{days} días"


def build_commercial_promo_codes_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Crear código 15 días",
            callback_data="admin_commercial_promo_create_15d"
        )],
        [InlineKeyboardButton(
            "Crear código 1 mes",
            callback_data="admin_commercial_promo_create_1m"
        )],
        [InlineKeyboardButton(
            "Crear código 3 meses",
            callback_data="admin_commercial_promo_create_3m"
        )],
        [InlineKeyboardButton(
            "Crear código 1 año",
            callback_data="admin_commercial_promo_create_1y"
        )],
        [InlineKeyboardButton(
            "Ver códigos activos",
            callback_data="admin_commercial_promo_active"
        )],
        [InlineKeyboardButton(
            "Desactivar código",
            callback_data="admin_commercial_promo_deactivate_menu"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_back_main"
        )]
    ])


def build_commercial_promo_active_text(rows):

    if not rows:

        return "🎟 Códigos promocionales\n\nNo hay códigos activos."


    lines = ["🎟 Códigos promocionales activos"]


    for row in rows:

        code_id, code, duration_days, max_uses, uses_count, created_by, created_at = row
        lines.append(
            "\n"
            f"ID: {code_id}\n"
            f"Código: {code}\n"
            f"Duración: {format_commercial_promo_duration(duration_days)}\n"
            f"Usos: {uses_count}/{max_uses}\n"
            f"Creado por: {created_by or '-'}\n"
            f"Fecha: {format_commercial_datetime(created_at)}"
        )


    return "\n".join(lines)


def build_commercial_promo_deactivate_keyboard(rows):

    keyboard = []


    for row in rows:

        code_id, code, *_rest = row
        keyboard.append([InlineKeyboardButton(
            f"Desactivar {code}",
            callback_data=f"admin_commercial_promo_deactivate_{code_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="admin_commercial_promo_codes"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_commercial_setup_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🆓 Grupo gratuito",
            callback_data=f"commercial_setup_free_group_{request_id}"
        )],

        [InlineKeyboardButton(
            "💳 Grupo de pago",
            callback_data=f"commercial_setup_paid_group_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏦 Stripe del dueño",
            callback_data=f"commercial_setup_owner_stripe_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_commercial_requests"
        )]

    ]


def extract_commercial_request_id(data, prefix):

    try:

        return int(data.replace(prefix, "", 1))

    except Exception:

        return None


def extract_commercial_group_limit_selection(data):

    prefix = "admin_commercial_set_group_limit_"


    try:

        raw_value = data.replace(prefix, "", 1)
        request_id_text, limit_text = raw_value.rsplit("_", 1)
        request_id = int(request_id_text)
        limit = int(limit_text)

    except Exception:

        return None, None


    if limit not in (1, 2, 5, 10):

        return None, None


    return request_id, limit


def update_commercial_request_group_limit(request_id, max_groups_allowed):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET max_groups_allowed=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            max_groups_allowed,
            request_id
        ))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def update_commercial_request_trial_approved(request_id, reviewer_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='trial_active',
                reviewed_by=%s,
                reviewed_at=NOW(),
                trial_starts_at=NOW(),
                trial_ends_at=NOW() + INTERVAL '1 day',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, request_id))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def update_commercial_request_trial_visibility(
    request_id,
    reviewer_id,
    public_visibility
):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='trial_active',
                reviewed_by=%s,
                reviewed_at=NOW(),
                trial_starts_at=COALESCE(trial_starts_at, NOW()),
                trial_ends_at=COALESCE(trial_ends_at, NOW() + INTERVAL '1 day'),
                requested_public_visibility=%s,
                creator_setup_status='awaiting_creator_setup',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, public_visibility, request_id))

        row = cur.fetchone()


    request_row = row_to_commercial_request(row)


    if not request_row:

        return None


    assign_owner_for_commercial_request(request_row)


    return request_row


def update_commercial_request_custom_approved(request_id, reviewer_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='awaiting_payment',
                reviewed_by=%s,
                reviewed_at=NOW(),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, request_id))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def update_commercial_request_rejected(request_id, reviewer_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='rejected',
                reviewed_by=%s,
                reviewed_at=NOW(),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, request_id))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def update_commercial_request_free_group(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET payment_mode='free',
                is_free_group=TRUE,
                status='trial_active',
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()

        request_row = row_to_commercial_request(row)


        if request_row and request_row.get("approved_group_id"):

            cur.execute("""

                UPDATE groups
                SET is_free_group=TRUE
                WHERE id=%s

            """, (request_row.get("approved_group_id"),))


    return row_to_commercial_request(row)


def update_commercial_request_paid_group(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET payment_mode='paid',
                is_free_group=FALSE,
                status='awaiting_payment_setup',
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()

        request_row = row_to_commercial_request(row)


        if request_row and request_row.get("approved_group_id"):

            cur.execute("""

                UPDATE groups
                SET is_free_group=FALSE
                WHERE id=%s

            """, (request_row.get("approved_group_id"),))


    return row_to_commercial_request(row)


def update_commercial_request_access_type(request_id, payment_mode):

    is_free = payment_mode == "free"


    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET payment_mode=%s,
                is_free_group=%s,
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            payment_mode,
            is_free,
            request_id
        ))

        row = cur.fetchone()
        request_row = row_to_commercial_request(row)


        if request_row and request_row.get("approved_group_id"):

            cur.execute("""

                UPDATE groups
                SET is_free_group=%s
                WHERE id=%s

            """, (
                is_free,
                request_row.get("approved_group_id")
            ))


    return request_row


def build_access_type_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔓 Comunidad gratuita",
            callback_data=f"creator_setup_access_free_{request_id}"
        )],
        [InlineKeyboardButton(
            "💎 Comunidad de pago",
            callback_data=f"creator_setup_access_paid_{request_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"configure_community_{request_id}"
        )]
    ])


def update_commercial_request_stripe_mode(request_id, stripe_mode):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET stripe_mode=%s,
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (stripe_mode, request_id))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def update_commercial_request_plan(request_id, plan_id, subscription_status):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET selected_commercial_plan_id=%s,
                commercial_subscription_status=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            plan_id,
            subscription_status,
            request_id
        ))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def disable_commercial_request_community(request_row):

    if not request_row:

        return None


    request_id = request_row.get("id")
    approved_group_id = request_row.get("approved_group_id")
    approved_telegram_group_id = request_row.get("approved_telegram_group_id")


    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='disabled',
                commercial_subscription_status='cancelled',
                requested_public_visibility='hidden',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()


        if approved_group_id:

            cur.execute("""

                UPDATE groups
                SET public_visibility='hidden',
                    is_active=FALSE
                WHERE id=%s

            """, (approved_group_id,))

        elif approved_telegram_group_id:

            cur.execute("""

                UPDATE groups
                SET public_visibility='hidden',
                    is_active=FALSE
                WHERE telegram_group_id=%s

            """, (approved_telegram_group_id,))


    return row_to_commercial_request(row)


def extract_commercial_plan_selection(data):

    try:

        payload = data.replace("user_commercial_plan_", "", 1)
        request_id, plan_id = payload.split("_", 1)

        return int(request_id), int(plan_id)

    except Exception:

        return None, None


async def notify_commercial_admin(context, text, reply_markup=None):

    try:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            reply_markup=reply_markup
        )

        return True

    except Exception as e:

        print("Error avisando admin comercial:", e)

        return False


async def notify_commercial_request_user(context, request_row, text, reply_markup=None):

    user_id = request_row.get("user_id") if request_row else None


    if not user_id:

        return False


    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup
        )

        return True

    except Exception as e:

        print("Error avisando solicitud comercial:", e)

    return False


SUPPORT_TICKET_FIELDS = [
    "id",
    "user_id",
    "username",
    "first_name",
    "status",
    "created_at",
    "updated_at",
    "last_message_at"
]


def row_to_support_ticket(row):

    if not row:

        return None


    return dict(zip(SUPPORT_TICKET_FIELDS, row))


def fetch_support_ticket(ticket_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
            FROM support_tickets
            WHERE id=%s
            LIMIT 1

        """, (ticket_id,))

        row = cur.fetchone()


    return row_to_support_ticket(row)


def fetch_user_support_ticket(ticket_id, user_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
            FROM support_tickets
            WHERE id=%s
            AND user_id=%s
            LIMIT 1

        """, (
            ticket_id,
            user_id
        ))

        row = cur.fetchone()


    return row_to_support_ticket(row)


def get_or_create_support_ticket(user):

    username = user.username if user and user.username else None
    first_name = user.first_name if user and user.first_name else None
    user_id = user.id if user else None


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
            FROM support_tickets
            WHERE user_id=%s
            AND status IN ('open', 'answered')
            ORDER BY last_message_at DESC
            LIMIT 1

        """, (user_id,))

        row = cur.fetchone()


        if row:

            cur.execute("""

                UPDATE support_tickets
                SET username=%s,
                    first_name=%s,
                    status='open',
                    updated_at=NOW(),
                    last_message_at=NOW()
                WHERE id=%s

            """, (
                username,
                first_name,
                row[0]
            ))

            return row_to_support_ticket(row)


        cur.execute(f"""

            INSERT INTO support_tickets
            (
                user_id,
                username,
                first_name,
                status,
                updated_at,
                last_message_at
            )
            VALUES (%s, %s, %s, 'open', NOW(), NOW())
            RETURNING {", ".join(SUPPORT_TICKET_FIELDS)}

        """, (
            user_id,
            username,
            first_name
        ))

        row = cur.fetchone()


    return row_to_support_ticket(row)


def create_support_message(ticket_id, sender_type, sender_id, message_text):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO support_messages
            (
                ticket_id,
                sender_type,
                sender_id,
                message_text
            )
            VALUES (%s, %s, %s, %s)

        """, (
            ticket_id,
            sender_type,
            sender_id,
            message_text
        ))


def update_support_ticket_status(ticket_id, status):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE support_tickets
            SET status=%s,
                updated_at=NOW(),
                last_message_at=NOW()
            WHERE id=%s

        """, (
            status,
            ticket_id
        ))


def fetch_support_messages(ticket_id, limit=8):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT sender_type,
                   sender_id,
                   message_text,
                   created_at
            FROM support_messages
            WHERE ticket_id=%s
            ORDER BY created_at DESC
            LIMIT %s

        """, (
            ticket_id,
            limit
        ))

        rows = cur.fetchall()


    return list(reversed(rows))


def fetch_recent_support_tickets():

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
            FROM support_tickets
            WHERE status IN ('open', 'answered')
            ORDER BY last_message_at DESC
            LIMIT 20

        """)

        rows = cur.fetchall()


    return [
        row_to_support_ticket(row)
        for row in rows
    ]


def format_support_username(ticket):

    username = ticket.get("username") if ticket else None


    if not username:

        return "-"


    if not username.startswith("@"):

        return f"@{username}"


    return username


def format_support_messages(messages):

    if not messages:

        return "Sin mensajes todavía."


    lines = []


    for sender_type, sender_id, message_text, created_at in messages:

        label = "Usuario" if sender_type == "user" else "Admin"
        timestamp = format_commercial_datetime(created_at)
        lines.append(
            f"{label} ({sender_id}) · {timestamp}\n{message_text or '-'}"
        )


    return "\n\n".join(lines)


def build_support_ticket_detail_text(ticket):

    messages = fetch_support_messages(
        ticket.get("id"),
        limit=10
    )

    return (
        f"🛟 Ticket #{ticket.get('id')}\n\n"
        f"Estado: {ticket.get('status') or '-'}\n"
        f"Usuario: {ticket.get('user_id') or '-'}\n"
        f"Username: {format_support_username(ticket)}\n"
        f"Nombre: {ticket.get('first_name') or '-'}\n"
        f"Último mensaje: {format_commercial_datetime(ticket.get('last_message_at'))}\n\n"
        f"{format_support_messages(messages)}"
    )


def build_support_ticket_keyboard(ticket_id):

    return [

        [InlineKeyboardButton(
            "✍️ Responder",
            callback_data=f"admin_support_reply_{ticket_id}"
        )],

        [InlineKeyboardButton(
            "✅ Cerrar ticket",
            callback_data=f"admin_support_close_{ticket_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_support_tickets"
        )]

    ]


def build_support_tickets_text(tickets):

    if not tickets:

        return (
            "🛟 Soporte\n\n"
            "No hay tickets abiertos."
        )


    lines = ["🛟 Tickets de soporte"]


    for ticket in tickets:

        messages = fetch_support_messages(
            ticket.get("id"),
            limit=1
        )
        last_message = messages[-1][2] if messages else "-"

        lines.append(
            "\n"
            f"Ticket #{ticket.get('id')}\n"
            f"Estado: {ticket.get('status') or '-'}\n"
            f"Usuario: {ticket.get('user_id') or '-'}\n"
            f"Username: {format_support_username(ticket)}\n"
            f"Nombre: {ticket.get('first_name') or '-'}\n"
            f"Último: {last_message}\n"
            f"Fecha: {format_commercial_datetime(ticket.get('last_message_at'))}"
        )


    return "\n".join(lines)


def build_support_tickets_keyboard(tickets):

    keyboard = []


    for ticket in tickets:

        username = format_support_username(ticket)
        label_name = username if username != "-" else ticket.get("first_name") or ticket.get("user_id")

        keyboard.append([
            InlineKeyboardButton(
                f"📨 Ticket #{ticket.get('id')} - {label_name}",
                callback_data=f"admin_support_ticket_{ticket.get('id')}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_back_main"
        )
    ])

    return keyboard


async def notify_support_admin(context, ticket, message_text):

    try:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🛟 Nuevo mensaje de soporte\n\n"
                f"Usuario: {ticket.get('user_id')}\n"
                f"Username: {format_support_username(ticket)}\n"
                f"Ticket: #{ticket.get('id')}\n\n"
                f"{message_text}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📨 Abrir ticket",
                    callback_data=f"admin_support_ticket_{ticket.get('id')}"
                )]
            ])
        )

        return True

    except Exception as e:

        print("Error avisando soporte admin:", e)

        return False


async def handle_user_support_message(update, context, text):

    user = update.effective_user
    ticket = get_or_create_support_ticket(user)

    create_support_message(
        ticket.get("id"),
        "user",
        user.id,
        text
    )

    update_support_ticket_status(
        ticket.get("id"),
        "open"
    )

    await notify_support_admin(
        context,
        ticket,
        text
    )

    context.user_data["support_mode"] = False

    await update.message.reply_text(
        "✅ Mensaje enviado a soporte.\n"
        f"Tu número de ticket es #{ticket.get('id')}.\n"
        "Un administrador te responderá por aquí.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔎 Consultar ticket",
                callback_data="user_support_lookup_start"
            )],
            [InlineKeyboardButton(
                "⬅️ Volver al inicio",
                callback_data="public_back_start"
            )]
        ])
    )


async def handle_support_lookup_message(update, context, text):

    user_id = update.effective_user.id


    try:

        ticket_id = int(text.replace("#", "").strip())

    except Exception:

        await update.message.reply_text(
            "❌ Número de ticket no válido."
        )

        return


    ticket = fetch_user_support_ticket(
        ticket_id,
        user_id
    )

    context.user_data["support_lookup_mode"] = False


    if not ticket:

        await update.message.reply_text(
            "❌ Ese ticket no existe o no pertenece a tu usuario.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver al inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return


    await update.message.reply_text(
        build_support_ticket_detail_text(ticket),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⬅️ Volver al inicio",
                callback_data="public_back_start"
            )]
        ])
    )


async def handle_admin_support_reply(update, context, text):

    admin_user = update.effective_user


    if not is_super_admin(admin_user.id):

        context.user_data.pop("replying_support_ticket", None)

        await update.message.reply_text(
            "⛔ No tienes permisos para responder soporte."
        )

        return


    ticket_id = context.user_data.get("replying_support_ticket")
    ticket = fetch_support_ticket(ticket_id)


    if not ticket:

        context.user_data.pop("replying_support_ticket", None)

        await update.message.reply_text(
            "❌ Ticket de soporte no encontrado."
        )

        return


    create_support_message(
        ticket_id,
        "admin",
        admin_user.id,
        text
    )

    update_support_ticket_status(
        ticket_id,
        "answered"
    )

    context.user_data.pop("replying_support_ticket", None)


    try:

        await context.bot.send_message(
            chat_id=ticket.get("user_id"),
            text=(
                "🛟 Respuesta de soporte:\n\n"
                f"{text}"
            )
        )

    except Exception as e:

        print("Error enviando respuesta soporte al usuario:", e)


    await update.message.reply_text(
        "✅ Respuesta enviada al usuario.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📨 Abrir ticket",
                callback_data=f"admin_support_ticket_{ticket_id}"
            )],
            [InlineKeyboardButton(
                "🛟 Tickets abiertos",
                callback_data="admin_support_tickets"
            )]
        ])
    )


async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:

        return


    text = update.message.text.strip()


    if context.user_data.get("replying_support_ticket"):

        await handle_admin_support_reply(
            update,
            context,
            text
        )

        return


    if context.user_data.get("support_lookup_mode"):

        await handle_support_lookup_message(
            update,
            context,
            text
        )

        return


    if context.user_data.get("support_mode"):

        await handle_user_support_message(
            update,
            context,
            text
        )

        return


# =========================
# BOTONES
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    user_id = query.from_user.id


    if data in (
        "public_back_start",
        CALLBACK_COMMERCIAL_BACK_START
    ):

        context.user_data["support_mode"] = False
        context.user_data["support_lookup_mode"] = False
        context.user_data.pop("replying_support_ticket", None)

        await delete_query_message_safely(query)

        await send_start_menu(
            update,
            context,
            chat_id=query.message.chat_id
        )

        return


    if data in (
        CALLBACK_COMMERCIAL_BACK_SOLUTIONS,
        CALLBACK_COMMERCIAL_BACK
    ):

        await delete_query_message_safely(query)

        await send_clean_message(
            context,
            query.message.chat_id,
            COMMERCIAL_MENU_TEXT_ES,
            reply_markup=InlineKeyboardMarkup(
                build_commercial_menu_keyboard()
            )
        )

        return


    if data == "start_explore_groups":

        await expire_expired_commercial_trials(context)

        await send_marketplace_list(
            context,
            query.message.chat_id,
            user_id,
            "trending"
        )

        return


    if data.startswith("marketplace_filter_"):

        await expire_expired_commercial_trials(context)

        filter_kind = data.replace("marketplace_filter_", "", 1)


        if filter_kind not in MARKETPLACE_FILTER_LABELS:

            filter_kind = "trending"


        await send_marketplace_list(
            context,
            query.message.chat_id,
            user_id,
            filter_kind
        )

        return


    if data.startswith("favorite_group_"):

        group_id = extract_commercial_request_id(
            data,
            "favorite_group_"
        )


        if not fetch_marketplace_group(group_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO community_favorites
                (user_id, group_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, group_id) DO NOTHING

            """, (
                user_id,
                group_id
            ))

            conn.commit()


        favorites_count = refresh_community_favorites_count(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            f"⭐ Comunidad guardada en favoritos.\n\n⭐ {format_marketplace_number(favorites_count)} favoritos",
            reply_markup=build_marketplace_access_keyboard(
                group_id,
                fetch_marketplace_group(group_id).get("is_free_group"),
                "start_explore_groups",
                user_id=user_id
            )
        )

        return


    if data.startswith("unfavorite_group_"):

        group_id = extract_commercial_request_id(
            data,
            "unfavorite_group_"
        )


        if not fetch_marketplace_group(group_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM community_favorites
                WHERE user_id=%s
                AND group_id=%s

            """, (
                user_id,
                group_id
            ))

            conn.commit()


        favorites_count = refresh_community_favorites_count(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            f"💔 Comunidad quitada de favoritos.\n\n⭐ {format_marketplace_number(favorites_count)} favoritos",
            reply_markup=build_marketplace_access_keyboard(
                group_id,
                fetch_marketplace_group(group_id).get("is_free_group"),
                "start_explore_groups",
                user_id=user_id
            )
        )

        return


    if data.startswith("marketplace_group_"):

        await expire_expired_commercial_trials(context)

        group_id = extract_commercial_request_id(
            data,
            "marketplace_group_"
        )
        group = fetch_marketplace_group(group_id)


        if not group:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        group["is_favorite"] = is_group_favorite(user_id, group_id)

        await delete_query_message_safely(query)
        await send_marketplace_group_card(
            context,
            query.message.chat_id,
            group,
            user_id=user_id
        )

        return


    if data.startswith("marketplace_dynamic_preview_"):

        group_id = extract_commercial_request_id(
            data,
            "marketplace_dynamic_preview_"
        )
        group = fetch_marketplace_group(group_id)


        if not group:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚡ Preview dinámico\n\n"
            "El preview dinámico estará disponible en una fase posterior. Por ahora puedes ver el preview manual.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "👁 Ver preview",
                    callback_data=f"marketplace_preview_{group_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver a ficha",
                    callback_data=f"marketplace_group_{group_id}"
                )]
            ])
        )

        return


    if data.startswith("marketplace_preview_"):

        group_id = extract_commercial_request_id(
            data,
            "marketplace_preview_"
        )
        group = fetch_marketplace_group(group_id)


        if not group:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        increment_community_stat(group_id, "preview_views")
        group = fetch_marketplace_group(group_id)
        group["is_favorite"] = is_group_favorite(user_id, group_id)

        await delete_query_message_safely(query)
        await send_marketplace_preview(
            context,
            query.message.chat_id,
            group,
            user_id=user_id
        )

        return


    if data == "start_no_groups":

        await send_clean_message(
            context,
            query.message.chat_id,
            "Todavía no hay comunidades publicadas.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🚀 Publicar mi comunidad",
                    callback_data="public_monetize_community"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return


    if data == "public_monetize_community":

        await delete_query_message_safely(query)

        await send_clean_message(
            context,
            query.message.chat_id,

            COMMERCIAL_MENU_TEXT_ES,

            reply_markup=InlineKeyboardMarkup(
                build_commercial_menu_keyboard()
            )

        )

        return


    if data == "public_support":

        context.user_data["support_mode"] = True
        context.user_data["support_lookup_mode"] = False

        await delete_query_message_safely(query)

        keyboard = [

            [InlineKeyboardButton(
                "🔎 Consultar ticket",
                callback_data="user_support_lookup_start"
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="public_back_start"
            )],

            [InlineKeyboardButton(
                "💬 Ayuda sobre este menú",
                callback_data=CALLBACK_SUPPORT_HELP
            )]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "🛟 Soporte\n\n"
            "Escribe tu mensaje y se lo enviaremos a un administrador.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "user_support_lookup_start":

        context.user_data["support_mode"] = False
        context.user_data["support_lookup_mode"] = True

        await query.message.reply_text(
            "🔎 Consultar ticket\n\n"
            "Escribe el número de ticket que quieres consultar. Ejemplo: 12"
        )

        return


    if data == "public_ai_help":

        await activate_ai_help_context(
            update,
            context
        )

        return


    if data == "commercial_shared_bot_space":

        await delete_query_message_safely(query)

        keyboard = [

            [InlineKeyboardButton(
                "🎁 Solicitar prueba de 1 día",
                callback_data=CALLBACK_SHARED_TRIAL_START
            )],

            [InlineKeyboardButton(
                "💳 Activar directamente sin prueba",
                callback_data="commercial_direct_activate"
            )],

            [InlineKeyboardButton(
                "📩 Hablar con un asesor",
                callback_data=CALLBACK_COMMERCIAL_CONTACT
            )],

            [InlineKeyboardButton(
                "💬 Ayuda sobre este menú",
                callback_data=CALLBACK_COMMERCIAL_HELP
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK_SOLUTIONS
            )]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "📌 Publicar mi comunidad en este bot\n\n"
            "Esta opción es para creadores que quieren empezar rápido sin crear un bot propio.\n\n"
            "Tu comunidad aparecerá dentro de nuestro bot principal. "
            "Los usuarios podrán verla y consultar sus condiciones de acceso desde aquí.\n\n"
            "✅ Incluye:\n"
            "• Publicación de tu comunidad dentro del bot.\n"
            "• Planes o condiciones de acceso configurables.\n"
            "• Accesos protegidos por el sistema.\n"
            "• Links seguros para entrar al grupo.\n"
            "• Gestión básica desde el sistema.\n\n"
            "🎁 Prueba inicial:\n"
            "Puedes probar esta opción durante 1 día para publicar tu comunidad y comprobar cómo funciona.\n\n"
            "Después de la prueba, si quieres continuar, tendrás que activar una suscripción.\n\n"
            "Si una suscripción activa se detiene o no se renueva, la comunidad podrá dejar de mostrarse para nuevas compras. "
            "Aun así, guardaremos la configuración durante 15 días para que puedas reactivarla sin tener que empezar desde cero.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_shared_trial_start":

        context.user_data["commercial_form"] = True
        context.user_data["commercial_form_type"] = "shared_trial"
        context.user_data["commercial_form_step"] = 1
        context.user_data["commercial_form_data"] = {}
        context.user_data["commercial_form_waiting"] = "creator_setup_waiting_community_name"

        await send_clean_message(
            context,
            query.message.chat_id,
            "Indica el nombre de la comunidad."
        )

        return


    if data == "commercial_direct_activate":

        plans = fetch_active_commercial_plans(PRODUCT_SHARED_BOT_SPACE)

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Activar directamente sin prueba\n\n"
            "Elige la duración comercial para publicar tu comunidad sin prueba.\n\n"
            "Si el plan no tiene pago automático configurado, un administrador debe añadir el price_id de Stripe.",
            reply_markup=InlineKeyboardMarkup(
                build_direct_activation_plan_keyboard(plans)
            )
        )

        return


    if data.startswith("commercial_direct_plan_"):

        plan_id = extract_commercial_request_id(
            data,
            "commercial_direct_plan_"
        )
        plan = fetch_commercial_plan(plan_id)


        if not plan:

            await query.message.reply_text(
                "❌ Plan comercial no encontrado."
            )

            return


        if not plan.get("stripe_price_id"):

            await query.message.reply_text(
                "Este plan todavía no tiene pago automático configurado. Un administrador debe añadir el price_id de Stripe."
            )

            await notify_commercial_admin(
                context,
                (
                    "💳 Activación directa solicitada\n\n"
                    f"Usuario: {user_id}\n"
                    f"Plan: {plan.get('name') or '-'}\n"
                    "Falta stripe_price_id."
                )
            )

            return


        await query.message.reply_text(
            "El pago automático comercial todavía está pendiente de conectar."
        )

        return


    if data == "commercial_custom_bot":

        await delete_query_message_safely(query)

        keyboard = [

            [InlineKeyboardButton(
                "🤖 Configurar mi bot personalizado",
                callback_data=CALLBACK_CUSTOM_BOT_START
            )],

            [InlineKeyboardButton(
                "📩 Hablar con un asesor",
                callback_data=CALLBACK_COMMERCIAL_CONTACT
            )],

            [InlineKeyboardButton(
                "💬 Ayuda sobre este menú",
                callback_data=CALLBACK_COMMERCIAL_HELP
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK_SOLUTIONS
            )]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "🤖 Crear mi bot personalizado\n\n"
            "Esta opción es para quien quiere una experiencia más profesional con su propio bot de Telegram.\n\n"
            "El cliente crea su bot en BotFather y configura su información, marca, textos, grupos y planes. "
            "Después de completar la configuración, realiza el pago y el sistema se activa.\n\n"
            "✅ Incluye:\n"
            "• Bot propio con nombre y marca del cliente.\n"
            "• Configuración de comunidades, grupos y planes.\n"
            "• Pagos y accesos automatizados.\n"
            "• Gestión de usuarios, links y permisos.\n"
            "• Posibilidad de usar IA y soporte dentro del sistema.\n\n"
            "⚠️ Importante:\n"
            "El bot personalizado no tiene prueba gratuita. "
            "Primero se prepara la configuración completa y, una vez pagado, el bot empieza a funcionar.\n\n"
            "Si la suscripción se detiene o no se renueva, el bot podrá quedar bloqueado o desactivado. "
            "Guardaremos la configuración durante 15 días para que puedas reactivar el servicio sin perder lo preparado.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_custom_bot_start":

        context.user_data["commercial_form"] = True
        context.user_data["commercial_form_type"] = "custom_bot"
        context.user_data["commercial_form_step"] = 1
        context.user_data["commercial_form_data"] = {}
        context.user_data["commercial_form_waiting"] = "creator_setup_waiting_project_name"

        await send_clean_message(
            context,
            query.message.chat_id,
            "Indica el nombre del proyecto o comunidad."
        )

        return


    if data == "commercial_contact":

        await delete_query_message_safely(query)

        request_id = create_commercial_request(
            query.from_user,
            "support_contact",
            {
                "contact_text": "Solicitud comercial desde botón Hablar con un asesor."
            }
        )

        await notify_commercial_request(
            context,
            request_id,
            "support_contact",
            query.from_user,
            {
                "contact_text": "Solicitud comercial desde botón Hablar con un asesor."
            }
        )

        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK_SOLUTIONS
            )]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "📩 Solicitud recibida\n\n"
            "Un administrador revisará la solicitud y podrá ayudarte con la mejor opción según lo que necesites.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="commercial"
        )

        return


    if data == "subscriptions_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="subscriptions"
        )

        return


    if data == "group_plans_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="group_plans"
        )

        return


    if data == "support_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="support"
        )

        return


    if data == "admin_users_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="admin_users"
        )

        return


    if data == "admin_groups_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="admin_groups"
        )

        return


    if data == "admin_payments_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="admin_payments"
        )

        return


    if data == "admin_logs_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="admin_logs"
        )

        return


    if data == "public_admin_panel":

        if not has_any_admin_permission(user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ No tienes permisos de gestión."
            )

            return


        keyboard = build_admin_panel_keyboard(user_id)


        if not keyboard:

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ No tienes permisos de gestión."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,

            "🔐 PANEL ADMIN",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # RBAC — BLOQUEAR CALLBACKS ADMIN
    # =========================

    if is_admin_callback(data):

        if is_super_admin(user_id):

            pass

        elif callback_requires_super_admin(data):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return

        elif not has_any_permission_any_group(
            user_id,
            get_required_permissions_for_callback(data)
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para usar esta sección."
            )

            return


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
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
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

        groups = fetch_group_admin_manageable_groups(user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return


        context.user_data["adding_group_admin"] = True
        context.user_data.pop("group_admin_target_user_id", None)
        context.user_data.pop("group_admin_target_display", None)
        context.user_data.pop("group_admin_permissions", None)

        await send_clean_message(
            context,
            query.message.chat_id,
            "➕ Añadir admin\n\nEnvía el user_id o @username del usuario si ya existe en la base de datos."
        )

        return


    if data.startswith("add_group_admin_select_group_"):

        group_id = extract_commercial_request_id(
            data,
            "add_group_admin_select_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        target_user_id = context.user_data.get("group_admin_target_user_id")


        if not target_user_id:

            await query.message.reply_text(
                "❌ No hay usuario pendiente para añadir."
            )

            return


        context.user_data["group_admin_selected_group_id"] = group_id
        context.user_data["group_admin_permissions"] = {
            permission: False
            for _key, _label, permission in GROUP_ADMIN_PERMISSION_OPTIONS
        }

        await send_clean_message(
            context,
            query.message.chat_id,
            "Permisos del nuevo admin:\n\n"
            + format_group_admin_permission_list(
                context.user_data["group_admin_permissions"]
            ),
            reply_markup=build_group_admin_permissions_keyboard(
                group_id,
                target_user_id,
                context.user_data["group_admin_permissions"],
                "gga_t"
            )
        )

        return


    if data.startswith("gga_t_"):

        payload = data.replace("gga_t_", "", 1)

        try:

            group_id_text, target_user_id_text, permission_key = payload.split("_", 2)
            group_id = int(group_id_text)
            target_user_id = int(target_user_id_text)

        except Exception:

            await query.message.reply_text("❌ Permiso no válido.")

            return


        permission = GROUP_ADMIN_PERMISSION_BY_KEY.get(permission_key)


        if not permission:

            await query.message.reply_text("❌ Permiso no válido.")

            return


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        if int(context.user_data.get("group_admin_target_user_id") or 0) != target_user_id:

            await query.message.reply_text(
                "❌ El usuario pendiente no coincide."
            )

            return


        permissions = context.user_data.setdefault(
            "group_admin_permissions",
            {
                current_permission: False
                for _key, _label, current_permission in GROUP_ADMIN_PERMISSION_OPTIONS
            }
        )
        permissions[permission] = not permissions.get(permission, False)

        await send_clean_message(
            context,
            query.message.chat_id,
            "Permisos del nuevo admin:\n\n"
            + format_group_admin_permission_list(permissions),
            reply_markup=build_group_admin_permissions_keyboard(
                group_id,
                target_user_id,
                permissions,
                "gga_t"
            )
        )

        return


    if data.startswith("add_group_admin_save_"):

        group_id = extract_commercial_request_id(
            data,
            "add_group_admin_save_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        target_user_id = context.user_data.get("group_admin_target_user_id")
        permissions = context.user_data.get("group_admin_permissions") or {}


        if not target_user_id:

            await query.message.reply_text(
                "❌ No hay usuario pendiente para añadir."
            )

            return


        save_group_admin_permissions(
            group_id,
            target_user_id,
            permissions
        )

        context.user_data["adding_group_admin"] = False
        context.user_data.pop("group_admin_target_user_id", None)
        context.user_data.pop("group_admin_target_display", None)
        context.user_data.pop("group_admin_selected_group_id", None)
        context.user_data.pop("group_admin_permissions", None)

        try:

            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    "✅ Has sido añadido como admin de una comunidad.\n\n"
                    f"Grupo: {fetch_group_name(group_id)}"
                )
            )

        except Exception as e:

            print("Error avisando admin de grupo:", e)


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Admin guardado correctamente.",
            reply_markup=build_group_admin_panel_keyboard()
        )

        return


    if data == "group_admin_view":

        groups = fetch_group_admin_manageable_groups(user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
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

        groups = fetch_group_admin_manageable_groups(user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
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


    if data.startswith("edit_admin_permissions_user_"):

        payload = data.replace("edit_admin_permissions_user_", "", 1)

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


        admin_row = fetch_group_admin_permissions(group_id, target_user_id)


        if not admin_row or admin_row.get("role") == "GROUP_OWNER":

            await query.message.reply_text("❌ Admin no editable.")

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "✏️ Editar permisos\n\n"
            + format_group_admin_permission_list(admin_row["permissions"]),
            reply_markup=build_group_admin_edit_permissions_keyboard(
                group_id,
                target_user_id,
                admin_row["permissions"]
            )
        )

        return


    if data.startswith("gap_t_"):

        payload = data.replace("gap_t_", "", 1)

        try:

            group_id_text, target_user_id_text, permission_key = payload.split("_", 2)
            group_id = int(group_id_text)
            target_user_id = int(target_user_id_text)

        except Exception:

            await query.message.reply_text("❌ Permiso no válido.")

            return


        permission = GROUP_ADMIN_PERMISSION_BY_KEY.get(permission_key)


        if not permission:

            await query.message.reply_text("❌ Permiso no válido.")

            return


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        admin_row = fetch_group_admin_permissions(group_id, target_user_id)


        if not admin_row or admin_row.get("role") == "GROUP_OWNER":

            await query.message.reply_text("❌ Admin no editable.")

            return


        permissions = admin_row["permissions"]
        permissions[permission] = not permissions.get(permission, False)
        save_group_admin_permissions(
            group_id,
            target_user_id,
            permissions
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Permisos actualizados.\n\n"
            + format_group_admin_permission_list(permissions),
            reply_markup=build_group_admin_edit_permissions_keyboard(
                group_id,
                target_user_id,
                permissions
            )
        )

        return


    if data == "group_admin_remove":

        groups = fetch_group_admin_manageable_groups(user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
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


    if data == "admin_support_tickets":

        tickets = fetch_recent_support_tickets()

        await send_clean_message(
            context,
            query.message.chat_id,
            build_support_tickets_text(tickets),
            reply_markup=InlineKeyboardMarkup(
                build_support_tickets_keyboard(tickets)
            )
        )

        return


    if data.startswith("admin_support_ticket_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_ticket_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        await query.message.reply_text(
            build_support_ticket_detail_text(ticket),
            reply_markup=InlineKeyboardMarkup(
                build_support_ticket_keyboard(ticket_id)
            )
        )

        return


    if data.startswith("admin_support_reply_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_reply_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Escribe ahora la respuesta para el usuario."
        )

        return


    if data.startswith("admin_support_close_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_close_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        update_support_ticket_status(
            ticket_id,
            "closed"
        )

        try:

            await context.bot.send_message(
                chat_id=ticket.get("user_id"),
                text=f"✅ Tu ticket #{ticket_id} ha sido cerrado."
            )

        except Exception as e:

            print("Error avisando cierre soporte:", e)


        await query.message.reply_text(
            f"✅ Ticket #{ticket_id} cerrado.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🛟 Tickets abiertos",
                    callback_data="admin_support_tickets"
                )]
            ])
        )

        return


    if data == "admin_commercial_promo_codes":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos promocionales\n\nCrea códigos para que dueños de grupos publiquen su comunidad sin pasar por checkout durante el periodo elegido.",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return


    if data.startswith("admin_commercial_promo_create_"):

        slug = data.replace("admin_commercial_promo_create_", "", 1)
        duration = COMMERCIAL_PROMO_DURATIONS.get(slug)


        if not duration:

            await query.message.reply_text("❌ Duración no válida.")

            return


        duration_days, duration_label = duration
        row = create_commercial_promo_code(duration_days, user_id)


        if not row:

            await query.message.reply_text("❌ Error creando código promocional.")

            return


        _code_id, code, _duration_days = row

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Código promocional creado\n\n"
            f"Código: {code}\n"
            f"Duración: {duration_label}\n"
            "Uso: 1 vez\n\n"
            "El dueño debe usarlo desde 📦 Configurar comunidad > 🎟 Tengo un código promocional.",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return


    if data == "admin_commercial_promo_active":

        rows = fetch_active_commercial_promo_codes()

        await send_clean_message(
            context,
            query.message.chat_id,
            build_commercial_promo_active_text(rows),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "Desactivar código",
                    callback_data="admin_commercial_promo_deactivate_menu"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_promo_codes"
                )]
            ])
        )

        return


    if data == "admin_commercial_promo_deactivate_menu":

        rows = fetch_active_commercial_promo_codes()

        await send_clean_message(
            context,
            query.message.chat_id,
            "❌ Desactivar código\n\nElige el código promocional que quieres desactivar.",
            reply_markup=build_commercial_promo_deactivate_keyboard(rows)
        )

        return


    if data.startswith("admin_commercial_promo_deactivate_"):

        code_id = extract_commercial_request_id(
            data,
            "admin_commercial_promo_deactivate_"
        )
        code = deactivate_commercial_promo_code(code_id)


        if not code:

            await query.message.reply_text("❌ Código promocional no encontrado.")

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            f"✅ Código desactivado: {code}",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return


    if data == "admin_commercial_requests":

        requests = fetch_pending_commercial_requests()

        await query.message.reply_text(
            build_commercial_requests_text(requests),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_requests_keyboard(requests)
            )
        )

        return


    if data.startswith("admin_commercial_group_limit_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_group_limit_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_group_limit_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_group_limit_keyboard(request_id)
            )
        )

        return


    if data.startswith("admin_commercial_set_group_limit_"):

        request_id, max_groups_allowed = extract_commercial_group_limit_selection(
            data
        )


        if not request_id or not max_groups_allowed:

            await query.message.reply_text(
                "❌ Cupo de grupos no válido."
            )

            return


        request_row = update_commercial_request_group_limit(
            request_id,
            max_groups_allowed
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            f"✅ Cupo actualizado a {max_groups_allowed} grupo(s).",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔎 Volver a solicitud",
                    callback_data=f"admin_commercial_review_{request_id}"
                )],
                [InlineKeyboardButton(
                    "🔢 Cambiar cupo",
                    callback_data=f"admin_commercial_group_limit_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_review_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_review_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_request_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return


    if data.startswith("admin_commercial_approve_trial_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_approve_trial_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            "✅ Aprobar prueba de comunidad\n\n"
            "Elige dónde quieres colocar esta comunidad inicialmente:\n\n"
            "🏠 Inicio: aparecerá directamente en /start.\n"
            "🔎 Explorar: aparecerá dentro de Explorar comunidades privadas.\n"
            "🙈 Oculta/Borrador: no aparecerá públicamente todavía.",
            reply_markup=InlineKeyboardMarkup(
                build_admin_trial_visibility_keyboard(request_id)
            )
        )

        return


    if data.startswith("admin_trial_visibility_start_home_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_trial_visibility_start_home_"
        )

        request_row = update_commercial_request_trial_visibility(
            request_id,
            user_id,
            "start_home"
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "✅ Tu prueba de 1 día ha sido aprobada.\n\n"
            "Ahora termina la configuración de tu comunidad.\n\n"
            "Primero elige cómo será el acceso para tus usuarios:\n\n"
            "🆓 Comunidad gratuita:\n"
            "Tus usuarios podrán entrar sin pagar, pero el acceso seguirá protegido por el bot.\n\n"
            "💳 Comunidad de pago:\n"
            "Tus usuarios pagarán directamente a través de tus propios cobros/Stripe.",
            reply_markup=InlineKeyboardMarkup(
                build_user_trial_choice_keyboard(request_id)
            )
        )

        await query.message.reply_text(
            "✅ Prueba de 1 día aprobada.\n\n"
            f"Ubicación inicial: {format_public_visibility('start_home')}.\n"
            "El creador ya recibió el flujo para terminar la configuración.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
        )

        return


    if data.startswith("admin_trial_visibility_explore_only_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_trial_visibility_explore_only_"
        )

        request_row = update_commercial_request_trial_visibility(
            request_id,
            user_id,
            "explore_only"
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "✅ Tu prueba de 1 día ha sido aprobada.\n\n"
            "Ahora termina la configuración de tu comunidad.\n\n"
            "Primero elige cómo será el acceso para tus usuarios:\n\n"
            "🆓 Comunidad gratuita:\n"
            "Tus usuarios podrán entrar sin pagar, pero el acceso seguirá protegido por el bot.\n\n"
            "💳 Comunidad de pago:\n"
            "Tus usuarios pagarán directamente a través de tus propios cobros/Stripe.",
            reply_markup=InlineKeyboardMarkup(
                build_user_trial_choice_keyboard(request_id)
            )
        )

        await query.message.reply_text(
            "✅ Prueba de 1 día aprobada.\n\n"
            f"Ubicación inicial: {format_public_visibility('explore_only')}.\n"
            "El creador ya recibió el flujo para terminar la configuración.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
        )

        return


    if data.startswith("admin_trial_visibility_hidden_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_trial_visibility_hidden_"
        )

        request_row = update_commercial_request_trial_visibility(
            request_id,
            user_id,
            "hidden"
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "✅ Tu prueba de 1 día ha sido aprobada.\n\n"
            "Ahora termina la configuración de tu comunidad.\n\n"
            "Primero elige cómo será el acceso para tus usuarios:\n\n"
            "🆓 Comunidad gratuita:\n"
            "Tus usuarios podrán entrar sin pagar, pero el acceso seguirá protegido por el bot.\n\n"
            "💳 Comunidad de pago:\n"
            "Tus usuarios pagarán directamente a través de tus propios cobros/Stripe.",
            reply_markup=InlineKeyboardMarkup(
                build_user_trial_choice_keyboard(request_id)
            )
        )

        await query.message.reply_text(
            "✅ Prueba de 1 día aprobada.\n\n"
            f"Ubicación inicial: {format_public_visibility('hidden')}.\n"
            "El creador ya recibió el flujo para terminar la configuración.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_approve_custom_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_approve_custom_"
        )

        request_row = update_commercial_request_custom_approved(
            request_id,
            user_id
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "✅ Tu solicitud de bot personalizado ha sido aprobada. "
            "El siguiente paso será completar configuración y pago para activar el servicio."
        )

        await query.message.reply_text(
            "✅ Configuración aprobada.\n\n"
            "La solicitud queda en espera de configuración y pago.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_reject_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reject_"
        )

        request_row = update_commercial_request_rejected(
            request_id,
            user_id
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "❌ Tu solicitud no ha sido aprobada por ahora.\n\n"
            "Puedes volver a intentarlo más adelante o contactar con soporte si necesitas revisar la propuesta."
        )

        await query.message.reply_text(
            "❌ Solicitud comercial rechazada.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
        )

        return


    if data.startswith("commercial_setup_free_group_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        await query.message.reply_text(
            "🆓 Grupo gratuito\n\n"
            "Este modo permitirá que la comunidad siga pasando por los filtros del bot aunque no cobre acceso. "
            "La configuración completa del grupo se hará en la siguiente fase."
        )

        return


    if data.startswith("commercial_setup_paid_group_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        await query.message.reply_text(
            "💳 Grupo de pago\n\n"
            "Este modo necesita Stripe o un modo de cobro configurado antes de activar ventas. "
            "La configuración completa del cobro se hará en la siguiente fase."
        )

        return


    if data.startswith("commercial_setup_owner_stripe_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        await query.message.reply_text(
            "🏦 Stripe del dueño\n\n"
            "El dueño usará su propia cuenta de Stripe para cobrar. "
            "La conexión y validación de credenciales queda preparada para una fase posterior."
        )

        return


    if data.startswith(LEGACY_ADMIN_PLATFORM_STRIPE_CALLBACK_PREFIX):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        await query.message.reply_text(
            "Esta opción ya no está disponible.\n\n"
            "Si la comunidad será de pago, el creador debe configurar su propia cuenta o sistema de cobro."
        )

        return


    # =========================
    # MIS SUSCRIPCIONES ACTIVAS
    # =========================

    if data == "mis_subs":

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT DISTINCT g.telegram_group_id, g.name

                    FROM users u

                    JOIN groups g
                    ON u.group_id = g.id

                    WHERE u.user_id=%s
                    AND COALESCE(u.subscription_active, FALSE)=TRUE
                    AND (
                        u.expiration IS NULL
                        OR u.expiration > NOW()
                    )
                    AND g.is_active=TRUE
                    AND g.telegram_group_id != 0

                    ORDER BY g.name ASC

                """, (user_id,))

                rows = cur.fetchall()

        except Exception as e:

            print("Error cargando suscripciones:", e)

            await query.message.reply_text(
                "❌ Error cargando suscripciones."
            )

            return


        if not rows:

            await reply_with_recover_navigation(
                query,
                "⚠️ No tienes suscripciones activas."
            )

            return


        keyboard = []


        for group_id, group_name in rows:

            keyboard.append([

                InlineKeyboardButton(

                    f"📦 {group_name}",

                    callback_data=f"mysub_{group_id}"

                )

            ])


        keyboard.append([

            InlineKeyboardButton(

                "💬 Ayuda sobre este menú",

                callback_data=CALLBACK_SUBSCRIPTIONS_HELP

            )

        ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="back_groups"

            )

        ])


        await query.message.reply_text(

            "📦 Tus suscripciones activas:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # DETALLE DE SUSCRIPCIÓN
    # =========================

    if data.startswith("mysub_"):

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id

        telegram_group_id = int(
            data.split("_")[1]
        )


        try:

            with conn.cursor() as cur:

                # =========================
                # OBTENER NOMBRE GRUPO
                # =========================

                cur.execute("""

                    SELECT name

                    FROM groups

                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                group_row = cur.fetchone()


                if not group_row:

                    await query.message.reply_text(
                        "❌ Grupo no encontrado."
                    )

                    return


                group_name = group_row[0]


                # =========================
                # OBTENER group_id REAL
                # =========================

                cur.execute("""

                    SELECT id

                    FROM groups

                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                group_id_row = cur.fetchone()


                if not group_id_row:

                    await query.message.reply_text(
                        "❌ Grupo no encontrado."
                    )

                    return


                real_group_id = group_id_row[0]


                # =========================
                # OBTENER EXPIRATION
                # =========================

                cur.execute("""

                    SELECT expiration

                    FROM users

                    WHERE user_id=%s
                    AND group_id=%s
                    AND COALESCE(subscription_active, FALSE)=TRUE
                    AND (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    LIMIT 1

                """, (

                    user_id,
                    real_group_id

                ))

                user_row = cur.fetchone()


                if not user_row:

                    await reply_with_recover_navigation(
                        query,
                        "No tienes una suscripción activa para este grupo."
                    )

                    return


                expiration = user_row[0]


                # =========================
                # OBTENER LINK ACTUAL
                # =========================

                cur.execute("""

                    SELECT invite_link

                    FROM invite_links

                    WHERE user_id=%s
                    AND group_id=%s
                    AND is_active=TRUE

                    ORDER BY created_at DESC

                    LIMIT 1

                """, (

                    user_id,
                    telegram_group_id

                ))

                link_row = cur.fetchone()


        except Exception as e:

            print("Error cargando detalle suscripción:", e)

            await query.message.reply_text(
                "❌ Error cargando suscripción."
            )

            return


        # =========================
        # FORMATEAR TIEMPO
        # =========================

        tiempo_texto = format_tiempo_restante(
            expiration
        )


        # =========================
        # REVOCAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link

                FROM invite_links

                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                telegram_group_id

            ))

            old_links = cur.fetchall()


            for (old_link,) in old_links:

                try:

                    revoke_link(
                        telegram_group_id,
                        old_link
                    )

                    cur.execute("""

                        UPDATE invite_links

                        SET is_active=FALSE,
                            revoked_at=NOW()

                        WHERE invite_link=%s

                    """, (old_link,))

                except Exception as e:

                    print(
                        "Error revocando link:",
                        e
                    )


            cur.execute("""

                DELETE FROM invite_links

                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                telegram_group_id

            ))

            conn.commit()


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        max_expire = int(time.time()) + 180

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        # =========================
        # CREAR LINK NUEVO
        # =========================

        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=expire_seconds,
            member_limit=1
        )


        if not link:

            await query.message.reply_text(
                "❌ Error creando acceso."
            )

            return


        # =========================
        # GUARDAR LINK NUEVO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, invite_link)

                VALUES (%s, %s, %s)

            """, (

                user_id,
                telegram_group_id,
                link

            ))

            conn.commit()


        keyboard = [

            [

                InlineKeyboardButton(

                    "💬 Ayuda sobre este menú",

                    callback_data=CALLBACK_SUBSCRIPTIONS_HELP

                )

            ],

            [

                InlineKeyboardButton(

                    "⬅️ Volver",

                    callback_data="mis_subs"

                )

            ]

        ]


        mensaje = (

            f"📦 {group_name}\n\n"

            f"⏳ Tiempo restante:\n"
            f"{tiempo_texto}\n\n"

            "⚠️ Este link expirará en 3 minutos.\n\n"

            f"🔗 Tu nuevo acceso:\n"
            f"{link}"

        )


        await query.message.reply_text(

            mensaje,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if data.startswith("free_access_"):

        try:

            await query.message.delete()

        except Exception:

            pass


        try:

            group_id = int(data.replace("free_access_", "", 1))

        except Exception:

            await query.message.reply_text(
                "❌ Comunidad no válida."
            )

            return


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT name,
                           telegram_group_id
                    FROM groups
                    WHERE id=%s
                    AND is_active=TRUE
                    AND COALESCE(is_free_group, FALSE)=TRUE
                    LIMIT 1

                """, (group_id,))

                group_row = cur.fetchone()


                if not group_row:

                    await query.message.reply_text(
                        "❌ Comunidad gratuita no encontrada o no disponible."
                    )

                    return


                group_name, telegram_group_id = group_row

                increment_community_stat(group_id, "access_clicks")

                cur.execute("""

                    SELECT invite_link
                    FROM invite_links
                    WHERE user_id=%s
                    AND group_id IN (%s, %s)
                    AND is_active=TRUE

                """, (
                    user_id,
                    group_id,
                    telegram_group_id
                ))

                old_links = cur.fetchall()


            for (old_link,) in old_links:

                try:

                    revoke_telegram_invite_link(
                        TOKEN,
                        telegram_group_id,
                        old_link
                    )

                except Exception as e:

                    print("Error revocando link gratuito anterior:", e)


            link = create_telegram_invite_link(
                TOKEN,
                telegram_group_id,
                expire_seconds=180,
                member_limit=1
            )


            if not link:

                await query.message.reply_text(
                    "❌ Error creando acceso."
                )

                return


            username = query.from_user.username
            first_name = query.from_user.first_name


            with conn.cursor() as cur:

                cur.execute("""

                    DELETE FROM invite_links
                    WHERE user_id=%s
                    AND group_id IN (%s, %s)

                """, (
                    user_id,
                    group_id,
                    telegram_group_id
                ))

                cur.execute("""

                    INSERT INTO invite_links
                    (user_id, group_id, invite_link, is_active)
                    VALUES (%s, %s, %s, TRUE)

                """, (
                    user_id,
                    telegram_group_id,
                    link
                ))

                cur.execute("""

                    INSERT INTO users
                    (
                        user_id,
                        group_id,
                        username,
                        first_name,
                        expiration,
                        subscription_active,
                        last_invite_link
                    )
                    VALUES (%s, %s, %s, %s, NULL, TRUE, %s)
                    ON CONFLICT (user_id, group_id)
                    DO UPDATE SET
                        username=EXCLUDED.username,
                        first_name=EXCLUDED.first_name,
                        expiration=NULL,
                        subscription_active=TRUE,
                        last_invite_link=EXCLUDED.last_invite_link

                """, (
                    user_id,
                    group_id,
                    username,
                    first_name,
                    link
                ))

                conn.commit()

        except Exception as e:

            print("Error concediendo acceso gratuito:", e)

            await query.message.reply_text(
                "❌ Error creando acceso gratuito."
            )

            return


        await query.message.reply_text(
            "✅ Acceso gratuito concedido.\n\n"
            "Este enlace es personal y de un solo uso.\n"
            "No lo compartas.\n\n"
            f"{link}"
        )

        return


    # =========================
    # ENTRAR A GRUPO
    # =========================

    if data.startswith("group_"):

        try:
            await query.message.delete()
        except:
            pass


        group_id = int(data.split("_")[1])


        # =========================
        # GUARDAR GRUPO SELECCIONADO
        # =========================

        context.user_data["selected_group"] = group_id


        # =========================
        # OBTENER PLANES DEL GRUPO
        # =========================

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT COALESCE(is_free_group, FALSE)
                    FROM groups
                    WHERE id=%s
                    AND is_active=TRUE

                """, (group_id,))

                group_row = cur.fetchone()


                if not group_row:

                    await send_clean_message(
            context,
            query.message.chat_id,
                        "❌ Comunidad no encontrada o no disponible."
                    )

                    return


                is_free_group = group_row[0] is True

                increment_community_stat(group_id, "access_clicks")

                cur.execute("""

                    SELECT name,
                           price_id,
                           amount,
                           currency

                    FROM plans

                    WHERE group_id=%s
                    AND is_active=TRUE

                    ORDER BY id ASC

                """, (group_id,))

                plans = cur.fetchall()

        except Exception as e:

            print("Error cargando planes:", e)

            await send_clean_message(
            context,
            query.message.chat_id,
                "❌ Error cargando planes."
            )

            return


        if is_free_group:

            await send_clean_message(
            context,
            query.message.chat_id,
                "Esta comunidad es gratuita, pero el acceso está protegido por el bot.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🔓 Entrar gratis",
                        callback_data=f"free_access_{group_id}"
                    )],
                    [InlineKeyboardButton(
                        "💬 Ayuda sobre este menú",
                        callback_data=CALLBACK_GROUP_PLANS_HELP
                    )],
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data="back_groups"
                    )]
                ])
            )

            return


        if not plans:

            await send_clean_message(
            context,
            query.message.chat_id,
                "⚠️ Este grupo no tiene planes disponibles."
            )

            return


        keyboard = []


        for name, price_id, amount, currency in plans:

            if amount and currency:

                button_text = f"{name} — {amount} {currency}"

            else:

                button_text = name


            keyboard.append([

                InlineKeyboardButton(

                    button_text,

                    callback_data=price_id

                )

            ])


        keyboard.append([

            InlineKeyboardButton(

                "🎟️ Usar código",

                callback_data="codigo"

            )

        ])


        keyboard.append([

            InlineKeyboardButton(

                "💬 Ayuda sobre este menú",

                callback_data=CALLBACK_GROUP_PLANS_HELP

            )

        ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="back_groups"

            )

        ])


        await send_clean_message(
            context,
            query.message.chat_id,

            "Selecciona un plan:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # VOLVER A GRUPOS
    # =========================

    if data == "back_groups":

        try:
            await query.message.delete()
        except:
            pass

        await start(update, context)

        return
    

    # =========================
    # RECUPERAR ACCESO
    # =========================

    if data == "recover_access":

        user_id = query.from_user.id

        with conn.cursor() as cur:

            cur.execute("""

                SELECT expiration
                FROM users
                WHERE user_id=%s
                AND group_id=%s
                AND COALESCE(subscription_active, FALSE)=TRUE
                AND (
                    expiration IS NULL
                    OR expiration > NOW()
                )

                LIMIT 1

            """, (user_id, get_group_id()))

            row = cur.fetchone()

        if not row:

            await reply_with_recover_navigation(
                query,
                "No tienes una suscripción activa para este grupo."
            )

            return


        expiration = row[0]

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s
                ORDER BY created_at DESC
                LIMIT 1

            """, (

                user_id,
                get_group_id()

            ))

            link_row = cur.fetchone()


        # =========================
        # REVOCAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            old_links = cur.fetchall()


        for (old_link,) in old_links:

            try:

                revoke_telegram_invite_link(
                    TOKEN,
                    get_group_id(),
                    old_link
                )

            except Exception as e:

                print(
                    "Error revocando link:",
                    e
                )


        # =========================
        # BORRAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            conn.commit()


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        max_expire = int(time.time()) + 180

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        # =========================
        # CREAR LINK NUEVO TEMPORAL
        # =========================

        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            get_group_id(),
            expire_seconds=expire_seconds,
            member_limit=1
        )


        if not link:

            await query.message.reply_text(
                "❌ Error creando acceso."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, invite_link)

                VALUES (%s, %s, %s)

            """, (

                user_id,
                get_group_id(),
                link

            ))

            conn.commit()


        await query.message.reply_text(

            f"🔗 Tu acceso VIP:\n{link}"

        )

        return


    # =========================
    # MENÚ USUARIOS
    # =========================

    if data == "menu_users":

        try:
            await query.message.delete()
        except:
            pass

        permissions = get_admin_permissions(user_id)

        keyboard = []


        if has_any_permission(permissions, ["can_view_users", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("📋 Ver usuarios", callback_data="admin_users")])

            keyboard.append([InlineKeyboardButton("🔍 Buscar usuario", callback_data="admin_search_user")])


        if has_any_permission(permissions, ["can_kick_users", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("🚫 Expulsar usuario", callback_data="admin_kick_user")])


        if has_any_permission(permissions, ["can_ban_users", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("⛔ Banear usuario", callback_data="admin_ban_user")])


        if has_any_permission(permissions, ["can_unban_users", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("♻️ Desbanear usuario", callback_data="admin_unban_user")])


        if has_any_permission(permissions, ["can_reset_warnings", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("🔄 Reset warnings", callback_data="admin_reset_warnings")])


        if is_super_admin(user_id):

            keyboard.append([InlineKeyboardButton("🔀 Mover usuario grupo", callback_data="admin_move_user")])


        keyboard.append([InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_USERS_HELP)])

        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")])

        await send_clean_message(
            context,
            query.message.chat_id,

            "👥 GESTIÓN USUARIOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ADMIN — PERMITIR USUARIO
    # =========================

    if data.startswith("allow_user_"):

        parts = data.split("_")

        user_id = int(parts[2])
        group_id = int(parts[3])

        if not user_has_group_permission_any(
            query.from_user.id,
            group_id,
            ["can_kick_users", "can_manage_users"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO users

                    (user_id, group_id, expiration)

                    VALUES (%s, %s, NULL)

                    ON CONFLICT
                    (user_id, group_id)

                    DO UPDATE SET expiration=NULL

                """, (

                    user_id,
                    group_id

                ))

                conn.commit()


            await query.message.reply_text(

                "✅ Usuario permitido permanentemente."

            )


        except Exception as e:

            print(
                "Error permitiendo usuario:",
                e
            )

        return


    # =========================
    # ADMIN — EXPULSAR USUARIO
    # =========================

    if data.startswith("deny_user_"):

        parts = data.split("_")

        user_id = int(parts[2])
        group_id = int(parts[3])


        if not user_has_group_permission_any(
            query.from_user.id,
            group_id,
            ["can_kick_users", "can_manage_users"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT telegram_group_id

                    FROM groups

                    WHERE id=%s

                """, (group_id,))

                row = cur.fetchone()


            if row:

                telegram_group_id = row[0]


                kick_chat_member(
                    TOKEN,
                    telegram_group_id,
                    user_id
                )


            await query.message.reply_text(

                "❌ Usuario expulsado."

            )


        except Exception as e:

            print(
                "Error expulsando usuario:",
                e
            )

        return


    # =========================
    # MENÚ ACCESOS
    # =========================

    if data == "menu_codes":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📤 Crear código", callback_data="admin_create_code")],

            [InlineKeyboardButton("📋 Ver códigos", callback_data="admin_codes")],

            [InlineKeyboardButton("❌ Eliminar código", callback_data="admin_delete_code")],

        ]


        if is_super_admin(user_id):

            keyboard.append([InlineKeyboardButton("🔄 Revocar links", callback_data="admin_revoke_links")])

            keyboard.append([InlineKeyboardButton("📩 Reenviar links", callback_data="admin_resend_links")])


        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")])

        await send_clean_message(
            context,
            query.message.chat_id,

            "🎟️ GESTIÓN ACCESOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ GRUPOS
    # =========================

    if data == "menu_groups":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = []


        if is_super_admin(user_id):

            keyboard.append([
                InlineKeyboardButton("➕ Añadir grupo", callback_data="admin_add_group")
            ])


        keyboard.extend([

            [InlineKeyboardButton("✏️ Editar grupo", callback_data="admin_edit_group")],

            [InlineKeyboardButton("📋 Ver grupos", callback_data="admin_view_groups")],

            [InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_GROUPS_HELP)],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ])

        await send_clean_message(
            context,
            query.message.chat_id,

            "📦 GESTIÓN GRUPOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # CANCELAR CREACIÓN GRUPO
    # =========================

    if data == "cancel_create_group":

        context.user_data["creating_group"] = False
        context.user_data.pop("new_group_data", None)
        context.user_data.pop("group_step", None)

        keyboard = []


        if is_super_admin(user_id):

            keyboard.append([
                InlineKeyboardButton("➕ Añadir grupo", callback_data="admin_add_group")
            ])


        keyboard.extend([

            [InlineKeyboardButton("✏️ Editar grupo", callback_data="admin_edit_group")],

            [InlineKeyboardButton("📋 Ver grupos", callback_data="admin_view_groups")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ])

        await query.message.reply_text(

            "📦 GESTIÓN GRUPOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # VER GRUPOS
    # =========================

    if data == "admin_view_groups":

        print("DEBUG: admin_view_groups pulsado")

        try:
            await query.message.delete()
        except:
            pass

        try:

            print("DEBUG: consultando groups...")

            with conn.cursor() as cur:

                groups = fetch_admin_groups_for_permissions(
                    user_id,
                    ["can_manage_groups", "can_manage_plans"]
                )

            print("DEBUG groups:", groups)

        except Exception as e:

            print("ERROR cargando grupos:", e)

            await query.message.reply_text(
                f"❌ Error cargando grupos:\n{str(e)}"
            )

            return


        if not groups:

            await query.message.reply_text(
                "⚠️ No hay grupos registrados."
            )

            return


        texto = "📋 GRUPOS REGISTRADOS\n\n"


        try:

            for group_id, name, telegram_id in groups:

                texto += (

                    f"🆔 ID interno: {group_id}\n"
                    f"📦 Nombre: {name}\n"
                    f"📡 Telegram ID: {telegram_id}\n\n"

                )

        except Exception as e:

            print("ERROR construyendo texto:", e)

            await query.message.reply_text(
                f"❌ Error procesando grupos:\n{str(e)}"
            )

            return


        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="menu_groups"
            )]

        ]


        await query.message.reply_text(

            texto,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ PAGOS
    # =========================

    if data == "menu_payments":

        try:
            await query.message.delete()
        except:
            pass

        permissions = get_admin_permissions(user_id)

        keyboard = []


        if has_any_permission(permissions, ["can_view_payments", "can_manage_payments"]):

            keyboard.append([InlineKeyboardButton("📋 Ver pagos", callback_data="admin_view_payments")])

            keyboard.append([InlineKeyboardButton("🔍 Buscar pago", callback_data="admin_search_payment")])


        if has_any_permission(permissions, ["can_manage_payments"]):

            keyboard.append([InlineKeyboardButton("📩 Reenviar acceso", callback_data="admin_resend_access")])

            keyboard.append([InlineKeyboardButton("❌ Cancelar suscripción", callback_data="admin_cancel_subscription")])


        keyboard.append([InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_PAYMENTS_HELP)])

        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")])

        await send_clean_message(
            context,
            query.message.chat_id,

            "💳 GESTIÓN PAGOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ NEGOCIO
    # =========================

    if data == "menu_business":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats")],

            [InlineKeyboardButton("👥 Usuarios activos", callback_data="admin_active_users")],

            [InlineKeyboardButton("💰 Ingresos", callback_data="admin_income")]

        ]


        if is_super_admin(user_id):

            keyboard.append([
                InlineKeyboardButton("🔄 Revocar todos links", callback_data="admin_revoke_links")
            ])


        keyboard.append([
            InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")
        ])

        await send_clean_message(
            context,
            query.message.chat_id,

            "📊 GESTIÓN NEGOCIO",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ LOGS
    # =========================

    if data == "menu_logs":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📜 Ver logs", callback_data="admin_logs")],

            [InlineKeyboardButton("👥 Logs usuarios", callback_data="admin_logs_users")],

            [InlineKeyboardButton("💳 Logs pagos", callback_data="admin_logs_payments")],

            [InlineKeyboardButton("🔐 Logs seguridad", callback_data="admin_logs_security")],

            [InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_LOGS_HELP)],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,

            "📜 LOGS SISTEMA",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # VOLVER AL MENÚ PRINCIPAL
    # =========================

    if data == "admin_back_main":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = build_admin_panel_keyboard(user_id)


        if not keyboard:

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ No tienes permisos de gestión."
            )

            return

        await send_clean_message(

            context,

            query.message.chat_id,

            "🔐 PANEL ADMIN",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # AÑADIR GRUPO — INICIO WIZARD
    # =========================

    if data == "admin_add_group":

        try:
            await query.message.delete()
        except:
            pass

        context.user_data["creating_group"] = True
        context.user_data["group_step"] = 1
        context.user_data["new_group_data"] = {}

        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Cancelar creación",
                callback_data="cancel_create_group"
            )]

        ]

        await query.message.reply_text(

            "📦 CREAR NUEVO GRUPO\n\n"

            "Paso 1️⃣\n"
            "Introduce el nombre del grupo.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return
    

    # =========================
    # EDITAR GRUPO — LISTA
    # =========================

    if data == "admin_edit_group":

        try:
            await query.message.delete()
        except:
            pass


        try:

            with conn.cursor() as cur:

                rows = fetch_admin_groups_for_permissions(
                    user_id,
                    [
                        "can_manage_groups",
                        "can_manage_plans",
                        "can_edit_group_texts",
                        "can_edit_marketplace_preview"
                    ]
                )

                groups = [
                    (group_id, name)
                    for group_id, name, _telegram_group_id in rows
                ]

        except Exception as e:

            print("Error cargando grupos:", e)

            await query.message.reply_text(
                "❌ Error cargando grupos."
            )

            return


        if not groups:

            await query.message.reply_text(
                "⚠️ No hay grupos disponibles."
            )

            return


        keyboard = []


        for group_id, group_name in groups:

            keyboard.append([

                InlineKeyboardButton(

                    group_name,

                    callback_data=f"edit_group_{group_id}"

                )

            ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="menu_groups"

            )

        ])


        await query.message.reply_text(

            "Selecciona el grupo a editar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return
    

    # =========================
    # MENÚ INTERNO DEL GRUPO
    # =========================

    if data.startswith("edit_group_") and data.split("_")[2].isdigit():

        try:
            await query.message.delete()
        except:
            pass


        group_id = int(data.split("_")[2])


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_manage_groups", "can_manage_plans"]
            + ["can_edit_group_texts", "can_edit_marketplace_preview"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        # Guardar grupo seleccionado

        context.user_data["selected_group_admin"] = group_id


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            "🔧 CONFIGURACIÓN DEL GRUPO",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if data == "edit_group_back":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_manage_plans"]
            + ["can_edit_group_texts", "can_edit_marketplace_preview"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        await query.message.reply_text(
            "🔧 CONFIGURACIÓN DEL GRUPO",
            reply_markup=InlineKeyboardMarkup(
                build_group_settings_keyboard(user_id, group_id)
            )
        )

        return


    if data in (
        "edit_group_name",
        "edit_group_stripe",
        "edit_group_admins"
    ):

        required_permissions = ["can_manage_groups"]


        if data == "edit_group_name":

            required_permissions = ["can_edit_group_texts", "can_manage_groups"]


        if data == "edit_group_admins":

            required_permissions = ["can_manage_admins"]

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            required_permissions
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return


        await query.message.reply_text(
            "⚠️ Esta acción todavía no tiene un flujo seguro disponible."
        )

        return


    # =========================
    # EDITAR PREVIEW
    # =========================

    if data == "edit_group_preview":

        try:
            await query.message.delete()
        except:
            pass


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return


        # =========================
        # OBTENER PREVIEW ACTUAL
        # =========================

        current_preview = None

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT preview_file_id

                    FROM groups

                    WHERE id=%s

                """, (group_id,))

                row = cur.fetchone()

                if row:

                    current_preview = row[0]

        except Exception as e:

            print("Error obteniendo preview:", e)


        context.user_data["editing_preview"] = True


        # =========================
        # MOSTRAR PREVIEW ACTUAL
        # =========================

        if current_preview:

            try:

                await context.bot.send_photo(

                    chat_id=query.message.chat_id,

                    photo=current_preview,

                    caption="📸 Preview actual del grupo"

                )

            except:

                try:

                    await context.bot.send_video(

                        chat_id=query.message.chat_id,

                        video=current_preview,

                        caption="📸 Preview actual del grupo"

                    )

                except Exception as e:

                    print("Error mostrando preview:", e)


        keyboard = [

            [InlineKeyboardButton("⏭ Omitir", callback_data="skip_preview")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="edit_group_back")]

        ]


        await query.message.reply_text(

            "🎬 Envía una imagen o video para el nuevo preview.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return
    
    # =========================
    # OMITIR PREVIEW
    # =========================

    if data == "skip_preview":

        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            "⏭ Preview omitido.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # GUARDAR PREVIEW
    # =========================

    if data == "save_preview":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return

        file_id = context.user_data.get("new_preview_file")


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups

                    SET preview_file_id=%s

                    WHERE id=%s

                """, (

                    file_id,
                    group_id

                ))

                conn.commit()

        except Exception as e:

            print("Error guardando preview:", e)


        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            "✅ Preview actualizado correctamente.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # CANCELAR PREVIEW
    # =========================

    if data == "cancel_preview":

        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            "❌ Cambios descartados.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return



    # =========================
    # EDITAR PLANES — MENÚ
    # =========================

    if data == "edit_group_plans":

        try:
            await query.message.delete()
        except:
            pass


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return


        keyboard = [

            [InlineKeyboardButton(
                "📋 Ver planes",
                callback_data="view_group_plans"
            )],

            [InlineKeyboardButton(
                "➕ Añadir plan",
                callback_data="add_group_plan"
            )],

            [InlineKeyboardButton(
                "✏️ Editar plan",
                callback_data="edit_group_plan_select"
            )],

            [InlineKeyboardButton(
                "🗑 Eliminar plan",
                callback_data="delete_group_plan_select"
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=f"edit_group_{group_id}"
            )]

        ]


        await query.message.reply_text(

            "💳 GESTIÓN DE PLANES\n\n"
            "Selecciona una opción:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # AÑADIR PLAN — INICIO
    # =========================

    if data == "add_group_plan":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )

        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return


        context.user_data["adding_plan"] = True
        context.user_data["add_plan_step"] = 1
        context.user_data["new_plan"] = {}


        await query.message.reply_text(

            "➕ CREAR NUEVO PLAN\n\n"

            "Paso 1️⃣\n"
            "Introduce el nombre del plan.\n\n"

            "Ejemplo:\n"
            "VIP Mensual"

        )

        return


    # =========================
    # VER PLANES DEL GRUPO
    # =========================

    if data == "view_group_plans":

        try:
            await query.message.delete()
        except:
            pass


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id,
                           name,
                           amount,
                           currency,
                           duration_days

                    FROM plans

                    WHERE group_id=%s
                    AND is_active=TRUE

                    ORDER BY id ASC

                """, (group_id,))

                plans = cur.fetchall()

        except Exception as e:

            print("Error cargando planes:", e)

            await query.message.reply_text(
                "❌ Error cargando planes."
            )

            return


        if not plans:

            keyboard = [

                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="edit_group_plans"
                )]

            ]

            await query.message.reply_text(

                "⚠️ Este grupo no tiene planes creados.",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

            return


        texto = "📋 PLANES DEL GRUPO\n\n"


        for plan_id, name, amount, currency, duration in plans:

            if duration == 0:

                duracion_texto = "♾️ Permanente"

            else:

                duracion_texto = f"{duration} días"


            if amount and currency:

                precio_texto = f"{amount} {currency}"

            else:

                precio_texto = "No definido"


            texto += (

                f"🆔 {plan_id}\n"

                f"📦 {name}\n"

                f"💰 {precio_texto}\n"

                f"⏳ {duracion_texto}\n\n"

            )


        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )]

        ]


        await query.message.reply_text(

            texto,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # EDITAR PLAN — SELECCIÓN
    # =========================

    if data == "edit_group_plan_select":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE
                ORDER BY id ASC

            """, (group_id,))

            plans = cur.fetchall()


        if not plans:

            await query.message.reply_text(
                "⚠️ No hay planes disponibles."
            )

            return


        keyboard = []


        for plan_id, name in plans:

            keyboard.append([

                InlineKeyboardButton(
                    name,
                    callback_data=f"edit_plan_{plan_id}"
                )

            ])


        keyboard.append([

            InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )

        ])


        await query.message.reply_text(

            "✏️ Selecciona el plan a editar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ELIMINAR GRUPO — CONFIRMAR
    # =========================

    if data == "delete_group_confirm":

        group_id = context.user_data.get("selected_group_admin")

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return

        if not group_id:

            await query.message.reply_text(
                "❌ No se encontró el grupo."
            )

            return

        try:

            with conn.cursor() as cur:

                # =========================
                # BORRAR PLANES
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM plans
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando plans:", e)


                # =========================
                # BORRAR USUARIOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM users
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando users:", e)


                # =========================
                # BORRAR LINKS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM invite_links
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando invite_links:", e)


                # =========================
                # BORRAR WARNINGS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM link_warnings
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando link_warnings:", e)


                # =========================
                # BORRAR PAGOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM payments
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando payments:", e)


                # =========================
                # BORRAR SUBSCRIPTIONS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM subscriptions
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando subscriptions:", e)


                # =========================
                # BORRAR BANEADOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM banned_users
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando banned_users:", e)


                # =========================
                # BORRAR ADMINS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM admins
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando admins:", e)


                # =========================
                # BORRAR GRUPO
                # =========================

                cur.execute("""

                    DELETE FROM groups
                    WHERE id=%s

                """, (group_id,))


                conn.commit()


            await query.message.reply_text(
                "🗑 Grupo eliminado correctamente."
            )

        except Exception as e:

            print("Error eliminando grupo:", e)

            await query.message.reply_text(
                "❌ Error eliminando grupo."
            )

        return


    # =========================
    # ELIMINAR PLAN — SELECCIÓN
    # =========================

    if data == "delete_group_plan_select":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE
                ORDER BY id ASC

            """, (group_id,))

            plans = cur.fetchall()


        if not plans:

            await query.message.reply_text(
                "⚠️ No hay planes disponibles."
            )

            return


        keyboard = []


        for plan_id, name in plans:

            keyboard.append([

                InlineKeyboardButton(
                    name,
                    callback_data=f"delete_plan_{plan_id}"
                )

            ])


        keyboard.append([

            InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )

        ])


        await query.message.reply_text(

            "🗑 Selecciona el plan a eliminar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ELIMINAR PLAN — REAL
    # =========================

    if data.startswith("delete_plan_"):

        plan_id = int(data.split("_")[2])

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE plans

                    SET is_active=FALSE

                    WHERE id=%s
                    AND group_id=%s

                """, (
                    plan_id,
                    group_id
                ))


                # =========================
                # NUEVO — VERIFICAR SI QUEDAN PLANES
                # =========================

                cur.execute("""

                    SELECT COUNT(*)
                    FROM plans
                    WHERE group_id=%s
                    AND is_active=TRUE

                """, (group_id,))

                remaining_plans = cur.fetchone()[0]


                # =========================
                # NUEVO — SI NO QUEDAN PLANES
                # NO BORRAR GRUPO — SOLO INFORMAR
                # =========================

                if remaining_plans == 0:

                    print(
                        "Grupo sin planes restantes:",
                        group_id
                    )


                conn.commit()

        except Exception as e:

            print("Error eliminando plan:", e)

            await query.message.reply_text(
                "❌ Error eliminando plan."
            )

            return


        await query.message.reply_text(
            "🗑 Plan eliminado correctamente."
        )

        return


    # =========================
    # ADMIN USERS
    # =========================

    if data == "admin_users":

        print("DEBUG: admin_users pulsado")

        try:

            with conn.cursor() as cur:

                group_ids = get_admin_group_ids(
                    user_id,
                    ["can_view_users", "can_manage_users"]
                )


                if group_ids is None:

                    cur.execute("""

                        SELECT u.user_id,
                               u.username,
                               u.first_name,
                               u.expiration,
                               g.name
                        FROM users u
                        LEFT JOIN groups g
                        ON u.group_id = g.id
                        ORDER BY u.expiration DESC NULLS LAST

                    """)

                elif not group_ids:

                    users = []

                else:

                    cur.execute("""

                        SELECT u.user_id,
                               u.username,
                               u.first_name,
                               u.expiration,
                               g.name
                        FROM users u
                        LEFT JOIN groups g
                        ON u.group_id = g.id
                        WHERE u.group_id = ANY(%s)
                        ORDER BY u.expiration DESC NULLS LAST

                    """, (group_ids,))

                if group_ids is None or group_ids:

                    users = cur.fetchall()


            if not users:

                await query.message.reply_text(
                    "No hay usuarios activos."
                )

                return


            texto = f"👥 Usuarios activos: {len(users)}\n\n"


            for user_id, username, first_name, expiration, group_name in users:

                nombre = first_name if first_name else "Sin nombre"

                if username:
                    nombre += f" (@{username})"

                if expiration:

                    exp = expiration.strftime("%Y-%m-%d")

                else:

                    exp = "♾️ Permanente"


                texto += (

                    f"ID: {user_id}\n"
                    f"Grupo: {group_name or '-'}\n"
                    f"Nombre: {nombre}\n"
                    f"Expira: {exp}\n\n"

                )


            await query.message.reply_text(texto)

        except Exception as e:

            print("ERROR admin_users:", e)

            await query.message.reply_text(
                "❌ Error mostrando usuarios"
            )

        return


    # =========================
    # VER CÓDIGOS
    # =========================

    if data == "admin_codes":

        with conn.cursor() as cur:

            cur.execute("""

                SELECT code, duration, used
                FROM invite_codes
                ORDER BY code DESC
                LIMIT 20

            """)

            rows = cur.fetchall()


        if not rows:

            await query.message.reply_text(
                "No hay códigos creados."
            )

            return


        texto = "🎟️ Últimos códigos:\n\n"


        for code, duration, used in rows:

            if duration == 0:

                duracion_texto = "♾️ Permanente"

            elif duration < 1440:

                duracion_texto = f"{duration} min"

            else:

                duracion_texto = f"{duration//1440} días"


            estado = "❌ USADO" if used else "✅ ACTIVO"


            texto += (

                f"{code}\n"
                f"{duracion_texto} — {estado}\n\n"

            )


        await query.message.reply_text(texto)

        return


    # =========================
    # CREAR CÓDIGO
    # =========================

    if data == "admin_create_code":

        keyboard = [

            [InlineKeyboardButton("⏱️ 15 min", callback_data="gen_15")],
            [InlineKeyboardButton("📅 1 día", callback_data="gen_1440")],
            [InlineKeyboardButton("📅 7 días", callback_data="gen_10080")],
            [InlineKeyboardButton("📅 30 días", callback_data="gen_43200")],
            [InlineKeyboardButton("♾️ Permanente", callback_data="gen_perm")]

        ]


        await query.message.reply_text(

            "Selecciona duración:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ELIMINAR CÓDIGO
    # =========================

    if data == "admin_delete_code":

        context.user_data["delete_code"] = True

        await query.message.reply_text(
            "❌ Envia el código a eliminar"
        )

        return


    # =========================
    # BUSCAR USUARIO
    # =========================

    if data == "admin_search_user":

        context.user_data["search_user"] = True

        await query.message.reply_text(
            "🔍 Envia el ID del usuario"
        )

        return


    # =========================
    # EXPULSAR USUARIO
    # =========================

    if data == "admin_kick_user":

        context.user_data["kick_user"] = True

        await query.message.reply_text(
            "🚫 Envia el ID del usuario"
        )

        return


    # =========================
    # BAN PERMANENTE
    # =========================

    if data == "admin_ban_user":

        context.user_data["ban_user"] = True

        await query.message.reply_text(
            "⛔ Envia el ID del usuario a BANEAR"
        )

        return


    # =========================
    # DESBANEAR USUARIO
    # =========================

    if data == "admin_unban_user":

        context.user_data["unban_user"] = True

        await query.message.reply_text(
            "♻️ Envia el ID del usuario a DESBANEAR"
        )

        return


    if data in (
        "admin_reset_warnings",
        "admin_resend_access",
        "admin_cancel_subscription",
        "admin_move_user"
    ):

        await query.message.reply_text(
            "⚠️ Esta acción todavía no tiene un flujo seguro disponible."
        )

        return


    if data == "admin_view_payments":

        group_ids = get_admin_group_ids(
            user_id,
            ["can_view_payments", "can_manage_payments"]
        )


        try:

            with conn.cursor() as cur:

                if group_ids is None:

                    cur.execute("""

                        SELECT p.user_id,
                               g.name,
                               p.amount,
                               p.currency,
                               p.status,
                               p.payment_date
                        FROM payments p
                        LEFT JOIN groups g
                        ON p.group_id = g.id
                        ORDER BY p.payment_date DESC
                        LIMIT 20

                    """)

                elif not group_ids:

                    payments = []

                else:

                    cur.execute("""

                        SELECT p.user_id,
                               g.name,
                               p.amount,
                               p.currency,
                               p.status,
                               p.payment_date
                        FROM payments p
                        LEFT JOIN groups g
                        ON p.group_id = g.id
                        WHERE p.group_id = ANY(%s)
                        ORDER BY p.payment_date DESC
                        LIMIT 20

                    """, (group_ids,))


                if group_ids is None or group_ids:

                    payments = cur.fetchall()

        except Exception as e:

            print("Error cargando pagos admin:", e)

            await query.message.reply_text(
                "❌ Error cargando pagos."
            )

            return


        if not payments:

            await query.message.reply_text(
                "⚠️ No hay pagos registrados."
            )

            return


        text = "💳 Últimos pagos\n\n"


        for payment_user_id, group_name, amount, currency, status, payment_date in payments:

            text += (
                f"Usuario: {payment_user_id}\n"
                f"Grupo: {group_name or '-'}\n"
                f"Importe: {amount or '-'} {currency or ''}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {payment_date or '-'}\n\n"
            )


        await query.message.reply_text(text)

        return


    if data == "admin_search_payment":

        await query.message.reply_text(
            "🔍 La búsqueda directa de pagos todavía no está disponible. Usa el listado filtrado de pagos."
        )

        return


    # =========================
    # ESTADÍSTICAS
    # =========================

    if data == "admin_stats":

        try:

            with conn.cursor() as cur:

                group_ids = get_admin_group_ids(
                    user_id,
                    ["can_view_stats"]
                )


                if group_ids is None:

                    group_filter = ""
                    params = ()

                elif not group_ids:

                    usuarios_activos = 0
                    usuarios_expirados = 0
                    usuarios_permanentes = 0
                    total_pagos = 0

                    raise StopIteration

                else:

                    group_filter = "AND group_id = ANY(%s)"
                    params = (group_ids,)


                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE (
                        expiration IS NULL
                        OR expiration > NOW()
                    )
                    {group_filter}

                """.format(group_filter=group_filter), params)

                usuarios_activos = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE expiration IS NOT NULL
                    AND expiration < NOW()
                    {group_filter}

                """.format(group_filter=group_filter), params)

                usuarios_expirados = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE expiration IS NULL
                    {group_filter}

                """.format(group_filter=group_filter), params)

                usuarios_permanentes = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM payments
                    WHERE 1=1
                    {group_filter}

                """.format(group_filter=group_filter), params)

                total_pagos = cur.fetchone()[0]


        except StopIteration:

            texto = (

                "📊 ESTADÍSTICAS\n\n"

                "👥 Activos: 0\n"
                "⛔ Expirados: 0\n"
                "♾️ Permanentes: 0\n\n"

                "💳 Pagos totales: 0"
            )


            await query.message.reply_text(texto)

            return

        try:

            texto = (

                "📊 ESTADÍSTICAS\n\n"

                f"👥 Activos: {usuarios_activos}\n"
                f"⛔ Expirados: {usuarios_expirados}\n"
                f"♾️ Permanentes: {usuarios_permanentes}\n\n"

                f"💳 Pagos totales: {total_pagos}"

            )


            await query.message.reply_text(texto)

        except Exception as e:

            print("ERROR admin_stats:", e)

            await query.message.reply_text(
                "❌ Error mostrando estadísticas"
            )

        return


    if data == "admin_active_users":

        group_ids = get_admin_group_ids(user_id, ["can_view_stats"])


        with conn.cursor() as cur:

            if group_ids is None:

                cur.execute("""

                    SELECT g.name,
                           COUNT(*)
                    FROM users u
                    LEFT JOIN groups g
                    ON u.group_id = g.id
                    WHERE u.expiration IS NULL
                    OR u.expiration > NOW()
                    GROUP BY g.name
                    ORDER BY g.name ASC

                """)

            elif not group_ids:

                rows = []

            else:

                cur.execute("""

                    SELECT g.name,
                           COUNT(*)
                    FROM users u
                    LEFT JOIN groups g
                    ON u.group_id = g.id
                    WHERE (
                        u.expiration IS NULL
                        OR u.expiration > NOW()
                    )
                    AND u.group_id = ANY(%s)
                    GROUP BY g.name
                    ORDER BY g.name ASC

                """, (group_ids,))


            if group_ids is None or group_ids:

                rows = cur.fetchall()


        if not rows:

            await query.message.reply_text(
                "👥 No hay usuarios activos."
            )

            return


        text = "👥 Usuarios activos por grupo\n\n"


        for group_name, total in rows:

            text += f"{group_name or '-'}: {total}\n"


        await query.message.reply_text(text)

        return


    if data == "admin_income":

        group_ids = get_admin_group_ids(
            user_id,
            ["can_view_payments", "can_view_stats"]
        )


        with conn.cursor() as cur:

            if group_ids is None:

                cur.execute("""

                    SELECT g.name,
                           COALESCE(SUM(p.amount), 0),
                           MAX(p.currency)
                    FROM payments p
                    LEFT JOIN groups g
                    ON p.group_id = g.id
                    GROUP BY g.name
                    ORDER BY g.name ASC

                """)

            elif not group_ids:

                rows = []

            else:

                cur.execute("""

                    SELECT g.name,
                           COALESCE(SUM(p.amount), 0),
                           MAX(p.currency)
                    FROM payments p
                    LEFT JOIN groups g
                    ON p.group_id = g.id
                    WHERE p.group_id = ANY(%s)
                    GROUP BY g.name
                    ORDER BY g.name ASC

                """, (group_ids,))


            if group_ids is None or group_ids:

                rows = cur.fetchall()


        if not rows:

            await query.message.reply_text(
                "💰 No hay ingresos registrados."
            )

            return


        text = "💰 Ingresos por grupo\n\n"


        for group_name, amount, currency in rows:

            text += f"{group_name or '-'}: {amount or 0} {currency or ''}\n"


        await query.message.reply_text(text)

        return


    if data in (
        "admin_logs",
        "admin_logs_users",
        "admin_logs_payments",
        "admin_logs_security"
    ):

        group_ids = get_admin_group_ids(user_id, ["can_view_logs"])


        with conn.cursor() as cur:

            if group_ids is None:

                cur.execute("""

                    SELECT l.user_id,
                           g.name,
                           l.action,
                           l.details,
                           l.created_at
                    FROM logs l
                    LEFT JOIN groups g
                    ON l.group_id = g.id
                    ORDER BY l.created_at DESC
                    LIMIT 20

                """)

            elif not group_ids:

                rows = []

            else:

                cur.execute("""

                    SELECT l.user_id,
                           g.name,
                           l.action,
                           l.details,
                           l.created_at
                    FROM logs l
                    LEFT JOIN groups g
                    ON l.group_id = g.id
                    WHERE l.group_id = ANY(%s)
                    ORDER BY l.created_at DESC
                    LIMIT 20

                """, (group_ids,))


            if group_ids is None or group_ids:

                rows = cur.fetchall()


        if not rows:

            await query.message.reply_text(
                "📜 No hay logs registrados."
            )

            return


        text = "📜 Últimos logs\n\n"


        for log_user_id, group_name, action, details, created_at in rows:

            text += (
                f"Usuario: {log_user_id or '-'}\n"
                f"Grupo: {group_name or '-'}\n"
                f"Acción: {action or '-'}\n"
                f"Detalle: {details or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(text)

        return


    # =========================
    # REVOCAR TODOS LOS LINKS
    # =========================

    if data == "admin_revoke_links":

        if not is_super_admin(query.from_user.id):
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT invite_link
                    FROM invite_links

                """)

                links = cur.fetchall()


            total = 0

            for (link,) in links:

                try:

                    # =========================
                    # OBTENER GRUPO REAL DEL LINK
                    # =========================

                    with conn.cursor() as cur2:

                        cur2.execute("""

                            SELECT group_id
                            FROM invite_links
                            WHERE invite_link=%s

                        """, (link,))

                        group_row = cur2.fetchone()


                    if not group_row:
                        continue


                    telegram_group_id = group_row[0]


                    revoke_link(
                        telegram_group_id,
                        link
                    )

                    total += 1


                except Exception as e:

                    print(
                        "Error revocando link:",
                        e
                    )


            await query.message.reply_text(

                f"🔄 {total} links revocados correctamente."

            )

        except Exception as e:

            print("Error revocando todos:", e)

            await query.message.reply_text(
                "❌ Error revocando links"
            )

        return


    # =========================
    # REENVIAR LINKS NUEVOS
    # =========================

    if data == "admin_resend_links":

        if not is_super_admin(query.from_user.id):
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id
                    FROM users

                    WHERE
                    (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    AND user_id NOT IN (

                        SELECT user_id
                        FROM banned_users

                    )

                """)

                users = cur.fetchall()


            enviados = 0

            for (user_id,) in users:

                try:

                    # =========================
                    # OBTENER TELEGRAM_GROUP_ID REAL
                    # =========================

                    with conn.cursor() as cur2:

                        cur2.execute("""

                            SELECT telegram_group_id

                            FROM groups

                            WHERE id=(

                                SELECT group_id
                                FROM users
                                WHERE user_id=%s
                                LIMIT 1

                            )

                        """, (user_id,))

                        group_row = cur2.fetchone()


                    if not group_row:
                        continue


                    telegram_group_id = group_row[0]


                    link = create_telegram_invite_link(
                        TOKEN,
                        telegram_group_id,
                        expire_seconds=60,
                        member_limit=1
                    )


                    if not link:

                        print(
                            "Error creando link para usuario:",
                            user_id
                        )

                        continue


                    with conn.cursor() as cur:

                        cur.execute("""

                            DELETE FROM invite_links
                            WHERE user_id=%s

                        """, (user_id,))


                        cur.execute("""

                            INSERT INTO invite_links
                            (user_id, group_id, invite_link)

                            VALUES (%s, %s, %s)

                        """, (

                            user_id,
                            get_group_id(),
                            link

                        ))

                        conn.commit()


                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                        json={
                            "chat_id": user_id,
                            "text": f"🔗 Nuevo acceso VIP:\n{link}"
                        }

                    )

                    enviados += 1

                except Exception as e:

                    print("Error enviando link:", e)


            await query.message.reply_text(

                f"📩 {enviados} nuevos links enviados."

            )

        except Exception as e:

            print("Error reenviando:", e)

            await query.message.reply_text(
                "❌ Error reenviando links"
            )

        return





    # =========================
    # EDITAR PLAN — INICIO
    # =========================

    if data.startswith("edit_plan_"):

        plan_id = int(data.split("_")[2])
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM plans
                WHERE id=%s
                AND group_id=%s
                LIMIT 1

            """, (
                plan_id,
                group_id
            ))

            plan_row = cur.fetchone()


        if not plan_row:

            await query.message.reply_text(
                "⛔ No tienes permisos para editar este plan."
            )

            return

        context.user_data["editing_plan"] = True
        context.user_data["editing_plan_id"] = plan_id
        context.user_data["edit_plan_step"] = 1

        await query.message.reply_text(

            "✏️ EDITAR PLAN\n\n"

            "Paso 1️⃣\n"
            "Introduce el nuevo nombre del plan."

        )

        return


    # =========================
    # GENERAR CÓDIGOS
    # =========================

    if data.startswith("gen_"):

        await crear_codigo_callback(update, context)
        return


    # =========================
    # USAR CÓDIGO
    # =========================

    if data == "codigo":

        context.user_data["waiting_code"] = True

        await query.message.reply_text(
            "Introduce tu código:"
        )

        return


    if data.startswith("user_trial_setup_free_"):

        request_id = extract_commercial_request_id(data, "user_trial_setup_free_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        update_commercial_request_free_group(request_id)

        await notify_commercial_admin(
            context,
            (
                "🆓 Configuración comercial elegida\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}\n"
                "Modo: grupo gratuito"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🔎 Revisar solicitud #{request_id}",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await query.message.reply_text(
            "🆓 Perfecto. Tu comunidad será gratis para los usuarios, pero el acceso seguirá protegido por el bot.\n\n"
            "Ahora puedes continuar la configuración de tu comunidad.\n\n"
            "Para mantener publicada tu comunidad después de la prueba, tendrás que activar una suscripción del servicio.",
            reply_markup=InlineKeyboardMarkup(build_user_activation_keyboard(request_id))
        )

        return


    if data.startswith("user_trial_setup_paid_"):

        request_id = extract_commercial_request_id(data, "user_trial_setup_paid_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        update_commercial_request_paid_group(request_id)

        await notify_commercial_admin(
            context,
            (
                "💳 Configuración comercial elegida\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}\n"
                "Modo: grupo de pago"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🔎 Revisar solicitud #{request_id}",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await query.message.reply_text(
            "💳 Perfecto. Tu comunidad será de pago.\n\n"
            "Los pagos de tus usuarios deben ir a tu propia cuenta o sistema de cobro. "
            "Nosotros no recibiremos el dinero de tu comunidad.\n\n"
            "El siguiente paso será configurar tus planes y tus datos de cobro.",
            reply_markup=InlineKeyboardMarkup(build_user_trial_payment_keyboard(request_id))
        )

        return


    if data.startswith("user_trial_setup_owner_stripe_"):

        request_id = extract_commercial_request_id(data, "user_trial_setup_owner_stripe_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        update_commercial_request_stripe_mode(request_id, "owner_stripe")

        await notify_commercial_admin(
            context,
            (
                "🏦 Stripe propio seleccionado\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🔎 Revisar solicitud #{request_id}",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await query.message.reply_text(
            "Perfecto. Has elegido configurar tu propio Stripe o sistema de cobro.\n\n"
            "El siguiente paso será dejar preparados tus planes, textos y datos de acceso.\n\n"
            "Para mantener publicada tu comunidad después de la prueba, tendrás que activar una suscripción del servicio.",
            reply_markup=InlineKeyboardMarkup(build_user_activation_keyboard(request_id))
        )

        return


    if data.startswith(LEGACY_USER_PLATFORM_STRIPE_CALLBACK_PREFIX):

        request_id = extract_commercial_request_id(
            data,
            LEGACY_USER_PLATFORM_STRIPE_CALLBACK_PREFIX
        )
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        await query.message.reply_text(
            "Esta opción ya no está disponible.\n\n"
            "Si tu comunidad será de pago, los cobros deben ir a tu propia cuenta o sistema de cobro.",
            reply_markup=InlineKeyboardMarkup(build_user_trial_payment_keyboard(request_id))
        )

        return


    if (
        data.startswith("configure_community_")
        or data.startswith("user_commercial_activate_")
    ):

        if data.startswith("configure_community_"):

            request_id = extract_commercial_request_id(data, "configure_community_")

        else:

            request_id = extract_commercial_request_id(data, "user_commercial_activate_")


        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        _assigned, group_id = assign_owner_for_commercial_request(request_row)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_creator_setup_panel_text(group_id),
            reply_markup=InlineKeyboardMarkup(
                build_creator_setup_keyboard(
                    request_id,
                    request_row.get("payment_mode")
                )
            )
        )

        return


    if data.startswith("creator_promo_code_start_"):

        request_id = extract_commercial_request_id(data, "creator_promo_code_start_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "promo_code")

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Código promocional\n\n"
            "Envía ahora el código promocional que te dio el propietario principal."
        )

        return


    if data.startswith("expired_trial_activate_"):

        request_id = extract_commercial_request_id(data, "expired_trial_activate_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        plans = fetch_active_commercial_plans(PRODUCT_SHARED_BOT_SPACE)

        if not plans:

            await send_clean_message(
                context,
                query.message.chat_id,
                "💳 Activar suscripción\n\nTodavía no hay planes comerciales disponibles.",
                reply_markup=build_expired_trial_recovery_keyboard(request_id)
            )

            return


        keyboard = build_commercial_plan_keyboard(request_id, plans)
        keyboard.append([
            InlineKeyboardButton(
                "⬅️ Volver a opciones",
                callback_data=f"expired_trial_options_{request_id}"
            )
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Activar suscripción\n\nElige un plan comercial para volver a publicar tu comunidad.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data.startswith("expired_trial_options_"):

        request_id = extract_commercial_request_id(data, "expired_trial_options_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "Tu prueba ha finalizado. Para volver a publicar tu comunidad, activa una suscripción.",
            reply_markup=build_expired_trial_recovery_keyboard(request_id)
        )

        return


    if (
        data.startswith("expired_trial_delete_")
        and not data.startswith("expired_trial_delete_confirm_")
    ):

        request_id = extract_commercial_request_id(data, "expired_trial_delete_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🗑 Eliminar comunidad definitivamente\n\n"
            "Esta acción ocultará y desactivará la comunidad. No se borrará físicamente por seguridad.\n\n"
            "¿Confirmas que quieres eliminarla?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Sí, eliminar comunidad",
                    callback_data=f"expired_trial_delete_confirm_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Cancelar",
                    callback_data=f"expired_trial_options_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("expired_trial_delete_confirm_"):

        request_id = extract_commercial_request_id(
            data,
            "expired_trial_delete_confirm_"
        )
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        disable_commercial_request_community(request_row)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Comunidad desactivada.\n\nNo se ha borrado físicamente, pero queda oculta e inactiva.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🏠 Volver al inicio",
                    callback_data="public_back_start"
                )
            ]])
        )

        await notify_commercial_admin(
            context,
            (
                "🗑 Comunidad desactivada por el creador\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "👁 Ver estado",
                    callback_data=f"admin_commercial_review_{request_id}"
                )
            ]])
        )

        return


    if data.startswith("creator_setup_marketplace_"):

        request_id = extract_commercial_request_id(data, "creator_setup_marketplace_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_creator_marketplace_text(group_id),
            reply_markup=InlineKeyboardMarkup(
                build_creator_marketplace_keyboard(request_id)
            )
        )

        return


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
            "⚙️ Nivel de preview\n\n"
            "Elige cuánto quieres mostrar en el marketplace.",
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


        message = "✅ Nivel de preview actualizado."

        if preview_mode in ("dynamic", "hybrid"):

            message += (
                "\n\n"
                "El preview dinámico estará disponible en una fase posterior. "
                "Por ahora puedes configurar un preview manual."
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


    if data.startswith("creator_setup_group_"):

        request_id = extract_commercial_request_id(data, "creator_setup_group_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "group")

        await send_clean_message(
            context,
            query.message.chat_id,
            "📡 Grupo o canal\n\n"
            "Flujo recomendado:\n\n"
            "1️⃣ Añade este bot a tu grupo o canal.\n"
            "2️⃣ Dale permisos de administrador para gestionar enlaces, usuarios y mensajes de acceso.\n"
            "3️⃣ Espera 30 segundos mientras el bot valida autorización y cupo.\n"
            "4️⃣ Si todo está correcto, el bot te enviará el ID del grupo por privado. Suele empezar por -100.\n"
            "5️⃣ Vuelve a este panel y pega el ID aquí si hace falta para completar la configuración.\n\n"
            "Si ya recibiste el ID, envíalo ahora."
        )

        return


    if data.startswith("creator_setup_texts_"):

        request_id = extract_commercial_request_id(data, "creator_setup_texts_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "texts")

        await send_clean_message(
            context,
            query.message.chat_id,
            "📝 Textos y descripción\n\n"
            "Paso 1: escribe el nombre público de tu comunidad."
        )

        return


    if data.startswith("creator_setup_stripe_"):

        request_id = extract_commercial_request_id(data, "creator_setup_stripe_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if request_row.get("payment_mode") == "free":

            await send_clean_message(
            context,
            query.message.chat_id,
                "💳 Cobros / Stripe propio\n\n"
                "No aplica para comunidad gratuita. Puedes configurar grupo/canal y textos sin Stripe ni price_id.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        start_creator_setup_state(context, request_id, "stripe")

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Cobros / Stripe propio\n\n"
            "Envía tu STRIPE_SECRET_KEY.\n\n"
            "No se mostrará completa después de guardarla. "
            "El checkout real con Stripe del creador todavía no se conecta en esta fase."
        )

        return


    if data.startswith("creator_setup_plans_not_applicable_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_plans_not_applicable_"
        )
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "💰 Planes de acceso\n\n"
            "No aplica para comunidad gratuita.\n\n"
            "Puedes configurar grupo/canal y textos. No se pedirá Stripe ni price_id mientras el modo sea gratuito.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_plans_"):

        request_id = extract_commercial_request_id(data, "creator_setup_plans_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if request_row.get("payment_mode") == "free":

            await send_clean_message(
            context,
            query.message.chat_id,
                "💰 Planes de acceso\n\n"
                "No aplica para comunidad gratuita.\n\n"
                "No se pedirá Stripe ni price_id en este modo.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        _assigned, group_id = assign_owner_for_commercial_request(request_row)


        if not group_id:

            await send_clean_message(
            context,
            query.message.chat_id,
                "💰 Planes de acceso\n\n"
                "Pendiente de crear/publicar grupo.\n\n"
                "La tabla actual de planes necesita un groups.id real. "
                "No existe una estructura segura de planes pendientes por solicitud, así que primero hay que vincular el grupo/canal.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_setup_keyboard(
                        request_id,
                        request_row.get("payment_mode")
                    )
                )
            )

            return


        plan_count = get_creator_plan_count(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            "💰 Planes de acceso\n\n"
            f"Planes activos configurados: {plan_count}\n\n"
            "El price_id debe pertenecer al Stripe propio del creador. "
            "No se mezcla con el Stripe global del bot.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "➕ Crear plan",
                    callback_data=f"creator_setup_add_plan_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_add_plan_"):

        request_id = extract_commercial_request_id(data, "creator_setup_add_plan_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        _assigned, group_id = assign_owner_for_commercial_request(request_row)


        if not group_id:

            await send_clean_message(
            context,
            query.message.chat_id,
                "⚠️ No se puede crear un plan todavía.\n\n"
                "Falta un groups.id real asociado a tu solicitud.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_setup_keyboard(
                        request_id,
                        request_row.get("payment_mode")
                    )
                )
            )

            return


        start_creator_setup_state(context, request_id, "plan")

        await send_clean_message(
            context,
            query.message.chat_id,
            "💰 Crear plan de acceso\n\n"
            "Paso 1: escribe el nombre del plan."
        )

        return


    if data.startswith("creator_setup_access_type_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_type_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Tipo de acceso\n\n"
            "Elige cómo entrarán los usuarios a tu comunidad. Puedes cambiarlo mientras configuras la comunidad.",
            reply_markup=build_access_type_keyboard(request_id)
        )

        return


    if data.startswith("creator_setup_access_free_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_free_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        request_row = update_commercial_request_access_type(request_id, "free")

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Tipo de acceso actualizado.\n\n"
            "Tu comunidad queda como gratuita. No se pedirá Stripe ni price_id y se mostrará Entrar gratis.",
            reply_markup=InlineKeyboardMarkup(
                build_creator_setup_keyboard(
                    request_id,
                    request_row.get("payment_mode")
                )
            )
        )

        return


    if data.startswith("creator_setup_access_paid_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_paid_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        request_row = update_commercial_request_access_type(request_id, "paid")

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Tipo de acceso actualizado.\n\n"
            "Tu comunidad queda como de pago. Ahora configura tus cobros/Stripe propio y planes con price_id.",
            reply_markup=InlineKeyboardMarkup(
                build_creator_setup_keyboard(
                    request_id,
                    request_row.get("payment_mode")
                )
            )
        )

        return


    if data.startswith("creator_setup_visibility_"):

        request_id = extract_commercial_request_id(data, "creator_setup_visibility_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "👁 Visibilidad pública\n\n"
            f"Ubicación elegida: {format_public_visibility(request_row.get('requested_public_visibility'))}\n\n"
            "La visibilidad la define el propietario principal al aprobar la prueba.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_review_"):

        request_id = extract_commercial_request_id(data, "creator_setup_review_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_creator_setup_summary(request_row),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_tutorial_"):

        request_id = extract_commercial_request_id(data, "creator_setup_tutorial_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🧭 Tutorial paso a paso\n\n"
            "1. Crea o entra en tu cuenta de Stripe.\n"
            "2. En Stripe, busca las claves de desarrollador para copiar STRIPE_SECRET_KEY.\n"
            "3. Configura un webhook en Stripe y guarda el STRIPE_WEBHOOK_SECRET.\n"
            "4. Crea tus productos y precios en Stripe.\n"
            "5. Copia el price_id de cada precio y úsalo al crear planes en el bot.\n"
            "6. Prepara tu grupo/canal de Telegram y añade el bot.\n"
            "7. Asegúrate de que el bot tenga permisos de administrador para gestionar accesos.\n"
            "8. Vuelve a este panel y revisa la configuración.\n\n"
            "No inventes precios ni claves. Copia siempre los datos desde Stripe.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_ai_"):

        request_id = extract_commercial_request_id(data, "creator_setup_ai_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await activate_ai_help_context(
            update,
            context,
            help_context="creator_setup"
        )

        return


    if data.startswith("user_commercial_plan_"):

        request_id, plan_id = extract_commercial_plan_selection(data)
        request_row = fetch_commercial_request(request_id)
        plan = fetch_commercial_plan(plan_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        if not plan:

            await query.message.reply_text(
                "❌ Plan comercial no encontrado."
            )

            return

        update_commercial_request_plan(request_id, plan_id, "pending")

        if not plan.get("stripe_price_id"):

            await notify_commercial_admin(
                context,
                (
                    "📅 Plan comercial seleccionado\n\n"
                    f"Solicitud #{request_id}\n"
                    f"Usuario: {user_id}\n"
                    f"Plan: {plan.get('name') or '-'}\n"
                    "Falta stripe_price_id."
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"🔎 Revisar solicitud #{request_id}",
                        callback_data=f"admin_commercial_review_{request_id}"
                    )]
                ])
            )

            await query.message.reply_text(
                "Este plan todavía no tiene pago automático configurado. Un administrador debe añadir el price_id de Stripe."
            )

            return

        await notify_commercial_admin(
            context,
            (
                "📅 Plan comercial seleccionado\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan.get('name') or '-'}\n"
                "El pago automático comercial todavía está pendiente de conectar."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🔎 Revisar solicitud #{request_id}",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await query.message.reply_text(
            "El pago automático comercial todavía está pendiente de conectar."
        )

        return


    # =========================
    # PAGOS STRIPE
    # =========================

    user_id = query.from_user.id

    group_id = context.user_data.get("selected_group")

    try:

        response = requests.post(

            f"{SERVER_URL}/create-checkout-session",

            json={

                "telegram_id": user_id,
                "plan": data,
                "group_id": group_id

            }

        )

        payment_url = response.json()["url"]


        await query.message.reply_text(

            f"💳 Paga aquí:\n{payment_url}"

        )

    except Exception as e:

        print(e)

        await query.message.reply_text(
            "❌ Error creando pago"
        )
