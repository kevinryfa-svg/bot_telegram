# =========================
# AI CONTEXT BUILDER — SAFE TEXT HELPERS
# =========================

def safe_text(value, default=""):

    if value is None:

        return default


    return str(value)


# =========================
# AI CONTEXT BUILDER — ADMIN CONTEXT
# =========================

def build_admin_context(groups_count=None, users_count=None, active_subscriptions=None):

    parts = []


    if groups_count is not None:

        parts.append(
            f"Grupos registrados: {groups_count}"
        )


    if users_count is not None:

        parts.append(
            f"Usuarios registrados: {users_count}"
        )


    if active_subscriptions is not None:

        parts.append(
            f"Suscripciones activas: {active_subscriptions}"
        )


    return "\n".join(parts)


# =========================
# AI CONTEXT BUILDER — GROUP OWNER CONTEXT
# =========================

def build_group_owner_context(group_name=None, group_id=None, plan=None, users_count=None):

    parts = []


    if group_name:

        parts.append(
            f"Grupo: {group_name}"
        )


    if group_id:

        parts.append(
            f"ID interno del grupo: {group_id}"
        )


    if plan:

        parts.append(
            f"Plan contratado: {plan}"
        )


    if users_count is not None:

        parts.append(
            f"Usuarios del grupo: {users_count}"
        )


    return "\n".join(parts)


# =========================
# AI CONTEXT BUILDER — USER CONTEXT
# =========================

def build_group_user_context(group_name=None, subscription_status=None, expiration=None):

    parts = []


    if group_name:

        parts.append(
            f"Grupo: {group_name}"
        )


    if subscription_status:

        parts.append(
            f"Estado de suscripción: {subscription_status}"
        )


    if expiration:

        parts.append(
            f"Expiración: {expiration}"
        )


    return "\n".join(parts)


# =========================
# AI CONTEXT BUILDER — EXCLUSIVE BOT CONTEXT
# =========================

def build_exclusive_bot_context(bot_name=None, owner_id=None, group_name=None, plan=None):

    parts = []


    if bot_name:

        parts.append(
            f"Bot exclusivo: {bot_name}"
        )


    if owner_id:

        parts.append(
            f"Owner ID: {owner_id}"
        )


    if group_name:

        parts.append(
            f"Grupo principal: {group_name}"
        )


    if plan:

        parts.append(
            f"Plan: {plan}"
        )


    return "\n".join(parts)
