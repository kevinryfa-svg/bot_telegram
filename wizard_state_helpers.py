from audit_log_service import log_event


PLAN_WIZARD_KEYS = (
    "adding_plan",
    "add_plan_step",
    "new_plan",
    "editing_plan",
    "editing_plan_id",
    "edit_plan_step",
    "edit_plan_name",
    "edit_plan_price",
    "edit_plan_provider",
    "edit_plan_provider_price_id",
    "edit_plan_stripe_price_id",
    "edit_plan_paypal_plan_id",
    "edit_plan_duration",
    "edit_plan_amount"
)


OWNER_PAYMENT_PROVIDER_WIZARD_KEYS = (
    "configuring_owner_payment_provider",
    "owner_payment_provider",
    "owner_payment_group_id",
    "owner_payment_step",
    "owner_payment_payload",
    "configuring_platform_payment_provider",
    "platform_payment_provider",
    "platform_payment_step",
    "platform_payment_payload"
)


def get_active_wizard_keys(context, keys):

    return [
        key
        for key in keys
        if context.user_data.get(key) is not None
    ]


def log_wizard_state_collision_if_needed(context, user_id=None, action=None):

    active_plan_keys = get_active_wizard_keys(context, PLAN_WIZARD_KEYS)
    active_payment_provider_keys = get_active_wizard_keys(
        context,
        OWNER_PAYMENT_PROVIDER_WIZARD_KEYS
    )

    if not active_plan_keys or not active_payment_provider_keys:

        return

    log_event(
        "wizard_state_collision_cleared",
        category="ui",
        severity="warning",
        scope="global",
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Estado de wizard incompatible detectado y limpiado.",
        metadata={
            "user_id": user_id,
            "active_plan_keys": active_plan_keys,
            "active_payment_provider_keys": active_payment_provider_keys,
            "action": action
        }
    )


def clear_plan_wizard_state(context, user_id=None, action=None):

    log_wizard_state_collision_if_needed(
        context,
        user_id=user_id,
        action=action
    )

    for key in PLAN_WIZARD_KEYS:

        context.user_data.pop(key, None)


def clear_owner_payment_provider_wizard_state(context, user_id=None, action=None):

    log_wizard_state_collision_if_needed(
        context,
        user_id=user_id,
        action=action
    )

    for key in OWNER_PAYMENT_PROVIDER_WIZARD_KEYS:

        context.user_data.pop(key, None)
