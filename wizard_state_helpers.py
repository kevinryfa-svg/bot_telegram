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
    # Sin esto, un «auto» de una edición anterior seguiría puesto y el
    # siguiente plan que se editara se llevaría un precio nuevo sin pedirlo.
    "edit_plan_stripe_autocreate",
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


LOCATION_FLOW_KEYS = (
    "location_gate_pending",
    "location_gate_group_id",
    "location_gate_action",
    "location_gate_price_id",
    "location_review_group_id",
    "location_review_step",
    "location_review_answers",
    "location_review_failed_latitude",
    "location_review_failed_longitude",
    "location_review_allowed_region",
    "location_review_allowed_region_type",
    "location_review_detected_label",
    "location_review_action",
    "location_review_price_id"
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


def clear_location_flow_state(context):

    cleared_keys = []

    for key in LOCATION_FLOW_KEYS:

        if context.user_data.pop(key, None) is not None:

            cleared_keys.append(key)

    return cleared_keys
