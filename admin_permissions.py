# =========================
# ADMIN PERMISSIONS — PRESETS
# =========================

PERMISSION_COLUMNS = [

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


ROLE_PRESETS = {

    "OWNER": [

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

    ],

    "MOD_SECURITY": [

        "can_manage_users",
        "can_kick_users",
        "can_ban_users",
        "can_unban_users",
        "can_warn_users",
        "can_reset_warnings",
        "can_view_users",
        "can_view_logs"

    ],

    "MOD_SUPPORT": [

        "can_resend_links",
        "can_recover_access",
        "can_view_users",
        "can_view_logs"

    ],

    "MOD_WARNING": [

        "can_warn_users",
        "can_reset_warnings",
        "can_view_users",
        "can_view_logs"

    ],

    "VIEWER": [

        "can_view_users",
        "can_view_payments",
        "can_view_stats",
        "can_view_logs"

    ]

}


# =========================
# ADMIN PERMISSIONS — HELPERS
# =========================

def normalize_role(role):

    if not role:

        return "VIEWER"


    role = str(role).strip().upper()


    if role not in ROLE_PRESETS:

        return "VIEWER"


    return role



def permissions_for_role(role):

    role = normalize_role(role)

    allowed = ROLE_PRESETS.get(
        role,
        []
    )


    return {

        permission: permission in allowed
        for permission in PERMISSION_COLUMNS

    }



def available_roles():

    return list(
        ROLE_PRESETS.keys()
    )
