from rbac import has_permission


# =========================
# ADMIN COMMAND SERVICE — PERMISSION CHECK
# =========================

def require_permission(user_id, group_id, permission):

    return has_permission(
        user_id,
        group_id,
        permission
    )


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
