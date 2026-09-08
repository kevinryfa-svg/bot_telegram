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
ADMIN_MENU_SUPPORT = "support"
ADMIN_MENU_GROUP_ADMINS = "group_admins"
ADMIN_MENU_BACKUP = "backup_premium"
ADMIN_MENU_OWNER_COMMUNITIES = "owner_communities"
ADMIN_MENU_GLOBAL_PANEL = "global_panel"
ADMIN_MENU_OWNERS_PANEL = "owners_panel"
ADMIN_MENU_BETA_MONITOR = "beta_monitor"
ADMIN_MENU_BETA_SMOKE_TEST = "beta_smoke_test"
ADMIN_MENU_AD_PROMO = "ad_promo"


# Menú principal reorganizado en 6 bloques. Cada bloque abre un submenú
# (los destinos internos siguen siendo los callbacks existentes). Los paneles
# que antes estaban sueltos en el nivel superior (beta, promoción automática,
# smoke test, métodos de pago, etc.) viven ahora dentro de "Global del bot".

ADMIN_MENU_SECTIONS = [
    {
        "key": ADMIN_MENU_GLOBAL_PANEL,
        "text": "👑 Global del bot",
        "callback_data": "admin_global_panel",
        "permissions_any": [
            "super_admin_only"
        ]
    },
    {
        "key": ADMIN_MENU_OWNERS_PANEL,
        "text": "🧑‍💼 Propietarios y comunidades",
        "callback_data": "admin_block_owners",
        "permissions_any": [
            "can_manage_groups",
            "can_manage_plans",
            "can_manage_admins",
            "can_edit_group_texts",
            "can_edit_marketplace_preview"
        ]
    },
    {
        "key": ADMIN_MENU_USERS,
        "text": "👥 Usuarios y accesos",
        "callback_data": "admin_block_users",
        "permissions_any": [
            "can_view_users",
            "can_manage_users"
        ]
    },
    {
        "key": ADMIN_MENU_PAYMENTS,
        "text": "💳 Pagos y negocio",
        "callback_data": "admin_block_business",
        "permissions_any": [
            "can_view_payments",
            "can_manage_payments",
            "can_view_stats"
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
        "key": ADMIN_MENU_LOGS,
        "text": "📜 Logs",
        "callback_data": "menu_logs",
        "permissions_any": [
            "can_view_logs"
        ]
    }
]


# =========================
# LA TABLA DE AYUDAS QUE NO LLEVABA A NINGUNA AYUDA
# =========================
# Aquí vivían `ADMIN_HELP_CONTEXT_BY_CALLBACK` (19 entradas) y
# `get_help_context_for_admin_callback`. Se han borrado, y no por estar sin
# usar, que eso solo es sospechoso: es que sus valores —«admin_users»,
# «admin_codes», «admin_groups»…— no existen en ningún sitio. La ayuda del
# panel se sirve desde `ADMIN_CONTEXT_HELP_TEXTS` (global_panel, global_config,
# global_tools…) y las secciones del catálogo son SECTION_*. Ninguno de los 12
# contextos que mencionaba esta tabla tiene texto escrito.
#
# Enchufarla no habría dado ayuda: habría dado doce pantallas diciendo «esta
# ayuda todavía no está configurada». Se borra y así el siguiente que busque de
# dónde sale la ayuda del panel encuentra un solo sitio.


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



# =========================
# QUE NINGUNA PANTALLA DEL PANEL SEA UN CALLEJÓN
# =========================
# Varias pantallas del panel se enviaban con un `reply_text(texto)` pelado, sin
# un solo botón: salud de la plataforma, ingresos, últimos pagos. Desde ellas no
# se puede ni volver ni recargar, así que el operador tiene que teclear /admin
# otra vez — y en la de salud, que es la que se mira DOS veces (antes y después
# de arreglar algo), recargar es justo lo que hace falta.
#
# El botón de recargar reenvía el MISMO callback que trajo aquí: así una
# pantalla nueva no necesita nada más que pasar su propio nombre.

def build_admin_screen_keyboard(callback_de_esta_pantalla=None, extra=None):
    """Recargar (si se sabe cómo) y volver al panel. Nunca lanza."""

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    filas = list(extra or [])

    if callback_de_esta_pantalla:

        filas.append([InlineKeyboardButton(
            "🔄 Actualizar",
            callback_data=callback_de_esta_pantalla
        )])

    filas.append([InlineKeyboardButton(
        "⬅️ Volver al panel",
        callback_data="admin_back_main"
    )])

    return InlineKeyboardMarkup(filas)
