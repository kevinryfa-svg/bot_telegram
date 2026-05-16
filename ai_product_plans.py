from ai_permissions import (
    AI_PLAN_BASIC,
    AI_PLAN_PRO,
    AI_PLAN_PREMIUM,
    AI_PLAN_EXCLUSIVE
)


# =========================
# AI PRODUCT PLANS — DEFINITIONS
# =========================

AI_PRODUCT_PLANS = {

    AI_PLAN_BASIC: {
        "name": "Básico",
        "description": "IA limitada para soporte y generación sencilla de textos.",
        "recommended_for": "Grupos pequeños que solo necesitan ayuda básica.",
        "bot_mode": "shared",
        "includes": [
            "Soporte con IA limitado",
            "Generación de mensajes simples",
            "Ayuda con dudas frecuentes"
        ]
    },

    AI_PLAN_PRO: {
        "name": "Pro",
        "description": "IA para dueños de grupo dentro del bot compartido.",
        "recommended_for": "Dueños de grupos que quieren gestionar mejor su comunidad.",
        "bot_mode": "shared",
        "includes": [
            "Asistente para dueño de grupo",
            "Redacción de normas y mensajes",
            "Ayuda con promociones",
            "Soporte para usuarios",
            "Ideas de automatización"
        ]
    },

    AI_PLAN_PREMIUM: {
        "name": "Premium",
        "description": "IA avanzada para gestión de grupos con análisis y automatización.",
        "recommended_for": "Comunidades medianas o grandes.",
        "bot_mode": "shared",
        "includes": [
            "Todo lo del plan Pro",
            "Análisis de actividad",
            "Recomendaciones de retención",
            "Mensajes avanzados",
            "Asistencia para incidencias"
        ]
    },

    AI_PLAN_EXCLUSIVE: {
        "name": "Exclusivo",
        "description": "IA integrada en un bot propio creado por el cliente en BotFather.",
        "recommended_for": "Clientes que quieren marca propia y uso exclusivo.",
        "bot_mode": "exclusive",
        "includes": [
            "Bot propio del cliente",
            "IA personalizada",
            "Prompts adaptados a la marca",
            "Gestión exclusiva de grupos",
            "Opciones avanzadas de configuración"
        ]
    }
}


# =========================
# AI PRODUCT PLANS — HELPERS
# =========================

def get_ai_product_plan(plan):

    return AI_PRODUCT_PLANS.get(plan)



def list_ai_product_plans():

    return AI_PRODUCT_PLANS



def get_ai_plan_name(plan):

    product_plan = get_ai_product_plan(plan)

    if not product_plan:

        return "Sin IA"


    return product_plan.get(
        "name",
        "Sin IA"
    )



def get_ai_plan_bot_mode(plan):

    product_plan = get_ai_product_plan(plan)

    if not product_plan:

        return "disabled"


    return product_plan.get(
        "bot_mode",
        "disabled"
    )



def format_ai_plan_summary(plan):

    product_plan = get_ai_product_plan(plan)

    if not product_plan:

        return "IA no disponible en este plan."


    includes = product_plan.get(
        "includes",
        []
    )

    includes_text = "\n".join(
        f"• {item}" for item in includes
    )

    return (
        f"🤖 Plan IA: {product_plan['name']}\n\n"
        f"{product_plan['description']}\n\n"
        f"Recomendado para: {product_plan['recommended_for']}\n\n"
        f"Incluye:\n{includes_text}"
    )
