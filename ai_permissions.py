# =========================
# AI PERMISSIONS — SCOPES
# =========================

AI_SCOPE_ADMIN = "admin"
AI_SCOPE_GROUP_OWNER = "group_owner"
AI_SCOPE_GROUP_USER = "group_user"
AI_SCOPE_PUBLIC = "public"
AI_SCOPE_EXCLUSIVE_BOT_OWNER = "exclusive_bot_owner"


# =========================
# AI PERMISSIONS — FEATURES
# =========================

AI_FEATURE_ADMIN_ASSISTANT = "admin_assistant"
AI_FEATURE_GROUP_OWNER_ASSISTANT = "group_owner_assistant"
AI_FEATURE_USER_ASSISTANT = "user_assistant"
AI_FEATURE_PUBLIC_ASSISTANT = "public_assistant"
AI_FEATURE_EXCLUSIVE_BOT_ASSISTANT = "exclusive_bot_assistant"
AI_FEATURE_ANALYTICS = "analytics"
AI_FEATURE_TEXT_GENERATION = "text_generation"
AI_FEATURE_SUPPORT = "support"
AI_FEATURE_AUTOMATION_HELP = "automation_help"


# =========================
# AI PERMISSIONS — PLANS
# =========================

AI_PLAN_DISABLED = "disabled"
AI_PLAN_BASIC = "basic"
AI_PLAN_PRO = "pro"
AI_PLAN_PREMIUM = "premium"
AI_PLAN_EXCLUSIVE = "exclusive"


# =========================
# AI PERMISSIONS — PLAN FEATURES
# =========================

PLAN_FEATURES = {

    AI_PLAN_DISABLED: [],

    AI_PLAN_BASIC: [
        AI_FEATURE_TEXT_GENERATION,
        AI_FEATURE_SUPPORT
    ],

    AI_PLAN_PRO: [
        AI_FEATURE_TEXT_GENERATION,
        AI_FEATURE_SUPPORT,
        AI_FEATURE_GROUP_OWNER_ASSISTANT,
        AI_FEATURE_USER_ASSISTANT,
        AI_FEATURE_AUTOMATION_HELP
    ],

    AI_PLAN_PREMIUM: [
        AI_FEATURE_TEXT_GENERATION,
        AI_FEATURE_SUPPORT,
        AI_FEATURE_GROUP_OWNER_ASSISTANT,
        AI_FEATURE_USER_ASSISTANT,
        AI_FEATURE_ANALYTICS,
        AI_FEATURE_AUTOMATION_HELP
    ],

    AI_PLAN_EXCLUSIVE: [
        AI_FEATURE_TEXT_GENERATION,
        AI_FEATURE_SUPPORT,
        AI_FEATURE_GROUP_OWNER_ASSISTANT,
        AI_FEATURE_USER_ASSISTANT,
        AI_FEATURE_EXCLUSIVE_BOT_ASSISTANT,
        AI_FEATURE_ANALYTICS,
        AI_FEATURE_AUTOMATION_HELP
    ]
}


# =========================
# AI PERMISSIONS — SCOPE FEATURES
# =========================

SCOPE_ALLOWED_FEATURES = {

    AI_SCOPE_ADMIN: [
        AI_FEATURE_ADMIN_ASSISTANT,
        AI_FEATURE_GROUP_OWNER_ASSISTANT,
        AI_FEATURE_USER_ASSISTANT,
        AI_FEATURE_EXCLUSIVE_BOT_ASSISTANT,
        AI_FEATURE_ANALYTICS,
        AI_FEATURE_TEXT_GENERATION,
        AI_FEATURE_SUPPORT,
        AI_FEATURE_AUTOMATION_HELP
    ],

    AI_SCOPE_GROUP_OWNER: [
        AI_FEATURE_GROUP_OWNER_ASSISTANT,
        AI_FEATURE_ANALYTICS,
        AI_FEATURE_TEXT_GENERATION,
        AI_FEATURE_SUPPORT,
        AI_FEATURE_AUTOMATION_HELP
    ],

    AI_SCOPE_GROUP_USER: [
        AI_FEATURE_USER_ASSISTANT,
        AI_FEATURE_TEXT_GENERATION,
        AI_FEATURE_SUPPORT
    ],

    AI_SCOPE_PUBLIC: [
        AI_FEATURE_PUBLIC_ASSISTANT,
        AI_FEATURE_SUPPORT
    ],

    AI_SCOPE_EXCLUSIVE_BOT_OWNER: [
        AI_FEATURE_EXCLUSIVE_BOT_ASSISTANT,
        AI_FEATURE_GROUP_OWNER_ASSISTANT,
        AI_FEATURE_USER_ASSISTANT,
        AI_FEATURE_ANALYTICS,
        AI_FEATURE_TEXT_GENERATION,
        AI_FEATURE_SUPPORT,
        AI_FEATURE_AUTOMATION_HELP
    ]
}


# =========================
# AI PERMISSIONS — HELPERS
# =========================

def normalize_ai_plan(plan):

    plan = str(plan or "").strip().lower()

    if plan in PLAN_FEATURES:

        return plan


    return AI_PLAN_DISABLED



def normalize_ai_scope(scope):

    scope = str(scope or "").strip().lower()

    if scope in SCOPE_ALLOWED_FEATURES:

        return scope


    return AI_SCOPE_PUBLIC



def get_plan_features(plan):

    return PLAN_FEATURES.get(
        normalize_ai_plan(plan),
        []
    )



def get_scope_features(scope):

    return SCOPE_ALLOWED_FEATURES.get(
        normalize_ai_scope(scope),
        []
    )



def ai_plan_allows_feature(plan, feature):

    return feature in get_plan_features(plan)



def ai_scope_allows_feature(scope, feature):

    return feature in get_scope_features(scope)



def can_use_ai_feature(plan, scope, feature):

    return (
        ai_plan_allows_feature(plan, feature)
        and ai_scope_allows_feature(scope, feature)
    )



def explain_ai_denial(plan, scope, feature):

    if not ai_plan_allows_feature(plan, feature):

        return "❌ Tu plan actual no incluye esta función de IA."


    if not ai_scope_allows_feature(scope, feature):

        return "❌ No tienes permisos para usar esta función de IA."


    return "❌ No se puede usar esta función de IA."
