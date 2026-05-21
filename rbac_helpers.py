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
    "can_view_logs",
    "can_edit_group_texts",
    "can_edit_marketplace_preview",
    "can_respond_group_support"

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
    "can_view_logs": True,
    "can_edit_group_texts": True,
    "can_edit_marketplace_preview": True,
    "can_respond_group_support": True
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


def ensure_commercial_creator_profile(user_id):

    if not user_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO commercial_creator_profiles
            (
                user_id,
                group_quota,
                commercial_status,
                updated_at
            )
            VALUES (%s, 1, 'created', NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET updated_at=commercial_creator_profiles.updated_at
            RETURNING user_id,
                      group_quota,
                      commercial_status,
                      subscription_until

        """, (user_id,))

        row = cur.fetchone()


    return row


def sync_commercial_creator_profile_from_request(user_id):

    if not user_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO commercial_creator_profiles
            (
                user_id,
                group_quota,
                commercial_status,
                subscription_until,
                updated_at
            )
            SELECT user_id,
                   GREATEST(COALESCE(MAX(max_groups_allowed), 1), 1),
                   MAX(status),
                   MAX(commercial_subscription_until),
                   NOW()
            FROM commercial_requests
            WHERE user_id=%s
            GROUP BY user_id
            ON CONFLICT (user_id)
            DO UPDATE SET
                group_quota=GREATEST(
                    commercial_creator_profiles.group_quota,
                    EXCLUDED.group_quota
                ),
                commercial_status=COALESCE(
                    commercial_creator_profiles.commercial_status,
                    EXCLUDED.commercial_status
                ),
                subscription_until=COALESCE(
                    commercial_creator_profiles.subscription_until,
                    EXCLUDED.subscription_until
                ),
                updated_at=NOW()
            RETURNING user_id,
                      group_quota,
                      commercial_status,
                      subscription_until

        """, (user_id,))

        row = cur.fetchone()


    return row


def get_creator_group_quota(user_id):

    if not user_id:

        return 0


    if is_super_admin(user_id):

        return 999999


    profile_row = sync_commercial_creator_profile_from_request(user_id)


    if profile_row:

        return profile_row[1] or 1


    return 0


def get_creator_group_quota_source(user_id, request_row=None):

    if not user_id:

        return 0, "sin usuario"


    with conn.cursor() as cur:

        cur.execute("""

            SELECT group_quota
            FROM commercial_creator_profiles
            WHERE user_id=%s
            LIMIT 1

        """, (user_id,))

        row = cur.fetchone()


    if row:

        return row[0] or 1, "perfil"


    if request_row:

        return request_row.get("max_groups_allowed") or 1, "legacy"


    return get_creator_group_quota(user_id), "perfil"


def set_creator_group_quota(user_id, group_quota, commercial_status=None):

    if not user_id:

        return None


    group_quota = int(group_quota)


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO commercial_creator_profiles
            (
                user_id,
                group_quota,
                commercial_status,
                updated_at
            )
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                group_quota=EXCLUDED.group_quota,
                commercial_status=COALESCE(
                    EXCLUDED.commercial_status,
                    commercial_creator_profiles.commercial_status
                ),
                updated_at=NOW()
            RETURNING user_id,
                      group_quota,
                      commercial_status,
                      subscription_until

        """, (
            user_id,
            group_quota,
            commercial_status
        ))

        row = cur.fetchone()


    return row


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


def has_group_permission(user_id, group_id, permission):

    return has_permission(user_id, group_id, permission)


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


def expand_group_scope_permissions(permissions):

    expanded_permissions = []


    for permission in permissions:

        if permission not in expanded_permissions:

            expanded_permissions.append(permission)


        if permission == "can_manage_users":

            for scoped_permission in (
                "can_kick_users",
                "can_ban_users",
                "can_unban_users",
                "can_warn_users",
                "can_reset_warnings"
            ):

                if scoped_permission not in expanded_permissions:

                    expanded_permissions.append(scoped_permission)


    return expanded_permissions


def get_admin_group_ids(user_id, permissions=None):

    if is_super_admin(user_id):

        return None


    scoped_permissions = expand_group_scope_permissions(
        permissions or ALLOWED_PERMISSIONS
    )

    valid_permissions = [

        permission
        for permission in scoped_permissions
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


def get_group_owner_user_id(group_id):

    if not group_id:

        return None


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id
                FROM admins
                WHERE group_id=%s
                AND role=%s
                AND is_active=TRUE
                LIMIT 1

            """, (
                group_id,
                GROUP_OWNER
            ))

            row = cur.fetchone()


        return row[0] if row else None

    except Exception as e:

        print(
            "Error obteniendo owner del grupo:",
            e
        )

        return None


def user_owns_group(user_id, group_id):

    if not user_id or not group_id:

        return False


    if is_super_admin(user_id):

        return True


    owner_user_id = get_group_owner_user_id(group_id)


    return (
        owner_user_id is not None
        and int(owner_user_id) == int(user_id)
    )


def can_user_claim_telegram_group(user_id, telegram_group_id, commercial_request_id):

    if not user_id or not telegram_group_id:

        return False


    if is_super_admin(user_id):

        return True


    try:

        telegram_group_id = int(telegram_group_id)

    except Exception:

        return False


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       added_by
                FROM groups
                WHERE telegram_group_id=%s
                LIMIT 1

            """, (telegram_group_id,))

            group_row = cur.fetchone()


        if not group_row:

            return True


        group_id, added_by = group_row


        with conn.cursor() as cur:

            cur.execute("""

                SELECT id
                FROM commercial_requests
                WHERE id=%s
                AND user_id=%s
                AND (
                    approved_group_id=%s
                    OR approved_telegram_group_id=%s
                )
                LIMIT 1

            """, (
                commercial_request_id,
                user_id,
                group_id,
                telegram_group_id
            ))

            own_request_row = cur.fetchone()


        if own_request_row:

            return True


        if added_by is not None and int(added_by) == int(user_id):

            return True


        return user_owns_group(user_id, group_id)

    except Exception as e:

        print(
            "Error comprobando propiedad de grupo Telegram:",
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
