import asyncio
import json
import os
import requests
import secrets
import string
import time

from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import ContextTypes

from admin_permission_map import (
    callback_requires_super_admin,
    get_required_permissions_for_callback,
    is_admin_callback
)
from admin_button_audit import (
    audit_admin_button_menus,
    format_admin_button_audit_detail,
    format_admin_button_audit_summary
)
from admin_menu_catalog import build_admin_menu_button_rows
from audit_log_service import (
    complete_active_beta_cycle,
    complete_expired_beta_cycles,
    create_beta_cycle,
    get_active_beta_cycle,
    get_beta_cycle_monitor_counts,
    get_latest_beta_cycle,
    list_beta_monitor_events,
    list_recent_events,
    log_event,
    mark_beta_monitor_events_resolved,
    record_beta_event,
    summarize_beta_monitor_events
)
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
from group_registration_handler import (
    cancel_creator_group_link_request,
    confirm_backup_destination_token,
    confirm_creator_group_link_request,
    leave_chat_safely,
    verificar_admin_despues
)
from invite_link_service import (
    create_telegram_invite_link,
    revoke_telegram_invite_link
)
from payment_service import (
    build_group_payment_methods_text,
    build_payment_methods_admin_text,
    is_stripe_payments_enabled
)
from rbac_helpers import (
    assign_group_owner_permissions,
    get_creator_group_quota_source,
    get_admin_group_ids,
    get_group_owner_user_id,
    has_any_permission_any_group,
    has_group_permission,
    has_permission,
    set_creator_group_quota,
    sync_commercial_creator_profile_from_request,
    is_super_admin
)
from start_handler import start, send_start_menu
from telegram_group_actions import kick_chat_member
from ui_menu_helpers import (
    delete_pending_preview_messages,
    make_button,
    remember_preview_message,
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


def build_unknown_callback_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]
    ])


def build_group_recovery_keyboard(group_id, retry_callback=None):

    keyboard = []

    if retry_callback:

        keyboard.append([InlineKeyboardButton(
            "🔁 Reintentar",
            callback_data=retry_callback
        )])


    if group_id:

        keyboard.append([InlineKeyboardButton(
            "⬅️ Volver a comunidad",
            callback_data=f"marketplace_group_{group_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(keyboard)


LEGACY_CALLBACK_PREFIXES = (
    "account_",
    "support_issue_",
    "support_contact_",
    "help_section_",
    "set_language_",
    "admin_my_groups",
    "admin_group_"
)


def is_legacy_callback(callback_data):

    return (
        isinstance(callback_data, str)
        and callback_data.startswith(LEGACY_CALLBACK_PREFIXES)
    )


def is_numeric_group_callback(callback_data):

    parts = (callback_data or "").split("_")

    return (
        len(parts) >= 2
        and parts[0] == "group"
        and parts[1].isdigit()
    )


def is_stripe_checkout_callback(callback_data):

    return (
        isinstance(callback_data, str)
        and callback_data.startswith("price_")
    )


LOCATION_REGION_TYPE_COUNTRY = "country"

LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY = (
    "spanish_autonomous_community"
)

COMUNIDAD_VALENCIANA_REGION = "comunidad_valenciana"

COMUNIDAD_VALENCIANA_LABEL = "Comunidad Valenciana"

HISPANIC_COUNTRIES = [
    ("ES", "España"),
    ("MX", "México"),
    ("AR", "Argentina"),
    ("CO", "Colombia"),
    ("CL", "Chile"),
    ("PE", "Perú"),
    ("VE", "Venezuela"),
    ("EC", "Ecuador"),
    ("BO", "Bolivia"),
    ("PY", "Paraguay"),
    ("UY", "Uruguay"),
    ("CR", "Costa Rica"),
    ("PA", "Panamá"),
    ("GT", "Guatemala"),
    ("HN", "Honduras"),
    ("SV", "El Salvador"),
    ("NI", "Nicaragua"),
    ("DO", "República Dominicana"),
    ("CU", "Cuba"),
    ("PR", "Puerto Rico"),
    ("GQ", "Guinea Ecuatorial")
]

HISPANIC_COUNTRY_LABELS = dict(HISPANIC_COUNTRIES)

COUNTRY_BOUNDING_BOXES = {
    "ES": (27.5, 43.9, -18.3, 4.4),
    "MX": (14.4, 32.8, -118.5, -86.5),
    "AR": (-55.2, -21.8, -73.6, -53.6),
    "CO": (-4.3, 13.5, -79.0, -66.8),
    "CL": (-56.0, -17.0, -76.0, -66.0),
    "PE": (-18.5, 0.5, -81.5, -68.5),
    "VE": (0.5, 12.7, -73.5, -59.5),
    "EC": (-5.2, 1.8, -81.3, -75.0),
    "BO": (-22.9, -9.5, -69.7, -57.4),
    "PY": (-27.7, -19.2, -62.7, -54.2),
    "UY": (-35.1, -30.0, -58.6, -53.0),
    "CR": (8.0, 11.3, -86.1, -82.5),
    "PA": (7.0, 9.8, -83.1, -77.1),
    "GT": (13.6, 17.9, -92.4, -88.0),
    "HN": (12.9, 16.6, -89.4, -83.0),
    "SV": (13.0, 14.5, -90.2, -87.7),
    "NI": (10.7, 15.1, -87.8, -82.6),
    "DO": (17.4, 19.9, -72.1, -68.2),
    "CU": (19.6, 23.4, -85.0, -74.1),
    "PR": (17.8, 18.6, -67.4, -65.2),
    "GQ": (-1.7, 3.8, 5.0, 11.5)
}

SPANISH_AUTONOMOUS_COMMUNITIES = [
    ("all_spain", "Toda España"),
    ("andalucia", "Andalucía"),
    ("aragon", "Aragón"),
    ("asturias", "Asturias"),
    ("islas_baleares", "Islas Baleares"),
    ("canarias", "Canarias"),
    ("cantabria", "Cantabria"),
    ("castilla_la_mancha", "Castilla-La Mancha"),
    ("castilla_y_leon", "Castilla y León"),
    ("cataluna", "Cataluña"),
    (COMUNIDAD_VALENCIANA_REGION, COMUNIDAD_VALENCIANA_LABEL),
    ("extremadura", "Extremadura"),
    ("galicia", "Galicia"),
    ("comunidad_de_madrid", "Comunidad de Madrid"),
    ("region_de_murcia", "Región de Murcia"),
    ("navarra", "Comunidad Foral de Navarra"),
    ("pais_vasco", "País Vasco"),
    ("la_rioja", "La Rioja"),
    ("ceuta", "Ceuta"),
    ("melilla", "Melilla")
]

SPANISH_AUTONOMOUS_COMMUNITY_LABELS = dict(SPANISH_AUTONOMOUS_COMMUNITIES)

SPANISH_AUTONOMOUS_COMMUNITY_BOXES = [
    ("ceuta", None, 35.86, 35.92, -5.38, -5.27),
    ("melilla", None, 35.24, 35.35, -3.05, -2.88),
    ("canarias", None, 27.5, 29.5, -18.3, -13.3),
    ("andalucia", None, 35.8, 38.8, -7.6, -1.6),
    ("region_de_murcia", None, 37.3, 38.9, -2.4, -0.6),
    (COMUNIDAD_VALENCIANA_REGION, "Alicante", 37.75, 38.95, -1.25, 0.25),
    (COMUNIDAD_VALENCIANA_REGION, "Valencia", 38.65, 40.05, -1.60, -0.05),
    (COMUNIDAD_VALENCIANA_REGION, "Castellón", 39.70, 40.85, -0.90, 0.60),
    ("extremadura", None, 37.9, 40.5, -7.6, -4.6),
    ("comunidad_de_madrid", None, 39.9, 41.2, -4.6, -3.0),
    ("castilla_la_mancha", None, 38.0, 41.4, -5.4, -1.0),
    ("islas_baleares", None, 38.6, 40.2, 1.1, 4.4),
    ("cataluna", None, 40.5, 42.9, 0.1, 3.4),
    ("aragon", None, 39.8, 42.9, -2.2, 0.9),
    ("castilla_y_leon", None, 40.0, 43.3, -7.1, -1.8),
    ("la_rioja", None, 41.8, 42.7, -3.2, -1.7),
    ("navarra", None, 41.9, 43.3, -2.6, -0.7),
    ("pais_vasco", None, 42.4, 43.6, -3.5, -1.7),
    ("cantabria", None, 42.75, 43.55, -4.9, -3.1),
    ("asturias", None, 42.9, 43.7, -7.2, -4.5),
    ("galicia", None, 41.8, 43.8, -9.4, -6.7)
]


def point_in_box(lat, lon, box):

    min_lat, max_lat, min_lon, max_lon = box

    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def is_location_in_comunidad_valenciana(lat, lon):

    resolved = resolve_location_region(lat, lon)

    return (
        resolved.get("spanish_autonomous_community") == COMUNIDAD_VALENCIANA_LABEL,
        resolved.get("province")
    )


def resolve_location_region(lat, lon):

    country_code = None


    for code, box in COUNTRY_BOUNDING_BOXES.items():

        if point_in_box(lat, lon, box):

            country_code = code

            break


    country_name = HISPANIC_COUNTRY_LABELS.get(country_code)
    autonomous_community = None
    province = None


    if country_code == "ES":

        for slug, detected_province, min_lat, max_lat, min_lon, max_lon in SPANISH_AUTONOMOUS_COMMUNITY_BOXES:

            if point_in_box(lat, lon, (min_lat, max_lat, min_lon, max_lon)):

                autonomous_community = SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(slug)
                province = detected_province

                break


    return {
        "country": country_code,
        "country_name": country_name,
        "spanish_autonomous_community": autonomous_community,
        "province": province
    }


def normalize_allowed_region_type(region_type, allowed_region):

    if region_type:

        return region_type


    if allowed_region in HISPANIC_COUNTRY_LABELS:

        return LOCATION_REGION_TYPE_COUNTRY


    if allowed_region in (
        COMUNIDAD_VALENCIANA_REGION,
        COMUNIDAD_VALENCIANA_LABEL
    ):

        return LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY


    if allowed_region in SPANISH_AUTONOMOUS_COMMUNITY_LABELS:

        return LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY


    return LOCATION_REGION_TYPE_COUNTRY


def normalize_allowed_region(region_type, allowed_region):

    if allowed_region == COMUNIDAD_VALENCIANA_LABEL:

        return COMUNIDAD_VALENCIANA_REGION


    if region_type == LOCATION_REGION_TYPE_COUNTRY:

        return allowed_region or "ES"


    if allowed_region in SPANISH_AUTONOMOUS_COMMUNITY_LABELS:

        return allowed_region


    return allowed_region or COMUNIDAD_VALENCIANA_REGION


def format_allowed_region(region_type, allowed_region):

    region_type = normalize_allowed_region_type(region_type, allowed_region)
    allowed_region = normalize_allowed_region(region_type, allowed_region)


    if region_type == LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY:

        return (
            f"{SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(allowed_region, allowed_region)}, España"
        )


    return HISPANIC_COUNTRY_LABELS.get(allowed_region, allowed_region or "España")


def location_matches_allowed_region(resolved_region, region_type, allowed_region):

    region_type = normalize_allowed_region_type(region_type, allowed_region)
    allowed_region = normalize_allowed_region(region_type, allowed_region)


    if region_type == LOCATION_REGION_TYPE_COUNTRY:

        return resolved_region.get("country") == allowed_region


    if region_type == LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY:

        return (
            resolved_region.get("country") == "ES"
            and resolved_region.get("spanish_autonomous_community")
            == SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(allowed_region)
        )


    return False


def build_location_denied_keyboard():

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "🛟 Contactar soporte",
            callback_data="public_support"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def build_location_gate_owner_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "✅ Activar restricción por ubicación",
            callback_data=f"creator_location_gate_enable_{request_id}"
        )],

        [InlineKeyboardButton(
            "🚫 Desactivar restricción",
            callback_data=f"creator_location_gate_disable_{request_id}"
        )],

        [InlineKeyboardButton(
            "🌎 Elegir país",
            callback_data=f"creator_location_country_menu_{request_id}"
        )],

        [InlineKeyboardButton(
            "🇪🇸 Elegir comunidad autónoma",
            callback_data=f"creator_location_spain_region_menu_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"configure_community_{request_id}"
        )]

    ])


def build_location_country_keyboard(request_id):

    keyboard = []


    for country_code, country_name in HISPANIC_COUNTRIES:

        callback_data = (
            f"creator_location_spain_region_menu_{request_id}"
            if country_code == "ES"
            else f"creator_location_country_set_{request_id}_{country_code}"
        )

        keyboard.append([InlineKeyboardButton(
            country_name,
            callback_data=callback_data
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_location_gate_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_spanish_autonomous_community_keyboard(request_id):

    keyboard = []


    for slug, label in SPANISH_AUTONOMOUS_COMMUNITIES:

        callback_data = (
            f"creator_location_country_set_{request_id}_ES"
            if slug == "all_spain"
            else f"creator_location_spain_region_set_{request_id}_{slug}"
        )

        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=callback_data
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_location_gate_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def get_group_location_gate(group_id):

    if not group_id:

        return False, None, None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT COALESCE(location_gate_enabled, FALSE),
                   allowed_region,
                   allowed_region_type
            FROM groups
            WHERE id=%s
            AND is_active=TRUE
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    if not row:

        return False, None, None


    region_type = normalize_allowed_region_type(row[2], row[1])
    allowed_region = normalize_allowed_region(region_type, row[1])

    return row[0] is True, allowed_region, region_type


def group_requires_location_gate(group_id):

    enabled, _allowed_region, _region_type = get_group_location_gate(group_id)

    return enabled


def get_group_location_gate_display(group_id):

    enabled, allowed_region, region_type = get_group_location_gate(group_id)

    return enabled, format_allowed_region(region_type, allowed_region)


def get_commercial_request_group_id(request_row):

    if not request_row:

        return None


    if request_row.get("approved_group_id"):

        return request_row.get("approved_group_id")


    approved_telegram_group_id = request_row.get("approved_telegram_group_id")


    if not approved_telegram_group_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id
            FROM groups
            WHERE telegram_group_id=%s
            LIMIT 1

        """, (approved_telegram_group_id,))

        row = cur.fetchone()


    return row[0] if row else None


def clear_location_gate_state(context):

    context.user_data.pop("location_gate_pending", None)
    context.user_data.pop("location_gate_group_id", None)
    context.user_data.pop("location_gate_action", None)
    context.user_data.pop("location_gate_price_id", None)


async def request_location_verification(
    context,
    chat_id,
    group_id,
    action,
    price_id=None
):

    context.user_data["location_gate_pending"] = True
    context.user_data["location_gate_group_id"] = group_id
    context.user_data["location_gate_action"] = action


    if price_id:

        context.user_data["location_gate_price_id"] = price_id

    else:

        context.user_data.pop("location_gate_price_id", None)


    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(
            "📍 Enviar ubicación",
            request_location=True
        )]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    _enabled, region_label = get_group_location_gate_display(group_id)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📍 Esta comunidad requiere verificar tu ubicación.\n\n"
            f"Región permitida: {region_label}\n\n"
            "Usaremos tu ubicación solo para comprobar la región y no guardaremos tus coordenadas exactas."
        ),
        reply_markup=keyboard
    )


def save_group_location_verification(group_id, user_id, resolved_region, status):

    resolved_region = resolved_region or {}

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO group_location_verifications
            (
                group_id,
                user_id,
                region_type,
                country,
                region,
                province,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)

        """, (
            group_id,
            user_id,
            (
                LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY
                if resolved_region.get("spanish_autonomous_community")
                else LOCATION_REGION_TYPE_COUNTRY
            ),
            resolved_region.get("country"),
            resolved_region.get("spanish_autonomous_community")
            or resolved_region.get("country_name"),
            resolved_region.get("province"),
            status
        ))

        conn.commit()


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


def user_has_group_owner_role(user_id):

    if is_super_admin(user_id):

        return True


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM admins
                WHERE user_id=%s
                AND role='GROUP_OWNER'
                AND is_active=TRUE
                LIMIT 1

            """, (user_id,))

            return cur.fetchone() is not None

    except Exception as e:

        print("Error verificando rol owner:", e)

        return False


def build_admin_home_text(user_id):

    if is_super_admin(user_id):

        return (
            "👑 Panel global del bot\n\n"
            "Gestiona la plataforma completa desde paneles separados: "
            "bot, propietarios y comunidades concretas."
        )


    if user_has_group_owner_role(user_id):

        return (
            "🏪 Mis comunidades\n\n"
            "Gestiona tus grupos concretos, códigos, planes, admins, logs y backups."
        )


    return (
        "👮 Panel admin de grupo\n\n"
        "Verás solo la comunidad actual, tus permisos concedidos y los accesos rápidos permitidos."
    )


def build_admin_global_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Monitor beta", callback_data="admin_beta_monitor")],
        [InlineKeyboardButton("😊 Satisfacción de clientes", callback_data="admin_customer_satisfaction")],
        [InlineKeyboardButton("🛟 Solicitudes de soporte", callback_data="admin_support_tickets")],
        [InlineKeyboardButton("🏪 Marketplace global", callback_data="admin_global_marketplace")],
        [InlineKeyboardButton("👥 Propietarios / solicitudes comerciales", callback_data="admin_owners_panel")],
        [InlineKeyboardButton("⚙️ Configuración global", callback_data="admin_global_config")],
        [InlineKeyboardButton("🛠 Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_global_panel")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_global_config_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏪 Marketplace / catálogo", callback_data="admin_global_marketplace")],
        [InlineKeyboardButton("💳 Planes comerciales del bot", callback_data="admin_global_commercial_plans")],
        [InlineKeyboardButton("💳 Métodos de pago", callback_data="admin_payment_providers")],
        [InlineKeyboardButton("🎟 Códigos comerciales globales", callback_data="admin_commercial_promo_codes")],
        [InlineKeyboardButton("😊 Encuestas y satisfacción", callback_data="admin_customer_satisfaction")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_global_config")],
        [InlineKeyboardButton("⬅️ Volver al panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_global_tools_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Smoke Test Beta", callback_data="admin_smoke_test")],
        [InlineKeyboardButton("🗓 Ciclo beta", callback_data="admin_beta_cycle")],
        [InlineKeyboardButton("🧪 Auditoría de botones", callback_data="admin_button_audit")],
        [InlineKeyboardButton("📜 Logs del sistema", callback_data="menu_logs")],
        [InlineKeyboardButton("📊 Monitor beta", callback_data="admin_beta_monitor")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_global_tools")],
        [InlineKeyboardButton("⬅️ Volver al panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_global_marketplace_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Ver marketplace como usuario", callback_data="start_explore_groups")],
        [InlineKeyboardButton("⚙️ Configuración global", callback_data="admin_global_config")],
        [InlineKeyboardButton("👥 Propietarios / comunidades", callback_data="admin_owners_panel")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_global_marketplace")],
        [InlineKeyboardButton("⬅️ Volver al panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_global_commercial_plans_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Propietarios / solicitudes", callback_data="admin_owners_panel")],
        [InlineKeyboardButton("💳 Suscripciones comerciales", callback_data="admin_commercial_subscriptions")],
        [InlineKeyboardButton("🎟 Códigos comerciales globales", callback_data="admin_commercial_promo_codes")],
        [InlineKeyboardButton("⬅️ Volver a configuración global", callback_data="admin_global_config")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_payment_providers_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Configuración global", callback_data="admin_global_config")],
        [InlineKeyboardButton("🛠 Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_button_audit_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver detalle", callback_data="admin_button_audit_detail")],
        [InlineKeyboardButton("🔁 Repetir auditoría", callback_data="admin_button_audit_refresh")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_button_audit")],
        [InlineKeyboardButton("⬅️ Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_button_audit_menu_specs():

    return [
        {
            "name": "Panel global",
            "callback_data": "admin_global_panel",
            "keyboard": build_admin_global_panel_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Configuración global",
            "callback_data": "admin_global_config",
            "keyboard": build_admin_global_config_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Herramientas internas",
            "callback_data": "admin_global_tools",
            "keyboard": build_admin_global_tools_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Propietarios / solicitudes comerciales",
            "callback_data": "admin_owners_panel",
            "keyboard": build_admin_owners_panel_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Satisfacción de clientes",
            "callback_data": "admin_customer_satisfaction",
            "keyboard": build_customer_satisfaction_panel_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Solicitudes de soporte",
            "callback_data": "admin_support_tickets",
            "keyboard": InlineKeyboardMarkup(build_support_tickets_keyboard([])),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Marketplace global",
            "callback_data": "admin_global_marketplace",
            "keyboard": build_admin_global_marketplace_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Planes comerciales del bot",
            "callback_data": "admin_global_commercial_plans",
            "keyboard": build_admin_global_commercial_plans_keyboard(),
            "requires_help": False,
            "requires_navigation": True
        }
    ]


def build_admin_button_audit_report():

    return audit_admin_button_menus(
        build_admin_button_audit_menu_specs(),
        get_required_permissions_for_callback
    )


def build_admin_owners_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕓 Solicitudes pendientes", callback_data="admin_commercial_requests")],
        [InlineKeyboardButton("✅ Propietarios activos", callback_data="admin_commercial_active_requests")],
        [InlineKeyboardButton("🧪 Trials activos", callback_data="admin_commercial_trials_active")],
        [InlineKeyboardButton("💳 Suscripciones comerciales", callback_data="admin_commercial_subscriptions")],
        [InlineKeyboardButton("📦 Cupos de grupos", callback_data="admin_commercial_group_limits")],
        [InlineKeyboardButton("📁 Archivados", callback_data="admin_commercial_archived_requests")],
        [InlineKeyboardButton("🔎 Buscar propietario", callback_data="admin_commercial_owner_tools")],
        [InlineKeyboardButton("📊 Resumen propietarios", callback_data="admin_commercial_owner_summary")],
        [InlineKeyboardButton("🔁 Reasignar owner/grupo", callback_data="admin_commercial_reassign_owner_group")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_owners_panel")],
        [InlineKeyboardButton("👑 Panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def build_customer_satisfaction_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Enviar encuesta global", callback_data="admin_satisfaction_send_global")],
        [InlineKeyboardButton("👥 Enviar solo a usuarios", callback_data="admin_satisfaction_send_users")],
        [InlineKeyboardButton("🧑‍💼 Enviar solo a propietarios", callback_data="admin_satisfaction_send_owners")],
        [InlineKeyboardButton("👮 Enviar solo a admins de grupo", callback_data="admin_satisfaction_send_group_admins")],
        [InlineKeyboardButton("📊 Ver resultados", callback_data="admin_satisfaction_results")],
        [InlineKeyboardButton("📝 Gestionar preguntas", callback_data="admin_satisfaction_questions")],
        [InlineKeyboardButton("➕ Añadir pregunta", callback_data="admin_satisfaction_add_rating")],
        [InlineKeyboardButton("➕ Añadir pregunta texto", callback_data="admin_satisfaction_add_text")],
        [InlineKeyboardButton("✏️ Editar preguntas", callback_data="admin_satisfaction_edit_menu")],
        [InlineKeyboardButton("🚫 Desactivar pregunta", callback_data="admin_satisfaction_deactivate_menu")],
        [InlineKeyboardButton("📋 Últimas respuestas", callback_data="admin_satisfaction_latest")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_customer_satisfaction")],
        [InlineKeyboardButton("⬅️ Volver al panel global", callback_data="admin_global_panel")]
    ])


ADMIN_CONTEXT_HELP_TEXTS = {
    "global_panel": (
        "❓ Ayuda — Panel global del bot\n\n"
        "Este panel es el índice principal de la plataforma.\n\n"
        "📊 Monitor beta: úsalo para ver alertas, pagos, accesos, códigos y errores recientes.\n"
        "😊 Satisfacción de clientes: envía encuestas y revisa qué opinan usuarios, owners y admins.\n"
        "🛟 Solicitudes de soporte: abre la bandeja de tickets de ayuda.\n"
        "🏪 Marketplace global: revisa cómo se ve el catálogo de comunidades y su configuración general.\n"
        "👥 Propietarios / solicitudes comerciales: gestiona creators, pruebas, cupos y solicitudes.\n"
        "⚙️ Configuración global: ajustes de plataforma, catálogo, planes comerciales y encuestas.\n"
        "🛠 Herramientas internas: diagnóstico, smoke test, ciclo beta y logs.\n\n"
        "Usa Volver para regresar al panel anterior o Inicio para volver al menú principal."
    ),
    "global_config": (
        "❓ Ayuda — Configuración global\n\n"
        "Este menú agrupa ajustes de plataforma y negocio.\n\n"
        "🏪 Marketplace / catálogo: abre la vista global del catálogo y sus opciones disponibles.\n"
        "💳 Planes comerciales del bot: revisa la zona de planes que pagan los owners para publicar.\n"
        "🎟 Códigos comerciales globales: crea códigos para owners, no para usuarios finales de grupos.\n"
        "💳 Métodos de pago: revisa Stripe activo y proveedores futuros sin activar accesos inseguros.\n"
        "😊 Encuestas y satisfacción: configura preguntas y envíos de encuestas.\n\n"
        "No incluye logs ni pruebas técnicas; eso vive en Herramientas internas."
    ),
    "global_tools": (
        "❓ Ayuda — Herramientas internas\n\n"
        "Este menú es para operar y diagnosticar el bot.\n\n"
        "🧪 Smoke Test Beta: ejecuta comprobaciones seguras antes de probar en real.\n"
        "🗓 Ciclo beta: controla semanas de beta, cierre y preparación de lanzamiento.\n"
        "🧪 Auditoría de botones: revisa menús, callbacks, permisos y navegación sin pulsar todo a mano.\n"
        "📜 Logs del sistema: revisa actividad técnica y eventos importantes.\n"
        "📊 Monitor beta: mira alertas y resumen de las últimas horas.\n\n"
        "Si buscas cambiar catálogo, planes o encuestas, usa Configuración global."
    ),
    "owners_panel": (
        "❓ Ayuda — Propietarios y solicitudes comerciales\n\n"
        "Aquí gestionas a quienes quieren publicar comunidades en el bot.\n\n"
        "🕓 Solicitudes pendientes: peticiones nuevas que aún necesitan decisión.\n"
        "✅ Propietarios activos: creators que ya están aprobados o configurando.\n"
        "🧪 Trials activos: pruebas de 1 día en curso.\n"
        "💳 Suscripciones comerciales: estado comercial de owners.\n"
        "📦 Cupos de grupos: cuántas comunidades puede tener cada owner.\n"
        "📁 Archivados: solicitudes cerradas sin borrar datos.\n"
        "🔎 Buscar propietario: revisa un owner concreto.\n"
        "📊 Resumen propietarios: vista general para decidir rápido.\n\n"
        "Úsalo cuando una persona quiera publicar, reactivar o resolver su comunidad."
    ),
    "customer_satisfaction": (
        "❓ Ayuda — Satisfacción de clientes\n\n"
        "Este módulo sirve para saber si el bot se entiende y dónde falla la experiencia.\n\n"
        "📤 Enviar encuesta global: manda una encuesta a todos los usuarios elegibles.\n"
        "👥 / 🧑‍💼 / 👮 Envíos segmentados: pregunta solo a usuarios, owners o admins.\n"
        "📊 Ver resultados: medias, tasa de respuesta y puntos débiles.\n"
        "📝 Gestionar preguntas: revisa las preguntas activas.\n"
        "➕ Añadir pregunta: crea preguntas de puntuación o texto.\n"
        "✏️ Editar / 🚫 Desactivar: ajusta preguntas sin perder respuestas anteriores.\n"
        "📋 Últimas respuestas: lee comentarios recientes.\n\n"
        "Úsalo durante beta para priorizar mejoras reales."
    ),
    "support_tickets": (
        "❓ Ayuda — Solicitudes de soporte\n\n"
        "Aquí ves tickets abiertos o respondidos recientemente.\n\n"
        "Cada botón de ticket abre la conversación con datos del usuario y últimos mensajes.\n"
        "✍️ Responder: envía una respuesta privada al usuario desde el bot.\n"
        "✅ Cerrar ticket: marca el caso como cerrado cuando ya está resuelto.\n\n"
        "Si una captura llega por soporte, se conserva dentro del ticket y no se mezcla con previews."
    ),
    "global_marketplace": (
        "❓ Ayuda — Marketplace global\n\n"
        "Esta pantalla te ayuda a revisar el catálogo público de comunidades.\n\n"
        "🔎 Ver marketplace como usuario: abre la experiencia pública para comprobar fichas, previews y accesos.\n"
        "⚙️ Configuración global: vuelve a ajustes de catálogo, planes comerciales y encuestas.\n"
        "👥 Propietarios / comunidades: revisa owners y solicitudes que alimentan el marketplace.\n\n"
        "Úsalo para comprobar si el escaparate del bot está claro antes de abrir la beta."
    ),
    "button_audit": (
        "❓ Ayuda — Auditoría de botones\n\n"
        "Esta herramienta revisa menús importantes sin pulsar botón por botón en Telegram.\n\n"
        "El resumen te dice si un menú está OK, si conviene revisarlo o si tiene un problema.\n"
        "📋 Ver detalle muestra cada botón con su callback y observación.\n"
        "🔁 Repetir auditoría vuelve a generar el informe con el estado actual.\n\n"
        "Es una revisión automática: ayuda a encontrar errores, pero las pruebas reales de pagos, soporte y grupos siguen siendo necesarias."
    )
}

ADMIN_CONTEXT_HELP_BACK_CALLBACKS = {
    "global_panel": "admin_global_panel",
    "global_config": "admin_global_config",
    "global_tools": "admin_global_tools",
    "owners_panel": "admin_owners_panel",
    "customer_satisfaction": "admin_customer_satisfaction",
    "support_tickets": "admin_support_tickets",
    "global_marketplace": "admin_global_marketplace",
    "button_audit": "admin_button_audit"
}


def build_admin_context_help_text(help_key):

    return ADMIN_CONTEXT_HELP_TEXTS.get(
        help_key,
        "❓ Ayuda\n\nEsta ayuda todavía no está configurada para este menú."
    )


def build_admin_context_help_keyboard(help_key):

    back_callback = ADMIN_CONTEXT_HELP_BACK_CALLBACKS.get(
        help_key,
        "admin_global_panel"
    )


    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver al menú", callback_data=back_callback)],
        [InlineKeyboardButton("👑 Panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def get_customer_satisfaction_audience_label(audience):

    labels = {
        "global": "todos los usuarios elegibles",
        "users": "usuarios",
        "owners": "propietarios",
        "group_admins": "admins de grupo"
    }

    return labels.get(audience, audience)


def fetch_customer_satisfaction_questions(active_only=True):

    with conn.cursor() as cur:

        if active_only:

            cur.execute("""

                SELECT id, question_key, question_text, category, answer_type, sort_order
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL
                AND COALESCE(is_active, TRUE)=TRUE
                ORDER BY sort_order ASC, id ASC

            """)

        else:

            cur.execute("""

                SELECT id, question_key, question_text, category, answer_type, sort_order, is_active
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL
                ORDER BY sort_order ASC, id ASC

            """)

        return cur.fetchall()


def fetch_customer_satisfaction_recipients(audience):

    queries = []

    if audience in ("global", "users"):
        queries.append("SELECT DISTINCT user_id FROM users WHERE user_id IS NOT NULL")

    if audience in ("global", "owners"):
        queries.append("""
            SELECT DISTINCT user_id
            FROM admins
            WHERE role='GROUP_OWNER'
            AND is_active=TRUE
            AND user_id IS NOT NULL
        """)

    if audience in ("global", "group_admins"):
        queries.append("""
            SELECT DISTINCT user_id
            FROM admins
            WHERE COALESCE(is_active, TRUE)=TRUE
            AND COALESCE(is_super_admin, FALSE)=FALSE
            AND COALESCE(role, '') <> 'GROUP_OWNER'
            AND user_id IS NOT NULL
        """)

    if audience == "global":
        queries.append("""
            SELECT DISTINCT user_id
            FROM commercial_requests
            WHERE user_id IS NOT NULL
        """)

    if not queries:
        return []

    with conn.cursor() as cur:
        cur.execute(" UNION ".join(queries))
        return sorted({row[0] for row in cur.fetchall() if row[0]})


def create_customer_satisfaction_survey(created_by, audience):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO customer_satisfaction_surveys
            (
                title,
                description,
                audience,
                status,
                created_by
            )
            VALUES (%s, %s, %s, 'draft', %s)
            RETURNING id

        """, (
            "Encuesta de satisfacción beta",
            "Encuesta rápida de satisfacción para mejorar el bot.",
            audience,
            created_by
        ))

        return cur.fetchone()[0]


def update_customer_satisfaction_sent_counts(survey_id, sent_count, failed_count):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE customer_satisfaction_surveys
            SET status='sent',
                sent_at=NOW(),
                sent_count=%s,
                failed_count=%s
            WHERE id=%s

        """, (sent_count, failed_count, survey_id))


def get_customer_satisfaction_role(user_id):

    if is_super_admin(user_id):
        return "super_admin"

    try:
        with conn.cursor() as cur:
            cur.execute("""

                SELECT role
                FROM admins
                WHERE user_id=%s
                AND is_active=TRUE
                ORDER BY CASE WHEN role='GROUP_OWNER' THEN 0 ELSE 1 END
                LIMIT 1

            """, (user_id,))
            row = cur.fetchone()
    except Exception:
        row = None

    if row and row[0] == "GROUP_OWNER":
        return "owner"

    if row:
        return "group_admin"

    return "user"


def get_or_create_customer_satisfaction_response(survey_id, user_id):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO customer_satisfaction_responses
            (
                survey_id,
                user_id,
                role,
                started_at
            )
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (survey_id, user_id)
            DO UPDATE SET started_at=COALESCE(customer_satisfaction_responses.started_at, NOW())
            RETURNING id

        """, (
            survey_id,
            user_id,
            get_customer_satisfaction_role(user_id)
        ))

        return cur.fetchone()[0]


