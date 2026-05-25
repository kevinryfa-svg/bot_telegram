AI_INTENT_PAYMENT_HELP = "payment_help"
AI_INTENT_ACCESS_RECOVERY = "access_recovery"
AI_INTENT_SUBSCRIPTION_STATUS = "subscription_status"
AI_INTENT_GROUP_SETUP = "group_setup"
AI_INTENT_PAYMENT_PROVIDER_SETUP = "payment_provider_setup"
AI_INTENT_SURVEY_ANALYSIS = "survey_analysis"
AI_INTENT_USER_TRACKING_SUMMARY = "user_tracking_summary"
AI_INTENT_SUPPORT_REPLY_DRAFT = "support_reply_draft"
AI_INTENT_PRICING_ADVICE = "pricing_advice"
AI_INTENT_MARKETPLACE_COPY = "marketplace_copy"
AI_INTENT_DIAGNOSTICS = "diagnostics"
AI_INTENT_GENERAL_BOT_HELP = "general_bot_help"
AI_INTENT_UNKNOWN = "unknown"


INTENT_KEYWORDS = (
    (AI_INTENT_ACCESS_RECOVERY, ("no me llega", "link", "enlace", "entrar", "acceso", "pagué", "pague", "ya pagué", "ya pague")),
    (AI_INTENT_PAYMENT_PROVIDER_SETUP, ("método de pago", "metodo de pago", "paypal", "revolut", "stripe", "guardarian", "changenow", "usdt", "cripto", "sandbox", "live")),
    (AI_INTENT_PAYMENT_HELP, ("pagar", "pago", "tarjeta", "checkout", "precio", "cobro", "falló", "fallo")),
    (AI_INTENT_SUBSCRIPTION_STATUS, ("suscripción", "suscripcion", "mis accesos", "caduca", "renovar")),
    (AI_INTENT_GROUP_SETUP, ("configurar comunidad", "configurar grupo", "crear comunidad", "panel owner", "mis comunidades")),
    (AI_INTENT_SURVEY_ANALYSIS, ("encuesta", "satisfacción", "satisfaccion", "respuestas", "opinión", "opinion")),
    (AI_INTENT_USER_TRACKING_SUMMARY, ("seguimiento", "usuarios", "actividad", "conversion", "conversión")),
    (AI_INTENT_SUPPORT_REPLY_DRAFT, ("soporte", "ticket", "responder", "cliente", "captura")),
    (AI_INTENT_PRICING_ADVICE, ("precio", "plan", "planes", "tarifa", "mensual", "semanal")),
    (AI_INTENT_MARKETPLACE_COPY, ("marketplace", "catálogo", "catalogo", "texto", "descripción", "descripcion", "copy")),
    (AI_INTENT_DIAGNOSTICS, ("error", "diagnóstico", "diagnostico", "logs", "fallando", "callback", "traceback")),
    (AI_INTENT_GENERAL_BOT_HELP, ("ayuda", "qué puedo", "que puedo", "cómo funciona", "como funciona"))
)


def classify_ai_intent(question, context_key=None):

    text = str(question or "").strip().lower()

    if not text:
        return AI_INTENT_UNKNOWN

    context_text = str(context_key or "").lower()

    if "support" in context_text or "soporte" in context_text:
        if any(keyword in text for keyword in ("responde", "respuesta", "cliente", "ticket", "soporte")):
            return AI_INTENT_SUPPORT_REPLY_DRAFT

    for intent, keywords in INTENT_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return intent

    return AI_INTENT_GENERAL_BOT_HELP
