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
CALLBACK_COMMERCIAL_BACK_START = "commercial_back_start"
CALLBACK_COMMERCIAL_BACK_SOLUTIONS = "commercial_back_solutions"
CALLBACK_SHARED_TRIAL_START = "commercial_shared_trial_start"
CALLBACK_CUSTOM_BOT_START = "commercial_custom_bot_start"
CALLBACK_COMMERCIAL_HELP = "commercial_help"

CALLBACK_SUBSCRIPTIONS_HELP = "subscriptions_help"
CALLBACK_GROUP_PLANS_HELP = "group_plans_help"
CALLBACK_SUPPORT_HELP = "support_help"
CALLBACK_ADMIN_USERS_HELP = "admin_users_help"
CALLBACK_ADMIN_GROUPS_HELP = "admin_groups_help"
CALLBACK_ADMIN_PAYMENTS_HELP = "admin_payments_help"
CALLBACK_ADMIN_LOGS_HELP = "admin_logs_help"


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
            "Los usuarios podrán descubrirla y ver sus condiciones de acceso desde este mismo bot. "
            "Es la opción más rápida para empezar con menos configuración. "
            "Si la suscripción del cliente caduca, la comunidad puede quedar desactivada o no visible. "
            "Puedes probar esta opción durante 1 día. Si después decides continuar, activas una suscripción. Si más adelante la suscripción se detiene, guardaremos la configuración durante 15 días para que puedas reactivar sin empezar desde cero."
        )
    },
    PRODUCT_CUSTOM_BOT: {
        "title_es": "🤖 Crear mi bot personalizado",
        "short_es": "La opción profesional con bot propio y marca propia.",
        "body_es": (
            "El cliente usa su propio bot de Telegram con marca, nombre y experiencia propia. "
            "El sistema gestiona accesos, suscripciones, pagos, links, usuarios, soporte, permisos e IA. "
            "Si la suscripción caduca, el bot personalizado puede quedar bloqueado o desactivado. "
            "Esta opción no tiene prueba gratuita. Primero se configura el bot completo y, después del pago, se activa. Si más adelante la suscripción se detiene, guardaremos la configuración durante 15 días para que puedas reanudar el servicio sin perder lo preparado."
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
        "En el producto de comunidad compartida hay una prueba de 1 día. "
        "La prueba se solicita desde el menú comercial y debe aprobarla el propietario o super admin antes de activarse. "
        "Tras aprobarla, la comunidad puede configurarse como grupo gratuito o de pago. "
        "Un grupo gratuito no cobra a los usuarios, pero el acceso sigue protegido por el bot. "
        "Durante la prueba no debe bloquearse al creador por pago, precio ni stripe_price_id. "
        "Primero debe terminar la configuración de la comunidad, el grupo o canal, los textos y el tipo de acceso. "
        "Para mantener la comunidad publicada después de la prueba, el creador deberá activar una suscripción del servicio. "
        "Si será de pago, los cobros deben ir a la propia cuenta o sistema de cobro del creador; la plataforma no recibe el dinero de su comunidad.\n"
        "El panel de configuración del creador permite guardar grupo/canal, textos, Stripe propio y planes durante la prueba. "
        "Para Stripe propio debe explicar dónde encontrar STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET y, si existe, STRIPE_PUBLISHABLE_KEY. "
        "Nunca debe inventar claves, pedir que se compartan fuera del bot ni mostrar claves completas. "
        "El price_id de cada plan se obtiene en Stripe al crear un producto/precio y pertenece al Stripe del creador, no al Stripe global del bot. "
        "Si todavía no hay groups.id real, los planes quedan pendientes porque la tabla actual de planes necesita un grupo publicado/asociado. "
        "El bot debe ser añadido al grupo/canal y tener permisos de administrador para gestionar accesos.\n"
        "Los planes comerciales previstos para el espacio compartido son 1 mes, 6 meses y 1 año. "
        "Si un plan futuro no tiene precio o stripe_price_id, debe decirse que está pendiente de configurar por un administrador, pero no debe presentarse como bloqueo durante la prueba.\n"
        "El bot personalizado no tiene prueba gratuita. "
        "Primero se aprueba y configura el bot, y se activa tras completar el pago. "
        "Si una suscripción se detiene, la configuración se guarda durante 15 días antes de archivarse.\n"
        "La IA no debe inventar precios, tiempos exactos de respuesta, enlaces de pago, teléfonos ni comandos.\n"
        "El panel de gestión solo debe presentarse a usuarios con permisos reales."
    )