def fetch_next_customer_satisfaction_question(response_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT q.id, q.question_text, q.answer_type, q.sort_order
            FROM customer_satisfaction_responses r
            JOIN customer_satisfaction_questions q
            ON q.survey_id IS NULL
            AND COALESCE(q.is_active, TRUE)=TRUE
            WHERE r.id=%s
            AND NOT EXISTS (
                SELECT 1
                FROM customer_satisfaction_answers a
                WHERE a.response_id=r.id
                AND a.question_id=q.id
            )
            ORDER BY q.sort_order ASC, q.id ASC
            LIMIT 1

        """, (response_id,))

        return cur.fetchone()


def save_customer_satisfaction_answer(response_id, question_id, rating=None, text_answer=None):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO customer_satisfaction_answers
            (
                response_id,
                question_id,
                rating,
                text_answer
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (response_id, question_id)
            DO UPDATE SET rating=EXCLUDED.rating,
                          text_answer=EXCLUDED.text_answer

        """, (response_id, question_id, rating, text_answer))


def customer_satisfaction_response_belongs_to_user(response_id, user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM customer_satisfaction_responses
            WHERE id=%s
            AND user_id=%s
            LIMIT 1

        """, (response_id, user_id))

        return cur.fetchone() is not None


def complete_customer_satisfaction_response(response_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE customer_satisfaction_responses
            SET completed_at=NOW()
            WHERE id=%s

        """, (response_id,))


def build_customer_satisfaction_results_text():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*), COALESCE(SUM(sent_count), 0), COALESCE(SUM(failed_count), 0)
            FROM customer_satisfaction_surveys

        """)
        survey_count, sent_count, failed_count = cur.fetchone()

        cur.execute("""

            SELECT COUNT(*)
            FROM customer_satisfaction_responses
            WHERE completed_at IS NOT NULL

        """)
        completed_count = cur.fetchone()[0]

        cur.execute("""

            SELECT AVG(rating)
            FROM customer_satisfaction_answers
            WHERE rating IS NOT NULL

        """)
        average_rating = cur.fetchone()[0]

        cur.execute("""

            SELECT q.category, AVG(a.rating)
            FROM customer_satisfaction_answers a
            JOIN customer_satisfaction_questions q
            ON q.id=a.question_id
            WHERE a.rating IS NOT NULL
            GROUP BY q.category
            ORDER BY AVG(a.rating) ASC
            LIMIT 8

        """)
        category_rows = cur.fetchall()

        cur.execute("""

            SELECT q.question_text, a.text_answer
            FROM customer_satisfaction_answers a
            JOIN customer_satisfaction_questions q
            ON q.id=a.question_id
            WHERE a.text_answer IS NOT NULL
            AND LENGTH(TRIM(a.text_answer)) > 0
            ORDER BY a.created_at DESC
            LIMIT 5

        """)
        text_rows = cur.fetchall()

    response_rate = 0
    if sent_count:
        response_rate = round((completed_count / sent_count) * 100, 1)

    category_text = "\n".join(
        f"- {category}: {round(float(avg), 2)}/5"
        for category, avg in category_rows
    ) or "Sin puntuaciones todavía."

    latest_text = "\n".join(
        f"- {question}: {answer[:120]}"
        for question, answer in text_rows
    ) or "Sin respuestas de texto todavía."

    average_text = f"{round(float(average_rating), 2)}/5" if average_rating else "Sin datos"

    return (
        "📊 Resultados de satisfacción\n\n"
        f"Encuestas creadas: {survey_count}\n"
        f"Total enviados: {sent_count}\n"
        f"Fallidos: {failed_count}\n"
        f"Total respuestas: {completed_count}\n"
        f"Tasa respuesta: {response_rate}%\n"
        f"Media general: {average_text}\n\n"
        "Media por categoría:\n"
        f"{category_text}\n\n"
        "Últimas respuestas texto:\n"
        f"{latest_text}"
    )


def build_customer_satisfaction_questions_text():

    rows = fetch_customer_satisfaction_questions(active_only=False)

    if not rows:
        return "📝 Gestionar preguntas\n\nNo hay preguntas configuradas."

    lines = ["📝 Gestionar preguntas"]

    for row in rows:
        question_id, _key, text, category, answer_type, sort_order, is_active = row
        status = "activa" if is_active else "desactivada"
        lines.append(
            f"\n{sort_order or question_id}. {text}\n"
            f"Tipo: {answer_type} · Categoría: {category} · Estado: {status}"
        )

    return "\n".join(lines)


def build_customer_satisfaction_deactivate_keyboard():

    rows = fetch_customer_satisfaction_questions(active_only=True)
    keyboard = []

    for question_id, _key, text, _category, _answer_type, _sort_order in rows[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"🚫 {text[:35]}",
                callback_data=f"admin_satisfaction_deactivate_{question_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_customer_satisfaction")])

    return InlineKeyboardMarkup(keyboard)


def build_customer_satisfaction_edit_keyboard():

    rows = fetch_customer_satisfaction_questions(active_only=False)
    keyboard = []

    for question_id, _key, text, _category, _answer_type, _sort_order, _is_active in rows[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"✏️ {text[:35]}",
                callback_data=f"admin_satisfaction_edit_{question_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_customer_satisfaction")])

    return InlineKeyboardMarkup(keyboard)


async def send_customer_satisfaction_question(context, chat_id, response_id):

    next_question = fetch_next_customer_satisfaction_question(response_id)

    if not next_question:
        complete_customer_satisfaction_response(response_id)
        context.user_data.pop("customer_satisfaction_response_id", None)
        context.user_data.pop("customer_satisfaction_text_question_id", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Gracias por tu opinión."
        )
        record_beta_event(
            "survey_completed",
            severity="info",
            user_id=chat_id,
            message="Encuesta de satisfacción completada."
        )
        return

    question_id, question_text, answer_type, sort_order = next_question

    if answer_type == "rating_1_5":
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Pregunta {sort_order}\n\n{question_text}\n\nResponde del 1 al 5.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("1️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_1"),
                InlineKeyboardButton("2️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_2"),
                InlineKeyboardButton("3️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_3"),
                InlineKeyboardButton("4️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_4"),
                InlineKeyboardButton("5️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_5")
            ]])
        )
        return

    context.user_data["customer_satisfaction_response_id"] = response_id
    context.user_data["customer_satisfaction_text_question_id"] = question_id

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Pregunta {sort_order}\n\n{question_text}\n\nResponde con texto."
    )


async def receive_customer_satisfaction_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    edit_question_id = context.user_data.get("customer_satisfaction_admin_edit_question_id")

    if edit_question_id:

        if not is_super_admin(update.effective_user.id):
            context.user_data.pop("customer_satisfaction_admin_edit_question_id", None)
            await update.message.reply_text("⛔ No tienes permisos para editar preguntas.")
            return

        question_text = (update.message.text or "").strip()

        if len(question_text) < 5:
            await update.message.reply_text(
                "⚠️ La pregunta es demasiado corta.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        with conn.cursor() as cur:
            cur.execute("""

                UPDATE customer_satisfaction_questions
                SET question_text=%s
                WHERE id=%s

            """, (question_text, edit_question_id))

        context.user_data.pop("customer_satisfaction_admin_edit_question_id", None)

        await update.message.reply_text(
            "✅ Pregunta actualizada.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    add_question_type = context.user_data.get("customer_satisfaction_admin_add_question")

    if add_question_type:

        if not is_super_admin(update.effective_user.id):
            context.user_data.pop("customer_satisfaction_admin_add_question", None)
            await update.message.reply_text("⛔ No tienes permisos para añadir preguntas.")
            return

        question_text = (update.message.text or "").strip()

        if len(question_text) < 5:
            await update.message.reply_text(
                "⚠️ La pregunta es demasiado corta.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        with conn.cursor() as cur:
            cur.execute("""

                SELECT COALESCE(MAX(sort_order), 0) + 1
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL

            """)
            sort_order = cur.fetchone()[0] or 1

            cur.execute("""

                INSERT INTO customer_satisfaction_questions
                (
                    survey_id,
                    question_key,
                    question_text,
                    category,
                    answer_type,
                    is_active,
                    sort_order
                )
                VALUES (NULL, %s, %s, 'custom', %s, TRUE, %s)

            """, (
                f"custom_{int(time.time())}",
                question_text,
                add_question_type,
                sort_order
            ))

        context.user_data.pop("customer_satisfaction_admin_add_question", None)

        await update.message.reply_text(
            "✅ Pregunta añadida.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    response_id = context.user_data.get("customer_satisfaction_response_id")
    question_id = context.user_data.get("customer_satisfaction_text_question_id")

    if not response_id or not question_id:
        await update.message.reply_text("No estaba esperando una respuesta de encuesta.")
        return

    if not customer_satisfaction_response_belongs_to_user(
        response_id,
        update.effective_user.id
    ):

        context.user_data.pop("customer_satisfaction_response_id", None)
        context.user_data.pop("customer_satisfaction_text_question_id", None)
        await update.message.reply_text("⛔ No puedes responder esta encuesta.")
        return

    save_customer_satisfaction_answer(
        response_id,
        question_id,
        text_answer=(update.message.text or "").strip()[:2000]
    )

    context.user_data.pop("customer_satisfaction_text_question_id", None)
    await send_customer_satisfaction_question(
        context,
        update.effective_chat.id,
        response_id
    )


def build_admin_panel_keyboard(user_id):

    if is_super_admin(user_id):

        return [
            [InlineKeyboardButton("👑 Panel global del bot", callback_data="admin_global_panel")],
            [InlineKeyboardButton("🧑‍💼 Panel de propietarios", callback_data="admin_owners_panel")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ]


    if user_has_group_owner_role(user_id):

        return [
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ]


    if has_any_admin_permission(user_id):

        return [
            [InlineKeyboardButton("👮 Panel admin de grupo", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ]


    return []


def build_beta_monitor_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Últimas 24h", callback_data="admin_beta_monitor_24h")],
        [InlineKeyboardButton("Críticos", callback_data="admin_beta_monitor_critical")],
        [InlineKeyboardButton("Warnings", callback_data="admin_beta_monitor_warning")],
        [InlineKeyboardButton("Pagos/accesos", callback_data="admin_beta_monitor_payments")],
        [InlineKeyboardButton("Códigos", callback_data="admin_beta_monitor_codes")],
        [InlineKeyboardButton("Backups", callback_data="admin_beta_monitor_backups")],
        [InlineKeyboardButton("🗓 Ciclo beta", callback_data="admin_beta_cycle")],
        [InlineKeyboardButton("▶️ Iniciar beta 1 semana", callback_data="admin_beta_cycle_start_beta_1")],
        [InlineKeyboardButton("🔁 Iniciar beta 2.0", callback_data="admin_beta_cycle_start_beta_2")],
        [InlineKeyboardButton("✅ Finalizar beta", callback_data="admin_beta_cycle_finish")],
        [InlineKeyboardButton("📋 Ver estado beta", callback_data="admin_beta_cycle_status")],
        [InlineKeyboardButton("🚀 Preparar lanzamiento final", callback_data="admin_beta_cycle_final_review")],
        [InlineKeyboardButton("Marcar resueltos", callback_data="admin_beta_monitor_resolve_all")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def format_beta_monitor_events_text(title, rows):

    if not rows:

        return f"{title}\n\nSin eventos registrados."


    text = f"{title}\n\n"


    for (
        event_id,
        created_at,
        event_type,
        severity,
        event_user_id,
        event_group_id,
        event_telegram_group_id,
        message,
        resolved
    ) in rows[:30]:

        status = "resuelto" if resolved else "pendiente"

        text += (
            f"#{event_id} · {event_type or '-'} · {severity or '-'} · {status}\n"
            f"Usuario: {event_user_id or '-'}\n"
            f"Grupo: {event_group_id or '-'} / {event_telegram_group_id or '-'}\n"
            f"Detalle: {message or '-'}\n"
            f"Fecha: {created_at or '-'}\n\n"
        )


    return text[:3900]


def format_beta_cycle_row(row):

    if not row:

        return "Sin ciclo beta registrado."


    (
        cycle_id,
        name,
        status,
        phase,
        starts_at,
        ends_at,
        created_by,
        completed_at,
        notes
    ) = row

    return (
        f"#{cycle_id} · {name or '-'}\n"
        f"Estado: {status or '-'}\n"
        f"Fase: {phase or '-'}\n"
        f"Inicio: {starts_at or '-'}\n"
        f"Fin previsto: {ends_at or '-'}\n"
        f"Creado por: {created_by or '-'}\n"
        f"Completado: {completed_at or '-'}\n"
        f"Notas: {notes or '-'}"
    )


def format_beta_cycle_status_text():

    active_cycle = get_active_beta_cycle()
    latest_cycle = active_cycle or get_latest_beta_cycle()
    counts = get_beta_cycle_monitor_counts(hours=24)

    lines = [
        "🗓 Ciclo beta",
        "",
        format_beta_cycle_row(latest_cycle),
        "",
        "📊 Estado últimas 24h",
        f"Críticos abiertos: {counts.get('critical_open', 0)}",
        f"Warnings abiertos: {counts.get('warning_open', 0)}",
        f"Pagos: {counts.get('payments', 0)}",
        f"Accesos permitidos: {counts.get('access_allowed', 0)}",
        f"Códigos canjeados: {counts.get('codes', 0)}",
        f"Backups fallidos: {counts.get('backup_failed', 0)}",
        f"Tickets soporte: {counts.get('support_tickets', 0)}"
    ]

    return "\n".join(lines)


def format_final_launch_checklist():

    return (
        "🚀 Preparar lanzamiento final\n\n"
        "Antes de abrir comercialmente, revisa:\n\n"
        "☐ Bugs P0 cerrados\n"
        "☐ Bugs P1 cerrados o aceptados\n"
        "☐ Smoke test OK\n"
        "☐ Railway estable\n"
        "☐ Stripe probado\n"
        "☐ Backups probados\n"
        "☐ Soporte probado\n"
        "☐ Logs limpios\n\n"
        "Este checklist no cambia pagos, grupos ni datos de usuarios."
    )


def build_beta_smoke_test_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Ejecutar checks automáticos", callback_data="admin_smoke_run")],
        [InlineKeyboardButton("📋 Checklist manual", callback_data="admin_smoke_manual")],
        [InlineKeyboardButton("📊 Último resultado", callback_data="admin_smoke_last")],
        [InlineKeyboardButton("🧹 Limpiar resultados", callback_data="admin_smoke_clear")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def add_smoke_check(report, name, status, detail):

    report.append({
        "name": name,
        "status": status,
        "detail": str(detail or "")
    })


def smoke_status_icon(status):

    if status == "ok":

        return "✅"

    if status == "fail":

        return "❌"

    if status == "manual":

        return "🧪"

    return "⚠️"


def read_project_file(path):

    try:

        with open(path, "r", encoding="utf-8") as file:

            return file.read()

    except Exception:

        return ""


def table_exists(table_name):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='public'
                AND table_name=%s
            )

        """, (table_name,))

        return cur.fetchone()[0] is True


def column_exists(table_name, column_name):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='public'
                AND table_name=%s
                AND column_name=%s
            )

        """, (table_name, column_name))

        return cur.fetchone()[0] is True


def count_table_rows(query):

    with conn.cursor() as cur:

        cur.execute(query)

        row = cur.fetchone()

        return row[0] if row else 0


def run_beta_smoke_checks():

    report = []

    project_files = {
        "main.py": read_project_file("main.py"),
        "callback_router.py": read_project_file("callback_router.py"),
        "stripe_handler.py": read_project_file("stripe_handler.py"),
        "invite_link_service.py": read_project_file("invite_link_service.py")
    }

    try:

        with conn.cursor() as cur:

            cur.execute("SELECT 1")

            result = cur.fetchone()

        add_smoke_check(
            report,
            "DB responde",
            "ok" if result and result[0] == 1 else "fail",
            "SELECT 1 ejecutado"
        )

    except Exception as e:

        add_smoke_check(report, "DB responde", "fail", e)


    critical_tables = [
        "groups",
        "users",
        "admins",
        "plans",
        "payments",
        "invite_links",
        "audit_logs",
        "beta_monitor_events",
        "beta_smoke_test_runs",
        "beta_cycles",
        "group_user_promo_codes",
        "group_backup_configs",
        "support_tickets"
    ]

    for table_name in critical_tables:

        try:

            add_smoke_check(
                report,
                f"Tabla {table_name}",
                "ok" if table_exists(table_name) else "fail",
                "Existe" if table_exists(table_name) else "No existe"
            )

        except Exception as e:

            add_smoke_check(report, f"Tabla {table_name}", "fail", e)


    try:

        add_smoke_check(
            report,
            "invite_links.telegram_group_id",
            "ok" if column_exists("invite_links", "telegram_group_id") else "fail",
            "Columna disponible para validar con ID real de Telegram"
        )

    except Exception as e:

        add_smoke_check(report, "invite_links.telegram_group_id", "fail", e)


    main_source = project_files["main.py"]
    router_source = project_files["callback_router.py"]
    stripe_source = project_files["stripe_handler.py"]
    invite_source = project_files["invite_link_service.py"]

    static_checks = [
        (
            "Global error handler registrado",
            "add_error_handler" in main_source and "global_error_handler" in main_source,
            "main.py contiene add_error_handler/global_error_handler"
        ),
        (
            "Scheduler beta registrado",
            "schedule_beta_monitor_job(telegram_app)" in main_source,
            "JobQueue beta conectado en arranque"
        ),
        (
            "Callbacks críticos presentes",
            all(
                callback_name in router_source
                for callback_name in [
                    "admin_beta_monitor",
                    "admin_smoke_test",
                    "admin_group_user_codes",
                    "group_user_code_create",
                    "group_user_promo_redeem_start",
                    "free_access_",
                    "marketplace_group_",
                    "owner_backup_panel"
                ]
            ),
            "Router contiene los callbacks críticos de beta"
        ),
        (
            "group_user_code no colisiona con group_{id}",
            "is_numeric_group_callback" in router_source
            and 'int(data.split("_")[1])' not in router_source,
            "El handler group_{id} valida prefijo numérico"
        ),
        (
            "Sin int(data.split(...)) peligroso",
            "int(data.split" not in router_source,
            "No hay conversión directa insegura de callback"
        ),
        (
            "BETA_MONITOR_ENABLED leído",
            "BETA_MONITOR_ENABLED" in read_project_file("audit_log_service.py"),
            "Monitor beta usa variable de entorno"
        ),
        (
            "Sin invite links completos en logs conocidos",
            "Respuesta createChatInviteLink" not in stripe_source
            and "Respuesta createChatInviteLink" not in invite_source,
            "No aparece el log antiguo con link completo"
        )
    ]

    for name, passed, detail in static_checks:

        add_smoke_check(
            report,
            name,
            "ok" if passed else "fail",
            detail
        )


    env_checks = [
        ("TOKEN presente", "TOKEN", True),
        ("STRIPE_SECRET_KEY presente", "STRIPE_SECRET_KEY", True),
        ("STRIPE_WEBHOOK_SECRET presente", "STRIPE_WEBHOOK_SECRET", True),
        ("SERVER_URL/WEBHOOK_URL presente", "SERVER_URL", True)
    ]

    for name, env_name, required in env_checks:

        value = os.environ.get(env_name)

        if env_name == "SERVER_URL":

            value = os.environ.get("SERVER_URL") or os.environ.get("WEBHOOK_URL")

        if value:

            add_smoke_check(report, name, "ok", "Configurado sin mostrar valor")

        else:

            add_smoke_check(
                report,
                name,
                "fail" if required else "warning",
                "No configurado"
            )


    data_checks = [
        ("Grupos activos cargables", "SELECT COUNT(*) FROM groups WHERE is_active=TRUE"),
        ("Owners/admins cargables", "SELECT COUNT(*) FROM admins WHERE is_active=TRUE"),
        ("Planes activos cargables", "SELECT COUNT(*) FROM plans WHERE is_active=TRUE"),
        ("Códigos por grupo activos cargables", "SELECT COUNT(*) FROM group_user_promo_codes WHERE is_active=TRUE"),
        ("Backups configurados cargables", "SELECT COUNT(*) FROM group_backup_configs")
    ]

    for name, query in data_checks:

        try:

            total = count_table_rows(query)

            add_smoke_check(
                report,
                name,
                "ok" if total > 0 else "warning",
                f"Registros encontrados: {total}"
            )

        except Exception as e:

            add_smoke_check(report, name, "fail", e)


    add_smoke_check(
        report,
        "Checks Telegram seguros",
        "manual",
        (
            "Pendiente de prueba real: getChat, getChatMember(bot), "
            "invite link revocable y revocación requieren elegir un grupo y confirmar."
        )
    )

    return report


def summarize_smoke_report(report):

    total_checks = len(report)
    passed_checks = len([item for item in report if item.get("status") == "ok"])
    failed_checks = len([item for item in report if item.get("status") == "fail"])
    warning_checks = len([
        item
        for item in report
        if item.get("status") in ("warning", "manual")
    ])

    return total_checks, passed_checks, failed_checks, warning_checks


def save_beta_smoke_run(started_by, report):

    total_checks, passed_checks, failed_checks, warning_checks = summarize_smoke_report(report)
    status = "failed" if failed_checks else "completed"

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO beta_smoke_test_runs
            (
                started_by,
                status,
                total_checks,
                passed_checks,
                failed_checks,
                warning_checks,
                report
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id, created_at

        """, (
            started_by,
            status,
            total_checks,
            passed_checks,
            failed_checks,
            warning_checks,
            json.dumps(report, ensure_ascii=False, default=str)
        ))

        run_id, created_at = cur.fetchone()
        conn.commit()

    return {
        "id": run_id,
        "created_at": created_at,
        "status": status,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "warning_checks": warning_checks,
        "report": report
    }


def get_last_beta_smoke_run():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   created_at,
                   status,
                   total_checks,
                   passed_checks,
                   failed_checks,
                   warning_checks,
                   report
            FROM beta_smoke_test_runs
            ORDER BY created_at DESC
            LIMIT 1

        """)

        row = cur.fetchone()

    if not row:

        return None

    report = row[7] or []

    return {
        "id": row[0],
        "created_at": row[1],
        "status": row[2],
        "total_checks": row[3],
        "passed_checks": row[4],
        "failed_checks": row[5],
        "warning_checks": row[6],
        "report": report
    }


def clear_beta_smoke_runs():

    with conn.cursor() as cur:

        cur.execute("DELETE FROM beta_smoke_test_runs")
        affected = cur.rowcount
        conn.commit()

    return affected


def format_beta_smoke_report(run):

    if not run:

        return "🧪 Smoke Test Beta\n\nTodavía no hay resultados guardados."


    lines = [
        "🧪 Smoke Test Beta",
        "",
        f"Ejecución: #{run['id']}",
        f"Fecha: {run['created_at']}",
        f"Estado: {run['status']}",
        "",
        f"✅ OK: {run['passed_checks']}",
        f"⚠️ Warnings/manuales: {run['warning_checks']}",
        f"❌ Fallos: {run['failed_checks']}",
        f"Total: {run['total_checks']}",
        ""
    ]


    for item in run.get("report", [])[:30]:

        lines.append(
            f"{smoke_status_icon(item.get('status'))} {item.get('name')}"
        )

        detail = item.get("detail")

        if detail:

            lines.append(f"   {detail}")


    return "\n".join(lines)[:3900]


def format_beta_smoke_manual_checklist():

    return (
        "📋 Checklist manual beta\n\n"
        "🧪 Ejecutar con cuentas/grupos reales antes de abrir la beta:\n\n"
        "1. Pago Stripe test/real y webhook confirmado.\n"
        "2. Entrada de usuario externo con link de pago.\n"
        "3. Acceso gratis con link único.\n"
        "4. Canje de código por grupo.\n"
        "5. Verificación request_location desde móvil.\n"
        "6. Backup texto, foto y vídeo con captions.\n"
        "7. Flujo con GroupAnonymousBot.\n"
        "8. Ticket soporte usuario/admin.\n"
        "9. Bot añadido a grupo por creator aprobado.\n"
        "10. Fallback de callback inválido con mensaje amable.\n\n"
        "Estos pasos no se ejecutan automáticamente para no crear pagos reales "
        "ni modificar grupos sin confirmación."
    )


def user_has_group_permission_any(user_id, group_id, permissions):

    if is_super_admin(user_id):

        return True


    return any(
        has_permission(user_id, group_id, permission)
        for permission in permissions
    )


GROUP_ADMIN_PERMISSION_OPTIONS = [
    ("view_users", "Ver usuarios", "can_view_users"),
    ("manage_users", "Gestionar usuarios", "can_manage_users"),
    ("kick_users", "Expulsar usuarios", "can_kick_users"),
    ("ban_users", "Banear usuarios", "can_ban_users"),
    ("unban_users", "Desbanear usuarios", "can_unban_users"),
    ("warn_users", "Dar warnings", "can_warn_users"),
    ("reset_warnings", "Resetear warnings", "can_reset_warnings"),
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


def user_is_group_owner(user_id, group_id):

    if is_super_admin(user_id):

        return True


    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM admins
            WHERE user_id=%s
            AND group_id=%s
            AND role='GROUP_OWNER'
            AND is_active=TRUE
            LIMIT 1

        """, (
            user_id,
            group_id
        ))

        return cur.fetchone() is not None


