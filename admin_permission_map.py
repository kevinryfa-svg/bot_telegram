# =========================
# ADMIN PERMISSION MAP
# =========================

# This module centralizes which admin permissions are required for each
# callback family. It is intentionally independent from callback_router.py
# so the router can be split safely later.


ADMIN_CALLBACK_PERMISSION_MAP = {

    # =========================
    # USERS
    # =========================

    "menu_users": [
        "can_view_users",
        "can_manage_users"
    ],
    "admin_users": [
        "can_view_users",
        "can_manage_users"
    ],
    "admin_search_user": [
        "can_view_users",
        "can_manage_users"
    ],
    "admin_kick_user": [
        "can_kick_users",
        "can_manage_users"
    ],
    "admin_ban_user": [
        "can_ban_users",
        "can_manage_users"
    ],
    "admin_unban_user": [
        "can_unban_users",
        "can_manage_users"
    ],
    "admin_reset_warnings": [
        "can_reset_warnings",
        "can_manage_users"
    ],
    "admin_move_user": [
        "can_manage_users"
    ],

    # =========================
    # ACCESS / CODES
    # =========================

    "menu_codes": [
        "can_manage_codes"
    ],
    "admin_create_code": [
        "can_manage_codes"
    ],
    "admin_codes": [
        "can_manage_codes"
    ],
    "admin_delete_code": [
        "can_manage_codes"
    ],
    "admin_revoke_links": [
        "can_resend_links",
        "can_manage_codes"
    ],
    "admin_resend_links": [
        "can_resend_links",
        "can_manage_codes"
    ],
    "codigo": [],

    # =========================
    # GROUPS / PLANS
    # =========================

    "menu_groups": [
        "can_manage_groups"
    ],
    "admin_add_group": [
        "can_manage_groups"
    ],
    "admin_edit_group": [
        "can_manage_groups"
    ],
    "admin_view_groups": [
        "can_manage_groups"
    ],
    "edit_group_": [
        "can_manage_groups"
    ],
    "edit_group_name": [
        "can_manage_groups"
    ],
    "edit_group_preview": [
        "can_manage_groups"
    ],
    "edit_group_plans": [
        "can_manage_plans",
        "can_manage_groups"
    ],
    "edit_group_stripe": [
        "can_manage_payments",
        "can_manage_groups"
    ],
    "edit_group_admins": [
        "can_manage_admins"
    ],
    "view_group_plans": [
        "can_manage_plans",
        "can_manage_groups"
    ],
    "add_group_plan": [
        "can_manage_plans",
        "can_manage_groups"
    ],
    "edit_group_plan_select": [
        "can_manage_plans",
        "can_manage_groups"
    ],
    "delete_group_plan_select": [
        "can_manage_plans",
        "can_manage_groups"
    ],
    "delete_group_confirm": [
        "can_manage_groups"
    ],
    "delete_plan_": [
        "can_manage_plans",
        "can_manage_groups"
    ],
    "edit_plan_": [
        "can_manage_plans",
        "can_manage_groups"
    ],
    "save_preview": [
        "can_manage_groups"
    ],
    "cancel_preview": [
        "can_manage_groups"
    ],
    "skip_preview": [
        "can_manage_groups"
    ],

    # =========================
    # PAYMENTS / BUSINESS
    # =========================

    "menu_payments": [
        "can_view_payments",
        "can_manage_payments"
    ],
    "admin_view_payments": [
        "can_view_payments",
        "can_manage_payments"
    ],
    "admin_search_payment": [
        "can_view_payments",
        "can_manage_payments"
    ],
    "admin_resend_access": [
        "can_resend_links",
        "can_manage_payments"
    ],
    "admin_cancel_subscription": [
        "can_manage_payments"
    ],
    "menu_business": [
        "can_view_stats"
    ],
    "admin_stats": [
        "can_view_stats"
    ],
    "admin_active_users": [
        "can_view_stats",
        "can_view_users"
    ],
    "admin_income": [
        "can_view_stats",
        "can_view_payments"
    ],

    # =========================
    # LOGS
    # =========================

    "menu_logs": [
        "can_view_logs"
    ],
    "admin_logs": [
        "can_view_logs"
    ],
    "admin_logs_users": [
        "can_view_logs"
    ],
    "admin_logs_payments": [
        "can_view_logs"
    ],
    "admin_logs_security": [
        "can_view_logs"
    ],

    # =========================
    # ADMIN ROOT
    # =========================

    "admin_back_main": [
        "can_manage_users",
        "can_manage_codes",
        "can_manage_groups",
        "can_manage_payments",
        "can_view_stats",
        "can_view_logs"
    ],
    "public_admin_panel": [
        "can_manage_users",
        "can_manage_codes",
        "can_manage_groups",
        "can_manage_payments",
        "can_view_stats",
        "can_view_logs"
    ]
}


ADMIN_CALLBACK_PREFIXES = [
    "menu_",
    "admin_",
    "edit_group_",
    "view_group_plans",
    "add_group_plan",
    "edit_plan_",
    "delete_group",
    "delete_plan_",
    "save_preview",
    "cancel_preview",
    "skip_preview",
    "allow_user_",
    "deny_user_",
    "gen_"
]


# =========================
# HELPERS
# =========================

def is_admin_callback(callback_data):

    return callback_data.startswith(
        tuple(ADMIN_CALLBACK_PREFIXES)
    )



def get_required_permissions_for_callback(callback_data):

    if callback_data in ADMIN_CALLBACK_PERMISSION_MAP:

        return ADMIN_CALLBACK_PERMISSION_MAP[callback_data]


    matching_prefixes = sorted(
        ADMIN_CALLBACK_PERMISSION_MAP.keys(),
        key=len,
        reverse=True
    )


    for prefix in matching_prefixes:

        if callback_data.startswith(prefix):

            return ADMIN_CALLBACK_PERMISSION_MAP[prefix]


    if is_admin_callback(callback_data):

        return ["super_admin_only"]


    return []



def callback_requires_super_admin(callback_data):

    return get_required_permissions_for_callback(callback_data) == [
        "super_admin_only"
    ]
