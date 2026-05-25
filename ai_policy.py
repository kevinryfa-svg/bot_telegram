import re


AI_ROLE_BUYER = "buyer"
AI_ROLE_OWNER = "owner"
AI_ROLE_GROUP_ADMIN = "group_admin"
AI_ROLE_SUPERADMIN = "superadmin"


AI_CONTEXT_PUBLIC_MARKETPLACE = "public_marketplace"
AI_CONTEXT_GROUP_DETAIL = "group_detail"
AI_CONTEXT_CHECKOUT_HELP = "checkout_help"
AI_CONTEXT_SUBSCRIPTION_HELP = "subscription_help"
AI_CONTEXT_SUPPORT_TICKET = "support_ticket"
AI_CONTEXT_OWNER_DASHBOARD = "owner_dashboard"
AI_CONTEXT_OWNER_PAYMENTS = "owner_payments"
AI_CONTEXT_OWNER_SURVEYS = "owner_surveys"
AI_CONTEXT_OWNER_USERS = "owner_users"
AI_CONTEXT_SUPERADMIN_DASHBOARD = "superadmin_dashboard"
AI_CONTEXT_USER_TRACKING = "user_tracking"
AI_CONTEXT_PAYMENT_DIAGNOSTICS = "payment_diagnostics"


SENSITIVE_KEYWORDS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "client_secret",
    "webhook_secret",
    "authorization",
    "password",
    "private_key",
    "invite_link",
    "checkout_url",
    "payment_url"
)


SENSITIVE_PATTERNS = (
    re.compile(r"(https://t\.me/\+)[A-Za-z0-9_-]+"),
    re.compile(r"(sk_live_)[A-Za-z0-9_]+"),
    re.compile(r"(sk_test_)[A-Za-z0-9_]+"),
    re.compile(r"(whsec_)[A-Za-z0-9_]+"),
    re.compile(r"([A-Za-z0-9_-]{24,})")
)


IMPLEMENTED_PAYMENT_METHODS = (
    "Stripe",
    "PayPal",
    "Revolut",
    "ChangeNOW.io / Cripto",
    "Guardarian / Tarjeta EUR → USDT",
    "Códigos y promociones"
)


def mask_sensitive_value(value):

    if value is None:
        return None

    text = str(value)

    if len(text) <= 8:
        return "***"

    return f"{text[:6]}***{text[-4:]}"


def sanitize_ai_text(text):

    safe_text = str(text or "")

    for pattern in SENSITIVE_PATTERNS:
        safe_text = pattern.sub(lambda match: mask_sensitive_value(match.group(0)), safe_text)

    return safe_text[:6000]


def sanitize_ai_metadata(metadata):

    if not isinstance(metadata, dict):
        return {}

    sanitized = {}

    for key, value in metadata.items():
        key_text = str(key)
        lower_key = key_text.lower()

        if any(keyword in lower_key for keyword in SENSITIVE_KEYWORDS):
            sanitized[key_text] = mask_sensitive_value(value)
        elif isinstance(value, dict):
            sanitized[key_text] = sanitize_ai_metadata(value)
        elif isinstance(value, (list, tuple)):
            sanitized[key_text] = [
                sanitize_ai_metadata(item) if isinstance(item, dict) else sanitize_ai_text(item)[:300]
                for item in value[:20]
            ]
        else:
            sanitized[key_text] = sanitize_ai_text(value)[:500]

    return sanitized


def build_ai_policy_prompt(role, context_key):

    return (
        "POLÍTICA INTERNA DE IA DEL BOT\n"
        f"Rol autorizado: {role}\n"
        f"Contexto: {context_key}\n\n"
        "Reglas obligatorias:\n"
        "- No reveles API keys, tokens, secrets, wallets completas, invite links completos ni URLs privadas completas.\n"
        "- No muestres datos de otros usuarios o comunidades si el rol no lo permite.\n"
        "- No inventes comunidades, precios, pagos, estados, permisos ni comandos.\n"
        "- Responde como asistente de este bot, no como chatbot genérico de internet.\n"
        "- Solo menciona métodos de pago implementados o activos en el contexto: Stripe, PayPal, Revolut, ChangeNOW.io / Cripto, Guardarian / Tarjeta EUR → USDT y códigos/promociones.\n"
        "- No menciones transferencias bancarias porque este bot no tiene ese proveedor.\n"
        "- No digas que el acceso se entrega por email/correo, bandeja de entrada o spam. El acceso se gestiona dentro del bot con Mis suscripciones, recuperar/reenviar enlace y soporte.\n"
        "- No listes criptomonedas concretas como disponibles salvo que el contexto de la comunidad lo confirme.\n"
        "- No inventes estados de pago. Si no hay estado real, indica que debe revisarse en el bot o soporte.\n"
        "- Si no tienes suficiente información, dilo claramente y ofrece soporte o la ruta del panel adecuada.\n"
        "- No concedas accesos, no marques pagos como pagados, no expulses, no banees y no cambies métodos de pago.\n"
        "- Puedes explicar, resumir, diagnosticar, sugerir pasos, preparar borradores y orientar al botón correcto.\n"
        "- Cualquier acción real debe hacerse por un flujo existente con confirmación humana.\n\n"
        "Formato recomendado:\n"
        "- Respuesta corta.\n"
        "- Pasos concretos.\n"
        "- Ruta o botón recomendado si existe.\n"
        "- Advertencia breve si hay riesgo."
    )