def fetch_backup_owner_groups(user_id):

    with conn.cursor() as cur:

        if is_super_admin(user_id):

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       COALESCE(bot_is_admin, FALSE)
                FROM groups
                WHERE telegram_group_id IS NOT NULL
                AND telegram_group_id != 0
                AND COALESCE(is_active, TRUE)=TRUE
                ORDER BY name ASC NULLS LAST,
                         id ASC

            """)

        else:

            cur.execute("""

                SELECT g.id,
                       g.name,
                       g.telegram_group_id,
                       COALESCE(g.bot_is_admin, FALSE)
                FROM admins a
                JOIN groups g
                ON g.id = a.group_id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                AND g.telegram_group_id IS NOT NULL
                AND g.telegram_group_id != 0
                AND COALESCE(g.is_active, TRUE)=TRUE
                ORDER BY g.name ASC NULLS LAST,
                         g.id ASC

            """, (user_id,))


        return cur.fetchall()


def fetch_backup_config(config_id, user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   owner_user_id,
                   source_group_id,
                   source_telegram_group_id,
                   destination_group_id,
                   destination_telegram_group_id,
                   mode,
                   status,
                   COALESCE(show_original_author, FALSE)
            FROM group_backup_configs
            WHERE id=%s
            AND owner_user_id=%s
            LIMIT 1

        """, (
            config_id,
            user_id
        ))

        return cur.fetchone()


def fetch_owner_backup_configs(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT c.id,
                   c.status,
                   c.mode,
                   sg.name,
                   dg.name,
                   c.last_message_at,
                   c.source_group_id,
                   c.destination_group_id,
                   COALESCE(c.show_original_author, FALSE)
            FROM group_backup_configs c
            LEFT JOIN groups sg
            ON sg.id = c.source_group_id
            LEFT JOIN groups dg
            ON dg.id = c.destination_group_id
            WHERE c.owner_user_id=%s
            ORDER BY c.updated_at DESC,
                     c.created_at DESC

        """, (user_id,))

        return cur.fetchall()


def format_backup_panel_text(user_id):

    configs = fetch_owner_backup_configs(user_id)


    if not configs:

        return (
            "🛡 Backup premium\n\n"
            "Estado: sin configurar\n"
            "Modo disponible: texto\n\n"
            "Selecciona un grupo origen y un grupo destino para copiar "
            "mensajes de texto nuevos que el bot reciba."
        )


    text = "🛡 Backup premium\n\n"


    for config in configs[:3]:

        (
            config_id,
            status,
            mode,
            source_name,
            destination_name,
            last_message_at,
            _source_group_id,
            _destination_group_id,
            show_original_author
        ) = config

        text += (
            f"Config #{config_id}\n"
            f"Estado: {status or 'inactive'}\n"
            f"Origen: {source_name or '-'}\n"
            f"Destino: {destination_name or '-'}\n"
            f"Modo: {format_backup_mode(mode)}\n"
            f"Mostrar autor original: {'Activado' if show_original_author else 'Desactivado'}\n"
            f"Último mensaje copiado: {last_message_at or '-'}\n\n"
        )


    return text


def format_backup_mode(mode):

    if mode == "text_photos":

        return "Texto + fotos"


    if mode == "text_photos_videos":

        return "Texto + fotos + vídeos"


    return "Solo texto"


def build_backup_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Activar backup", callback_data="owner_backup_activate")],
        [InlineKeyboardButton("⏸ Pausar backup", callback_data="owner_backup_pause")],
        [InlineKeyboardButton("⚙️ Cambiar modo", callback_data="owner_backup_change_mode")],
        [InlineKeyboardButton("🔗 Vincular grupo destino con código", callback_data="owner_backup_destination_token")],
        [InlineKeyboardButton("👤 Mostrar autor original", callback_data="owner_backup_toggle_author")],
        [InlineKeyboardButton("🔁 Cambiar destino", callback_data="owner_backup_change_destination")],
        [InlineKeyboardButton("⚠️ Últimos errores", callback_data="owner_backup_errors")],
        [InlineKeyboardButton("📜 Últimos mensajes copiados", callback_data="owner_backup_messages")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def build_backup_group_select_keyboard(groups, prefix, back_callback="owner_backup_panel"):

    keyboard = []


    for group_id, name, _telegram_group_id, bot_is_admin in groups:

        label = name or f"Grupo {group_id}"


        if not bot_is_admin:

            label += " · bot sin admin"


        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"{prefix}{group_id}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)


def backup_group_by_id(groups, group_id):

    for group in groups:

        if int(group[0]) == int(group_id):

            return group


    return None


def build_backup_config_select_keyboard(configs, prefix, back_callback="owner_backup_panel"):

    keyboard = []


    for config in configs:

        (
            config_id,
            status,
            mode,
            source_name,
            destination_name,
            _last_message_at,
            _source_group_id,
            _destination_group_id,
            _show_original_author
        ) = config

        keyboard.append([
            InlineKeyboardButton(
                f"#{config_id} · {source_name or '-'} → {destination_name or '-'} · {format_backup_mode(mode)} · {status or 'inactive'}",
                callback_data=f"{prefix}{config_id}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)


def build_backup_mode_keyboard(config_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Solo texto", callback_data=f"owner_backup_set_mode_{config_id}_text")],
        [InlineKeyboardButton("Texto + fotos", callback_data=f"owner_backup_set_mode_{config_id}_text_photos")],
        [InlineKeyboardButton("Texto + fotos + vídeos", callback_data=f"owner_backup_set_mode_{config_id}_text_photos_videos")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="owner_backup_panel")]
    ])


def generate_backup_destination_token():

    alphabet = string.ascii_uppercase + string.digits

    return "BACKUP-" + "".join(
        secrets.choice(alphabet)
        for _ in range(5)
    )


def create_backup_destination_token(owner_user_id, source_group_id, source_telegram_group_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE backup_destination_tokens
            SET status='expired',
                updated_at=NOW()
            WHERE owner_user_id=%s
            AND source_group_id=%s
            AND status='pending'

        """, (
            owner_user_id,
            source_group_id
        ))


        for _attempt in range(5):

            token = generate_backup_destination_token()

            try:

                cur.execute("""

                    INSERT INTO backup_destination_tokens
                    (
                        token,
                        owner_user_id,
                        source_group_id,
                        source_telegram_group_id,
                        status,
                        expires_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, 'pending', NOW() + INTERVAL '24 hours', NOW())
                    RETURNING id, token, expires_at

                """, (
                    token,
                    owner_user_id,
                    source_group_id,
                    source_telegram_group_id
                ))

                row = cur.fetchone()
                conn.commit()

                return row

            except Exception:

                conn.rollback()


    return None


def fetch_backup_recent_messages(user_id, limit=20):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT l.created_at,
                   sg.name,
                   dg.name,
                   l.source_message_id,
                   l.destination_message_id,
                   l.message_type,
                   l.status
            FROM backup_message_log l
            JOIN group_backup_configs c
            ON c.id = l.config_id
            LEFT JOIN groups sg
            ON sg.id = l.source_group_id
            LEFT JOIN groups dg
            ON dg.id = l.destination_group_id
            WHERE c.owner_user_id=%s
            ORDER BY l.created_at DESC
            LIMIT %s

        """, (
            user_id,
            limit
        ))

        return cur.fetchall()


def fetch_backup_recent_errors(user_id, limit=20):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT e.created_at,
                   e.severity,
                   e.error_type,
                   e.message
            FROM backup_errors e
            WHERE e.owner_user_id=%s
            ORDER BY e.created_at DESC
            LIMIT %s

        """, (
            user_id,
            limit
        ))

        return cur.fetchall()


def generate_group_user_promo_code():

    alphabet = string.ascii_uppercase + string.digits

    return "G-" + "".join(
        secrets.choice(alphabet)
        for _ in range(10)
    )


def normalize_group_user_promo_code(raw_code):

    return (raw_code or "").strip().upper()


def is_valid_group_user_promo_code(raw_code):

    code = normalize_group_user_promo_code(raw_code)


    if not 4 <= len(code) <= 32:

        return False


    return all(
        char in string.ascii_uppercase + string.digits + "-_"
        for char in code
    )


def fetch_group_basic_info(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   name,
                   telegram_group_id
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,))

        return cur.fetchone()


def build_group_user_codes_error_keyboard(group_id=None):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=build_group_user_code_callback("group_user_codes_panel", group_id)
        )],
        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]
    ])


def set_group_user_promo_context(context, group_id, step=None):

    group = fetch_group_basic_info(group_id)


    if not group:

        return None


    resolved_group_id, _group_name, telegram_group_id = group
    owner_user_id = get_group_owner_user_id(resolved_group_id)

    context.user_data["selected_group_admin"] = resolved_group_id
    context.user_data["selected_group_user_codes"] = resolved_group_id
    context.user_data["selected_group_id"] = resolved_group_id
    context.user_data["group_user_promo_group_id"] = resolved_group_id
    context.user_data["group_user_promo_telegram_group_id"] = telegram_group_id
    context.user_data["group_user_promo_owner_user_id"] = owner_user_id


    if step:

        context.user_data["group_user_promo_step"] = step


    return group


def clear_group_user_promo_wizard(context, keep_group=True):

    keys = (
        "group_user_promo_duration_days",
        "group_user_promo_is_permanent",
        "group_user_promo_max_uses",
        "group_user_promo_waiting",
        "group_user_promo_step",
        "group_user_promo_pending_code_id"
    )


    for key in keys:

        context.user_data.pop(key, None)


    if not keep_group:

        for key in (
            "selected_group_user_codes",
            "group_user_promo_group_id",
            "group_user_promo_telegram_group_id",
            "group_user_promo_owner_user_id"
        ):

            context.user_data.pop(key, None)


def fetch_group_user_promo_codes(group_id, active_only=False):

    with conn.cursor() as cur:

        active_filter = ""


        if active_only:

            active_filter = """
                AND is_active=TRUE
                AND (
                    expires_at IS NULL
                    OR expires_at > NOW()
                )
                AND (
                    max_uses=0
                    OR used_count < max_uses
                )
            """


        cur.execute(f"""

            SELECT id,
                   code,
                   duration_days,
                   is_permanent,
                   max_uses,
                   used_count,
                   is_active,
                   expires_at,
                   created_at
            FROM group_user_promo_codes
            WHERE group_id=%s
            {active_filter}
            ORDER BY created_at DESC
            LIMIT 50

        """, (group_id,))

        return cur.fetchall()


def fetch_group_user_promo_usage(group_id, limit=30):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT r.redeemed_at,
                   r.user_id,
                   c.code,
                   r.expiration
            FROM group_user_promo_redemptions r
            JOIN group_user_promo_codes c
            ON c.id = r.code_id
            WHERE r.group_id=%s
            ORDER BY r.redeemed_at DESC
            LIMIT %s

        """, (
            group_id,
            limit
        ))

        return cur.fetchall()


def format_group_user_promo_duration(duration_days, is_permanent):

    if is_permanent:

        return "permanente"


    return f"{duration_days} día(s)"


def format_group_user_promo_uses(max_uses, used_count):

    if max_uses == 0:

        return f"{used_count}/ilimitado"


    return f"{used_count}/{max_uses}"


def build_group_user_code_callback(callback_data, group_id=None):

    if group_id:

        return f"{callback_data}_{group_id}"


    return callback_data


def build_group_user_codes_keyboard(group_id=None):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Crear código", callback_data=build_group_user_code_callback("group_user_code_create", group_id))],
        [InlineKeyboardButton("📋 Ver códigos activos", callback_data=build_group_user_code_callback("group_user_codes_active", group_id))],
        [InlineKeyboardButton("🚫 Desactivar código", callback_data=build_group_user_code_callback("group_user_code_deactivate_menu", group_id))],
        [InlineKeyboardButton("📊 Usos de códigos", callback_data=build_group_user_code_callback("group_user_code_usage", group_id))],
        [InlineKeyboardButton("⬅️ Volver", callback_data="edit_group_back")]
    ])


def build_group_user_code_duration_keyboard(group_id=None):

    suffix = f"_{group_id}" if group_id else ""

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 día", callback_data=f"group_user_code_duration{suffix}_1")],
        [InlineKeyboardButton("7 días", callback_data=f"group_user_code_duration{suffix}_7")],
        [InlineKeyboardButton("30 días", callback_data=f"group_user_code_duration{suffix}_30")],
        [InlineKeyboardButton("Permanente", callback_data=f"group_user_code_duration{suffix}_permanent")],
        [InlineKeyboardButton("Personalizado", callback_data=f"group_user_code_duration{suffix}_custom")],
        [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))]
    ])


def build_group_user_code_uses_keyboard(group_id=None):

    suffix = f"_{group_id}" if group_id else ""

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 uso", callback_data=f"group_user_code_uses{suffix}_1")],
        [InlineKeyboardButton("5 usos", callback_data=f"group_user_code_uses{suffix}_5")],
        [InlineKeyboardButton("10 usos", callback_data=f"group_user_code_uses{suffix}_10")],
        [InlineKeyboardButton("Ilimitado", callback_data=f"group_user_code_uses{suffix}_0")],
        [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_code_create", group_id))]
    ])


def build_group_user_code_kind_keyboard(group_id=None):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Código automático", callback_data=build_group_user_code_callback("group_user_code_auto", group_id))],
        [InlineKeyboardButton("Código manual", callback_data=build_group_user_code_callback("group_user_code_manual", group_id))],
        [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_code_create", group_id))]
    ])


def build_group_user_code_deactivate_keyboard(rows, group_id=None):

    keyboard = []


    for code_id, code, duration_days, is_permanent, max_uses, used_count, _is_active, _expires_at, _created_at in rows:

        keyboard.append([
            InlineKeyboardButton(
                f"{code} · {format_group_user_promo_duration(duration_days, is_permanent)} · {format_group_user_promo_uses(max_uses, used_count)}",
                callback_data=(
                    f"group_user_code_deactivate_{group_id}_{code_id}"
                    if group_id
                    else f"group_user_code_deactivate_{code_id}"
                )
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))])

    return InlineKeyboardMarkup(keyboard)


def create_group_user_promo_code(
    group_id,
    owner_user_id,
    duration_days,
    is_permanent,
    max_uses,
    code=None
):

    group = fetch_group_basic_info(group_id)


    if not group:

        return None


    _group_id, _group_name, telegram_group_id = group
    group_owner_user_id = get_group_owner_user_id(group_id) or owner_user_id


    if is_permanent:

        duration_days = None

    elif not duration_days or not 1 <= int(duration_days) <= 3650:

        raise ValueError("invalid_duration")


    if max_uses != 0 and max_uses < 1:

        raise ValueError("invalid_max_uses")


    for _attempt in range(8):

        candidate = normalize_group_user_promo_code(
            code or generate_group_user_promo_code()
        )


        if not is_valid_group_user_promo_code(candidate):

            raise ValueError("invalid_code")


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO group_user_promo_codes
                    (
                        group_id,
                        telegram_group_id,
                        owner_user_id,
                        code,
                        duration_days,
                        is_permanent,
                        max_uses,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                    RETURNING id,
                              code,
                              duration_days,
                              is_permanent,
                              max_uses

                """, (
                    group_id,
                    telegram_group_id,
                    group_owner_user_id,
                    candidate,
                    duration_days,
                    is_permanent,
                    max_uses
                ))

                row = cur.fetchone()
                conn.commit()

                return row

        except Exception as e:

            conn.rollback()


            if code:

                raise


            print("Reintentando código de grupo duplicado:", e)


    return None


def fetch_group_user_promo_by_code(code):

    normalized_code = normalize_group_user_promo_code(code)


    with conn.cursor() as cur:

        cur.execute("""

            SELECT c.id,
                   c.group_id,
                   c.telegram_group_id,
                   c.owner_user_id,
                   c.code,
                   c.duration_days,
                   c.is_permanent,
                   c.max_uses,
                   c.used_count,
                   c.is_active,
                   c.expires_at,
                   g.name,
                   COALESCE(g.is_active, TRUE)
            FROM group_user_promo_codes c
            JOIN groups g
            ON g.id = c.group_id
            WHERE c.code=%s
            LIMIT 1

        """, (normalized_code,))

        return cur.fetchone()


def validate_group_user_promo_row(row):

    if not row:

        return False, "❌ Código de acceso no encontrado."


    (
        _code_id,
        _group_id,
        _telegram_group_id,
        _owner_user_id,
        _code,
        _duration_days,
        _is_permanent,
        max_uses,
        used_count,
        is_active,
        expires_at,
        _group_name,
        group_is_active
    ) = row


    if group_is_active is not True:

        return False, "❌ Esta comunidad no está disponible."


    if is_active is not True:

        return False, "❌ Este código ya no está activo."


    if expires_at and expires_at <= datetime.now():

        return False, "❌ Este código ha caducado."


    if max_uses != 0 and used_count >= max_uses:

        return False, "❌ Este código ya alcanzó el máximo de usos."


    return True, None


async def grant_group_user_promo_access(context, chat_id, telegram_user, promo_row):

    (
        code_id,
        group_id,
        telegram_group_id,
        owner_user_id,
        code,
        duration_days,
        is_permanent,
        _max_uses,
        _used_count,
        _is_active,
        _expires_at,
        group_name,
        _group_is_active
    ) = promo_row

    user_id = telegram_user.id


    if not is_permanent and not duration_days:

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Este código no tiene una duración válida."
        )

        return


    expiration = None


    if not is_permanent:

        expiration = datetime.now() + timedelta(days=int(duration_days))


    link = create_telegram_invite_link(
        TOKEN,
        telegram_group_id,
        expire_seconds=180,
        member_limit=1
    )


    if not link:

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Error creando el enlace de acceso."
        )

        return


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE group_user_promo_codes
            SET used_count=used_count + 1
            WHERE id=%s
            AND is_active=TRUE
            AND (
                expires_at IS NULL
                OR expires_at > NOW()
            )
            AND (
                max_uses=0
                OR used_count < max_uses
            )
            RETURNING used_count

        """, (code_id,))

        code_update = cur.fetchone()


        if not code_update:

            conn.rollback()

            try:

                revoke_telegram_invite_link(
                    TOKEN,
                    telegram_group_id,
                    link
                )

            except Exception as e:

                print("Error revocando link de código no disponible:", e)


            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Este código ya no está disponible."
            )

            return


        cur.execute("""

            DELETE FROM invite_links
            WHERE user_id=%s
            AND (
                group_id=%s
                OR telegram_group_id=%s
                OR group_id=%s
            )

        """, (
            user_id,
            group_id,
            telegram_group_id,
            telegram_group_id
        ))

        cur.execute("""

            INSERT INTO invite_links
            (user_id, group_id, telegram_group_id, invite_link, is_active)
            VALUES (%s, %s, %s, %s, TRUE)

        """, (
            user_id,
            group_id,
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
            VALUES (%s, %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (user_id, group_id)
            DO UPDATE SET
                username=EXCLUDED.username,
                first_name=EXCLUDED.first_name,
                expiration=EXCLUDED.expiration,
                subscription_active=TRUE,
                last_invite_link=EXCLUDED.last_invite_link

        """, (
            user_id,
            group_id,
            telegram_user.username,
            telegram_user.first_name,
            expiration,
            link
        ))

        cur.execute("""

            INSERT INTO group_user_promo_redemptions
            (
                code_id,
                group_id,
                user_id,
                invite_link,
                expiration
            )
            VALUES (%s, %s, %s, %s, %s)

        """, (
            code_id,
            group_id,
            user_id,
            link,
            expiration
        ))

        conn.commit()


    log_event(
        "group_user_promo_redeemed",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=user_id,
        target_user_id=owner_user_id,
        message="Código promocional de grupo canjeado.",
        metadata={
            "code_id": code_id,
            "code": code,
            "is_permanent": is_permanent,
            "duration_days": duration_days
        }
    )


    try:

        await context.bot.send_message(
            chat_id=owner_user_id,
            text=(
                "🎟 Código de tu grupo canjeado\n\n"
                f"Grupo: {group_name or group_id}\n"
                f"Usuario: {user_id}\n"
                f"Código: {code}"
            )
        )

    except Exception as e:

        print("Error avisando al owner del canje de código:", e)


    expiration_text = "permanente" if expiration is None else expiration.strftime("%Y-%m-%d %H:%M")

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ Código canjeado correctamente.\n\n"
            f"Comunidad: {group_name or group_id}\n"
            f"Acceso: {expiration_text}\n\n"
            "Este enlace es personal y de un solo uso.\n"
            "No lo compartas.\n\n"
            f"{link}"
        ),
        reply_markup=ReplyKeyboardRemove()
    )


async def receive_group_user_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):

    waiting = context.user_data.get("group_user_promo_waiting")


    if waiting == "custom_duration":

        raw_duration = (update.message.text or "").strip()
        group_id = context.user_data.get("group_user_promo_group_id")


        if not raw_duration.isdigit() or not 1 <= int(raw_duration) <= 3650:

            await update.message.reply_text(
                "⚠️ El dato no parece válido. Revisa el formato y vuelve a intentarlo.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        context.user_data["group_user_promo_duration_days"] = int(raw_duration)
        context.user_data["group_user_promo_is_permanent"] = False
        context.user_data["group_user_promo_waiting"] = None

        await update.message.reply_text(
            "Elige cuántos usos tendrá el código.",
            reply_markup=build_group_user_code_uses_keyboard(group_id)
        )

        return


    if waiting == "manual_code":

        manual_code = normalize_group_user_promo_code(update.message.text)
        group_id = context.user_data.get("group_user_promo_group_id")
        duration_days = context.user_data.get("group_user_promo_duration_days")
        is_permanent = context.user_data.get("group_user_promo_is_permanent") is True
        max_uses = context.user_data.get("group_user_promo_max_uses")


        if not is_valid_group_user_promo_code(manual_code):

            await update.message.reply_text(
                "⚠️ El dato no parece válido. Revisa el formato y vuelve a intentarlo.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        if not group_id or max_uses is None:

            await update.message.reply_text(
                "❌ No hay configuración de código pendiente.",
                reply_markup=build_group_user_codes_error_keyboard()
            )
            context.user_data.pop("group_user_promo_waiting", None)

            return


        if not user_has_group_permission_any(
            update.effective_user.id,
            group_id,
            ["can_manage_codes"]
        ):

            await update.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )
            context.user_data.pop("group_user_promo_waiting", None)

            return


        try:

            row = create_group_user_promo_code(
                group_id,
                update.effective_user.id,
                duration_days,
                is_permanent,
                max_uses,
                code=manual_code
            )

        except Exception as e:

            print("Error creando código manual de grupo:", e)

            await update.message.reply_text(
                "❌ No pude crear el código. Revisa que no esté repetido.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        clear_group_user_promo_wizard(context, keep_group=True)

        await update.message.reply_text(
            "✅ Código creado\n\n"
            f"Código: {row[1]}\n"
            f"Duración: {format_group_user_promo_duration(row[2], row[3])}\n"
            f"Usos máximos: {'ilimitado' if row[4] == 0 else row[4]}",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if waiting == "redeem_code":

        promo_row = fetch_group_user_promo_by_code(update.message.text)
        valid, error_message = validate_group_user_promo_row(promo_row)
        selected_group_id = context.user_data.get("group_user_promo_redeem_group_id")


        if valid and selected_group_id and int(promo_row[1]) != int(selected_group_id):

            valid = False
            error_message = "❌ Este código no pertenece a esta comunidad."


        if not valid:

            context.user_data.pop("group_user_promo_waiting", None)

            log_event(
                "group_code_failed",
                category="access",
                severity="warning",
                scope="global",
                actor_user_id=update.effective_user.id,
                target_user_id=update.effective_user.id,
                message="Intento fallido de canje de código de grupo.",
                metadata={
                    "reason": error_message
                }
            )

            await update.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🎟 Canjear código de esta comunidad",
                        callback_data=f"group_user_promo_redeem_start_{selected_group_id}"
                        if selected_group_id
                        else "start_explore_groups"
                    )],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        context.user_data["group_user_promo_waiting"] = None
        context.user_data["group_user_promo_pending_code_id"] = promo_row[0]

        await update.message.reply_text(
            "🎟 Código encontrado\n\n"
            f"Comunidad: {promo_row[11] or promo_row[1]}\n"
            f"Duración: {format_group_user_promo_duration(promo_row[5], promo_row[6])}\n\n"
            "Confirma para generar tu enlace personal de acceso.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Canjear acceso", callback_data=f"group_user_promo_confirm_{promo_row[0]}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    await update.message.reply_text(
        "No estaba esperando ese dato. Usa los botones del menú para continuar.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])
    )


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


def build_group_admin_error_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="group_admin_panel"
        )],
        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]
    ])


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


