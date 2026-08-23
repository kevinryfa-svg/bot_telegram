SUPER_ADMIN_ONLY = "super_admin_only"


ADMIN_CALLBACK_PERMISSION_MAP = {

    "admin_back_main": (
        "can_view_users",
        "can_manage_users",
        "can_manage_codes",
        "can_manage_groups",
        "can_manage_admins",
        "can_manage_plans",
        "can_view_payments",
        "can_manage_payments",
        "can_view_stats",
        "can_view_logs"
    ),

    "menu_users": ("can_view_users", "can_manage_users"),
    "admin_users": ("can_view_users", "can_manage_users"),
    "admin_search_user": ("can_view_users", "can_manage_users"),
    "admin_users_help": ("can_view_users", "can_manage_users"),

    "admin_kick_user": ("can_kick_users", "can_manage_users"),
    "admin_ban_user": ("can_ban_users", "can_manage_users"),
    "admin_unban_user": ("can_unban_users", "can_manage_users"),
    "admin_reset_warnings": ("can_reset_warnings", "can_manage_users"),
    "admin_move_user": (SUPER_ADMIN_ONLY,),

    "menu_codes": (SUPER_ADMIN_ONLY,),
    "admin_create_code": (SUPER_ADMIN_ONLY,),
    "admin_codes": (SUPER_ADMIN_ONLY,),
    "admin_delete_code": (SUPER_ADMIN_ONLY,),
    "admin_group_user_codes": (SUPER_ADMIN_ONLY,),

    "menu_groups": (
        "can_manage_groups",
        "can_manage_plans",
        "can_manage_codes",
        "can_manage_admins",
        "can_edit_group_texts",
        "can_edit_marketplace_preview"
    ),
    "admin_add_group": (SUPER_ADMIN_ONLY,),
    "admin_edit_group": (
        "can_manage_groups",
        "can_manage_plans",
        "can_manage_codes",
        "can_manage_admins",
        "can_edit_group_texts",
        "can_edit_marketplace_preview"
    ),
    "admin_view_groups": (
        "can_manage_groups",
        "can_manage_plans",
        "can_manage_codes",
        "can_manage_admins",
        "can_edit_group_texts",
        "can_edit_marketplace_preview"
    ),
    "admin_groups_help": (
        "can_manage_groups",
        "can_manage_plans",
        "can_manage_codes",
        "can_manage_admins",
        "can_edit_group_texts",
        "can_edit_marketplace_preview"
    ),
    "cancel_create_group": (SUPER_ADMIN_ONLY,),
    "view_group_plans": ("can_manage_groups", "can_manage_plans"),
    "add_group_plan": ("can_manage_groups", "can_manage_plans"),
    "edit_group_plan_select": ("can_manage_groups", "can_manage_plans"),
    "delete_group_plan_select": ("can_manage_groups", "can_manage_plans"),

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

    "admin_beta_monitor": (SUPER_ADMIN_ONLY,),
    "admin_beta_monitor_24h": (SUPER_ADMIN_ONLY,),
    "admin_beta_monitor_critical": (SUPER_ADMIN_ONLY,),
    "admin_beta_monitor_warning": (SUPER_ADMIN_ONLY,),
    "admin_beta_monitor_payments": (SUPER_ADMIN_ONLY,),
    "admin_beta_monitor_access": (SUPER_ADMIN_ONLY,),
    "admin_beta_monitor_codes": (SUPER_ADMIN_ONLY,),
    "admin_beta_monitor_backups": (SUPER_ADMIN_ONLY,),
    "admin_beta_monitor_resolve_all": (SUPER_ADMIN_ONLY,),
    "admin_beta_cycle": (SUPER_ADMIN_ONLY,),
    "admin_beta_cycle_start_beta_1": (SUPER_ADMIN_ONLY,),
    "admin_beta_cycle_start_beta_2": (SUPER_ADMIN_ONLY,),
    "admin_beta_cycle_finish": (SUPER_ADMIN_ONLY,),
    "admin_beta_cycle_status": (SUPER_ADMIN_ONLY,),
    "admin_beta_cycle_final_review": (SUPER_ADMIN_ONLY,),

    "admin_smoke_test": (SUPER_ADMIN_ONLY,),
    "admin_smoke_run": (SUPER_ADMIN_ONLY,),
    "admin_smoke_manual": (SUPER_ADMIN_ONLY,),
    "admin_smoke_last": (SUPER_ADMIN_ONLY,),
    "admin_smoke_clear": (SUPER_ADMIN_ONLY,),

    "admin_global_panel": (SUPER_ADMIN_ONLY,),
    # El embudo de la plataforma entera: mismos ojos que el panel global.
    "admin_platform_funnel": (SUPER_ADMIN_ONLY,),
    "admin_global_marketplace": (SUPER_ADMIN_ONLY,),
    "admin_global_commercial_plans": (SUPER_ADMIN_ONLY,),
    "admin_payment_providers": (SUPER_ADMIN_ONLY,),
    "admin_global_config": (SUPER_ADMIN_ONLY,),
    "admin_global_tools": (SUPER_ADMIN_ONLY,),
    "admin_ai_center": (SUPER_ADMIN_ONLY,),
    "admin_ai_errors": (SUPER_ADMIN_ONLY,),
    "admin_ai_payments": (SUPER_ADMIN_ONLY,),
    "admin_ai_users": (SUPER_ADMIN_ONLY,),
    "admin_ai_surveys": (SUPER_ADMIN_ONLY,),
    "admin_ai_support": (SUPER_ADMIN_ONLY,),
    "admin_ai_audits": (SUPER_ADMIN_ONLY,),
    "admin_ai_codex_task": (SUPER_ADMIN_ONLY,),
    "admin_ai_feedback": (SUPER_ADMIN_ONLY,),
    "admin_ai_ask": (SUPER_ADMIN_ONLY,),
    "admin_ad_promo": ("can_manage_groups",),
    "admin_ad_promo_campaigns": ("can_manage_groups",),
    "admin_ad_promo_create": ("can_manage_groups",),
    "admin_button_audit": (SUPER_ADMIN_ONLY,),
    "admin_button_audit_detail": (SUPER_ADMIN_ONLY,),
    "admin_button_audit_refresh": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking_search": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking_latest": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking_groups": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking_payments": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking_codes": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking_support": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking_surveys": (SUPER_ADMIN_ONLY,),
    "admin_user_tracking_locations": (SUPER_ADMIN_ONLY,),
    "admin_owners_panel": (SUPER_ADMIN_ONLY,),
    "admin_customer_satisfaction": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_results": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_questions": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_deactivate_menu": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_add_rating": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_add_text": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_edit_menu": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_latest": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_send_pending": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_resend_incomplete": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_send_never_sent": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_delivery_status": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_force_new_cycle": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_send_global": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_send_users": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_send_owners": (SUPER_ADMIN_ONLY,),
    "admin_satisfaction_send_group_admins": (SUPER_ADMIN_ONLY,),
    "admin_commercial_active_requests": (SUPER_ADMIN_ONLY,),
    "admin_commercial_trials_active": (SUPER_ADMIN_ONLY,),
    "admin_commercial_subscriptions": (SUPER_ADMIN_ONLY,),
    "admin_commercial_group_limits": (SUPER_ADMIN_ONLY,),
    "admin_commercial_owner_tools": (SUPER_ADMIN_ONLY,),
    "admin_commercial_owner_summary": (SUPER_ADMIN_ONLY,),
    "admin_commercial_reassign_owner_group": (SUPER_ADMIN_ONLY,),

    "group_admin_panel": ("can_manage_admins",),

    "owner_panel_users": (
        "can_view_users",
        "can_manage_users",
        "can_kick_users",
        "can_ban_users",
        "can_unban_users",
        "can_warn_users",
        "can_reset_warnings",
        "can_resend_links",
        "can_recover_access"
    ),
    "owner_panel_codes": ("can_manage_codes",),
    "owner_panel_payments": (
        "can_manage_plans",
        "can_manage_groups",
        "can_view_payments",
        "can_manage_payments"
    ),
    "owner_panel_security": ("can_manage_groups", "can_view_logs"),
    "owner_panel_marketplace": (
        "can_manage_groups",
        "can_edit_group_texts",
        "can_edit_marketplace_preview"
    ),
    "owner_panel_admins": ("can_manage_admins",),
    "owner_panel_logs": ("can_view_logs",),
    "owner_panel_support": ("can_respond_group_support",),
    "owner_support_tickets": ("can_respond_group_support",),
    "owner_panel_satisfaction": ("can_manage_groups", "can_view_logs"),
    "owner_satisfaction_send_pending": ("can_manage_groups", "can_view_logs"),
    "owner_satisfaction_resend_incomplete": ("can_manage_groups", "can_view_logs"),
    "owner_satisfaction_send_never_sent": ("can_manage_groups", "can_view_logs"),
    "owner_satisfaction_delivery_status": ("can_manage_groups", "can_view_logs"),
    "owner_satisfaction_force_new_cycle": ("can_manage_groups", "can_view_logs"),
    "owner_satisfaction_confirm": ("can_manage_groups", "can_view_logs"),
    "owner_panel_backup": ("can_manage_groups",),
    "owner_panel_general": ("can_manage_groups", "can_edit_group_texts"),
    "owner_setup_assistant": (
        "can_manage_groups",
        "can_manage_plans",
        "can_manage_codes",
        "can_manage_admins",
        "can_edit_group_texts",
        "can_edit_marketplace_preview",
        "can_view_logs"
    ),
    "owner_panel_security_info": ("can_manage_groups", "can_view_logs"),
    "owner_panel_location_info": ("can_manage_groups",),
    "owner_panel_access_type_info": ("can_manage_groups",),
    "owner_panel_general_info": ("can_manage_groups", "can_edit_group_texts"),
    "owner_panel_audit": ("can_manage_groups", "can_view_logs"),
    "owner_panel_audit_detail": ("can_manage_groups", "can_view_logs"),
    "owner_panel_commercial_config": ("can_manage_groups", "can_manage_plans", "can_view_payments", "can_manage_payments"),
    "owner_ai_panel": (
        "can_manage_groups",
        "can_manage_plans",
        "can_view_logs",
        "can_respond_group_support"
    ),
    "owner_ai_ask": (
        "can_manage_groups",
        "can_manage_plans",
        "can_view_logs",
        "can_respond_group_support"
    ),

    "admin_revoke_links": (SUPER_ADMIN_ONLY,),
    "admin_resend_links": (SUPER_ADMIN_ONLY,)

}


