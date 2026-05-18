# =========================
# ADMIN MENU CATALOG
# =========================

# This module defines the admin panel sections independently from Telegram.
# It returns plain dictionaries so callback_router.py or future admin modules
# can convert them into InlineKeyboardButton rows without duplicating rules.


ADMIN_MENU_USERS = "users"
ADMIN_MENU_CODES = "codes"
ADMIN_MENU_GROUPS = "groups"
ADMIN_MENU_PAYMENTS = "payments"
ADMIN_MENU_BUSINESS = "business"
ADMIN_MENU_LOGS = "logs"
ADMIN_MENU_COMMERCIAL = "commercial"
ADMIN_MENU_SUPPORT = "support"


ADMIN_MENU_SECTIONS = [
    {
        "key": ADMIN_MENU_USERS,
        "text": "👥 Gestión Usuarios",
        "callback_data": "menu_users",
        "permissions_any": [
            "can_view_users",
            "can_manage_users"
        ]
    },
    {
        "key": ADMIN_MENU_CODES,
        "text": "🎟️ Gestión Accesos",
        "callback_data": "menu_codes",
        "permissions_any": [
            "can_manage_codes"
        ]
    },
    {
        "key": ADMIN_MENU_GROUPS,
        "text": "📦 Gestión Grupos",
        "callback_data": "menu_groups",
        "permissions_any": [
            "can_manage_groups",
            "can_manage_plans"
        ]
    },
    {
        "key": ADMIN_MENU_PAYMENTS,
        "text": "💳 Gestión Pagos",
        "callback_data": "menu_payments",
        "permissions_any": [
            "can_view_payments",
            "can_manage_payments"
        ]
    },
    {
        "key": ADMIN_MENU_BUSINESS,
        "text": "📊 Gestión Negocio",
        "callback_data": "menu_business",
        "permissions_any": [
            "can_view_stats"
        ]
    },
    {
        "key": ADMIN_MENU_LOGS,
        "text": "📜 Logs",
        "callback_data": "menu_logs",
        "permissions_any": [
            "can_view_logs"
        ]
    },
    {
        "key": ADMIN_MENU_SUPPORT,
        "text": "🛟 Soporte",
        "callback_data": "admin_support_tickets",
        "permissions_any": [
            "super_admin_only"
        ]
    },
    {
        "key": ADMIN_MENU_COMMERCIAL,
        "text": "📩 Solicitudes comerciales",
        "callback_data": "admin_commercial_requests",
        "permissions_any": [
            "super_admin_only"
        ]
    },
    {
        "key": "commercial_promo_codes",
        "text": "🎟 Códigos promocionales",
        "callback_data": "admin_commercial_promo_codes",
        "permissions_any": [
            "super_admin_only"
        ]
    }
]


# =========================
# ADMIN MENU — HELP CONTEXTS
# =========================

ADMIN_HELP_CONTEXT_BY_CALLBACK = {
    "menu_users": "admin_users",
    "menu_codes": "admin_codes",
    "menu_groups": "admin_groups",
    "menu_payments": "admin_payments",
    "menu_business": "admin_business",
    "menu_logs": "admin_logs",
    "admin_commercial_requests": "commercial_admin",
    "admin_commercial_promo_codes": "commercial_admin",
    "admin_support_tickets": "support_admin"
}


# =========================
# HELPERS
# =========================

def user_has_any_permission(permissions, required_permissions):

    if not required_permissions:

        return False


    if "super_admin_only" in required_permissions:

        return False


    return any(
        permissions.get(permission) is True
        for permission in required_permissions
    )



def get_admin_menu_sections(permissions=None, is_super_admin=False):

    permissions = permissions or {}

    sections = []


    for section in ADMIN_MENU_SECTIONS:

        required_permissions = section.get(
            "permissions_any",
            []
        )


        if is_super_admin:

            sections.append(section)
            continue


        if user_has_any_permission(
            permissions,
            required_permissions
        ):

            sections.append(section)


    return sections



def build_admin_menu_button_rows(permissions=None, is_super_admin=False):

    return [
        [
            {
                "text": section["text"],
                "callback_data": section["callback_data"]
            }
        ]
        for section in get_admin_menu_sections(
            permissions=permissions,
            is_super_admin=is_super_admin
        )
    ]



def get_help_context_for_admin_callback(callback_data):

    return ADMIN_HELP_CONTEXT_BY_CALLBACK.get(callback_data)