def fetch_group_admin_permissions(group_id, target_user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT can_view_users,
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
        "role": row[len(GROUP_ADMIN_PERMISSION_OPTIONS)],
        "is_active": row[len(GROUP_ADMIN_PERMISSION_OPTIONS) + 1] is True
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
        values_by_permission.get("can_manage_users", False),
        values_by_permission.get("can_kick_users", False),
        values_by_permission.get("can_ban_users", False),
        values_by_permission.get("can_unban_users", False),
        values_by_permission.get("can_warn_users", False),
        values_by_permission.get("can_reset_warnings", False),
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


OWNER_QUICK_STATUS_PERMISSIONS = {
    "can_view_users": "ver usuarios",
    "can_manage_users": "gestionar usuarios",
    "can_kick_users": "expulsar usuarios",
    "can_ban_users": "banear usuarios",
    "can_unban_users": "desbanear usuarios",
    "can_warn_users": "gestionar warnings",
    "can_reset_warnings": "reiniciar warnings",
    "can_resend_links": "reenviar enlaces",
    "can_recover_access": "recuperar accesos",
    "can_manage_codes": "gestionar códigos",
    "can_manage_plans": "gestionar planes",
    "can_manage_payments": "gestionar pagos",
    "can_view_payments": "ver pagos",
    "can_manage_groups": "configurar comunidad",
    "can_manage_admins": "gestionar admins",
    "can_view_logs": "ver logs",
    "can_edit_group_texts": "editar textos",
    "can_edit_marketplace_preview": "editar marketplace",
}


def get_group_permission_summary(user_id, group_id):

    if is_super_admin(user_id):

        return "Puedes gestionar: todo el panel de esta comunidad."


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT role, """ + ", ".join(ADMIN_PERMISSION_COLUMNS) + """
                FROM admins
                WHERE user_id=%s
                AND group_id=%s
                AND is_active=TRUE
                LIMIT 1

            """, (user_id, group_id))

            row = cur.fetchone()

    except Exception as e:

        print("Error cargando permisos del grupo:", e)

        return "Puedes gestionar: permisos no disponibles ahora."


    if not row:

        return "Puedes gestionar: ninguna sección de esta comunidad."


    role = row[0]

    if role == "GROUP_OWNER":

        return "Puedes gestionar: todo el panel owner de esta comunidad."


    granted = [
        OWNER_QUICK_STATUS_PERMISSIONS[column]
        for index, column in enumerate(ADMIN_PERMISSION_COLUMNS, start=1)
        if row[index] and column in OWNER_QUICK_STATUS_PERMISSIONS
    ]


    if not granted:

        return "Puedes gestionar: permisos limitados sin accesos rápidos activos."


    return "Puedes gestionar: " + ", ".join(granted[:8]) + ("..." if len(granted) > 8 else "") + "."


def fetch_owner_group_quick_status(group_id):

    status = {
        "name": "Comunidad",
        "is_free_group": False,
        "public_visibility": "start_home",
        "active_users": 0,
        "active_plans": 0,
        "active_codes": 0,
        "active_admins": 0,
        "backup_active": False,
        "critical_errors": []
    }


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT name, COALESCE(is_free_group, FALSE), COALESCE(public_visibility, 'start_home')
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            group_row = cur.fetchone()

            if group_row:

                status["name"] = group_row[0] or "Comunidad"
                status["is_free_group"] = bool(group_row[1])
                status["public_visibility"] = group_row[2] or "start_home"


            cur.execute("""

                SELECT COUNT(*)
                FROM users
                WHERE group_id=%s
                AND COALESCE(subscription_active, FALSE)=TRUE
                AND (
                    expiration IS NULL
                    OR expiration > NOW()
                )

            """, (group_id,))

            status["active_users"] = cur.fetchone()[0] or 0


            cur.execute("""

                SELECT COUNT(*)
                FROM plans
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE

            """, (group_id,))

            status["active_plans"] = cur.fetchone()[0] or 0


            cur.execute("""

                SELECT COUNT(*)
                FROM group_user_promo_codes
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE

            """, (group_id,))

            status["active_codes"] = cur.fetchone()[0] or 0


            cur.execute("""

                SELECT COUNT(*)
                FROM admins
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE

            """, (group_id,))

            status["active_admins"] = cur.fetchone()[0] or 0


            cur.execute("""

                SELECT 1
                FROM group_backup_configs
                WHERE source_group_id=%s
                AND status='active'
                LIMIT 1

            """, (group_id,))

            status["backup_active"] = cur.fetchone() is not None


            cur.execute("""

                SELECT event_type, message
                FROM audit_logs
                WHERE group_id=%s
                AND severity='critical'
                ORDER BY created_at DESC
                LIMIT 3

            """, (group_id,))

            status["critical_errors"] = cur.fetchall()

    except Exception as e:

        print("Error cargando estado rápido owner:", e)


    return status


def build_owner_quick_status_text(user_id, group_id):

    status = fetch_owner_group_quick_status(group_id)
    access_type = "Gratis" if status["is_free_group"] else "Pago"
    backup_text = "Activo" if status["backup_active"] else "No activo"
    errors_text = "Sin errores críticos recientes"


    if status["critical_errors"]:

        errors_text = "\n".join(
            f"- {event_type or 'error'}: {message or 'sin detalle'}"
            for event_type, message in status["critical_errors"]
        )


    return (
        "✅ Estado rápido de esta comunidad\n\n"
        f"Comunidad: {status['name']}\n"
        f"Tipo: {access_type}\n"
        f"Visibilidad marketplace: {status['public_visibility']}\n"
        f"Usuarios activos: {status['active_users']}\n"
        f"Planes activos: {status['active_plans']}\n"
        f"Códigos activos: {status['active_codes']}\n"
        f"Admins activos: {status['active_admins']}\n"
        f"Backup: {backup_text}\n"
        f"Errores críticos recientes: {errors_text}\n\n"
        f"{get_group_permission_summary(user_id, group_id)}\n\n"
        "🏪 Panel de comunidad\n"
        "Elige el apartado que quieres gestionar."
    )


def build_owner_setup_assistant_text(group_id):

    status = fetch_owner_group_quick_status(group_id)

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT
                    COALESCE(name, ''),
                    COALESCE(preview_text, ''),
                    preview_image_file_id,
                    preview_video_file_id,
                    COALESCE(preview_mode, 'manual')
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            group_row = cur.fetchone()

    except Exception as e:

        print("Error cargando asistente owner:", e)

        group_row = None


    name_done = bool(group_row and group_row[0])
    preview_done = bool(
        group_row
        and (
            group_row[1]
            or group_row[2]
            or group_row[3]
            or group_row[4] in ("dynamic", "hybrid", "private")
        )
    )
    access_done = status["is_free_group"] or status["active_plans"] > 0
    codes_done = status["active_codes"] > 0
    admins_done = status["active_admins"] > 0
    logs_done = not status["critical_errors"]
    backup_done = status["backup_active"]


    def mark(done):

        return "✅ completado" if done else "⚠️ pendiente"


    return (
        "🧭 Asistente de configuración\n\n"
        "Sigue esta lista para dejar tu comunidad lista para la beta.\n\n"
        f"{mark(name_done)} — configurar nombre/descripción\n"
        f"{mark(preview_done)} — configurar preview\n"
        f"{mark(access_done)} — configurar plan o acceso gratis\n"
        f"{mark(codes_done)} — crear primer código promocional\n"
        f"{mark(admins_done)} — revisar admins\n"
        f"{mark(logs_done)} — revisar logs críticos\n"
        f"{mark(backup_done)} — activar backup opcional"
    )


def build_owner_setup_assistant_keyboard(user_id, group_id):

    keyboard = []


    if user_has_group_permission_any(user_id, group_id, ["can_manage_groups", "can_edit_group_texts"]):
        keyboard.append([InlineKeyboardButton("⚙️ Nombre/descripción", callback_data="owner_panel_general")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_groups", "can_edit_marketplace_preview"]):
        keyboard.append([InlineKeyboardButton("🖼 Preview", callback_data="owner_panel_marketplace")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_plans", "can_manage_groups"]):
        keyboard.append([InlineKeyboardButton("💳 Plan/acceso", callback_data="owner_panel_payments")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_codes"]):
        keyboard.append([InlineKeyboardButton("🎟 Primer código", callback_data="owner_panel_codes")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_admins"]):
        keyboard.append([InlineKeyboardButton("👑 Admins", callback_data="owner_panel_admins")])

    if user_has_group_permission_any(user_id, group_id, ["can_view_logs"]):
        keyboard.append([InlineKeyboardButton("📜 Logs", callback_data="owner_panel_logs")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):
        keyboard.append([InlineKeyboardButton("🛡 Backup opcional", callback_data="owner_panel_backup")])


    keyboard.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return InlineKeyboardMarkup(keyboard)


def build_group_settings_keyboard(user_id, group_id):

    keyboard = []


    keyboard.append([
        InlineKeyboardButton("🧭 Asistente de configuración", callback_data="owner_setup_assistant")
    ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        [
            "can_view_users",
            "can_manage_users",
            "can_kick_users",
            "can_ban_users",
            "can_unban_users",
            "can_warn_users",
            "can_reset_warnings",
            "can_resend_links",
            "can_recover_access"
        ]
    ):

        keyboard.append([
            InlineKeyboardButton("👥 Usuarios y accesos", callback_data="owner_panel_users")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_codes"]
    ):

        keyboard.append([
            InlineKeyboardButton("🎟 Códigos y promociones", callback_data="owner_panel_codes")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
    ):

        keyboard.append([
            InlineKeyboardButton("💳 Planes y pagos del grupo", callback_data="owner_panel_payments")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_view_logs"]
    ):

        keyboard.append([
            InlineKeyboardButton("🛡 Seguridad del grupo", callback_data="owner_panel_security")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_edit_group_texts", "can_edit_marketplace_preview"]
    ):

        keyboard.append([
            InlineKeyboardButton("🖼 Marketplace y preview", callback_data="owner_panel_marketplace")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_admins"]
    ):

        keyboard.append([
            InlineKeyboardButton("👑 Administradores del grupo", callback_data="owner_panel_admins")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_view_logs"]
    ):

        keyboard.append([
            InlineKeyboardButton("📜 Logs y actividad del grupo", callback_data="owner_panel_logs")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_respond_group_support"]
    ):

        keyboard.append([
            InlineKeyboardButton("🛟 Solicitudes de soporte", callback_data="owner_panel_support")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups"]
    ):

        keyboard.append([
            InlineKeyboardButton("🛡 Backup premium", callback_data="owner_panel_backup")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_edit_group_texts"]
    ):

        keyboard.append([
            InlineKeyboardButton("⚙️ Configuración de la comunidad", callback_data="owner_panel_general")
        ])


    if is_super_admin(user_id):

        keyboard.append([
            InlineKeyboardButton("❌ Eliminar grupo", callback_data="delete_group_confirm")
        ])


    keyboard.append([
        InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")
    ])

    keyboard.append([
        InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")
    ])

    return keyboard


def build_owner_panel_nav_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_section_keyboard(user_id, group_id, section):

    keyboard = []


    if section == "users":

        if user_has_group_permission_any(user_id, group_id, ["can_view_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("📋 Ver usuarios", callback_data="admin_users")])

        if user_has_group_permission_any(user_id, group_id, ["can_kick_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("🚫 Expulsar usuario", callback_data="admin_kick_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_ban_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("⛔ Banear usuario", callback_data="admin_ban_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_unban_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("♻️ Desbanear usuario", callback_data="admin_unban_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_warn_users", "can_reset_warnings", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("⚠️ Warnings", callback_data="admin_reset_warnings")])

        if user_has_group_permission_any(user_id, group_id, ["can_resend_links", "can_recover_access"]):
            keyboard.append([InlineKeyboardButton("📩 Reenviar / recuperar link", callback_data="admin_resend_access")])

    elif section == "codes":

        keyboard.extend([
            [InlineKeyboardButton("🎟 Códigos de mi grupo", callback_data="edit_group_user_codes")],
            [InlineKeyboardButton("➕ Crear código", callback_data="group_user_code_create")],
            [InlineKeyboardButton("📋 Ver códigos activos", callback_data="group_user_codes_active")],
            [InlineKeyboardButton("📊 Usos de códigos", callback_data="group_user_code_usage")],
            [InlineKeyboardButton("🚫 Desactivar código", callback_data="group_user_code_deactivate_menu")]
        ])

    elif section == "payments":

        if user_has_group_permission_any(user_id, group_id, ["can_manage_plans", "can_manage_groups"]):
            keyboard.append([InlineKeyboardButton("📋 Ver planes", callback_data="view_group_plans")])
            keyboard.append([InlineKeyboardButton("💳 Crear/editar planes", callback_data="edit_group_plans")])

        if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):
            keyboard.append([InlineKeyboardButton("🔗 Stripe/configuración pagos", callback_data="edit_group_stripe")])

        if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:
            keyboard.append([InlineKeyboardButton("💳 Métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")])

        if user_has_group_permission_any(user_id, group_id, ["can_view_payments", "can_manage_payments"]):
            keyboard.append([InlineKeyboardButton("💳 Pagos recibidos", callback_data="admin_view_payments")])
            keyboard.append([InlineKeyboardButton("📌 Suscripciones activas", callback_data="admin_view_payments")])

    elif section == "security":

        if user_has_group_permission_any(user_id, group_id, ["can_view_logs"]):
            keyboard.append([InlineKeyboardButton("📜 Logs de accesos", callback_data="admin_logs_security")])

        if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):
            keyboard.append([InlineKeyboardButton("📍 Ubicación permitida", callback_data="owner_panel_location_info")])
            keyboard.append([InlineKeyboardButton("🛡 Anti-intrusos", callback_data="owner_panel_security_info")])
            keyboard.append([InlineKeyboardButton("🔗 Anti-links", callback_data="owner_panel_security_info")])

    elif section == "marketplace":

        keyboard.extend([
            [InlineKeyboardButton("✏️ Editar ficha", callback_data="edit_group_name")],
            [InlineKeyboardButton("🎬 Editar preview", callback_data="edit_group_preview")],
            [InlineKeyboardButton("👁 Preview manual/dinámico/mixto", callback_data="edit_group_preview")],
            [InlineKeyboardButton("📂 Categoría/tags", callback_data="edit_group_preview")]
        ])

    elif section == "admins":

        keyboard.extend([
            [InlineKeyboardButton("👑 Administradores", callback_data="edit_group_admins")],
            [InlineKeyboardButton("➕ Añadir admin", callback_data="group_admin_add")],
            [InlineKeyboardButton("📋 Ver admins", callback_data="group_admin_view")],
            [InlineKeyboardButton("✏️ Editar permisos", callback_data="group_admin_edit")],
            [InlineKeyboardButton("❌ Quitar admin", callback_data="group_admin_remove")]
        ])

    elif section == "logs":

        keyboard.extend([
            [InlineKeyboardButton("📜 Logs de mi grupo", callback_data="admin_logs")],
            [InlineKeyboardButton("👥 Accesos", callback_data="admin_logs_users")],
            [InlineKeyboardButton("💳 Pagos", callback_data="admin_logs_payments")],
            [InlineKeyboardButton("🎟 Códigos", callback_data="admin_logs_security")],
            [InlineKeyboardButton("🛡 Backups / errores", callback_data="admin_logs_security")]
        ])

    elif section == "support":

        keyboard.extend([
            [InlineKeyboardButton("🛟 Ver solicitudes de soporte", callback_data="owner_support_tickets")],
            [InlineKeyboardButton("💬 Abrir soporte", callback_data="public_support")]
        ])

    elif section == "backup":

        keyboard.extend([
            [InlineKeyboardButton("🛡 Estado backup", callback_data="owner_backup_panel")],
            [InlineKeyboardButton("🔗 Configurar origen/destino", callback_data="owner_backup_destination_token")],
            [InlineKeyboardButton("⚙️ Cambiar modo", callback_data="owner_backup_change_mode")],
            [InlineKeyboardButton("📜 Últimos mensajes copiados", callback_data="owner_backup_messages")],
            [InlineKeyboardButton("⚠️ Últimos errores", callback_data="owner_backup_errors")]
        ])

    elif section == "general":

        keyboard.extend([
            [InlineKeyboardButton("✏️ Nombre comunidad", callback_data="edit_group_name")],
            [InlineKeyboardButton("📝 Descripción", callback_data="edit_group_name")],
            [InlineKeyboardButton("🔓 Tipo gratis/pago", callback_data="owner_panel_access_type_info")],
            [InlineKeyboardButton("🔢 Cupo/configuración", callback_data="owner_panel_general_info")],
            [InlineKeyboardButton("🧹 Reiniciar configuración segura", callback_data="owner_panel_general_info")]
        ])


    keyboard.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return InlineKeyboardMarkup(keyboard)


OWNER_PANEL_SECTIONS = {
    "owner_panel_users": (
        "👥 Usuarios y accesos",
        "Gestiona entradas, expulsiones, bans, warnings y recuperación de acceso.",
        ["can_view_users", "can_manage_users", "can_kick_users", "can_ban_users", "can_unban_users", "can_warn_users", "can_reset_warnings", "can_resend_links", "can_recover_access"],
        "users"
    ),
    "owner_panel_codes": (
        "🎟 Códigos y promociones",
        "Crea y revisa códigos de acceso exclusivos para esta comunidad.",
        ["can_manage_codes"],
        "codes"
    ),
    "owner_panel_payments": (
        "💳 Planes y pagos del grupo",
        "Gestiona planes, cobros, Stripe y pagos recibidos.",
        ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"],
        "payments"
    ),
    "owner_panel_security": (
        "🛡 Seguridad del grupo",
        "Revisa protección de acceso, anti-intrusos, anti-links y ubicación permitida.",
        ["can_manage_groups", "can_view_logs"],
        "security"
    ),
    "owner_panel_marketplace": (
        "🖼 Marketplace y preview",
        "Configura visibilidad pública, ficha, previews, categoría y tags.",
        ["can_manage_groups", "can_edit_group_texts", "can_edit_marketplace_preview"],
        "marketplace"
    ),
    "owner_panel_admins": (
        "👑 Administradores del grupo",
        "Añade admins de grupo y ajusta sus permisos por comunidad.",
        ["can_manage_admins"],
        "admins"
    ),
    "owner_panel_logs": (
        "📜 Logs y actividad del grupo",
        "Consulta accesos, pagos, códigos, backups y errores de esta comunidad.",
        ["can_view_logs"],
        "logs"
    ),
    "owner_panel_support": (
        "🛟 Solicitudes de soporte",
        "Revisa el acceso al soporte de esta comunidad sin mezclar tickets globales.",
        ["can_respond_group_support"],
        "support"
    ),
    "owner_panel_backup": (
        "🛡 Backup premium",
        "Configura copia de seguridad de mensajes nuevos recibidos por el bot.",
        ["can_manage_groups"],
        "backup"
    ),
    "owner_panel_general": (
        "⚙️ Configuración de la comunidad",
        "Edita datos básicos, tipo de acceso y ajustes seguros de la comunidad.",
        ["can_manage_groups", "can_edit_group_texts"],
        "general"
    )
}

def get_selected_group_for_permissions(context, user_id, permissions):

    for key in (
        "selected_group_admin",
        "selected_group_user_codes",
        "group_user_promo_group_id",
        "selected_owner_group"
    ):

        group_id = context.user_data.get(key)


        if not group_id:

            continue


        try:

            group_id = int(group_id)

        except Exception:

            continue


        if user_has_group_permission_any(user_id, group_id, permissions):

            return group_id


    return None


def resolve_group_user_codes_group(context, user_id, permissions, group_id=None):

    if group_id:

        try:

            group_id = int(group_id)

        except Exception:

            return None


        if not user_has_group_permission_any(user_id, group_id, permissions):

            return None


        if not set_group_user_promo_context(context, group_id):

            return None


        return group_id


    return get_selected_group_for_permissions(
        context,
        user_id,
        permissions
    )


def parse_group_user_code_group_callback(data, prefix):

    if data == prefix:

        return None


    if not data.startswith(f"{prefix}_"):

        return None


    payload = data.replace(f"{prefix}_", "", 1)


    if not payload.isdigit():

        return None


    return int(payload)


def parse_group_user_code_step_callback(data, prefix):

    payload = data.replace(prefix, "", 1).strip("_")


    if not payload:

        return None, None


    parts = payload.split("_", 1)


    if len(parts) == 2 and parts[0].isdigit():

        return int(parts[0]), parts[1]


    return None, payload


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
    "max_groups_allowed",
    "expired_at",
    "delete_after",
    "last_expiry_reminder_at",
    "previous_public_visibility",
    "last_interaction_user_id",
    "last_interaction_username",
    "last_interaction_first_name",
    "last_interaction_at"

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


COMMERCIAL_REQUEST_MESSAGE_FIELDS = [

    "id",
    "commercial_request_id",
    "sender_type",
    "sender_id",
    "message_text",
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

COMMERCIAL_ADVANCED_STATUSES = (
    "trial_active",
    "awaiting_creator_setup",
    "setup_in_progress",
    "setup_ready",
    "active",
    "trial_expired",
    "expired_pending_reactivation",
    "awaiting_payment",
    "awaiting_payment_setup"
)

COMMERCIAL_ARCHIVED_STATUSES = (
    "archived",
    "closed"
)

COMMERCIAL_ADVANCED_CREATOR_SETUP_STATUSES = (
    "awaiting_creator_setup",
    "pending_group_link",
    "setup_in_progress",
    "setup_ready"
)

DUPLICATE_COMMERCIAL_APPROVAL_MESSAGE = (
    "Esta solicitud ya está aprobada o en configuración. "
    "No se ha reenviado el flujo al usuario."
)


def row_to_commercial_request(row):

    if not row:

        return None


    return dict(zip(COMMERCIAL_REQUEST_FIELDS, row))


def row_to_commercial_plan(row):

    if not row:

        return None


    return dict(zip(COMMERCIAL_PLAN_FIELDS, row))


def row_to_commercial_request_message(row):

    if not row:

        return None


    return dict(zip(COMMERCIAL_REQUEST_MESSAGE_FIELDS, row))


def format_commercial_request_type(request_type):

    labels = {
        "shared_trial": "prueba comunidad compartida",
        "custom_bot": "bot personalizado",
        "support_contact": "contacto comercial"
    }

    return labels.get(request_type, request_type or "-")


def format_commercial_request_status(status):

    labels = {
        "pending": "pendiente",
        "approved": "aprobada",
        "rejected": "rechazada",
        "trial_active": "trial activo",
        "trial_expired": "trial caducado",
        "awaiting_creator_setup": "pendiente de configuración",
        "setup_in_progress": "configuración en curso",
        "setup_ready": "configuración lista",
        "awaiting_payment_setup": "pendiente de cobro",
        "awaiting_payment": "pendiente de pago",
        "active": "activa",
        "disabled": "desactivada",
        "expired_pending_reactivation": "pendiente de reactivación",
        "archived": "archivada",
        "closed": "cerrada"
    }

    return labels.get(status, status or "-")


def format_public_visibility(public_visibility):

    labels = {
        "start_home": "inicio",
        "explore_only": "explorar",
        "hidden": "oculta/borrador"
    }

    return labels.get(public_visibility, public_visibility or "-")


def commercial_request_has_linked_group(request_row):

    if not request_row:

        return False


    return (
        request_row.get("approved_group_id") is not None
        or request_row.get("approved_telegram_group_id") is not None
    )


def is_commercial_request_advanced(request_row):

    if not request_row:

        return False


    status = request_row.get("status") or ""
    creator_setup_status = request_row.get("creator_setup_status") or ""


    return (
        status in COMMERCIAL_ADVANCED_STATUSES
        or status in COMMERCIAL_ARCHIVED_STATUSES
        or (
            status != "pending"
            and creator_setup_status in COMMERCIAL_ADVANCED_CREATOR_SETUP_STATUSES
        )
        or commercial_request_has_linked_group(request_row)
    )


def is_commercial_request_archived(request_row):

    if not request_row:

        return False


    return (request_row.get("status") or "") in COMMERCIAL_ARCHIVED_STATUSES


def fetch_recoverable_creator_request_id(user_id):

    if not user_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id
            FROM commercial_requests
            WHERE user_id=%s
            AND request_type='shared_trial'
            AND COALESCE(status, 'pending') NOT IN (
                'pending',
                'rejected',
                'archived',
                'closed',
                'deleted_irreversible'
            )
            AND (
                status = ANY(%s)
                OR creator_setup_status = ANY(%s)
                OR approved_group_id IS NOT NULL
                OR approved_telegram_group_id IS NOT NULL
            )
            ORDER BY reviewed_at DESC NULLS LAST,
                     updated_at DESC NULLS LAST,
                     created_at DESC
            LIMIT 1

        """, (
            user_id,
            list(COMMERCIAL_ADVANCED_STATUSES) + ["approved"],
            list(COMMERCIAL_ADVANCED_CREATOR_SETUP_STATUSES)
        ))

        row = cur.fetchone()


    return row[0] if row else None


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

MARKETPLACE_DEFAULT_FILTER = "trending"

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
            AND (
                (
                    cr.status='trial_active'
                    AND cr.trial_ends_at IS NOT NULL
                    AND cr.trial_ends_at < NOW()
                    AND COALESCE(cr.commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
                )
                OR cr.status='expired_pending_reactivation'
            )
        )
    """


def build_expired_trial_recovery_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "💳 Reactivar pagando",
            callback_data=f"expired_trial_activate_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Reactivar con código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Ver configuración",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "🗑 Eliminar ahora definitivamente",
            callback_data=f"expired_trial_delete_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def build_expired_trial_reminder_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "💳 Reactivar pagando",
            callback_data=f"expired_trial_activate_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Usar código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Ver configuración",
            callback_data=f"configure_community_{request_id}"
        )]

    ])


def format_retention_days_left(delete_after):

    if not delete_after:

        return 0


    try:

        remaining_seconds = (delete_after - datetime.now()).total_seconds()
        remaining_days = int((remaining_seconds + 86399) // 86400)

        return max(remaining_days, 0)

    except Exception:

        return 0


def expired_community_message(days_left=None):

    text = (
        "Tu comunidad ha caducado.\n"
        "Tus datos se conservarán durante 15 días.\n"
        "Puedes reactivarla pagando o usando un código promocional."
    )


    if days_left is not None:

        text += f"\n\nTe quedan {days_left} días antes del borrado definitivo."


    return text


def mark_commercial_request_expired(cur, request_id):

    cur.execute(f"""

        UPDATE commercial_requests cr
        SET status='expired_pending_reactivation',
            commercial_subscription_status='expired',
            previous_public_visibility=COALESCE(
                NULLIF(cr.previous_public_visibility, 'hidden'),
                NULLIF(cr.requested_public_visibility, 'hidden'),
                NULLIF(g.public_visibility, 'hidden'),
                'explore_only'
            ),
            requested_public_visibility='hidden',
            expired_at=NOW(),
            delete_after=NOW() + INTERVAL '15 days',
            last_expiry_reminder_at=NOW(),
            updated_at=NOW()
        FROM groups g
        WHERE cr.id=%s
        AND (
            cr.approved_group_id = g.id
            OR cr.approved_telegram_group_id = g.telegram_group_id
        )
        RETURNING {", ".join("cr." + field for field in COMMERCIAL_REQUEST_FIELDS)}

    """, (request_id,))

    row = cur.fetchone()


    if not row:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='expired_pending_reactivation',
                commercial_subscription_status='expired',
                previous_public_visibility=COALESCE(
                    NULLIF(previous_public_visibility, 'hidden'),
                    NULLIF(requested_public_visibility, 'hidden'),
                    'explore_only'
                ),
                requested_public_visibility='hidden',
                expired_at=NOW(),
                delete_after=NOW() + INTERVAL '15 days',
                last_expiry_reminder_at=NOW(),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def hide_commercial_request_group(cur, request_row):

    approved_group_id = request_row.get("approved_group_id") if request_row else None
    approved_telegram_group_id = (
        request_row.get("approved_telegram_group_id")
        if request_row
        else None
    )


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


def finalize_expired_commercial_request(cur, request_row):

    if not request_row:

        return None


    request_id = request_row.get("id")
    approved_group_id = request_row.get("approved_group_id")
    approved_telegram_group_id = request_row.get("approved_telegram_group_id")


    cur.execute(f"""

        UPDATE commercial_requests
        SET status='deleted_irreversible',
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
            SET is_active=FALSE,
                public_visibility='hidden',
                preview_text=NULL,
                preview_image_file_id=NULL,
                preview_video_file_id=NULL,
                category=NULL,
                tags=NULL,
                marketplace_badge=NULL
            WHERE id=%s

        """, (approved_group_id,))

    elif approved_telegram_group_id:

        cur.execute("""

            UPDATE groups
            SET is_active=FALSE,
                public_visibility='hidden',
                preview_text=NULL,
                preview_image_file_id=NULL,
                preview_video_file_id=NULL,
                category=NULL,
                tags=NULL,
                marketplace_badge=NULL
            WHERE telegram_group_id=%s

        """, (approved_telegram_group_id,))


    request_row = row_to_commercial_request(row)


    if request_row:

        sync_commercial_creator_profile_from_request(
            request_row.get("user_id")
        )


    return request_row


async def process_expired_commercial_retention(context):

    newly_expired_requests = []
    reminder_requests = []
    finalized_requests = []
    summary = {
        "newly_expired": 0,
        "expiry_notices_sent": 0,
        "reminders_due": 0,
        "reminders_sent": 0,
        "finalized": 0,
        "admin_notices_sent": 0,
        "send_errors": 0,
        "skipped_without_user": 0
    }


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id
            FROM commercial_requests
            WHERE (
                (
                    status='trial_active'
                    AND trial_ends_at IS NOT NULL
                    AND trial_ends_at < NOW()
                    AND COALESCE(commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
                )
                OR (
                    status='active'
                    AND commercial_subscription_until IS NOT NULL
                    AND commercial_subscription_until < NOW()
                )
            )
            AND (
                approved_group_id IS NOT NULL
                OR approved_telegram_group_id IS NOT NULL
            )

        """)

        rows = cur.fetchall()


        for (request_id,) in rows:

            request_row = mark_commercial_request_expired(cur, request_id)
            hide_commercial_request_group(cur, request_row)


            if request_row:

                newly_expired_requests.append(request_row)


        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status='expired_pending_reactivation'
            AND delete_after IS NOT NULL
            AND delete_after <= NOW()

        """)

        rows = cur.fetchall()


        for row in rows:

            request_row = row_to_commercial_request(row)
            finalized_row = finalize_expired_commercial_request(
                cur,
                request_row
            )

            finalized_requests.append(finalized_row or request_row)


        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status='expired_pending_reactivation'
            AND delete_after IS NOT NULL
            AND delete_after > NOW()
            AND (
                last_expiry_reminder_at IS NULL
                OR last_expiry_reminder_at < NOW() - INTERVAL '1 day'
            )

        """)

        rows = cur.fetchall()


        for row in rows:

            request_row = row_to_commercial_request(row)

            cur.execute("""

                UPDATE commercial_requests
                SET last_expiry_reminder_at=NOW(),
                    updated_at=NOW()
                WHERE id=%s

            """, (request_row.get("id"),))

            reminder_requests.append(request_row)


    for request_row in newly_expired_requests:

        summary["newly_expired"] += 1
        user_id = request_row.get("user_id")


        if not user_id:

            summary["skipped_without_user"] += 1
            print(
                "Commercial expiry scheduler: solicitud sin user_id:",
                request_row.get("id")
            )
            continue


        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=expired_community_message(
                    format_retention_days_left(request_row.get("delete_after"))
                ),
                reply_markup=build_expired_trial_recovery_keyboard(
                    request_row.get("id")
                )
            )

            summary["expiry_notices_sent"] += 1

        except Exception as e:

            summary["send_errors"] += 1
            print("Error avisando comunidad caducada:", e)


    for request_row in reminder_requests:

        summary["reminders_due"] += 1
        user_id = request_row.get("user_id")


        if not user_id:

            summary["skipped_without_user"] += 1
            print(
                "Commercial expiry scheduler: recordatorio sin user_id:",
                request_row.get("id")
            )
            continue


        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Te quedan "
                    f"{format_retention_days_left(request_row.get('delete_after'))} días "
                    "para reactivar tu comunidad antes del borrado definitivo."
                ),
                reply_markup=build_expired_trial_reminder_keyboard(
                    request_row.get("id")
                )
            )

            summary["reminders_sent"] += 1

        except Exception as e:

            summary["send_errors"] += 1
            print("Error enviando recordatorio de comunidad caducada:", e)


    for request_row in finalized_requests:

        summary["finalized"] += 1

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "🗑 Comunidad marcada con borrado definitivo\n\n"
                    f"Solicitud #{request_row.get('id')}\n"
                    f"Usuario: {request_row.get('user_id')}\n"
                    "Se ocultó definitivamente y se limpió la configuración marketplace."
                )
            )

            summary["admin_notices_sent"] += 1

        except Exception as e:

            summary["send_errors"] += 1
            print("Error avisando borrado definitivo comercial:", e)

    active_count = sum(
        int(summary.get(key, 0) or 0)
        for key in (
            "newly_expired",
            "expiry_notices_sent",
            "reminders_due",
            "reminders_sent",
            "finalized",
            "admin_notices_sent",
            "send_errors"
        )
    )

    if active_count > 0:

        print(
            "Commercial expiry scheduler:",
            f"newly_expired={summary['newly_expired']}",
            f"expiry_notices_sent={summary['expiry_notices_sent']}",
            f"reminders_due={summary['reminders_due']}",
            f"reminders_sent={summary['reminders_sent']}",
            f"finalized={summary['finalized']}",
            f"admin_notices_sent={summary['admin_notices_sent']}",
            f"skipped_without_user={summary['skipped_without_user']}",
            f"send_errors={summary['send_errors']}"
        )

    return summary


async def expire_expired_commercial_trials(context):

    await process_expired_commercial_retention(context)


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


def marketplace_filter_title(filter_kind):

    if filter_kind in MARKETPLACE_FILTER_LABELS:

        return MARKETPLACE_FILTER_LABELS.get(filter_kind)


    if filter_kind.startswith("category:"):

        category = filter_kind.split(":", 1)[1]

        return f"📂 {MARKETPLACE_CATEGORY_LABELS.get(category, category)}"


    if filter_kind.startswith("tag:"):

        tag = filter_kind.split(":", 1)[1].replace("-", " ")

        return f"🏷 {tag}"


    return MARKETPLACE_FILTER_LABELS.get(MARKETPLACE_DEFAULT_FILTER)


def build_marketplace_filter_menu_keyboard(active_filter=MARKETPLACE_DEFAULT_FILTER):

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
        "📂 Categoría",
        callback_data="marketplace_filter_category"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏷 Tags",
        callback_data="marketplace_filter_tags"
    )])

    keyboard.append([InlineKeyboardButton(
        "🧹 Quitar filtros",
        callback_data="start_explore_groups"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a comunidades",
        callback_data=marketplace_filter_callback_data(active_filter)
        if active_filter
        else "start_explore_groups"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_marketplace_category_filter_keyboard():

    keyboard = [
        [InlineKeyboardButton(
            label,
            callback_data=f"marketplace_filter_category_{slug}"
        )]
        for label, slug in MARKETPLACE_CATEGORIES
    ]

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a filtros",
        callback_data="marketplace_filters"
    )])

    return InlineKeyboardMarkup(keyboard)


