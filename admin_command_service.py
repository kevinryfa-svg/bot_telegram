from bot_config import ADMIN_ID
from rbac import has_permission, is_super_admin


# =========================
# ADMIN COMMAND SERVICE — SUPER ADMIN CHECK
# =========================

def is_admin_user(user_id):

    return is_super_admin(
        user_id,
        ADMIN_ID
    )


# =========================
# ADMIN COMMAND SERVICE — PERMISSION CHECK
# =========================

def require_permission(user_id, group_id, permission):

    return has_permission(
        user_id,
        group_id,
        permission,
        ADMIN_ID
    )


async def deny_if_missing_permission(update, user_id, group_id, permission):

    if require_permission(
        user_id,
        group_id,
        permission
    ):

        return False


    message = update.message

    if not message and update.callback_query:

        message = update.callback_query.message


    if message:

        await message.reply_text(
            permission_denied_text(permission)
        )


    return True


# =========================
# ADMIN COMMAND SERVICE — DENY TEXT
# =========================

def permission_denied_text(permission=None):

    if permission:

        return f"❌ No tienes permiso para esta acción.\nPermiso requerido: {permission}"


    return "❌ No tienes permiso para esta acción."


# =========================
# ADMIN COMMAND SERVICE — PARSE IDS
# =========================

def parse_int(value):

    try:

        return int(str(value).strip())

    except Exception:

        return None



def parse_command_args(text):

    if not text:

        return []


    return str(text).strip().split()


# =========================
# ADMIN COMMAND SERVICE — SAFE GROUP TARGET
# =========================

def resolve_command_group(default_group_id, provided_group_id=None):

    if provided_group_id is None:

        return default_group_id


    parsed = parse_int(
        provided_group_id
    )


    if parsed is None:

        return default_group_id


    return parsed
