from bot_config import ADMIN_ID
from db import conn


ALLOWED_PERMISSIONS = [

    "can_manage_users",
    "can_kick_users",
    "can_ban_users",
    "can_unban_users",
    "can_warn_users",
    "can_reset_warnings",
    "can_resend_links",
    "can_recover_access",
    "can_manage_codes",
    "can_manage_groups",
    "can_manage_plans",
    "can_manage_payments",
    "can_manage_admins",
    "can_view_users",
    "can_view_payments",
    "can_view_stats",
    "can_view_logs"

]


# =========================
# RBAC — SUPER ADMIN
# =========================

def is_super_admin(user_id):

    if int(user_id) == ADMIN_ID:

        return True


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id
                FROM admins
                WHERE user_id=%s
                AND is_super_admin=TRUE
                AND is_active=TRUE

                LIMIT 1

            """, (user_id,))

            row = cur.fetchone()


        if row:

            return True

    except Exception as e:

        print(
            "Error comprobando super admin:",
            e
        )


    return False


# =========================
# RBAC — PERMISOS
# =========================

def has_permission(user_id, group_id, permission):

    if is_super_admin(user_id):

        return True


    if permission not in ALLOWED_PERMISSIONS:

        print(
            "Permiso no válido:",
            permission
        )

        return False


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT {permission}
                FROM admins
                WHERE user_id=%s
                AND group_id=%s
                AND is_active=TRUE

                LIMIT 1

            """, (

                user_id,
                group_id

            ))

            row = cur.fetchone()


        if row and row[0] is True:

            return True

    except Exception as e:

        print(
            "Error comprobando permiso:",
            e
        )


    return False


def has_any_permission_any_group(user_id, permissions):

    if is_super_admin(user_id):

        return True


    valid_permissions = [

        permission
        for permission in permissions
        if permission in ALLOWED_PERMISSIONS

    ]


    if not valid_permissions:

        return False


    permission_conditions = " OR ".join(

        f"{permission}=TRUE"
        for permission in valid_permissions

    )


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT id
                FROM admins
                WHERE user_id=%s
                AND is_active=TRUE
                AND ({permission_conditions})

                LIMIT 1

            """, (user_id,))

            row = cur.fetchone()


        if row:

            return True

    except Exception as e:

        print(
            "Error comprobando permisos:",
            e
        )


    return False