def marketplace_tag_callback_slug(tag):

    normalized = (tag or "").strip().lower().replace(" ", "-")
    allowed = set(string.ascii_lowercase + string.digits + "-_")

    return "".join(
        char
        for char in normalized
        if char in allowed
    )[:32]


def fetch_marketplace_filter_tags(limit=8):

    tags = []


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT g.tags
            FROM groups g
            WHERE g.is_active=TRUE
            AND g.telegram_group_id != 0
            AND COALESCE(g.public_visibility, 'start_home')='explore_only'
            AND g.tags IS NOT NULL
            AND g.tags != ''
            AND {marketplace_trial_visibility_filter()}
            LIMIT 80

        """)

        rows = cur.fetchall()


    seen = set()


    for row in rows:

        for raw_tag in (row[0] or "").split(","):

            tag = raw_tag.strip()
            slug = marketplace_tag_callback_slug(tag)


            if not tag or not slug or slug in seen:

                continue


            seen.add(slug)
            tags.append((tag, slug))


            if len(tags) >= limit:

                return tags


    return tags


def build_marketplace_tag_filter_keyboard():

    tags = fetch_marketplace_filter_tags()


    if not tags:

        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⬅️ Volver a filtros",
                callback_data="marketplace_filters"
            )]
        ])


    keyboard = [
        [InlineKeyboardButton(
            f"🏷 {tag}",
            callback_data=f"marketplace_filter_tag_{slug}"
        )]
        for tag, slug in tags
    ]

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a filtros",
        callback_data="marketplace_filters"
    )])

    return InlineKeyboardMarkup(keyboard)


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
        "🎟 Tengo código para esta comunidad",
        callback_data=f"group_user_promo_redeem_start_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=back_callback
    )])

    return InlineKeyboardMarkup(keyboard)


def build_marketplace_preview_keyboard(group, user_id=None):

    group_id = group.get("id")
    keyboard = []


    if user_id:

        is_favorite = is_group_favorite(user_id, group_id)

        keyboard.append([InlineKeyboardButton(
            favorite_button_text(is_favorite),
            callback_data=favorite_callback_data(group_id, is_favorite)
        )])


    if (group.get("preview_mode") or "manual") in ("dynamic", "hybrid"):

        keyboard.append([InlineKeyboardButton(
            "⚡ Ver últimos vídeos",
            callback_data=f"marketplace_dynamic_preview_{group_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "🔓 Entrar gratis" if group.get("is_free_group") else "💳 Ver acceso",
        callback_data=f"free_access_{group_id}" if group.get("is_free_group") else f"group_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "🎟 Canjear código de esta comunidad",
        callback_data=f"group_user_promo_redeem_start_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a comunidad",
        callback_data=f"marketplace_group_{group_id}"
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

    keyboard.append([InlineKeyboardButton(
        "🔎 Filtrar grupos",
        callback_data="marketplace_filters"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return keyboard


def row_to_marketplace_group(row):

    if not row:

        return None


    fields = [
        "id",
        "name",
        "is_free_group",
        "preview_text",
        "preview_file_id",
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
               g.preview_file_id,
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


def marketplace_filter_callback_data(filter_kind):

    if filter_kind.startswith("category:"):

        return f"marketplace_filter_category_{filter_kind.split(':', 1)[1]}"


    if filter_kind.startswith("tag:"):

        return f"marketplace_filter_tag_{filter_kind.split(':', 1)[1]}"


    if filter_kind in MARKETPLACE_FILTER_LABELS:

        return f"marketplace_filter_{filter_kind}"


    return "start_explore_groups"


def fetch_marketplace_groups(filter_kind="trending", limit=8):

    filters = [
        "g.is_active=TRUE",
        "g.telegram_group_id != 0",
        "COALESCE(g.public_visibility, 'start_home')='explore_only'",
        marketplace_trial_visibility_filter()
    ]
    params = []


    if filter_kind == "free":

        filters.append("COALESCE(g.is_free_group, FALSE)=TRUE")


    if filter_kind == "premium":

        filters.append("COALESCE(g.is_free_group, FALSE)=FALSE")


    if filter_kind.startswith("category:"):

        filters.append("COALESCE(g.category, '')=%s")
        params.append(filter_kind.split(":", 1)[1])


    if filter_kind.startswith("tag:"):

        tag_slug = filter_kind.split(":", 1)[1].replace("-", " ")
        filters.append("LOWER(COALESCE(g.tags, '')) LIKE %s")
        params.append(f"%{tag_slug.lower()}%")


    where_clause = " AND ".join(filters)
    order_clause = get_marketplace_order_clause(filter_kind)


    with conn.cursor() as cur:

        cur.execute(f"""

            {get_marketplace_group_select()}
            WHERE {where_clause}
            {order_clause}
            LIMIT %s

        """, tuple(params + [limit]))

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

    preview_mode = group.get("preview_mode") or "manual"
    base_text = (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"⭐ {format_marketplace_number(group.get('favorites_count'))} favoritos\n"
        f"👥 {format_marketplace_number(group.get('member_count'))} miembros\n"
        f"{format_marketplace_kind(group)}"
    )


    if preview_mode == "private":

        return base_text


    if preview_mode == "dynamic":

        return (
            f"{base_text}\n\n"
            "⚡ Preview dinámico activo."
        )


    return (
        f"{base_text}\n\n"
        f"📝 {group.get('preview_text') or 'Preview manual pendiente de configurar.'}"
    )


def build_marketplace_group_keyboard(group, user_id=None):

    group_id = group.get("id")
    is_free_group = group.get("is_free_group")
    preview_mode = group.get("preview_mode") or "manual"
    keyboard = []


    if preview_mode in ("manual", "hybrid"):

        keyboard.append([InlineKeyboardButton(
            "👁 Ver preview",
            callback_data=f"marketplace_preview_{group_id}"
        )])


    if preview_mode in ("dynamic", "hybrid"):

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
        "🎟 Canjear código de esta comunidad",
        callback_data=f"group_user_promo_redeem_start_{group_id}"
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


def fetch_dynamic_preview_videos(group_id, limit=3):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   video_file_id,
                   caption,
                   created_at,
                   message_id
            FROM group_preview_videos
            WHERE group_id=%s
            AND is_active=TRUE
            ORDER BY created_at DESC, id DESC
            LIMIT %s

        """, (
            group_id,
            limit
        ))

        rows = cur.fetchall()


    return [
        {
            "id": row[0],
            "video_file_id": row[1],
            "caption": row[2],
            "created_at": row[3],
            "message_id": row[4]
        }
        for row in rows
    ]


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


def format_dynamic_preview_video_caption(group, video, index, total):

    caption = video.get("caption") or "Vídeo publicado en la comunidad."


    if len(caption) > 700:

        caption = caption[:697] + "..."


    return (
        f"⚡ Preview dinámico {index}/{total}\n"
        f"🔥 {group.get('name') or 'Comunidad privada'}\n\n"
        f"{caption}"
    )


def build_dynamic_preview_access_keyboard(group, user_id=None):

    group_id = group.get("id")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔓 Entrar gratis" if group.get("is_free_group") else "💳 Comprar acceso",
            callback_data=f"free_access_{group_id}" if group.get("is_free_group") else f"group_{group_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver a comunidad",
            callback_data=f"marketplace_group_{group_id}"
        )]
    ])


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


    if preview_mode == "dynamic":

        return (
            f"🔥 {group.get('name') or 'Comunidad privada'}\n"
            f"📂 {format_marketplace_category(group)}\n"
            f"{stats_text}\n"
            f"{format_marketplace_kind(group)}\n\n"
            "⚡ Preview dinámico activo. Se mostrarán los últimos 3 vídeos publicados en la comunidad desde que el owner lo activó."
        )


    text = (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"{stats_text}\n"
        f"{format_marketplace_kind(group)}\n\n"
        f"📝 {group.get('preview_text') or 'Preview manual pendiente de configurar.'}"
    )


    if preview_mode == "hybrid":

        text += (
            "\n\n"
            "💎 Preview mixto activo: este teaser se combina con los últimos vídeos dinámicos disponibles."
        )


    if group.get("tags"):

        text += f"\n🏷 {group.get('tags')}"


    return text


async def send_marketplace_group_card(context, chat_id, group, user_id=None):

    caption = format_marketplace_group_caption(group)
    keyboard = build_marketplace_group_keyboard(group, user_id=user_id)
    preview_mode = group.get("preview_mode") or "manual"


    if preview_mode in ("manual", "hybrid") and group.get("preview_video_file_id"):

        message = await context.bot.send_video(
            chat_id=chat_id,
            video=group.get("preview_video_file_id"),
            caption=caption,
            reply_markup=keyboard
        )
        remember_preview_message(context, chat_id, message)

        return


    if preview_mode in ("manual", "hybrid") and group.get("preview_image_file_id"):

        message = await context.bot.send_photo(
            chat_id=chat_id,
            photo=group.get("preview_image_file_id"),
            caption=caption,
            reply_markup=keyboard
        )
        remember_preview_message(context, chat_id, message)

        return


    await send_clean_message(
        context,
        chat_id,
        caption,
        reply_markup=keyboard
    )


async def send_marketplace_preview(context, chat_id, group, user_id=None):

    caption = format_marketplace_preview_caption(group)
    keyboard = build_marketplace_preview_keyboard(
        group,
        user_id=user_id
    )
    preview_mode = group.get("preview_mode") or "manual"


    if preview_mode not in ("manual", "hybrid"):

        await send_clean_message(
            context,
            chat_id,
            "Este grupo todavía no tiene preview manual.",
            reply_markup=keyboard
        )

        return


    if preview_mode in ("manual", "hybrid") and group.get("preview_video_file_id"):

        message = await context.bot.send_video(
            chat_id=chat_id,
            video=group.get("preview_video_file_id"),
            caption=caption,
            reply_markup=keyboard
        )
        remember_preview_message(context, chat_id, message)

        return


    if preview_mode in ("manual", "hybrid") and group.get("preview_image_file_id"):

        message = await context.bot.send_photo(
            chat_id=chat_id,
            photo=group.get("preview_image_file_id"),
            caption=caption,
            reply_markup=keyboard
        )
        remember_preview_message(context, chat_id, message)

        return


    if group.get("preview_file_id"):

        try:

            message = await context.bot.send_photo(
                chat_id=chat_id,
                photo=group.get("preview_file_id"),
                caption=caption,
                reply_markup=keyboard
            )
            remember_preview_message(context, chat_id, message)

            return

        except Exception:

            try:

                message = await context.bot.send_video(
                    chat_id=chat_id,
                    video=group.get("preview_file_id"),
                    caption=caption,
                    reply_markup=keyboard
                )
                remember_preview_message(context, chat_id, message)

                return

            except Exception as e:

                print("Error mostrando preview legacy:", e)


    if not group.get("preview_text"):

        await send_clean_message(
            context,
            chat_id,
            "Este grupo todavía no tiene preview manual.",
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
    title = marketplace_filter_title(filter_kind)


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
            "📝 Preview fijo/manual",
            callback_data=f"creator_preview_mode_set_{request_id}_manual"
        )],
        [InlineKeyboardButton(
            "⚡ Preview dinámico (últimos 3 vídeos)",
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
            "⚙️ Ver explicación de modos",
            callback_data=f"creator_preview_mode_{request_id}"
        )],
        [InlineKeyboardButton(
            "🎬 Ver vídeos guardados",
            callback_data=f"creator_dynamic_preview_videos_{request_id}"
        )],
        [InlineKeyboardButton(
            "🗑 Borrar vídeo del preview",
            callback_data=f"creator_dynamic_preview_delete_{request_id}"
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


def build_group_preview_mode_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📝 Preview manual",
            callback_data="edit_group_preview_mode_manual"
        )],
        [InlineKeyboardButton(
            "⚡ Preview dinámico",
            callback_data="edit_group_preview_mode_dynamic"
        )],
        [InlineKeyboardButton(
            "💎 Preview mixto",
            callback_data="edit_group_preview_mode_hybrid"
        )],
        [InlineKeyboardButton(
            "🔒 Sin preview público",
            callback_data="edit_group_preview_mode_private"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="edit_group_back"
        )]
    ])


def preview_mode_selection_text():

    return (
        "¿Qué tipo de preview quieres para este grupo?\n\n"
        "📝 Manual:\n"
        "Subes una imagen o vídeo fijo que verán los usuarios antes de entrar.\n\n"
        "⚡ Dinámico:\n"
        "El bot mostrará los últimos 3 vídeos publicados en el grupo desde que actives este modo.\n\n"
        "💎 Mixto:\n"
        "Muestra primero el preview manual y además permite ver los últimos vídeos dinámicos.\n\n"
        "🔒 Sin preview:\n"
        "No se mostrará contenido previo, solo la ficha del grupo."
    )


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
        "¿Qué tipo de preview quieres mostrar?\n\n"
        "📝 Preview fijo/manual: texto, imagen, vídeo teaser, categoría y tags.\n\n"
        "⚡ Preview dinámico: muestra los últimos 3 vídeos publicados después de activarlo. El bot no descarga vídeos; solo guarda el file_id de Telegram.\n\n"
        "💎 Preview mixto: combina tu teaser manual con los últimos vídeos dinámicos si existen.\n\n"
        "🔒 Sin preview público: muestra una ficha mínima sin enseñar contenido."
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


def get_owner_groups_summary(user_id):

    if not user_id:

        return 0, "Sin grupos"


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT g.name
                FROM admins a
                JOIN groups g
                ON g.id=a.group_id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                ORDER BY g.name ASC

            """, (user_id,))

            names = [
                row[0] or "Sin nombre"
                for row in cur.fetchall()
            ]

    except Exception as e:

        print("Error cargando grupos del propietario:", e)

        names = []


    if not names:

        return 0, "Sin grupos"


    shown = ", ".join(names[:3])

    if len(names) > 3:

        shown += f" +{len(names) - 3} más"


    return len(names), shown


def build_owner_groups_detail_text(request_row):

    user_id = request_row.get("user_id") if request_row else None

    if not user_id:

        return "🏪 Grupos del propietario\n\nNo hay usuario asociado a esta solicitud."


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT g.id, g.name, g.telegram_group_id, COALESCE(g.is_active, TRUE)
                FROM groups g
                JOIN admins a
                ON a.group_id = g.id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                ORDER BY g.name ASC

            """, (user_id,))

            rows = cur.fetchall()

    except Exception as e:

        print("Error cargando detalle de grupos del propietario:", e)

        rows = []


    if not rows:

        return "🏪 Grupos del propietario\n\nEste propietario todavía no tiene grupos vinculados."


    lines = [
        "🏪 Grupos del propietario",
        "",
        format_owner_request_card(request_row)
    ]


    for group_id, name, telegram_group_id, is_active in rows:

        lines.append(
            "\n"
            f"Grupo: {name or 'Sin nombre'}\n"
            f"ID interno: {group_id}\n"
            f"Telegram ID: {telegram_group_id or '-'}\n"
            f"Estado: {'activo' if is_active else 'inactivo'}"
        )


    return "\n".join(lines)


def format_owner_request_card(request_row):

    username = request_row.get("username") or "Sin username"

    if username != "Sin username" and not username.startswith("@"):

        username = f"@{username}"


    first_name = request_row.get("first_name") or "Sin nombre disponible"
    user_id = request_row.get("user_id")
    status = request_row.get("status") or "-"
    max_groups, _quota_source = get_creator_group_quota_source(user_id, request_row)
    used_groups, group_names = get_owner_groups_summary(user_id)
    trial_until = request_row.get("trial_ends_at")
    subscription_until = request_row.get("commercial_subscription_until")
    last_activity = (
        request_row.get("last_interaction_at")
        or request_row.get("updated_at")
        or request_row.get("created_at")
    )

    trial_text = "inactivo"
    if status == "trial_active":
        trial_text = f"activo hasta {format_commercial_datetime(trial_until)}"

    commercial_text = "activo" if status == "active" else "inactivo"
    if subscription_until:
        commercial_text = f"{commercial_text} hasta {format_commercial_datetime(subscription_until)}"

    return (
        f"👤 Nombre: {first_name} {username}\n"
        f"🆔 Usuario: {user_id or '-'}\n"
        f"📌 Estado: {format_commercial_request_status(status)}\n"
        f"📦 Cupo: {used_groups}/{max_groups}\n"
        f"🧪 Trial: {trial_text}\n"
        f"💳 Comercial: {commercial_text}\n"
        f"🏪 Grupos: {used_groups} · {group_names}\n"
        f"🕒 Última actividad: {format_commercial_datetime(last_activity)}"
    )


def format_owner_request_button_label(request_row, prefix="👁 Ver"):

    first_name = request_row.get("first_name") or "Sin nombre"
    username = request_row.get("username") or "Sin username"

    if username != "Sin username" and not username.startswith("@"):

        username = f"@{username}"


    return (
        f"{prefix} · {first_name} {username} "
        f"#{request_row.get('id')}"
    )[:64]


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


def fetch_archived_commercial_requests():

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status IN ('archived', 'closed')
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 20

        """)

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def fetch_commercial_requests_by_statuses(statuses, limit=20):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status = ANY(%s)
            ORDER BY updated_at DESC, created_at DESC
            LIMIT %s

        """, (statuses, limit))

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def build_commercial_status_list_text(title, requests):

    if not requests:

        return f"{title}\n\nNo hay solicitudes en esta vista."


    lines = [title]


    for request_row in requests:

        lines.append("\n" + format_owner_request_card(request_row))


    return "\n".join(lines)


def build_commercial_status_list_keyboard(requests, back_callback="admin_owners_panel"):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "👁 Ver estado"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton("🧑‍💼 Propietarios", callback_data=back_callback)
    ])

    keyboard.append([
        InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")
    ])

    return keyboard


def fetch_commercial_request(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE id=%s

            LIMIT 1

        """, (request_id,))

        row = cur.fetchone()


    request_row = row_to_commercial_request(row)


    if request_row:

        sync_commercial_creator_profile_from_request(
            request_row.get("user_id")
        )


    return request_row


def archive_commercial_request(request_id, archived_by):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='archived',
                reviewed_by=COALESCE(reviewed_by, %s),
                reviewed_at=COALESCE(reviewed_at, NOW()),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            archived_by,
            request_id
        ))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def reopen_archived_commercial_request(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='setup_ready',
                updated_at=NOW()
            WHERE id=%s
            AND status IN ('archived', 'closed')
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def create_commercial_request_message(request_id, sender_type, sender_id, message_text):

    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO commercial_request_messages
            (
                commercial_request_id,
                sender_type,
                sender_id,
                message_text
            )
            VALUES (%s, %s, %s, %s)
            RETURNING {", ".join(COMMERCIAL_REQUEST_MESSAGE_FIELDS)}

        """, (
            request_id,
            sender_type,
            sender_id,
            message_text
        ))

        row = cur.fetchone()


    return row_to_commercial_request_message(row)


def update_commercial_request_last_interaction(request_id, user):

    if not request_id or not user:

        return


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE commercial_requests
            SET last_interaction_user_id=%s,
                last_interaction_username=%s,
                last_interaction_first_name=%s,
                last_interaction_at=NOW(),
                updated_at=NOW()
            WHERE id=%s

        """, (
            user.id,
            user.username,
            user.first_name,
            request_id
        ))


def fetch_commercial_request_messages(request_id, limit=10):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_MESSAGE_FIELDS)}
            FROM commercial_request_messages
            WHERE commercial_request_id=%s
            ORDER BY created_at DESC, id DESC
            LIMIT %s

        """, (
            request_id,
            limit
        ))

        rows = cur.fetchall()


    messages = [
        row_to_commercial_request_message(row)
        for row in rows
    ]

    return list(reversed(messages))


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
        )],

        [InlineKeyboardButton(
            "📍 Restricción por ubicación",
            callback_data=f"creator_setup_location_gate_{request_id}"
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

    else:

        location_enabled, region_label = get_group_location_gate_display(group_id)
        location_status = "Activada" if location_enabled else "Desactivada"

        text += (
            "\n\n"
            f"📍 Ubicación: {location_status}\n"
            f"Región permitida: {region_label}"
        )


    return text


def start_creator_setup_state(context, request_id, action):

    clear_creator_onboarding_context(context)

    waiting_states = {
        "group": "creator_setup_waiting_group_reference",
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


def clear_creator_onboarding_context(context):

    for key in (
        "commercial_form",
        "commercial_form_type",
        "commercial_form_step",
        "commercial_form_data",
        "commercial_form_waiting",
        "creator_setup",
        "creator_setup_request_id",
        "creator_setup_action",
        "creator_setup_step",
        "creator_setup_data",
        "creator_setup_waiting",
        "marketplace_preview_media",
        "marketplace_preview_request_id",
        "marketplace_preview_media_type",
        "marketplace_preview_target_mode"
    ):

        context.user_data.pop(key, None)


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
    location_enabled, region_label = get_group_location_gate_display(group_id)
    location_status = "Activada" if location_enabled else "Desactivada"
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
        f"📍 Ubicación: {location_status}\n"
        f"Región permitida: {region_label}\n"
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
        "🕓 Solicitudes pendientes\n\n"
        "Gestiona aquí a los dueños de comunidades: solicitudes, pruebas, cupos, grupos y estado comercial."
    ]


    for request_row in requests:

        lines.append(
            "\n"
            f"{format_owner_request_card(request_row)}\n"
            f"Tipo: {format_commercial_request_type(request_row.get('request_type'))}\n"
            f"Solicitud: {get_commercial_request_title(request_row)}\n"
            f"Contacto: {request_row.get('contact_text') or '-'}"
        )


    return "\n".join(lines)


def build_commercial_requests_keyboard(requests):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "📄 Ver detalle"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "📁 Solicitudes archivadas",
            callback_data="admin_commercial_archived_requests"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_archived_commercial_requests_text(requests):

    if not requests:

        return (
            "📁 Solicitudes archivadas\n\n"
            "No hay solicitudes archivadas."
        )


    lines = [
        "📁 Archivados\n\n"
        "Solicitudes finalizadas o cerradas sin borrar sus datos."
    ]


    for request_row in requests:

        lines.append("\n" + format_owner_request_card(request_row))


    return "\n".join(lines)


def build_archived_commercial_requests_keyboard(requests):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "👁 Ver estado"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_request_detail_text(request_row):

    username = request_row.get("username") or "-"
    profile_quota, quota_source = get_creator_group_quota_source(
        request_row.get("user_id"),
        request_row
    )

    if username != "-" and not username.startswith("@"):

        username = f"@{username}"


    return (
        "📩 Solicitud comercial\n\n"
        f"{format_owner_request_card(request_row)}\n\n"
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
        f"Grupo vinculado: {request_row.get('approved_group_id') or '-'}\n"
        f"Telegram group ID: {request_row.get('approved_telegram_group_id') or '-'}\n"
        f"Ubicación pública solicitada: {format_public_visibility(request_row.get('requested_public_visibility'))}\n"
        f"Estado configuración creador: {request_row.get('creator_setup_status') or '-'}\n"
        f"Preview creador: {request_row.get('creator_preview_text') or '-'}\n"
        f"Cupo actual del creator: {profile_quota}\n"
        f"Cupo de esta solicitud: {request_row.get('max_groups_allowed') or 1}\n"
        f"Fuente de cupo: {quota_source}\n"
        f"Último user_id interacción: {request_row.get('last_interaction_user_id') or '-'}\n"
        f"Último username interacción: {request_row.get('last_interaction_username') or '-'}\n"
        f"Último nombre interacción: {request_row.get('last_interaction_first_name') or '-'}\n"
        f"Última interacción: {format_commercial_datetime(request_row.get('last_interaction_at'))}\n"
        f"Plan comercial: {request_row.get('selected_commercial_plan_id') or '-'}\n"
        f"Estado suscripción comercial: {request_row.get('commercial_subscription_status') or '-'}\n"
        f"Suscripción comercial hasta: {format_commercial_datetime(request_row.get('commercial_subscription_until'))}"
    )


def build_commercial_contact_button(request_row):

    return InlineKeyboardButton(
        "💬 Hablar con solicitante",
        callback_data=f"admin_commercial_chat_{request_row.get('id')}"
    )


def build_commercial_advanced_review_keyboard(request_row):

    request_id = request_row.get("id")
    keyboard = []
    contact_button = build_commercial_contact_button(request_row)


    keyboard.append([contact_button])


    keyboard.append([
        InlineKeyboardButton(
            "📄 Ver detalle completo",
            callback_data=f"admin_commercial_status_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🏪 Ver sus grupos",
            callback_data=f"admin_commercial_owner_groups_{request_id}"
        )
    ])

    if not is_commercial_request_archived(request_row):

        keyboard.append([
            InlineKeyboardButton(
                "🔢 Cambiar cupo",
                callback_data=f"admin_commercial_group_limit_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "🗄 Finalizar solicitud",
                callback_data=f"admin_commercial_archive_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "📝 Añadir nota interna",
                callback_data=f"admin_commercial_internal_note_{request_id}"
            )
        ])

    else:

        keyboard.append([
            InlineKeyboardButton(
                "📁 Archivada",
                callback_data=f"admin_commercial_status_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "♻️ Reabrir solicitud",
                callback_data=f"admin_commercial_reopen_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_archive_confirm_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Confirmar archivo",
            callback_data=f"admin_commercial_archive_confirm_{request_id}"
        )],
        [InlineKeyboardButton(
            "❌ Cancelar",
            callback_data=f"admin_commercial_archive_cancel_{request_id}"
        )]
    ])


def build_commercial_pending_review_keyboard(request_row):

    request_id = request_row.get("id")
    request_type = request_row.get("request_type")
    keyboard = [
        [build_commercial_contact_button(request_row)]
    ]

    keyboard.append([
        InlineKeyboardButton(
            "📄 Ver detalle completo",
            callback_data=f"admin_commercial_status_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🏪 Ver sus grupos",
            callback_data=f"admin_commercial_owner_groups_{request_id}"
        )
    ])


    if request_type == "shared_trial":

        keyboard.append([
            InlineKeyboardButton(
                "✅ Aprobar prueba",
                callback_data=f"admin_commercial_approve_trial_{request_id}"
            )
        ])

    elif request_type == "custom_bot":

        keyboard.append([
            InlineKeyboardButton(
                "✅ Aprobar personalizada",
                callback_data=f"admin_commercial_approve_custom_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "❌ Rechazar",
            callback_data=f"admin_commercial_reject_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "📦 Cambiar cupo",
            callback_data=f"admin_commercial_group_limit_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "📝 Añadir nota interna",
            callback_data=f"admin_commercial_internal_note_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_review_keyboard(request_row):

    if is_commercial_request_advanced(request_row):

        return build_commercial_advanced_review_keyboard(request_row)


    return build_commercial_pending_review_keyboard(request_row)


def build_commercial_request_chat_text(request_row, messages):

    request_id = request_row.get("id")
    title = get_commercial_request_title(request_row)


    lines = [
        "💬 Chat de solicitud comercial",
        "",
        f"Solicitud: #{request_id}",
        f"Solicitante: {request_row.get('user_id') or '-'}",
        f"Proyecto: {title}",
        ""
    ]


    if not messages:

        lines.append("Todavía no hay mensajes en esta conversación.")

    else:

        lines.append("Historial reciente:")


        for message in messages:

            sender_label = (
                "Admin"
                if message.get("sender_type") == "admin"
                else "Solicitante"
            )
            created_at = format_commercial_datetime(message.get("created_at"))
            text = (message.get("message_text") or "").strip()

            lines.append(
                "\n"
                f"{sender_label} · {created_at}\n"
                f"{text}"
            )


    return "\n".join(lines)


def build_admin_commercial_request_chat_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "✍️ Responder",
            callback_data=f"admin_commercial_reply_{request_id}"
        )],

        [InlineKeyboardButton(
            "📩 Ver solicitud",
            callback_data=f"admin_commercial_review_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_commercial_requests"
        )]

    ])


def build_user_commercial_request_chat_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "Responder solicitud",
            callback_data=f"commercial_request_chat_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def build_commercial_group_limit_text(request_row):

    profile_quota, quota_source = get_creator_group_quota_source(
        request_row.get("user_id"),
        request_row
    )

    return (
        "🔢 Cupo de grupos\n\n"
        f"Solicitud: #{request_row.get('id')}\n"
        f"Creador: {request_row.get('user_id') or '-'}\n"
        f"Cupo actual del creator: {profile_quota}\n"
        f"Cupo de esta solicitud: {request_row.get('max_groups_allowed') or 1}\n"
        f"Fuente: {quota_source}\n\n"
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


    request_row = row_to_commercial_request(row)


    if request_row:

        set_creator_group_quota(
            request_row.get("user_id"),
            max_groups_allowed,
            request_row.get("status")
        )

        with conn.cursor() as cur:

            cur.execute(f"""

                UPDATE commercial_requests
                SET max_groups_allowed=%s,
                    updated_at=NOW()
                WHERE user_id=%s
                RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

            """, (
                max_groups_allowed,
                request_row.get("user_id")
            ))


    return request_row


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


    request_row = row_to_commercial_request(row)


    if request_row:

        sync_commercial_creator_profile_from_request(
            request_row.get("user_id")
        )


    return request_row


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


    sync_commercial_creator_profile_from_request(
        request_row.get("user_id")
    )

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


    request_row = row_to_commercial_request(row)


    if request_row:

        sync_commercial_creator_profile_from_request(
            request_row.get("user_id")
        )


    return request_row


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


    with conn.cursor() as cur:

        return finalize_expired_commercial_request(cur, request_row)


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


async def reply_duplicate_commercial_approval(query, request_id):

    await query.message.reply_text(
        DUPLICATE_COMMERCIAL_APPROVAL_MESSAGE,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "👁 Ver estado",
                callback_data=f"admin_commercial_review_{request_id}"
            )]
        ])
    )


