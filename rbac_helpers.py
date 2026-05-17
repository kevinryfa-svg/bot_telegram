from bot_config import ADMIN_ID
from db import conn


GROUP_OWNER = "GROUP_OWNER"


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


GROUP_OWNER_PERMISSIONS = {
    "can_manage_users": True,
    "can_kick_users": True,
    "can_ban_users": True,
    "can_unban_users": True,
    "can_warn_users": True,
    "can_reset_warnings": True,
    "can_resend_links": True,
    "can_recover_access": True,
    "can_manage_codes": False,
    "can_manage_groups": True,
    "can_manage_plans": True,
    "can_manage_payments": False,
    "can_manage_admins": True,
    "can_view_users": True,
    "can_view_payments": True,
    "can_view_stats": True,
    "can_view_logs": True
}


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


def get_admin_group_ids(user_id, permissions=None):

    if is_super_admin(user_id):

        return None


    valid_permissions = [

        permission
        for permission in (permissions or ALLOWED_PERMISSIONS)
        if permission in ALLOWED_PERMISSIONS

    ]


    if not valid_permissions:

        return []


    permission_conditions = " OR ".join(

        f"{permission}=TRUE"
        for permission in valid_permissions

    )


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT DISTINCT group_id
                FROM admins
                WHERE user_id=%s
                AND is_active=TRUE
                AND group_id IS NOT NULL
                AND group_id != 0
                AND ({permission_conditions})
                ORDER BY group_id ASC

            """, (user_id,))

            rows = cur.fetchall()


        return [
            row[0]
            for row in rows
        ]

    except Exception as e:

        print(
            "Error obteniendo grupos admin:",
            e
        )

        return []


def assign_group_owner_permissions(user_id, group_id):

    if not user_id or not group_id:

        return False


    columns = [
        "user_id",
        "group_id",
        "role",
        "is_super_admin",
        *GROUP_OWNER_PERMISSIONS.keys(),
        "is_active"
    ]

    values = [
        user_id,
        group_id,
        GROUP_OWNER,
        False,
        *GROUP_OWNER_PERMISSIONS.values(),
        True
    ]

    placeholders = ", ".join(["%s"] * len(columns))
    update_columns = [
        "role",
        "is_super_admin",
        *GROUP_OWNER_PERMISSIONS.keys(),
        "is_active"
    ]
    update_set = ", ".join(
        f"{column}=EXCLUDED.{column}"
        for column in update_columns
    )


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                INSERT INTO admins
                ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT (user_id, group_id)
                DO UPDATE SET {update_set}

            """, values)


        return True

    except Exception as e:

        print(
            "Error asignando GROUP_OWNER:",
            e
        )

        return False


def assign_pending_commercial_owner_for_group(group_id, telegram_group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT commercial_requests.id,
                       commercial_requests.user_id,
                       commercial_requests.requested_public_visibility
                FROM commercial_requests
                WHERE user_id IS NOT NULL
                AND (
                    approved_group_id=%s
                    OR approved_telegram_group_id=%s
                )
                ORDER BY reviewed_at DESC NULLS LAST,
                         created_at DESC

            """, (
                group_id,
                telegram_group_id
            ))

            rows = cur.fetchall()


        assigned = 0


        for request_id, owner_user_id, public_visibility in rows:

            if assign_group_owner_permissions(owner_user_id, group_id):

                assigned += 1

                with conn.cursor() as cur:

                    cur.execute("""

                        UPDATE commercial_requests
                        SET approved_group_id=%s,
                            approved_telegram_group_id=%s,
                            updated_at=NOW()
                        WHERE id=%s

                    """, (
                        group_id,
                        telegram_group_id,
                        request_id
                    ))


                if public_visibility:

                    with conn.cursor() as cur:

                        cur.execute("""

                            UPDATE groups
                            SET public_visibility=%s
                            WHERE id=%s

                        """, (
                            public_visibility,
                            group_id
                        ))


        return assigned

    except Exception as e:

        print(
            "Error asignando owner comercial pendiente:",
            e
        )

        return 0
