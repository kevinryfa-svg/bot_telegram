SUPER_ADMIN_ONLY = "super_admin_only"


ADMIN_CALLBACK_PERMISSION_MAP = {

    "admin_back_main": (
        "can_view_users",
        "can_manage_users",
        "can_manage_codes",
        "can_manage_groups",
        "can_view_payments",
        "can_manage_payments",
        "can_view_stats",
        "can_view_logs"
    ),

    "menu_users": ("can_view_users", "can_manage_users"),
    "admin_users": ("can_view_users", "can_manage_users"),
    "admin_search_user": ("can_view_users", "can_manage_users"),
    "admin_users_help": ("can_view_users", "can_manage_users"),

    "admin_kick_user": ("can_manage_users",),
    "admin_ban_user": ("can_manage_users",),
    "admin_unban_user": ("can_manage_users",),
    "admin_reset_warnings": ("can_manage_users",),
    "admin_move_user": ("can_manage_users",),

    "menu_codes": ("can_manage_codes",),
    "admin_create_code": ("can_manage_codes",),
    "admin_codes": ("can_manage_codes",),
    "admin_delete_code": ("can_manage_codes",),

    "menu_groups": ("can_manage_groups",),
    "admin_add_group": ("can_manage_groups",),
    "admin_edit_group": ("can_manage_groups",),
    "admin_view_groups": ("can_manage_groups",),
    "admin_groups_help": ("can_manage_groups",),
    "cancel_create_group": ("can_manage_groups",),
    "view_group_plans": ("can_manage_groups",),
    "add_group_plan": ("can_manage_groups",),
    "edit_group_plan_select": ("can_manage_groups",),
    "delete_group_plan_select": ("can_manage_groups",),

    "menu_payments": ("can_view_payments", "can_manage_payments"),
    "admin_view_payments": ("can_view_payments", "can_manage_payments"),
    "admin_search_payment": ("can_view_payments", "can_manage_payments"),
    "admin_payments_help": ("can_view_payments", "can_manage_payments"),
    "admin_resend_access": ("can_manage_payments",),
    "admin_cancel_subscription": ("can_manage_payments",),

    "menu_business": ("can_view_stats",),
    "admin_stats": ("can_view_stats",),
    "admin_income": ("can_view_stats",),
    "admin_active_users": ("can_view_stats",),

    "menu_logs": ("can_view_logs",),
    "admin_logs": ("can_view_logs",),
    "admin_logs_users": ("can_view_logs",),
    "admin_logs_payments": ("can_view_logs",),
    "admin_logs_security": ("can_view_logs",),
    "admin_logs_help": ("can_view_logs",),

    "admin_revoke_links": (SUPER_ADMIN_ONLY,),
    "admin_resend_links": (SUPER_ADMIN_ONLY,)

}


ADMIN_CALLBACK_PREFIX_PERMISSION_MAP = (

    ("allow_user_", ("can_manage_users",)),
    ("deny_user_", ("can_manage_users",)),
    ("edit_group", ("can_manage_groups",)),
    ("edit_plan_", ("can_manage_groups",)),
    ("delete_group", ("can_manage_groups",)),
    ("delete_plan_", ("can_manage_groups",)),
    ("save_preview", ("can_manage_groups",)),
    ("cancel_preview", ("can_manage_groups",)),
    ("skip_preview", ("can_manage_groups",)),
    ("gen_", ("can_manage_codes",))

)


ADMIN_CALLBACK_PREFIXES = (

    "menu_",
    "admin_",
    "edit_group",
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
    "gen_",
    "cancel_create_group"

)


def get_required_permissions_for_callback(callback_data):

    if not callback_data:

        return ()


    if callback_data in ADMIN_CALLBACK_PERMISSION_MAP:

        return ADMIN_CALLBACK_PERMISSION_MAP[callback_data]


    for prefix, permissions in ADMIN_CALLBACK_PREFIX_PERMISSION_MAP:

        if callback_data.startswith(prefix):

            return permissions


    if is_admin_callback(callback_data):

        return (SUPER_ADMIN_ONLY,)


    return ()


def callback_requires_super_admin(callback_data):

    return SUPER_ADMIN_ONLY in get_required_permissions_for_callback(callback_data)


def is_admin_callback(callback_data):

    if not callback_data:

        return False


    if callback_data in ADMIN_CALLBACK_PERMISSION_MAP:

        return True


    return callback_data.startswith(ADMIN_CALLBACK_PREFIXES)