async def handle_admin_trial_visibility_approval(
    context,
    query,
    user_id,
    request_id,
    public_visibility
):

    existing_request = fetch_commercial_request(request_id)


    if not existing_request:

        await query.message.reply_text(
            "❌ Solicitud comercial no encontrada."
        )

        return


    if is_commercial_request_advanced(existing_request):

        await reply_duplicate_commercial_approval(query, request_id)

        return


    request_row = update_commercial_request_trial_visibility(
        request_id,
        user_id,
        public_visibility
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
        f"Ubicación inicial: {format_public_visibility(public_visibility)}.\n"
        "El creador ya recibió el flujo para terminar la configuración.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="admin_commercial_requests"
            )]
        ])
    )


def clear_commercial_request_chat_state(context):

    context.user_data.pop("replying_commercial_request", None)
    context.user_data.pop("replying_commercial_request_as", None)


def start_commercial_request_chat_reply(context, request_id, sender_type):

    context.user_data["replying_commercial_request"] = request_id
    context.user_data["replying_commercial_request_as"] = sender_type
    context.user_data["support_mode"] = False
    context.user_data["support_lookup_mode"] = False
    context.user_data.pop("replying_support_ticket", None)


async def receive_commercial_request_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:

        return


    request_id = context.user_data.get("replying_commercial_request")
    sender_type = context.user_data.get("replying_commercial_request_as")
    text = update.message.text.strip()
    user = update.effective_user
    message_user = update.message.from_user
    request_row = fetch_commercial_request(request_id)

    print(
        "commercial_request_chat_message:",
        f"request_id={request_id or '-'}",
        f"sender_type={sender_type or '-'}",
        f"effective_user.id={user.id if user else '-'}",
        f"message.from_user.id={message_user.id if message_user else '-'}",
        f"username={user.username if user and user.username else '-'}",
        f"first_name={user.first_name if user and user.first_name else '-'}",
        f"commercial_requests.user_id={request_row.get('user_id') if request_row else '-'}"
    )


    if not request_row:

        clear_commercial_request_chat_state(context)

        await update.message.reply_text(
            "❌ Solicitud comercial no encontrada."
        )

        return


    if sender_type == "admin":

        if not is_super_admin(user.id):

            clear_commercial_request_chat_state(context)

            await update.message.reply_text(
                "⛔ No tienes permisos para responder esta solicitud."
            )

            return


        create_commercial_request_message(
            request_id,
            "admin",
            user.id,
            text
        )

        update_commercial_request_last_interaction(
            request_id,
            user
        )

        clear_commercial_request_chat_state(context)

        await notify_commercial_request_user(
            context,
            request_row,
            "💬 Mensaje sobre tu solicitud comercial:\n\n"
            f"{text}",
            reply_markup=build_user_commercial_request_chat_keyboard(request_id)
        )

        await update.message.reply_text(
            "✅ Mensaje enviado al solicitante.",
            reply_markup=build_admin_commercial_request_chat_keyboard(request_id)
        )

        return


    if sender_type == "user":

        if int(request_row.get("user_id") or 0) != int(user.id):

            clear_commercial_request_chat_state(context)

            await update.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        create_commercial_request_message(
            request_id,
            "user",
            user.id,
            text
        )

        update_commercial_request_last_interaction(
            request_id,
            user
        )

        clear_commercial_request_chat_state(context)

        await notify_commercial_admin(
            context,
            "💬 Respuesta sobre solicitud comercial\n\n"
            f"Solicitud: #{request_id}\n"
            f"Usuario: {user.id}\n\n"
            f"{text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💬 Abrir conversación",
                    callback_data=f"admin_commercial_chat_{request_id}"
                )],
                [InlineKeyboardButton(
                    "👁 Ver solicitud",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await update.message.reply_text(
            "✅ Respuesta enviada sobre tu solicitud comercial.",
            reply_markup=build_user_commercial_request_chat_keyboard(request_id)
        )

        return


    clear_commercial_request_chat_state(context)

    await update.message.reply_text(
        "⚠️ No se pudo continuar esta conversación comercial."
    )


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

    print(
        "support_ticket_get_or_create:",
        f"effective_user.id={user_id or '-'}",
        f"username={username or '-'}",
        f"first_name={first_name or '-'}"
    )


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


def build_support_ticket_keyboard(ticket):

    if isinstance(ticket, dict):

        ticket_id = ticket.get("id")
        ticket_status = ticket.get("status")

    else:

        ticket_id = ticket
        ticket_status = None


    if ticket_status == "closed":

        return [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="admin_support_tickets"
            )]

        ]


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


def build_support_user_navigation_keyboard():

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "🛟 Abrir soporte",
            callback_data="public_support"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def build_support_closed_ticket_keyboard():

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "🆕 Crear nuevo ticket",
            callback_data="public_support"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def clear_support_user_state(context):

    context.user_data["support_mode"] = False
    context.user_data["support_lookup_mode"] = False
    context.user_data.pop("replying_support_ticket", None)
    context.user_data.pop("support_replying_ticket", None)


def log_support_ticket_privacy_attempt(ticket_id, requester_user_id, owner_user_id=None):

    print(
        "Intento de acceso indebido a soporte:",
        f"ticket_id={ticket_id}",
        f"requester_user_id={requester_user_id}",
        f"owner_user_id={owner_user_id or '-'}"
    )


def support_ticket_belongs_to_user(ticket, user_id):

    try:

        return int(ticket.get("user_id")) == int(user_id)

    except Exception:

        return False


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
            "❓ Ayuda",
            callback_data="admin_help_support_tickets"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_global_panel"
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


def build_support_photo_admin_caption(ticket, user, original_caption, context_text=None):

    username = user.username if user and user.username else "-"

    if username != "-" and not username.startswith("@"):

        username = f"@{username}"


    caption_parts = [
        "🛟 Captura recibida en soporte",
        "",
        f"Ticket: #{ticket.get('id')}",
        f"Usuario ID: {user.id if user else '-'}",
        f"Nombre: {user.first_name if user and user.first_name else '-'}",
        f"Username: {username}"
    ]


    if context_text:

        caption_parts.extend([
            "",
            f"Contexto: {context_text}"
        ])


    caption_parts.extend([
        "",
        "Mensaje del usuario:",
        original_caption or "Sin caption."
    ])

    return "\n".join(caption_parts)[:1024]


async def notify_support_admin_photo(context, ticket, user, photo_file_id, original_caption=None):

    context_text = (
        context.user_data.get("support_context")
        or context.user_data.get("support_help_context")
        or context.user_data.get("help_context")
    )


    try:

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file_id,
            caption=build_support_photo_admin_caption(
                ticket,
                user,
                original_caption,
                context_text=context_text
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

        print("Error avisando soporte admin con foto:", e)

        return False


async def handle_user_support_message(update, context, text):

    user = update.effective_user
    message_user = update.message.from_user if update.message else None

    print(
        "support_message_user:",
        f"effective_user.id={user.id if user else '-'}",
        f"message.from_user.id={message_user.id if message_user else '-'}",
        f"username={user.username if user and user.username else '-'}",
        f"first_name={user.first_name if user and user.first_name else '-'}"
    )

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

    log_event(
        "support_ticket_created",
        category="support",
        severity="info",
        scope="global",
        actor_user_id=user.id,
        target_user_id=user.id,
        message="Ticket o mensaje de soporte recibido durante beta.",
        metadata={
            "ticket_id": ticket.get("id"),
            "status": ticket.get("status")
        }
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


async def handle_user_support_photo(update, context):

    user = update.effective_user
    message = update.message


    if not message or not message.photo:

        return


    photo_file_id = message.photo[-1].file_id
    original_caption = (message.caption or "").strip()
    ticket = get_or_create_support_ticket(user)
    stored_text = "📷 Captura recibida."


    if original_caption:

        stored_text += f"\nCaption: {original_caption}"


    create_support_message(
        ticket.get("id"),
        "user",
        user.id,
        stored_text
    )

    update_support_ticket_status(
        ticket.get("id"),
        "open"
    )

    await notify_support_admin_photo(
        context,
        ticket,
        user,
        photo_file_id,
        original_caption=original_caption
    )

    log_event(
        "support_ticket_created",
        category="support",
        severity="info",
        scope="global",
        actor_user_id=user.id,
        target_user_id=user.id,
        message="Captura de soporte recibida durante beta.",
        metadata={
            "ticket_id": ticket.get("id"),
            "has_caption": bool(original_caption),
            "content_type": "photo"
        }
    )

    await message.reply_text(
        "✅ Captura recibida. El soporte la revisará lo antes posible.",
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

        context.user_data["support_lookup_mode"] = False

        await update.message.reply_text(
            "⚠️ No encontré ese ticket.",
            reply_markup=build_support_user_navigation_keyboard()
        )

        return


    ticket = fetch_support_ticket(ticket_id)

    context.user_data["support_lookup_mode"] = False


    if not ticket:

        await update.message.reply_text(
            "⚠️ No encontré ese ticket.",
            reply_markup=build_support_user_navigation_keyboard()
        )

        return


    if not support_ticket_belongs_to_user(ticket, user_id):

        log_support_ticket_privacy_attempt(
            ticket_id,
            user_id,
            ticket.get("user_id")
        )

        await update.message.reply_text(
            "⛔ No puedes acceder a este ticket.",
            reply_markup=build_support_user_navigation_keyboard()
        )

        return


    if ticket.get("status") == "closed":

        await update.message.reply_text(
            f"{build_support_ticket_detail_text(ticket)}\n\n"
            "📁 Este ticket está cerrado.",
            reply_markup=build_support_closed_ticket_keyboard()
        )

        return


    await update.message.reply_text(
        build_support_ticket_detail_text(ticket),
        reply_markup=build_support_user_navigation_keyboard()
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


    if ticket.get("status") == "closed":

        context.user_data.pop("replying_support_ticket", None)

        await update.message.reply_text(
            "📁 Este ticket está cerrado.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🛟 Tickets abiertos",
                    callback_data="admin_support_tickets"
                )]
            ])
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

    if not update.message:

        return


    if update.message.photo and context.user_data.get("support_mode"):

        await handle_user_support_photo(
            update,
            context
        )

        return


    if not update.message.text:

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


async def create_free_access_for_user(context, chat_id, telegram_user, group_id):

    user_id = telegram_user.id


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

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Comunidad gratuita no encontrada o no disponible.",
                    reply_markup=build_group_recovery_keyboard(group_id)
                )

                return


            group_name, telegram_group_id = group_row

            increment_community_stat(group_id, "access_clicks")

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )
                AND is_active=TRUE

            """, (
                user_id,
                group_id,
                telegram_group_id,
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

            log_event(
                "free_access_invite_link_error",
                category="access",
                severity="warning",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="No se pudo crear enlace de acceso gratuito."
            )

            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Error creando acceso.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        username = telegram_user.username
        first_name = telegram_user.first_name


        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (
                user_id,
                group_id,
                telegram_group_id,
                telegram_group_id
            ))

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, telegram_group_id, invite_link, is_active)
                VALUES (%s, %s, %s, %s, TRUE)

            """, (
                user_id,
                group_id,
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

        log_event(
            "free_access_error",
            category="access",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error concediendo acceso gratuito.",
            metadata={
                "error": str(e)
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Error creando acceso gratuito.",
            reply_markup=build_group_recovery_keyboard(group_id)
        )

        return


    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ Acceso gratuito concedido.\n\n"
            "Este enlace es personal y de un solo uso.\n"
            "No lo compartas.\n\n"
            f"{link}"
        ),
        reply_markup=ReplyKeyboardRemove()
    )


async def create_checkout_for_user(context, chat_id, user_id, group_id, price_id):

    if not is_stripe_payments_enabled():

        await context.bot.send_message(
            chat_id=chat_id,
            text="Este método de pago aún no está disponible.",
            reply_markup=build_group_recovery_keyboard(group_id)
        )

        return


    try:

        response = requests.post(

            f"{SERVER_URL}/create-checkout-session",

            json={

                "telegram_id": user_id,
                "plan": price_id,
                "group_id": group_id

            }

        )

        payment_url = response.json()["url"]


        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💳 Paga aquí:\n{payment_url}",
            reply_markup=ReplyKeyboardRemove()
        )

    except Exception as e:

        log_event(
            "checkout_creation_error",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error creando sesión de pago.",
            metadata={
                "price_id": price_id,
                "error": str(e)
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Error creando pago",
            reply_markup=build_group_recovery_keyboard(
                group_id,
                retry_callback=price_id if is_stripe_checkout_callback(price_id) else None
            )
        )


async def receive_location_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("location_gate_pending"):

        return


    chat_id = update.effective_chat.id
    user_id = update.effective_user.id


    if not update.message or not update.message.location:

        await context.bot.send_message(
            chat_id=chat_id,
            text="📍 Para continuar debes pulsar el botón de ubicación.",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(
                    "📍 Enviar ubicación",
                    request_location=True
                )]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )

        return


    group_id = context.user_data.get("location_gate_group_id")
    action = context.user_data.get("location_gate_action")
    price_id = context.user_data.get("location_gate_price_id")
    location = update.message.location
    resolved_region = resolve_location_region(
        location.latitude,
        location.longitude
    )
    _enabled, allowed_region, region_type = get_group_location_gate(group_id)
    region_label = format_allowed_region(region_type, allowed_region)
    is_allowed = location_matches_allowed_region(
        resolved_region,
        region_type,
        allowed_region
    )


    if not is_allowed:

        try:

            save_group_location_verification(
                group_id,
                user_id,
                resolved_region,
                "rejected"
            )

        except Exception as e:

            print("Error guardando verificación de ubicación rechazada:", e)


        log_event(
            "location_denied",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Usuario rechazado por restricción de ubicación.",
            metadata={
                "allowed_region": region_label,
                "country": resolved_region.get("country"),
                "region": resolved_region.get("spanish_autonomous_community"),
                "province": resolved_region.get("province")
            }
        )

        clear_location_gate_state(context)

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⛔ Esta comunidad solo admite usuarios verificados en: {region_label}.",
            reply_markup=ReplyKeyboardRemove()
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="Puedes contactar con soporte si crees que es un error.",
            reply_markup=build_location_denied_keyboard()
        )

        return


    try:

        save_group_location_verification(
            group_id,
            user_id,
            resolved_region,
            "verified"
        )

    except Exception as e:

        print("Error guardando verificación de ubicación:", e)


    clear_location_gate_state(context)


    if action == "free_access":

        await create_free_access_for_user(
            context,
            chat_id,
            update.effective_user,
            group_id
        )

        return


    if action == "checkout":

        await create_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return


    await context.bot.send_message(
        chat_id=chat_id,
        text="✅ Ubicación verificada.",
        reply_markup=ReplyKeyboardRemove()
    )