ADMIN_CALLBACK_PREFIX_PERMISSION_MAP = (

    ("allow_user_", ("can_manage_users",)),
    ("deny_user_", ("can_kick_users", "can_manage_users")),
    ("admin_ad_promo_", ("can_manage_groups",)),
    ("admin_support_", (SUPER_ADMIN_ONLY,)),
    ("admin_commercial_", (SUPER_ADMIN_ONLY,)),
    ("admin_satisfaction_confirm_", (SUPER_ADMIN_ONLY,)),
    ("admin_trial_visibility_", (SUPER_ADMIN_ONLY,)),
    ("group_admin_", ("can_manage_admins",)),
    ("add_group_admin_", ("can_manage_admins",)),
    ("edit_admin_permissions_", ("can_manage_admins",)),
    ("edit_group", (
        "can_manage_groups",
        "can_manage_plans",
        "can_manage_codes",
        "can_manage_admins",
        "can_edit_group_texts",
        "can_edit_marketplace_preview"
    )),
    ("admin_group_user_codes", (SUPER_ADMIN_ONLY,)),
    ("admin_help_", (SUPER_ADMIN_ONLY,)),
    ("group_user_codes_", ("can_manage_codes",)),
    ("group_user_code_", ("can_manage_codes",)),
    ("owner_group_payment_methods_", ("can_manage_groups", "can_manage_plans", "can_view_payments", "can_manage_payments")),
    ("owner_group_payment_provider_", ("can_manage_groups", "can_manage_plans", "can_view_payments", "can_manage_payments")),
    ("owner_group_payment_connect_", ("can_manage_groups", "can_manage_plans", "can_manage_payments")),
    ("owner_group_payment_disable_", ("can_manage_groups", "can_manage_plans", "can_manage_payments")),
    ("owner_group_payment_delete_", ("can_manage_groups", "can_manage_plans", "can_manage_payments")),
    ("owner_payment_paypal_", ("can_manage_groups", "can_manage_plans", "can_manage_payments")),
    ("owner_payment_revolut_", ("can_manage_groups", "can_manage_plans", "can_manage_payments")),
    ("owner_payment_changenow_", ("can_manage_groups", "can_manage_plans", "can_manage_payments")),
    ("owner_payment_guardarian_", ("can_manage_groups", "can_manage_plans", "can_manage_payments")),
    ("guardarian_group_plan_", ()),
    ("owner_group_payments_", ("can_view_payments", "can_manage_payments")),
    ("owner_group_subscriptions_", ("can_view_payments", "can_manage_payments")),
    ("owner_group_users_", ("can_view_users", "can_manage_users")),
    ("owner_group_logs_", ("can_view_logs",)),
    ("owner_location_", ("can_manage_groups",)),
    ("owner_ai_", ("can_manage_groups", "can_manage_plans", "can_view_logs", "can_respond_group_support")),
    ("owner_support_ai_", ("can_respond_group_support",)),
    ("owner_support_use_ai_", ("can_respond_group_support",)),
    ("owner_support_ticket_", ("can_respond_group_support",)),
    ("owner_support_reply_", ("can_respond_group_support",)),
    ("owner_support_close_", ("can_respond_group_support",)),
    ("owner_satisfaction_confirm_", ("can_manage_groups", "can_view_logs")),
    ("owner_panel_help_", ("can_manage_groups", "can_manage_plans", "can_manage_codes", "can_manage_admins", "can_edit_group_texts", "can_edit_marketplace_preview", "can_view_users", "can_manage_users", "can_view_payments", "can_manage_payments", "can_view_logs", "can_respond_group_support")),
    ("edit_plan_", ("can_manage_groups", "can_manage_plans")),
    ("delete_group", (SUPER_ADMIN_ONLY,)),
    ("delete_plan_", ("can_manage_groups", "can_manage_plans")),
    ("save_preview", ("can_manage_groups", "can_edit_marketplace_preview")),
    ("cancel_preview", ("can_manage_groups", "can_edit_marketplace_preview")),
    ("skip_preview", ("can_manage_groups", "can_edit_marketplace_preview")),
    ("gen_", ("can_manage_codes",))

)


ADMIN_CALLBACK_PREFIXES = (

    "menu_",
    "admin_",
    "group_admin_",
    "add_group_admin_",
    "edit_admin_permissions_",
    "edit_group",
    "admin_group_user_codes",
    "admin_help_",
    "admin_satisfaction_confirm_",
    "group_user_codes_",
    "group_user_code_",
    "owner_group_payment_methods_",
    "owner_group_payment_provider_",
    "owner_group_payment_connect_",
    "owner_group_payment_disable_",
    "owner_group_payment_delete_",
    "owner_payment_paypal_",
    "owner_payment_revolut_",
    "owner_payment_changenow_",
    "owner_payment_guardarian_",
    "guardarian_group_plan_",
    "owner_group_payments_",
    "owner_group_subscriptions_",
    "owner_group_users_",
    "owner_group_logs_",
    "owner_location_",
    "owner_ai_",
    "owner_support_ai_",
    "owner_support_use_ai_",
    "owner_support_ticket_",
    "owner_support_reply_",
    "owner_support_close_",
    "owner_satisfaction_confirm_",
    "owner_panel_help_",
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
