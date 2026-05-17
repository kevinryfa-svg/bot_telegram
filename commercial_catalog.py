# =========================
# COMMERCIAL CATALOG
# =========================

PRODUCT_SHARED_BOT_SPACE = "shared_bot_space"
PRODUCT_CUSTOM_BOT = "custom_bot"

CLIENT_STATUS_ACTIVE = "active"
CLIENT_STATUS_EXPIRED = "expired"
CLIENT_STATUS_GRACE_PERIOD = "grace_period"
CLIENT_STATUS_DISABLED = "disabled"
CLIENT_STATUS_ARCHIVED = "archived"

CLIENT_GRACE_PERIOD_DAYS = 15


# =========================
# CALLBACKS — PUBLIC MENU
# =========================

CALLBACK_EXPLORE_COMMUNITIES = "public_explore_communities"
CALLBACK_MY_ACCESS = "public_my_access"
CALLBACK_MONETIZE_COMMUNITY = "public_monetize_community"
CALLBACK_SUPPORT = "public_support"
CALLBACK_AI_HELP = "public_ai_help"
CALLBACK_ADMIN_PANEL = "public_admin_panel"

CALLBACK_SHARED_BOT_SPACE = "commercial_shared_bot_space"
CALLBACK_CUSTOM_BOT = "commercial_custom_bot"
CALLBACK_COMMERCIAL_CONTACT = "commercial_contact"
CALLBACK_COMMERCIAL_BACK = "commercial_back"


# =========================
# TEXTS
# =========================

PUBLIC_START_TEXT_ES = (
    "👋 Bienvenido\n\n"
    "Desde aquí puedes explorar comunidades privadas, gestionar tus accesos "
    "o descubrir soluciones para monetizar tu propia comunidad.\n\n"
    "Selecciona una opción:"
)

COMMERCIAL_MENU_TEXT_ES = (
    "🚀 Soluciones para comunidades\n\n"
    "Convierte tu comunidad privada en un sistema profesional con accesos automáticos, "
    "suscripciones, pagos, links seguros, soporte e IA.\n\n"
    "Elige cómo quieres empezar:"
)

COMMERCIAL_PRODUCTS = {
    PRODUCT_SHARED_BOT_SPACE: {
        "title_es": "📌 Publicar mi comunidad en este bot",
        "short_es": "La forma más rápida de empezar usando nuestro bot compartido.",
        "body_es": (
            "Tu comunidad aparece dentro de nuestro bot principal. "
            "Los usuarios podrán descubrirla, ver sus planes y comprar acceso desde este mismo bot. "
            "Es la opción más rápida para empezar con menos configuración. "
            "Si la suscripción del cliente caduca, la comunidad puede quedar desactivada o no visible. "
            "La configuración se conserva durante 15 días de gracia para poder reactivar."
        )
    },
    PRODUCT_CUSTOM_BOT: {
        "title_es": "🤖 Crear mi bot personalizado",
        "short_es": "La opción profesional con bot propio y marca propia.",
        "body_es": (
            "El cliente usa su propio bot de Telegram con marca, nombre y experiencia propia. "
            "El sistema gestiona accesos, suscripciones, pagos, links, usuarios, soporte, permisos e IA. "
            "Si la suscripción caduca, el bot personalizado puede quedar bloqueado o desactivado. "
            "La configuración se conserva durante 15 días de gracia para poder reanudar el servicio."
        )
    }
}

PUBLIC_MENU_BUTTONS = [
    {"text": "🔥 Explorar comunidades privadas", "callback_data": CALLBACK_EXPLORE_COMMUNITIES},
    {"text": "🎟 Gestionar mi acceso", "callback_data": CALLBACK_MY_ACCESS},
    {"text": "🚀 Soluciones para mi comunidad", "callback_data": CALLBACK_MONETIZE_COMMUNITY},
    {"text": "🛟 Soporte", "callback_data": CALLBACK_SUPPORT},
    {"text": "💬 Ayuda IA", "callback_data": CALLBACK_AI_HELP},
]

ADMIN_MENU_BUTTON = {
    "text": "⚙️ Panel de gestión",
    "callback_data": CALLBACK_ADMIN_PANEL
}


def get_public_menu_buttons(include_admin_panel=False):
    buttons = list(PUBLIC_MENU_BUTTONS)

    if include_admin_panel:
        buttons.append(ADMIN_MENU_BUTTON)

    return buttons


def get_commercial_product(product_type):
    return COMMERCIAL_PRODUCTS.get(product_type)


def get_commercial_product_text(product_type):
    product = get_commercial_product(product_type)

    if not product:
        return None

    return product.get("body_es")


def build_commercial_ai_context():
    return (
        "MODELO COMERCIAL DEL BOT:\n\n"
        "Hay dos productos comerciales:\n"
        "1. Espacio en bot compartido: el cliente publica su comunidad dentro del bot principal.\n"
        "2. Bot personalizado: el cliente usa su propio bot con marca propia.\n\n"
        "Ambos productos tienen 15 días de gracia después de caducar.\n"
        "La IA no debe inventar precios, enlaces de pago, teléfonos ni comandos.\n"
        "El panel de gestión solo debe presentarse a usuarios con permisos reales."
    )