# =========================
# BOTONES
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    user_id = query.from_user.id


    callback_chat_id = getattr(query.message, "chat_id", None) if query.message else None

    try:

        is_private_callback_chat = callback_chat_id and int(callback_chat_id) > 0

    except Exception:

        is_private_callback_chat = False


    if is_private_callback_chat:

        await delete_pending_preview_messages(
            context,
            callback_chat_id
        )


    if data.startswith("retry_creator_group_verification_"):

        try:

            telegram_group_id = int(
                data.replace("retry_creator_group_verification_", "", 1)
            )

        except Exception:

            await query.message.reply_text(
                "❌ Grupo no válido para reintentar verificación."
            )

            return


        try:

            chat = await context.bot.get_chat(telegram_group_id)
            group_name = chat.title or str(telegram_group_id)

        except Exception as e:

            print("Error obteniendo grupo para reintentar verificación:", e)
            group_name = str(telegram_group_id)


        asyncio.create_task(
            verificar_admin_despues(
                telegram_group_id,
                group_name,
                context.bot.id,
                context,
                user_id,
                query.from_user.username,
                query.from_user.first_name
            )
        )

        await query.message.reply_text(
            "🔁 Reintentando verificación.\n\n"
            "Comprobaré de nuevo si el bot ya tiene permisos de administrador."
        )

        return


    if data.startswith("confirm_creator_group_link_"):

        try:

            pending_id = int(data.replace("confirm_creator_group_link_", "", 1))

        except Exception:

            await query.message.reply_text(
                "❌ Solicitud de vinculación no válida."
            )

            return


        result = confirm_creator_group_link_request(
            pending_id,
            user_id
        )

        status = result.get("status")

        print(
            "creator_group_link_confirm_callback:",
            f"pending_id={pending_id}",
            f"query.from_user.id={query.from_user.id if query.from_user else '-'}",
            f"username={query.from_user.username if query.from_user and query.from_user.username else '-'}",
            f"first_name={query.from_user.first_name if query.from_user and query.from_user.first_name else '-'}",
            f"status={status}"
        )


        if status == "confirmed":

            await query.message.reply_text(
                "✅ Grupo vinculado correctamente.\n\n"
                "El panel de gestión se activó para esta comunidad."
            )

            await query.message.reply_text(
                "📦 Puedes continuar configurando tu comunidad desde el panel.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📦 Configurar comunidad",
                        callback_data=f"configure_community_{result.get('request_id')}"
                    )],
                    [InlineKeyboardButton(
                        "🏠 Inicio",
                        callback_data="public_back_start"
                    )]
                ])
            )

            try:

                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        "✅ Grupo vinculado por creator\n\n"
                        f"Grupo: {result.get('group_name')}\n"
                        f"Telegram ID: {result.get('telegram_group_id')}\n"
                        f"ID interno: {result.get('group_id')}\n"
                        f"Usuario: {user_id}\n"
                        f"Solicitud: #{result.get('request_id')}"
                    )
                )

            except Exception as e:

                print("Error avisando admin de vinculación:", e)

            return


        if status == "not_owner":

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if status == "owned_by_other":

            await query.message.reply_text(
                "⛔ Este grupo ya está vinculado a otra comunidad."
            )

            return


        if status == "no_capacity":

            await query.message.reply_text(
                "Has alcanzado el cupo máximo de grupos de tu suscripción."
            )

            return


        if status == "not_pending":

            await query.message.reply_text(
                "⚠️ Esta vinculación ya fue procesada."
            )

            return


        await query.message.reply_text(
            "⚠️ No se pudo confirmar esta vinculación. Vuelve a añadir el bot desde tu panel de configuración."
        )

        return


    if data.startswith("cancel_creator_group_link_"):

        try:

            pending_id = int(data.replace("cancel_creator_group_link_", "", 1))

        except Exception:

            await query.message.reply_text(
                "❌ Solicitud de vinculación no válida."
            )

            return


        result = cancel_creator_group_link_request(
            pending_id,
            user_id
        )

        status = result.get("status")


        if status == "cancelled":

            telegram_group_id = result.get("telegram_group_id")

            await query.message.reply_text(
                "❌ Vinculación cancelada.\n\n"
                "No se ha asociado este grupo a tu comunidad."
            )

            try:

                await context.bot.send_message(
                    chat_id=telegram_group_id,
                    text="⚠️ La vinculación fue cancelada. El bot saldrá del grupo."
                )

            except Exception as e:

                print("Error avisando grupo de cancelación:", e)


            await leave_chat_safely(
                context,
                telegram_group_id
            )

            return


        if status == "not_owner":

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if status == "not_pending":

            await query.message.reply_text(
                "⚠️ Esta vinculación ya fue procesada."
            )

            return


        await query.message.reply_text(
            "⚠️ No encontré esta vinculación pendiente."
        )

        return


    if data in (
        "public_back_start",
        CALLBACK_COMMERCIAL_BACK_START
    ):

        clear_support_user_state(context)
        clear_location_gate_state(context)

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
            MARKETPLACE_DEFAULT_FILTER
        )

        return


    if data == "marketplace_filters":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🔎 Filtrar grupos\n\nElige cómo quieres ordenar o acotar las comunidades.",
            reply_markup=build_marketplace_filter_menu_keyboard()
        )

        return


    if data == "marketplace_filter_category":

        await send_clean_message(
            context,
            query.message.chat_id,
            "📂 Filtrar por categoría\n\nElige una categoría para ver comunidades relacionadas.",
            reply_markup=build_marketplace_category_filter_keyboard()
        )

        return


    if data == "marketplace_filter_tags":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🏷 Filtrar por tags\n\nElige uno de los tags disponibles.",
            reply_markup=build_marketplace_tag_filter_keyboard()
        )

        return


    if data.startswith("marketplace_filter_category_"):

        await expire_expired_commercial_trials(context)

        category = data.replace("marketplace_filter_category_", "", 1)


        if category not in MARKETPLACE_CATEGORY_LABELS:

            category = "otros"


        await send_marketplace_list(
            context,
            query.message.chat_id,
            user_id,
            f"category:{category}"
        )

        return


    if data.startswith("marketplace_filter_tag_"):

        await expire_expired_commercial_trials(context)

        tag_slug = data.replace("marketplace_filter_tag_", "", 1)


        await send_marketplace_list(
            context,
            query.message.chat_id,
            user_id,
            f"tag:{tag_slug}"
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


        videos = fetch_dynamic_preview_videos(group_id, limit=3)


        if not videos:

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚡ Preview dinámico\n\n"
                "Todavía no hay vídeos capturados para este grupo.\n\n"
                "Publica un vídeo nuevo en el grupo después de activar el modo dinámico.",
                reply_markup=build_dynamic_preview_access_keyboard(
                    group,
                    user_id=user_id
                )
            )

            return


        await delete_query_message_safely(query)
        total = len(videos)


        for index, video in enumerate(videos, start=1):

            reply_markup = (
                build_dynamic_preview_access_keyboard(
                    group,
                    user_id=user_id
                )
                if index == total
                else None
            )

            message = await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video.get("video_file_id"),
                caption=format_dynamic_preview_video_caption(
                    group,
                    video,
                    index,
                    total
                ),
                reply_markup=reply_markup
            )
            remember_preview_message(
                context,
                query.message.chat_id,
                message
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
        context.user_data.pop("replying_support_ticket", None)
        context.user_data.pop("support_replying_ticket", None)

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
        context.user_data.pop("replying_support_ticket", None)
        context.user_data.pop("support_replying_ticket", None)

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

        print(
            "commercial_form_start:",
            f"query.from_user.id={query.from_user.id if query.from_user else '-'}",
            f"username={query.from_user.username if query.from_user and query.from_user.username else '-'}",
            f"first_name={query.from_user.first_name if query.from_user and query.from_user.first_name else '-'}",
            "request_type=shared_trial"
        )

        recoverable_request_id = fetch_recoverable_creator_request_id(user_id)

        if recoverable_request_id:

            clear_creator_onboarding_context(context)

            await send_clean_message(
                context,
                query.message.chat_id,
                "Ya tienes una prueba/configuración pendiente.\n\n"
                "Puedes continuar donde lo dejaste sin iniciar otra solicitud.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🔄 Recuperar configuración",
                        callback_data=f"configure_community_{recoverable_request_id}"
                    )],
                    [InlineKeyboardButton(
                        "📡 Añadir grupo/canal",
                        callback_data=f"creator_setup_group_{recoverable_request_id}"
                    )],
                    [InlineKeyboardButton(
                        "🎟 Tengo código promocional",
                        callback_data=f"creator_promo_code_start_{recoverable_request_id}"
                    )],
                    [InlineKeyboardButton(
                        "🛟 Soporte",
                        callback_data="public_support"
                    )],
                    [InlineKeyboardButton(
                        "🧹 Reiniciar configuración",
                        callback_data=f"creator_setup_reset_{recoverable_request_id}"
                    )],
                    [InlineKeyboardButton(
                        "🏠 Inicio",
                        callback_data="public_back_start"
                    )]
                ])
            )

            return

        context.user_data["commercial_form"] = True
        context.user_data["commercial_form_type"] = "shared_trial"
        context.user_data["commercial_form_step"] = 1
        context.user_data["commercial_form_data"] = {}
        context.user_data["commercial_form_waiting"] = "creator_setup_waiting_community_name"

        await send_clean_message(
            context,
            query.message.chat_id,
            "Indica el nombre de la comunidad.\n\n"
            "Ejemplo: GrupoStarsVip"
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

        print(
            "commercial_form_start:",
            f"query.from_user.id={query.from_user.id if query.from_user else '-'}",
            f"username={query.from_user.username if query.from_user and query.from_user.username else '-'}",
            f"first_name={query.from_user.first_name if query.from_user and query.from_user.first_name else '-'}",
            "request_type=custom_bot"
        )

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

        print(
            "commercial_contact_request:",
            f"query.from_user.id={query.from_user.id if query.from_user else '-'}",
            f"username={query.from_user.username if query.from_user and query.from_user.username else '-'}",
            f"first_name={query.from_user.first_name if query.from_user and query.from_user.first_name else '-'}"
        )

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

        await expire_expired_commercial_trials(context)

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

            build_admin_home_text(user_id),

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


    if data == "admin_global_panel":

        await send_clean_message(
            context,
            query.message.chat_id,
            "👑 Panel global del bot: índice principal de la plataforma.\n\n"
            "Desde aquí entras a monitor beta, satisfacción, soporte, marketplace, propietarios y los dos submenús separados de configuración y herramientas.",
            reply_markup=build_admin_global_panel_keyboard()
        )

        return


    if data.startswith("admin_help_"):

        help_key = data.replace("admin_help_", "", 1)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_admin_context_help_text(help_key),
            reply_markup=build_admin_context_help_keyboard(help_key)
        )

        return


    if data in (
        "admin_button_audit",
        "admin_button_audit_refresh"
    ):

        report = build_admin_button_audit_report()
        context.user_data["admin_button_audit_report"] = report

        await send_clean_message(
            context,
            query.message.chat_id,
            format_admin_button_audit_summary(report),
            reply_markup=build_admin_button_audit_keyboard()
        )

        return


    if data == "admin_button_audit_detail":

        report = context.user_data.get("admin_button_audit_report")


        if not report:

            report = build_admin_button_audit_report()
            context.user_data["admin_button_audit_report"] = report


        await send_clean_message(
            context,
            query.message.chat_id,
            format_admin_button_audit_detail(report),
            reply_markup=build_admin_button_audit_keyboard()
        )

        return


    if data == "admin_owners_panel":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🧑‍💼 Panel de propietarios: gestiona solicitudes, trials y cupos.\n\n"
            "No se mezcla con códigos de grupo, planes de acceso ni configuración de comunidades concretas.",
            reply_markup=build_admin_owners_panel_keyboard()
        )

        return


    if data in (
        "admin_global_marketplace",
        "admin_global_commercial_plans",
        "admin_payment_providers",
        "admin_global_config",
        "admin_global_tools"
    ):

        info_texts = {
            "admin_global_marketplace": (
                "🏪 Marketplace global\n\n"
                "Vista de catálogo global. Desde aquí puedes abrir el marketplace como usuario y volver a configuración o propietarios."
            ),
            "admin_global_commercial_plans": (
                "💳 Planes comerciales del bot\n\n"
                "Zona informativa para revisar suscripciones comerciales, códigos globales y gestión de owners. No se mezcla con planes de acceso de cada grupo."
            ),
            "admin_payment_providers": build_payment_methods_admin_text(),
            "admin_global_config": (
                "⚙️ Configuración global\n\n"
                "Opciones de plataforma y configuración comercial. No incluye herramientas técnicas ni logs operativos para mantener el menú claro."
            ),
            "admin_global_tools": (
                "🛠 Herramientas internas\n\n"
                "Herramientas de diagnóstico, revisión beta y mantenimiento interno. No mezcla configuración comercial ni satisfacción."
            )
        }
        reply_markups = {
            "admin_global_marketplace": build_admin_global_marketplace_keyboard(),
            "admin_global_commercial_plans": build_admin_global_commercial_plans_keyboard(),
            "admin_payment_providers": build_admin_payment_providers_keyboard(),
            "admin_global_config": build_admin_global_config_keyboard(),
            "admin_global_tools": build_admin_global_tools_keyboard()
        }

        await send_clean_message(
            context,
            query.message.chat_id,
            info_texts[data],
            reply_markup=reply_markups.get(data, build_admin_global_panel_keyboard())
        )

        return


    if data in (
        "admin_commercial_active_requests",
        "admin_commercial_trials_active",
        "admin_commercial_subscriptions",
        "admin_commercial_group_limits",
        "admin_commercial_owner_tools",
        "admin_commercial_reassign_owner_group"
    ):

        if data == "admin_commercial_active_requests":

            requests = fetch_commercial_requests_by_statuses([
                "approved",
                "awaiting_creator_setup",
                "setup_in_progress",
                "setup_ready",
                "active"
            ])

            title = "✅ Solicitudes activas"

        elif data == "admin_commercial_trials_active":

            requests = fetch_commercial_requests_by_statuses([
                "trial_active"
            ])

            title = "⏳ Trials activos"

        elif data == "admin_commercial_subscriptions":

            requests = fetch_commercial_requests_by_statuses([
                "active",
                "trial_expired",
                "expired_pending_reactivation"
            ])

            title = "💳 Suscripciones comerciales"

        else:

            requests = fetch_commercial_requests_by_statuses([
                "approved",
                "trial_active",
                "awaiting_creator_setup",
                "setup_in_progress",
                "setup_ready",
                "active"
            ])

            title = (
                "🔢 Cupos de grupos"
                if data == "admin_commercial_group_limits"
                else (
                    "🔁 Reasignar owner/grupo"
                    if data == "admin_commercial_reassign_owner_group"
                    else "🔎 Buscar propietario"
                )
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            build_commercial_status_list_text(title, requests),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_status_list_keyboard(requests)
            )
        )

        return


    if data == "admin_commercial_owner_summary":

        pending_requests = fetch_pending_commercial_requests()
        active_requests = fetch_commercial_requests_by_statuses([
            "approved",
            "awaiting_creator_setup",
            "setup_in_progress",
            "setup_ready",
            "active"
        ])
        trial_requests = fetch_commercial_requests_by_statuses([
            "trial_active"
        ])
        subscription_requests = fetch_commercial_requests_by_statuses([
            "active",
            "trial_expired",
            "expired_pending_reactivation"
        ])
        archived_requests = fetch_archived_commercial_requests()

        await send_clean_message(
            context,
            query.message.chat_id,
            "📊 Resumen propietarios\n\n"
            f"🕓 Solicitudes pendientes: {len(pending_requests)}\n"
            f"✅ Propietarios activos/configurando: {len(active_requests)}\n"
            f"🧪 Trials activos: {len(trial_requests)}\n"
            f"💳 Suscripciones/recoveries: {len(subscription_requests)}\n"
            f"📁 Archivados: {len(archived_requests)}\n\n"
            "Usa los botones del panel de propietarios para abrir cada vista y revisar casos concretos.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🕓 Solicitudes pendientes", callback_data="admin_commercial_requests")],
                [InlineKeyboardButton("✅ Propietarios activos", callback_data="admin_commercial_active_requests")],
                [InlineKeyboardButton("🧑‍💼 Propietarios", callback_data="admin_owners_panel")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_customer_satisfaction":

        await send_clean_message(
            context,
            query.message.chat_id,
            "😊 Satisfacción de clientes\n\n"
            "Envía encuestas y revisa la opinión de usuarios, propietarios y administradores.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_send_"):

        audience_slug = data.replace("admin_satisfaction_send_", "", 1)
        audience = {
            "global": "global",
            "users": "users",
            "owners": "owners",
            "group_admins": "group_admins"
        }.get(audience_slug)

        if not audience:
            await query.message.reply_text(
                "❌ Audiencia no válida.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        recipients = fetch_customer_satisfaction_recipients(audience)
        survey_id = create_customer_satisfaction_survey(user_id, audience)

        await send_clean_message(
            context,
            query.message.chat_id,
            "📤 Confirmar envío de encuesta\n\n"
            f"Audiencia: {get_customer_satisfaction_audience_label(audience)}\n"
            f"Usuarios elegibles: {len(recipients)}\n\n"
            "Vas a enviar una encuesta de satisfacción. ¿Confirmas?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar envío", callback_data=f"admin_satisfaction_confirm_{survey_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="admin_customer_satisfaction")]
            ])
        )

        return


    if data.startswith("admin_satisfaction_confirm_"):

        try:
            survey_id = int(data.replace("admin_satisfaction_confirm_", "", 1))
        except Exception:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        with conn.cursor() as cur:
            cur.execute("""

                SELECT audience, status
                FROM customer_satisfaction_surveys
                WHERE id=%s
                LIMIT 1

            """, (survey_id,))
            survey_row = cur.fetchone()

        if not survey_row:
            await query.message.reply_text(
                "❌ Encuesta no encontrada.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        audience, status = survey_row
        if status != "draft":
            await query.message.reply_text(
                "⚠️ Esta encuesta ya fue enviada o cerrada.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        recipients = fetch_customer_satisfaction_recipients(audience)
        sent_count = 0
        failed_count = 0

        for recipient_id in recipients:
            try:
                await context.bot.send_message(
                    chat_id=recipient_id,
                    text=(
                        "Queremos mejorar el bot. Responde esta encuesta rápida de 1 a 5.\n\n"
                        "Tus respuestas ayudan a mejorar menús, acceso, pagos, soporte y seguridad."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📝 Responder encuesta", callback_data=f"satisfaction_start_{survey_id}")]
                    ])
                )
                sent_count += 1
            except Exception as e:
                failed_count += 1
                print("Error enviando encuesta de satisfacción:", e)

        update_customer_satisfaction_sent_counts(survey_id, sent_count, failed_count)

        log_event(
            "survey_sent",
            category="satisfaction",
            severity="info",
            actor_user_id=user_id,
            message="Encuesta de satisfacción enviada.",
            metadata={
                "survey_id": survey_id,
                "audience": audience,
                "sent_count": sent_count,
                "failed_count": failed_count
            }
        )
        record_beta_event(
            "survey_sent",
            severity="info",
            user_id=user_id,
            message="Encuesta de satisfacción enviada.",
            metadata={
                "survey_id": survey_id,
                "audience": audience,
                "sent_count": sent_count,
                "failed_count": failed_count
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Encuesta enviada\n\n"
            f"Enviados: {sent_count}\n"
            f"Fallidos: {failed_count}",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_results":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_results_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_questions":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_questions_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_deactivate_menu":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🚫 Desactivar pregunta\n\nElige una pregunta activa para ocultarla en próximas encuestas.",
            reply_markup=build_customer_satisfaction_deactivate_keyboard()
        )

        return


    if data == "admin_satisfaction_edit_menu":

        await send_clean_message(
            context,
            query.message.chat_id,
            "✏️ Editar preguntas\n\nElige la pregunta cuyo texto quieres actualizar.",
            reply_markup=build_customer_satisfaction_edit_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_edit_"):

        try:
            question_id = int(data.replace("admin_satisfaction_edit_", "", 1))
        except Exception:
            await query.message.reply_text("❌ Pregunta no válida.")
            return

        context.user_data["customer_satisfaction_admin_edit_question_id"] = question_id

        await query.message.reply_text(
            "✏️ Editar pregunta\n\nEscribe el nuevo texto de la pregunta.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_deactivate_"):

        try:
            question_id = int(data.replace("admin_satisfaction_deactivate_", "", 1))
        except Exception:
            await query.message.reply_text("❌ Pregunta no válida.")
            return

        with conn.cursor() as cur:
            cur.execute("""

                UPDATE customer_satisfaction_questions
                SET is_active=FALSE
                WHERE id=%s

            """, (question_id,))

        await query.message.reply_text(
            "✅ Pregunta desactivada.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_add_rating":

        context.user_data["customer_satisfaction_admin_add_question"] = "rating_1_5"
        await query.message.reply_text(
            "➕ Añadir pregunta\n\nEscribe el texto de la pregunta. Se guardará como valoración 1-5.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_add_text":

        context.user_data["customer_satisfaction_admin_add_question"] = "text"
        await query.message.reply_text(
            "➕ Añadir pregunta texto\n\nEscribe el texto de la pregunta. El usuario responderá con texto libre.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_latest":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_results_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("satisfaction_start_"):

        try:
            survey_id = int(data.replace("satisfaction_start_", "", 1))
        except Exception:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        response_id = get_or_create_customer_satisfaction_response(
            survey_id,
            user_id
        )

        context.user_data["customer_satisfaction_response_id"] = response_id
        await send_customer_satisfaction_question(
            context,
            query.message.chat_id,
            response_id
        )

        return


    if data.startswith("satisfaction_rate_"):

        parts = data.split("_")

        if len(parts) != 5 or not all(part.isdigit() for part in parts[2:]):
            await query.message.reply_text("❌ Respuesta no válida.")
            return

        response_id = int(parts[2])
        question_id = int(parts[3])
        rating = int(parts[4])

        if not customer_satisfaction_response_belongs_to_user(
            response_id,
            user_id
        ):

            await query.message.reply_text("⛔ No puedes responder esta encuesta.")
            return

        if rating < 1 or rating > 5:
            await query.message.reply_text("❌ Respuesta no válida.")
            return

        save_customer_satisfaction_answer(
            response_id,
            question_id,
            rating=rating
        )

        await send_customer_satisfaction_question(
            context,
            query.message.chat_id,
            response_id
        )

        return


    if data == "owner_backup_panel":

        groups = fetch_backup_owner_groups(user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes grupos propios con permisos para configurar backup."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            format_backup_panel_text(user_id),
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data in (
        "owner_backup_activate",
        "owner_backup_change_destination",
        "owner_backup_destination_token"
    ):

        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]


        if not groups:

            await query.message.reply_text(
                "⚠️ Necesitas al menos un grupo origen propio con el bot añadido como administrador.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🛡 Backup premium\n\nSelecciona el grupo origen. Después generaré un código para vincular el grupo destino.",
            reply_markup=build_backup_group_select_keyboard(
                groups,
                "owner_backup_source_"
            )
        )

        return


    if data == "owner_backup_change_mode":

        configs = fetch_owner_backup_configs(user_id)


        if not configs:

            await query.message.reply_text(
                "⚠️ No tienes ninguna configuración de backup activa para cambiar el modo.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚙️ Cambiar modo de backup\n\n"
            "Solo texto copia mensajes de texto.\n"
            "Texto + fotos copia texto, captions y fotos nuevas sin descargar archivos.\n"
            "Texto + fotos + vídeos añade vídeos nuevos usando Telegram, sin descargar archivos.",
            reply_markup=build_backup_config_select_keyboard(
                configs,
                "owner_backup_mode_config_"
            )
        )

        return


    if data.startswith("owner_backup_mode_config_"):

        try:

            config_id = int(
                data.replace("owner_backup_mode_config_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚙️ Elige el modo de backup\n\n"
            "Solo texto: copia únicamente mensajes de texto.\n"
            "Texto + fotos: copia mensajes de texto, captions y fotos nuevas usando Telegram, sin descargar imágenes.\n"
            "Texto + fotos + vídeos: también copia vídeos nuevos con copy_message, sin guardar binarios.",
            reply_markup=build_backup_mode_keyboard(config_id)
        )

        return


    if data.startswith("owner_backup_set_mode_"):

        try:

            payload = data.replace("owner_backup_set_mode_", "", 1)
            config_id_text, selected_mode = payload.split("_", 1)
            config_id = int(config_id_text)

        except Exception:

            await query.message.reply_text("❌ Modo de backup no válido.")

            return


        if selected_mode not in (
            "text",
            "text_photos",
            "text_photos_videos"
        ):

            await query.message.reply_text("❌ Modo de backup no válido.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET mode=%s,
                    updated_at=NOW()
                WHERE id=%s
                AND owner_user_id=%s

            """, (
                selected_mode,
                config_id,
                user_id
            ))

            conn.commit()


        log_event(
            "backup_mode_changed",
            category="backup",
            severity="info",
            scope="group",
            group_id=config[2],
            telegram_group_id=config[3],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Modo de backup premium actualizado.",
            metadata={
                "config_id": config_id,
                "mode": selected_mode
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Modo de backup actualizado.\n\n"
            f"Modo activo: {format_backup_mode(selected_mode)}",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_toggle_author":

        configs = fetch_owner_backup_configs(user_id)


        if not configs:

            await query.message.reply_text(
                "⚠️ No tienes ninguna configuración de backup para cambiar esta opción.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "👤 Mostrar autor original\n\n"
            "Elige la configuración donde quieres activar o desactivar la atribución.",
            reply_markup=build_backup_config_select_keyboard(
                configs,
                "owner_backup_author_config_"
            )
        )

        return


    if data.startswith("owner_backup_author_config_"):

        try:

            config_id = int(
                data.replace("owner_backup_author_config_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET show_original_author=NOT COALESCE(show_original_author, FALSE),
                    updated_at=NOW()
                WHERE id=%s
                AND owner_user_id=%s
                RETURNING COALESCE(show_original_author, FALSE)

            """, (
                config_id,
                user_id
            ))

            show_original_author = cur.fetchone()[0]
            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Preferencia actualizada.\n\n"
            f"Mostrar autor original: {'Activado' if show_original_author else 'Desactivado'}",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_confirm_destination_"):

        try:

            token_id = int(
                data.replace("owner_backup_confirm_destination_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Código de backup no válido.")

            return


        result = await confirm_backup_destination_token(
            token_id,
            user_id,
            context
        )


        await send_clean_message(
            context,
            query.message.chat_id,
            result["message"],
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_source_"):

        try:

            source_group_id = int(
                data.replace("owner_backup_source_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Grupo origen no válido.")

            return


        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]
        source_group = backup_group_by_id(groups, source_group_id)


        if not source_group:

            await query.message.reply_text(
                "⛔ Este grupo no pertenece a tu panel o el bot no está como administrador."
            )

            return


        token_row = create_backup_destination_token(
            user_id,
            source_group[0],
            source_group[2]
        )


        if not token_row:

            await query.message.reply_text(
                "❌ No pude generar el código de vinculación del backup.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        token_id, token, expires_at = token_row
        command = f"/backup_{token}"


        log_event(
            "backup_destination_token_created",
            category="backup",
            severity="info",
            scope="group",
            group_id=source_group[0],
            telegram_group_id=source_group[2],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Token de destino backup creado.",
            metadata={
                "token_id": token_id,
                "expires_at": expires_at
            }
        )


        await send_clean_message(
            context,
            query.message.chat_id,
            "🛡 Backup premium\n\n"
            f"Origen: {source_group[1] or source_group_id}\n\n"
            "Crea un grupo nuevo o usa un grupo vacío como destino.\n"
            "Añade este bot como administrador.\n"
            "Dentro del grupo destino escribe este comando:\n\n"
            f"{command}\n\n"
            "El código caduca en 24 horas y solo puede usarse una vez.",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_dest_"):

        try:

            payload = data.replace("owner_backup_dest_", "", 1)
            source_group_text, destination_group_text = payload.split("_", 1)
            source_group_id = int(source_group_text)
            destination_group_id = int(destination_group_text)

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        if source_group_id == destination_group_id:

            await query.message.reply_text(
                "⚠️ El origen y el destino no pueden ser el mismo grupo."
            )

            return


        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]
        source_group = backup_group_by_id(groups, source_group_id)
        destination_group = backup_group_by_id(groups, destination_group_id)


        if not source_group or not destination_group:

            await query.message.reply_text(
                "⛔ Solo puedes configurar backup entre grupos propios donde el bot esté como administrador."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO backup_subscriptions
                (
                    owner_user_id,
                    status,
                    plan_type,
                    updated_at
                )
                VALUES (%s, 'active', 'text', NOW())
                RETURNING id

            """, (user_id,))

            subscription_id = cur.fetchone()[0]

            cur.execute("""

                INSERT INTO group_backup_configs
                (
                    owner_user_id,
                    source_group_id,
                    source_telegram_group_id,
                    destination_group_id,
                    destination_telegram_group_id,
                    subscription_id,
                    mode,
                    status,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'text', 'active', NOW())
                ON CONFLICT (owner_user_id, source_group_id, destination_group_id)
                DO UPDATE SET
                    source_telegram_group_id=EXCLUDED.source_telegram_group_id,
                    destination_telegram_group_id=EXCLUDED.destination_telegram_group_id,
                    subscription_id=EXCLUDED.subscription_id,
                    mode='text',
                    status='active',
                    updated_at=NOW()
                RETURNING id

            """, (
                user_id,
                source_group[0],
                source_group[2],
                destination_group[0],
                destination_group[2],
                subscription_id
            ))

            config_id = cur.fetchone()[0]

            conn.commit()


        log_event(
            "backup_activated",
            category="backup",
            severity="info",
            scope="group",
            group_id=source_group_id,
            telegram_group_id=source_group[2],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Backup premium texto activado.",
            metadata={
                "config_id": config_id,
                "destination_group_id": destination_group_id,
                "destination_telegram_group_id": destination_group[2],
                "mode": "text"
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Backup premium activado.\n\n"
            f"Origen: {source_group[1] or source_group_id}\n"
            f"Destino: {destination_group[1] or destination_group_id}\n"
            "Modo: texto",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_pause":

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET status='paused',
                    updated_at=NOW()
                WHERE owner_user_id=%s
                AND status='active'

            """, (user_id,))

            affected = cur.rowcount
            conn.commit()


        log_event(
            "backup_paused",
            category="backup",
            severity="info",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Backup premium pausado por owner.",
            metadata={
                "configs_paused": affected
            }
        )

        await query.message.reply_text(
            f"⏸ Backup pausado en {affected} configuración(es).",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_messages":

        rows = fetch_backup_recent_messages(user_id)


        if not rows:

            await query.message.reply_text(
                "📜 Todavía no hay mensajes copiados.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        text = "📜 Últimos mensajes copiados\n\n"


        for created_at, source_name, destination_name, source_message_id, destination_message_id, message_type, status in rows[:20]:

            text += (
                f"Origen: {source_name or '-'}\n"
                f"Destino: {destination_name or '-'}\n"
                f"Tipo: {message_type or '-'}\n"
                f"Mensaje origen: {source_message_id or '-'}\n"
                f"Mensaje destino: {destination_message_id or '-'}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_errors":

        rows = fetch_backup_recent_errors(user_id)


        if not rows:

            await query.message.reply_text(
                "✅ No hay errores recientes de backup.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        text = "⚠️ Últimos errores de backup\n\n"


        for created_at, severity, error_type, message in rows[:20]:

            text += (
                f"Tipo: {error_type or '-'}\n"
                f"Severidad: {severity or '-'}\n"
                f"Detalle: {message or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_backup_panel_keyboard()
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

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
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


    if data.startswith("add_group_admin_select_group_"):

        group_id = extract_commercial_request_id(
            data,
            "add_group_admin_select_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        target_user_id = context.user_data.get("group_admin_target_user_id")


        if not target_user_id:

            await query.message.reply_text(
                "❌ No hay usuario pendiente para añadir.",
                reply_markup=build_group_admin_error_keyboard()
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
                "⛔ Esta comunidad no pertenece a tu panel.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if int(context.user_data.get("group_admin_target_user_id") or 0) != target_user_id:

            await query.message.reply_text(
                "❌ El usuario pendiente no coincide.",
                reply_markup=build_group_admin_error_keyboard()
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
                "⛔ Esta comunidad no pertenece a tu panel.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        target_user_id = context.user_data.get("group_admin_target_user_id")
        permissions = context.user_data.get("group_admin_permissions") or {}


        if not target_user_id:

            await query.message.reply_text(
                "❌ No hay usuario pendiente para añadir.",
                reply_markup=build_group_admin_error_keyboard()
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

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
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
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
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

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
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
                build_support_ticket_keyboard(ticket)
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


        if ticket.get("status") == "closed":

            await query.message.reply_text(
                "📁 Este ticket está cerrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🛟 Tickets abiertos",
                        callback_data="admin_support_tickets"
                    )]
                ])
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

            await query.message.reply_text(
                "❌ Duración no válida.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_commercial_promo_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

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


    if data == "admin_commercial_archived_requests":

        requests = fetch_archived_commercial_requests()

        await query.message.reply_text(
            build_archived_commercial_requests_text(requests),
            reply_markup=InlineKeyboardMarkup(
                build_archived_commercial_requests_keyboard(requests)
            )
        )

        return


    if data.startswith("admin_commercial_status_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_status_"
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


    if data.startswith("admin_commercial_owner_groups_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_owner_groups_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_owner_groups_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📄 Ver detalle completo",
                    callback_data=f"admin_commercial_status_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver al panel de propietarios",
                    callback_data="admin_owners_panel"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_internal_note_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_internal_note_"
        )

        await query.message.reply_text(
            "📝 Añadir nota interna\n\n"
            "Este acceso deja claro dónde irá la nota interna. "
            "La edición de notas se conectará al flujo de texto seguro en una fase posterior.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📄 Ver detalle completo",
                    callback_data=f"admin_commercial_status_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver al panel de propietarios",
                    callback_data="admin_owners_panel"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_archive_confirm_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_confirm_"
        )

        request_row = archive_commercial_request(request_id, user_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            "🗄 Solicitud archivada.\n\n"
            "No se han borrado datos, grupo, owner ni conversación comercial.",
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return


    if data.startswith("admin_commercial_archive_cancel_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_cancel_"
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


    if data.startswith("admin_commercial_archive_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        if is_commercial_request_archived(request_row):

            await query.message.reply_text(
                "📁 Esta solicitud ya está archivada.",
                reply_markup=InlineKeyboardMarkup(
                    build_commercial_review_keyboard(request_row)
                )
            )

            return


        await query.message.reply_text(
            "🗄 Finalizar solicitud\n\n"
            "Se archivará la solicitud comercial sin borrar datos, grupo, owner ni conversación comercial.",
            reply_markup=build_commercial_archive_confirm_keyboard(request_id)
        )

        return


    if data.startswith("admin_commercial_reopen_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reopen_"
        )

        request_row = reopen_archived_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud archivada no encontrada."
            )

            return


        await query.message.reply_text(
            "♻️ Solicitud reabierta.",
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return


    if data.startswith("admin_commercial_chat_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_chat_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        messages = fetch_commercial_request_messages(request_id)

        await query.message.reply_text(
            build_commercial_request_chat_text(request_row, messages),
            reply_markup=build_admin_commercial_request_chat_keyboard(request_id)
        )

        return


    if data.startswith("admin_commercial_reply_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reply_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        start_commercial_request_chat_reply(
            context,
            request_id,
            "admin"
        )

        await query.message.reply_text(
            f"✍️ Responder solicitud comercial #{request_id}\n\n"
            "Escribe ahora el mensaje para el solicitante."
        )

        return


    if data.startswith("commercial_request_chat_"):

        request_id = extract_commercial_request_id(
            data,
            "commercial_request_chat_"
        )

        request_row = fetch_commercial_request(request_id)


        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_commercial_request_chat_reply(
            context,
            request_id,
            "user"
        )

        await query.message.reply_text(
            f"💬 Responder solicitud comercial #{request_id}\n\n"
            "Escribe ahora tu respuesta."
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


        if is_commercial_request_advanced(request_row):

            await reply_duplicate_commercial_approval(query, request_id)

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

        await handle_admin_trial_visibility_approval(
            context,
            query,
            user_id,
            request_id,
            "start_home"
        )

        return


    if data.startswith("admin_trial_visibility_explore_only_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_trial_visibility_explore_only_"
        )

        await handle_admin_trial_visibility_approval(
            context,
            query,
            user_id,
            request_id,
            "explore_only"
        )

        return


    if data.startswith("admin_trial_visibility_hidden_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_trial_visibility_hidden_"
        )

        await handle_admin_trial_visibility_approval(
            context,
            query,
            user_id,
            request_id,
            "hidden"
        )

        return


    if data.startswith("admin_commercial_approve_custom_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_approve_custom_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        if is_commercial_request_advanced(request_row):

            await reply_duplicate_commercial_approval(query, request_id)

            return


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

        existing_request = fetch_commercial_request(request_id)


        if is_commercial_request_advanced(existing_request):

            await query.message.reply_text(
                "Esta solicitud ya está aprobada, configurada o archivada. No se ha rechazado.",
                reply_markup=InlineKeyboardMarkup(
                    build_commercial_review_keyboard(existing_request)
                )
            )

            return


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
        mysub_parts = data.split("_")


        if len(mysub_parts) < 2 or not mysub_parts[1].lstrip("-").isdigit():

            await reply_with_recover_navigation(
                query,
                "⚠️ Esta opción ya no está disponible o no está configurada."
            )

            return

        telegram_group_id = int(
            mysub_parts[1]
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
                    AND (
                        group_id=%s
                        OR telegram_group_id=%s
                        OR group_id=%s
                    )
                    AND is_active=TRUE

                    ORDER BY created_at DESC

                    LIMIT 1

                """, (

                    user_id,
                    real_group_id,
                    telegram_group_id,
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
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
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
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
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
                (user_id, group_id, telegram_group_id, invite_link)

                VALUES (%s, %s, %s, %s)

            """, (

                user_id,
                real_group_id,
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


        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(location_gate_enabled, FALSE),
                       allowed_region,
                       allowed_region_type
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


        location_gate_enabled, allowed_region, allowed_region_type = group_row


        if location_gate_enabled is True:

            await request_location_verification(
                context,
                query.message.chat_id,
                group_id,
                "free_access"
            )

            return


        await create_free_access_for_user(
            context,
            query.message.chat_id,
            query.from_user,
            group_id
        )

        return


    # =========================
    # ENTRAR A GRUPO
    # =========================

    if is_numeric_group_callback(data):

        try:
            await query.message.delete()
        except:
            pass


        group_callback_parts = data.split("_")
        group_id = int(group_callback_parts[1])


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
                        "🎟 Canjear código de esta comunidad",
                        callback_data=f"group_user_promo_redeem_start_{group_id}"
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

                "🎟 Canjear código de esta comunidad",

                callback_data=f"group_user_promo_redeem_start_{group_id}"

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

        if (
            len(parts) < 4
            or not parts[2].isdigit()
            or not parts[3].isdigit()
        ):

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return

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

        if (
            len(parts) < 4
            or not parts[2].isdigit()
            or not parts[3].isdigit()
        ):

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return

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

        try:
            await query.message.delete()
        except:
            pass

        try:

            with conn.cursor() as cur:

                groups = fetch_admin_groups_for_permissions(
                    user_id,
                    ["can_manage_groups", "can_manage_plans"]
                )

            log_event(
                "admin_view_groups_loaded",
                category="admin",
                severity="info",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Listado de grupos cargado desde panel admin.",
                metadata={
                    "groups_count": len(groups)
                }
            )

        except Exception as e:

            log_event(
                "admin_view_groups_error",
                category="admin",
                severity="error",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Error cargando grupos desde panel admin.",
                metadata={
                    "error": str(e)
                }
            )

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

        logs_label = (
            "📜 Logs del sistema"
            if is_super_admin(user_id)
            else "📜 Logs de mi grupo"
        )


        keyboard = [

            [InlineKeyboardButton(logs_label, callback_data="admin_logs")],

            [InlineKeyboardButton("👥 Logs usuarios", callback_data="admin_logs_users")],

            [InlineKeyboardButton("💳 Logs pagos", callback_data="admin_logs_payments")],

            [InlineKeyboardButton("🔐 Logs seguridad", callback_data="admin_logs_security")],

            [InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_LOGS_HELP)],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,

            logs_label,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # VOLVER AL MENÚ PRINCIPAL
    # =========================

    if data == "admin_back_main":

        await expire_expired_commercial_trials(context)

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

            build_admin_home_text(user_id),

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
    # CÓDIGOS POR GRUPO — SUPER ADMIN
    # =========================

    if data == "admin_group_user_codes":

        rows = fetch_admin_groups_for_permissions(
            user_id,
            ["can_manage_codes"]
        )


        if not rows:

            await query.message.reply_text(
                "⚠️ No hay grupos disponibles.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        keyboard = []

        for group_id, group_name, _telegram_group_id in rows:

            keyboard.append([InlineKeyboardButton(
                group_name or f"Grupo {group_id}",
                callback_data=f"group_user_code_select_group_{group_id}"
            )])


        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")])

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos por grupo\n\n"
            "Elige el grupo para gestionar códigos de acceso de usuarios finales.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data.startswith("group_user_code_select_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_user_code_select_group_"
        )


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_manage_codes"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar códigos en esta comunidad.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_group_user_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        group = set_group_user_promo_context(
            context,
            group_id,
            step="panel"
        )


        if not group:

            await query.message.reply_text(
                "❌ Grupo no encontrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_group_user_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        _group_id, group_name, _telegram_group_id = group

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos de mi grupo\n\n"
            f"Grupo: {group_name or group_id}\n\n"
            "Crea códigos para usuarios finales de esta comunidad.",
            reply_markup=build_group_user_codes_keyboard(group_id)
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
                        "can_manage_codes",
                        "can_manage_admins",
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

                callback_data="admin_back_main"

            )

        ])


        panel_intro = (
            "🏪 Mis comunidades\n\n"
            "Selecciona una comunidad para abrir su panel de gestión:"
            if is_super_admin(user_id) or user_has_group_owner_role(user_id)
            else
            "👮 Panel admin de grupo\n\n"
            "Selecciona la comunidad donde tienes permisos. Solo verás accesos compatibles con tu rol:"
        )


        await query.message.reply_text(

            panel_intro,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if data == "owner_setup_assistant":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            [
                "can_manage_groups",
                "can_manage_plans",
                "can_manage_codes",
                "can_manage_admins",
                "can_edit_group_texts",
                "can_edit_marketplace_preview",
                "can_view_logs"
            ]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para abrir el asistente de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_setup_assistant_text(group_id),
            reply_markup=build_owner_setup_assistant_keyboard(user_id, group_id)
        )

        return


    if data in OWNER_PANEL_SECTIONS:

        title, description, required_permissions, section = OWNER_PANEL_SECTIONS[data]

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            required_permissions
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if section == "codes":

            set_group_user_promo_context(
                context,
                group_id,
                step="panel"
            )


        if section == "admins":

            context.user_data["selected_owner_group"] = group_id


        await send_clean_message(
            context,
            query.message.chat_id,
            f"{title}\n\nEsto sirve para: {description}",
            reply_markup=build_owner_section_keyboard(
                user_id,
                group_id,
                section
            )
        )

        return


    if data.startswith("owner_group_payment_methods_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_payment_methods_"
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver métodos de pago de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        group_id, group_name, telegram_group_id = group

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            build_group_payment_methods_text(
                group_id,
                group_name,
                telegram_group_id,
                owner_user_id
            ),
            reply_markup=keyboard
        )

        return


    if data == "owner_support_tickets":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_respond_group_support"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver soporte de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        keyboard = [
            [InlineKeyboardButton("⬅️ Volver al apartado soporte", callback_data="owner_panel_support")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ]


        if is_super_admin(user_id):

            keyboard.insert(
                0,
                [InlineKeyboardButton("🛟 Abrir bandeja global", callback_data="admin_support_tickets")]
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            "🛟 Solicitudes de soporte\n\n"
            "Esta sección pertenece a la comunidad seleccionada. "
            "La bandeja de tickets actual es global para proteger conversaciones privadas; "
            "por eso solo el super admin puede abrir el listado completo desde aquí.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data in (
        "owner_panel_security_info",
        "owner_panel_location_info",
        "owner_panel_access_type_info",
        "owner_panel_general_info"
    ):

        info_texts = {
            "owner_panel_security_info": (
                "🛡 Seguridad del grupo\n\n"
                "La protección anti-intrusos, anti-links y validación de accesos "
                "funciona con la configuración actual del bot. Usa los logs para revisar actividad."
            ),
            "owner_panel_location_info": (
                "📍 Ubicación permitida\n\n"
                "La restricción por ubicación se gestiona desde el flujo de configuración "
                "del creator cuando la comunidad está vinculada."
            ),
            "owner_panel_access_type_info": (
                "🔓 Tipo gratis/pago\n\n"
                "El tipo de acceso se mantiene desde la configuración comercial de la comunidad. "
                "No se cambia desde aquí para evitar tocar pagos o checkout."
            ),
            "owner_panel_general_info": (
                "⚙️ Configuración general\n\n"
                "Estos ajustes se gestionan con flujos seguros existentes. "
                "No se reinicia ni borra configuración sin confirmación específica."
            )
        }

        await query.message.reply_text(
            info_texts.get(data, "Información no disponible."),
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    # =========================
    # MENÚ INTERNO DEL GRUPO
    # =========================

    edit_group_parts = data.split("_")


    if (
        data.startswith("edit_group_")
        and len(edit_group_parts) >= 3
        and edit_group_parts[2].isdigit()
    ):

        try:
            await query.message.delete()
        except:
            pass


        group_id = int(edit_group_parts[2])


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_manage_groups", "can_manage_plans"]
            + ["can_manage_codes", "can_manage_admins"]
            + ["can_edit_group_texts", "can_edit_marketplace_preview"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        # Guardar grupo seleccionado

        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            build_owner_quick_status_text(user_id, group_id)
            + "\nSolo verás secciones compatibles con tus permisos en esta comunidad.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if data == "edit_group_back":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_manage_plans"]
            + ["can_manage_codes", "can_manage_admins"]
            + ["can_edit_group_texts", "can_edit_marketplace_preview"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        await query.message.reply_text(
            build_owner_quick_status_text(user_id, group_id),
            reply_markup=InlineKeyboardMarkup(
                build_group_settings_keyboard(user_id, group_id)
            )
        )

        return


    if data in (
        "edit_group_name",
        "edit_group_stripe",
        "edit_group_admins",
        "edit_group_user_codes"
    ):

        required_permissions = ["can_manage_groups"]


        if data == "edit_group_name":

            required_permissions = ["can_edit_group_texts", "can_manage_groups"]


        if data == "edit_group_admins":

            required_permissions = ["can_manage_admins"]

        if data == "edit_group_user_codes":

            required_permissions = ["can_manage_codes"]

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            required_permissions
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if data == "edit_group_admins":

            context.user_data["selected_owner_group"] = group_id

            await send_clean_message(
                context,
                query.message.chat_id,
                "👥 Admins de mi grupo\n\nGestiona admins y permisos por comunidad.",
                reply_markup=build_group_admin_panel_keyboard()
            )

            return


        if data == "edit_group_user_codes":

            set_group_user_promo_context(
                context,
                group_id,
                step="panel"
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                "🎟 Códigos de mi grupo\n\n"
                "Crea códigos para usuarios finales de esta comunidad. "
                "Estos códigos solo funcionan en este grupo y no se mezclan con los códigos promocionales comerciales.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        await query.message.reply_text(
            "⚠️ Esta acción todavía no tiene un flujo seguro disponible."
        )

        return


    if data == "group_user_codes_panel" or data.startswith("group_user_codes_panel_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_codes_panel"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="panel"
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos de mi grupo\n\n"
            "Estos códigos dan acceso a usuarios finales solo para esta comunidad.",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if data == "group_user_code_create" or data.startswith("group_user_code_create_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_create"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="duration"
        )
        clear_group_user_promo_wizard(context, keep_group=True)
        context.user_data["group_user_promo_step"] = "duration"

        await send_clean_message(
            context,
            query.message.chat_id,
            "➕ Crear código\n\nElige la duración del acceso para el usuario final.",
            reply_markup=build_group_user_code_duration_keyboard(group_id)
        )

        return


    if data.startswith("group_user_code_duration_"):

        callback_group_id, slug = parse_group_user_code_step_callback(
            data,
            "group_user_code_duration"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="uses"
        )


        if slug == "custom":

            context.user_data["group_user_promo_waiting"] = "custom_duration"

            await query.message.reply_text(
                "Envía la duración en días, entre 1 y 3650.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        if slug == "permanent":

            context.user_data["group_user_promo_duration_days"] = None
            context.user_data["group_user_promo_is_permanent"] = True

        else:

            try:

                duration_days = int(slug)

            except Exception:

                await query.message.reply_text(
                    "❌ Duración no válida.",
                    reply_markup=build_group_user_codes_error_keyboard()
                )

                return


            if not 1 <= duration_days <= 3650:

                await query.message.reply_text(
                    "❌ Duración no válida.",
                    reply_markup=build_group_user_codes_error_keyboard()
                )

                return


            context.user_data["group_user_promo_duration_days"] = duration_days
            context.user_data["group_user_promo_is_permanent"] = False


        await send_clean_message(
            context,
            query.message.chat_id,
            "Elige cuántos usos tendrá el código.",
            reply_markup=build_group_user_code_uses_keyboard(group_id)
        )

        return


    if data.startswith("group_user_code_uses_"):

        callback_group_id, uses_text = parse_group_user_code_step_callback(
            data,
            "group_user_code_uses"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            max_uses = int(uses_text)

        except Exception:

            await query.message.reply_text(
                "❌ Número de usos no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        if max_uses not in (0, 1, 5, 10):

            await query.message.reply_text(
                "❌ Número de usos no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="code_kind"
        )
        context.user_data["group_user_promo_max_uses"] = max_uses

        await send_clean_message(
            context,
            query.message.chat_id,
            "Elige cómo quieres generar el código.",
            reply_markup=build_group_user_code_kind_keyboard(group_id)
        )

        return


    if data == "group_user_code_manual" or data.startswith("group_user_code_manual_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_manual"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="manual_code"
        )
        context.user_data["group_user_promo_waiting"] = "manual_code"

        await query.message.reply_text(
            "Envía el código manual.\n\n"
            "Usa entre 4 y 32 caracteres: letras, números, guion o guion bajo.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))]
            ])
        )

        return


    if data == "group_user_code_auto" or data.startswith("group_user_code_auto_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_auto"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        duration_days = context.user_data.get("group_user_promo_duration_days")
        is_permanent = context.user_data.get("group_user_promo_is_permanent") is True
        max_uses = context.user_data.get("group_user_promo_max_uses")


        if max_uses is None:

            await query.message.reply_text(
                "❌ Falta completar la configuración del código.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            row = create_group_user_promo_code(
                group_id,
                user_id,
                duration_days,
                is_permanent,
                max_uses
            )

        except Exception as e:

            print("Error creando código de grupo:", e)

            await query.message.reply_text(
                "❌ Error creando el código.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        if not row:

            await query.message.reply_text(
                "❌ Error creando el código.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        clear_group_user_promo_wizard(context, keep_group=True)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Código creado\n\n"
            f"Código: {row[1]}\n"
            f"Duración: {format_group_user_promo_duration(row[2], row[3])}\n"
            f"Usos máximos: {'ilimitado' if row[4] == 0 else row[4]}",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if data == "group_user_codes_active" or data.startswith("group_user_codes_active_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_codes_active"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_codes(group_id, active_only=True)


        if not rows:

            await query.message.reply_text(
                "📋 No hay códigos activos para este grupo.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        text = "📋 Códigos activos de mi grupo\n\n"


        for _code_id, code, duration_days, is_permanent, max_uses, used_count, _is_active, expires_at, _created_at in rows:

            text += (
                f"Código: {code}\n"
                f"Duración: {format_group_user_promo_duration(duration_days, is_permanent)}\n"
                f"Usos: {format_group_user_promo_uses(max_uses, used_count)}\n"
                f"Caduca: {expires_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if data == "group_user_code_deactivate_menu" or data.startswith("group_user_code_deactivate_menu_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_deactivate_menu"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para desactivar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_codes(group_id, active_only=True)


        await query.message.reply_text(
            "🚫 Desactivar código\n\nElige el código que quieres desactivar.",
            reply_markup=build_group_user_code_deactivate_keyboard(rows, group_id)
        )

        return


    if data.startswith("group_user_code_deactivate_"):

        payload = data.replace("group_user_code_deactivate_", "", 1)
        callback_group_id = None
        code_id_text = payload


        if "_" in payload:

            maybe_group_id, maybe_code_id = payload.split("_", 1)


            if maybe_group_id.isdigit() and maybe_code_id.isdigit():

                callback_group_id = int(maybe_group_id)
                code_id_text = maybe_code_id


        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para desactivar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            code_id = int(code_id_text)

        except Exception:

            await query.message.reply_text(
                "❌ Código no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_user_promo_codes
                SET is_active=FALSE
                WHERE id=%s
                AND group_id=%s
                RETURNING code

            """, (
                code_id,
                group_id
            ))

            row = cur.fetchone()
            conn.commit()


        if not row:

            await query.message.reply_text(
                "❌ Código no encontrado.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        await query.message.reply_text(
            f"🚫 Código desactivado:\n{row[0]}",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if data == "group_user_code_usage" or data.startswith("group_user_code_usage_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_usage"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver usos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_usage(group_id)


        if not rows:

            await query.message.reply_text(
                "📊 Todavía no hay usos de códigos en este grupo.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        text = "📊 Usos de códigos\n\n"


        for redeemed_at, redeemed_user_id, code, expiration in rows:

            text += (
                f"Código: {code}\n"
                f"Usuario: {redeemed_user_id}\n"
                f"Canjeado: {redeemed_at}\n"
                f"Expira: {expiration or 'permanente'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_group_user_codes_keyboard(group_id)
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


        await query.message.reply_text(
            preview_mode_selection_text(),
            reply_markup=build_group_preview_mode_keyboard()

        )

        return


    if data.startswith("edit_group_preview_mode_"):

        preview_mode = data.replace("edit_group_preview_mode_", "", 1)

        if preview_mode not in PREVIEW_MODE_LABELS:

            await query.message.reply_text("❌ Nivel de preview no válido.")

            return


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


        if preview_mode in ("manual", "hybrid"):

            context.user_data["editing_preview"] = True
            context.user_data["editing_preview_mode"] = preview_mode

            await query.message.reply_text(
                "✅ Tipo de preview actualizado.\n\n"
                "Envía ahora una imagen o vídeo para guardarlo como preview manual.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data="edit_group_back"
                    )]
                ])
            )

            return


        message = "✅ Preview dinámico activado."

        if preview_mode == "dynamic":

            message = (
                "✅ Preview dinámico activado.\n\n"
                "Solo capturará vídeos nuevos publicados en el grupo después de activar este modo."
            )

        elif preview_mode == "private":

            message = "✅ Sin preview público activado."


        await query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(
                build_group_settings_keyboard(user_id, group_id)
            )
        )

        return

    # =========================
    # OMITIR PREVIEW
    # =========================

    if data == "skip_preview":

        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)
        context.user_data.pop("new_preview_file_type", None)
        context.user_data.pop("editing_preview_mode", None)

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
        file_type = context.user_data.get("new_preview_file_type")
        preview_mode = context.user_data.get("editing_preview_mode") or "manual"


        if not file_id:

            await query.message.reply_text(
                "❌ Debes enviar una imagen o vídeo antes de guardar."
            )

            return


        column_name = (
            "preview_video_file_id"
            if file_type == "video"
            else "preview_image_file_id"
        )


        try:

            with conn.cursor() as cur:

                cur.execute(f"""

                    UPDATE groups

                    SET {column_name}=%s,
                        preview_file_id=%s,
                        preview_mode=%s

                    WHERE id=%s

                """, (

                    file_id,
                    file_id,
                    preview_mode,
                    group_id

                ))

                conn.commit()

        except Exception as e:

            print("Error guardando preview:", e)


        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)
        context.user_data.pop("new_preview_file_type", None)
        context.user_data.pop("editing_preview_mode", None)


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            "✅ Preview manual guardado.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # CANCELAR PREVIEW
    # =========================

    if data == "cancel_preview":

        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)
        context.user_data.pop("new_preview_file_type", None)
        context.user_data.pop("editing_preview_mode", None)

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

        parts = data.split("_")


        if len(parts) < 3 or not parts[2].isdigit():

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        plan_id = int(parts[2])

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


    if data.startswith("admin_beta_cycle"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        if data in (
            "admin_beta_cycle",
            "admin_beta_cycle_status"
        ):

            await query.message.reply_text(
                format_beta_cycle_status_text(),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data in (
            "admin_beta_cycle_start_beta_1",
            "admin_beta_cycle_start_beta_2"
        ):

            complete_expired_beta_cycles()

            phase = (
                "beta_2"
                if data == "admin_beta_cycle_start_beta_2"
                else "beta_1"
            )

            cycle, active_cycle = create_beta_cycle(
                created_by=user_id,
                phase=phase,
                duration_days=7
            )

            if active_cycle:

                await query.message.reply_text(
                    (
                        "⚠️ Ya hay un ciclo beta activo.\n\n"
                        f"{format_beta_cycle_row(active_cycle)}"
                    ),
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            if not cycle:

                await query.message.reply_text(
                    "⚠️ No se pudo iniciar el ciclo beta.",
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            phase_label = "Beta 2.0" if phase == "beta_2" else "Beta cerrada"

            log_event(
                "beta_cycle_started",
                category="beta",
                severity="info",
                message=f"{phase_label} iniciada",
                actor_user_id=user_id,
                metadata={
                    "cycle_id": cycle[0],
                    "phase": phase,
                    "ends_at": str(cycle[5])
                }
            )

            await query.message.reply_text(
                (
                    f"✅ {phase_label} iniciada hasta {cycle[5]}.\n\n"
                    f"{format_beta_cycle_row(cycle)}"
                ),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data == "admin_beta_cycle_finish":

            cycle = complete_active_beta_cycle(
                notes="Finalizada manualmente desde el panel beta."
            )

            if not cycle:

                await query.message.reply_text(
                    "⚠️ No hay una beta activa para finalizar.",
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            log_event(
                "beta_cycle_completed",
                category="beta",
                severity="info",
                message="Ciclo beta finalizado manualmente",
                actor_user_id=user_id,
                metadata={
                    "cycle_id": cycle[0],
                    "phase": cycle[3]
                }
            )

            await query.message.reply_text(
                (
                    "✅ Beta finalizada.\n\n"
                    f"{format_beta_cycle_row(cycle)}"
                ),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data == "admin_beta_cycle_final_review":

            await query.message.reply_text(
                format_final_launch_checklist(),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


    if data.startswith("admin_smoke"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        if data == "admin_smoke_run":

            try:

                report = run_beta_smoke_checks()
                run = save_beta_smoke_run(user_id, report)

                log_event(
                    "beta_smoke_test_run",
                    category="beta",
                    severity="warning" if run["failed_checks"] else "info",
                    message=(
                        f"Smoke test beta ejecutado: "
                        f"{run['passed_checks']} OK, "
                        f"{run['warning_checks']} warnings/manuales, "
                        f"{run['failed_checks']} fallos"
                    ),
                    actor_user_id=user_id,
                    metadata={
                        "run_id": run["id"],
                        "total_checks": run["total_checks"],
                        "passed_checks": run["passed_checks"],
                        "failed_checks": run["failed_checks"],
                        "warning_checks": run["warning_checks"]
                    }
                )

                await query.message.reply_text(
                    format_beta_smoke_report(run),
                    reply_markup=build_beta_smoke_test_keyboard()
                )

            except Exception as e:

                log_event(
                    "beta_smoke_test_error",
                    category="beta",
                    severity="warning",
                    message="Error ejecutando Smoke Test Beta",
                    actor_user_id=user_id,
                    metadata={"error": str(e)}
                )

                await query.message.reply_text(
                    "⚠️ No se pudo ejecutar el Smoke Test Beta.",
                    reply_markup=build_beta_smoke_test_keyboard()
                )

            return


        if data == "admin_smoke_manual":

            await query.message.reply_text(
                format_beta_smoke_manual_checklist(),
                reply_markup=build_beta_smoke_test_keyboard()
            )

            return


        if data == "admin_smoke_last":

            try:

                run = get_last_beta_smoke_run()
                text = format_beta_smoke_report(run)

            except Exception as e:

                text = (
                    "🧪 Smoke Test Beta\n\n"
                    f"⚠️ No se pudo cargar el último resultado: {e}"
                )


            await query.message.reply_text(
                text,
                reply_markup=build_beta_smoke_test_keyboard()
            )

            return


        if data == "admin_smoke_clear":

            try:

                affected = clear_beta_smoke_runs()

                log_event(
                    "beta_smoke_test_results_cleared",
                    category="beta",
                    severity="info",
                    message=f"Resultados Smoke Test Beta limpiados: {affected}",
                    actor_user_id=user_id
                )

                await query.message.reply_text(
                    f"🧹 Resultados eliminados: {affected}",
                    reply_markup=build_beta_smoke_test_keyboard()
                )

            except Exception as e:

                await query.message.reply_text(
                    f"⚠️ No se pudieron limpiar los resultados: {e}",
                    reply_markup=build_beta_smoke_test_keyboard()
                )

            return


        await query.message.reply_text(
            "🧪 Smoke Test Beta",
            reply_markup=build_beta_smoke_test_keyboard()
        )

        return


    if data.startswith("admin_beta_monitor"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        if data == "admin_beta_monitor_resolve_all":

            affected = mark_beta_monitor_events_resolved(hours=24)

            await query.message.reply_text(
                f"✅ Eventos marcados como resueltos: {affected}",
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        title = "📊 Monitor beta"
        severity = None
        event_types = None


        if data == "admin_beta_monitor_critical":

            title = "🚨 Monitor beta · Críticos"
            severity = "critical"

        elif data == "admin_beta_monitor_warning":

            title = "⚠️ Monitor beta · Warnings"
            severity = "warning"

        elif data == "admin_beta_monitor_payments":

            title = "💳 Monitor beta · Pagos/accesos"
            event_types = [
                "payment_confirmed",
                "payment_failed",
                "invite_link_created",
                "invite_link_failed",
                "access_allowed",
                "unauthorized_access"
            ]

        elif data == "admin_beta_monitor_codes":

            title = "🎟 Monitor beta · Códigos"
            event_types = [
                "group_code_redeemed",
                "group_code_failed"
            ]

        elif data == "admin_beta_monitor_backups":

            title = "🛡 Monitor beta · Backups"
            event_types = [
                "backup_message_failed",
                "backup_permission_error"
            ]


        if data == "admin_beta_monitor":

            text = summarize_beta_monitor_events(hours=6)

        else:

            rows = list_beta_monitor_events(
                hours=24,
                severity=severity,
                event_types=event_types,
                limit=50
            )
            text = format_beta_monitor_events_text(
                title,
                rows
            )


        await query.message.reply_text(
            text,
            reply_markup=build_beta_monitor_keyboard()
        )

        return


    if data in (
        "admin_logs",
        "admin_logs_users",
        "admin_logs_payments",
        "admin_logs_security"
    ):

        group_ids = get_admin_group_ids(user_id, ["can_view_logs"])
        category_filter = None


        if data == "admin_logs_payments":

            category_filter = "payment"

        elif data == "admin_logs_security":

            category_filter = "access"

        elif data == "admin_logs_users":

            category_filter = "user"


        rows = list_recent_events(
            limit=50,
            group_ids=group_ids
        )


        if category_filter:

            rows = [
                row
                for row in rows
                if row[2] == category_filter
            ]


        if not rows:

            await query.message.reply_text(
                "📜 No hay logs registrados."
            )

            return


        text = (
            "📜 Logs del sistema\n\n"
            if group_ids is None
            else "📜 Logs de mi grupo\n\n"
        )


        for (
            created_at,
            event_type,
            category,
            severity,
            log_group_id,
            log_telegram_group_id,
            actor_user_id,
            target_user_id,
            message
        ) in rows[:30]:

            text += (
                f"Evento: {event_type or '-'}\n"
                f"Categoría: {category or '-'} / {severity or '-'}\n"
                f"Grupo: {log_group_id or '-'}"
                f" / {log_telegram_group_id or '-'}\n"
                f"Actor: {actor_user_id or '-'}\n"
                f"Usuario: {target_user_id or '-'}\n"
                f"Detalle: {message or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver", callback_data="menu_logs")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

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

                            SELECT COALESCE(telegram_group_id, group_id)
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
                            (user_id, group_id, telegram_group_id, invite_link)

                            VALUES (%s, %s, %s, %s)

                        """, (

                            user_id,
                            get_group_id(),
                            telegram_group_id,
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

        parts = data.split("_")


        if len(parts) < 3 or not parts[2].isdigit():

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        plan_id = int(parts[2])
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


    if data == "group_user_promo_redeem_start":

        await query.message.reply_text(
            "🎟 Código de comunidad\n\n"
            "El canje de códigos se hace desde la ficha de una comunidad concreta.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("group_user_promo_redeem_start_"):

        try:

            redeem_group_id = int(data.replace("group_user_promo_redeem_start_", "", 1))

        except Exception:

            await query.message.reply_text(
                "❌ Comunidad no válida.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return

        context.user_data["group_user_promo_waiting"] = "redeem_code"
        context.user_data["group_user_promo_redeem_group_id"] = redeem_group_id

        await query.message.reply_text(
            "🎟 Canjear código de esta comunidad\n\n"
            "Envía ahora el código de acceso. Solo será válido si pertenece a esta comunidad.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a comunidad", callback_data=f"marketplace_group_{redeem_group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("group_user_promo_confirm_"):

        try:

            code_id = int(data.replace("group_user_promo_confirm_", "", 1))

        except Exception:

            await query.message.reply_text(
                "❌ Código no válido.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        pending_code_id = context.user_data.get("group_user_promo_pending_code_id")


        if int(pending_code_id or 0) != code_id:

            await query.message.reply_text(
                "❌ No hay un código pendiente para confirmar.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                SELECT c.id,
                       c.group_id,
                       c.telegram_group_id,
                       c.owner_user_id,
                       c.code,
                       c.duration_days,
                       c.is_permanent,
                       c.max_uses,
                       c.used_count,
                       c.is_active,
                       c.expires_at,
                       g.name,
                       COALESCE(g.is_active, TRUE)
                FROM group_user_promo_codes c
                JOIN groups g
                ON g.id = c.group_id
                WHERE c.id=%s
                LIMIT 1

            """, (code_id,))

            promo_row = cur.fetchone()


        valid, error_message = validate_group_user_promo_row(promo_row)
        selected_group_id = context.user_data.get("group_user_promo_redeem_group_id")


        if valid and selected_group_id and int(promo_row[1]) != int(selected_group_id):

            valid = False
            error_message = "❌ Este código no pertenece a esta comunidad."


        if not valid:

            await query.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver a comunidad",
                        callback_data=f"marketplace_group_{selected_group_id}"
                        if selected_group_id
                        else "start_explore_groups"
                    )],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        try:

            await grant_group_user_promo_access(
                context,
                query.message.chat_id,
                query.from_user,
                promo_row
            )

            context.user_data.pop("group_user_promo_pending_code_id", None)
            context.user_data.pop("group_user_promo_waiting", None)
            context.user_data.pop("group_user_promo_redeem_group_id", None)

        except Exception as e:

            print("Error canjeando código de grupo:", e)

            await query.message.reply_text(
                "❌ Error canjeando el código.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
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
                    f"👁 Ver estado #{request_id}",
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
                    f"👁 Ver estado #{request_id}",
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
                    f"👁 Ver estado #{request_id}",
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

        clear_creator_onboarding_context(context)

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


    if data.startswith("creator_setup_reset_confirm_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_reset_confirm_"
        )
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        clear_creator_onboarding_context(context)

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE commercial_requests
                SET updated_at=NOW()
                WHERE id=%s

            """, (request_id,))


        await send_clean_message(
            context,
            query.message.chat_id,
            "🧹 Configuración reiniciada.\n\n"
            "La prueba y el cupo asignado se mantienen. Puedes continuar desde el panel.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔄 Recuperar configuración",
                    callback_data=f"configure_community_{request_id}"
                )],
                [InlineKeyboardButton(
                    "📡 Añadir grupo/canal",
                    callback_data=f"creator_setup_group_{request_id}"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_reset_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_reset_"
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
            "🧹 Reiniciar configuración\n\n"
            "Esto limpiará los pasos temporales abiertos en este chat, pero no borrará tu prueba, cupo ni solicitud comercial.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Confirmar reinicio",
                    callback_data=f"creator_setup_reset_confirm_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver a configuración",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
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
            expired_community_message(
                format_retention_days_left(request_row.get("delete_after"))
            ),
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
            "✅ Comunidad marcada con borrado definitivo.\n\n"
            "No se han borrado logs críticos, pero queda oculta, inactiva y fuera del marketplace.",
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
            "3️⃣ Espera 30 segundos.\n"
            "4️⃣ El bot detectará automáticamente el ID del grupo.\n"
            "5️⃣ Recibirás un mensaje privado para confirmar la vinculación.\n\n"
            "No necesitas usar bots externos para obtener el ID.\n\n"
            "Si quieres, puedes enviar aquí el link del grupo como referencia. "
            "El link no se usará para sacar el ID real; el ID real se detecta cuando añades el bot al grupo."
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
            "Paso 1: escribe el nombre público de tu comunidad.\n\n"
            "Ejemplo: GrupoStarsVip"
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


    if data.startswith("creator_setup_location_gate_"):

        request_id = extract_commercial_request_id(data, "creator_setup_location_gate_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Restricción por ubicación\n\n"
                "Primero debes vincular tu grupo o canal. Después podrás activar esta restricción.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )],
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        enabled, region_label = get_group_location_gate_display(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            "📍 Restricción por ubicación\n\n"
            f"Estado: {'Activada' if enabled else 'Desactivada'}\n"
            f"Región permitida: {region_label}\n\n"
            "Si está activada, antes de entrar el usuario deberá enviar ubicación desde el botón oficial de Telegram.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_gate_enable_"):

        request_id = extract_commercial_request_id(data, "creator_location_gate_enable_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=COALESCE(allowed_region, %s),
                    allowed_region_type=COALESCE(allowed_region_type, %s)
                WHERE id=%s

            """, (
                "ES",
                LOCATION_REGION_TYPE_COUNTRY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Restricción por ubicación activada.\n\n"
            "Puedes restringir por país. En España también puedes restringir por comunidad autónoma.\n\n"
            "Región permitida: España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_gate_disable_"):

        request_id = extract_commercial_request_id(data, "creator_location_gate_disable_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if group_id:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups
                    SET location_gate_enabled=FALSE
                    WHERE id=%s

                """, (group_id,))

                conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Restricción por ubicación desactivada.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_country_menu_"):

        request_id = extract_commercial_request_id(data, "creator_location_country_menu_")
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
            "🌎 Elegir país\n\n"
            "Puedes restringir por país. En España también puedes restringir por comunidad autónoma.",
            reply_markup=build_location_country_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_spain_region_menu_"):

        request_id = extract_commercial_request_id(data, "creator_location_spain_region_menu_")
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
            "🇪🇸 España\n\n"
            "Elige toda España o una comunidad autónoma concreta.",
            reply_markup=build_spanish_autonomous_community_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_country_set_"):

        payload = data.replace("creator_location_country_set_", "", 1)

        try:

            request_id_text, country_code = payload.split("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ País no válido."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if (
            country_code not in HISPANIC_COUNTRY_LABELS
            or not commercial_request_belongs_to_user(request_row, user_id)
        ):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                country_code,
                LOCATION_REGION_TYPE_COUNTRY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            f"Región permitida: {HISPANIC_COUNTRY_LABELS.get(country_code)}.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_spain_region_set_"):

        payload = data.replace("creator_location_spain_region_set_", "", 1)

        try:

            request_id_text, region_slug = payload.split("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad autónoma no válida."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if (
            region_slug not in SPANISH_AUTONOMOUS_COMMUNITY_LABELS
            or region_slug == "all_spain"
            or not commercial_request_belongs_to_user(request_row, user_id)
        ):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                region_slug,
                LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            f"Región permitida: {SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(region_slug)}, España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_region_cv_"):

        request_id = extract_commercial_request_id(data, "creator_location_region_cv_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                COMUNIDAD_VALENCIANA_REGION,
                LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            "Región permitida: Comunidad Valenciana, España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
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
                        f"👁 Ver estado #{request_id}",
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
                    f"👁 Ver estado #{request_id}",
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

    if data.startswith("group_"):

        log_event(
            "callback_unknown_group_prefixed",
            category="ui",
            severity="warning",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Callback con prefijo group_ no manejado por rutas específicas.",
            metadata={
                "callback_data": data
            }
        )

        await query.message.reply_text(
            "⚠️ Esta opción ya no está disponible o no está configurada.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return


    if is_legacy_callback(data):

        log_event(
            "legacy_callback_blocked",
            category="ui",
            severity="info",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Callback legacy bloqueado antes del fallback.",
            metadata={
                "callback_data": data
            }
        )

        await query.message.reply_text(
            "⚠️ Esta opción ya no está disponible o no está configurada.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return


    if not is_stripe_checkout_callback(data):

        log_event(
            "unknown_callback",
            category="ui",
            severity="info",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Callback desconocido o no configurado.",
            metadata={
                "callback_data": data
            }
        )

        await query.message.reply_text(
            "⚠️ Esta opción ya no está disponible o no está configurada.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return


    user_id = query.from_user.id

    group_id = context.user_data.get("selected_group")


    if not group_id:

        log_event(
            "checkout_callback_missing_group",
            category="payment",
            severity="warning",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Callback de checkout sin grupo seleccionado.",
            metadata={
                "callback_data": data
            }
        )

        await query.message.reply_text(
            "⚠️ Esta opción ya no está disponible o no está configurada.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return

    if group_requires_location_gate(group_id):

        await request_location_verification(
            context,
            query.message.chat_id,
            group_id,
            "checkout",
            price_id=data
        )

        return


    await create_checkout_for_user(
        context,
        query.message.chat_id,
        user_id,
        group_id,
        data
    )
