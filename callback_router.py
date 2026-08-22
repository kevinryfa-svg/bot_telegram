import asyncio
import json
import os
import re
import requests
import secrets
import shutil
import string
import subprocess
import time
import tempfile
import unicodedata
import stripe

from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import ContextTypes

from admin_permission_map import (
    callback_requires_super_admin,
    get_required_permissions_for_callback,
    is_admin_callback
)
from admin_button_audit import (
    audit_admin_button_menus,
    callback_has_handler,
    flatten_keyboard_buttons,
    format_admin_button_audit_detail,
    format_admin_button_audit_summary,
    load_callback_router_source
)
from admin_menu_catalog import build_admin_menu_button_rows
from audit_log_service import (
    complete_active_beta_cycle,
    complete_expired_beta_cycles,
    create_beta_cycle,
    get_active_beta_cycle,
    get_beta_cycle_monitor_counts,
    get_latest_beta_cycle,
    list_beta_monitor_events,
    list_recent_events,
    log_event,
    mark_beta_monitor_events_resolved,
    record_beta_event,
    summarize_beta_monitor_events
)
from ai_handler import activate_ai_help_context
from ai_policy import (
    AI_CONTEXT_CHECKOUT_HELP,
    AI_CONTEXT_OWNER_DASHBOARD,
    AI_CONTEXT_OWNER_PAYMENTS,
    AI_CONTEXT_OWNER_SURVEYS,
    AI_CONTEXT_OWNER_USERS,
    AI_CONTEXT_PAYMENT_DIAGNOSTICS,
    AI_CONTEXT_PUBLIC_MARKETPLACE,
    AI_CONTEXT_SUPPORT_TICKET,
    AI_CONTEXT_SUPERADMIN_DASHBOARD,
    AI_CONTEXT_USER_TRACKING,
    AI_ROLE_BUYER,
    AI_ROLE_OWNER,
    AI_ROLE_SUPERADMIN,
    sanitize_ai_text
)
from ai_service import (
    generate_ai_response,
    is_ai_enabled
)
from ai_response_service import (
    build_ai_feedback_keyboard_rows,
    build_contextual_ai_answer,
    get_ai_interaction_feedback_context,
    update_ai_feedback
)
from support_ai_service import build_support_reply_suggestion
from code_admin_handler import crear_codigo_callback
from bot_config import ADMIN_ID
from commercial_catalog import (
    COMMERCIAL_MENU_TEXT_ES,
    COMMERCIAL_PRODUCTS,
    PRODUCT_SHARED_BOT_SPACE,
    PRODUCT_CUSTOM_BOT,
    CALLBACK_SHARED_BOT_SPACE,
    CALLBACK_CUSTOM_BOT,
    CALLBACK_COMMERCIAL_CONTACT,
    CALLBACK_COMMERCIAL_BACK,
    CALLBACK_COMMERCIAL_BACK_START,
    CALLBACK_COMMERCIAL_BACK_SOLUTIONS,
    CALLBACK_SHARED_TRIAL_START,
    CALLBACK_CUSTOM_BOT_START,
    CALLBACK_COMMERCIAL_HELP,
    CALLBACK_SUBSCRIPTIONS_HELP,
    CALLBACK_GROUP_PLANS_HELP,
    CALLBACK_SUPPORT_HELP,
    CALLBACK_ADMIN_USERS_HELP,
    CALLBACK_ADMIN_GROUPS_HELP,
    CALLBACK_ADMIN_PAYMENTS_HELP,
    CALLBACK_ADMIN_LOGS_HELP
)
from commercial_form_handler import (
    create_commercial_request,
    notify_commercial_request
)
from db import conn
from formatters import format_tiempo_restante
from i18n_service import DEFAULT_LANGUAGE, load_user_language, t
from owner_addon_service import (
    activate_owner_addon_manual_trial,
    owner_addon_is_purchase_allowed,
    fetch_owner_addon_product,
    ensure_owner_addon_stripe_price,
    fetch_owner_addon_products,
    fetch_owner_addon_subscription,
    fetch_owner_addon_subscriptions_for_management,
    fetch_owner_addon_subscriptions,
    owner_has_feature,
    update_owner_addon_cancel_at_period_end,
    update_owner_addon_plan_from_stripe,
    update_owner_addon_subscription_from_stripe,
    upsert_owner_addon_checkout_pending
)
# Los backups del propietario se han sacado a su propio módulo (tercera fase de
# partir este archivo).
from owner_backup_callbacks import (
    NOT_HANDLED as OWNER_BACKUP_NOT_HANDLED,
    handle_owner_backup_callbacks
)
from owner_backup_service import (
    create_owner_backup,
    fetch_due_owner_backup_jobs,
    fetch_owner_backup_file,
    fetch_owner_backup_job,
    fetch_owner_backups,
    mark_owner_backup_job_run,
    upsert_owner_backup_job
)
from group_registration_handler import (
    cancel_creator_group_link_request,
    confirm_backup_destination_token,
    confirm_creator_group_link_request,
    leave_chat_safely,
    verificar_admin_despues
)
from group_service import (
    format_community_kind,
    format_community_kind_capitalized,
    get_community_type,
    normalize_community_type
)
# Guardian se ha sacado a su propio módulo (primera fase de partir este
# archivo). Se reimportan los nombres que se siguen usando aquí fuera: los
# manejadores de texto del panel del propietario y las otras ramas de Guardian.
from guardian_callbacks import (
    build_owner_guardian_addon_required_keyboard,
    build_owner_guardian_addon_required_text,
    build_owner_guardian_cancel_keyboard,
    build_owner_guardian_forbidden_words_cancel_keyboard,
    build_owner_guardian_forbidden_words_keyboard,
    build_owner_guardian_night_mode_cancel_keyboard,
    build_owner_guardian_night_mode_keyboard,
    build_owner_guardian_panel_keyboard,
    handle_guardian_callbacks,
    log_owner_guardian_addon_gate,
    owner_can_use_guardian,
    user_can_view_guardian_warnings
)
from guardian_service import (
    GUARDIAN_LOG_EVENT_CATEGORIES,
    add_guardian_forbidden_word,
    add_guardian_warning,
    count_guardian_link_whitelist_domains,
    count_guardian_forbidden_words,
    count_guardian_warnings,
    deactivate_guardian_forbidden_word,
    ensure_guardian_settings,
    fetch_guardian_settings,
    get_guardian_anti_links_settings,
    get_guardian_forbidden_words_settings,
    get_guardian_log_event_settings,
    get_guardian_night_mode_settings,
    list_guardian_link_whitelist_domains,
    list_guardian_forbidden_words,
    list_guardian_warning_summary,
    list_guardian_warnings,
    parse_guardian_hhmm,
    record_guardian_log_event,
    reset_guardian_warnings,
    send_guardian_event_log,
    send_guardian_test_log,
    set_guardian_log_event_enabled,
    update_guardian_anti_links_settings,
    update_guardian_forbidden_words_settings,
    update_guardian_night_mode_settings,
    update_guardian_log_channel
)
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link,
    create_telegram_public_invite_link,
    format_access_link_validity,
    mask_invite_link,
    revoke_telegram_invite_link
)
from publicity_invite_link_service import (
    create_publicity_invite_link,
    get_active_publicity_invite_link,
    get_publicity_invite_link_by_id,
    list_publicity_invite_links,
    revoke_publicity_invite_link,
    revoke_publicity_invite_link_by_id
)
from payment_service import (
    build_group_payment_provider_detail_text,
    build_group_payment_methods_text,
    build_payment_methods_admin_text,
    clear_group_payment_provider_config,
    disable_group_payment_provider_config,
    clear_platform_payment_provider_config,
    disable_platform_payment_provider_config,
    ensure_group_payment_provider_config,
    ensure_platform_payment_provider_config,
    fetch_platform_payment_provider_config,
    is_changenow_group_checkout_available,
    is_changenow_platform_checkout_available,
    is_guardarian_group_checkout_available,
    is_guardarian_platform_checkout_available,
    is_paypal_group_checkout_available,
    is_revolut_group_checkout_available,
    is_stripe_payments_enabled,
    group_payment_provider_statuses_by_ux,
    list_group_payment_provider_statuses,
    PAYMENT_UX_GROUP_LABELS,
    PAYMENT_UX_GROUP_ORDER,
    save_group_payment_provider_encrypted_config,
    save_platform_payment_provider_encrypted_config
)
from group_delivery_health_service import (
    describe_group_delivery,
    group_can_deliver_access,
    recheck_group_delivery_live
)
from payment_access_service import (
    get_user_group_access_state,
    grant_group_access_after_payment,
    log_purchase_blocked_existing_access,
    should_block_new_group_purchase
)
from payment_providers.guardarian_provider import process_guardarian_webhook
# El asistente de métodos de pago del propietario se ha sacado a su propio
# módulo (segunda fase de partir este archivo).
from ad_promo_callbacks import (
    AD_PROMO_CAMPAIGN_FIELDS,
    AD_PROMO_CAPTION_ANGLES,
    AD_PROMO_CREATE_STEPS,
    AD_PROMO_MEDIA_FIELDS,
    AD_PROMO_WATERMARK_POSITIONS,
    NOT_HANDLED as AD_PROMO_NOT_HANDLED,
    handle_ad_promo_callbacks
)
from admin_payment_provider_callbacks import (
    OWNER_PAYMENT_PROVIDER_CHANGENOW,
    OWNER_PAYMENT_PROVIDER_GUARDARIAN,
    NOT_HANDLED as ADMIN_PAYMENT_PROVIDER_NOT_HANDLED,
    handle_admin_payment_provider_callbacks
)
from owner_revenue_service import build_owner_revenue_text
from owner_publicity_callbacks import (
    TOKEN,
    NOT_HANDLED as OWNER_PUBLICITY_NOT_HANDLED,
    handle_owner_publicity_callbacks
)
from admin_satisfaction_callbacks import (
    NOT_HANDLED as ADMIN_SATISFACTION_NOT_HANDLED,
    handle_admin_satisfaction_callbacks
)
from creator_preview_callbacks import (
    MARKETPLACE_CATEGORIES,
    MARKETPLACE_CATEGORY_LABELS,
    PREVIEW_MODE_LABELS,
    NOT_HANDLED as CREATOR_PREVIEW_NOT_HANDLED,
    handle_creator_preview_callbacks
)
from creator_location_callbacks import (
    COMUNIDAD_VALENCIANA_LABEL,
    COMUNIDAD_VALENCIANA_REGION,
    HISPANIC_COUNTRIES,
    HISPANIC_COUNTRY_LABELS,
    LOCATION_REGION_TYPE_COUNTRY,
    LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
    SPANISH_AUTONOMOUS_COMMUNITIES,
    SPANISH_AUTONOMOUS_COMMUNITY_LABELS,
    NOT_HANDLED as CREATOR_LOCATION_NOT_HANDLED,
    handle_creator_location_callbacks
)
from owner_addon_callbacks import (
    OWNER_ADDON_PLAN_CHANGE_CODES,
    NOT_HANDLED as OWNER_ADDON_NOT_HANDLED,
    handle_owner_addon_callbacks
)
from location_review_callbacks import (
    LOCATION_MANUAL_REVIEW_FIELDS,
    NOT_HANDLED as LOCATION_REVIEW_NOT_HANDLED,
    handle_location_review_callbacks
)
from owner_satisfaction_callbacks import (
    NOT_HANDLED as OWNER_SATISFACTION_NOT_HANDLED,
    handle_owner_satisfaction_callbacks
)
from delete_group_callbacks import (
    NOT_HANDLED as DELETE_GROUP_NOT_HANDLED,
    handle_delete_group_callbacks
)
from mysub_callbacks import (
    NOT_HANDLED as MYSUB_NOT_HANDLED,
    handle_mysub_callbacks
)
from creator_setup_callbacks import (
    COMMERCIAL_REQUEST_FIELDS,
    NOT_HANDLED as CREATOR_SETUP_NOT_HANDLED,
    handle_creator_setup_callbacks
)
from admin_commercial_callbacks import (
    COMMERCIAL_REQUEST_MESSAGE_FIELDS,
    NOT_HANDLED as ADMIN_COMMERCIAL_NOT_HANDLED,
    handle_admin_commercial_callbacks
)
from owner_group_callbacks import (
    OWNER_PAYMENT_PROVIDER_PAYPAL,
    OWNER_PAYMENT_PROVIDER_REVOLUT,
    NOT_HANDLED as OWNER_GROUP_NOT_HANDLED,
    handle_owner_group_callbacks
)
from owner_support_callbacks import (
    NOT_HANDLED as OWNER_SUPPORT_NOT_HANDLED,
    handle_owner_support_callbacks
)
from group_user_callbacks import (
    NOT_HANDLED as GROUP_USER_NOT_HANDLED,
    handle_group_user_callbacks
)
from edit_group_callbacks import (
    ADMIN_PERMISSION_COLUMNS,
    NOT_HANDLED as EDIT_GROUP_NOT_HANDLED,
    handle_edit_group_callbacks
)
from community_links_callbacks import (
    NOT_HANDLED as COMMUNITY_LINKS_NOT_HANDLED,
    handle_community_links_callbacks
)
from add_group_callbacks import (
    GROUP_ADMIN_PERMISSION_OPTIONS,
    OWNER_PAYMENT_PROVIDER_STRIPE,
    NOT_HANDLED as ADD_GROUP_NOT_HANDLED,
    handle_add_group_callbacks
)
from group_admin_callbacks import (
    NOT_HANDLED as GROUP_ADMIN_NOT_HANDLED,
    handle_group_admin_callbacks
)
from owner_panel_callbacks import (
    OWNER_PANEL_SECTIONS,
    NOT_HANDLED as OWNER_PANEL_NOT_HANDLED,
    handle_owner_panel_callbacks
)
from owner_location_callbacks import (
    NOT_HANDLED as OWNER_LOCATION_NOT_HANDLED,
    handle_owner_location_callbacks
)
from admin_guardarian_callbacks import (
    NOT_HANDLED as ADMIN_GUARDARIAN_NOT_HANDLED,
    handle_admin_guardarian_callbacks
)
from admin_beta_callbacks import (
    NOT_HANDLED as ADMIN_BETA_NOT_HANDLED,
    handle_admin_beta_callbacks
)
from admin_guardian_callbacks import (
    NOT_HANDLED as ADMIN_GUARDIAN_NOT_HANDLED,
    handle_admin_guardian_callbacks
)
from guardian_user_callbacks import (
    NOT_HANDLED as GUARDIAN_USER_NOT_HANDLED,
    handle_guardian_user_callbacks
)
from community_user_callbacks import (
    NOT_HANDLED as COMMUNITY_USER_NOT_HANDLED,
    handle_community_user_callbacks
)
from admin_support_callbacks import (
    NOT_HANDLED as ADMIN_SUPPORT_NOT_HANDLED,
    handle_admin_support_callbacks
)
from admin_view_callbacks import (
    NOT_HANDLED as ADMIN_VIEW_NOT_HANDLED,
    handle_admin_view_callbacks
)
from admin_changenow_callbacks import (
    NOT_HANDLED as ADMIN_CHANGENOW_NOT_HANDLED,
    handle_admin_changenow_callbacks
)
from admin_resend_callbacks import (
    NOT_HANDLED as ADMIN_RESEND_NOT_HANDLED,
    handle_admin_resend_callbacks
)
from creator_dynamic_callbacks import (
    NOT_HANDLED as CREATOR_DYNAMIC_NOT_HANDLED,
    handle_creator_dynamic_callbacks
)
from recover_access_callbacks import (
    NOT_HANDLED as RECOVER_ACCESS_NOT_HANDLED,
    handle_recover_access_callbacks
)
from platform_revenue_service import (
    build_platform_revenue_text,
    build_scoped_income_text,
)
from owner_payment_callbacks import (
    OWNER_PAYMENT_CALLBACK_PREFIXES,
    handle_owner_payment_callbacks
)
from plan_payment_provider_helpers import (
    PLAN_PAYMENT_PROVIDER_LABELS,
    PLAN_PAYMENT_PROVIDER_CHANGENOW,
    PLAN_PAYMENT_PROVIDER_GUARDARIAN,
    PLAN_PAYMENT_PROVIDER_PAYPAL,
    PLAN_PAYMENT_PROVIDER_REVOLUT,
    PLAN_PAYMENT_PROVIDER_STRIPE,
    format_plan_payment_provider,
    normalize_plan_payment_provider
)
from payment_secret_store import (
    encrypt_provider_config,
    has_payment_encryption_key,
    mask_provider_config,
    mask_secret_value
)
from rbac_helpers import (
    assign_group_owner_permissions,
    get_creator_group_quota_source,
    get_admin_group_ids,
    get_group_owner_user_id,
    has_any_permission_any_group,
    has_group_permission,
    has_permission,
    set_creator_group_quota,
    sync_commercial_creator_profile_from_request,
    is_super_admin
)
from start_handler import start, send_start_menu
from telegram_group_actions import kick_chat_member
from ui_menu_helpers import (
    delete_pending_preview_messages,
    make_button,
    remember_preview_message,
    send_clean_message
)
from user_activity_logger import (
    fetch_recent_user_events,
    fetch_tracking_overview,
    fetch_user_activity_profile,
    log_user_event,
    log_user_event_by_ids
)
from reengagement_service import (
    CALLBACK_REENGAGEMENT_STOP,
    opt_out_reengagement
)
from wizard_state_helpers import (
    clear_location_flow_state,
    clear_owner_payment_provider_wizard_state,
    clear_plan_wizard_state
)


# TOKEN vive en owner_publicity_callbacks (tramo extraído) y se importa arriba.
SERVER_URL = os.environ.get("SERVER_URL")

# Marcadores: main.py los rellena en caliente (callback_router_module.X = ...).
# Los tramos extraídos los leen de aquí en diferido, en el momento de la llamada.
revoke_link = None
get_group_id = None


# OWNER_PAYMENT_PROVIDER_CHANGENOW/GUARDARIAN viven en
# admin_payment_provider_callbacks (tramo extraído) y se importan arriba.
# Redefinirlas aquí sombreaba el import: mismo valor hoy, bug latente mañana.
OWNER_PAYMENT_PROVIDER_CONTEXT_KEYS = (
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


def get_group_plan_enabled_payment_providers(group_id):

    providers = []

    if is_stripe_payments_enabled():

        providers.append(OWNER_PAYMENT_PROVIDER_STRIPE)


    if is_paypal_group_checkout_available(group_id):

        providers.append(OWNER_PAYMENT_PROVIDER_PAYPAL)


    if is_revolut_group_checkout_available(group_id):

        providers.append(OWNER_PAYMENT_PROVIDER_REVOLUT)


    if is_changenow_group_checkout_available(group_id):

        providers.append(OWNER_PAYMENT_PROVIDER_CHANGENOW)


    if is_guardarian_group_checkout_available(group_id):

        providers.append(OWNER_PAYMENT_PROVIDER_GUARDARIAN)


    return providers


def get_group_payment_provider_status(provider_statuses, provider):

    for provider_status in provider_statuses:

        if provider_status.get("provider") == provider:

            return provider_status

    return None




def is_group_provider_globally_disabled(provider_status):

    return bool(provider_status and provider_status.get("global_enabled") is not True)








async def delete_query_message_safely(query):

    try:

        if int(query.message.chat_id) < 0:

            return


        await query.message.delete()

    except Exception:

        pass


def build_recover_navigation_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Volver al inicio",
            callback_data="public_back_start"
        )],
        [InlineKeyboardButton(
            "🔎 Ver comunidades",
            callback_data="start_explore_groups"
        )]
    ])


async def reply_with_recover_navigation(query, text):

    await query.message.reply_text(
        text,
        reply_markup=build_recover_navigation_keyboard()
    )


def build_unknown_callback_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]
    ])


def clear_owner_payment_provider_wizard(context, user_id=None, action=None):

    clear_plan_wizard_state(
        context,
        user_id=user_id,
        action=action or "owner_payment_provider_wizard"
    )
    clear_owner_payment_provider_wizard_state(
        context,
        user_id=user_id,
        action=action or "owner_payment_provider_wizard"
    )


def build_owner_paypal_cancel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar configuración", callback_data=f"owner_payment_paypal_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_revolut_cancel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar configuración", callback_data=f"owner_payment_revolut_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])






def build_owner_paypal_confirm_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Guardar cifrado", callback_data=f"owner_payment_paypal_save_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_paypal_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")]
    ])


def build_owner_revolut_confirm_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Guardar cifrado", callback_data=f"owner_payment_revolut_save_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_revolut_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")]
    ])


def build_owner_changenow_cancel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar configuración", callback_data=f"owner_payment_changenow_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])




def build_owner_changenow_confirm_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Guardar cifrado", callback_data=f"owner_payment_changenow_save_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_changenow_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")]
    ])


def build_platform_changenow_cancel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar configuración", callback_data="admin_payment_changenow_cancel")],
        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])




def build_platform_changenow_confirm_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Guardar cifrado", callback_data="admin_payment_changenow_save")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_payment_changenow_cancel")],
        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")]
    ])


def is_valid_paypal_text_value(value, min_length=8):

    if not value:

        return False


    text = value.strip()

    if len(text) < min_length or len(text) > 300:

        return False


    return not any(char.isspace() for char in text)


async def delete_sensitive_user_message(update):

    try:

        if update.message:

            await update.message.delete()

    except Exception:

        pass


def build_owner_paypal_safe_summary(payload):

    safe_payload = {
        "mode": payload.get("mode"),
        "client_id": payload.get("client_id"),
        "client_secret": payload.get("client_secret"),
        "webhook_id": payload.get("webhook_id")
    }
    masked = mask_provider_config(safe_payload)
    webhook_text = "sí" if payload.get("webhook_id") else "no"

    return (
        f"Modo: {masked.get('mode') or '-'}\n"
        f"Client ID: {mask_secret_value(masked.get('client_id')) if masked.get('client_id') else '-'}\n"
        f"Client secret: {masked.get('client_secret') or '***'}\n"
        f"Webhook ID configurado: {webhook_text}"
    )


def build_owner_revolut_safe_summary(payload):

    safe_payload = {
        "mode": payload.get("mode"),
        "api_key": payload.get("api_key"),
        "webhook_secret": payload.get("webhook_secret"),
        "base_url": payload.get("base_url")
    }
    masked = mask_provider_config(safe_payload)
    base_url_text = payload.get("base_url") or "por defecto"

    return (
        f"Modo: {masked.get('mode') or '-'}\n"
        f"API key: {masked.get('api_key') or '***'}\n"
        f"Webhook secret: {masked.get('webhook_secret') or '***'}\n"
        f"Base URL: {base_url_text}"
    )


def build_changenow_safe_summary(payload):

    safe_payload = {
        "rate_mode": payload.get("rate_mode"),
        "api_key": payload.get("api_key"),
        "payout_currency": payload.get("payout_currency"),
        "payout_network": payload.get("payout_network"),
        "payout_wallet": payload.get("payout_wallet"),
        "payin_currency": payload.get("payin_currency"),
        "payin_network": payload.get("payin_network")
    }
    masked = mask_provider_config(safe_payload)

    return (
        f"Modo: {masked.get('rate_mode') or '-'}\n"
        f"API key: {masked.get('api_key') or '***'}\n"
        f"Recibe: {masked.get('payout_currency') or '-'} / {masked.get('payout_network') or '-'}\n"
        f"Wallet destino: {mask_secret_value(payload.get('payout_wallet')) if payload.get('payout_wallet') else '-'}\n"
        f"Paga usuario: {masked.get('payin_currency') or '-'} / {masked.get('payin_network') or '-'}\n"
        "Revisión manual: activada"
    )


def build_changenow_tutorial_text(scope_label="esta comunidad"):

    return (
        "💱 ChangeNOW.io / Cripto\n\n"
        "¿Qué es ChangeNOW.io?\n"
        "Es un proveedor que permite aceptar pagos en criptomonedas y convertirlos hacia una moneda o wallet de destino.\n\n"
        "¿Para qué sirve?\n"
        f"Sirve para que compradores paguen con cripto por accesos o productos de {scope_label}.\n\n"
        "¿Cómo funciona en este bot?\n"
        "1. Configuras una wallet, moneda/red destino y API key.\n"
        "2. El comprador elige pagar con cripto.\n"
        "3. El bot registra una operación de pago.\n"
        "4. El pago queda en revisión manual.\n"
        "5. El acceso se activa solo cuando un superadmin confirma el pago.\n\n"
        "¿Qué necesitas antes de configurarlo?\n"
        "- una wallet propia;\n"
        "- moneda y red correctas;\n"
        "- API key de ChangeNOW si tu integración la requiere;\n"
        "- entender que ChangeNOW no ofrece sandbox oficial dedicado;\n"
        "- asumir que los pagos cripto pueden tardar.\n\n"
        "Importante sobre seguridad:\n"
        "Por ahora ChangeNOW NO activa accesos automáticamente. Los pagos quedan en revisión manual porque falta confirmación pública suficiente sobre callback/push firmado e idempotencia segura.\n\n"
        "Fixed / Floating:\n"
        "Fixed intenta mantener importe/tasa fija durante una ventana limitada. Floating puede variar según mercado. Para vender accesos conviene fixed si ChangeNOW lo permite."
    )


def build_changenow_payment_review_text(order):

    lines = [
        "💱 Pago cripto creado",
        "",
        "Este pago queda en revisión manual. El acceso no se activa automáticamente.",
        "",
        f"Referencia interna: {order.get('transaction_id')}",
        f"Moneda/red de pago: {order.get('payin_currency') or '-'} / {order.get('payin_network') or '-'}",
        f"Moneda/red destino: {order.get('payout_currency') or '-'} / {order.get('payout_network') or '-'}",
        f"Modo: {order.get('rate_mode') or 'fixed'}",
        ""
    ]

    if order.get("payin_address"):

        lines.extend([
            "Datos de pago generados por ChangeNOW:",
            f"Dirección: {order.get('payin_address')}",
            f"Memo/tag: {order.get('payin_extra_id') or '-'}",
            f"Importe esperado: {order.get('expected_amount_from') or '-'}",
            f"Válido hasta: {order.get('valid_until') or '-'}",
            ""
        ])

    lines.extend([
        "Cuando el pago se confirme, soporte revisará la operación y activará el acceso si todo coincide.",
        "No envíes fondos por otra red ni a otra dirección."
    ])

    return "\n".join(lines)



def build_guardarian_tutorial_text(scope_label="esta comunidad"):

    return (
        "💳 Tarjeta EUR → USDT / Guardarian\n\n"
        "¿Qué es Guardarian?\n"
        "Es una pasarela fiat a cripto: el comprador paga con tarjeta en euros y Guardarian liquida en USDT hacia la wallet configurada.\n\n"
        "¿Para qué sirve?\n"
        f"Sirve para vender accesos o productos de {scope_label} con tarjeta, manteniendo privacidad frente al comprador y liquidación en USDT. No oculta obligaciones KYC/AML ni sustituye una revisión de cumplimiento.\n\n"
        "¿Cómo funciona en este bot?\n"
        "1. Configuras API key, wallet USDT y red correcta.\n"
        "2. El comprador paga con tarjeta en EUR.\n"
        "3. El webhook solo despierta al bot.\n"
        "4. El bot consulta GET /v1/transaction/{id}.\n"
        "5. El acceso se activa automáticamente solo si Guardarian devuelve status finished.\n\n"
        "Qué necesitas:\n"
        "- cuenta/API key de Guardarian;\n"
        "- wallet USDT propia;\n"
        "- red correcta: TRC20, ERC20, Polygon, BEP20 u otra soportada;\n"
        "- webhook secret si tu cuenta lo ofrece;\n"
        "- revisar límites, KYC/AML y riesgos de tarjeta.\n\n"
        "Qué es la red USDT:\n"
        "USDT puede existir en varias redes. TRC20 suele ser económica, ERC20 usa Ethereum y puede ser más cara, Polygon/BEP20 suelen tener comisiones más bajas. La red elegida debe coincidir exactamente con la wallet.\n\n"
        "Importante:\n"
        "Una wallet o red incorrecta puede perder fondos. Algunos pagos pueden requerir verificación o revisión por importe, país o riesgo."
    )


def build_guardarian_safe_summary(payload):

    masked = mask_provider_config({
        "api_key": payload.get("api_key"),
        "webhook_secret": payload.get("webhook_secret"),
        "payout_wallet": payload.get("payout_wallet"),
        "payout_network": payload.get("payout_network"),
        "mode": payload.get("mode"),
        "base_url": payload.get("base_url")
    })
    webhook_text = "sí" if payload.get("webhook_secret") else "no"

    return (
        f"Modo: {masked.get('mode') or 'live'}\n"
        "Fiat comprador: EUR\n"
        "Recibe owner/plataforma: USDT\n"
        f"Red USDT: {masked.get('payout_network') or '-'}\n"
        f"Wallet destino: {mask_secret_value(payload.get('payout_wallet')) if payload.get('payout_wallet') else '-'}\n"
        f"API key: {masked.get('api_key') or '***'}\n"
        f"Webhook secret configurado: {webhook_text}\n"
        f"Base URL: {payload.get('base_url') or 'por defecto'}\n"
        "Automático: sí, solo con status finished"
    )


def build_owner_guardarian_cancel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar configuración", callback_data=f"owner_payment_guardarian_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])




def build_owner_guardarian_confirm_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Guardar cifrado", callback_data=f"owner_payment_guardarian_save_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_guardarian_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")]
    ])


def build_platform_guardarian_cancel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar configuración", callback_data="admin_payment_guardarian_cancel")],
        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])




def build_platform_guardarian_confirm_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Guardar cifrado", callback_data="admin_payment_guardarian_save")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_payment_guardarian_cancel")],
        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")]
    ])


def build_guardarian_payment_text(order):

    payment_url = order.get("url") or order.get("payment_url") or order.get("checkout_url")
    lines = [
        "💳 Pago EUR → USDT creado",
        "",
        "Paga con tarjeta en euros. El acceso se activa automáticamente cuando Guardarian confirme oficialmente el pago.",
        "El webhook solo avisa al bot; antes de activar nada el bot consulta GET /v1/transaction/{id}.",
        "",
        f"Referencia interna: {order.get('transaction_id') or '-'}",
        f"Importe: {order.get('amount') or '-'} EUR",
        f"Estado: {order.get('status') or 'pending'}",
        ""
    ]

    if payment_url:

        lines.extend([
            "Abre el enlace para pagar:",
            payment_url,
            ""
        ])

    lines.extend([
        "Algunos pagos pueden tardar por verificación bancaria, KYC/AML o revisión de riesgo.",
        "Ofrece privacidad frente al comprador y liquidación en USDT, sin ocultar posibles revisiones KYC/AML."
    ])

    return "\n".join(lines)


def build_group_recovery_keyboard(group_id, retry_callback=None):

    keyboard = []

    if retry_callback:

        keyboard.append([InlineKeyboardButton(
            "🔁 Reintentar",
            callback_data=retry_callback
        )])


    if group_id:

        keyboard.append([InlineKeyboardButton(
            "⬅️ Volver a comunidad",
            callback_data=f"marketplace_group_{group_id}"
        )])


    # Soporte aquí mismo: quien no consigue pagar no debería tener que buscar
    # con quién hablar por los menús.
    keyboard.append([InlineKeyboardButton(
        "🛟 Contactar soporte",
        callback_data="public_support"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(keyboard)




def build_payment_link_keyboard(group_id):
    """
    Botones que acompañan al enlace de pago.

    Antes el enlace se enviaba solo, quitando además el teclado: si el cliente
    dudaba, cerraba el navegador o el enlace no le abría, se quedaba sin salida.
    """

    keyboard = []

    if group_id:

        keyboard.append([InlineKeyboardButton(
            "⬅️ Volver a la comunidad",
            callback_data=f"marketplace_group_{group_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "🛟 Tengo un problema con el pago",
        callback_data="public_support"
    )])

    return InlineKeyboardMarkup(keyboard)


PAYMENT_FAILED_TEXT = (
    "❌ No he podido abrir la pasarela de pago\n\n"
    "No se te ha cobrado nada.\n\n"
    "Vuelve a intentarlo en un momento. Si sigue sin funcionar, escríbenos y "
    "lo miramos: puede ser algo de la comunidad y no tuyo."
)


def format_access_expiration(expires_at):

    if not expires_at:
        return "permanente"

    try:
        return expires_at.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(expires_at)


def build_existing_group_access_text(access_state):

    group_name = access_state.get("group_name") or f"Grupo {access_state.get('group_id')}"
    community_type = normalize_community_type(access_state.get("community_type"))
    community_kind = format_community_kind(community_type)
    expires_at = access_state.get("expires_at")

    if access_state.get("reason") == "owner_access":

        return (
            f"👑 Eres el propietario de {group_name}.\n\n"
            "No necesitas comprar acceso.\n"
            "Puedes gestionar esta comunidad desde tu panel."
        )


    if access_state.get("has_active_access"):

        return (
            f"✅ Ya tienes acceso activo a {group_name}.\n\n"
            f"Acceso: {format_access_expiration(expires_at)}\n\n"
            f"Si necesitas volver a entrar al {community_kind}, usa Recuperar/Reenviar enlace.\n"
            "Si crees que esto es un error, abre soporte."
        )

    if access_state.get("reason") == "payment_pending_stale":

        return (
            f"⏳ Tu intento de pago anterior para {group_name} parece caducado.\n\n"
            "Puedes crear uno nuevo desde el botón de abajo.\n"
            "Si ya pagaste, abre soporte para revisar el pago y evitar duplicados."
        )

    if access_state.get("subscription_status") == "pending":

        provider = (
            access_state.get("pending_payment_provider")
            or access_state.get("last_payment_provider")
            or "proveedor"
        )

        if access_state.get("pending_payment_can_resume"):

            return (
                f"⏳ Tienes un pago pendiente para {group_name}.\n\n"
                "Puedes continuar el pago desde el botón de abajo.\n"
                "Si ya pagaste, revisa el estado o abre soporte."
            )

        return (
            f"⏳ Hay un intento de pago pendiente para {group_name}, pero no puedo recuperar el enlace de pago.\n\n"
            f"Proveedor: {provider}\n"
            f"Estado: {access_state.get('last_payment_status') or 'pending'}\n\n"
            "Si ya pagaste, no crees otro pago: abre soporte para revisarlo y evitar duplicados.\n"
            "Si no llegaste a pagar, puedes crear un nuevo intento desde Ver planes."
        )

    if access_state.get("reason") == "paid_without_access_record":

        return (
            f"⚠️ Encontré un pago confirmado para {group_name}, pero no puedo reconstruir el acceso automáticamente.\n\n"
            "Para evitar cobrarte dos veces, no crearé otro pago ahora.\n"
            "Revisa Mis suscripciones o abre soporte para recuperar tu acceso."
        )

    if access_state.get("subscription_status") == "expired":

        return (
            f"⚠️ Tu acceso anterior a {group_name} está vencido.\n\n"
            "Puedes renovar el acceso o revisar los planes disponibles."
        )

    return (
        f"ℹ️ Estado de acceso para {group_name}\n\n"
        "No veo un acceso activo ahora mismo."
    )


def append_existing_group_access_notice(text, user_id, group_id):

    if not user_id:

        return text


    access_state = get_user_group_access_state(user_id, group_id)


    if not should_block_new_group_purchase(access_state):

        return text


    notice = build_existing_group_access_text(access_state)
    max_caption_length = 950
    available_text_length = max_caption_length - len(notice) - 2


    if available_text_length > 20 and len(text) > available_text_length:

        text = f"{text[:available_text_length - 3]}..."


    return f"{text}\n\n{notice}"


async def append_existing_group_access_notice_async(context, text, user_id, group_id):

    if not user_id:

        return text


    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    if not should_block_new_group_purchase(access_state):

        return text


    notice = build_existing_group_access_text(access_state)
    max_caption_length = 950
    available_text_length = max_caption_length - len(notice) - 2


    if available_text_length > 20 and len(text) > available_text_length:

        text = f"{text[:available_text_length - 3]}..."


    return f"{text}\n\n{notice}"


def fetch_group_telegram_id(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT telegram_group_id
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            row = cur.fetchone()


        if row:

            return row[0]

    except Exception as e:

        print("fetch_group_telegram_id_error:", str(e)[:200])


    return None


def sync_user_access_from_telegram_member(user_id, group_id):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO users (
                user_id,
                group_id,
                subscription_active,
                expiration,
                created_at
            )
            VALUES (%s, %s, TRUE, NULL, NOW())
            ON CONFLICT (user_id, group_id)
            DO UPDATE SET
                subscription_active=TRUE,
                expiration=CASE
                    WHEN users.expiration IS NULL THEN EXCLUDED.expiration
                    ELSE users.expiration
                END

        """, (
            user_id,
            group_id
        ))

        conn.commit()


async def resolve_group_access_state_for_user(context, user_id, group_id):

    access_state = get_user_group_access_state(user_id, group_id)


    if not user_id or not group_id:

        return access_state


    if access_state.get("subscription_status") not in ("pending", "paid_without_access_record"):

        return access_state


    previous_subscription_status = access_state.get("subscription_status")
    previous_reason = access_state.get("reason")
    telegram_group_id = (
        access_state.get("telegram_group_id")
        or fetch_group_telegram_id(group_id)
    )


    if not telegram_group_id:

        return access_state


    try:

        member = await context.bot.get_chat_member(
            chat_id=telegram_group_id,
            user_id=user_id
        )

    except Exception as e:

        print("resolve_group_access_state_get_chat_member_error:", str(e)[:200])

        log_event(
            "access_sync_from_telegram_member_check_failed",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="No se pudo comprobar membresía de Telegram para resolver acceso pendiente.",
            metadata={
                "previous_subscription_status": previous_subscription_status,
                "previous_reason": previous_reason,
                "error": str(e)[:300]
            }
        )

        return access_state


    member_status = getattr(member, "status", None)


    if member_status not in ("member", "administrator", "creator"):

        return access_state


    try:

        sync_user_access_from_telegram_member(user_id, group_id)

    except Exception as e:

        print("sync_user_access_from_telegram_member_error:", str(e)[:200])

        return access_state


    access_state["telegram_group_id"] = telegram_group_id
    access_state["has_active_access"] = True
    access_state["has_user_access_record"] = True
    access_state["subscription_status"] = "active"
    access_state["access_source"] = "telegram_member"
    access_state["can_buy_again"] = False
    access_state["can_recover_link"] = True
    access_state["can_renew"] = False
    access_state["reason"] = "active_telegram_member"
    access_state["ignored_pending_payment"] = True
    access_state["ignored_pending_provider"] = access_state.get("last_payment_provider")

    metadata = {
        "group_id": group_id,
        "telegram_group_id": telegram_group_id,
        "previous_subscription_status": previous_subscription_status,
        "previous_reason": previous_reason,
        "ignored_pending_provider": access_state.get("ignored_pending_provider"),
        "ignored_pending_payment": access_state.get("ignored_pending_payment"),
        "telegram_member_status": member_status
    }

    log_event(
        "access_synced_from_telegram_member",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Acceso activo sincronizado porque el usuario ya es miembro en Telegram.",
        metadata=metadata
    )

    log_user_event_by_ids(
        user_id,
        "access_synced_from_telegram_member",
        event_key=f"telegram_member_{group_id}",
        group_id=group_id,
        metadata=metadata
    )

    return access_state


def build_existing_group_access_keyboard(group_id, access_state, retry_callback=None):

    keyboard = []
    telegram_group_id = access_state.get("telegram_group_id")


    if access_state.get("reason") == "owner_access":

        keyboard.append([InlineKeyboardButton(
            "⚙️ Gestionar comunidad",
            callback_data="admin_edit_group"
        )])
        keyboard.append([InlineKeyboardButton(
            "📊 Panel owner",
            callback_data="owner_panel_general"
        )])

    elif access_state.get("has_active_access"):

        keyboard.append([InlineKeyboardButton(
            "🔗 Recuperar/Reenviar enlace",
            callback_data=f"mysub_{telegram_group_id}" if telegram_group_id else "mis_subs"
        )])
        keyboard.append([InlineKeyboardButton(
            "📋 Ver mi suscripción",
            callback_data="mis_subs"
        )])

    elif access_state.get("reason") == "payment_pending_stale":

        keyboard.append([InlineKeyboardButton(
            "🔄 Crear nuevo pago / Ver planes",
            callback_data=f"group_{group_id}"
        )])

    elif access_state.get("subscription_status") == "pending":

        checkout_url = access_state.get("pending_payment_checkout_url")

        if access_state.get("pending_payment_can_resume") and checkout_url:

            keyboard.append([InlineKeyboardButton(
                "💳 Continuar pago",
                url=checkout_url
            )])

        else:

            keyboard.append([InlineKeyboardButton(
                "🔄 Crear nuevo pago / Ver planes",
                callback_data=f"group_{group_id}"
            )])

        keyboard.append([InlineKeyboardButton(
            "🔁 Revisar estado del pago",
            callback_data=f"payment_status_group_{group_id}"
        )])

    elif access_state.get("reason") == "paid_without_access_record":

        keyboard.append([InlineKeyboardButton(
            "📋 Ver mis suscripciones",
            callback_data="mis_subs"
        )])

    elif access_state.get("subscription_status") == "expired":

        keyboard.append([InlineKeyboardButton(
            "🔄 Renovar acceso",
            callback_data=f"group_{group_id}"
        )])
        keyboard.append([InlineKeyboardButton(
            "📋 Ver planes",
            callback_data=f"group_{group_id}"
        )])


    if retry_callback and access_state.get("can_buy_again"):

        keyboard.append([InlineKeyboardButton(
            "💳 Reintentar pago",
            callback_data=retry_callback
        )])


    if access_state.get("reason") != "owner_access":

        keyboard.append([InlineKeyboardButton(
            "🛟 Soporte",
            callback_data=f"public_support_group_{group_id}"
        )])
    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(keyboard)


async def send_existing_group_access_notice(context, chat_id, user_id, group_id, provider="unknown", event_type="purchase_blocked_existing_access", retry_callback=None, access_state=None):

    access_state = access_state or await resolve_group_access_state_for_user(
        context,
        user_id,
        group_id
    )
    log_purchase_blocked_existing_access(
        user_id,
        group_id,
        provider=provider,
        event_type=event_type,
        access_state=access_state
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=build_existing_group_access_text(access_state),
        reply_markup=build_existing_group_access_keyboard(
            group_id,
            access_state,
            retry_callback=retry_callback
        )
    )


LEGACY_CALLBACK_PREFIXES = (
    "account_",
    "support_issue_",
    "support_contact_",
    "help_section_",
    "set_language_",
    "admin_my_groups",
    "admin_group_"
)


def is_legacy_callback(callback_data):

    return (
        isinstance(callback_data, str)
        and callback_data.startswith(LEGACY_CALLBACK_PREFIXES)
    )


def parse_callback_int(data, prefix):

    if not isinstance(data, str) or not data.startswith(prefix):

        return None


    value = data.replace(prefix, "", 1)

    if not value.isdigit():

        return None


    return int(value)


def is_numeric_group_callback(callback_data):

    return parse_callback_int(callback_data, "group_") is not None


def is_stripe_checkout_callback(callback_data):

    return (
        isinstance(callback_data, str)
        and callback_data.startswith("price_")
    )








COUNTRY_BOUNDING_BOXES = {
    "ES": (27.5, 43.9, -18.3, 4.4),
    "MX": (14.4, 32.8, -118.5, -86.5),
    "AR": (-55.2, -21.8, -73.6, -53.6),
    "CO": (-4.3, 13.5, -79.0, -66.8),
    "CL": (-56.0, -17.0, -76.0, -66.0),
    "PE": (-18.5, 0.5, -81.5, -68.5),
    "VE": (0.5, 12.7, -73.5, -59.5),
    "EC": (-5.2, 1.8, -81.3, -75.0),
    "BO": (-22.9, -9.5, -69.7, -57.4),
    "PY": (-27.7, -19.2, -62.7, -54.2),
    "UY": (-35.1, -30.0, -58.6, -53.0),
    "CR": (8.0, 11.3, -86.1, -82.5),
    "PA": (7.0, 9.8, -83.1, -77.1),
    "GT": (13.6, 17.9, -92.4, -88.0),
    "HN": (12.9, 16.6, -89.4, -83.0),
    "SV": (13.0, 14.5, -90.2, -87.7),
    "NI": (10.7, 15.1, -87.8, -82.6),
    "DO": (17.4, 19.9, -72.1, -68.2),
    "CU": (19.6, 23.4, -85.0, -74.1),
    "PR": (17.8, 18.6, -67.4, -65.2),
    "GQ": (-1.7, 3.8, 5.0, 11.5)
}



LOCATION_BORDER_MARGIN_DEGREES = 0.08


def normalize_location_text(value):

    if value is None:

        return ""


    text = unicodedata.normalize(
        "NFKD",
        str(value).strip().lower()
    )
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    return "".join(
        char
        for char in text
        if char.isalnum()
    )


def resolve_country_code_alias(value):

    normalized_value = normalize_location_text(value)


    if not normalized_value:

        return None


    for country_code, country_label in HISPANIC_COUNTRY_LABELS.items():

        if normalized_value in (
            normalize_location_text(country_code),
            normalize_location_text(country_label)
        ):

            return country_code


    country_aliases = {
        "spain": "ES",
        "mexico": "MX",
        "dominicanrepublic": "DO",
        "republicadominicana": "DO",
        "equatorialguinea": "GQ",
        "guineaecuatorial": "GQ"
    }

    return country_aliases.get(normalized_value)


def resolve_spanish_autonomous_community_alias(value):

    normalized_value = normalize_location_text(value)


    if not normalized_value:

        return None


    community_aliases = {
        "todaespana": "all_spain",
        "espana": "all_spain",
        "spain": "all_spain",
        "comunidadvalenciana": COMUNIDAD_VALENCIANA_REGION,
        "comunitatvalenciana": COMUNIDAD_VALENCIANA_REGION,
        "valenciancommunity": COMUNIDAD_VALENCIANA_REGION,
        "valencia": COMUNIDAD_VALENCIANA_REGION,
        "alicante": COMUNIDAD_VALENCIANA_REGION,
        "castellon": COMUNIDAD_VALENCIANA_REGION,
        "castello": COMUNIDAD_VALENCIANA_REGION,
        "paisvalencia": COMUNIDAD_VALENCIANA_REGION
    }


    if normalized_value in community_aliases:

        return community_aliases[normalized_value]


    for community_slug, community_label in SPANISH_AUTONOMOUS_COMMUNITY_LABELS.items():

        if normalized_value in (
            normalize_location_text(community_slug),
            normalize_location_text(community_label)
        ):

            return community_slug


    return None


SPANISH_LOCATION_FIXTURE_BOXES = [
    # Fixtures near the Alicante/Murcia border. They are checked before broad
    # autonomous-community boxes because the coarse Murcia box overlaps Elche.
    (COMUNIDAD_VALENCIANA_REGION, "Alicante", "Elche", 38.19, 38.36, -0.82, -0.58),
    (COMUNIDAD_VALENCIANA_REGION, "Alicante", "Alicante", 38.25, 38.43, -0.58, -0.35),
    (COMUNIDAD_VALENCIANA_REGION, "Alicante", "Torrevieja", 37.90, 38.05, -0.78, -0.60),
    (COMUNIDAD_VALENCIANA_REGION, "Alicante", "Orihuela", 37.85, 38.15, -1.05, -0.80),
    ("region_de_murcia", None, "Murcia capital", 37.85, 38.08, -1.35, -1.00),
    ("region_de_murcia", None, "Cartagena", 37.50, 37.70, -1.10, -0.85),
    (COMUNIDAD_VALENCIANA_REGION, "Valencia", "Valencia capital", 39.36, 39.58, -0.50, -0.28),
    (COMUNIDAD_VALENCIANA_REGION, "Castellón", "Castellón", 39.90, 40.10, -0.15, 0.15)
]

SPANISH_AUTONOMOUS_COMMUNITY_BOXES = [
    ("ceuta", None, 35.86, 35.92, -5.38, -5.27),
    ("melilla", None, 35.24, 35.35, -3.05, -2.88),
    ("canarias", None, 27.5, 29.5, -18.3, -13.3),
    ("andalucia", None, 35.8, 38.8, -7.6, -1.6),
    ("region_de_murcia", None, 37.3, 38.9, -2.4, -0.6),
    (COMUNIDAD_VALENCIANA_REGION, "Alicante", 37.75, 38.95, -1.05, 0.25),
    (COMUNIDAD_VALENCIANA_REGION, "Valencia", 38.65, 40.05, -1.60, -0.05),
    (COMUNIDAD_VALENCIANA_REGION, "Castellón", 39.70, 40.85, -0.90, 0.60),
    ("extremadura", None, 37.9, 40.5, -7.6, -4.6),
    ("comunidad_de_madrid", None, 39.9, 41.2, -4.6, -3.0),
    ("castilla_la_mancha", None, 38.0, 41.4, -5.4, -1.0),
    ("islas_baleares", None, 38.6, 40.2, 1.1, 4.4),
    ("cataluna", None, 40.5, 42.9, 0.1, 3.4),
    ("aragon", None, 39.8, 42.9, -2.2, 0.9),
    ("castilla_y_leon", None, 40.0, 43.3, -7.1, -1.8),
    ("la_rioja", None, 41.8, 42.7, -3.2, -1.7),
    ("navarra", None, 41.9, 43.3, -2.6, -0.7),
    ("pais_vasco", None, 42.4, 43.6, -3.5, -1.7),
    ("cantabria", None, 42.75, 43.55, -4.9, -3.1),
    ("asturias", None, 42.9, 43.7, -7.2, -4.5),
    ("galicia", None, 41.8, 43.8, -9.4, -6.7)
]


def point_in_box(lat, lon, box):

    min_lat, max_lat, min_lon, max_lon = box

    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def is_near_location_box_border(lat, lon, box, margin=LOCATION_BORDER_MARGIN_DEGREES):

    min_lat, max_lat, min_lon, max_lon = box

    return (
        abs(lat - min_lat) <= margin
        or abs(max_lat - lat) <= margin
        or abs(lon - min_lon) <= margin
        or abs(max_lon - lon) <= margin
    )


def is_location_in_comunidad_valenciana(lat, lon):

    resolved = resolve_location_region(lat, lon)

    return (
        resolved.get("spanish_autonomous_community") == COMUNIDAD_VALENCIANA_LABEL,
        resolved.get("province")
    )


def resolve_location_region(lat, lon):

    country_code = None


    for code, box in COUNTRY_BOUNDING_BOXES.items():

        if point_in_box(lat, lon, box):

            country_code = code

            break


    country_name = HISPANIC_COUNTRY_LABELS.get(country_code)
    autonomous_community = None
    province = None
    detection_source = None
    near_boundary = False
    matched_box = None


    if country_code == "ES":

        for slug, detected_province, fixture_name, min_lat, max_lat, min_lon, max_lon in SPANISH_LOCATION_FIXTURE_BOXES:

            box = (min_lat, max_lat, min_lon, max_lon)

            if point_in_box(lat, lon, box):

                autonomous_community = SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(slug)
                province = detected_province
                detection_source = f"fixture:{fixture_name}"
                near_boundary = is_near_location_box_border(lat, lon, box)
                matched_box = {
                    "name": fixture_name,
                    "min_lat": min_lat,
                    "max_lat": max_lat,
                    "min_lon": min_lon,
                    "max_lon": max_lon
                }

                break


    if country_code == "ES" and not autonomous_community:

        for slug, detected_province, min_lat, max_lat, min_lon, max_lon in SPANISH_AUTONOMOUS_COMMUNITY_BOXES:

            box = (min_lat, max_lat, min_lon, max_lon)

            if point_in_box(lat, lon, box):

                autonomous_community = SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(slug)
                province = detected_province
                detection_source = "autonomous_community_box"
                near_boundary = is_near_location_box_border(lat, lon, box)
                matched_box = {
                    "name": slug,
                    "min_lat": min_lat,
                    "max_lat": max_lat,
                    "min_lon": min_lon,
                    "max_lon": max_lon
                }

                break


    return {
        "country": country_code,
        "country_name": country_name,
        "spanish_autonomous_community": autonomous_community,
        "province": province,
        "detection_source": detection_source,
        "near_boundary": near_boundary,
        "matched_box": matched_box
    }


def normalize_allowed_region_type(region_type, allowed_region):

    country_code = resolve_country_code_alias(allowed_region)
    community_slug = resolve_spanish_autonomous_community_alias(allowed_region)


    if region_type:

        if (
            region_type == LOCATION_REGION_TYPE_COUNTRY
            and community_slug
            and community_slug != "all_spain"
            and not country_code
        ):

            return LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY


        if (
            region_type == LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY
            and community_slug == "all_spain"
        ):

            return LOCATION_REGION_TYPE_COUNTRY


        return region_type


    if country_code or community_slug == "all_spain":

        return LOCATION_REGION_TYPE_COUNTRY


    if community_slug:

        return LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY


    return LOCATION_REGION_TYPE_COUNTRY


def normalize_allowed_region(region_type, allowed_region):

    if region_type == LOCATION_REGION_TYPE_COUNTRY:

        return resolve_country_code_alias(allowed_region) or "ES"


    community_slug = resolve_spanish_autonomous_community_alias(allowed_region)


    if community_slug == "all_spain":

        return COMUNIDAD_VALENCIANA_REGION


    return community_slug or allowed_region or COMUNIDAD_VALENCIANA_REGION


def format_allowed_region(region_type, allowed_region):

    region_type = normalize_allowed_region_type(region_type, allowed_region)
    allowed_region = normalize_allowed_region(region_type, allowed_region)


    if region_type == LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY:

        return (
            f"{SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(allowed_region, allowed_region)}, España"
        )


    return HISPANIC_COUNTRY_LABELS.get(allowed_region, allowed_region or "España")


def location_matches_allowed_region(resolved_region, region_type, allowed_region):

    region_type = normalize_allowed_region_type(region_type, allowed_region)
    allowed_region = normalize_allowed_region(region_type, allowed_region)


    if region_type == LOCATION_REGION_TYPE_COUNTRY:

        return resolved_region.get("country") == allowed_region


    if region_type == LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY:

        detected_community_slug = resolve_spanish_autonomous_community_alias(
            resolved_region.get("spanish_autonomous_community")
        )

        return (
            resolved_region.get("country") == "ES"
            and detected_community_slug == allowed_region
        )


    return False


def format_detected_location_region(resolved_region):

    resolved_region = resolved_region or {}


    if not resolved_region.get("country"):

        return "región no identificada"


    if resolved_region.get("country") == "ES":

        detected_parts = []


        if resolved_region.get("spanish_autonomous_community"):

            detected_parts.append(resolved_region.get("spanish_autonomous_community"))


        if resolved_region.get("province"):

            detected_parts.append(resolved_region.get("province"))


        detected_parts.append("España")

        return ", ".join(detected_parts)


    return resolved_region.get("country_name") or resolved_region.get("country")


def get_location_rejection_reason(resolved_region, region_type, allowed_region):

    region_type = normalize_allowed_region_type(region_type, allowed_region)
    allowed_region = normalize_allowed_region(region_type, allowed_region)
    detected_label = format_detected_location_region(resolved_region)


    if not resolved_region or not resolved_region.get("country"):

        return (
            "location_geocode_failed",
            "No he podido identificar el país o la región de la ubicación recibida.",
            detected_label
        )


    if region_type == LOCATION_REGION_TYPE_COUNTRY:

        expected_country = HISPANIC_COUNTRY_LABELS.get(allowed_region, allowed_region)

        return (
            "location_region_mismatch",
            f"La ubicación detectada es {detected_label}, pero esta comunidad permite {expected_country}.",
            detected_label
        )


    if region_type == LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY:

        if resolved_region.get("country") != "ES":

            return (
                "location_region_mismatch",
                f"La ubicación detectada es {detected_label}, pero esta comunidad permite una comunidad autónoma de España.",
                detected_label
            )


        if not resolved_region.get("spanish_autonomous_community"):

            return (
                "location_geocode_failed",
                "He detectado España, pero no he podido identificar la comunidad autónoma con suficiente seguridad.",
                detected_label
            )


        expected_region = SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(allowed_region, allowed_region)

        return (
            "location_region_mismatch",
            f"La ubicación detectada es {detected_label}, pero esta comunidad permite {expected_region}, España.",
            detected_label
        )


    return (
        "location_check_failed",
        "No he podido validar esta ubicación con la regla configurada.",
        detected_label
    )


def build_location_log_metadata(region_type, allowed_region, region_label, resolved_region, reason, location=None, action=None):

    resolved_region = resolved_region or {}
    metadata = {
        "rule_type": normalize_allowed_region_type(region_type, allowed_region),
        "allowed_region": region_label,
        "allowed_region_raw": allowed_region,
        "detected_country": resolved_region.get("country"),
        "detected_country_name": resolved_region.get("country_name"),
        "detected_region": resolved_region.get("spanish_autonomous_community"),
        "detected_province": resolved_region.get("province"),
        "detected_label": format_detected_location_region(resolved_region),
        "detection_source": resolved_region.get("detection_source"),
        "near_boundary": resolved_region.get("near_boundary") is True,
        "reason": reason,
        "action": action
    }

    matched_box = resolved_region.get("matched_box")


    if matched_box:

        metadata["matched_box"] = matched_box.get("name")


    if location:

        metadata["telegram_location_received"] = True
        metadata["lat_approx"] = round(location.latitude, 1)
        metadata["lon_approx"] = round(location.longitude, 1)


    return metadata


def build_location_denied_keyboard(group_id=None):

    if group_id:

        return InlineKeyboardMarkup([

            [InlineKeyboardButton(
                "📩 Solicitar revisión manual",
                callback_data=f"location_review_request_{group_id}"
            )],

            [InlineKeyboardButton(
                "🔄 Enviar otra ubicación",
                callback_data=f"location_review_send_location_{group_id}"
            )],

            [InlineKeyboardButton(
                "🏠 Inicio",
                callback_data="public_back_start"
            )]

        ])

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "🛟 Contactar soporte",
            callback_data="public_support"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def clear_location_manual_review_state(context):

    for key in [
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
    ]:

        context.user_data.pop(key, None)


def build_location_manual_review_metadata(review=None, ticket=None):

    review = review or {}
    ticket = ticket or {}

    return {
        "review_id": review.get("id"),
        "user_id": review.get("user_id") or ticket.get("user_id"),
        "group_id": review.get("group_id") or ticket.get("group_id"),
        "telegram_group_id": review.get("telegram_group_id"),
        "support_ticket_id": review.get("support_ticket_id") or ticket.get("id"),
        "status": review.get("status"),
        "expires_at": str(review.get("expires_at")) if review.get("expires_at") else None,
        "allowed_region": review.get("allowed_region"),
        "allowed_region_type": review.get("allowed_region_type")
    }


def fetch_group_location_review_details(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   name,
                   telegram_group_id,
                   allowed_region,
                   allowed_region_type
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    if not row:

        return None


    group_id, name, telegram_group_id, allowed_region, allowed_region_type = row
    region_type = normalize_allowed_region_type(
        allowed_region_type,
        allowed_region
    )
    normalized_region = normalize_allowed_region(
        region_type,
        allowed_region
    )

    return {
        "group_id": group_id,
        "name": name,
        "telegram_group_id": telegram_group_id,
        "allowed_region": normalized_region,
        "allowed_region_type": region_type,
        "allowed_region_label": format_allowed_region(
            region_type,
            normalized_region
        )
    }




def row_to_location_manual_review(row):

    if not row:

        return None


    return dict(zip(LOCATION_MANUAL_REVIEW_FIELDS, row))


def fetch_location_manual_review(review_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(LOCATION_MANUAL_REVIEW_FIELDS)}
            FROM location_manual_reviews
            WHERE id=%s
            LIMIT 1

        """, (review_id,))

        row = cur.fetchone()


    return row_to_location_manual_review(row)


def fetch_active_location_manual_review(user_id, group_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(LOCATION_MANUAL_REVIEW_FIELDS)}
            FROM location_manual_reviews
            WHERE user_id=%s
            AND group_id=%s
            AND status='approved_temp'
            AND expires_at > NOW()
            ORDER BY expires_at DESC
            LIMIT 1

        """, (
            user_id,
            group_id
        ))

        row = cur.fetchone()


    return row_to_location_manual_review(row)


def group_has_location_manual_reviews(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM location_manual_reviews
            WHERE group_id=%s
            LIMIT 1

        """, (group_id,))

        return cur.fetchone() is not None


def should_show_owner_location_reviews_button(group_id):

    location_enabled, _allowed_region, _region_type = get_group_location_gate(group_id)

    return location_enabled is True or group_has_location_manual_reviews(group_id)






def mark_location_manual_review_completed(user_id, group_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE location_manual_reviews
            SET status='completed',
                completed_at=NOW(),
                updated_at=NOW()
            WHERE id IN (
                SELECT id
                FROM location_manual_reviews
                WHERE user_id=%s
                AND group_id=%s
                AND status IN ('pending', 'approved_temp')
                ORDER BY created_at DESC
                LIMIT 1
            )
            RETURNING {", ".join(LOCATION_MANUAL_REVIEW_FIELDS)}

        """, (
            user_id,
            group_id
        ))

        row = cur.fetchone()


    return row_to_location_manual_review(row)






def create_location_manual_review(user, group_details, answers, failed_latitude=None, failed_longitude=None):

    ticket = get_or_create_support_ticket(
        user,
        group_id=group_details.get("group_id")
    )

    ticket_summary = (
        "📍 Solicitud de revisión manual de ubicación\n\n"
        f"Comunidad: {group_details.get('name') or group_details.get('group_id')}\n"
        f"Zona permitida: {group_details.get('allowed_region_label')}\n"
        f"Ubicación fallida: {failed_latitude or '-'}, {failed_longitude or '-'}\n\n"
        "Respuestas del formulario:\n"
        f"1. Motivo: {answers.get('reason') or '-'}\n"
        f"2. Justificación residencia: {answers.get('residence_proof') or '-'}\n"
        f"3. Cuándo podrá enviar ubicación válida: {answers.get('valid_location_eta') or '-'}"
    )

    create_support_message(
        ticket.get("id"),
        "user",
        user.id,
        ticket_summary
    )

    update_support_ticket_status(
        ticket.get("id"),
        "open"
    )

    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO location_manual_reviews
            (
                user_id,
                group_id,
                telegram_group_id,
                support_ticket_id,
                requested_by_user_id,
                status,
                failed_latitude,
                failed_longitude,
                allowed_region,
                allowed_region_type,
                question_1_reason,
                question_2_residence_proof,
                question_3_valid_location_eta,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING {", ".join(LOCATION_MANUAL_REVIEW_FIELDS)}

        """, (
            user.id,
            group_details.get("group_id"),
            group_details.get("telegram_group_id"),
            ticket.get("id"),
            user.id,
            failed_latitude,
            failed_longitude,
            group_details.get("allowed_region"),
            group_details.get("allowed_region_type"),
            answers.get("reason"),
            answers.get("residence_proof"),
            answers.get("valid_location_eta")
        ))

        row = cur.fetchone()


    review = row_to_location_manual_review(row)

    return review, ticket


def user_can_manage_location_manual_review(user_id, group_id):

    if is_super_admin(user_id):

        return True


    owner_user_id = get_group_owner_user_id(group_id)


    try:

        if owner_user_id is not None and int(owner_user_id) == int(user_id):

            return True

    except Exception:

        pass


    return user_has_group_permission_any(
        user_id,
        group_id,
        ["can_respond_group_support", "can_manage_groups"]
    )


def fetch_location_review_admin_recipients(group_id):

    recipients = set()
    owner_user_id = get_group_owner_user_id(group_id)


    if owner_user_id:

        recipients.add(int(owner_user_id))


    recipients.add(int(ADMIN_ID))


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id
                FROM admins
                WHERE group_id=%s
                AND is_active=TRUE
                AND (
                    role='GROUP_OWNER'
                    OR can_respond_group_support=TRUE
                    OR can_manage_groups=TRUE
                )

            """, (group_id,))

            for row in cur.fetchall():

                if row and row[0]:

                    recipients.add(int(row[0]))

    except Exception as e:

        print("Error obteniendo admins para revisión manual:", e)


    return list(recipients)


def format_location_manual_review_detail(review, ticket=None):

    group_details = fetch_group_location_review_details(
        review.get("group_id")
    ) or {}

    failed_location = (
        f"{review.get('failed_latitude')}, {review.get('failed_longitude')}"
        if review.get("failed_latitude") is not None and review.get("failed_longitude") is not None
        else "-"
    )

    return (
        f"📍 Revisión manual de ubicación #{review.get('id')}\n\n"
        f"Estado: {review.get('status') or '-'}\n"
        f"Usuario: {review.get('user_id') or '-'}\n"
        f"Comunidad: {group_details.get('name') or review.get('group_id')}\n"
        f"Group ID: {review.get('group_id') or '-'}\n"
        f"Telegram group ID: {review.get('telegram_group_id') or '-'}\n"
        f"Ticket: #{review.get('support_ticket_id') or '-'}\n"
        f"Ubicación fallida: {failed_location}\n"
        f"Zona permitida: {format_allowed_region(review.get('allowed_region_type'), review.get('allowed_region'))}\n\n"
        "Respuestas del formulario:\n"
        f"1. Motivo: {review.get('question_1_reason') or '-'}\n"
        f"2. Justificación residencia: {review.get('question_2_residence_proof') or '-'}\n"
        f"3. Cuándo podrá enviar ubicación válida: {review.get('question_3_valid_location_eta') or '-'}"
    )




def format_location_review_reason_preview(reason):

    if not reason:

        return "-"


    first_line = str(reason).strip().splitlines()[0].strip()

    return first_line[:120] if first_line else "-"










def build_location_manual_review_admin_keyboard(review):

    review_id = review.get("id")
    ticket_id = review.get("support_ticket_id")
    keyboard = []


    if review.get("status") == "pending":

        keyboard.append([InlineKeyboardButton(
            "✅ Aprobar revisión temporal 7 días",
            callback_data=f"location_review_approve7_{review_id}"
        )])
        keyboard.append([InlineKeyboardButton(
            "❌ Rechazar revisión",
            callback_data=f"location_review_reject_{review_id}"
        )])


    if ticket_id:

        keyboard.append([InlineKeyboardButton(
            "💬 Responder al usuario",
            callback_data=f"owner_support_reply_{ticket_id}"
        )])
        keyboard.append([InlineKeyboardButton(
            "🛟 Abrir ticket",
            callback_data=f"owner_support_ticket_{ticket_id}"
        )])


    return InlineKeyboardMarkup(keyboard)


async def notify_location_manual_review_admins(context, review, ticket):

    text = format_location_manual_review_detail(
        review,
        ticket=ticket
    )
    keyboard = build_location_manual_review_admin_keyboard(review)


    for recipient_id in fetch_location_review_admin_recipients(review.get("group_id")):

        try:

            await context.bot.send_message(
                chat_id=recipient_id,
                text=text,
                reply_markup=keyboard
            )

        except Exception as e:

            print("Error avisando revisión manual de ubicación:", recipient_id, e)


# Tandas fallidas seguidas antes de pausar sola una campaña de promoción.
AD_PROMO_MAX_CONSECUTIVE_FAILURES = int(
    os.environ.get("AD_PROMO_MAX_CONSECUTIVE_FAILURES", "5")
)





def row_to_ad_promo_campaign(row):

    return dict(zip(AD_PROMO_CAMPAIGN_FIELDS, row)) if row else None


def row_to_ad_promo_media(row):

    return dict(zip(AD_PROMO_MEDIA_FIELDS, row)) if row else None


def fetch_ad_promo_campaign(campaign_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(AD_PROMO_CAMPAIGN_FIELDS)}
            FROM ad_promo_campaigns
            WHERE id=%s
            LIMIT 1

        """, (campaign_id,))

        row = cur.fetchone()


    return row_to_ad_promo_campaign(row)






def fetch_ad_promo_capture_campaigns(source_chat_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(AD_PROMO_CAMPAIGN_FIELDS)}
            FROM ad_promo_campaigns
            WHERE source_chat_id=%s
            AND is_active=TRUE
            AND is_paused=FALSE
            AND auto_capture_enabled=TRUE

        """, (source_chat_id,))

        rows = cur.fetchall()


    return [row_to_ad_promo_campaign(row) for row in rows]


def fetch_due_ad_promo_campaigns(limit=10):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(AD_PROMO_CAMPAIGN_FIELDS)}
            FROM ad_promo_campaigns
            WHERE is_active=TRUE
            AND is_paused=FALSE
            AND (
                next_run_at IS NULL
                OR next_run_at <= NOW()
            )
            ORDER BY next_run_at NULLS FIRST,
                     updated_at ASC
            LIMIT %s

        """, (limit,))

        rows = cur.fetchall()


    return [row_to_ad_promo_campaign(row) for row in rows]


def fetch_due_ad_promo_daily_reviews(limit=10):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(AD_PROMO_CAMPAIGN_FIELDS)}
            FROM ad_promo_campaigns
            WHERE is_active=TRUE
            AND (
                next_offer_check_at IS NULL
                OR next_offer_check_at <= NOW()
            )
            ORDER BY next_offer_check_at NULLS FIRST,
                     updated_at ASC
            LIMIT %s

        """, (limit,))

        rows = cur.fetchall()


    return [row_to_ad_promo_campaign(row) for row in rows]


def count_ad_promo_media(campaign_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*) FILTER (WHERE is_active=TRUE),
                   COUNT(*) FILTER (WHERE is_active IS DISTINCT FROM TRUE),
                   COUNT(*),
                   MAX(created_at) FILTER (WHERE is_active=TRUE),
                   MAX(created_at)
            FROM ad_promo_media
            WHERE campaign_id=%s

        """, (campaign_id,))

        row = cur.fetchone()


    return {
        "active": row[0] if row else 0,
        "inactive": row[1] if row else 0,
        "total": row[2] if row else 0,
        "last_capture": (row[3] or row[4]) if row else None
    }


def get_ad_promo_media_counts(campaign_id):

    return count_ad_promo_media(campaign_id)


def extract_ad_promo_migrated_chat_id(error):

    migrate_to_chat_id = getattr(error, "migrate_to_chat_id", None)

    if migrate_to_chat_id is not None:

        try:

            return int(migrate_to_chat_id)

        except Exception:

            return None


    error_text = str(error or "")
    match = re.search(
        r"Group migrated to supergroup\. New chat id:\s*(-?\d+)",
        error_text,
        flags=re.IGNORECASE
    )

    if not match:

        return None


    try:

        return int(match.group(1))

    except Exception:

        return None


def update_ad_promo_campaign_promo_chat_id(campaign_id, new_chat_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE ad_promo_campaigns
            SET promo_group_telegram_id=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(AD_PROMO_CAMPAIGN_FIELDS)}

        """, (
            new_chat_id,
            campaign_id
        ))

        row = cur.fetchone()
        conn.commit()


    return row_to_ad_promo_campaign(row)






def select_ad_promo_media_for_batch(campaign, test=False):

    order_sql = (
        "RANDOM()"
        if campaign.get("randomize_media")
        else "last_sent_at NULLS FIRST, usage_count ASC, created_at ASC"
    )
    campaign_id = campaign.get("id")
    try:

        batch_size = int(campaign.get("batch_size") or 1)

    except Exception:

        batch_size = 1


    batch_size = max(batch_size, 1)

    if test:

        batch_size = max(batch_size, 1)


    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*)
            FROM ad_promo_media
            WHERE campaign_id=%s
            AND is_active=TRUE

        """, (campaign_id,))

        active_count = cur.fetchone()[0]


    recent_filter = ""

    if campaign.get("randomize_media") and active_count > batch_size * 2:

        recent_filter = "AND (last_sent_at IS NULL OR last_sent_at < NOW() - INTERVAL '12 hours')"


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(AD_PROMO_MEDIA_FIELDS)}
            FROM ad_promo_media
            WHERE campaign_id=%s
            AND is_active=TRUE
            {recent_filter}
            ORDER BY {order_sql}
            LIMIT %s

        """, (
            campaign_id,
            batch_size
        ))

        rows = cur.fetchall()


    if len(rows) < batch_size and recent_filter:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT {", ".join(AD_PROMO_MEDIA_FIELDS)}
                FROM ad_promo_media
                WHERE campaign_id=%s
                AND is_active=TRUE
                ORDER BY {order_sql}
                LIMIT %s

            """, (
                campaign_id,
                batch_size
            ))

            rows = cur.fetchall()


    return [row_to_ad_promo_media(row) for row in rows]


def create_ad_promo_campaign(data):

    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO ad_promo_campaigns
            (
                paid_group_id,
                source_chat_id,
                source_chat_title,
                source_chat_type,
                promo_group_telegram_id,
                promo_group_title,
                promo_group_type,
                batch_size,
                interval_minutes,
                max_posts,
                bot_link,
                offer_text,
                price_text,
                cta_text,
                created_by_user_id,
                updated_by_user_id,
                next_run_at,
                next_offer_check_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW() + INTERVAL '10 minutes', NOW() + INTERVAL '24 hours', NOW())
            RETURNING {", ".join(AD_PROMO_CAMPAIGN_FIELDS)}

        """, (
            data.get("paid_group_id"),
            data.get("source_chat_id"),
            data.get("source_chat_title"),
            data.get("source_chat_type"),
            data.get("promo_group_telegram_id"),
            data.get("promo_group_title"),
            data.get("promo_group_type") or "group",
            data.get("batch_size") or 5,
            data.get("interval_minutes") or 60,
            data.get("max_posts") or 50,
            data.get("bot_link"),
            data.get("offer_text"),
            data.get("price_text"),
            data.get("cta_text"),
            data.get("created_by_user_id"),
            data.get("created_by_user_id")
        ))

        row = cur.fetchone()


    return row_to_ad_promo_campaign(row)


def update_ad_promo_campaign(campaign_id, updates, actor_user_id=None):

    allowed_fields = {
        "is_active",
        "is_paused",
        "auto_capture_enabled",
        "randomize_media",
        "ai_copy_enabled",
        "batch_size",
        "interval_minutes",
        "max_posts",
        "delete_old_posts",
        "bot_link",
        "marketplace_link",
        "default_caption",
        "offer_text",
        "price_text",
        "cta_text",
        "tone",
        "watermark_mode",
        "watermark_text",
        "watermark_position",
        "watermark_max_file_size_mb",
        "watermark_max_duration_seconds",
        "watermark_opacity",
        "last_run_at",
        "next_run_at",
        "last_offer_check_at",
        "next_offer_check_at",
        "consecutive_failures",
        "last_error_text",
        "paused_reason"
    }
    set_parts = []
    params = []


    for field, value in updates.items():

        if field not in allowed_fields:

            continue


        set_parts.append(f"{field}=%s")
        params.append(value)


    if actor_user_id is not None:

        set_parts.append("updated_by_user_id=%s")
        params.append(actor_user_id)


    if not set_parts:

        return fetch_ad_promo_campaign(campaign_id)


    set_parts.append("updated_at=NOW()")
    params.append(campaign_id)

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE ad_promo_campaigns
            SET {", ".join(set_parts)}
            WHERE id=%s
            RETURNING {", ".join(AD_PROMO_CAMPAIGN_FIELDS)}

        """, params)

        row = cur.fetchone()


    return row_to_ad_promo_campaign(row)


def save_ad_promo_media(campaign, message, chat):

    video = getattr(message, "video", None)

    if not video:

        return None


    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO ad_promo_media
            (
                campaign_id,
                paid_group_id,
                source_chat_id,
                source_message_id,
                telegram_file_id,
                file_unique_id,
                media_type,
                duration,
                width,
                height,
                file_size,
                original_caption
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'video', %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING {", ".join(AD_PROMO_MEDIA_FIELDS)}

        """, (
            campaign.get("id"),
            campaign.get("paid_group_id"),
            chat.id if chat else campaign.get("source_chat_id"),
            message.message_id,
            video.file_id,
            video.file_unique_id,
            video.duration,
            video.width,
            video.height,
            video.file_size,
            getattr(message, "caption", None)
        ))

        row = cur.fetchone()


    return row_to_ad_promo_media(row)


async def capture_ad_promo_video(update, context):

    message = update.channel_post or update.message
    chat = update.effective_chat


    if not message or not chat or not getattr(message, "video", None):

        return []


    campaigns = fetch_ad_promo_capture_campaigns(chat.id)
    captured = []


    for campaign in campaigns:

        media = save_ad_promo_media(campaign, message, chat)

        if not media:

            continue


        captured.append(media)
        log_event(
            "ad_promo_media_captured",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            message="Vídeo capturado para biblioteca de promoción automática.",
            metadata={
                "campaign_id": campaign.get("id"),
                "media_id": media.get("id"),
                "source_chat_id": chat.id,
                "source_message_id": message.message_id,
                "file_unique_id": media.get("file_unique_id")
            }
        )


    return captured


def sanitize_ad_promo_text(text):

    cleaned = sanitize_ai_text(text or "")

    for word in ("Codex", "GitHub", "Railway", "userbot", "scraping"):

        cleaned = cleaned.replace(word, "")


    return cleaned.strip()[:900]


def is_generic_ad_promo_extra_field(field, text):

    normalized = (text or "").strip().lower()

    if not normalized:

        return True


    generic_offer_texts = {
        "promo activa esta semana",
        "promo activa esta semana.",
        "oferta activa esta semana",
        "oferta activa esta semana."
    }
    generic_cta_fragments = (
        "entra al bot y revisa los planes disponibles",
        "revisa los planes disponibles",
        "consulta los planes disponibles"
    )


    if field == "offer_text" and normalized in generic_offer_texts:

        return True


    if field == "cta_text" and any(fragment in normalized for fragment in generic_cta_fragments):

        return True


    return False


def is_low_quality_legacy_ad_promo_copy(text):

    normalized = normalize_ad_promo_compare_text(text)
    legacy_patterns = (
        "promo activa esta semana",
        "entra al bot y revisa los planes disponibles",
        "atencion comunidad",
        "atencion starsvip",
        "no querras perderte",
        "la curiosidad esta en el aire",
        "accede a nuestros planes",
        "por solo 6 99",
        "solo 6 99 eur",
        "revisa los detalles en nuestro bot",
        "unete a la experiencia"
    )

    return any(pattern in normalized for pattern in legacy_patterns)


def format_ad_promo_price_text(price_text):

    text = sanitize_ad_promo_text(price_text)

    if not text:

        return None


    if "opciones premium" in normalize_ad_promo_compare_text(text):

        return text


    permanent = "permanente" in normalize_ad_promo_compare_text(text)
    text = re.sub(r"\bpermanente\b", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s+", " ", text)


    if text.lower().startswith("acceso desde"):

        text = re.sub(
            r"^acceso\s+desde",
            "⭐ Opciones premium desde",
            text,
            flags=re.IGNORECASE
        ).strip()

    elif not text.startswith("⭐"):

        text = f"⭐ {text}"


    if permanent and "acceso permanente" not in normalize_ad_promo_compare_text(text):

        text = f"{text} · Acceso permanente"


    return text


def normalize_ad_promo_compare_text(text):

    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)

    return " ".join(text.split())


def ad_promo_text_contains_cta(text):

    normalized = normalize_ad_promo_compare_text(text)
    cta_fragments = (
        "abre el bot",
        "abrir el bot",
        "entra al bot",
        "entrar al bot",
        "revisa desde el bot",
        "revisar desde el bot",
        "explora desde el bot",
        "explorar desde el bot",
        "mira que comunidades",
        "mira que hay disponible",
        "descubre desde el bot",
        "gestiona tus accesos",
        "todo desde el bot"
    )

    return any(fragment in normalized for fragment in cta_fragments)


def ad_promo_text_mentions_offer_theme(text):

    normalized = normalize_ad_promo_compare_text(text)
    theme_words = (
        "gratis",
        "gratuito",
        "gratuitos",
        "premium",
        "explora",
        "explorar",
        "descubre",
        "descubrir",
        "comunidades",
        "grupos",
        "bot",
        "accesos",
        "planes"
    )

    return any(word in normalized.split() for word in theme_words)


def should_append_ad_promo_extra_field(field, text, base_copy):

    if is_generic_ad_promo_extra_field(field, text):

        return False


    normalized_text = normalize_ad_promo_compare_text(text)
    normalized_base = normalize_ad_promo_compare_text(base_copy)

    if not normalized_text:

        return False


    if normalized_text in normalized_base:

        return False


    if field == "price_text":

        return True


    if field == "offer_text" and ad_promo_text_mentions_offer_theme(base_copy):

        return False


    if field == "cta_text" and ad_promo_text_contains_cta(base_copy):

        return False


    return True


def build_ad_promo_bot_link(campaign, bot_username=None):

    if campaign.get("bot_link"):

        return campaign.get("bot_link")


    if bot_username:

        return f"https://t.me/{bot_username}?start=group_{campaign.get('paid_group_id')}"


    return campaign.get("marketplace_link") or "-"


def build_local_ad_promo_copy(campaign):

    hour = datetime.now().hour

    if datetime.now().weekday() >= 5:

        return (
            "🤖 Descubre comunidades desde nuestro bot\n\n"
            "Puedes empezar por grupos gratuitos y revisar también opciones premium si quieres una experiencia más completa.\n\n"
            "Explora lo disponible, compara con calma y elige desde el bot."
        )


    if hour < 12:

        return (
            "👀 ¿Buscas nuevos grupos para explorar?\n\n"
            "Desde el bot puedes encontrar comunidades gratuitas para empezar sin compromiso y opciones premium para ir más allá.\n\n"
            "Abre el menú y mira qué comunidades están activas."
        )


    if hour < 19:

        return (
            "🎁 Empieza gratis y decide después\n\n"
            "Nuestra red reúne comunidades gratuitas y planes premium en un solo bot, para que puedas descubrir opciones antes de elegir.\n\n"
            "Revisa lo disponible desde el menú principal."
        )


    return (
        "⭐ Un bot, varias comunidades\n\n"
        "Explora grupos gratuitos, descubre opciones premium y gestiona tus accesos desde un mismo lugar.\n\n"
        "Abre el bot y mira qué encaja contigo."
    )


def fetch_ad_promo_copy_variant(campaign_id):

    for _attempt in range(5):

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM ad_promo_copy_variants
                WHERE campaign_id=%s
                AND is_active=TRUE

            """, (campaign_id,))

            active_count = cur.fetchone()[0]


        freshness_filter = ""

        if active_count > 3:

            freshness_filter = "AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '6 hours')"


        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT id,
                       text
                FROM ad_promo_copy_variants
                WHERE campaign_id=%s
                AND is_active=TRUE
                {freshness_filter}
                ORDER BY last_used_at NULLS FIRST,
                         usage_count ASC,
                         RANDOM()
                LIMIT 1

            """, (campaign_id,))

            row = cur.fetchone()


        if not row and freshness_filter:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id,
                           text
                    FROM ad_promo_copy_variants
                    WHERE campaign_id=%s
                    AND is_active=TRUE
                    ORDER BY last_used_at NULLS FIRST,
                             usage_count ASC,
                             RANDOM()
                    LIMIT 1

                """, (campaign_id,))

                row = cur.fetchone()


        if not row:

            return None


        if is_low_quality_legacy_ad_promo_copy(row[1]):

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE ad_promo_copy_variants
                    SET is_active=FALSE
                    WHERE id=%s

                """, (row[0],))

            log_event(
                "ad_promo_legacy_copy_variant_disabled",
                category="marketing",
                severity="info",
                scope="group",
                message="Variante legacy de promoción automática desactivada.",
                metadata={
                    "campaign_id": campaign_id,
                    "variant_id": row[0]
                }
            )
            continue


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE ad_promo_copy_variants
                SET usage_count=usage_count + 1,
                    last_used_at=NOW()
                WHERE id=%s

            """, (row[0],))


        return row[1]


    return None


def save_ad_promo_copy_variant(campaign_id, text, source="ai"):

    text = sanitize_ad_promo_text(text)

    if not text:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO ad_promo_copy_variants
            (
                campaign_id,
                text,
                source
            )
            VALUES (%s, %s, %s)
            RETURNING text

        """, (
            campaign_id,
            text,
            source
        ))

        row = cur.fetchone()


    return row[0] if row else None





def build_ad_promo_ai_system_prompt():

    return (
        "Eres una experta en marketing directo, copywriting para Telegram y conversión a cliente. "
        "Escribes en español natural, persuasivo y claro, sin sonar robótica ni a anuncio barato. "
        "Tu objetivo es que la persona abra el bot para explorar comunidades, no vender solo por precio. "
        "No prometas resultados, descuentos, cifras, contenido concreto ni beneficios no confirmados. "
        "No uses lenguaje agresivo ni demasiados emojis."
    )


def build_ad_promo_ai_prompt(campaign, group_name, angle=None, instruction=None):

    return (
        "Escribe un caption comercial para Telegram en español.\n\n"
        "Contexto:\n"
        "- El bot reúne comunidades gratuitas y premium.\n"
        "- Hay grupos gratuitos para empezar sin pagar cuando estén disponibles.\n"
        "- Hay opciones premium para quien busca una experiencia más completa o más exclusiva.\n"
        "- El bot sirve para descubrir comunidades, comparar opciones y gestionar accesos.\n"
        "- El objetivo es que el usuario abra el bot y explore antes de decidir.\n\n"
        "Instrucciones de copywriting:\n"
        "- Hook inicial fuerte.\n"
        "- 2 a 4 líneas de valor.\n"
        "- Puedes usar bullets cortos, pero no siempre.\n"
        "- CTA claro hacia abrir el bot.\n"
        "- Ideal entre 350 y 650 caracteres. Máximo 900.\n"
        "- Usa el precio solo como refuerzo si aporta valor, no como argumento principal.\n"
        "- No repitas siempre la misma estructura.\n"
        "- Alterna entre descubrimiento, gratis primero, premium/exclusividad, comodidad, comunidad y conversión suave.\n"
        "- No uses siempre los mismos emojis ni frases como “promo activa esta semana”.\n"
        "- No incluyas enlaces; el enlace se añadirá después.\n"
        "- No menciones infraestructura, APIs, Codex, GitHub, Railway ni procesos internos.\n\n"
        "Ejemplos de estilo:\n"
        "🚀 Descubre nuevas comunidades desde un solo bot\n\n"
        "Puedes encontrar grupos gratuitos para empezar y comunidades premium para quienes buscan una experiencia más cuidada.\n\n"
        "🎁 Grupos gratuitos\n⭐ Opciones premium\n🤖 Todo gestionado desde el bot\n\n"
        "Abre el bot y revisa las comunidades activas.\n\n"
        "👀 ¿Buscas comunidades privadas, gratuitas o premium?\n\n"
        "Nuestro bot reúne diferentes grupos para que puedas descubrirlos desde un solo lugar. Algunos son gratuitos para empezar sin compromiso; otros son premium para quienes quieren una experiencia más completa.\n\n"
        "Abre el bot y mira qué comunidades están disponibles.\n\n"
        "Datos de esta campaña:\n"
        f"- Comunidad: {group_name}.\n"
        f"- Ángulo elegido: {angle or 'variado'}.\n"
        f"- Guía del ángulo: {instruction or 'Cambia el enfoque para no repetir patrones'}.\n"
        f"- Oferta configurada: {campaign.get('offer_text') or '-'}.\n"
        f"- Precio configurado: {campaign.get('price_text') or '-'}.\n"
        f"- Tono: {campaign.get('tone') or 'conversion'}."
    )










def maybe_generate_ad_promo_ai_copy(campaign):

    if not campaign.get("ai_copy_enabled") or not is_ai_enabled():

        return None


    group = fetch_group_basic_info(campaign.get("paid_group_id"))
    group_name = group[1] if group else f"Comunidad {campaign.get('paid_group_id')}"
    angle_index = int(time.time()) % len(AD_PROMO_CAPTION_ANGLES)
    angle, instruction = AD_PROMO_CAPTION_ANGLES[angle_index]
    prompt = build_ad_promo_ai_prompt(
        campaign,
        group_name,
        angle=angle,
        instruction=instruction
    )
    ok, answer = generate_ai_response(
        prompt,
        system_prompt=build_ad_promo_ai_system_prompt()
    )


    if not ok or not answer:

        return None


    text = save_ad_promo_copy_variant(
        campaign.get("id"),
        answer,
        source="ai"
    )

    if text:

        log_event(
            "ad_promo_ai_copy_generated",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            message="Copy IA generado para campaña promocional.",
            metadata={"campaign_id": campaign.get("id")}
        )


    return text


async def build_ad_promo_caption(context, campaign):

    bot_username = None

    try:

        bot_user = await context.bot.get_me()
        bot_username = bot_user.username

    except Exception:

        bot_username = None


    copy_text = fetch_ad_promo_copy_variant(campaign.get("id"))

    if not copy_text:

        copy_text = maybe_generate_ad_promo_ai_copy(campaign)

    if not copy_text:

        copy_text = campaign.get("default_caption") or build_local_ad_promo_copy(campaign)
        save_ad_promo_copy_variant(
            campaign.get("id"),
            copy_text,
            source="template"
        )


    parts = [sanitize_ad_promo_text(copy_text)]

    for field in ("price_text", "offer_text", "cta_text"):

        if campaign.get(field):

            extra_text = format_ad_promo_price_text(campaign.get(field)) if field == "price_text" else sanitize_ad_promo_text(campaign.get(field))

            if should_append_ad_promo_extra_field(field, extra_text, copy_text):

                parts.append(extra_text)


    parts.append(f"👉 {build_ad_promo_bot_link(campaign, bot_username)}")

    return "\n\n".join(part for part in parts if part)[:1024]


AD_PROMO_WATERMARK_MODES = {"none", "caption", "video"}


def normalize_ad_promo_watermark_mode(mode):

    mode = (mode or "caption").strip().lower()

    return mode if mode in AD_PROMO_WATERMARK_MODES else "caption"


def normalize_ad_promo_watermark_position(position):

    position = (position or "bottom_right").strip().lower()

    return position if position in AD_PROMO_WATERMARK_POSITIONS else "bottom_right"


def parse_ad_promo_watermark_opacity(value):

    text = str(value or "").strip().replace("%", "")

    try:

        number = float(text.replace(",", "."))

    except Exception:

        return None


    if 10 <= number <= 100:

        number = number / 100


    if 0.1 <= number <= 1.0:

        return round(number, 2)


    return None


def resolve_ad_promo_watermark_label(campaign, bot_username=None):

    text = sanitize_ad_promo_text(campaign.get("watermark_text") or "")

    if text:

        return text[:40]


    if bot_username:

        return f"@{bot_username}"[:40]


    return "Ver acceso en el bot"


def append_ad_promo_caption_watermark(caption, watermark_text):

    watermark_text = sanitize_ad_promo_text(watermark_text)[:40]

    if not watermark_text:

        return caption


    final_caption = f"{caption}\n\n💧 {watermark_text}" if caption else f"💧 {watermark_text}"

    return final_caption[:1024]


def is_ffmpeg_available():

    return bool(shutil.which("ffmpeg"))


def escape_ffmpeg_drawtext_text(text):

    return (
        sanitize_ad_promo_text(text)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", " ")
    )[:40]


def build_watermark_filter(text, position, opacity):

    safe_text = escape_ffmpeg_drawtext_text(text)
    position = normalize_ad_promo_watermark_position(position)

    try:

        opacity = float(opacity or 0.65)

    except Exception:

        opacity = 0.65


    opacity = min(max(opacity, 0.1), 1.0)
    coordinates = {
        "bottom_right": "x=w-tw-24:y=h-th-24",
        "bottom_left": "x=24:y=h-th-24",
        "top_right": "x=w-tw-24:y=24",
        "top_left": "x=24:y=24",
        "center": "x=(w-tw)/2:y=(h-th)/2"
    }

    return (
        "drawtext="
        f"text='{safe_text}':"
        "fontcolor=white@"
        f"{opacity}:"
        "fontsize=44:"
        "box=1:"
        "boxcolor=black@0.55:"
        "boxborderw=14:"
        "shadowcolor=black@0.9:"
        "shadowx=2:"
        "shadowy=2:"
        f"{coordinates[position]}"
    )


def apply_video_watermark(input_path, output_path, text, position, opacity):

    command = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        build_watermark_filter(text, position, opacity),
        "-codec:a",
        "copy",
        "-movflags",
        "+faststart",
        output_path
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.returncode != 0:

        raise RuntimeError((result.stderr or result.stdout or "ffmpeg failed")[:500])


async def prepare_ad_promo_watermarked_video(context, campaign, media, caption):

    mode = normalize_ad_promo_watermark_mode(campaign.get("watermark_mode"))

    if mode == "none":

        return {
            "video": media.get("telegram_file_id"),
            "caption": caption,
            "temp_paths": [],
            "watermark_status": {
                "status": "none",
                "message": "Marca de agua desactivada."
            }
        }


    bot_username = None

    try:

        bot_user = await context.bot.get_me()
        bot_username = bot_user.username

    except Exception:

        bot_username = None


    watermark_text = resolve_ad_promo_watermark_label(campaign, bot_username=bot_username)
    caption_with_watermark = append_ad_promo_caption_watermark(caption, watermark_text)

    if mode == "caption":

        return {
            "video": media.get("telegram_file_id"),
            "caption": caption_with_watermark,
            "temp_paths": [],
            "watermark_status": {
                "status": "caption",
                "message": "Marca de agua añadida al caption."
            }
        }


    max_size = int(campaign.get("watermark_max_file_size_mb") or 50) * 1024 * 1024
    max_duration = int(campaign.get("watermark_max_duration_seconds") or 180)

    if (media.get("file_size") and int(media.get("file_size") or 0) > max_size) or (
        media.get("duration") and int(media.get("duration") or 0) > max_duration
    ):

        log_event(
            "ad_promo_watermark_skipped_limits",
            category="marketing",
            severity="warning",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            message="Marca de agua de vídeo omitida por límites configurados.",
            metadata={
                "campaign_id": campaign.get("id"),
                "media_id": media.get("id"),
                "file_size": media.get("file_size"),
                "duration": media.get("duration"),
                "max_size_mb": campaign.get("watermark_max_file_size_mb"),
                "max_duration_seconds": max_duration,
                "max_size_bytes": max_size
            }
        )

        return {
            "video": media.get("telegram_file_id"),
            "caption": caption_with_watermark,
            "temp_paths": [],
            "watermark_status": {
                "status": "skipped_limits",
                "message": (
                    "Marca incrustada omitida por límites. "
                    f"Tamaño: {media.get('file_size') or '-'} bytes / límite: {max_size} bytes. "
                    f"Duración: {media.get('duration') or '-'} s / límite: {max_duration} s. "
                    "Se usó fallback en caption."
                )
            }
        }


    if not is_ffmpeg_available():

        log_event(
            "ad_promo_watermark_unavailable",
            category="marketing",
            severity="warning",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            message="ffmpeg no disponible para incrustar marca de agua.",
            metadata={"campaign_id": campaign.get("id"), "media_id": media.get("id"), "watermark_mode": mode}
        )

        return {
            "video": media.get("telegram_file_id"),
            "caption": caption_with_watermark,
            "temp_paths": [],
            "watermark_status": {
                "status": "unavailable",
                "message": "ffmpeg no está disponible. Se usó fallback en caption."
            }
        }


    temp_paths = []

    try:

        token = secrets.token_hex(8)
        input_path = os.path.join(tempfile.gettempdir(), f"ad_promo_{token}_in.mp4")
        output_path = os.path.join(tempfile.gettempdir(), f"ad_promo_{token}_wm.mp4")
        temp_paths.extend([input_path, output_path])
        telegram_file = await context.bot.get_file(media.get("telegram_file_id"))
        await telegram_file.download_to_drive(input_path)
        apply_video_watermark(
            input_path,
            output_path,
            watermark_text,
            campaign.get("watermark_position"),
            campaign.get("watermark_opacity")
        )
        output_size = os.path.getsize(output_path) if os.path.exists(output_path) else None

        if not output_size:

            raise RuntimeError("ffmpeg no generó un archivo de salida válido.")


        log_event(
            "ad_promo_watermark_applied",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            message="Marca de agua incrustada en vídeo promocional.",
            metadata={
                "campaign_id": campaign.get("id"),
                "media_id": media.get("id"),
                "output_file_size": output_size,
                "watermark_opacity": campaign.get("watermark_opacity"),
                "watermark_position": campaign.get("watermark_position")
            }
        )

        return {
            "video": output_path,
            "caption": caption,
            "temp_paths": temp_paths,
            "watermark_status": {
                "status": "embedded",
                "message": f"Marca de agua incrustada en vídeo. Tamaño salida: {output_size or '-'} bytes."
            }
        }

    except Exception as e:

        log_event(
            "ad_promo_watermark_failed",
            category="marketing",
            severity="warning",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            message="No se pudo incrustar marca de agua en vídeo promocional.",
            metadata={
                "campaign_id": campaign.get("id"),
                "media_id": media.get("id"),
                "error": str(e)[:500]
            }
        )

        for path in temp_paths:

            if path and os.path.exists(path):

                try:

                    os.remove(path)

                except Exception:

                    pass


        return {
            "video": media.get("telegram_file_id"),
            "caption": caption_with_watermark,
            "temp_paths": [],
            "watermark_status": {
                "status": "failed",
                "message": f"Falló el procesamiento ffmpeg. Se usó fallback en caption. Error: {str(e)[:300]}"
            }
        }


async def delete_old_ad_promo_posts(context, campaign):

    if not campaign.get("delete_old_posts"):

        return {"deleted": 0, "failed": 0}


    max_posts = int(campaign.get("max_posts") or 50)
    deleted = 0
    failed = 0

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   promo_group_telegram_id,
                   message_id
            FROM ad_promo_sent_posts
            WHERE campaign_id=%s
            AND deleted_at IS NULL
            ORDER BY sent_at DESC
            OFFSET %s

        """, (
            campaign.get("id"),
            max_posts
        ))

        rows = cur.fetchall()


    for row_id, chat_id, message_id in rows:

        try:

            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id
            )

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE ad_promo_sent_posts
                    SET deleted_at=NOW()
                    WHERE id=%s

                """, (row_id,))

            deleted += 1
            log_event(
                "ad_promo_post_deleted",
                category="marketing",
                severity="info",
                scope="group",
                group_id=campaign.get("paid_group_id"),
                message="Post promocional antiguo eliminado.",
                metadata={"campaign_id": campaign.get("id"), "message_id": message_id}
            )

        except Exception as e:

            failed += 1

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE ad_promo_sent_posts
                    SET delete_error=%s
                    WHERE id=%s

                """, (
                    str(e)[:500],
                    row_id
                ))

            log_event(
                "ad_promo_delete_failed",
                category="marketing",
                severity="warning",
                scope="group",
                group_id=campaign.get("paid_group_id"),
                message="No se pudo borrar un post promocional antiguo.",
                metadata={"campaign_id": campaign.get("id"), "message_id": message_id, "error": str(e)[:300]}
            )


    return {"deleted": deleted, "failed": failed}


async def send_ad_promo_video_message(context, chat_id, video_payload, caption):

    if isinstance(video_payload, str) and os.path.exists(video_payload):

        with open(video_payload, "rb") as video_file:

            return await context.bot.send_video(
                chat_id=chat_id,
                video=video_file,
                caption=caption
            )


    return await context.bot.send_video(
        chat_id=chat_id,
        video=video_payload,
        caption=caption
    )


async def send_ad_promo_campaign_batch(context, campaign, test=False):

    media_counts = get_ad_promo_media_counts(campaign.get("id"))
    media_rows = select_ad_promo_media_for_batch(campaign, test=test)

    if not media_rows:

        reason = "no_active_media" if media_counts.get("total") else "no_media"
        message = (
            "Hay vídeos guardados, pero ninguno está activo."
            if reason == "no_active_media"
            else "No hay vídeos activos capturados para esta campaña."
        )

        if test:

            log_event(
                "ad_promo_test_no_media",
                category="marketing",
                severity="warning",
                scope="group",
                group_id=campaign.get("paid_group_id"),
                message=message,
                metadata={
                    "campaign_id": campaign.get("id"),
                    "reason": reason,
                    "total_media": media_counts.get("total"),
                    "active_media": media_counts.get("active"),
                    "inactive_media": media_counts.get("inactive")
                }
            )


        return {
            "ok": False,
            "sent": 0,
            "failed": 0,
            "reason": reason,
            "message": message,
            "media_counts": media_counts
        }


    batch_id = secrets.token_hex(8)
    sent = 0
    failed = 0
    last_error = None
    migration_notice = None
    watermark_statuses = []

    for media in media_rows:

        caption = await build_ad_promo_caption(context, campaign)
        prepared_video = None
        target_chat_id = campaign.get("promo_group_telegram_id")

        try:

            prepared_video = await prepare_ad_promo_watermarked_video(
                context,
                campaign,
                media,
                caption
            )
            if prepared_video.get("watermark_status"):

                watermark_statuses.append(prepared_video.get("watermark_status"))


            video_payload = prepared_video.get("video")

            try:

                message = await send_ad_promo_video_message(
                    context,
                    target_chat_id,
                    video_payload,
                    prepared_video.get("caption")
                )

            except Exception as send_error:

                migrated_chat_id = extract_ad_promo_migrated_chat_id(send_error)

                if not migrated_chat_id:

                    raise


                old_chat_id = target_chat_id
                campaign = update_ad_promo_campaign_promo_chat_id(
                    campaign.get("id"),
                    migrated_chat_id
                ) or campaign
                campaign["promo_group_telegram_id"] = migrated_chat_id
                target_chat_id = migrated_chat_id
                migration_notice = (
                    "El grupo fue migrado a supergrupo. "
                    f"Nuevo chat ID detectado: {migrated_chat_id}."
                )
                log_event(
                    "ad_promo_chat_migrated",
                    category="marketing",
                    severity="info",
                    scope="group",
                    group_id=campaign.get("paid_group_id"),
                    message="Chat destino de promoción migrado a supergrupo.",
                    metadata={
                        "campaign_id": campaign.get("id"),
                        "old_chat_id": old_chat_id,
                        "new_chat_id": migrated_chat_id,
                        "field": "promo_group_telegram_id"
                    }
                )

                try:

                    message = await send_ad_promo_video_message(
                        context,
                        migrated_chat_id,
                        video_payload,
                        prepared_video.get("caption")
                    )

                except Exception as retry_error:

                    raise RuntimeError(
                        f"Reintento fallido: {retry_error}"
                    ) from retry_error

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO ad_promo_sent_posts
                    (
                        campaign_id,
                        promo_group_telegram_id,
                        message_id,
                        media_id,
                        batch_id,
                        caption_text
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)

                """, (
                    campaign.get("id"),
                    target_chat_id,
                    message.message_id,
                    media.get("id"),
                    batch_id,
                    prepared_video.get("caption")
                ))

                cur.execute("""

                    UPDATE ad_promo_media
                    SET usage_count=usage_count + 1,
                        last_sent_at=NOW()
                    WHERE id=%s

                """, (media.get("id"),))

            sent += 1

        except Exception as e:

            failed += 1
            last_error = str(e)[:500]
            print(
                "Ad promo: fallo enviando vídeo promocional "
                f"(campaña {campaign.get('id')}, media {media.get('id')}): {e}"
            )
            log_event(
                "ad_promo_send_failed",
                category="marketing",
                severity="warning",
                scope="group",
                group_id=campaign.get("paid_group_id"),
                message="No se pudo enviar un vídeo promocional.",
                metadata={"campaign_id": campaign.get("id"), "media_id": media.get("id"), "error": str(e)[:300], "test": test}
            )


        finally:

            for path in (prepared_video or {}).get("temp_paths", []):

                if path and os.path.exists(path):

                    try:

                        os.remove(path)

                    except Exception:

                        pass


    if not test:

        update_ad_promo_campaign(
            campaign.get("id"),
            {
                "last_run_at": datetime.now(),
                "next_run_at": datetime.now() + timedelta(minutes=max(int(campaign.get("interval_minutes") or 60), 5))
            }
        )


    delete_summary = await delete_old_ad_promo_posts(context, campaign)
    ok = sent > 0
    reason = None
    message = "Prueba enviada correctamente." if test and ok else "Tanda promocional enviada."

    if not ok:

        reason = "send_failed" if failed else "nothing_sent"
        message = (
            "La prueba no se pudo enviar."
            if test and failed
            else "No se envió ningún vídeo."
        )

        if test:

            log_event(
                "ad_promo_test_send_failed" if failed else "ad_promo_test_nothing_sent",
                category="marketing",
                severity="warning",
                scope="group",
                group_id=campaign.get("paid_group_id"),
                message=message,
                metadata={
                    "campaign_id": campaign.get("id"),
                    "batch_id": batch_id,
                    "sent": sent,
                    "failed": failed,
                    "reason": reason,
                    "error": last_error,
                    "migration_notice": migration_notice,
                    "watermark_statuses": watermark_statuses
                }
            )

    elif test:

        log_event(
            "ad_promo_test_sent",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            message="Prueba de campaña promocional enviada.",
            metadata={
                "campaign_id": campaign.get("id"),
                "batch_id": batch_id,
                "sent": sent,
                "failed": failed,
                "migration_notice": migration_notice,
                "watermark_statuses": watermark_statuses
            }
        )

    if sent:

        log_event(
            "ad_promo_batch_sent",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            message="Tanda promocional enviada.",
            metadata={
                "campaign_id": campaign.get("id"),
                "batch_id": batch_id,
                "sent": sent,
                "failed": failed,
                "test": test,
                "deleted": delete_summary.get("deleted")
            }
        )


    return {
        "ok": ok,
        "sent": sent,
        "failed": failed,
        "reason": reason,
        "message": message,
        "error": last_error,
        "migration_notice": migration_notice,
        "watermark_statuses": watermark_statuses,
        "media_counts": media_counts,
        **delete_summary
    }


async def process_due_ad_promo_campaigns(context):

    summary = {"campaigns": 0, "sent": 0, "failed": 0, "skipped": 0}

    for campaign in fetch_due_ad_promo_campaigns():

        summary["campaigns"] += 1
        result = await send_ad_promo_campaign_batch(context, campaign)

        if result.get("reason") in ("no_media", "no_active_media"):

            summary["skipped"] += 1
            update_ad_promo_campaign(
                campaign.get("id"),
                {
                    "next_run_at": datetime.now() + timedelta(minutes=max(int(campaign.get("interval_minutes") or 60), 5))
                }
            )
            continue


        sent_now = int(result.get("sent", 0) or 0)
        failed_now = int(result.get("failed", 0) or 0)

        summary["sent"] += sent_now
        summary["failed"] += failed_now


        # =========================
        # AUTO-PAUSA TRAS FALLOS REPETIDOS
        # =========================
        # Sin esto, una campaña cuyo destino esté roto (el bot ya no es admin,
        # canal borrado, etc.) reintenta cada pocos minutos indefinidamente y
        # llena el monitor de errores idénticos. Ahora se pausa sola y se avisa
        # una única vez con el motivo real.

        if failed_now and not sent_now:

            streak = int(campaign.get("consecutive_failures") or 0) + 1
            last_error_text = str(result.get("error") or "")[:500]

            updates = {
                "consecutive_failures": streak,
                "last_error_text": last_error_text
            }

            if streak >= AD_PROMO_MAX_CONSECUTIVE_FAILURES:

                updates["is_paused"] = True
                updates["paused_reason"] = (
                    f"Pausada automáticamente tras {streak} tandas fallidas. "
                    f"Último error: {last_error_text}"
                )

            update_ad_promo_campaign(campaign.get("id"), updates)

            if streak >= AD_PROMO_MAX_CONSECUTIVE_FAILURES:

                log_event(
                    "ad_promo_campaign_auto_paused",
                    category="marketing",
                    severity="error",
                    scope="group",
                    group_id=campaign.get("paid_group_id"),
                    message="Campaña de promoción pausada automáticamente por fallos repetidos.",
                    metadata={
                        "campaign_id": campaign.get("id"),
                        "consecutive_failures": streak,
                        "error": last_error_text
                    }
                )

                try:

                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=(
                            "⏸ Promoción automática pausada\n\n"
                            f"Campaña #{campaign.get('id')} se ha pausado sola tras "
                            f"{streak} tandas fallidas seguidas.\n\n"
                            f"Motivo: {last_error_text or 'desconocido'}\n\n"
                            "Revisa que el bot siga siendo administrador del canal "
                            "de destino y reactívala cuando esté resuelto."
                        )
                    )

                except Exception as notify_error:

                    print(
                        "Ad promo: no se pudo avisar de la pausa automática:",
                        notify_error
                    )

        elif sent_now:

            if int(campaign.get("consecutive_failures") or 0):

                update_ad_promo_campaign(
                    campaign.get("id"),
                    {"consecutive_failures": 0}
                )


    return summary


def build_ad_promo_daily_review_text(campaign):

    group = fetch_group_basic_info(campaign.get("paid_group_id"))
    group_name = group[1] if group else f"Grupo {campaign.get('paid_group_id')}"
    media_summary = count_ad_promo_media(campaign.get("id"))

    return (
        "📣 Revisión diaria de promoción\n\n"
        f"Campaña: #{campaign.get('id')} · {group_name}\n"
        f"Oferta actual: {campaign.get('offer_text') or '-'}\n"
        f"Precio actual: {campaign.get('price_text') or '-'}\n"
        f"Frecuencia: {campaign.get('interval_minutes') or '-'} min\n"
        f"Vídeos por tanda: {campaign.get('batch_size') or '-'}\n"
        f"Cupo máximo: {campaign.get('max_posts') or '-'}\n"
        f"Vídeos capturados: {media_summary.get('active')}\n\n"
        "¿Quieres cambiar algo?"
    )


def build_ad_promo_daily_review_keyboard(campaign_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Cambiar oferta", callback_data=f"admin_ad_promo_edit_offer_{campaign_id}")],
        [InlineKeyboardButton("💶 Cambiar precio", callback_data=f"admin_ad_promo_edit_price_{campaign_id}")],
        [InlineKeyboardButton("⏱ Cambiar frecuencia", callback_data=f"admin_ad_promo_edit_frequency_{campaign_id}")],
        [InlineKeyboardButton("🎬 Cambiar cantidad", callback_data=f"admin_ad_promo_edit_batch_{campaign_id}")],
        [InlineKeyboardButton("🧹 Cambiar cupo", callback_data=f"admin_ad_promo_edit_maxposts_{campaign_id}")],
        [InlineKeyboardButton("✅ Mantener igual", callback_data=f"admin_ad_promo_keep_offer_{campaign_id}")]
    ])


async def process_ad_promo_daily_reviews(context):

    sent = 0

    for campaign in fetch_due_ad_promo_daily_reviews():

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=build_ad_promo_daily_review_text(campaign),
                reply_markup=build_ad_promo_daily_review_keyboard(campaign.get("id"))
            )

            update_ad_promo_campaign(
                campaign.get("id"),
                {
                    "last_offer_check_at": datetime.now(),
                    "next_offer_check_at": datetime.now() + timedelta(hours=24)
                }
            )
            sent += 1

            log_event(
                "ad_promo_daily_review_sent",
                category="marketing",
                severity="info",
                scope="group",
                group_id=campaign.get("paid_group_id"),
                message="Revisión diaria de promoción enviada al superadmin.",
                metadata={"campaign_id": campaign.get("id")}
            )

        except Exception as e:

            print("Error enviando revisión diaria promo:", e)


    return {"sent": sent}










def build_ad_promo_campaign_detail_text(campaign):

    group = fetch_group_basic_info(campaign.get("paid_group_id"))
    group_name = group[1] if group else f"Grupo {campaign.get('paid_group_id')}"
    media_summary = count_ad_promo_media(campaign.get("id"))

    return (
        f"📣 Campaña #{campaign.get('id')}\n\n"
        f"Comunidad de pago: {group_name} ({campaign.get('paid_group_id')})\n"
        f"Fuente: {campaign.get('source_chat_title') or campaign.get('source_chat_id')}\n"
        f"Destino promo: {campaign.get('promo_group_title') or campaign.get('promo_group_telegram_id')}\n"
        f"Estado: {'pausada' if campaign.get('is_paused') else 'activa' if campaign.get('is_active') else 'inactiva'}\n"
        f"Captura: {'ON' if campaign.get('auto_capture_enabled') else 'OFF'}\n"
        f"Random: {'ON' if campaign.get('randomize_media') else 'OFF'}\n"
        f"IA textos: {'ON' if campaign.get('ai_copy_enabled') else 'OFF'}\n"
        f"Marca de agua: {normalize_ad_promo_watermark_mode(campaign.get('watermark_mode'))}\n"
        f"Vídeos activos: {media_summary.get('active')}\n"
        f"Última captura: {format_commercial_datetime(media_summary.get('last_capture')) if media_summary.get('last_capture') else '-'}\n"
        f"Frecuencia: {campaign.get('interval_minutes')} min\n"
        f"Vídeos por tanda: {campaign.get('batch_size')}\n"
        f"Cupo máximo: {campaign.get('max_posts')}\n"
        f"Borrado rotativo: {'ON' if campaign.get('delete_old_posts') else 'OFF'}\n\n"
        f"Precio: {campaign.get('price_text') or '-'}\n"
        f"Oferta: {campaign.get('offer_text') or '-'}\n"
        f"CTA: {campaign.get('cta_text') or '-'}\n"
        f"Bot link: {campaign.get('bot_link') or 'auto'}"
        + (
            f"\n\n⚠️ Último error: {campaign.get('last_error_text')}"
            if campaign.get("last_error_text") else ""
        )
        + (
            f"\n⏸ Motivo de la pausa: {campaign.get('paused_reason')}"
            if campaign.get("paused_reason") else ""
        )
    )


def build_ad_promo_campaign_detail_keyboard(campaign):

    campaign_id = campaign.get("id")
    pause_label = "▶️ Reanudar" if campaign.get("is_paused") else "⏸ Pausar"
    pause_callback = f"admin_ad_promo_resume_{campaign_id}" if campaign.get("is_paused") else f"admin_ad_promo_pause_{campaign_id}"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Diagnóstico", callback_data=f"admin_ad_promo_diagnostics_{campaign_id}")],
        [InlineKeyboardButton("📚 Biblioteca de vídeos", callback_data=f"admin_ad_promo_library_{campaign_id}")],
        [InlineKeyboardButton("📝 Generar captions", callback_data=f"admin_ad_promo_generate_captions_{campaign_id}")],
        [InlineKeyboardButton("🧠 Regenerar textos IA", callback_data=f"ad_promo_regenerate_copy_{campaign_id}")],
        [InlineKeyboardButton("📋 Ver captions", callback_data=f"admin_ad_promo_copy_variants_{campaign_id}")],
        [InlineKeyboardButton("🧪 Enviar prueba", callback_data=f"admin_ad_promo_test_{campaign_id}")],
        [InlineKeyboardButton("🎲 Optimizar rotación", callback_data=f"admin_ad_promo_optimize_rotation_{campaign_id}")],
        [InlineKeyboardButton("🎲 Random ON/OFF", callback_data=f"admin_ad_promo_random_{campaign_id}")],
        [InlineKeyboardButton("🤖 IA textos ON/OFF", callback_data=f"admin_ad_promo_ai_{campaign_id}")],
        [InlineKeyboardButton("🎥 Captura ON/OFF", callback_data=f"admin_ad_promo_capture_{campaign_id}")],
        [InlineKeyboardButton("💧 Marca de agua", callback_data=f"admin_ad_promo_watermark_{campaign_id}")],
        [InlineKeyboardButton("📝 Editar oferta", callback_data=f"admin_ad_promo_edit_offer_{campaign_id}")],
        [InlineKeyboardButton("💶 Editar precio", callback_data=f"admin_ad_promo_edit_price_{campaign_id}")],
        [InlineKeyboardButton("📣 Editar CTA", callback_data=f"admin_ad_promo_edit_cta_{campaign_id}")],
        [InlineKeyboardButton("⏱ Frecuencia", callback_data=f"admin_ad_promo_edit_frequency_{campaign_id}")],
        [InlineKeyboardButton("🎬 Vídeos por tanda", callback_data=f"admin_ad_promo_edit_batch_{campaign_id}")],
        [InlineKeyboardButton("🧹 Cupo/borrado", callback_data=f"admin_ad_promo_edit_maxposts_{campaign_id}")],
        [InlineKeyboardButton(pause_label, callback_data=pause_callback)],
        [InlineKeyboardButton("🗑 Borrar antiguos", callback_data=f"admin_ad_promo_delete_old_{campaign_id}")],
        [InlineKeyboardButton("🗑 Eliminar campaña", callback_data=f"admin_ad_promo_delete_campaign_{campaign_id}")],
        [InlineKeyboardButton("⬅️ Campañas", callback_data="admin_ad_promo_campaigns")]
    ])








def build_ad_promo_watermark_keyboard(campaign):

    campaign_id = campaign.get("id")

    keyboard = [
        [
            InlineKeyboardButton("🚫 Sin marca", callback_data=f"admin_ad_promo_watermark_mode_{campaign_id}_none"),
            InlineKeyboardButton("📝 Marca en caption", callback_data=f"admin_ad_promo_watermark_mode_{campaign_id}_caption")
        ],
        [InlineKeyboardButton("🎬 Marca incrustada en vídeo", callback_data=f"admin_ad_promo_watermark_mode_{campaign_id}_video")],
        [InlineKeyboardButton("✏️ Cambiar texto", callback_data=f"admin_ad_promo_watermark_text_{campaign_id}")],
        [InlineKeyboardButton("🌫 Cambiar opacidad", callback_data=f"admin_ad_promo_watermark_opacity_{campaign_id}")]
    ]

    positions = [
        ("bottom_right", "↘️ Abajo derecha"),
        ("bottom_left", "↙️ Abajo izquierda"),
        ("top_right", "↗️ Arriba derecha"),
        ("top_left", "↖️ Arriba izquierda"),
        ("center", "⏺ Centro")
    ]

    for position, label in positions:

        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=f"admin_ad_promo_watermark_position_{campaign_id}_{position}"
        )])


    keyboard.extend([
        [InlineKeyboardButton("⚙️ Cambiar límites", callback_data=f"admin_ad_promo_watermark_limits_{campaign_id}")],
        [InlineKeyboardButton("🧪 Enviar prueba con marca", callback_data=f"admin_ad_promo_watermark_test_{campaign_id}")],
        [InlineKeyboardButton("🔙 Volver campaña", callback_data=f"admin_ad_promo_campaign_{campaign_id}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)












































def build_ad_promo_promo_choice_text():

    return (
        "Ahora elige dónde se publicará la publicidad gratuita.\n\n"
        "Este será el grupo/canal gratuito donde el bot subirá vídeos promocionales, textos, ofertas y el enlace al bot.\n\n"
        "Elige una opción:"
    )


def build_ad_promo_promo_choice_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Elegir grupo/canal destino desde lista", callback_data="admin_ad_promo_promo_picker")],
        [InlineKeyboardButton("🔁 Reenviar mensaje del grupo/canal destino", callback_data="admin_ad_promo_retry_promo_forward")],
        [InlineKeyboardButton("✍️ Introducir ID manualmente", callback_data="admin_ad_promo_manual_promo")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_ad_promo_cancel")]
    ])


def build_ad_promo_forward_keyboard(manual_callback, back_callback="admin_ad_promo_create"):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Introducir ID manualmente", callback_data=manual_callback)],
        [InlineKeyboardButton("🔙 Volver", callback_data=back_callback)],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_ad_promo")]
    ])


def build_ad_promo_forward_fallback_keyboard(kind):

    if kind == "source":

        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Seleccionar grupo/canal fuente", callback_data="admin_ad_promo_source_picker")],
            [InlineKeyboardButton("✍️ Introducir ID manualmente", callback_data="admin_ad_promo_manual_source")],
            [InlineKeyboardButton("🔁 Reintentar reenvío", callback_data="admin_ad_promo_retry_source_forward")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="admin_ad_promo_cancel")]
        ])


    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Seleccionar grupo/canal destino", callback_data="admin_ad_promo_promo_picker")],
        [InlineKeyboardButton("✍️ Introducir ID manualmente", callback_data="admin_ad_promo_manual_promo")],
        [InlineKeyboardButton("🔁 Reintentar reenvío", callback_data="admin_ad_promo_retry_promo_forward")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_ad_promo_cancel")]
    ])










def save_ad_promo_wizard_chat(wizard, kind, chat_id, title=None, chat_type=None):

    wizard.setdefault("data", {})

    if kind == "source":

        wizard["data"]["source_chat_id"] = chat_id
        wizard["data"]["source_chat_title"] = title
        wizard["data"]["source_chat_type"] = chat_type
        wizard["step"] = "promo_forward"
        return wizard


    wizard["data"]["promo_group_telegram_id"] = chat_id
    wizard["data"]["promo_group_title"] = title
    wizard["data"]["promo_group_type"] = chat_type or "group"
    wizard.pop("step", None)
    wizard["step_index"] = 0

    return wizard


def extract_forwarded_chat_from_message(message):

    if not message:

        return None


    forward_origin = getattr(message, "forward_origin", None)
    forward_chat = None


    if forward_origin:

        forward_chat = (
            getattr(forward_origin, "chat", None)
            or getattr(forward_origin, "sender_chat", None)
        )


    if not forward_chat:

        forward_chat = getattr(message, "forward_from_chat", None)


    if not forward_chat:

        return None


    return {
        "chat_id": getattr(forward_chat, "id", None),
        "title": getattr(forward_chat, "title", None) or getattr(forward_chat, "username", None),
        "type": getattr(forward_chat, "type", None)
    }


def parse_ad_promo_int(value, minimum=None):

    text = str(value or "").strip()

    if text.startswith("-"):

        digits = text[1:]

    else:

        digits = text


    if not digits.isdigit():

        return None


    number = int(text)

    if minimum is not None and number < minimum:

        return None


    return number






async def resolve_ad_promo_chat_details(context, chat_id):

    try:

        chat = await context.bot.get_chat(chat_id)

        return {
            "title": getattr(chat, "title", None) or getattr(chat, "username", None),
            "type": getattr(chat, "type", None) or "group"
        }

    except Exception:

        return {"title": None, "type": None}


async def receive_ad_promo_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id if update.effective_user else None

    if not is_super_admin(user_id):

        context.user_data.pop("ad_promo_wizard", None)
        context.user_data.pop("ad_promo_edit", None)
        return


    text = (update.message.text or "").strip() if update.message else ""

    if context.user_data.get("ad_promo_edit"):

        edit_state = context.user_data.get("ad_promo_edit") or {}
        campaign_id = edit_state.get("campaign_id")
        field = edit_state.get("field")
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            context.user_data.pop("ad_promo_edit", None)
            await update.message.reply_text("❌ Campaña no encontrada.")
            return


        numeric_fields = {
            "interval_minutes": 5,
            "batch_size": 1,
            "max_posts": 1,
            "watermark_max_file_size_mb": 1,
            "watermark_max_duration_seconds": 1
        }

        if field == "watermark_limits":

            parts = text.replace(",", " ").split()

            if len(parts) < 2:

                await update.message.reply_text("❌ Envía dos números: tamaño_mb duración_segundos. Ejemplo: 50 180")
                return


            max_size_mb = parse_ad_promo_int(parts[0], minimum=1)
            max_duration = parse_ad_promo_int(parts[1], minimum=1)

            if max_size_mb is None or max_duration is None:

                await update.message.reply_text("❌ Límites no válidos. Ejemplo: 50 180")
                return


            update_ad_promo_campaign(
                campaign_id,
                {
                    "watermark_max_file_size_mb": max_size_mb,
                    "watermark_max_duration_seconds": max_duration
                },
                actor_user_id=user_id
            )
            context.user_data.pop("ad_promo_edit", None)

            await update.message.reply_text(
                "✅ Límites de marca de agua actualizados.",
                reply_markup=build_ad_promo_watermark_keyboard(fetch_ad_promo_campaign(campaign_id))
            )
            return


        if field == "watermark_opacity":

            value = parse_ad_promo_watermark_opacity(text)

            if value is None:

                await update.message.reply_text(
                    "❌ Opacidad no válida.\n\n"
                    "Envía un decimal entre 0.1 y 1.0 o un porcentaje entre 10 y 100.\n"
                    "Ejemplos: 0.75, 75, 100"
                )
                return


            update_ad_promo_campaign(
                campaign_id,
                {"watermark_opacity": value},
                actor_user_id=user_id
            )
            context.user_data.pop("ad_promo_edit", None)

            await update.message.reply_text(
                f"✅ Opacidad actualizada a {value}.",
                reply_markup=build_ad_promo_watermark_keyboard(fetch_ad_promo_campaign(campaign_id))
            )
            return


        if field in numeric_fields:

            value = parse_ad_promo_int(text, minimum=numeric_fields[field])

            if value is None:

                await update.message.reply_text("❌ Valor no válido. Envía un número válido.")
                return

        elif field == "watermark_text":

            value = sanitize_ad_promo_text(text)[:40]

        elif field == "bot_link" and text.lower() == "auto":

            value = None

        else:

            value = sanitize_ad_promo_text(text)


        update_ad_promo_campaign(
            campaign_id,
            {field: value},
            actor_user_id=user_id
        )
        context.user_data.pop("ad_promo_edit", None)

        log_event(
            "ad_promo_campaign_updated",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            actor_user_id=user_id,
            message="Campaña de promoción actualizada.",
            metadata={"campaign_id": campaign_id, "field": field}
        )

        if field == "watermark_text":

            log_event(
                "ad_promo_watermark_text_updated",
                category="marketing",
                severity="info",
                scope="group",
                group_id=campaign.get("paid_group_id"),
                actor_user_id=user_id,
                message="Texto de marca de agua actualizado.",
                metadata={"campaign_id": campaign_id}
            )

        await update.message.reply_text(
            "✅ Campaña actualizada.",
            reply_markup=build_ad_promo_watermark_keyboard(fetch_ad_promo_campaign(campaign_id))
            if field.startswith("watermark_")
            else build_ad_promo_campaign_detail_keyboard(fetch_ad_promo_campaign(campaign_id))
        )
        return


    wizard = context.user_data.get("ad_promo_wizard")

    if not wizard:

        return


    wizard_step = wizard.get("step")

    if wizard_step in ("source_forward", "promo_forward"):

        forwarded_chat = extract_forwarded_chat_from_message(update.message)

        if not forwarded_chat or not forwarded_chat.get("chat_id"):

            if wizard_step == "source_forward":

                await update.message.reply_text(
                    "No he podido detectar el origen del mensaje reenviado.\n\n"
                    "Esto puede pasar si Telegram oculta el origen del reenvío o si el mensaje se envió como texto normal.\n\n"
                    "Elige una opción:",
                    reply_markup=build_ad_promo_forward_fallback_keyboard("source")
                )

            else:

                await update.message.reply_text(
                    "No he podido detectar el grupo/canal de destino.\n\n"
                    "Esto puede pasar si Telegram oculta el origen del reenvío o si el mensaje se envió como texto normal.\n\n"
                    "Elige una opción:",
                    reply_markup=build_ad_promo_forward_fallback_keyboard("promo")
                )

            return


        try:

            chat = await context.bot.get_chat(forwarded_chat.get("chat_id"))

        except Exception:

            await update.message.reply_text(
                "No puedo acceder a ese grupo/canal. "
                "Añade el bot como administrador y vuelve a reenviar un mensaje.",
                reply_markup=build_ad_promo_forward_keyboard(
                    "admin_ad_promo_manual_source"
                    if wizard_step == "source_forward"
                    else "admin_ad_promo_manual_promo",
                    back_callback="admin_ad_promo_choose_source"
                    if wizard_step == "source_forward"
                    else "admin_ad_promo_choose_promo"
                )
            )

            return


        chat_title = getattr(chat, "title", None) or forwarded_chat.get("title")
        chat_type = getattr(chat, "type", None) or forwarded_chat.get("type")
        wizard.setdefault("data", {})

        if wizard_step == "source_forward":

            wizard = save_ad_promo_wizard_chat(
                wizard,
                "source",
                forwarded_chat.get("chat_id"),
                title=chat_title,
                chat_type=chat_type
            )
            context.user_data["ad_promo_wizard"] = wizard

            await update.message.reply_text(
                "✅ Fuente configurada.\n\n"
                f"{build_ad_promo_promo_choice_text()}",
                reply_markup=build_ad_promo_promo_choice_keyboard()
            )

            return


        wizard = save_ad_promo_wizard_chat(
            wizard,
            "promo",
            forwarded_chat.get("chat_id"),
            title=chat_title,
            chat_type=chat_type
        )
        context.user_data["ad_promo_wizard"] = wizard

        await update.message.reply_text(
            "✅ Grupo/canal gratuito configurado.\n\n"
            f"{AD_PROMO_CREATE_STEPS[0][1]}"
        )

        return


    if wizard_step in ("manual_source", "manual_promo"):

        chat_id = parse_ad_promo_int(text)

        if chat_id is None:

            await update.message.reply_text("❌ chat_id no válido. Envía el ID numérico completo.")
            return


        details = await resolve_ad_promo_chat_details(context, chat_id)

        if not details.get("title") and not details.get("type"):

            await update.message.reply_text(
                "No puedo acceder a ese grupo/canal. "
                "Añade el bot como administrador y vuelve a intentarlo."
            )

            return


        wizard.setdefault("data", {})

        if wizard_step == "manual_source":

            wizard = save_ad_promo_wizard_chat(
                wizard,
                "source",
                chat_id,
                title=details.get("title"),
                chat_type=details.get("type")
            )
            context.user_data["ad_promo_wizard"] = wizard

            await update.message.reply_text(
                "✅ Fuente configurada.\n\n"
                f"{build_ad_promo_promo_choice_text()}",
                reply_markup=build_ad_promo_promo_choice_keyboard()
            )

            return


        wizard = save_ad_promo_wizard_chat(
            wizard,
            "promo",
            chat_id,
            title=details.get("title"),
            chat_type=details.get("type")
        )
        context.user_data["ad_promo_wizard"] = wizard

        await update.message.reply_text(
            "✅ Grupo/canal gratuito configurado.\n\n"
            f"{AD_PROMO_CREATE_STEPS[0][1]}"
        )

        return


    step_index = wizard.get("step_index", 0)
    field, _prompt = AD_PROMO_CREATE_STEPS[step_index]
    int_fields = {
        "batch_size": 1,
        "interval_minutes": 5,
        "max_posts": 1
    }
    if field in int_fields:

        value = parse_ad_promo_int(text, minimum=int_fields[field])

        if value is None:

            await update.message.reply_text("❌ Valor no válido. Envía un número válido.")
            return

    elif field == "bot_link" and text.lower() == "auto":

        value = None

    else:

        value = sanitize_ad_promo_text(text)


    wizard.setdefault("data", {})[field] = value
    step_index += 1

    if step_index < len(AD_PROMO_CREATE_STEPS):

        wizard["step_index"] = step_index
        context.user_data["ad_promo_wizard"] = wizard
        await update.message.reply_text(AD_PROMO_CREATE_STEPS[step_index][1])
        return


    data = wizard.get("data") or {}
    source_details = await resolve_ad_promo_chat_details(
        context,
        data.get("source_chat_id")
    )
    promo_details = await resolve_ad_promo_chat_details(
        context,
        data.get("promo_group_telegram_id")
    )
    data["source_chat_title"] = source_details.get("title") or data.get("source_chat_title")
    data["source_chat_type"] = source_details.get("type") or data.get("source_chat_type")
    data["promo_group_title"] = promo_details.get("title") or data.get("promo_group_title")
    data["promo_group_type"] = promo_details.get("type") or data.get("promo_group_type") or "group"
    data["created_by_user_id"] = user_id
    campaign = create_ad_promo_campaign(data)
    context.user_data.pop("ad_promo_wizard", None)
    context.user_data.pop("ad_promo_create", None)

    log_event(
        "ad_promo_campaign_created",
        category="marketing",
        severity="info",
        scope="group",
        group_id=campaign.get("paid_group_id"),
        actor_user_id=user_id,
        message="Campaña de promoción automática creada.",
        metadata={"campaign_id": campaign.get("id")}
    )

    await update.message.reply_text(
        "✅ Campaña creada.\n\n"
        "El bot capturará vídeos nuevos que reciba en el chat fuente configurado.",
        reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
    )


async def continue_after_location_manual_review(context, chat_id, telegram_user, group_id, action, price_id=None, review=None):

    expires_at = review.get("expires_at") if review else None
    expires_text = format_commercial_datetime(expires_at) if expires_at else "-"
    user_id = telegram_user.id if telegram_user else None

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📍 Revisión temporal activa\n\n"
            f"Tu revisión manual está aprobada hasta {expires_text}.\n"
            "Puedes continuar ahora, aunque tu ubicación actual no coincida.\n\n"
            "Esta aprobación es temporal y solo aplica a esta comunidad."
        ),
        reply_markup=ReplyKeyboardRemove()
    )

    log_event(
        "location_manual_review_temp_access_used",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Revisión temporal de ubicación usada para continuar flujo de acceso.",
        metadata={
            "review_id": review.get("id") if review else None,
            "user_id": user_id,
            "group_id": group_id,
            "action": action,
            "price_id": price_id,
            "expires_at": str(expires_at) if expires_at else None
        }
    )

    clear_location_gate_state(context)

    if action == "free_access":

        await create_free_access_for_user(
            context,
            chat_id,
            telegram_user,
            group_id
        )

        return True


    if action == "checkout":

        await create_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return True


    if action == "paypal_checkout":

        await create_paypal_group_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return True


    if action == "revolut_checkout":

        await create_revolut_group_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return True


    if action == "changenow_checkout":

        await create_changenow_group_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return True


    if action == "guardarian_checkout":

        await create_guardarian_group_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return True


    if action == "location_only":

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Tu revisión temporal sigue activa para esta comunidad.\n"
                "Puedes volver al inicio o enviar una ubicación válida cuando estés en la zona permitida."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📍 Enviar ubicación ahora",
                    callback_data=f"location_review_send_location_{group_id}"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return True


    await context.bot.send_message(
        chat_id=chat_id,
        text="Tu revisión temporal está activa, pero no he podido continuar esta acción.",
        reply_markup=build_group_recovery_keyboard(group_id)
    )

    return True


async def process_expired_location_manual_reviews(context):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE location_manual_reviews
            SET status='expired',
                updated_at=NOW()
            WHERE status='approved_temp'
            AND expires_at < NOW()
            RETURNING {", ".join(LOCATION_MANUAL_REVIEW_FIELDS)}

        """)

        rows = cur.fetchall()


    expired_reviews = [
        row_to_location_manual_review(row)
        for row in rows
    ]


    for review in expired_reviews:

        log_event(
            "location_manual_review_expired",
            category="access",
            severity="info",
            scope="group",
            group_id=review.get("group_id"),
            actor_user_id=review.get("user_id"),
            target_user_id=review.get("user_id"),
            message="Revisión manual temporal de ubicación caducada.",
            metadata=build_location_manual_review_metadata(review)
        )

        try:

            await context.bot.send_message(
                chat_id=review.get("user_id"),
                text=(
                    "📍 Tu revisión temporal de ubicación ha caducado.\n\n"
                    "Para continuar, envía una ubicación válida para esta comunidad."
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📍 Enviar ubicación de nuevo",
                        callback_data=f"location_review_send_location_{review.get('group_id')}"
                    )],
                    [InlineKeyboardButton(
                        "🏠 Inicio",
                        callback_data="public_back_start"
                    )]
                ])
            )

        except Exception as e:

            print("Error notificando caducidad de revisión manual:", e)


    return {
        "expired": len(expired_reviews)
    }


def build_location_gate_owner_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "✅ Activar restricción por ubicación",
            callback_data=f"creator_location_gate_enable_{request_id}"
        )],

        [InlineKeyboardButton(
            "🚫 Desactivar restricción",
            callback_data=f"creator_location_gate_disable_{request_id}"
        )],

        [InlineKeyboardButton(
            "🌎 Elegir país",
            callback_data=f"creator_location_country_menu_{request_id}"
        )],

        [InlineKeyboardButton(
            "🇪🇸 Elegir comunidad autónoma",
            callback_data=f"creator_location_spain_region_menu_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"configure_community_{request_id}"
        )]

    ])






def get_group_location_gate(group_id):

    if not group_id:

        return False, None, None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT COALESCE(location_gate_enabled, FALSE),
                   allowed_region,
                   allowed_region_type
            FROM groups
            WHERE id=%s
            AND is_active=TRUE
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    if not row:

        return False, None, None


    region_type = normalize_allowed_region_type(row[2], row[1])
    allowed_region = normalize_allowed_region(region_type, row[1])

    return row[0] is True, allowed_region, region_type


def group_requires_location_gate(group_id):

    enabled, _allowed_region, _region_type = get_group_location_gate(group_id)

    return enabled


def get_group_location_gate_display(group_id):

    enabled, allowed_region, region_type = get_group_location_gate(group_id)

    return enabled, format_allowed_region(region_type, allowed_region)


def get_commercial_request_group_id(request_row):

    if not request_row:

        return None


    if request_row.get("approved_group_id"):

        return request_row.get("approved_group_id")


    approved_telegram_group_id = request_row.get("approved_telegram_group_id")


    if not approved_telegram_group_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id
            FROM groups
            WHERE telegram_group_id=%s
            LIMIT 1

        """, (approved_telegram_group_id,))

        row = cur.fetchone()


    return row[0] if row else None


def clear_location_gate_state(context):

    context.user_data.pop("location_gate_pending", None)
    context.user_data.pop("location_gate_group_id", None)
    context.user_data.pop("location_gate_action", None)
    context.user_data.pop("location_gate_price_id", None)


async def clear_location_flow_navigation(context, chat_id):

    cleared_keys = clear_location_flow_state(context)

    if not cleared_keys:

        return cleared_keys


    try:

        await context.bot.send_message(
            chat_id=chat_id,
            text="📍 Verificación de ubicación cancelada.",
            reply_markup=ReplyKeyboardRemove()
        )

    except Exception as e:

        print("Error quitando teclado de ubicación:", e)


    return cleared_keys


async def request_location_verification(
    context,
    chat_id,
    group_id,
    action,
    price_id=None,
    telegram_user=None,
    allow_manual_review_bypass=True
):

    context.user_data["location_gate_pending"] = True
    context.user_data["location_gate_group_id"] = group_id
    context.user_data["location_gate_action"] = action


    if price_id:

        context.user_data["location_gate_price_id"] = price_id

    else:

        context.user_data.pop("location_gate_price_id", None)


    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(
            "📍 Enviar ubicación",
            request_location=True
        )]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


    if telegram_user and allow_manual_review_bypass:

        review = fetch_active_location_manual_review(
            telegram_user.id,
            group_id
        )


        if review:

            await continue_after_location_manual_review(
                context,
                chat_id,
                telegram_user,
                group_id,
                action,
                price_id=price_id,
                review=review
            )

            return


    _enabled, region_label = get_group_location_gate_display(group_id)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📍 Esta comunidad requiere verificar tu ubicación.\n\n"
            f"Región permitida: {region_label}\n\n"
            "Pulsa el botón de Telegram “📍 Enviar ubicación”. No escribas tu ciudad manualmente.\n\n"
            "Usaremos tu ubicación solo para comprobar la región y no guardaremos tus coordenadas exactas.\n\n"
            "Si estás dentro de la zona permitida y te rechaza, contacta con soporte."
        ),
        reply_markup=keyboard
    )


def save_group_location_verification(group_id, user_id, resolved_region, status):

    resolved_region = resolved_region or {}

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO group_location_verifications
            (
                group_id,
                user_id,
                region_type,
                country,
                region,
                province,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)

        """, (
            group_id,
            user_id,
            (
                LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY
                if resolved_region.get("spanish_autonomous_community")
                else LOCATION_REGION_TYPE_COUNTRY
            ),
            resolved_region.get("country"),
            resolved_region.get("spanish_autonomous_community")
            or resolved_region.get("country_name"),
            resolved_region.get("province"),
            status
        ))

        conn.commit()




def get_admin_permissions(user_id):

    permissions = {
        column: False
        for column in ADMIN_PERMISSION_COLUMNS
    }


    if is_super_admin(user_id):

        return {
            column: True
            for column in ADMIN_PERMISSION_COLUMNS
        }


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT {", ".join(ADMIN_PERMISSION_COLUMNS)}

                FROM admins

                WHERE user_id=%s
                AND is_active=TRUE

            """, (user_id,))

            rows = cur.fetchall()


        for row in rows:

            for index, column in enumerate(ADMIN_PERMISSION_COLUMNS):

                permissions[column] = permissions[column] or row[index] is True

    except Exception as e:

        print("Error cargando permisos admin:", e)


    return permissions


def has_any_permission(permissions, names):

    return any(
        permissions.get(name) is True
        for name in names
    )


def has_any_admin_permission(user_id):

    permissions = get_admin_permissions(user_id)

    return any(
        value is True
        for value in permissions.values()
    )


def can_access_admin_callback(user_id, data):

    if is_super_admin(user_id):

        return True


    permissions = get_admin_permissions(user_id)


    if data == "admin_back_main":

        return any(
            value is True
            for value in permissions.values()
        )


    users_callbacks = {
        "menu_users",
        "admin_users",
        "admin_search_user"
    }

    manage_users_callbacks = {
        "admin_move_user"
    }

    codes_callbacks = {
        "menu_codes",
        "admin_create_code",
        "admin_codes",
        "admin_delete_code"
    }

    groups_callbacks = {
        "menu_groups",
        "admin_add_group",
        "admin_edit_group",
        "admin_view_groups",
        "cancel_create_group",
        "view_group_plans",
        "add_group_plan",
        "edit_group_plan_select",
        "delete_group_plan_select"
    }

    payments_callbacks = {
        "menu_payments",
        "admin_view_payments",
        "admin_search_payment"
    }

    manage_payments_callbacks = {
        "admin_resend_access",
        "admin_cancel_subscription"
    }

    stats_callbacks = {
        "menu_business",
        "admin_stats",
        "admin_income",
        "admin_active_users"
    }

    logs_callbacks = {
        "menu_logs",
        "admin_logs",
        "admin_logs_users",
        "admin_logs_payments",
        "admin_logs_security"
    }


    if data in users_callbacks:

        return has_any_permission(
            permissions,
            ["can_view_users", "can_manage_users"]
        )


    if data in manage_users_callbacks:

        return has_any_permission(
            permissions,
            ["can_manage_users"]
        )


    if data == "admin_kick_user":

        return has_any_permission(
            permissions,
            ["can_kick_users", "can_manage_users"]
        )


    if data == "admin_ban_user":

        return has_any_permission(
            permissions,
            ["can_ban_users", "can_manage_users"]
        )


    if data == "admin_unban_user":

        return has_any_permission(
            permissions,
            ["can_unban_users", "can_manage_users"]
        )


    if data == "admin_reset_warnings":

        return has_any_permission(
            permissions,
            ["can_reset_warnings", "can_manage_users"]
        )


    if data in codes_callbacks or data.startswith("gen_"):

        return has_any_permission(
            permissions,
            ["can_manage_codes"]
        )


    if (
        data in groups_callbacks
        or data.startswith("edit_group")
        or data.startswith("edit_plan_")
        or data.startswith("delete_group")
        or data.startswith("delete_plan_")
        or data.startswith("save_preview")
        or data.startswith("cancel_preview")
        or data.startswith("skip_preview")
    ):

        return has_any_permission(
            permissions,
            ["can_manage_groups"]
        )


    if data in payments_callbacks:

        return has_any_permission(
            permissions,
            ["can_view_payments", "can_manage_payments"]
        )


    if data in manage_payments_callbacks:

        return has_any_permission(
            permissions,
            ["can_manage_payments"]
        )


    if data in stats_callbacks:

        return has_any_permission(
            permissions,
            ["can_view_stats"]
        )


    if data in logs_callbacks:

        return has_any_permission(
            permissions,
            ["can_view_logs"]
        )


    if data.startswith("allow_user_"):

        return has_any_permission(
            permissions,
            ["can_manage_users"]
        )


    if data.startswith("deny_user_"):

        return has_any_permission(
            permissions,
            ["can_kick_users", "can_manage_users"]
        )


    return False


def build_commercial_menu_keyboard():

    return [

        [InlineKeyboardButton(
            COMMERCIAL_PRODUCTS[PRODUCT_SHARED_BOT_SPACE]["title_es"],
            callback_data=CALLBACK_SHARED_BOT_SPACE
        )],

        [InlineKeyboardButton(
            COMMERCIAL_PRODUCTS[PRODUCT_CUSTOM_BOT]["title_es"],
            callback_data=CALLBACK_CUSTOM_BOT
        )],

        [InlineKeyboardButton(
            "📩 Hablar con un asesor",
            callback_data=CALLBACK_COMMERCIAL_CONTACT
        )],

        [InlineKeyboardButton(
            "💬 Ayuda sobre este menú",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="public_back_start"
        )]

    ]


def user_has_group_owner_role(user_id):

    if is_super_admin(user_id):

        return True


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM admins
                WHERE user_id=%s
                AND role='GROUP_OWNER'
                AND is_active=TRUE
                LIMIT 1

            """, (user_id,))

            return cur.fetchone() is not None

    except Exception as e:

        print("Error verificando rol owner:", e)

        return False


def build_admin_home_text(user_id):

    if is_super_admin(user_id):

        return (
            "👑 Panel global del bot\n\n"
            "Gestiona la plataforma completa desde paneles separados: "
            "bot, propietarios y comunidades concretas."
        )


    if user_has_group_owner_role(user_id):

        return (
            "🏪 Mis comunidades\n\n"
            "Gestiona tus grupos concretos, códigos, planes, admins, logs y backups."
        )


    return (
        "👮 Panel admin de grupo\n\n"
        "Verás solo la comunidad actual, tus permisos concedidos y los accesos rápidos permitidos."
    )


def build_admin_global_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Monitor beta", callback_data="admin_beta_monitor")],
        [InlineKeyboardButton("😊 Satisfacción de clientes", callback_data="admin_customer_satisfaction")],
        [InlineKeyboardButton("🛟 Solicitudes de soporte", callback_data="admin_support_tickets")],
        [InlineKeyboardButton("🏪 Marketplace global", callback_data="admin_global_marketplace")],
        [InlineKeyboardButton("👥 Propietarios / solicitudes comerciales", callback_data="admin_owners_panel")],
        [InlineKeyboardButton("⚙️ Configuración global", callback_data="admin_global_config")],
        [InlineKeyboardButton("🛠 Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_global_panel")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_global_config_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏪 Marketplace / catálogo", callback_data="admin_global_marketplace")],
        [InlineKeyboardButton("💳 Planes comerciales del bot", callback_data="admin_global_commercial_plans")],
        [InlineKeyboardButton("💳 Métodos de pago", callback_data="admin_payment_providers")],
        [InlineKeyboardButton("🎟 Códigos comerciales globales", callback_data="admin_commercial_promo_codes")],
        [InlineKeyboardButton("😊 Encuestas y satisfacción", callback_data="admin_customer_satisfaction")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_global_config")],
        [InlineKeyboardButton("⬅️ Volver al panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_global_tools_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Centro IA", callback_data="admin_ai_center")],
        [InlineKeyboardButton("📣 Promoción automática", callback_data="admin_ad_promo")],
        [InlineKeyboardButton("🧪 Smoke Test Beta", callback_data="admin_smoke_test")],
        [InlineKeyboardButton("🗓 Ciclo beta", callback_data="admin_beta_cycle")],
        [InlineKeyboardButton("🧪 Auditoría de botones", callback_data="admin_button_audit")],
        [InlineKeyboardButton("👁 Seguimiento de usuarios", callback_data="admin_user_tracking")],
        [InlineKeyboardButton("📜 Logs del sistema", callback_data="menu_logs")],
        [InlineKeyboardButton("📊 Monitor beta", callback_data="admin_beta_monitor")],
        [InlineKeyboardButton("🗄️ Copia de la base de datos", callback_data="admin_db_backup")],
        [InlineKeyboardButton("🧱 Migraciones de base de datos", callback_data="admin_db_migrations")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_global_tools")],
        [InlineKeyboardButton("⬅️ Volver al panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_ai_feedback_markup(interaction_id, back_callback=None):

    rows = [
        [InlineKeyboardButton(label, callback_data=callback_data)]
        for label, callback_data in build_ai_feedback_keyboard_rows(interaction_id)
    ]

    if back_callback:

        rows.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])


    rows.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(rows)


def build_ai_feedback_next_keyboard(interaction_id=None, role=None, include_report=False, include_support=False):

    ask_callback = "public_ai_help"

    if role == AI_ROLE_BUYER:
        ask_callback = "ai_ask_buyer"
    elif role == AI_ROLE_OWNER:
        ask_callback = "owner_ai_ask"
    elif role == AI_ROLE_SUPERADMIN:
        ask_callback = "admin_ai_ask"

    rows = []


    if include_report and interaction_id:

        rows.append([InlineKeyboardButton("📝 Reportar problema", callback_data=f"ai_feedback_{interaction_id}_report")])


    rows.append([InlineKeyboardButton("🔁 Hacer otra pregunta", callback_data=ask_callback)])


    if include_support:

        rows.append([InlineKeyboardButton("🛟 Abrir soporte", callback_data="public_support")])


    rows.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(rows)


def build_buyer_ai_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pagué y no tengo link", callback_data="ai_buyer_access_help")],
        [InlineKeyboardButton("💳 Cómo puedo pagar", callback_data="ai_buyer_payment_methods")],
        [InlineKeyboardButton("📍 Por qué pide ubicación", callback_data="ai_buyer_location_help")],
        [InlineKeyboardButton("✍️ Preguntar a la IA", callback_data="ai_ask_buyer")],
        [InlineKeyboardButton("🛟 Soporte", callback_data="public_support")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_ai_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Ayúdame a configurar mi comunidad", callback_data="owner_ai_setup")],
        [InlineKeyboardButton("💳 Ayuda con métodos de pago", callback_data="owner_ai_payments")],
        [InlineKeyboardButton("📊 Analizar mis encuestas", callback_data="owner_ai_surveys")],
        [InlineKeyboardButton("👥 Analizar usuarios/accesos", callback_data="owner_ai_users")],
        [InlineKeyboardButton("🛟 Ayuda con soporte", callback_data="owner_ai_support")],
        [InlineKeyboardButton("🖼 Mejorar texto de marketplace", callback_data="owner_ai_marketplace")],
        [InlineKeyboardButton("🧪 Diagnóstico de mi comunidad", callback_data="owner_ai_diagnostics")],
        [InlineKeyboardButton("✍️ Preguntar a la IA", callback_data="owner_ai_ask")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_ai_center_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚨 Diagnóstico de errores", callback_data="admin_ai_errors")],
        [InlineKeyboardButton("💳 Diagnóstico de pagos", callback_data="admin_ai_payments")],
        [InlineKeyboardButton("👥 Resumen de usuarios", callback_data="admin_ai_users")],
        [InlineKeyboardButton("😊 Resumen de encuestas", callback_data="admin_ai_surveys")],
        [InlineKeyboardButton("🛟 Resumen soporte", callback_data="admin_ai_support")],
        [InlineKeyboardButton("🧪 Auditorías", callback_data="admin_ai_audits")],
        [InlineKeyboardButton("🧾 Preparar tarea para Codex", callback_data="admin_ai_codex_task")],
        [InlineKeyboardButton("📋 Feedback IA / problemas", callback_data="admin_ai_feedback")],
        [InlineKeyboardButton("✍️ Preguntar a la IA", callback_data="admin_ai_ask")],
        [InlineKeyboardButton("⬅️ Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_ai_feedback_text(limit=10):

    try:
        with conn.cursor() as cur:
            cur.execute("""

                SELECT user_id,
                       role,
                       group_id,
                       intent,
                       feedback_rating,
                       response_summary,
                       created_at
                FROM ai_interactions
                WHERE feedback_rating IN ('not_useful', 'problem')
                ORDER BY created_at DESC
                LIMIT %s

            """, (limit,))
            rows = cur.fetchall()

    except Exception as exc:
        print("admin_ai_feedback_error:", str(exc)[:200])
        rows = []


    if not rows:
        return (
            "📋 Feedback IA / problemas\n\n"
            "Todavía no hay respuestas marcadas como no útiles o con problema reportado."
        )


    lines = [
        "📋 Feedback IA / problemas",
        "",
        "Últimas respuestas a revisar:"
    ]


    for user_id, role, group_id, intent, feedback_rating, response_summary, created_at in rows:

        lines.extend([
            "",
            f"Fecha: {created_at}",
            f"Usuario: {user_id}",
            f"Rol: {role or '-'}",
            f"Grupo: {group_id or '-'}",
            f"Intent: {intent or '-'}",
            f"Feedback: {feedback_rating or '-'}",
            f"Resumen: {str(response_summary or '-')[:350]}"
        ])


    return "\n".join(lines)


async def send_ai_result_message(context, chat_id, result, back_callback=None):

    prefix = "🤖 Respuesta IA"

    if result.get("fallback_used"):
        prefix += "\n\nNota: respuesta generada con fallback seguro porque el modelo no está disponible o no aportó respuesta fiable."

    await send_clean_message(
        context,
        chat_id,
        f"{prefix}\n\n{result.get('answer') or 'No tengo suficiente información para confirmarlo.'}",
        reply_markup=build_ai_feedback_markup(
            result.get("interaction_id"),
            back_callback=back_callback
        )
    )


def build_admin_global_marketplace_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Ver marketplace como usuario", callback_data="start_explore_groups")],
        [InlineKeyboardButton("⚙️ Configuración global", callback_data="admin_global_config")],
        [InlineKeyboardButton("👥 Propietarios / comunidades", callback_data="admin_owners_panel")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_global_marketplace")],
        [InlineKeyboardButton("⬅️ Volver al panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_global_commercial_plans_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Precio de publicar comunidad",
                              callback_data="admin_platform_plan_prices")],
        [InlineKeyboardButton("👥 Propietarios / solicitudes", callback_data="admin_owners_panel")],
        [InlineKeyboardButton("💳 Suscripciones comerciales", callback_data="admin_commercial_subscriptions")],
        [InlineKeyboardButton("🎟 Códigos comerciales globales", callback_data="admin_commercial_promo_codes")],
        [InlineKeyboardButton("⬅️ Volver a configuración global", callback_data="admin_global_config")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_payment_providers_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💱 ChangeNOW.io / Cripto", callback_data="admin_payment_changenow")],
        [InlineKeyboardButton("💳 Tarjeta EUR → USDT / Guardarian", callback_data="admin_payment_guardarian")],
        [InlineKeyboardButton("🧪 Pagos ChangeNOW en revisión", callback_data="admin_changenow_manual_review")],
        [InlineKeyboardButton("🧪 Pagos Guardarian en revisión", callback_data="admin_guardarian_manual_review")],
        [InlineKeyboardButton("🎟 Códigos comerciales globales", callback_data="admin_commercial_promo_codes")],
        [InlineKeyboardButton("⚙️ Configuración global", callback_data="admin_global_config")],
        [InlineKeyboardButton("🛠 Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_button_audit_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver detalle", callback_data="admin_button_audit_detail")],
        [InlineKeyboardButton("🔁 Repetir auditoría", callback_data="admin_button_audit_refresh")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_button_audit")],
        [InlineKeyboardButton("⬅️ Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_button_audit_menu_specs():

    return [
        {
            "name": "Panel global",
            "callback_data": "admin_global_panel",
            "keyboard": build_admin_global_panel_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Configuración global",
            "callback_data": "admin_global_config",
            "keyboard": build_admin_global_config_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Herramientas internas",
            "callback_data": "admin_global_tools",
            "keyboard": build_admin_global_tools_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Propietarios / solicitudes comerciales",
            "callback_data": "admin_owners_panel",
            "keyboard": build_admin_owners_panel_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Satisfacción de clientes",
            "callback_data": "admin_customer_satisfaction",
            "keyboard": build_customer_satisfaction_panel_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Solicitudes de soporte",
            "callback_data": "admin_support_tickets",
            "keyboard": InlineKeyboardMarkup(build_support_tickets_keyboard([])),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Marketplace global",
            "callback_data": "admin_global_marketplace",
            "keyboard": build_admin_global_marketplace_keyboard(),
            "requires_help": True,
            "requires_navigation": True
        },
        {
            "name": "Planes comerciales del bot",
            "callback_data": "admin_global_commercial_plans",
            "keyboard": build_admin_global_commercial_plans_keyboard(),
            "requires_help": False,
            "requires_navigation": True
        }
    ]


def build_admin_button_audit_report():

    return audit_admin_button_menus(
        build_admin_button_audit_menu_specs(),
        get_required_permissions_for_callback
    )


def build_admin_owners_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕓 Solicitudes pendientes", callback_data="admin_commercial_requests")],
        [InlineKeyboardButton("✅ Propietarios activos", callback_data="admin_commercial_active_requests")],
        [InlineKeyboardButton("🧪 Trials activos", callback_data="admin_commercial_trials_active")],
        [InlineKeyboardButton("💳 Suscripciones comerciales", callback_data="admin_commercial_subscriptions")],
        [InlineKeyboardButton("📦 Cupos de grupos", callback_data="admin_commercial_group_limits")],
        [InlineKeyboardButton("📁 Archivados", callback_data="admin_commercial_archived_requests")],
        [InlineKeyboardButton("🔎 Buscar propietario", callback_data="admin_commercial_owner_tools")],
        [InlineKeyboardButton("📊 Resumen propietarios", callback_data="admin_commercial_owner_summary")],
        [InlineKeyboardButton("🔁 Reasignar owner/grupo", callback_data="admin_commercial_reassign_owner_group")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_owners_panel")],
        [InlineKeyboardButton("👑 Panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def build_customer_satisfaction_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 Enviar a pendientes", callback_data="admin_satisfaction_send_pending")],
        [InlineKeyboardButton("🔁 Reenviar a no completados", callback_data="admin_satisfaction_resend_incomplete")],
        [InlineKeyboardButton("🧹 Enviar solo a nunca enviados", callback_data="admin_satisfaction_send_never_sent")],
        [InlineKeyboardButton("📊 Ver estado de envíos", callback_data="admin_satisfaction_delivery_status")],
        [InlineKeyboardButton("📋 Detalle de encuestas", callback_data="satisfaction_detail")],
        [InlineKeyboardButton("⚠️ Forzar nuevo ciclo", callback_data="admin_satisfaction_force_new_cycle")],
        [InlineKeyboardButton("👥 Enviar solo a usuarios", callback_data="admin_satisfaction_send_users")],
        [InlineKeyboardButton("🧑‍💼 Enviar solo a propietarios", callback_data="admin_satisfaction_send_owners")],
        [InlineKeyboardButton("👮 Enviar solo a admins de grupo", callback_data="admin_satisfaction_send_group_admins")],
        [InlineKeyboardButton("📊 Ver resultados", callback_data="admin_satisfaction_results")],
        [InlineKeyboardButton("📝 Gestionar preguntas", callback_data="admin_satisfaction_questions")],
        [InlineKeyboardButton("➕ Añadir pregunta", callback_data="admin_satisfaction_add_rating")],
        [InlineKeyboardButton("➕ Añadir pregunta texto", callback_data="admin_satisfaction_add_text")],
        [InlineKeyboardButton("✏️ Editar preguntas", callback_data="admin_satisfaction_edit_menu")],
        [InlineKeyboardButton("🚫 Desactivar pregunta", callback_data="admin_satisfaction_deactivate_menu")],
        [InlineKeyboardButton("📋 Últimas respuestas", callback_data="admin_satisfaction_latest")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="admin_help_customer_satisfaction")],
        [InlineKeyboardButton("⬅️ Volver al panel global", callback_data="admin_global_panel")]
    ])


def build_owner_satisfaction_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 Enviar a pendientes", callback_data="owner_satisfaction_send_pending")],
        [InlineKeyboardButton("🔁 Reenviar a no completados", callback_data="owner_satisfaction_resend_incomplete")],
        [InlineKeyboardButton("🧹 Enviar solo a nunca enviados", callback_data="owner_satisfaction_send_never_sent")],
        [InlineKeyboardButton("📊 Ver estado de envíos", callback_data="owner_satisfaction_delivery_status")],
        [InlineKeyboardButton("📋 Detalle de encuestas", callback_data="satisfaction_detail")],
        [InlineKeyboardButton("⚠️ Forzar nuevo ciclo", callback_data="owner_satisfaction_force_new_cycle")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="owner_panel_help_satisfaction")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="owner_panel_general")]
    ])


ADMIN_CONTEXT_HELP_TEXTS = {
    "global_panel": (
        "❓ Ayuda — Panel global del bot\n\n"
        "Este panel es el índice principal de la plataforma.\n\n"
        "📊 Monitor beta: úsalo para ver alertas, pagos, accesos, códigos y errores recientes.\n"
        "😊 Satisfacción de clientes: envía encuestas y revisa qué opinan usuarios, owners y admins.\n"
        "🛟 Solicitudes de soporte: abre la bandeja de tickets de ayuda.\n"
        "🏪 Marketplace global: revisa cómo se ve el catálogo de comunidades y su configuración general.\n"
        "👥 Propietarios / solicitudes comerciales: gestiona creators, pruebas, cupos y solicitudes.\n"
        "⚙️ Configuración global: ajustes de plataforma, catálogo, planes comerciales y encuestas.\n"
        "🛠 Herramientas internas: diagnóstico, smoke test, ciclo beta y logs.\n\n"
        "Usa Volver para regresar al panel anterior o Inicio para volver al menú principal."
    ),
    "global_config": (
        "❓ Ayuda — Configuración global\n\n"
        "Este menú agrupa ajustes de plataforma y negocio.\n\n"
        "🏪 Marketplace / catálogo: abre la vista global del catálogo y sus opciones disponibles.\n"
        "💳 Planes comerciales del bot: revisa la zona de planes que pagan los owners para publicar.\n"
        "🎟 Códigos comerciales globales: crea códigos para owners, no para usuarios finales de grupos.\n"
        "💳 Métodos de pago: revisa Stripe activo y proveedores futuros sin activar accesos inseguros.\n"
        "😊 Encuestas y satisfacción: configura preguntas y envíos de encuestas.\n\n"
        "No incluye logs ni pruebas técnicas; eso vive en Herramientas internas."
    ),
    "global_tools": (
        "❓ Ayuda — Herramientas internas\n\n"
        "Este menú es para operar y diagnosticar el bot.\n\n"
        "🧪 Smoke Test Beta: ejecuta comprobaciones seguras antes de probar en real.\n"
        "🗓 Ciclo beta: controla semanas de beta, cierre y preparación de lanzamiento.\n"
        "🧪 Auditoría de botones: revisa menús, callbacks, permisos y navegación sin pulsar todo a mano.\n"
        "📜 Logs del sistema: revisa actividad técnica y eventos importantes.\n"
        "📊 Monitor beta: mira alertas y resumen de las últimas horas.\n\n"
        "Si buscas cambiar catálogo, planes o encuestas, usa Configuración global."
    ),
    "owners_panel": (
        "❓ Ayuda — Propietarios y solicitudes comerciales\n\n"
        "Aquí gestionas a quienes quieren publicar comunidades en el bot.\n\n"
        "🕓 Solicitudes pendientes: peticiones nuevas que aún necesitan decisión.\n"
        "✅ Propietarios activos: creators que ya están aprobados o configurando.\n"
        "🧪 Trials activos: pruebas de 1 día en curso.\n"
        "💳 Suscripciones comerciales: estado comercial de owners.\n"
        "📦 Cupos de grupos: cuántas comunidades puede tener cada owner.\n"
        "📁 Archivados: solicitudes cerradas sin borrar datos.\n"
        "🔎 Buscar propietario: revisa un owner concreto.\n"
        "📊 Resumen propietarios: vista general para decidir rápido.\n\n"
        "Úsalo cuando una persona quiera publicar, reactivar o resolver su comunidad."
    ),
    "customer_satisfaction": (
        "❓ Ayuda — Satisfacción de clientes\n\n"
        "Este módulo sirve para saber si el bot se entiende y dónde falla la experiencia.\n\n"
        "📨 Enviar a pendientes: solo escribe a quienes no la recibieron y no la completaron.\n"
        "🔁 Reenviar a no completados: recuerda la encuesta solo a quienes la recibieron y aún no respondieron.\n"
        "🧹 Enviar solo a nunca enviados: evita completados y también evita cualquier usuario con envío previo.\n"
        "📊 Ver estado de envíos: muestra completados, enviados sin responder, nunca enviados y fallidos.\n"
        "⚠️ Forzar nuevo ciclo: abre una campaña nueva, pero sigue omitiendo por defecto a quienes ya respondieron.\n"
        "👥 / 🧑‍💼 / 👮 Envíos segmentados: pregunta solo a usuarios, owners o admins.\n"
        "📊 Ver resultados: medias, tasa de respuesta y puntos débiles.\n"
        "📝 Gestionar preguntas: revisa las preguntas activas.\n"
        "➕ Añadir pregunta: crea preguntas de puntuación o texto.\n"
        "✏️ Editar / 🚫 Desactivar: ajusta preguntas sin perder respuestas anteriores.\n"
        "📋 Últimas respuestas: lee comentarios recientes.\n\n"
        "Úsalo durante beta para priorizar mejoras reales."
    ),
    "support_tickets": (
        "❓ Ayuda — Solicitudes de soporte\n\n"
        "Aquí ves tickets abiertos o respondidos recientemente.\n\n"
        "Cada botón de ticket abre la conversación con datos del usuario y últimos mensajes.\n"
        "✍️ Responder: envía una respuesta privada al usuario desde el bot.\n"
        "✅ Cerrar ticket: marca el caso como cerrado cuando ya está resuelto.\n\n"
        "Si una captura llega por soporte, se conserva dentro del ticket y no se mezcla con previews."
    ),
    "global_marketplace": (
        "❓ Ayuda — Marketplace global\n\n"
        "Esta pantalla te ayuda a revisar el catálogo público de comunidades.\n\n"
        "🔎 Ver marketplace como usuario: abre la experiencia pública para comprobar fichas, previews y accesos.\n"
        "⚙️ Configuración global: vuelve a ajustes de catálogo, planes comerciales y encuestas.\n"
        "👥 Propietarios / comunidades: revisa owners y solicitudes que alimentan el marketplace.\n\n"
        "Úsalo para comprobar si el escaparate del bot está claro antes de abrir la beta."
    ),
    "button_audit": (
        "❓ Ayuda — Auditoría de botones\n\n"
        "Esta herramienta revisa menús importantes sin pulsar botón por botón en Telegram.\n\n"
        "El resumen te dice si un menú está OK, si conviene revisarlo o si tiene un problema.\n"
        "📋 Ver detalle muestra cada botón con su callback y observación.\n"
        "🔁 Repetir auditoría vuelve a generar el informe con el estado actual.\n\n"
        "Es una revisión automática: ayuda a encontrar errores, pero las pruebas reales de pagos, soporte y grupos siguen siendo necesarias."
    )
}

ADMIN_CONTEXT_HELP_BACK_CALLBACKS = {
    "global_panel": "admin_global_panel",
    "global_config": "admin_global_config",
    "global_tools": "admin_global_tools",
    "owners_panel": "admin_owners_panel",
    "customer_satisfaction": "admin_customer_satisfaction",
    "support_tickets": "admin_support_tickets",
    "global_marketplace": "admin_global_marketplace",
    "button_audit": "admin_button_audit"
}


def build_admin_context_help_text(help_key):

    return ADMIN_CONTEXT_HELP_TEXTS.get(
        help_key,
        "❓ Ayuda\n\nEsta ayuda todavía no está configurada para este menú."
    )


def build_admin_context_help_keyboard(help_key):

    back_callback = ADMIN_CONTEXT_HELP_BACK_CALLBACKS.get(
        help_key,
        "admin_global_panel"
    )


    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver al menú", callback_data=back_callback)],
        [InlineKeyboardButton("👑 Panel global", callback_data="admin_global_panel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])








def normalize_customer_satisfaction_campaign_id(campaign_id=None):

    return str(campaign_id or "default")






def fetch_latest_customer_satisfaction_survey(audience="global", group_id=None):

    with conn.cursor() as cur:
        cur.execute("""

            SELECT id,
                   audience,
                   status,
                   group_id,
                   COALESCE(campaign_id, 'default'),
                   COALESCE(send_mode, 'pending')
            FROM customer_satisfaction_surveys
            WHERE audience=%s
            AND COALESCE(group_id, 0)=COALESCE(%s, 0)
            ORDER BY created_at DESC, id DESC
            LIMIT 1

        """, (audience, group_id))
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "audience": row[1],
        "status": row[2],
        "group_id": row[3],
        "campaign_id": row[4],
        "send_mode": row[5]
    }






















def format_tracking_time(value):

    if not value:
        return "-"

    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)[:16]


def build_user_tracking_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Resumen general", callback_data="admin_user_tracking")],
        [InlineKeyboardButton("👤 Buscar usuario", callback_data="admin_user_tracking_search")],
        [InlineKeyboardButton("🕒 Última actividad", callback_data="admin_user_tracking_latest")],
        [InlineKeyboardButton("🏪 Actividad por comunidad", callback_data="admin_user_tracking_groups")],
        [InlineKeyboardButton("💳 Actividad de pagos", callback_data="admin_user_tracking_payments")],
        [InlineKeyboardButton("🎟 Códigos canjeados", callback_data="admin_user_tracking_codes")],
        [InlineKeyboardButton("🛟 Soporte", callback_data="admin_user_tracking_support")],
        [InlineKeyboardButton("😊 Encuestas", callback_data="admin_user_tracking_surveys")],
        [InlineKeyboardButton("📍 Ubicaciones", callback_data="admin_user_tracking_locations")],
        [InlineKeyboardButton("📋 Detalle de encuestas", callback_data="satisfaction_detail")],
        [InlineKeyboardButton("⬅️ Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def format_user_tracking_event_rows(rows):

    if not rows:
        return "Sin actividad registrada todavía."

    lines = []

    for row in rows[:25]:
        user_id, username, first_name, event_type, event_key, group_id, plan_id, provider, created_at = row
        user_label = f"@{username}" if username else (first_name or str(user_id))
        group_text = f" · grupo {group_id}" if group_id else ""
        plan_text = f" · plan {plan_id}" if plan_id else ""
        provider_text = f" · {provider}" if provider else ""
        lines.append(
            f"- {format_tracking_time(created_at)} · {event_type} · {user_label} ({user_id})\n"
            f"  {event_key or '-'}{group_text}{plan_text}{provider_text}"
        )

    return "\n".join(lines)


def build_user_tracking_overview_text():

    overview = fetch_tracking_overview()

    top_events = "\n".join(
        f"- {event_key}: {count}"
        for event_key, count in overview.get("top_events", [])
    ) or "Sin datos."

    top_groups = "\n".join(
        f"- {name} ({group_id}): {count}"
        for group_id, name, count in overview.get("top_groups", [])
    ) or "Sin datos."

    return (
        "👁 Seguimiento de usuarios\n\n"
        "Este panel muestra actividad registrada dentro del bot y comunidades gestionadas por el bot. "
        "No muestra grupos externos de Telegram donde el bot no participa.\n\n"
        f"Usuarios que iniciaron bot: {overview.get('started_users', 0)}\n"
        f"Usuarios activos 24h: {overview.get('active_24h', 0)}\n"
        f"Usuarios activos 7 días: {overview.get('active_7d', 0)}\n"
        f"Eventos 24h: {overview.get('events_24h', 0)}\n"
        f"Pagos iniciados 7 días: {overview.get('payments_started', 0)}\n"
        f"Pagos completados 7 días: {overview.get('payments_completed', 0)}\n"
        f"Soportes abiertos 7 días: {overview.get('support_opened', 0)}\n"
        f"Encuestas completadas 7 días: {overview.get('surveys_completed', 0)}\n\n"
        "Top botones/comandos 7 días:\n"
        f"{top_events}\n\n"
        "Top comunidades 7 días:\n"
        f"{top_groups}"
    )


def build_user_tracking_events_text(title, event_type=None):

    rows = fetch_recent_user_events(limit=25, event_type=event_type)

    return f"{title}\n\n{format_user_tracking_event_rows(rows)}"


def build_user_tracking_groups_text():

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.group_id,
                       COALESCE(g.name, 'Grupo ' || e.group_id::text),
                       COUNT(DISTINCT e.user_id),
                       COUNT(*)
                FROM bot_user_events e
                LEFT JOIN groups g ON g.id=e.group_id
                WHERE e.group_id IS NOT NULL
                GROUP BY e.group_id, g.name
                ORDER BY COUNT(*) DESC
                LIMIT 20
            """)
            rows = cur.fetchall()
    except Exception:
        rows = []

    if not rows:
        body = "Sin actividad por comunidad registrada todavía."
    else:
        body = "\n".join(
            f"- {name} ({group_id}): {users} usuarios · {events} eventos"
            for group_id, name, users, events in rows
        )

    return f"🏪 Actividad por comunidad\n\n{body}"


def build_user_tracking_payments_text():

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id,
                       group_id,
                       plan_id,
                       provider,
                       payment_scope,
                       amount,
                       currency,
                       status,
                       created_at
                FROM payment_transactions
                ORDER BY created_at DESC
                LIMIT 25
            """)
            rows = cur.fetchall()
    except Exception:
        rows = []

    if not rows:
        return "💳 Actividad de pagos\n\nSin transacciones registradas todavía."

    lines = ["💳 Actividad de pagos", ""]

    for user_id, group_id, plan_id, provider, scope, amount, currency, status, created_at in rows:
        amount_text = f"{amount} {currency or ''}".strip() if amount is not None else "-"
        lines.append(
            f"- {format_tracking_time(created_at)} · {provider} · {status}\n"
            f"  Usuario: {user_id or '-'} · Grupo: {group_id or '-'} · Plan: {plan_id or '-'} · Scope: {scope or '-'} · Importe: {amount_text}"
        )

    return "\n".join(lines)


def build_user_tracking_user_profile_text(profile_data):

    if not profile_data:
        return "👤 Buscar usuario\n\nNo encontré actividad registrada para ese usuario."

    profile = profile_data["profile"]
    user_id, username, first_name, last_name, first_seen, last_seen, total_events = profile
    username_text = f"@{username}" if username else "Sin username"
    name_text = " ".join(part for part in (first_name, last_name) if part).strip() or "Sin nombre disponible"
    groups_text = "\n".join(
        f"- {name} ({group_id})"
        for group_id, name in profile_data.get("groups", [])
    ) or "Sin comunidades del bot registradas."

    return (
        f"👤 {name_text}\n"
        f"Username: {username_text}\n"
        f"ID: {user_id}\n"
        f"Primera actividad: {format_tracking_time(first_seen)}\n"
        f"Última actividad: {format_tracking_time(last_seen)}\n"
        f"Eventos: {total_events}\n\n"
        f"Compras iniciadas: {profile_data.get('checkout_count', 0)}\n"
        f"Pagos completados: {profile_data.get('payment_count', 0)}\n"
        f"Pagos fallidos: {profile_data.get('payment_failed_count', 0)}\n"
        f"Soporte: {profile_data.get('support_count', 0)}\n"
        f"Encuestas recibidas: {profile_data.get('survey_sent_count', 0)}\n"
        f"Encuestas completadas: {profile_data.get('survey_completed_count', 0)}\n\n"
        "Comunidades del bot con actividad:\n"
        f"{groups_text}\n\n"
        "Últimas acciones:\n"
        f"{format_user_tracking_event_rows(profile_data.get('events', []))}"
    )


def user_can_view_satisfaction_survey(user_id, survey_id):

    if is_super_admin(user_id):
        return True

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT group_id
                FROM customer_satisfaction_surveys
                WHERE id=%s
                LIMIT 1
            """, (survey_id,))
            row = cur.fetchone()
    except Exception:
        row = None

    if not row or not safe_satisfaction_value(row, 0):
        return False

    return user_has_group_permission_any(
        user_id,
        safe_satisfaction_value(row, 0),
        ["can_manage_groups", "can_view_logs"]
    )


def get_satisfaction_detail_scope(user_id, context):

    if is_super_admin(user_id):
        return None

    return get_selected_group_for_permissions(
        context,
        user_id,
        ["can_manage_groups", "can_view_logs"]
    )


def safe_satisfaction_value(row, index, default=None):

    try:
        if row is None or len(row) <= index:
            return default

        value = row[index]
        return default if value is None else value

    except Exception:
        return default


def log_satisfaction_detail_row_issue(callback, user_id=None, group_id=None, screen=None, row=None, expected_columns=None):

    try:
        log_event(
            "satisfaction_detail_row_issue",
            category="satisfaction",
            severity="warning",
            scope="group" if group_id else "global",
            group_id=group_id,
            actor_user_id=user_id,
            message="Fila incompleta al renderizar detalle de encuestas.",
            metadata={
                "callback": callback,
                "screen": screen,
                "expected_columns": expected_columns,
                "actual_columns": len(row) if row is not None else 0
            }
        )
    except Exception:
        pass


def normalize_satisfaction_survey_row(row, callback="satisfaction_detail", user_id=None, group_id=None, screen="survey_list"):

    if not row or len(row) < 2:
        log_satisfaction_detail_row_issue(
            callback,
            user_id=user_id,
            group_id=group_id,
            screen=screen,
            row=row,
            expected_columns=15
        )
        return None

    if len(row) < 15:
        log_satisfaction_detail_row_issue(
            callback,
            user_id=user_id,
            group_id=group_id,
            screen=screen,
            row=row,
            expected_columns=15
        )

    return {
        "survey_id": safe_satisfaction_value(row, 0),
        "title": safe_satisfaction_value(row, 1, "Encuesta"),
        "group_id": safe_satisfaction_value(row, 2),
        "group_name": safe_satisfaction_value(row, 3, "Global"),
        "campaign_id": safe_satisfaction_value(row, 4, "default"),
        "status": safe_satisfaction_value(row, 5, "draft"),
        "created_at": safe_satisfaction_value(row, 6),
        "sent_at": safe_satisfaction_value(row, 7),
        "sent_count": safe_satisfaction_value(row, 8, 0) or 0,
        "completed_count": safe_satisfaction_value(row, 9, 0) or 0,
        "failed_count": safe_satisfaction_value(row, 10, 0) or 0,
        "skipped_count": safe_satisfaction_value(row, 11, 0) or 0,
        "average_rating": safe_satisfaction_value(row, 12),
        "last_sent_at": safe_satisfaction_value(row, 13),
        "survey_count": safe_satisfaction_value(row, 14, 0) or 0
    }


def fetch_satisfaction_surveys_for_scope(group_id=None, limit=12):

    params = []
    group_filter = ""

    if group_id is not None:
        group_filter = "WHERE COALESCE(s.group_id, 0)=COALESCE(%s, 0)"
        params.append(group_id)

    params.append(limit)

    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.id,
                       COALESCE(s.title, 'Encuesta'),
                       s.group_id,
                       COALESCE(g.name, 'Global'),
                       COALESCE(s.campaign_id, 'default'),
                       COALESCE(s.status, 'draft'),
                       s.created_at,
                       s.sent_at,
                       COALESCE(s.sent_count, 0),
                       (
                           SELECT COUNT(*)
                           FROM customer_satisfaction_responses r
                           WHERE r.survey_id=s.id
                           AND r.completed_at IS NOT NULL
                       ),
                       COALESCE(s.failed_count, 0),
                       COALESCE(s.skipped_completed_count, 0) + COALESCE(s.skipped_already_sent_count, 0),
                       (
                           SELECT AVG(a.rating)
                           FROM customer_satisfaction_answers a
                           JOIN customer_satisfaction_responses r ON r.id=a.response_id
                           WHERE r.survey_id=s.id
                           AND a.rating IS NOT NULL
                       ),
                       (
                           SELECT MAX(cs.sent_at)
                           FROM customer_satisfaction_sent cs
                           WHERE cs.survey_id=s.id
                       ),
                       COUNT(*) OVER()
                FROM customer_satisfaction_surveys s
                LEFT JOIN groups g ON g.id=s.group_id
                {group_filter}
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT %s
            """, tuple(params))
            return cur.fetchall()
    except Exception as e:
        try:
            log_event(
                "satisfaction_detail_load_failed",
                category="satisfaction",
                severity="warning",
                scope="group" if group_id else "global",
                group_id=group_id,
                message="No se pudo cargar el listado de detalle de encuestas.",
                metadata={
                    "callback": "satisfaction_detail",
                    "error": str(e)[:250]
                }
            )
        except Exception:
            pass

        return []


def build_satisfaction_survey_list_text(user_id, context):

    group_id = get_satisfaction_detail_scope(user_id, context)

    if not is_super_admin(user_id) and not group_id:
        return "⛔ No tienes permiso para ver detalle de encuestas."

    rows = fetch_satisfaction_surveys_for_scope(group_id=group_id)

    if not rows:
        return "📋 Todavía no hay encuestas registradas para mostrar."

    first_row = rows[0] if rows else None
    survey_count = safe_satisfaction_value(first_row, 14, len(rows)) or len(rows)
    lines = [
        "😊 Detalle de satisfacción",
        "",
        f"Encuestas/campañas registradas: {survey_count}",
        "",
        "Elige una encuesta para ver enviados, pendientes, fallidos y respuestas persona por persona."
    ]

    for index, row in enumerate(rows, start=1):
        survey = normalize_satisfaction_survey_row(
            row,
            user_id=user_id,
            group_id=group_id,
            screen="survey_list_text"
        )

        if not survey:
            continue

        pending_count = max(survey["sent_count"] - survey["completed_count"] - survey["failed_count"], 0)
        response_rate = round((survey["completed_count"] / survey["sent_count"]) * 100, 1) if survey["sent_count"] else 0
        average_rating = survey.get("average_rating")
        average_text = f"{round(float(average_rating), 2)}/5" if average_rating else "Sin datos"
        last_sent_at = survey.get("last_sent_at") or survey.get("sent_at")
        lines.append(
            f"\n{index}) #{survey['survey_id']} · {survey['title']}\n"
            f"Comunidad: {survey['group_name']} ({survey['group_id'] or 'global'})\n"
            f"Campaña: {survey['campaign_id']} · Estado: {survey['status']}\n"
            f"Enviados: {survey['sent_count']} · Fallidos: {survey['failed_count']} · Respuestas: {survey['completed_count']}\n"
            f"Pendientes: {pending_count} · Omitidos: {survey['skipped_count']}\n"
            f"Media: {average_text} · Tasa respuesta: {response_rate}%\n"
            f"Creada: {format_tracking_time(survey['created_at'])} · Último envío: {format_tracking_time(last_sent_at)}"
        )

    return "\n".join(lines) if len(lines) > 5 else "📋 Todavía no hay encuestas registradas para mostrar."


def build_satisfaction_survey_list_keyboard(user_id, context):

    group_id = get_satisfaction_detail_scope(user_id, context)
    keyboard = []
    back_callback = "admin_customer_satisfaction" if is_super_admin(user_id) else "owner_panel_satisfaction"

    if not is_super_admin(user_id) and not group_id:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

    rows = fetch_satisfaction_surveys_for_scope(group_id=group_id)

    for row in rows[:10]:
        survey = normalize_satisfaction_survey_row(
            row,
            user_id=user_id,
            group_id=group_id,
            screen="survey_list_keyboard"
        )

        if not survey or not survey["survey_id"]:
            continue

        keyboard.append([
            InlineKeyboardButton(
                f"📝 #{survey['survey_id']} · {survey['group_name'] or survey['title']}",
                callback_data=f"satisfaction_survey_{survey['survey_id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def fetch_satisfaction_survey_header(survey_id):

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.id,
                       COALESCE(s.title, 'Encuesta'),
                       s.group_id,
                       COALESCE(g.name, 'Global'),
                       COALESCE(s.campaign_id, 'default'),
                       COALESCE(s.status, 'draft'),
                       s.created_at,
                       s.sent_at
                FROM customer_satisfaction_surveys s
                LEFT JOIN groups g ON g.id=s.group_id
                WHERE s.id=%s
                LIMIT 1
            """, (survey_id,))
            return cur.fetchone()
    except Exception as e:
        try:
            log_event(
                "satisfaction_detail_load_failed",
                category="satisfaction",
                severity="warning",
                message="No se pudo cargar la cabecera de encuesta.",
                metadata={
                    "callback": "satisfaction_survey",
                    "survey_id": survey_id,
                    "error": str(e)[:250]
                }
            )
        except Exception:
            pass

        return None


def build_satisfaction_survey_detail_text(survey_id):

    header = fetch_satisfaction_survey_header(survey_id)

    if not header:
        return "❌ Encuesta no encontrada."

    if len(header) < 8:
        log_satisfaction_detail_row_issue(
            "satisfaction_survey",
            group_id=safe_satisfaction_value(header, 2),
            screen="survey_header",
            row=header,
            expected_columns=8
        )
        return "⚠️ No he podido cargar el detalle de esta encuesta. Vuelve a intentarlo o pulsa Inicio."

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(DISTINCT cs.user_id) FILTER (WHERE cs.status IN ('sent', 'completed', 'failed')),
                       COUNT(DISTINCT r.user_id) FILTER (WHERE r.completed_at IS NOT NULL),
                       COUNT(DISTINCT cs.user_id) FILTER (WHERE cs.status='failed'),
                       COUNT(DISTINCT cs.user_id) FILTER (WHERE cs.status LIKE 'skipped%'),
                       AVG(a.rating)
                FROM customer_satisfaction_surveys s
                LEFT JOIN customer_satisfaction_sent cs ON cs.survey_id=s.id
                LEFT JOIN customer_satisfaction_responses r ON r.survey_id=s.id
                LEFT JOIN customer_satisfaction_answers a ON a.response_id=r.id AND a.rating IS NOT NULL
                WHERE s.id=%s
            """, (survey_id,))
            aggregate = cur.fetchone() or (0, 0, 0, 0, None)

            cur.execute("""
                SELECT question_text
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL
                AND COALESCE(is_active, TRUE)=TRUE
                ORDER BY sort_order ASC, id ASC
                LIMIT 12
            """)
            questions = [row[0] for row in cur.fetchall() if row and len(row) > 0]
    except Exception as e:
        try:
            log_event(
                "satisfaction_detail_load_failed",
                category="satisfaction",
                severity="warning",
                group_id=safe_satisfaction_value(header, 2),
                message="No se pudo cargar el detalle agregado de encuesta.",
                metadata={
                    "callback": "satisfaction_survey",
                    "survey_id": survey_id,
                    "error": str(e)[:250]
                }
            )
        except Exception:
            pass

        aggregate = (0, 0, 0, 0, None)
        questions = []

    sent_count = safe_satisfaction_value(aggregate, 0, 0) or 0
    completed_count = safe_satisfaction_value(aggregate, 1, 0) or 0
    failed_count = safe_satisfaction_value(aggregate, 2, 0) or 0
    skipped_count = safe_satisfaction_value(aggregate, 3, 0) or 0
    average_rating = safe_satisfaction_value(aggregate, 4)
    survey_id = safe_satisfaction_value(header, 0)
    title = safe_satisfaction_value(header, 1, "Encuesta")
    group_id = safe_satisfaction_value(header, 2)
    group_name = safe_satisfaction_value(header, 3, "Global")
    campaign_id = safe_satisfaction_value(header, 4, "default")
    status = safe_satisfaction_value(header, 5, "draft")
    created_at = safe_satisfaction_value(header, 6)
    sent_at = safe_satisfaction_value(header, 7)
    pending_count = max((sent_count or 0) - (completed_count or 0) - (failed_count or 0), 0)
    response_rate = round(((completed_count or 0) / sent_count) * 100, 1) if sent_count else 0
    average_text = f"{round(float(average_rating), 2)}/5" if average_rating else "Sin datos"
    question_text = "\n".join(f"- {question}" for question in questions) or "Sin preguntas activas."

    return (
        f"📝 Encuesta #{survey_id}\n\n"
        f"Título: {title}\n"
        f"Comunidad: {group_name} ({group_id or 'global'})\n"
        f"Campaña: {campaign_id}\n"
        f"Estado: {status}\n"
        f"Creada: {format_tracking_time(created_at)}\n"
        f"Enviada: {format_tracking_time(sent_at)}\n\n"
        f"Enviados: {sent_count or 0}\n"
        f"Respondidos: {completed_count or 0}\n"
        f"Pendientes: {pending_count}\n"
        f"Fallidos: {failed_count or 0}\n"
        f"Omitidos: {skipped_count or 0}\n"
        f"Tasa respuesta: {response_rate}%\n"
        f"Media: {average_text}\n\n"
        "Preguntas:\n"
        f"{question_text}"
    )


def build_satisfaction_survey_detail_keyboard(survey_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Respondieron", callback_data=f"satisfaction_survey_users_{survey_id}_completed")],
        [InlineKeyboardButton("⏳ Pendientes", callback_data=f"satisfaction_survey_users_{survey_id}_pending")],
        [InlineKeyboardButton("❌ Fallidos/omitidos", callback_data=f"satisfaction_survey_users_{survey_id}_failed")],
        [InlineKeyboardButton("📊 Resumen respuestas", callback_data=f"satisfaction_survey_summary_{survey_id}")],
        [InlineKeyboardButton("⬅️ Volver a encuestas", callback_data="satisfaction_detail")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def fetch_satisfaction_survey_users(survey_id, status):

    if status == "completed":
        status_filter = "r.completed_at IS NOT NULL"
    elif status == "pending":
        status_filter = "cs.status='sent' AND r.completed_at IS NULL"
    else:
        status_filter = "(cs.status='failed' OR cs.status LIKE 'skipped%')"

    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT cs.user_id,
                       COALESCE(MAX(u.username), MAX(e.username), ''),
                       COALESCE(MAX(u.first_name), MAX(e.first_name), ''),
                       COALESCE(MAX(cs.status), 'sent'),
                       MIN(cs.sent_at),
                       MAX(r.completed_at),
                       MAX(r.id)
                FROM customer_satisfaction_sent cs
                LEFT JOIN customer_satisfaction_responses r ON r.survey_id=cs.survey_id AND r.user_id=cs.user_id
                LEFT JOIN users u ON u.user_id=cs.user_id AND (cs.group_id IS NULL OR u.group_id=cs.group_id)
                LEFT JOIN bot_user_events e ON e.user_id=cs.user_id
                WHERE cs.survey_id=%s
                AND {status_filter}
                GROUP BY cs.user_id
                ORDER BY MAX(COALESCE(r.completed_at, cs.sent_at, cs.created_at)) DESC NULLS LAST
                LIMIT 20
            """, (survey_id,))
            return cur.fetchall()
    except Exception as e:
        try:
            log_event(
                "satisfaction_detail_load_failed",
                category="satisfaction",
                severity="warning",
                message="No se pudo cargar usuarios de encuesta.",
                metadata={
                    "callback": "satisfaction_survey_users",
                    "survey_id": survey_id,
                    "status": status,
                    "error": str(e)[:250]
                }
            )
        except Exception:
            pass

        return []


def build_satisfaction_survey_users_text(survey_id, status):

    label = {
        "completed": "✅ Usuarios que respondieron",
        "pending": "⏳ Usuarios pendientes",
        "failed": "❌ Fallidos u omitidos"
    }.get(status, "Usuarios")
    rows = fetch_satisfaction_survey_users(survey_id, status)

    if not rows:
        return f"{label}\n\nNo hay usuarios en este estado."

    lines = [label, ""]

    for row in rows:
        if len(row) < 7:
            log_satisfaction_detail_row_issue(
                "satisfaction_survey_users",
                user_id=safe_satisfaction_value(row, 0),
                screen=f"survey_users_{status}",
                row=row,
                expected_columns=7
            )

        user_id = safe_satisfaction_value(row, 0)
        username = safe_satisfaction_value(row, 1, "")
        first_name = safe_satisfaction_value(row, 2, "")
        sent_status = safe_satisfaction_value(row, 3, "sent")
        sent_at = safe_satisfaction_value(row, 4)
        completed_at = safe_satisfaction_value(row, 5)
        user_label = f"@{username}" if username else (first_name or "Sin nombre")
        lines.append(
            f"- {user_label} · ID {user_id}\n"
            f"  Estado: {sent_status} · Enviada: {format_tracking_time(sent_at)} · Respondida: {format_tracking_time(completed_at)}"
        )

    return "\n".join(lines)


def build_satisfaction_survey_users_keyboard(survey_id, status):

    rows = fetch_satisfaction_survey_users(survey_id, status)
    keyboard = []

    for row in rows[:12]:
        if len(row) < 7:
            log_satisfaction_detail_row_issue(
                "satisfaction_survey_users",
                user_id=safe_satisfaction_value(row, 0),
                screen=f"survey_users_keyboard_{status}",
                row=row,
                expected_columns=7
            )

        user_id = safe_satisfaction_value(row, 0)
        username = safe_satisfaction_value(row, 1, "")
        first_name = safe_satisfaction_value(row, 2, "")
        response_id = safe_satisfaction_value(row, 6)

        if not response_id:
            continue

        label = f"👤 @{username}" if username else f"👤 {first_name or user_id}"
        keyboard.append([InlineKeyboardButton(label[:45], callback_data=f"satisfaction_response_{response_id}")])

    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=f"satisfaction_survey_{survey_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def build_satisfaction_response_detail_text(response_id):

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id,
                       r.survey_id,
                       r.user_id,
                       COALESCE(MAX(u.username), MAX(e.username), ''),
                       COALESCE(MAX(u.first_name), MAX(e.first_name), ''),
                       COALESCE(MAX(e.last_name), ''),
                       s.group_id,
                       COALESCE(g.name, 'Global'),
                       MIN(cs.sent_at),
                       r.completed_at
                FROM customer_satisfaction_responses r
                JOIN customer_satisfaction_surveys s ON s.id=r.survey_id
                LEFT JOIN groups g ON g.id=s.group_id
                LEFT JOIN customer_satisfaction_sent cs ON cs.survey_id=r.survey_id AND cs.user_id=r.user_id
                LEFT JOIN users u ON u.user_id=r.user_id AND (s.group_id IS NULL OR u.group_id=s.group_id)
                LEFT JOIN bot_user_events e ON e.user_id=r.user_id
                WHERE r.id=%s
                GROUP BY r.id, r.survey_id, r.user_id, s.group_id, g.name, r.completed_at
                LIMIT 1
            """, (response_id,))
            header = cur.fetchone()

            if not header:
                return "❌ Respuesta no encontrada."

            cur.execute("""
                SELECT q.sort_order,
                       q.question_text,
                       a.rating,
                       a.text_answer
                FROM customer_satisfaction_answers a
                JOIN customer_satisfaction_questions q ON q.id=a.question_id
                WHERE a.response_id=%s
                ORDER BY q.sort_order ASC, q.id ASC
            """, (response_id,))
            answers = cur.fetchall()
    except Exception as e:
        try:
            log_event(
                "satisfaction_detail_load_failed",
                category="satisfaction",
                severity="warning",
                message="No se pudo cargar detalle de respuesta de encuesta.",
                metadata={
                    "callback": "satisfaction_response",
                    "response_id": response_id,
                    "error": str(e)[:250]
                }
            )
        except Exception:
            pass

        return "⚠️ No he podido cargar esta respuesta. Vuelve a intentarlo o pulsa Inicio."

    if len(header) < 10:
        log_satisfaction_detail_row_issue(
            "satisfaction_response",
            user_id=safe_satisfaction_value(header, 2),
            group_id=safe_satisfaction_value(header, 6),
            screen="response_header",
            row=header,
            expected_columns=10
        )
        return "⚠️ No he podido cargar esta respuesta. Vuelve a intentarlo o pulsa Inicio."

    survey_id = safe_satisfaction_value(header, 1)
    user_id = safe_satisfaction_value(header, 2)
    username = safe_satisfaction_value(header, 3, "")
    first_name = safe_satisfaction_value(header, 4, "")
    last_name = safe_satisfaction_value(header, 5, "")
    group_id = safe_satisfaction_value(header, 6)
    group_name = safe_satisfaction_value(header, 7, "Global")
    sent_at = safe_satisfaction_value(header, 8)
    completed_at = safe_satisfaction_value(header, 9)
    name_text = " ".join(part for part in (first_name, last_name) if part).strip() or "Sin nombre disponible"
    username_text = f"@{username}" if username else "Sin username"
    answer_lines = []

    for row in answers:
        sort_order = safe_satisfaction_value(row, 0, "-")
        question_text = safe_satisfaction_value(row, 1, "Pregunta")
        rating = safe_satisfaction_value(row, 2)
        text_answer = safe_satisfaction_value(row, 3)
        answer = rating if rating is not None else (text_answer or "-")
        answer_lines.append(
            f"{sort_order}. {question_text}\nRespuesta: {str(answer)[:500]}"
        )

    return (
        f"👤 {name_text} ({username_text})\n"
        f"ID: {user_id}\n"
        f"Encuesta: #{survey_id}\n"
        f"Comunidad: {group_name} ({group_id or 'global'})\n"
        f"Enviada: {format_tracking_time(sent_at)}\n"
        f"Respondida: {format_tracking_time(completed_at)}\n\n"
        + ("\n\n".join(answer_lines) or "Sin respuestas guardadas.")
    )


def build_satisfaction_summary_answers_text(survey_id):

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT q.question_text,
                       AVG(a.rating),
                       COUNT(*) FILTER (WHERE a.rating=1),
                       COUNT(*) FILTER (WHERE a.rating=2),
                       COUNT(*) FILTER (WHERE a.rating=3),
                       COUNT(*) FILTER (WHERE a.rating=4),
                       COUNT(*) FILTER (WHERE a.rating=5),
                       COUNT(a.rating)
                FROM customer_satisfaction_answers a
                JOIN customer_satisfaction_responses r ON r.id=a.response_id
                JOIN customer_satisfaction_questions q ON q.id=a.question_id
                WHERE r.survey_id=%s
                AND a.rating IS NOT NULL
                GROUP BY q.id, q.question_text, q.sort_order
                ORDER BY q.sort_order ASC, q.id ASC
            """, (survey_id,))
            rating_rows = cur.fetchall()

            cur.execute("""
                SELECT q.question_text,
                       a.text_answer,
                       r.user_id,
                       COALESCE(MAX(u.username), MAX(e.username), '')
                FROM customer_satisfaction_answers a
                JOIN customer_satisfaction_responses r ON r.id=a.response_id
                JOIN customer_satisfaction_questions q ON q.id=a.question_id
                LEFT JOIN users u ON u.user_id=r.user_id
                LEFT JOIN bot_user_events e ON e.user_id=r.user_id
                WHERE r.survey_id=%s
                AND a.text_answer IS NOT NULL
                AND LENGTH(TRIM(a.text_answer)) > 0
                GROUP BY q.question_text, a.text_answer, r.user_id, a.created_at
                ORDER BY a.created_at DESC
                LIMIT 8
            """, (survey_id,))
            text_rows = cur.fetchall()
    except Exception as e:
        try:
            log_event(
                "satisfaction_detail_load_failed",
                category="satisfaction",
                severity="warning",
                message="No se pudo cargar resumen de respuestas.",
                metadata={
                    "callback": "satisfaction_survey_summary",
                    "survey_id": survey_id,
                    "error": str(e)[:250]
                }
            )
        except Exception:
            pass

        rating_rows = []
        text_rows = []

    rating_text = []
    for row in rating_rows:
        question = safe_satisfaction_value(row, 0, "Pregunta")
        avg = safe_satisfaction_value(row, 1)
        one = safe_satisfaction_value(row, 2, 0) or 0
        two = safe_satisfaction_value(row, 3, 0) or 0
        three = safe_satisfaction_value(row, 4, 0) or 0
        four = safe_satisfaction_value(row, 5, 0) or 0
        five = safe_satisfaction_value(row, 6, 0) or 0
        total = safe_satisfaction_value(row, 7, 0) or 0
        positive = round(((four + five) / total) * 100, 1) if total else 0
        average = round(float(avg), 2) if avg is not None else 0
        rating_text.append(
            f"- {question}\n  Media: {average}/5 · Positivo: {positive}% · 1:{one} 2:{two} 3:{three} 4:{four} 5:{five}"
        )

    text_answers = []
    for row in text_rows:
        question = safe_satisfaction_value(row, 0, "Pregunta")
        answer = safe_satisfaction_value(row, 1, "")
        user_id = safe_satisfaction_value(row, 2)
        username = safe_satisfaction_value(row, 3, "")
        user_label = f"@{username}" if username else str(user_id)
        text_answers.append(f"- {question} · {user_label}: {answer[:180]}")

    return (
        f"📊 Resumen de respuestas #{survey_id}\n\n"
        "Preguntas 1-5:\n"
        f"{chr(10).join(rating_text) or 'Sin respuestas numéricas.'}\n\n"
        "Respuestas de texto recientes:\n"
        f"{chr(10).join(text_answers) or 'Sin respuestas de texto.'}"
    )


def get_customer_satisfaction_role(user_id):

    if is_super_admin(user_id):
        return "super_admin"

    try:
        with conn.cursor() as cur:
            cur.execute("""

                SELECT role
                FROM admins
                WHERE user_id=%s
                AND is_active=TRUE
                ORDER BY CASE WHEN role='GROUP_OWNER' THEN 0 ELSE 1 END
                LIMIT 1

            """, (user_id,))
            row = cur.fetchone()
    except Exception:
        row = None

    if row and row[0] == "GROUP_OWNER":
        return "owner"

    if row:
        return "group_admin"

    return "user"


def get_or_create_customer_satisfaction_response(survey_id, user_id):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO customer_satisfaction_responses
            (
                survey_id,
                user_id,
                role,
                started_at
            )
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (survey_id, user_id)
            DO UPDATE SET started_at=COALESCE(customer_satisfaction_responses.started_at, NOW())
            RETURNING id

        """, (
            survey_id,
            user_id,
            get_customer_satisfaction_role(user_id)
        ))

        return cur.fetchone()[0]


def fetch_next_customer_satisfaction_question(response_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT q.id, q.question_text, q.answer_type, q.sort_order
            FROM customer_satisfaction_responses r
            JOIN customer_satisfaction_questions q
            ON q.survey_id IS NULL
            AND COALESCE(q.is_active, TRUE)=TRUE
            WHERE r.id=%s
            AND NOT EXISTS (
                SELECT 1
                FROM customer_satisfaction_answers a
                WHERE a.response_id=r.id
                AND a.question_id=q.id
            )
            ORDER BY q.sort_order ASC, q.id ASC
            LIMIT 1

        """, (response_id,))

        return cur.fetchone()


def save_customer_satisfaction_answer(response_id, question_id, rating=None, text_answer=None):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO customer_satisfaction_answers
            (
                response_id,
                question_id,
                rating,
                text_answer
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (response_id, question_id)
            DO UPDATE SET rating=EXCLUDED.rating,
                          text_answer=EXCLUDED.text_answer

        """, (response_id, question_id, rating, text_answer))


def customer_satisfaction_response_belongs_to_user(response_id, user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM customer_satisfaction_responses
            WHERE id=%s
            AND user_id=%s
            LIMIT 1

        """, (response_id, user_id))

        return cur.fetchone() is not None


def complete_customer_satisfaction_response(response_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE customer_satisfaction_responses
            SET completed_at=NOW()
            WHERE id=%s
            RETURNING survey_id, user_id

        """, (response_id,))
        row = cur.fetchone()

        if not row:
            return

        survey_id, user_id = row

        cur.execute("""

            SELECT group_id, COALESCE(campaign_id, 'default')
            FROM customer_satisfaction_surveys
            WHERE id=%s
            LIMIT 1

        """, (survey_id,))
        survey_row = cur.fetchone()

        if not survey_row:
            return

        group_id, campaign_id = survey_row

        cur.execute("""

            UPDATE customer_satisfaction_sent
            SET status='completed',
                completed_at=NOW(),
                updated_at=NOW()
            WHERE survey_id=%s
            AND COALESCE(group_id, 0)=COALESCE(%s, 0)
            AND user_id=%s
            AND COALESCE(campaign_id, 'default')=%s

        """, (survey_id, group_id, user_id, campaign_id))










async def send_customer_satisfaction_question(context, chat_id, response_id):

    next_question = fetch_next_customer_satisfaction_question(response_id)

    if not next_question:
        complete_customer_satisfaction_response(response_id)
        context.user_data.pop("customer_satisfaction_response_id", None)
        context.user_data.pop("customer_satisfaction_text_question_id", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Gracias por tu opinión."
        )
        record_beta_event(
            "survey_completed",
            severity="info",
            user_id=chat_id,
            message="Encuesta de satisfacción completada."
        )
        log_user_event_by_ids(
            chat_id,
            "survey_completed",
            event_key="customer_satisfaction",
            metadata={"response_id": response_id}
        )
        return

    question_id, question_text, answer_type, sort_order = next_question

    if answer_type == "rating_1_5":
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Pregunta {sort_order}\n\n{question_text}\n\nResponde del 1 al 5.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("1️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_1"),
                InlineKeyboardButton("2️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_2"),
                InlineKeyboardButton("3️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_3"),
                InlineKeyboardButton("4️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_4"),
                InlineKeyboardButton("5️⃣", callback_data=f"satisfaction_rate_{response_id}_{question_id}_5")
            ]])
        )
        return

    context.user_data["customer_satisfaction_response_id"] = response_id
    context.user_data["customer_satisfaction_text_question_id"] = question_id

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Pregunta {sort_order}\n\n{question_text}\n\nResponde con texto."
    )


async def receive_customer_satisfaction_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    edit_question_id = context.user_data.get("customer_satisfaction_admin_edit_question_id")

    if edit_question_id:

        if not is_super_admin(update.effective_user.id):
            context.user_data.pop("customer_satisfaction_admin_edit_question_id", None)
            await update.message.reply_text("⛔ No tienes permisos para editar preguntas.")
            return

        question_text = (update.message.text or "").strip()

        if len(question_text) < 5:
            await update.message.reply_text(
                "⚠️ La pregunta es demasiado corta.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        with conn.cursor() as cur:
            cur.execute("""

                UPDATE customer_satisfaction_questions
                SET question_text=%s
                WHERE id=%s

            """, (question_text, edit_question_id))

        context.user_data.pop("customer_satisfaction_admin_edit_question_id", None)

        await update.message.reply_text(
            "✅ Pregunta actualizada.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    add_question_type = context.user_data.get("customer_satisfaction_admin_add_question")

    if add_question_type:

        if not is_super_admin(update.effective_user.id):
            context.user_data.pop("customer_satisfaction_admin_add_question", None)
            await update.message.reply_text("⛔ No tienes permisos para añadir preguntas.")
            return

        question_text = (update.message.text or "").strip()

        if len(question_text) < 5:
            await update.message.reply_text(
                "⚠️ La pregunta es demasiado corta.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        with conn.cursor() as cur:
            cur.execute("""

                SELECT COALESCE(MAX(sort_order), 0) + 1
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL

            """)
            sort_order = cur.fetchone()[0] or 1

            cur.execute("""

                INSERT INTO customer_satisfaction_questions
                (
                    survey_id,
                    question_key,
                    question_text,
                    category,
                    answer_type,
                    is_active,
                    sort_order
                )
                VALUES (NULL, %s, %s, 'custom', %s, TRUE, %s)

            """, (
                f"custom_{int(time.time())}",
                question_text,
                add_question_type,
                sort_order
            ))

        context.user_data.pop("customer_satisfaction_admin_add_question", None)

        await update.message.reply_text(
            "✅ Pregunta añadida.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    response_id = context.user_data.get("customer_satisfaction_response_id")
    question_id = context.user_data.get("customer_satisfaction_text_question_id")

    if not response_id or not question_id:
        await update.message.reply_text("No estaba esperando una respuesta de encuesta.")
        return

    if not customer_satisfaction_response_belongs_to_user(
        response_id,
        update.effective_user.id
    ):

        context.user_data.pop("customer_satisfaction_response_id", None)
        context.user_data.pop("customer_satisfaction_text_question_id", None)
        await update.message.reply_text("⛔ No puedes responder esta encuesta.")
        return

    save_customer_satisfaction_answer(
        response_id,
        question_id,
        text_answer=(update.message.text or "").strip()[:2000]
    )

    context.user_data.pop("customer_satisfaction_text_question_id", None)
    await send_customer_satisfaction_question(
        context,
        update.effective_chat.id,
        response_id
    )


async def receive_user_tracking_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    if not is_super_admin(update.effective_user.id):
        context.user_data.pop("admin_user_tracking_search", None)
        await update.message.reply_text("⛔ Solo el superadmin puede usar seguimiento de usuarios.")
        return

    search_text = update.message.text.strip()
    context.user_data.pop("admin_user_tracking_search", None)
    profile_data = fetch_user_activity_profile(search_text)

    await update.message.reply_text(
        build_user_tracking_user_profile_text(profile_data),
        reply_markup=build_user_tracking_panel_keyboard()
    )


def build_admin_panel_keyboard(user_id):

    if is_super_admin(user_id):

        # Menú principal ÚNICO: el mismo que muestra /admin (catálogo), para
        # que "Volver" e "Inicio" no aterricen en un panel distinto del de
        # entrada. Antes había dos menús principales incompatibles.
        rows = [
            [
                InlineKeyboardButton(
                    spec["text"],
                    callback_data=spec["callback_data"]
                )
                for spec in row
            ]
            for row in build_admin_menu_button_rows(is_super_admin=True)
        ]

        rows.append(
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        )

        return rows


    if user_has_group_owner_role(user_id):

        return [
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ]


    if has_any_admin_permission(user_id):

        return [
            [InlineKeyboardButton("👮 Panel admin de grupo", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ]


    return []






def format_beta_cycle_row(row):

    if not row:

        return "Sin ciclo beta registrado."


    (
        cycle_id,
        name,
        status,
        phase,
        starts_at,
        ends_at,
        created_by,
        completed_at,
        notes
    ) = row

    return (
        f"#{cycle_id} · {name or '-'}\n"
        f"Estado: {status or '-'}\n"
        f"Fase: {phase or '-'}\n"
        f"Inicio: {starts_at or '-'}\n"
        f"Fin previsto: {ends_at or '-'}\n"
        f"Creado por: {created_by or '-'}\n"
        f"Completado: {completed_at or '-'}\n"
        f"Notas: {notes or '-'}"
    )






def build_beta_smoke_test_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Ejecutar checks automáticos", callback_data="admin_smoke_run")],
        [InlineKeyboardButton("📋 Checklist manual", callback_data="admin_smoke_manual")],
        [InlineKeyboardButton("📊 Último resultado", callback_data="admin_smoke_last")],
        [InlineKeyboardButton("🧹 Limpiar resultados", callback_data="admin_smoke_clear")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def add_smoke_check(report, name, status, detail):

    report.append({
        "name": name,
        "status": status,
        "detail": str(detail or "")
    })


def smoke_status_icon(status):

    if status == "ok":

        return "✅"

    if status == "fail":

        return "❌"

    if status == "manual":

        return "🧪"

    return "⚠️"


def read_project_file(path):

    try:

        with open(path, "r", encoding="utf-8") as file:

            return file.read()

    except Exception:

        return ""


def table_exists(table_name):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='public'
                AND table_name=%s
            )

        """, (table_name,))

        return cur.fetchone()[0] is True


def column_exists(table_name, column_name):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='public'
                AND table_name=%s
                AND column_name=%s
            )

        """, (table_name, column_name))

        return cur.fetchone()[0] is True


def count_table_rows(query):

    with conn.cursor() as cur:

        cur.execute(query)

        row = cur.fetchone()

        return row[0] if row else 0


def run_beta_smoke_checks():

    report = []

    project_files = {
        "main.py": read_project_file("main.py"),
        "callback_router.py": read_project_file("callback_router.py"),
        "stripe_handler.py": read_project_file("stripe_handler.py"),
        "invite_link_service.py": read_project_file("invite_link_service.py")
    }

    try:

        with conn.cursor() as cur:

            cur.execute("SELECT 1")

            result = cur.fetchone()

        add_smoke_check(
            report,
            "DB responde",
            "ok" if result and result[0] == 1 else "fail",
            "SELECT 1 ejecutado"
        )

    except Exception as e:

        add_smoke_check(report, "DB responde", "fail", e)


    critical_tables = [
        "groups",
        "users",
        "admins",
        "plans",
        "payments",
        "invite_links",
        "audit_logs",
        "beta_monitor_events",
        "beta_smoke_test_runs",
        "beta_cycles",
        "group_user_promo_codes",
        "group_backup_configs",
        "support_tickets"
    ]

    for table_name in critical_tables:

        try:

            add_smoke_check(
                report,
                f"Tabla {table_name}",
                "ok" if table_exists(table_name) else "fail",
                "Existe" if table_exists(table_name) else "No existe"
            )

        except Exception as e:

            add_smoke_check(report, f"Tabla {table_name}", "fail", e)


    try:

        add_smoke_check(
            report,
            "invite_links.telegram_group_id",
            "ok" if column_exists("invite_links", "telegram_group_id") else "fail",
            "Columna disponible para validar con ID real de Telegram"
        )

    except Exception as e:

        add_smoke_check(report, "invite_links.telegram_group_id", "fail", e)


    main_source = project_files["main.py"]
    router_source = project_files["callback_router.py"]
    stripe_source = project_files["stripe_handler.py"]
    invite_source = project_files["invite_link_service.py"]
    unsafe_split_pattern = "int(" + "data.split"
    legacy_group_pattern = "int(" + 'data.split("_")[1])'

    static_checks = [
        (
            "Global error handler registrado",
            "add_error_handler" in main_source and "global_error_handler" in main_source,
            "main.py contiene add_error_handler/global_error_handler"
        ),
        (
            "Scheduler beta registrado",
            "schedule_beta_monitor_job(telegram_app)" in main_source,
            "JobQueue beta conectado en arranque"
        ),
        (
            "Callbacks críticos presentes",
            all(
                callback_name in router_source
                for callback_name in [
                    "admin_beta_monitor",
                    "admin_smoke_test",
                    "admin_group_user_codes",
                    "group_user_code_create",
                    "group_user_promo_redeem_start",
                    "free_access_",
                    "marketplace_group_",
                    "owner_backup_panel"
                ]
            ),
            "Router contiene los callbacks críticos de beta"
        ),
        (
            "group_user_code no colisiona con group_{id}",
            "is_numeric_group_callback" in router_source
            and legacy_group_pattern not in router_source,
            "El handler group_{id} valida prefijo numérico"
        ),
        (
            "Sin parseo split directo peligroso",
            unsafe_split_pattern not in router_source,
            "No hay conversión directa insegura de callback"
        ),
        (
            "BETA_MONITOR_ENABLED leído",
            "BETA_MONITOR_ENABLED" in read_project_file("audit_log_service.py"),
            "Monitor beta usa variable de entorno"
        ),
        (
            "Sin invite links completos en logs conocidos",
            "Respuesta createChatInviteLink" not in stripe_source
            and "Respuesta createChatInviteLink" not in invite_source,
            "No aparece el log antiguo con link completo"
        )
    ]

    for name, passed, detail in static_checks:

        add_smoke_check(
            report,
            name,
            "ok" if passed else "fail",
            detail
        )


    env_checks = [
        ("TOKEN presente", "TOKEN", True),
        ("STRIPE_SECRET_KEY presente", "STRIPE_SECRET_KEY", True),
        ("STRIPE_WEBHOOK_SECRET presente", "STRIPE_WEBHOOK_SECRET", True),
        ("SERVER_URL/WEBHOOK_URL presente", "SERVER_URL", True)
    ]

    for name, env_name, required in env_checks:

        value = os.environ.get(env_name)

        if env_name == "SERVER_URL":

            value = os.environ.get("SERVER_URL") or os.environ.get("WEBHOOK_URL")

        if value:

            add_smoke_check(report, name, "ok", "Configurado sin mostrar valor")

        else:

            add_smoke_check(
                report,
                name,
                "fail" if required else "warning",
                "No configurado"
            )


    data_checks = [
        ("Grupos activos cargables", "SELECT COUNT(*) FROM groups WHERE is_active=TRUE"),
        ("Owners/admins cargables", "SELECT COUNT(*) FROM admins WHERE is_active=TRUE"),
        ("Planes activos cargables", "SELECT COUNT(*) FROM plans WHERE is_active=TRUE"),
        ("Códigos por grupo activos cargables", "SELECT COUNT(*) FROM group_user_promo_codes WHERE is_active=TRUE"),
        ("Backups configurados cargables", "SELECT COUNT(*) FROM group_backup_configs")
    ]

    for name, query in data_checks:

        try:

            total = count_table_rows(query)

            add_smoke_check(
                report,
                name,
                "ok" if total > 0 else "warning",
                f"Registros encontrados: {total}"
            )

        except Exception as e:

            add_smoke_check(report, name, "fail", e)


    add_smoke_check(
        report,
        "Checks Telegram seguros",
        "manual",
        (
            "Pendiente de prueba real: getChat, getChatMember(bot), "
            "invite link revocable y revocación requieren elegir un grupo y confirmar."
        )
    )

    return report


def summarize_smoke_report(report):

    total_checks = len(report)
    passed_checks = len([item for item in report if item.get("status") == "ok"])
    failed_checks = len([item for item in report if item.get("status") == "fail"])
    warning_checks = len([
        item
        for item in report
        if item.get("status") in ("warning", "manual")
    ])

    return total_checks, passed_checks, failed_checks, warning_checks


def save_beta_smoke_run(started_by, report):

    total_checks, passed_checks, failed_checks, warning_checks = summarize_smoke_report(report)
    status = "failed" if failed_checks else "completed"

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO beta_smoke_test_runs
            (
                started_by,
                status,
                total_checks,
                passed_checks,
                failed_checks,
                warning_checks,
                report
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id, created_at

        """, (
            started_by,
            status,
            total_checks,
            passed_checks,
            failed_checks,
            warning_checks,
            json.dumps(report, ensure_ascii=False, default=str)
        ))

        run_id, created_at = cur.fetchone()
        conn.commit()

    return {
        "id": run_id,
        "created_at": created_at,
        "status": status,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "warning_checks": warning_checks,
        "report": report
    }


def get_last_beta_smoke_run():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   created_at,
                   status,
                   total_checks,
                   passed_checks,
                   failed_checks,
                   warning_checks,
                   report
            FROM beta_smoke_test_runs
            ORDER BY created_at DESC
            LIMIT 1

        """)

        row = cur.fetchone()

    if not row:

        return None

    report = row[7] or []

    return {
        "id": row[0],
        "created_at": row[1],
        "status": row[2],
        "total_checks": row[3],
        "passed_checks": row[4],
        "failed_checks": row[5],
        "warning_checks": row[6],
        "report": report
    }


def clear_beta_smoke_runs():

    with conn.cursor() as cur:

        cur.execute("DELETE FROM beta_smoke_test_runs")
        affected = cur.rowcount
        conn.commit()

    return affected


def format_beta_smoke_report(run):

    if not run:

        return "🧪 Smoke Test Beta\n\nTodavía no hay resultados guardados."


    lines = [
        "🧪 Smoke Test Beta",
        "",
        f"Ejecución: #{run['id']}",
        f"Fecha: {run['created_at']}",
        f"Estado: {run['status']}",
        "",
        f"✅ OK: {run['passed_checks']}",
        f"⚠️ Warnings/manuales: {run['warning_checks']}",
        f"❌ Fallos: {run['failed_checks']}",
        f"Total: {run['total_checks']}",
        ""
    ]


    for item in run.get("report", [])[:30]:

        lines.append(
            f"{smoke_status_icon(item.get('status'))} {item.get('name')}"
        )

        detail = item.get("detail")

        if detail:

            lines.append(f"   {detail}")


    return "\n".join(lines)[:3900]


def format_beta_smoke_manual_checklist():

    return (
        "📋 Checklist manual beta\n\n"
        "🧪 Ejecutar con cuentas/grupos reales antes de abrir la beta:\n\n"
        "1. Pago Stripe test/real y webhook confirmado.\n"
        "2. Entrada de usuario externo con link de pago.\n"
        "3. Acceso gratis con link único.\n"
        "4. Canje de código por grupo.\n"
        "5. Verificación request_location desde móvil.\n"
        "6. Backup texto, foto y vídeo con captions.\n"
        "7. Flujo con GroupAnonymousBot.\n"
        "8. Ticket soporte usuario/admin.\n"
        "9. Bot añadido a grupo por creator aprobado.\n"
        "10. Fallback de callback inválido con mensaje amable.\n\n"
        "Estos pasos no se ejecutan automáticamente para no crear pagos reales "
        "ni modificar grupos sin confirmación."
    )


def user_has_group_permission_any(user_id, group_id, permissions):

    if is_super_admin(user_id):

        return True


    return any(
        has_permission(user_id, group_id, permission)
        for permission in permissions
    )




GROUP_ADMIN_PERMISSION_BY_KEY = {
    key: permission
    for key, _label, permission in GROUP_ADMIN_PERMISSION_OPTIONS
}


def can_manage_group_admins(user_id, group_id):

    return has_group_permission(
        user_id,
        group_id,
        "can_manage_admins"
    )


def user_is_group_owner(user_id, group_id):

    if is_super_admin(user_id):

        return True


    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM admins
            WHERE user_id=%s
            AND group_id=%s
            AND role='GROUP_OWNER'
            AND is_active=TRUE
            LIMIT 1

        """, (
            user_id,
            group_id
        ))

        return cur.fetchone() is not None






















def generate_backup_destination_token():

    alphabet = string.ascii_uppercase + string.digits

    return "BACKUP-" + "".join(
        secrets.choice(alphabet)
        for _ in range(5)
    )








def generate_group_user_promo_code():

    alphabet = string.ascii_uppercase + string.digits

    return "G-" + "".join(
        secrets.choice(alphabet)
        for _ in range(10)
    )


def normalize_group_user_promo_code(raw_code):

    return (raw_code or "").strip().upper()


def is_valid_group_user_promo_code(raw_code):

    code = normalize_group_user_promo_code(raw_code)


    if not 4 <= len(code) <= 32:

        return False


    return all(
        char in string.ascii_uppercase + string.digits + "-_"
        for char in code
    )


def fetch_group_basic_info(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   name,
                   telegram_group_id,
                   COALESCE(community_type, 'group')
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,))

        return cur.fetchone()


def build_group_user_codes_error_keyboard(group_id=None):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=build_group_user_code_callback("group_user_codes_panel", group_id)
        )],
        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]
    ])


def set_group_user_promo_context(context, group_id, step=None):

    group = fetch_group_basic_info(group_id)


    if not group:

        return None


    resolved_group_id, _group_name, telegram_group_id, *_ = group
    owner_user_id = get_group_owner_user_id(resolved_group_id)

    context.user_data["selected_group_admin"] = resolved_group_id
    context.user_data["selected_group_user_codes"] = resolved_group_id
    context.user_data["selected_group_id"] = resolved_group_id
    context.user_data["group_user_promo_group_id"] = resolved_group_id
    context.user_data["group_user_promo_telegram_group_id"] = telegram_group_id
    context.user_data["group_user_promo_owner_user_id"] = owner_user_id


    if step:

        context.user_data["group_user_promo_step"] = step


    return group


def clear_group_user_promo_wizard(context, keep_group=True):

    keys = (
        "group_user_promo_duration_days",
        "group_user_promo_is_permanent",
        "group_user_promo_max_uses",
        "group_user_promo_waiting",
        "group_user_promo_step",
        "group_user_promo_pending_code_id"
    )


    for key in keys:

        context.user_data.pop(key, None)


    if not keep_group:

        for key in (
            "selected_group_user_codes",
            "group_user_promo_group_id",
            "group_user_promo_telegram_group_id",
            "group_user_promo_owner_user_id"
        ):

            context.user_data.pop(key, None)






def format_group_user_promo_duration(duration_days, is_permanent):

    if is_permanent:

        return "permanente"


    return f"{duration_days} día(s)"




def build_group_user_code_callback(callback_data, group_id=None):

    if group_id:

        return f"{callback_data}_{group_id}"


    return callback_data


def build_group_user_codes_keyboard(group_id=None):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Crear código", callback_data=build_group_user_code_callback("group_user_code_create", group_id))],
        [InlineKeyboardButton("📋 Ver códigos activos", callback_data=build_group_user_code_callback("group_user_codes_active", group_id))],
        [InlineKeyboardButton("🚫 Desactivar código", callback_data=build_group_user_code_callback("group_user_code_deactivate_menu", group_id))],
        [InlineKeyboardButton("📊 Usos de códigos", callback_data=build_group_user_code_callback("group_user_code_usage", group_id))],
        [InlineKeyboardButton("⬅️ Volver", callback_data="edit_group_back")]
    ])




def build_group_user_code_uses_keyboard(group_id=None):

    suffix = f"_{group_id}" if group_id else ""

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 uso", callback_data=f"group_user_code_uses{suffix}_1")],
        [InlineKeyboardButton("5 usos", callback_data=f"group_user_code_uses{suffix}_5")],
        [InlineKeyboardButton("10 usos", callback_data=f"group_user_code_uses{suffix}_10")],
        [InlineKeyboardButton("Ilimitado", callback_data=f"group_user_code_uses{suffix}_0")],
        [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_code_create", group_id))]
    ])






def create_group_user_promo_code(
    group_id,
    owner_user_id,
    duration_days,
    is_permanent,
    max_uses,
    code=None
):

    group = fetch_group_basic_info(group_id)


    if not group:

        return None


    _group_id, _group_name, telegram_group_id, *_ = group
    group_owner_user_id = get_group_owner_user_id(group_id) or owner_user_id


    if is_permanent:

        duration_days = None

    elif not duration_days or not 1 <= int(duration_days) <= 3650:

        raise ValueError("invalid_duration")


    if max_uses != 0 and max_uses < 1:

        raise ValueError("invalid_max_uses")


    for _attempt in range(8):

        candidate = normalize_group_user_promo_code(
            code or generate_group_user_promo_code()
        )


        if not is_valid_group_user_promo_code(candidate):

            raise ValueError("invalid_code")


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO group_user_promo_codes
                    (
                        group_id,
                        telegram_group_id,
                        owner_user_id,
                        code,
                        duration_days,
                        is_permanent,
                        max_uses,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                    RETURNING id,
                              code,
                              duration_days,
                              is_permanent,
                              max_uses

                """, (
                    group_id,
                    telegram_group_id,
                    group_owner_user_id,
                    candidate,
                    duration_days,
                    is_permanent,
                    max_uses
                ))

                row = cur.fetchone()
                conn.commit()

                return row

        except Exception as e:

            conn.rollback()


            if code:

                raise


            print("Reintentando código de grupo duplicado:", e)


    return None


def fetch_group_user_promo_by_code(code):

    normalized_code = normalize_group_user_promo_code(code)


    with conn.cursor() as cur:

        cur.execute("""

            SELECT c.id,
                   c.group_id,
                   c.telegram_group_id,
                   c.owner_user_id,
                   c.code,
                   c.duration_days,
                   c.is_permanent,
                   c.max_uses,
                   c.used_count,
                   c.is_active,
                   c.expires_at,
                   g.name,
                   COALESCE(g.community_type, 'group'),
                   COALESCE(g.is_active, TRUE)
            FROM group_user_promo_codes c
            JOIN groups g
            ON g.id = c.group_id
            WHERE c.code=%s
            LIMIT 1

        """, (normalized_code,))

        return cur.fetchone()


def validate_group_user_promo_row(row):

    if not row:

        return False, "❌ Código de acceso no encontrado."


    (
        _code_id,
        _group_id,
        _telegram_group_id,
        _owner_user_id,
        _code,
        _duration_days,
        _is_permanent,
        max_uses,
        used_count,
        is_active,
        expires_at,
        _group_name,
        _community_type,
        group_is_active
    ) = row


    if group_is_active is not True:

        return False, "❌ Esta comunidad no está disponible."


    if is_active is not True:

        return False, "❌ Este código ya no está activo."


    if expires_at and expires_at <= datetime.now():

        return False, "❌ Este código ha caducado."


    if max_uses != 0 and used_count >= max_uses:

        return False, "❌ Este código ya alcanzó el máximo de usos."


    return True, None




async def receive_group_user_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):

    waiting = context.user_data.get("group_user_promo_waiting")


    if waiting == "custom_duration":

        raw_duration = (update.message.text or "").strip()
        group_id = context.user_data.get("group_user_promo_group_id")


        if not raw_duration.isdigit() or not 1 <= int(raw_duration) <= 3650:

            await update.message.reply_text(
                "⚠️ El dato no parece válido. Revisa el formato y vuelve a intentarlo.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        context.user_data["group_user_promo_duration_days"] = int(raw_duration)
        context.user_data["group_user_promo_is_permanent"] = False
        context.user_data["group_user_promo_waiting"] = None

        await update.message.reply_text(
            "Elige cuántos usos tendrá el código.",
            reply_markup=build_group_user_code_uses_keyboard(group_id)
        )

        return


    if waiting == "manual_code":

        manual_code = normalize_group_user_promo_code(update.message.text)
        group_id = context.user_data.get("group_user_promo_group_id")
        duration_days = context.user_data.get("group_user_promo_duration_days")
        is_permanent = context.user_data.get("group_user_promo_is_permanent") is True
        max_uses = context.user_data.get("group_user_promo_max_uses")


        if not is_valid_group_user_promo_code(manual_code):

            await update.message.reply_text(
                "⚠️ El dato no parece válido. Revisa el formato y vuelve a intentarlo.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        if not group_id or max_uses is None:

            await update.message.reply_text(
                "❌ No hay configuración de código pendiente.",
                reply_markup=build_group_user_codes_error_keyboard()
            )
            context.user_data.pop("group_user_promo_waiting", None)

            return


        if not user_has_group_permission_any(
            update.effective_user.id,
            group_id,
            ["can_manage_codes"]
        ):

            await update.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )
            context.user_data.pop("group_user_promo_waiting", None)

            return


        try:

            row = create_group_user_promo_code(
                group_id,
                update.effective_user.id,
                duration_days,
                is_permanent,
                max_uses,
                code=manual_code
            )

        except Exception as e:

            print("Error creando código manual de grupo:", e)

            await update.message.reply_text(
                "❌ No pude crear el código. Revisa que no esté repetido.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        clear_group_user_promo_wizard(context, keep_group=True)

        await update.message.reply_text(
            "✅ Código creado\n\n"
            f"Código: {row[1]}\n"
            f"Duración: {format_group_user_promo_duration(row[2], row[3])}\n"
            f"Usos máximos: {'ilimitado' if row[4] == 0 else row[4]}",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if waiting == "redeem_code":

        promo_row = fetch_group_user_promo_by_code(update.message.text)
        valid, error_message = validate_group_user_promo_row(promo_row)
        selected_group_id = context.user_data.get("group_user_promo_redeem_group_id")


        if valid and selected_group_id and int(promo_row[1]) != int(selected_group_id):

            valid = False
            error_message = "❌ Este código no pertenece a esta comunidad."


        if not valid:

            context.user_data.pop("group_user_promo_waiting", None)

            log_event(
                "group_code_failed",
                category="access",
                severity="warning",
                scope="global",
                actor_user_id=update.effective_user.id,
                target_user_id=update.effective_user.id,
                message="Intento fallido de canje de código de grupo.",
                metadata={
                    "reason": error_message
                }
            )

            await update.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🎟 Canjear código de esta comunidad",
                        callback_data=f"group_user_promo_redeem_start_{selected_group_id}"
                        if selected_group_id
                        else "start_explore_groups"
                    )],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        context.user_data["group_user_promo_waiting"] = None
        context.user_data["group_user_promo_pending_code_id"] = promo_row[0]

        await update.message.reply_text(
            "🎟 Código encontrado\n\n"
            f"Comunidad: {promo_row[11] or promo_row[1]}\n"
            f"Duración: {format_group_user_promo_duration(promo_row[5], promo_row[6])}\n\n"
            "Confirma para generar tu enlace personal de acceso.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Canjear acceso", callback_data=f"group_user_promo_confirm_{promo_row[0]}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    await update.message.reply_text(
        "No estaba esperando ese dato. Usa los botones del menú para continuar.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])
    )


async def receive_owner_payment_provider_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if context.user_data.get("configuring_platform_payment_provider"):

        provider = context.user_data.get("platform_payment_provider")
        step = context.user_data.get("platform_payment_step")
        payload = context.user_data.get("platform_payment_payload") or {}
        user_id = update.effective_user.id if update.effective_user else None
        chat_id = update.effective_chat.id if update.effective_chat else None
        text = (update.message.text or "").strip() if update.message else ""

        clear_plan_wizard_state(
            context,
            user_id=user_id,
            action="receive_platform_payment_provider_text"
        )


        if provider not in (OWNER_PAYMENT_PROVIDER_CHANGENOW, OWNER_PAYMENT_PROVIDER_GUARDARIAN) or not is_super_admin(user_id):

            clear_owner_payment_provider_wizard(context)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⛔ No tienes permiso para configurar este proveedor de plataforma.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        if text.lower() in ("cancelar", "/cancel", "cancel"):

            clear_owner_payment_provider_wizard(context)
            await delete_sensitive_user_message(update)
            back_callback = "admin_payment_guardarian" if provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN else "admin_payment_changenow"
            back_label = "⬅️ Volver a Guardarian" if provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN else "⬅️ Volver a ChangeNOW"
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ Configuración cancelada. No se ha guardado ningún secreto.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(back_label, callback_data=back_callback)],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if not has_payment_encryption_key():

            clear_owner_payment_provider_wizard(context)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Falta PAYMENT_CONFIG_ENCRYPTION_KEY. No se guardan credenciales sin cifrado.",
                reply_markup=build_admin_payment_providers_keyboard()
            )

            return


        if provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN:

            if step == "api_key":

                await delete_sensitive_user_message(update)

                if not is_valid_paypal_text_value(text, min_length=8):

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ La API key de Guardarian no parece válida. Pégala otra vez o cancela.",
                        reply_markup=build_platform_guardarian_cancel_keyboard()
                    )

                    return


                payload["api_key"] = text
                context.user_data["platform_payment_payload"] = payload
                context.user_data["platform_payment_step"] = "payout_network"

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Indica la red USDT destino. Ejemplos: TRC20, ERC20, Polygon, BEP20.",
                    reply_markup=build_platform_guardarian_cancel_keyboard()
                )

                return


            if step == "payout_network":

                value = text.upper().strip()

                if not value or len(value) > 30:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ Red no válida. Ejemplos: TRC20, ERC20, Polygon, BEP20.",
                        reply_markup=build_platform_guardarian_cancel_keyboard()
                    )

                    return


                payload["payout_network"] = value
                context.user_data["platform_payment_payload"] = payload
                context.user_data["platform_payment_step"] = "payout_wallet"

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Envía la wallet USDT destino de la plataforma. Revísala con cuidado: una red o wallet incorrecta puede perder fondos.",
                    reply_markup=build_platform_guardarian_cancel_keyboard()
                )

                return


            if step == "payout_wallet":

                await delete_sensitive_user_message(update)

                if len(text) < 12 or len(text) > 300 or any(char.isspace() for char in text):

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ La wallet no parece válida. Pégala otra vez o cancela.",
                        reply_markup=build_platform_guardarian_cancel_keyboard()
                    )

                    return


                payload["payout_wallet"] = text
                context.user_data["platform_payment_payload"] = payload
                context.user_data["platform_payment_step"] = "webhook_secret"

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Envía el webhook secret de Guardarian si lo tienes. Si no lo tienes, escribe: saltar",
                    reply_markup=build_platform_guardarian_cancel_keyboard()
                )

                return


            if step == "webhook_secret":

                await delete_sensitive_user_message(update)
                lowered = text.lower()

                if lowered in ("saltar", "skip", "no", "-"):

                    payload["webhook_secret"] = None

                elif is_valid_paypal_text_value(text, min_length=8):

                    payload["webhook_secret"] = text

                else:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ El webhook secret no parece válido. Envíalo otra vez o escribe saltar.",
                        reply_markup=build_platform_guardarian_cancel_keyboard()
                    )

                    return


                context.user_data["platform_payment_payload"] = payload
                context.user_data["platform_payment_step"] = "base_url"

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Envía GUARDARIAN_BASE_URL solo si usas una URL oficial distinta. Si no lo necesitas, escribe: saltar",
                    reply_markup=build_platform_guardarian_cancel_keyboard()
                )

                return


            if step == "base_url":

                await delete_sensitive_user_message(update)
                lowered = text.lower()

                if lowered in ("saltar", "skip", "no", "-"):

                    payload["base_url"] = None

                elif text.startswith("https://") and len(text) <= 300:

                    payload["base_url"] = text.rstrip("/")

                else:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ La URL no parece válida. Debe empezar por https:// o escribe saltar.",
                        reply_markup=build_platform_guardarian_cancel_keyboard()
                    )

                    return


                context.user_data["platform_payment_payload"] = payload
                context.user_data["platform_payment_step"] = "confirm"

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "Revisa la configuración Guardarian plataforma:\n\n"
                        f"{build_guardarian_safe_summary(payload)}\n\n"
                        "Se guardará cifrada. Los pagos solo conceden acceso con status finished verificado por API."
                    ),
                    reply_markup=build_platform_guardarian_confirm_keyboard()
                )

                return


            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ No sé qué dato esperaba. Vuelve a iniciar la configuración Guardarian.",
                reply_markup=build_platform_guardarian_cancel_keyboard()
            )

            return


        if step == "api_key":

            await delete_sensitive_user_message(update)

            if not is_valid_paypal_text_value(text, min_length=8):

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La API key de ChangeNOW no parece válida. Pégala otra vez o cancela.",
                    reply_markup=build_platform_changenow_cancel_keyboard()
                )

                return


            payload["api_key"] = text
            context.user_data["platform_payment_payload"] = payload
            context.user_data["platform_payment_step"] = "payout_currency"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la moneda que recibirá la plataforma. Ejemplo: USDT, USDC, BTC.",
                reply_markup=build_platform_changenow_cancel_keyboard()
            )

            return


        if step == "payout_currency":

            value = text.upper().strip()

            if not value or len(value) > 12:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Moneda no válida. Ejemplo: USDT.",
                    reply_markup=build_platform_changenow_cancel_keyboard()
                )

                return


            payload["payout_currency"] = value.lower()
            context.user_data["platform_payment_payload"] = payload
            context.user_data["platform_payment_step"] = "payout_network"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la red destino. Ejemplo: trx, eth, btc.",
                reply_markup=build_platform_changenow_cancel_keyboard()
            )

            return


        if step == "payout_network":

            value = text.lower().strip()

            if not value or len(value) > 20:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Red no válida. Ejemplo: trx.",
                    reply_markup=build_platform_changenow_cancel_keyboard()
                )

                return


            payload["payout_network"] = value
            context.user_data["platform_payment_payload"] = payload
            context.user_data["platform_payment_step"] = "payout_wallet"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Envía la wallet destino de la plataforma. Revísala con cuidado: una wallet incorrecta puede perder fondos.",
                reply_markup=build_platform_changenow_cancel_keyboard()
            )

            return


        if step == "payout_wallet":

            await delete_sensitive_user_message(update)

            if len(text) < 12 or len(text) > 300 or any(char.isspace() for char in text):

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La wallet no parece válida. Pégala otra vez o cancela.",
                    reply_markup=build_platform_changenow_cancel_keyboard()
                )

                return


            payload["payout_wallet"] = text
            context.user_data["platform_payment_payload"] = payload
            context.user_data["platform_payment_step"] = "payin_currency"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la moneda que pagará el comprador por defecto. Ejemplo: BTC, ETH, USDT.",
                reply_markup=build_platform_changenow_cancel_keyboard()
            )

            return


        if step == "payin_currency":

            value = text.upper().strip()

            if not value or len(value) > 12:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Moneda de pago no válida. Ejemplo: BTC.",
                    reply_markup=build_platform_changenow_cancel_keyboard()
                )

                return


            payload["payin_currency"] = value.lower()
            context.user_data["platform_payment_payload"] = payload
            context.user_data["platform_payment_step"] = "payin_network"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la red de pago. Ejemplo: btc, eth, trx.",
                reply_markup=build_platform_changenow_cancel_keyboard()
            )

            return


        if step == "payin_network":

            value = text.lower().strip()

            if not value or len(value) > 20:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Red de pago no válida. Ejemplo: btc.",
                    reply_markup=build_platform_changenow_cancel_keyboard()
                )

                return


            payload["payin_network"] = value
            context.user_data["platform_payment_payload"] = payload
            context.user_data["platform_payment_step"] = "confirm"

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Revisa la configuración ChangeNOW plataforma:\n\n"
                    f"{build_changenow_safe_summary(payload)}\n\n"
                    "El modo seguro deja todos los pagos en revisión manual. ¿Guardar cifrado?"
                ),
                reply_markup=build_platform_changenow_confirm_keyboard()
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ No sé qué dato esperaba. Vuelve a iniciar la configuración ChangeNOW.",
            reply_markup=build_platform_changenow_cancel_keyboard()
        )

        return


    if not context.user_data.get("configuring_owner_payment_provider"):

        return


    provider = context.user_data.get("owner_payment_provider")
    group_id = context.user_data.get("owner_payment_group_id")
    step = context.user_data.get("owner_payment_step")
    payload = context.user_data.get("owner_payment_payload") or {}
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else None


    if provider not in (OWNER_PAYMENT_PROVIDER_PAYPAL, OWNER_PAYMENT_PROVIDER_REVOLUT, OWNER_PAYMENT_PROVIDER_CHANGENOW, OWNER_PAYMENT_PROVIDER_GUARDARIAN) or not group_id:

        clear_owner_payment_provider_wizard(context)
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ No he podido recuperar la configuración del método de pago. Vuelve a empezar desde Métodos de pago del grupo.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return


    owner_user_id = get_group_owner_user_id(group_id)


    if not is_super_admin(user_id) and owner_user_id != user_id:

        clear_owner_payment_provider_wizard(context)
        await context.bot.send_message(
            chat_id=chat_id,
            text="⛔ No tienes permiso para configurar este método de pago en esta comunidad.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    if not has_payment_encryption_key():

        clear_owner_payment_provider_wizard(context)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ No se puede guardar este método de pago todavía.\n\n"
                "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot. "
                "Por seguridad no se guardan credenciales sin cifrado."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver al proveedor", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    text = (update.message.text or "").strip() if update.message else ""

    clear_plan_wizard_state(
        context,
        user_id=user_id,
        action="receive_owner_payment_provider_text"
    )


    if text.lower() in ("cancelar", "/cancel", "cancel"):

        clear_owner_payment_provider_wizard(context)
        await delete_sensitive_user_message(update)
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Configuración cancelada. No se ha guardado ningún secreto.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver al proveedor", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN:

        if step == "api_key":

            await delete_sensitive_user_message(update)

            if not is_valid_paypal_text_value(text, min_length=8):

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La API key de Guardarian no parece válida. Pégala otra vez o cancela.",
                    reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
                )

                return


            payload["api_key"] = text
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "payout_network"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la red USDT destino. Ejemplos: TRC20, ERC20, Polygon, BEP20.",
                reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
            )

            return


        if step == "payout_network":

            value = text.upper().strip()

            if not value or len(value) > 30:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Red no válida. Ejemplos: TRC20, ERC20, Polygon, BEP20.",
                    reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
                )

                return


            payload["payout_network"] = value
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "payout_wallet"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Envía tu wallet USDT destino. Revísala con cuidado: una red o wallet incorrecta puede perder fondos.",
                reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
            )

            return


        if step == "payout_wallet":

            await delete_sensitive_user_message(update)

            if len(text) < 12 or len(text) > 300 or any(char.isspace() for char in text):

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La wallet no parece válida. Pégala otra vez o cancela.",
                    reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
                )

                return


            payload["payout_wallet"] = text
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "webhook_secret"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Envía el webhook secret de Guardarian si lo tienes. Si no lo tienes, escribe: saltar",
                reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
            )

            return


        if step == "webhook_secret":

            await delete_sensitive_user_message(update)
            lowered = text.lower()

            if lowered in ("saltar", "skip", "no", "-"):

                payload["webhook_secret"] = None

            elif is_valid_paypal_text_value(text, min_length=8):

                payload["webhook_secret"] = text

            else:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ El webhook secret no parece válido. Envíalo otra vez o escribe saltar.",
                    reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
                )

                return


            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "base_url"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Envía GUARDARIAN_BASE_URL solo si usas una URL oficial distinta. Si no lo necesitas, escribe: saltar",
                reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
            )

            return


        if step == "base_url":

            await delete_sensitive_user_message(update)
            lowered = text.lower()

            if lowered in ("saltar", "skip", "no", "-"):

                payload["base_url"] = None

            elif text.startswith("https://") and len(text) <= 300:

                payload["base_url"] = text.rstrip("/")

            else:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La URL no parece válida. Debe empezar por https:// o escribe saltar.",
                    reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
                )

                return


            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "confirm"

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Revisa la configuración segura de Guardarian:\n\n"
                    f"{build_guardarian_safe_summary(payload)}\n\n"
                    "Se guardará cifrada. Guardarian quedará disponible para compradores del grupo. El acceso solo se concede con status finished verificado por API."
                ),
                reply_markup=build_owner_guardarian_confirm_keyboard(group_id)
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text="Usa los botones del asistente para continuar con Guardarian.",
            reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
        )

        return


    if provider == OWNER_PAYMENT_PROVIDER_CHANGENOW:

        if step == "api_key":

            await delete_sensitive_user_message(update)

            if not is_valid_paypal_text_value(text, min_length=8):

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La API key de ChangeNOW no parece válida. Pégala otra vez o cancela.",
                    reply_markup=build_owner_changenow_cancel_keyboard(group_id)
                )

                return


            payload["api_key"] = text
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "payout_currency"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la moneda que quieres recibir. Ejemplo: USDT, USDC, BTC.",
                reply_markup=build_owner_changenow_cancel_keyboard(group_id)
            )

            return


        if step == "payout_currency":

            value = text.upper().strip()

            if not value or len(value) > 12:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Moneda no válida. Ejemplo: USDT.",
                    reply_markup=build_owner_changenow_cancel_keyboard(group_id)
                )

                return


            payload["payout_currency"] = value.lower()
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "payout_network"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la red destino. Ejemplo: trx, eth, btc.",
                reply_markup=build_owner_changenow_cancel_keyboard(group_id)
            )

            return


        if step == "payout_network":

            value = text.lower().strip()

            if not value or len(value) > 20:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Red no válida. Ejemplo: trx.",
                    reply_markup=build_owner_changenow_cancel_keyboard(group_id)
                )

                return


            payload["payout_network"] = value
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "payout_wallet"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Envía tu wallet destino. Revísala con cuidado: una wallet incorrecta puede perder fondos.",
                reply_markup=build_owner_changenow_cancel_keyboard(group_id)
            )

            return


        if step == "payout_wallet":

            await delete_sensitive_user_message(update)

            if len(text) < 12 or len(text) > 300 or any(char.isspace() for char in text):

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La wallet no parece válida. Pégala otra vez o cancela.",
                    reply_markup=build_owner_changenow_cancel_keyboard(group_id)
                )

                return


            payload["payout_wallet"] = text
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "payin_currency"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la moneda que pagará el comprador por defecto. Ejemplo: BTC, ETH, USDT.",
                reply_markup=build_owner_changenow_cancel_keyboard(group_id)
            )

            return


        if step == "payin_currency":

            value = text.upper().strip()

            if not value or len(value) > 12:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Moneda de pago no válida. Ejemplo: BTC.",
                    reply_markup=build_owner_changenow_cancel_keyboard(group_id)
                )

                return


            payload["payin_currency"] = value.lower()
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "payin_network"

            await context.bot.send_message(
                chat_id=chat_id,
                text="Indica la red de pago. Ejemplo: btc, eth, trx.",
                reply_markup=build_owner_changenow_cancel_keyboard(group_id)
            )

            return


        if step == "payin_network":

            value = text.lower().strip()

            if not value or len(value) > 20:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Red de pago no válida. Ejemplo: btc.",
                    reply_markup=build_owner_changenow_cancel_keyboard(group_id)
                )

                return


            payload["payin_network"] = value
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "confirm"

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Revisa la configuración ChangeNOW de tu comunidad:\n\n"
                    f"{build_changenow_safe_summary(payload)}\n\n"
                    "El modo seguro deja todos los pagos en revisión manual. ¿Guardar cifrado?"
                ),
                reply_markup=build_owner_changenow_confirm_keyboard(group_id)
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ No sé qué dato esperaba. Vuelve a iniciar la configuración ChangeNOW.",
            reply_markup=build_owner_changenow_cancel_keyboard(group_id)
        )

        return


    if provider == OWNER_PAYMENT_PROVIDER_REVOLUT:

        if step == "api_key":

            await delete_sensitive_user_message(update)


            if not is_valid_paypal_text_value(text, min_length=16):

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La API key de Revolut no parece válida. Pégala otra vez o cancela la configuración.",
                    reply_markup=build_owner_revolut_cancel_keyboard(group_id)
                )

                return


            payload["api_key"] = text
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "webhook_secret"

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Ahora envía el REVOLUT_WEBHOOK_SECRET.\n\n"
                    "Lo borraré del chat si Telegram lo permite y nunca se mostrará completo."
                ),
                reply_markup=build_owner_revolut_cancel_keyboard(group_id)
            )

            return


        if step == "webhook_secret":

            await delete_sensitive_user_message(update)


            if not is_valid_paypal_text_value(text, min_length=16):

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ El webhook secret de Revolut no parece válido. Pégalo otra vez o cancela la configuración.",
                    reply_markup=build_owner_revolut_cancel_keyboard(group_id)
                )

                return


            payload["webhook_secret"] = text
            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "base_url"

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Envía REVOLUT_BASE_URL solo si usas una URL personalizada.\n\n"
                    "Si no lo necesitas, escribe: saltar"
                ),
                reply_markup=build_owner_revolut_cancel_keyboard(group_id)
            )

            return


        if step == "base_url":

            await delete_sensitive_user_message(update)

            lowered = text.lower()


            if lowered in ("saltar", "skip", "no", "-"):

                payload["base_url"] = None

            elif text.startswith("https://") and len(text) <= 300:

                payload["base_url"] = text.rstrip("/")

            else:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ La URL no parece válida. Debe empezar por https:// o escribe saltar.",
                    reply_markup=build_owner_revolut_cancel_keyboard(group_id)
                )

                return


            context.user_data["owner_payment_payload"] = payload
            context.user_data["owner_payment_step"] = "confirm"

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Revisa la configuración segura de Revolut:\n\n"
                    f"{build_owner_revolut_safe_summary(payload)}\n\n"
                    "Se guardará cifrada. Revolut quedará disponible para compradores del grupo cuando el webhook confirme pagos reales."
                ),
                reply_markup=build_owner_revolut_confirm_keyboard(group_id)
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text="Usa los botones del asistente para continuar con Revolut.",
            reply_markup=build_owner_revolut_cancel_keyboard(group_id)
        )

        return


    if step == "client_id":

        await delete_sensitive_user_message(update)


        if not is_valid_paypal_text_value(text, min_length=12):

            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ El Client ID no parece válido. Pégalo otra vez o cancela la configuración.",
                reply_markup=build_owner_paypal_cancel_keyboard(group_id)
            )

            return


        payload["client_id"] = text
        context.user_data["owner_payment_payload"] = payload
        context.user_data["owner_payment_step"] = "client_secret"

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Ahora envía el PAYPAL_CLIENT_SECRET.\n\n"
                "Lo borraré del chat si Telegram lo permite y nunca se mostrará completo."
            ),
            reply_markup=build_owner_paypal_cancel_keyboard(group_id)
        )

        return


    if step == "client_secret":

        await delete_sensitive_user_message(update)


        if not is_valid_paypal_text_value(text, min_length=16):

            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ El Client Secret no parece válido. Pégalo otra vez o cancela la configuración.",
                reply_markup=build_owner_paypal_cancel_keyboard(group_id)
            )

            return


        payload["client_secret"] = text
        context.user_data["owner_payment_payload"] = payload
        context.user_data["owner_payment_step"] = "webhook_id"

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Envía el PAYPAL_WEBHOOK_ID si ya lo tienes.\n\n"
                "Si todavía no lo tienes, escribe: saltar\n\n"
                "En esta fase el webhook por grupo queda preparado, pero no activa cobros reales."
            ),
            reply_markup=build_owner_paypal_cancel_keyboard(group_id)
        )

        return


    if step == "webhook_id":

        await delete_sensitive_user_message(update)

        lowered = text.lower()


        if lowered in ("saltar", "skip", "no", "-"):

            payload["webhook_id"] = None

        elif is_valid_paypal_text_value(text, min_length=8):

            payload["webhook_id"] = text

        else:

            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ El Webhook ID no parece válido. Envíalo otra vez o escribe saltar.",
                reply_markup=build_owner_paypal_cancel_keyboard(group_id)
            )

            return


        context.user_data["owner_payment_payload"] = payload
        context.user_data["owner_payment_step"] = "confirm"

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Revisa la configuración segura de PayPal:\n\n"
                f"{build_owner_paypal_safe_summary(payload)}\n\n"
                "Se guardará cifrada y quedará pendiente de verificación. "
                "Todavía no activará cobros PayPal reales para compradores del grupo."
            ),
            reply_markup=build_owner_paypal_confirm_keyboard(group_id)
        )

        return


    await context.bot.send_message(
        chat_id=chat_id,
        text="Usa los botones del asistente para continuar con PayPal.",
        reply_markup=build_owner_paypal_cancel_keyboard(group_id)
    )






def build_group_admin_error_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🏪 Elegir comunidad",
            callback_data="admin_edit_group"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="group_admin_panel"
        )],
        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]
    ])


def format_group_admin_permission_list(selected_permissions=None):

    selected_permissions = selected_permissions or {}
    lines = []


    for key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        enabled = selected_permissions.get(permission) is True
        marker = "✅" if enabled else "▫️"
        lines.append(f"{marker} {label}")


    return "\n".join(lines)


def build_group_admin_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Añadir admin", callback_data="group_admin_add")],
        [InlineKeyboardButton("📋 Ver admins", callback_data="group_admin_view")],
        [InlineKeyboardButton("✏️ Editar permisos", callback_data="group_admin_edit")],
        [InlineKeyboardButton("❌ Quitar admin", callback_data="group_admin_remove")],
        [InlineKeyboardButton("📖 Ver permisos disponibles", callback_data="group_admin_permissions_info")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])






def fetch_group_admin_permissions(group_id, target_user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT can_view_users,
                   can_manage_users,
                   can_kick_users,
                   can_ban_users,
                   can_unban_users,
                   can_warn_users,
                   can_reset_warnings,
                   can_resend_links,
                   can_view_stats,
                   can_manage_plans,
                   can_edit_group_texts,
                   can_edit_marketplace_preview,
                   can_respond_group_support,
                   can_view_logs,
                   role,
                   is_active
            FROM admins
            WHERE group_id=%s
            AND user_id=%s
            AND is_super_admin=FALSE
            LIMIT 1

        """, (
            group_id,
            target_user_id
        ))

        row = cur.fetchone()


    if not row:

        return None


    permissions = {}

    for index, (_key, _label, permission) in enumerate(GROUP_ADMIN_PERMISSION_OPTIONS):

        permissions[permission] = row[index] is True


    return {
        "permissions": permissions,
        "role": row[len(GROUP_ADMIN_PERMISSION_OPTIONS)],
        "is_active": row[len(GROUP_ADMIN_PERMISSION_OPTIONS) + 1] is True
    }


def build_group_admin_permissions_keyboard(group_id, target_user_id, permissions, toggle_callback_prefix):

    keyboard = []


    for key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        enabled = permissions.get(permission) is True
        prefix = "✅" if enabled else "▫️"
        keyboard.append([InlineKeyboardButton(
            f"{prefix} {label}",
            callback_data=f"{toggle_callback_prefix}_{group_id}_{target_user_id}_{key}"
        )])


    keyboard.append([InlineKeyboardButton(
        "💾 Guardar admin",
        callback_data=f"add_group_admin_save_{group_id}"
    )])
    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="group_admin_panel"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_group_admin_edit_permissions_keyboard(group_id, target_user_id, permissions):

    keyboard = []


    for key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        enabled = permissions.get(permission) is True
        prefix = "✅" if enabled else "▫️"
        keyboard.append([InlineKeyboardButton(
            f"{prefix} {label}",
            callback_data=f"gap_t_{group_id}_{target_user_id}_{key}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"group_admin_edit_group_{group_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def save_group_admin_permissions(group_id, target_user_id, permissions):

    columns = [
        "user_id",
        "group_id",
        "role",
        "is_super_admin",
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
        "can_respond_group_support",
        "is_active"
    ]
    values_by_permission = {
        permission: permissions.get(permission) is True
        for _key, _label, permission in GROUP_ADMIN_PERMISSION_OPTIONS
    }
    values = [
        target_user_id,
        group_id,
        "GROUP_ADMIN",
        False,
        values_by_permission.get("can_manage_users", False),
        values_by_permission.get("can_kick_users", False),
        values_by_permission.get("can_ban_users", False),
        values_by_permission.get("can_unban_users", False),
        values_by_permission.get("can_warn_users", False),
        values_by_permission.get("can_reset_warnings", False),
        values_by_permission.get("can_resend_links", False),
        False,
        False,
        False,
        values_by_permission.get("can_manage_plans", False),
        False,
        False,
        values_by_permission.get("can_view_users", False),
        False,
        values_by_permission.get("can_view_stats", False),
        values_by_permission.get("can_view_logs", False),
        values_by_permission.get("can_edit_group_texts", False),
        values_by_permission.get("can_edit_marketplace_preview", False),
        values_by_permission.get("can_respond_group_support", False),
        True
    ]
    placeholders = ", ".join(["%s"] * len(columns))
    update_columns = columns[2:]
    update_set = ", ".join(
        f"{column}=EXCLUDED.{column}"
        for column in update_columns
    )


    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO admins
            ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (user_id, group_id)
            DO UPDATE SET {update_set}

        """, values)




def fetch_group_name(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT name
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    return row[0] if row else f"Grupo {group_id}"






def fetch_admin_groups_for_permissions(user_id, permissions):

    group_ids = get_admin_group_ids(user_id, permissions)


    try:

        with conn.cursor() as cur:

            if group_ids is None:

                cur.execute("""

                    SELECT id, name, telegram_group_id
                    FROM groups
                    WHERE telegram_group_id != 0
                    ORDER BY id ASC

                """)

            elif not group_ids:

                return []

            else:

                cur.execute("""

                    SELECT id, name, telegram_group_id
                    FROM groups
                    WHERE telegram_group_id != 0
                    AND id = ANY(%s)
                    ORDER BY id ASC

                """, (group_ids,))


            return cur.fetchall()

    except Exception as e:

        print("Error cargando grupos permitidos:", e)

        raise






def fetch_owner_group_quick_status(group_id):

    status = {
        "name": "Comunidad",
        "community_type": "group",
        "is_free_group": False,
        "is_marketplace_visible": False,
        "is_main_menu_visible": False,
        "free_invite_link": None,
        "public_visibility": "start_home",
        "active_users": 0,
        "active_plans": 0,
        "active_codes": 0,
        "active_admins": 0,
        "backup_active": False,
        "critical_errors": []
    }


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT name,
                       (
                           COALESCE(is_free_group, FALSE)
                           OR COALESCE(is_free, FALSE)
                       ),
                       COALESCE(public_visibility, 'start_home'),
                       COALESCE(community_type, 'group'),
                       (
                           COALESCE(is_marketplace_visible, FALSE)
                           OR COALESCE(public_visibility, 'start_home') IN ('explore_only', 'both')
                       ),
                       (
                           COALESCE(is_main_menu_visible, FALSE)
                           OR COALESCE(public_visibility, 'start_home') IN ('start_home', 'both')
                       ),
                       free_invite_link
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            group_row = cur.fetchone()

            if group_row:

                status["name"] = group_row[0] or "Comunidad"
                status["is_free_group"] = bool(group_row[1])
                status["public_visibility"] = group_row[2] or "start_home"
                status["community_type"] = normalize_community_type(group_row[3])
                status["is_marketplace_visible"] = bool(group_row[4])
                status["is_main_menu_visible"] = bool(group_row[5])
                status["free_invite_link"] = group_row[6]


            cur.execute("""

                SELECT COUNT(*)
                FROM users
                WHERE group_id=%s
                AND COALESCE(subscription_active, FALSE)=TRUE
                AND (
                    expiration IS NULL
                    OR expiration > NOW()
                )

            """, (group_id,))

            status["active_users"] = cur.fetchone()[0] or 0


            cur.execute("""

                SELECT COUNT(*)
                FROM plans
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE

            """, (group_id,))

            status["active_plans"] = cur.fetchone()[0] or 0


            cur.execute("""

                SELECT COUNT(*)
                FROM group_user_promo_codes
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE

            """, (group_id,))

            status["active_codes"] = cur.fetchone()[0] or 0


            cur.execute("""

                SELECT COUNT(*)
                FROM admins
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE

            """, (group_id,))

            status["active_admins"] = cur.fetchone()[0] or 0


            cur.execute("""

                SELECT 1
                FROM group_backup_configs
                WHERE source_group_id=%s
                AND status='active'
                LIMIT 1

            """, (group_id,))

            status["backup_active"] = cur.fetchone() is not None


            cur.execute("""

                SELECT event_type, message
                FROM audit_logs
                WHERE group_id=%s
                AND severity='critical'
                ORDER BY created_at DESC
                LIMIT 3

            """, (group_id,))

            status["critical_errors"] = cur.fetchall()

    except Exception as e:

        print("Error cargando estado rápido owner:", e)


    return status




def build_owner_setup_assistant_text(group_id):

    status = fetch_owner_group_quick_status(group_id)

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT
                    COALESCE(name, ''),
                    COALESCE(preview_text, ''),
                    preview_image_file_id,
                    preview_video_file_id,
                    COALESCE(preview_mode, 'manual')
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            group_row = cur.fetchone()

    except Exception as e:

        print("Error cargando asistente owner:", e)

        group_row = None


    name_done = bool(group_row and group_row[0])
    preview_done = bool(
        group_row
        and (
            group_row[1]
            or group_row[2]
            or group_row[3]
            or group_row[4] in ("dynamic", "hybrid", "private")
        )
    )
    access_done = status["is_free_group"] or status["active_plans"] > 0
    codes_done = status["active_codes"] > 0
    admins_done = status["active_admins"] > 0
    logs_done = not status["critical_errors"]
    backup_done = status["backup_active"]


    def mark(done):

        return "✅ completado" if done else "⚠️ pendiente"


    return (
        "🧭 Asistente de configuración\n\n"
        "Sigue esta lista para dejar tu comunidad lista para la beta.\n\n"
        f"{mark(name_done)} — configurar nombre/descripción\n"
        f"{mark(preview_done)} — configurar preview\n"
        f"{mark(access_done)} — configurar plan o acceso gratis\n"
        f"{mark(codes_done)} — crear primer código promocional\n"
        f"{mark(admins_done)} — revisar admins\n"
        f"{mark(logs_done)} — revisar logs críticos\n"
        f"{mark(backup_done)} — activar backup opcional"
    )


def build_owner_setup_assistant_keyboard(user_id, group_id):

    keyboard = []


    if user_has_group_permission_any(user_id, group_id, ["can_manage_groups", "can_edit_group_texts"]):
        keyboard.append([InlineKeyboardButton("⚙️ Nombre/descripción", callback_data="owner_panel_general")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_groups", "can_edit_marketplace_preview"]):
        keyboard.append([InlineKeyboardButton("🖼 Preview", callback_data="owner_panel_marketplace")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_plans", "can_manage_groups"]):
        keyboard.append([InlineKeyboardButton("💳 Plan/acceso", callback_data="owner_panel_payments")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_codes"]):
        keyboard.append([InlineKeyboardButton("🎟 Primer código", callback_data="owner_panel_codes")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_admins"]):
        keyboard.append([InlineKeyboardButton("👑 Admins", callback_data="owner_panel_admins")])

    if user_has_group_permission_any(user_id, group_id, ["can_view_logs"]):
        keyboard.append([InlineKeyboardButton("📜 Logs", callback_data="owner_panel_logs")])

    if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):
        keyboard.append([InlineKeyboardButton("💾 Backups automáticos", callback_data="owner_panel_backup")])


    keyboard.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return InlineKeyboardMarkup(keyboard)








def fetch_free_invite_group(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   name,
                   telegram_group_id,
                   (
                       COALESCE(is_free_group, FALSE)
                       OR COALESCE(is_free, FALSE)
                   ) AS is_free,
                   free_invite_link,
                   COALESCE(community_type, 'group')
            FROM groups
            WHERE id=%s
            AND is_active=TRUE
            LIMIT 1

        """, (group_id,))

        return cur.fetchone()


def format_free_invite_link_error(result, community_kind="grupo"):

    description = (result or {}).get("description") or (result or {}).get("error") or ""
    lowered = str(description).lower()


    if "not enough rights" in lowered or "administrator" in lowered or "rights" in lowered:

        return (
            "No puedo generar el link porque no soy administrador del grupo.\n\n"
            "Necesito permiso para invitar usuarios mediante enlace."
        )


    if "invite" in lowered or "permission" in lowered or "permis" in lowered:

        return "Necesito permiso para invitar usuarios mediante enlace."


    return (
        f"No he podido crear el link de entrada del {community_kind}.\n\n"
        "Revisa que el bot sea administrador y tenga permiso para invitar usuarios mediante enlace."
    )


def get_or_create_free_group_invite_link(group_id, regenerate=False):

    group_row = fetch_free_invite_group(group_id)


    if not group_row:

        return {
            "ok": False,
            "reason": "group_not_found"
        }


    _group_id, group_name, telegram_group_id, is_free, free_invite_link, community_type = group_row
    community_type = normalize_community_type(community_type)


    if not is_free:

        return {
            "ok": False,
            "reason": "not_free_group",
            "group_name": group_name
        }


    if not telegram_group_id:

        return {
            "ok": False,
            "reason": "missing_telegram_group_id",
            "group_name": group_name
        }


    if free_invite_link and not regenerate:

        return {
            "ok": True,
            "invite_link": free_invite_link,
            "created": False,
            "group_name": group_name,
            "telegram_group_id": telegram_group_id,
            "community_type": community_type
        }


    if free_invite_link and regenerate:

        try:

            revoke_telegram_invite_link(
                TOKEN,
                telegram_group_id,
                free_invite_link
            )

        except Exception as e:

            print("Error revocando link gratuito anterior:", e)


    result = create_telegram_public_invite_link(
        TOKEN,
        telegram_group_id,
        name="Acceso gratuito",
        community_type=community_type,
        return_details=True
    )
    invite_link = result.get("invite_link") if result else None


    if not invite_link:

        log_event(
            "free_group_invite_link_failed",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            message="No se pudo generar link gratuito persistente.",
            metadata={
                "error_code": (result or {}).get("error_code"),
                "description": ((result or {}).get("description") or (result or {}).get("error") or "")[:500]
            }
        )

        return {
            "ok": False,
            "reason": "telegram_error",
            "telegram_result": result,
            "group_name": group_name,
            "telegram_group_id": telegram_group_id,
            "community_type": community_type
        }


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE groups
            SET free_invite_link=%s,
                free_invite_link_created_at=NOW()
            WHERE id=%s

        """, (
            invite_link,
            group_id
        ))

        conn.commit()


    return {
        "ok": True,
        "invite_link": invite_link,
        "created": True,
        "group_name": group_name,
        "telegram_group_id": telegram_group_id,
        "community_type": community_type
    }


def build_group_settings_keyboard(user_id, group_id):

    keyboard = []


    keyboard.append([
        InlineKeyboardButton("🧭 Asistente de configuración", callback_data="owner_setup_assistant")
    ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_view_logs", "can_manage_plans", "can_respond_group_support"]
    ):

        keyboard.append([
            InlineKeyboardButton("🤖 Asistente de comunidad", callback_data="owner_ai_panel")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        [
            "can_view_users",
            "can_manage_users",
            "can_kick_users",
            "can_ban_users",
            "can_unban_users",
            "can_warn_users",
            "can_reset_warnings",
            "can_resend_links",
            "can_recover_access"
        ]
    ):

        keyboard.append([
            InlineKeyboardButton("👥 Usuarios y accesos", callback_data="owner_panel_users")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_codes"]
    ):

        keyboard.append([
            InlineKeyboardButton("🎟 Códigos y promociones", callback_data="owner_panel_codes")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
    ):

        keyboard.append([
            InlineKeyboardButton("💳 Planes y pagos del grupo", callback_data="owner_panel_payments")
        ])

        # El panel enseñaba todo menos el dinero: el propietario no podía ver
        # cuánto factura sin irse al panel de Stripe (que solo cubre uno de los
        # cinco métodos). Mismos permisos que el bloque de pagos de arriba.
        keyboard.append([
            InlineKeyboardButton("💰 Ingresos", callback_data="owner_panel_revenue")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_view_logs"]
    ):

        keyboard.append([
            InlineKeyboardButton("🛡 Seguridad del grupo", callback_data="owner_panel_security")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_edit_group_texts", "can_edit_marketplace_preview"]
    ):

        keyboard.append([
            InlineKeyboardButton("🖼 Marketplace y preview", callback_data="owner_panel_marketplace")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_admins"]
    ):

        keyboard.append([
            InlineKeyboardButton("👑 Administradores del grupo", callback_data="owner_panel_admins")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_view_logs"]
    ):

        keyboard.append([
            InlineKeyboardButton("📜 Logs y actividad del grupo", callback_data="owner_panel_logs")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_respond_group_support"]
    ):

        keyboard.append([
            InlineKeyboardButton("🛟 Solicitudes de soporte", callback_data="owner_panel_support")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_view_logs"]
    ):

        keyboard.append([
            InlineKeyboardButton("😊 Encuestas de comunidad", callback_data="owner_panel_satisfaction")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups"]
    ):

        keyboard.append([
            InlineKeyboardButton("🧩 Servicios extra", callback_data="owner_addons_menu")
        ])

        keyboard.append([
            InlineKeyboardButton("📣 Promoción automática", callback_data="admin_ad_promo")
        ])

        keyboard.append([
            InlineKeyboardButton("💾 Backups automáticos", callback_data="owner_panel_backup")
        ])

        keyboard.append([
            InlineKeyboardButton("🛡 Guardian", callback_data="owner_panel_guardian")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_edit_group_texts"]
    ):

        keyboard.append([
            InlineKeyboardButton("⚙️ Configuración de la comunidad", callback_data="owner_panel_general")
        ])


    if user_has_group_permission_any(
        user_id,
        group_id,
        ["can_manage_groups", "can_view_logs"]
    ):

        keyboard.append([
            InlineKeyboardButton("🧪 Auditoría del panel de comunidad", callback_data="owner_panel_audit")
        ])


    if is_super_admin(user_id):

        keyboard.append([
            InlineKeyboardButton("❌ Eliminar grupo", callback_data="delete_group_confirm")
        ])


    keyboard.append([
        InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")
    ])

    keyboard.append([
        InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")
    ])

    return keyboard


def build_owner_panel_nav_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def format_owner_addon_price(product):

    cents = product.get("monthly_price_cents") or 0
    currency = (product.get("currency") or "eur").upper()

    try:

        amount = int(cents) / 100

    except Exception:

        amount = 0


    if amount <= 0:

        return f"0 {currency}/mes"


    return f"{amount:.2f}".replace(".", ",") + f" {currency}/mes"


def build_owner_addons_menu_text(owner_user_id, group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Comunidad {group_id}"
    products = fetch_owner_addon_products(active_only=True)

    lines = [
        "🧩 Servicios extra",
        "",
        f"Comunidad: {group_name}",
        "",
        "Estos servicios son complementos mensuales para owners. No cambian las suscripciones de usuarios ni los accesos actuales."
    ]


    if not products:

        lines.append("")
        lines.append("Ahora mismo no hay servicios extra activos para mostrar.")
        return "\n".join(lines)


    for product in products:

        lines.append("")
        lines.append(f"• {product.get('name')}")
        lines.append(f"  Precio: {format_owner_addon_price(product)}")
        lines.append(f"  {product.get('description') or 'Sin descripción.'}")


    return "\n".join(lines)


def build_owner_addons_menu_keyboard(user_id=None):

    keyboard = []
    products = fetch_owner_addon_products(active_only=True)


    for product in products:

        keyboard.append([InlineKeyboardButton(
            f"Ver / contratar · {product.get('name')}",
            callback_data=f"owner_addon_product_{product.get('code')}"
        )])


    if user_id and is_super_admin(user_id):

        keyboard.append([InlineKeyboardButton("🎁 Activar Guardian 30 días", callback_data="admin_guardian_trial_start")])


    keyboard.append([InlineKeyboardButton("📦 Mis servicios activos", callback_data="owner_addons_active")])
    keyboard.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return InlineKeyboardMarkup(keyboard)


def build_admin_guardian_trial_cancel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_guardian_trial_cancel")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_admin_guardian_trial_result_keyboard(group_id=None):

    keyboard = []

    if group_id:

        keyboard.append([InlineKeyboardButton("🛡 Abrir Guardian del grupo", callback_data="owner_panel_guardian")])


    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def fetch_admin_guardian_trial_groups(page=0, page_size=8, query=None):

    page = max(int(page or 0), 0)
    page_size = max(int(page_size or 8), 1)
    params = []
    filters = [
        "COALESCE(g.is_active, TRUE)=TRUE",
        "a.user_id IS NOT NULL"
    ]

    query_text = (query or "").strip()

    if query_text:

        search_filters = ["g.name ILIKE %s"]
        params.append(f"%{query_text}%")

        if query_text.lstrip("-").isdigit():

            search_filters.append("g.id=%s")
            params.append(int(query_text))
            search_filters.append("g.telegram_group_id=%s")
            params.append(int(query_text))
            search_filters.append("a.user_id=%s")
            params.append(int(query_text))


        filters.append(f"({' OR '.join(search_filters)})")


    params.extend([
        page_size + 1,
        page * page_size
    ])

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT g.id,
                   g.name,
                   g.telegram_group_id,
                   a.user_id AS owner_user_id,
                   COALESCE(g.is_active, TRUE)
            FROM groups g
            JOIN admins a
              ON a.group_id = g.id
             AND a.role = 'GROUP_OWNER'
             AND COALESCE(a.is_active, TRUE)=TRUE
            WHERE {" AND ".join(filters)}
            ORDER BY g.id DESC
            LIMIT %s OFFSET %s

        """, params)

        rows = cur.fetchall()


    return rows[:page_size], len(rows) > page_size








def build_admin_guardian_trial_search_results_text(query):

    return (
        "🔎 Resultados de búsqueda Guardian\n\n"
        f"Búsqueda: {(query or '').strip() or '-'}\n\n"
        "Elige un grupo para activar Guardian 30 días."
    )


def build_admin_guardian_trial_search_results_keyboard(query):

    rows, _has_next = fetch_admin_guardian_trial_groups(page=0, page_size=8, query=query)
    keyboard = []

    for group_id, name, telegram_group_id, owner_user_id, _is_active in rows:

        keyboard.append([
            InlineKeyboardButton(
                f"{name or f'Grupo {group_id}'} · #{group_id}",
                callback_data=f"admin_guardian_trial_group_{group_id}"
            )
        ])


    if not keyboard:

        keyboard.append([InlineKeyboardButton("Sin resultados", callback_data="admin_guardian_trial_search")])


    keyboard.append([InlineKeyboardButton("🔎 Buscar otra vez", callback_data="admin_guardian_trial_search")])
    keyboard.append([InlineKeyboardButton("🎁 Ver listado", callback_data="admin_guardian_trial_groups_0")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def build_owner_addon_product_text(product, group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Comunidad {group_id}"
    stripe_status = (
        "configurado"
        if product.get("stripe_price_id")
        else "pendiente de configuración"
    )

    text = (
        "🧩 Servicio extra\n\n"
        f"Comunidad: {group_name}\n"
        f"Servicio: {product.get('name')}\n"
        f"Precio: {format_owner_addon_price(product)}\n"
        f"Stripe: {stripe_status}\n\n"
        f"{product.get('description') or 'Sin descripción.'}"
    )


    if not product.get("stripe_price_id"):

        text += "\n\n⚠️ Este servicio todavía no tiene precio de Stripe configurado."


    return text


async def receive_admin_guardian_trial_text(update, context):

    user_id = update.effective_user.id if update.effective_user else None
    text = (update.message.text or "").strip() if update.message else ""
    search_waiting = bool(context.user_data.get("admin_guardian_trial_search_waiting"))

    if not is_super_admin(user_id):

        context.user_data.pop("admin_guardian_trial_waiting", None)
        context.user_data.pop("admin_guardian_trial_search_waiting", None)

        log_event(
            "admin_guardian_trial_permission_denied",
            category="guardian",
            severity="warning",
            scope="global",
            actor_user_id=user_id,
            message="Usuario no superadmin intentó activar trial manual Guardian.",
            metadata={
                "user_id": user_id
            }
        )

        await update.message.reply_text(
            "⛔ Solo superadmin puede activar Guardian manualmente."
        )

        return


    if text.lower() in ("cancelar", "cancel", "salir"):

        context.user_data.pop("admin_guardian_trial_waiting", None)
        context.user_data.pop("admin_guardian_trial_search_waiting", None)

        await update.message.reply_text(
            "✅ Activación manual de Guardian cancelada.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    if search_waiting:

        context.user_data.pop("admin_guardian_trial_search_waiting", None)

        await update.message.reply_text(
            build_admin_guardian_trial_search_results_text(text),
            reply_markup=build_admin_guardian_trial_search_results_keyboard(text)
        )

        return


    parts = text.split()

    if len(parts) != 2:

        await update.message.reply_text(
            "⚠️ Envía owner_user_id y group_id separados por espacio.\n\n"
            "Ejemplo:\n"
            "123456789 1159",
            reply_markup=build_admin_guardian_trial_cancel_keyboard()
        )

        return


    try:

        owner_user_id = int(parts[0])
        group_id = int(parts[1])

    except Exception:

        await update.message.reply_text(
            "⚠️ Owner ID y Group ID deben ser números enteros.",
            reply_markup=build_admin_guardian_trial_cancel_keyboard()
        )

        return


    result = activate_owner_addon_manual_trial(
        owner_user_id,
        group_id,
        "guardian",
        days=30,
        activated_by_user_id=user_id
    )
    context.user_data.pop("admin_guardian_trial_waiting", None)

    if not result.get("ok"):

        reason = result.get("reason") or "unknown"
        extra = ""

        if reason == "owner_group_mismatch":

            extra = f"\nOwner real del grupo: {result.get('group_owner_user_id') or '-'}"


        await update.message.reply_text(
            "⚠️ No he podido activar Guardian manualmente.\n\n"
            f"Motivo: {reason}{extra}",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    context.user_data["selected_group_admin"] = group_id
    context.user_data["selected_owner_group"] = group_id

    await update.message.reply_text(
        "✅ Guardian activado manualmente 30 días\n\n"
        f"Owner ID: {owner_user_id}\n"
        f"Group ID: {group_id}\n"
        f"Hasta: {format_commercial_datetime(result.get('current_period_end'))}\n"
        f"Subscription ID: {result.get('subscription_id')}",
        reply_markup=build_admin_guardian_trial_result_keyboard(group_id)
    )


def build_owner_addon_product_keyboard(product):

    keyboard = []

    if product.get("stripe_price_id"):

        keyboard.append([InlineKeyboardButton(
            "💳 Contratar mensual",
            callback_data=f"owner_addon_checkout_{product.get('code')}"
        )])


    keyboard.extend([
        [InlineKeyboardButton("⬅️ Volver a servicios extra", callback_data="owner_addons_menu")],
        [InlineKeyboardButton("📦 Mis servicios activos", callback_data="owner_addons_active")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_owner_addon_checkout_keyboard(product, checkout_url):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pagar en Stripe", url=checkout_url)],
        [InlineKeyboardButton("⬅️ Volver a servicios extra", callback_data="owner_addons_menu")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_addon_checkout_urls():

    base_url = (SERVER_URL or "").rstrip("/")

    if not base_url:

        return "https://t.me/TheStarVipBOT", "https://t.me/TheStarVipBOT"


    return (
        f"{base_url}/owner-addon-success?session_id={{CHECKOUT_SESSION_ID}}",
        f"{base_url}/owner-addon-cancel"
    )


def create_owner_addon_stripe_checkout_session(
    product,
    owner_user_id,
    buyer_user_id,
    group_id
):

    # El precio se asegura AQUÍ, no se da por hecho. Antes esta línea usaba
    # product["stripe_price_id"] tal cual, y los servicios se sembraban sin él:
    # el checkout salía con price=None y no se podía comprar. Ahora, si falta,
    # se crea con la clave de la plataforma en el momento.
    precio_id = ensure_owner_addon_stripe_price(product)

    if not precio_id:

        raise ValueError(
            "El servicio no tiene precio mensual configurado, así que no se "
            "puede cobrar."
        )

    # Stripe Tax sigue fuera de automatic_tax en los extras, pero ya no por
    # falta de tax_behavior: los precios que crea este código llevan la marca
    # fiscal (stripe_catalog). Queda fuera porque encenderlo aquí cambiaría lo
    # que paga un propietario que ya está suscrito, y eso se decide aparte.
    success_url, cancel_url = build_owner_addon_checkout_urls()
    metadata = {
        "purpose": "owner_addon",
        "owner_user_id": str(owner_user_id),
        "buyer_user_id": str(buyer_user_id),
        "group_id": str(group_id),
        "addon_code": str(product.get("code"))
    }

    return stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{
            "price": precio_id,
            "quantity": 1
        }],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=f"owner_addon:{owner_user_id}:{group_id}:{product.get('code')}",
        metadata=metadata,
        subscription_data={
            "metadata": metadata
        }
    )


def build_owner_addons_active_text(owner_user_id, group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Comunidad {group_id}"
    subscriptions = fetch_owner_addon_subscriptions_for_management(
        owner_user_id,
        group_id=group_id
    )

    lines = [
        "📦 Mis servicios",
        "",
        f"Comunidad: {group_name}"
    ]


    if not subscriptions:

        lines.append("")
        lines.append("No tienes servicios extra registrados todavía.")
        return "\n".join(lines)


    products = {
        product.get("code"): product
        for product in fetch_owner_addon_products(active_only=False)
    }

    for subscription in subscriptions:

        product = products.get(subscription.get("addon_code")) or {}
        scope = "todas tus comunidades" if subscription.get("group_id") is None else f"comunidad {subscription.get('group_id')}"
        period_end = format_commercial_datetime(subscription.get("current_period_end"))
        cancel_text = "sí" if subscription.get("cancel_at_period_end") else "no"

        lines.append("")
        lines.append(f"• {product.get('name') or subscription.get('addon_code')}")
        lines.append(f"  Estado: {subscription.get('status')}")
        lines.append(f"  Ámbito: {scope}")
        lines.append(f"  Fin del periodo: {period_end}")
        lines.append(f"  Cancelación programada: {cancel_text}")


    return "\n".join(lines)


def build_owner_addons_active_keyboard(owner_user_id=None, group_id=None):

    keyboard = []

    if owner_user_id:

        products = {
            product.get("code"): product
            for product in fetch_owner_addon_products(active_only=False)
        }
        subscriptions = fetch_owner_addon_subscriptions_for_management(
            owner_user_id,
            group_id=group_id
        )

        for subscription in subscriptions[:15]:

            product = products.get(subscription.get("addon_code")) or {}
            product_name = product.get("name") or subscription.get("addon_code")

            keyboard.append([InlineKeyboardButton(
                f"Gestionar · {product_name}",
                callback_data=f"owner_addon_manage_{subscription.get('id')}"
            )])


    keyboard.extend([
        [InlineKeyboardButton("⬅️ Volver a servicios extra", callback_data="owner_addons_menu")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)






































def owner_can_use_ad_promo(user_id, group_id):

    if is_super_admin(user_id):

        return True, get_group_owner_user_id(group_id) if group_id else user_id


    if not group_id:

        return False, None


    if not user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):

        return False, get_group_owner_user_id(group_id)


    owner_user_id = get_group_owner_user_id(group_id)

    if not owner_user_id:

        return False, None


    return (
        owner_has_feature(
            owner_user_id,
            "ad_promo",
            group_id=group_id
        ),
        owner_user_id
    )


def build_ad_promo_owner_addon_required_text(group_id=None):

    lines = [
        "📣 Publicidad automática",
        "",
        "Este servicio es un extra mensual para dueños de comunidades.",
        "Permite publicar vídeos promocionales automáticamente.",
        "Incluye capturas, rotación, captions, diagnóstico y marca de agua.",
        "",
        "Para usarlo necesitas activar Publicidad automática o Pack Publicidad + Backups."
    ]

    products = [
        fetch_owner_addon_product("ad_promo"),
        fetch_owner_addon_product("bundle_ads_backups")
    ]
    products = [
        product
        for product in products
        if product and product.get("is_active")
    ]


    if products:

        lines.append("")
        lines.append("Servicios disponibles:")

        for product in products:

            lines.append(f"- {product.get('name')}: {format_owner_addon_price(product)}")


    return "\n".join(lines)


def build_ad_promo_owner_addon_required_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧩 Ver servicios extra", callback_data="owner_addons_menu")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def owner_can_use_backups(user_id, group_id):

    if is_super_admin(user_id):

        return True, get_group_owner_user_id(group_id) if group_id else user_id


    if not group_id:

        return False, None


    owner_user_id = get_group_owner_user_id(group_id)

    if not owner_user_id:

        return False, None


    if int(owner_user_id) != int(user_id) and not user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):

        return False, owner_user_id


    return (
        owner_has_feature(
            owner_user_id,
            "backups",
            group_id=group_id
        ),
        owner_user_id
    )


def build_owner_backup_addon_required_text(group_id=None):

    lines = [
        "💾 Backups automáticos",
        "",
        "Este servicio es un extra mensual para dueños de comunidades.",
        "Permite crear backups manuales y programar backups automáticos.",
        "Incluye configuración, resúmenes operativos, campañas, addons, encuestas y métricas.",
        "No incluye secretos, tokens, tarjetas ni enlaces completos de invitación.",
        "",
        "Para usarlo necesitas activar Backups automáticos o Pack Publicidad + Backups."
    ]

    products = [
        fetch_owner_addon_product("backups"),
        fetch_owner_addon_product("bundle_ads_backups")
    ]
    products = [
        product
        for product in products
        if product and product.get("is_active")
    ]


    if products:

        lines.append("")
        lines.append("Servicios disponibles:")

        for product in products:

            lines.append(f"- {product.get('name')}: {format_owner_addon_price(product)}")


    return "\n".join(lines)


def build_owner_backup_addon_required_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧩 Ver servicios extra", callback_data="owner_addons_menu")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def log_owner_backup_addon_gate(event_name, user_id, owner_user_id, group_id, action):

    log_event(
        event_name,
        category="backup",
        severity="info" if event_name.endswith("_allowed") else "warning",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=owner_user_id,
        message="Puerta de addon de backups evaluada.",
        metadata={
            "user_id": user_id,
            "owner_user_id": owner_user_id,
            "group_id": group_id,
            "callback": action,
            "required_feature": "backups"
        }
    )


























































async def receive_guardian_log_channel_forward(update, context):

    group_id = context.user_data.get("guardian_log_channel_group_id")
    user_id = update.effective_user.id if update.effective_user else None

    try:

        group_id = int(group_id)

    except Exception:

        context.user_data.pop("guardian_log_channel_group_id", None)

        await update.message.reply_text(
            "⚠️ No he podido resolver la comunidad para conectar Guardian."
        )

        return


    allowed, owner_user_id = owner_can_use_guardian(user_id, group_id)

    if not allowed:

        context.user_data.pop("guardian_log_channel_group_id", None)

        await update.message.reply_text(
            build_owner_guardian_addon_required_text(group_id),
            reply_markup=build_owner_guardian_addon_required_keyboard()
        )

        return


    forwarded_chat = extract_forwarded_chat_from_message(update.message)

    if not forwarded_chat or not forwarded_chat.get("chat_id"):

        await update.message.reply_text(
            "⚠️ Reenvía un mensaje del canal de logs para que pueda detectar el chat_id.",
            reply_markup=build_owner_guardian_cancel_keyboard(group_id)
        )

        return


    group = fetch_group_basic_info(group_id)
    telegram_group_id = group[2] if group else None

    ensure_guardian_settings(
        group_id,
        owner_user_id=owner_user_id,
        telegram_group_id=telegram_group_id
    )

    settings = update_guardian_log_channel(
        group_id,
        forwarded_chat.get("chat_id"),
        channel_title=forwarded_chat.get("title"),
        actor_user_id=user_id
    )

    context.user_data.pop("guardian_log_channel_group_id", None)

    log_event(
        "guardian_log_channel_connected",
        category="guardian",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=owner_user_id,
        message="Canal de logs Guardian conectado desde forward.",
        metadata={
            "group_id": group_id,
            "log_channel_id": forwarded_chat.get("chat_id"),
            "log_channel_title": forwarded_chat.get("title")
        }
    )

    await update.message.reply_text(
        "✅ Canal de logs Guardian conectado.\n\n"
        "Puedes enviar un log de prueba desde el panel.",
        reply_markup=build_owner_guardian_panel_keyboard(group_id)
    )

    await send_guardian_test_log(
        context,
        settings,
        group[1] if group else f"Grupo {group_id}",
        actor_user_id=user_id
    )


async def receive_guardian_forbidden_word_text(update, context):

    group_id = context.user_data.get("guardian_forbidden_word_add_group_id")
    user_id = update.effective_user.id if update.effective_user else None
    text = (update.message.text or "").strip() if update.message else ""

    try:

        group_id = int(group_id)

    except Exception:

        context.user_data.pop("guardian_forbidden_word_add_group_id", None)

        await update.message.reply_text(
            "⚠️ No he podido resolver la comunidad para añadir la palabra."
        )

        return


    if text.lower() in ("cancelar", "cancel", "salir"):

        context.user_data.pop("guardian_forbidden_word_add_group_id", None)

        await update.message.reply_text(
            "✅ Añadir palabra prohibida cancelado.",
            reply_markup=build_owner_guardian_forbidden_words_keyboard(group_id)
        )

        return


    allowed, owner_user_id = owner_can_use_guardian(user_id, group_id)

    if not allowed:

        context.user_data.pop("guardian_forbidden_word_add_group_id", None)

        await update.message.reply_text(
            build_owner_guardian_addon_required_text(group_id),
            reply_markup=build_owner_guardian_addon_required_keyboard()
        )

        return


    if not text or len(text) > 120:

        await update.message.reply_text(
            "⚠️ Envía una palabra o frase válida de hasta 120 caracteres.",
            reply_markup=build_owner_guardian_forbidden_words_cancel_keyboard(group_id)
        )

        return


    result = add_guardian_forbidden_word(
        group_id,
        text,
        action="log_only",
        created_by=user_id
    )
    context.user_data.pop("guardian_forbidden_word_add_group_id", None)

    await send_guardian_event_log(
        context,
        group_id,
        "guardian_forbidden_word_added",
        "Palabra prohibida añadida a Guardian.",
        severity="info",
        actor_user_id=user_id,
        target_user_id=owner_user_id,
        metadata={
            "word_id": result.get("id"),
            "action": result.get("action"),
            "created": result.get("created")
        }
    )

    await update.message.reply_text(
        f"✅ Palabra/frase añadida: {result.get('word')}",
        reply_markup=build_owner_guardian_forbidden_words_keyboard(group_id)
    )


async def receive_guardian_night_mode_time_text(update, context):

    group_id = context.user_data.get("guardian_night_mode_time_group_id")
    field = context.user_data.get("guardian_night_mode_time_field")
    user_id = update.effective_user.id if update.effective_user else None
    text = (update.message.text or "").strip() if update.message else ""

    try:

        group_id = int(group_id)

    except Exception:

        context.user_data.pop("guardian_night_mode_time_group_id", None)
        context.user_data.pop("guardian_night_mode_time_field", None)

        await update.message.reply_text(
            "⚠️ No he podido resolver la comunidad para configurar modo noche."
        )

        return


    if text.lower() in ("cancelar", "cancel", "salir"):

        context.user_data.pop("guardian_night_mode_time_group_id", None)
        context.user_data.pop("guardian_night_mode_time_field", None)

        await update.message.reply_text(
            "✅ Configuración de horario de modo noche cancelada.",
            reply_markup=build_owner_guardian_night_mode_keyboard(group_id)
        )

        return


    allowed, owner_user_id = owner_can_use_guardian(user_id, group_id)

    if not allowed:

        context.user_data.pop("guardian_night_mode_time_group_id", None)
        context.user_data.pop("guardian_night_mode_time_field", None)

        await update.message.reply_text(
            build_owner_guardian_addon_required_text(group_id),
            reply_markup=build_owner_guardian_addon_required_keyboard()
        )

        return


    if field not in ("start", "end") or not parse_guardian_hhmm(text):

        await update.message.reply_text(
            "⚠️ Envía una hora válida en formato HH:MM, por ejemplo 23:00.",
            reply_markup=build_owner_guardian_night_mode_cancel_keyboard(group_id)
        )

        return


    if field == "start":

        update_guardian_night_mode_settings(group_id, start_time=text)
        field_label = "inicio"

    else:

        update_guardian_night_mode_settings(group_id, end_time=text)
        field_label = "fin"


    context.user_data.pop("guardian_night_mode_time_group_id", None)
    context.user_data.pop("guardian_night_mode_time_field", None)

    await send_guardian_event_log(
        context,
        group_id,
        "guardian_night_mode_settings_updated",
        "Horario de modo noche actualizado.",
        severity="info",
        actor_user_id=user_id,
        target_user_id=owner_user_id,
        metadata={
            "field": field,
            "value": text
        }
    )

    await update.message.reply_text(
        f"✅ Hora de {field_label} actualizada: {text}",
        reply_markup=build_owner_guardian_night_mode_keyboard(group_id)
    )


def parse_ad_promo_callback_leading_int(data, prefix):

    if not data.startswith(prefix):

        return None


    value = data.replace(prefix, "", 1).split("_", 1)[0]

    return int(value) if value.isdigit() else None


def fetch_ad_promo_media_campaign_id(media_id):

    if not media_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT campaign_id
            FROM ad_promo_media
            WHERE id=%s
            LIMIT 1

        """, (media_id,))

        row = cur.fetchone()


    return row[0] if row else None


def fetch_ad_promo_copy_variant_campaign_id(variant_id):

    if not variant_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT campaign_id
            FROM ad_promo_copy_variants
            WHERE id=%s
            LIMIT 1

        """, (variant_id,))

        row = cur.fetchone()


    return row[0] if row else None


def resolve_ad_promo_group_id_for_callback(data, context):

    if data.startswith("admin_ad_promo_select_group_"):

        return extract_commercial_request_id(
            data,
            "admin_ad_promo_select_group_"
        )


    wizard = context.user_data.get("ad_promo_wizard") or {}
    wizard_data = wizard.get("data") or {}

    for key in (
        "paid_group_id",
        "selected_group_admin",
        "selected_owner_group"
    ):

        if key in wizard_data:

            return wizard_data.get(key)


    for prefix in (
        "admin_ad_promo_watermark_mode_",
        "admin_ad_promo_watermark_position_",
        "admin_ad_promo_watermark_text_",
        "admin_ad_promo_watermark_opacity_",
        "admin_ad_promo_watermark_limits_",
        "admin_ad_promo_watermark_test_",
        "admin_ad_promo_watermark_",
        "admin_ad_promo_diagnostics_",
        "admin_ad_promo_generate_captions_",
        "admin_ad_promo_copy_variants_",
        "ad_promo_regenerate_copy_yes_",
        "ad_promo_regenerate_copy_",
        "admin_ad_promo_optimize_rotation_",
        "admin_ad_promo_delete_campaign_yes_",
        "admin_ad_promo_delete_campaign_",
        "admin_ad_promo_campaign_",
        "admin_ad_promo_library_",
        "admin_ad_promo_random_",
        "admin_ad_promo_ai_",
        "admin_ad_promo_capture_",
        "admin_ad_promo_pause_",
        "admin_ad_promo_resume_",
        "admin_ad_promo_test_",
        "admin_ad_promo_delete_old_",
        "admin_ad_promo_edit_offer_",
        "admin_ad_promo_edit_price_",
        "admin_ad_promo_edit_cta_",
        "admin_ad_promo_edit_frequency_",
        "admin_ad_promo_edit_batch_",
        "admin_ad_promo_edit_maxposts_",
        "admin_ad_promo_edit_botlink_",
        "admin_ad_promo_keep_offer_"
    ):

        campaign_id = parse_ad_promo_callback_leading_int(data, prefix)

        if campaign_id:

            campaign = fetch_ad_promo_campaign(campaign_id)

            return campaign.get("paid_group_id") if campaign else None


    if data.startswith("admin_ad_promo_media_off_"):

        media_id = extract_commercial_request_id(data, "admin_ad_promo_media_off_")
        campaign_id = fetch_ad_promo_media_campaign_id(media_id)
        campaign = fetch_ad_promo_campaign(campaign_id) if campaign_id else None

        return campaign.get("paid_group_id") if campaign else None


    if data.startswith("admin_ad_promo_copy_off_"):

        variant_id = extract_commercial_request_id(data, "admin_ad_promo_copy_off_")
        campaign_id = fetch_ad_promo_copy_variant_campaign_id(variant_id)
        campaign = fetch_ad_promo_campaign(campaign_id) if campaign_id else None

        return campaign.get("paid_group_id") if campaign else None


    return get_selected_group_for_permissions(
        context,
        context.user_data.get("_ad_promo_gate_user_id"),
        ["can_manage_groups"]
    )


def should_log_ad_promo_owner_addon_gate(data):

    if data in (
        "admin_ad_promo",
        "admin_ad_promo_campaigns",
        "admin_ad_promo_create"
    ):

        return True


    return any(data.startswith(prefix) for prefix in (
        "admin_ad_promo_select_group_",
        "admin_ad_promo_campaign_",
        "admin_ad_promo_library_",
        "admin_ad_promo_diagnostics_",
        "admin_ad_promo_test_",
        "admin_ad_promo_watermark_",
        "admin_ad_promo_delete_campaign_",
        "admin_ad_promo_generate_captions_",
        "ad_promo_regenerate_copy_",
        "admin_ad_promo_optimize_rotation_"
    ))


def is_ad_promo_ui_callback(data):

    return data == "admin_ad_promo" or data.startswith("admin_ad_promo_") or data.startswith("ad_promo_regenerate_copy_")


async def enforce_ad_promo_owner_addon_gate(query, context, data, user_id):

    if not is_ad_promo_ui_callback(data):

        return True


    if is_super_admin(user_id):

        return True


    context.user_data["_ad_promo_gate_user_id"] = user_id
    group_id = resolve_ad_promo_group_id_for_callback(data, context)
    context.user_data.pop("_ad_promo_gate_user_id", None)


    if not group_id:

        await query.message.reply_text(
            "⚠️ No he podido identificar la comunidad para esta acción de publicidad automática.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return False


    try:

        group_id = int(group_id)

    except Exception:

        await query.message.reply_text(
            "⚠️ La comunidad asociada a esta acción no es válida.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return False


    if not user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):

        await query.message.reply_text(
            "⛔ No tienes permiso para gestionar publicidad automática de esta comunidad.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return False


    allowed, owner_user_id = owner_can_use_ad_promo(user_id, group_id)
    metadata = {
        "user_id": user_id,
        "owner_user_id": owner_user_id,
        "group_id": group_id,
        "callback_data": data[:120],
        "required_feature": "ad_promo"
    }


    if allowed:

        if should_log_ad_promo_owner_addon_gate(data):

            log_event(
                "ad_promo_owner_addon_allowed",
                category="marketing",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Acceso a publicidad automática permitido por addon owner.",
                metadata=metadata
            )


        return True


    if should_log_ad_promo_owner_addon_gate(data):

        log_event(
            "ad_promo_owner_addon_required",
            category="marketing",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Publicidad automática requiere addon owner activo.",
            metadata=metadata
        )


    await send_clean_message(
        context,
        query.message.chat_id,
        build_ad_promo_owner_addon_required_text(group_id),
        reply_markup=build_ad_promo_owner_addon_required_keyboard()
    )

    return False


def build_owner_section_keyboard(user_id, group_id, section):

    keyboard = []


    if section == "users":

        if user_can_view_community_users(user_id, group_id):
            keyboard.append([InlineKeyboardButton("📋 Ver usuarios de esta comunidad", callback_data=f"owner_group_users_{group_id}")])

            if fetch_free_community_for_known_user_sync(group_id):
                keyboard.append([InlineKeyboardButton("🔄 Sincronizar usuarios conocidos", callback_data=f"community_users_sync_known_{group_id}")])

        if user_has_group_permission_any(user_id, group_id, ["can_kick_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("🚫 Expulsar usuario", callback_data="admin_kick_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_ban_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("⛔ Banear usuario", callback_data="admin_ban_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_unban_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("♻️ Desbanear usuario", callback_data="admin_unban_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_warn_users", "can_reset_warnings", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("⚠️ Warnings", callback_data="admin_reset_warnings")])

        if user_can_recover_community_access_links(user_id, group_id):
            keyboard.append([InlineKeyboardButton("📩 Reenviar / recuperar link", callback_data=f"community_links_recover_menu_{group_id}")])

    elif section == "codes":

        keyboard.extend([
            [InlineKeyboardButton("🎟 Códigos de mi grupo", callback_data="edit_group_user_codes")],
            [InlineKeyboardButton("➕ Crear código", callback_data="group_user_code_create")],
            [InlineKeyboardButton("📋 Ver códigos activos", callback_data="group_user_codes_active")],
            [InlineKeyboardButton("📊 Usos de códigos", callback_data="group_user_code_usage")],
            [InlineKeyboardButton("🚫 Desactivar código", callback_data="group_user_code_deactivate_menu")]
        ])

    elif section == "payments":

        owner_can_manage_payment_methods = is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id


        if user_has_group_permission_any(user_id, group_id, ["can_manage_plans", "can_manage_groups"]):
            keyboard.append([InlineKeyboardButton("📋 Ver planes", callback_data="view_group_plans")])
            keyboard.append([InlineKeyboardButton("💳 Crear/editar planes", callback_data="edit_group_plans")])


        if owner_can_manage_payment_methods:
            keyboard.extend([
                [InlineKeyboardButton("💳 Stripe", callback_data="edit_group_stripe")],
                [InlineKeyboardButton("🅿️ PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")],
                [InlineKeyboardButton("🏦 Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")],
                [InlineKeyboardButton("💱 ChangeNOW.io / Cripto", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")],
                [InlineKeyboardButton("💳 Tarjeta EUR → USDT / Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")],
                [InlineKeyboardButton("🎟 Códigos y promociones", callback_data="owner_panel_codes")],
                [InlineKeyboardButton("🏷 Cupones de descuento (Stripe)", callback_data="owner_stripe_coupons")],
                [InlineKeyboardButton("🏦 Cobrar en MI cuenta (Stripe Connect)", callback_data="owner_stripe_connect")]
            ])


        if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]) and not owner_can_manage_payment_methods:
            keyboard.append([InlineKeyboardButton("🔗 Estado Stripe", callback_data="edit_group_stripe")])

        if owner_can_manage_payment_methods:
            keyboard.append([InlineKeyboardButton("💳 Métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")])

        if user_has_group_permission_any(user_id, group_id, ["can_view_payments", "can_manage_payments"]):
            keyboard.append([InlineKeyboardButton("💳 Pagos recibidos", callback_data=f"owner_group_payments_{group_id}")])
            keyboard.append([InlineKeyboardButton("📌 Suscripciones activas", callback_data=f"owner_group_subscriptions_{group_id}")])

    elif section == "security":

        # Guardian es el motor real de antispam / antienlaces / modo noche y
        # antes no aparecía aquí (estaba en un bloque inalcanzable), mientras
        # que "Anti-intrusos" y "Anti-links" eran dos botones distintos que
        # abrían exactamente la misma pantalla.
        if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):

            keyboard.append([InlineKeyboardButton(
                "🛡 Guardian (antispam y enlaces)",
                callback_data="owner_panel_guardian"
            )])

            keyboard.append([InlineKeyboardButton(
                "🔎 Resumen de seguridad",
                callback_data="owner_panel_security_info"
            )])

            keyboard.append([InlineKeyboardButton(
                "📍 Ubicación permitida",
                callback_data="owner_panel_location_info"
            )])

            if should_show_owner_location_reviews_button(group_id):

                keyboard.append([InlineKeyboardButton(
                    "📍 Revisiones de ubicación",
                    callback_data=f"owner_location_reviews_{group_id}"
                )])


            keyboard.append([InlineKeyboardButton(
                "📢 Grupos de publicidad",
                callback_data=f"owner_publicity_group_{group_id}"
            )])


        if user_has_group_permission_any(user_id, group_id, ["can_view_logs"]):

            keyboard.append([InlineKeyboardButton(
                "📜 Logs de accesos",
                callback_data=f"owner_group_logs_access_{group_id}"
            )])

    elif section == "marketplace":

        # Antes había tres botones distintos ("Editar preview", "Preview
        # manual/dinámico/mixto" y "Categoría/tags") que abrían la misma
        # pantalla. Se deja uno solo, con el nombre de lo que hace de verdad.
        keyboard.extend([
            [InlineKeyboardButton("🌐 Publicación", callback_data=f"owner_group_publication_{group_id}")],
            [InlineKeyboardButton("✏️ Editar ficha (nombre y descripción)", callback_data="edit_group_name")],
            [InlineKeyboardButton("🎬 Preview, categoría y etiquetas", callback_data="edit_group_preview")]
        ])

    elif section == "admins":

        keyboard.extend([
            [InlineKeyboardButton("👑 Administradores", callback_data="edit_group_admins")],
            [InlineKeyboardButton("➕ Añadir admin", callback_data="group_admin_add")],
            [InlineKeyboardButton("📋 Ver admins", callback_data="group_admin_view")],
            [InlineKeyboardButton("✏️ Editar permisos", callback_data="group_admin_edit")],
            [InlineKeyboardButton("❌ Quitar admin", callback_data="group_admin_remove")]
        ])

    elif section == "logs":

        keyboard.extend([
            [InlineKeyboardButton("📜 Actividad reciente", callback_data=f"owner_group_logs_all_{group_id}")],
            [InlineKeyboardButton("👥 Accesos", callback_data=f"owner_group_logs_access_{group_id}")],
            [InlineKeyboardButton("💳 Pagos", callback_data=f"owner_group_logs_payment_{group_id}")],
            [InlineKeyboardButton("🛟 Soporte", callback_data=f"owner_group_logs_support_{group_id}")],
            [InlineKeyboardButton("🛡 Seguridad / errores", callback_data=f"owner_group_logs_security_{group_id}")]
        ])

    elif section == "support":

        keyboard.append([InlineKeyboardButton("🛟 Ver solicitudes de soporte", callback_data="owner_support_tickets")])

        if should_show_owner_location_reviews_button(group_id):

            keyboard.append([InlineKeyboardButton(
                "📍 Revisiones de ubicación",
                callback_data=f"owner_location_reviews_{group_id}"
            )])


        keyboard.append([InlineKeyboardButton("💬 Abrir soporte sobre esta comunidad", callback_data=f"public_support_group_{group_id}")])

    elif section == "backup":

        keyboard.extend([
            [InlineKeyboardButton("🛡 Estado backup", callback_data="owner_backup_panel")],
            [InlineKeyboardButton("🔗 Configurar origen/destino", callback_data="owner_backup_destination_token")],
            [InlineKeyboardButton("⚙️ Cambiar modo", callback_data="owner_backup_change_mode")],
            [InlineKeyboardButton("📜 Últimos mensajes copiados", callback_data="owner_backup_messages")],
            [InlineKeyboardButton("⚠️ Últimos errores", callback_data="owner_backup_errors")]
        ])

    elif section == "general":

        # "Nombre comunidad" y "Descripción" abrían la misma pantalla, igual
        # que "Cupo/configuración" y "Reiniciar configuración segura".
        keyboard.extend([
            [InlineKeyboardButton("✏️ Nombre y descripción", callback_data="edit_group_name")],
            [InlineKeyboardButton("🔓 Tipo gratis/pago", callback_data="owner_panel_commercial_config")],
            [InlineKeyboardButton("🔢 Cupo y configuración", callback_data="owner_panel_general_info")]
        ])


    keyboard.append([
        InlineKeyboardButton("❓ Ayuda", callback_data=f"owner_panel_help_{section}")
    ])

    keyboard.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return InlineKeyboardMarkup(keyboard)










def list_manageable_group_ids(user_id, permissions):
    """Comunidades sobre las que este usuario puede actuar."""

    group_ids = get_admin_group_ids(user_id, permissions)


    # get_admin_group_ids devuelve None para el super admin: puede con todas.
    if group_ids is None:

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id
                    FROM groups
                    WHERE COALESCE(is_active, TRUE)=TRUE
                    ORDER BY id

                """)

                return [row[0] for row in cur.fetchall() if row[0]]

        except Exception as e:

            print("Error listando comunidades administrables:", e)
            return []


    return list(group_ids or [])


def get_selected_group_for_permissions(context, user_id, permissions):

    for key in (
        "selected_group_admin",
        "selected_group_user_codes",
        "group_user_promo_group_id",
        "selected_owner_group"
    ):

        group_id = context.user_data.get(key)


        if not group_id:

            continue


        try:

            group_id = int(group_id)

        except Exception:

            continue


        if user_has_group_permission_any(user_id, group_id, permissions):

            return group_id


    # No hay comunidad seleccionada. Esto pasa constantemente porque el estado
    # de la conversación se pierde en cada reinicio del bot, y hacía que
    # incluso el propietario principal viera "no tienes permiso" cuando en
    # realidad solo faltaba saber SOBRE QUÉ comunidad actuar.
    # Si solo hay una comunidad posible, no hay ambigüedad: se usa esa.

    manageable = list_manageable_group_ids(user_id, permissions)


    if len(manageable) == 1:

        group_id = int(manageable[0])
        context.user_data["selected_group_admin"] = group_id

        return group_id


    return None


def user_can_view_group_panel(user_id, group_id, permissions=None):

    if not group_id:

        return False


    return user_has_group_permission_any(
        user_id,
        group_id,
        permissions or [
            "can_manage_groups",
            "can_view_logs",
            "can_respond_group_support"
        ]
    )


def build_owner_location_management_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Activar ubicación", callback_data=f"owner_location_enable_{group_id}")],
        [InlineKeyboardButton("🚫 Desactivar ubicación", callback_data=f"owner_location_disable_{group_id}")],
        [InlineKeyboardButton("🇪🇸 Toda España", callback_data=f"owner_location_country_set_{group_id}_ES")],
        [InlineKeyboardButton("📍 Comunidad Valenciana", callback_data=f"owner_location_region_set_{group_id}_{COMUNIDAD_VALENCIANA_REGION}")],
        [InlineKeyboardButton("📂 Elegir comunidad autónoma", callback_data=f"owner_location_regions_{group_id}")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="owner_panel_help_security")],
        [InlineKeyboardButton("⬅️ Volver a seguridad", callback_data="owner_panel_security")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])




def build_owner_location_management_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    enabled, allowed_region, region_type = get_group_location_gate(group_id)
    region_label = format_allowed_region(region_type, allowed_region)
    status = "Activada" if enabled else "Desactivada"

    return (
        "📍 Ubicación permitida\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n"
        f"Estado: {status}\n"
        f"Regla actual: {region_label}\n\n"
        "Esto pide al usuario una ubicación real de Telegram antes de generar el link de acceso. "
        "No se aceptan ciudades escritas manualmente y no se guardan coordenadas exactas.\n\n"
        "Puedes activar/desactivar la restricción o cambiar la región permitida. "
        "Cada cambio queda registrado en logs."
    )




















COMMUNITY_USERS_PAGE_SIZE = 6


def user_can_view_community_users(user_id, group_id):

    if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:

        return True


    return user_has_group_permission_any(user_id, group_id, ["can_view_users", "can_manage_users", "can_manage_groups"])




def user_can_recover_community_access_links(user_id, group_id):

    if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:

        return True


    return user_has_group_permission_any(
        user_id,
        group_id,
        ["can_resend_links", "can_recover_access", "can_manage_users"]
    )








def fetch_free_community_for_known_user_sync(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       (
                           COALESCE(is_free_group, FALSE)
                           OR COALESCE(is_free, FALSE)
                       )
                FROM groups
                WHERE id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                LIMIT 1

            """, (group_id,))

            row = cur.fetchone()

    except Exception as e:

        try:

            conn.rollback()

        except Exception:

            pass

        print("free_community_sync_group_lookup_error:", str(e)[:300])
        return None


    if not row or row[3] is not True:

        return None


    return {
        "group_id": row[0],
        "name": row[1],
        "telegram_group_id": row[2],
        "is_free_group": row[3] is True
    }


def parse_community_user_callback(data, prefix, include_days=False):

    if not data.startswith(prefix):

        return None


    parts = data.replace(prefix, "", 1).split("_")
    expected = 3 if include_days else 2


    if len(parts) != expected or not all(part.isdigit() for part in parts):

        return None


    return tuple(int(part) for part in parts)


def format_community_user_display_name(row):

    if row.get("username"):

        return f"@{row.get('username')}"


    if row.get("first_name"):

        return row.get("first_name")


    return f"ID {row.get('user_id')}"


def format_community_user_access_type(access_state):

    if access_state.get("is_group_owner"):

        return "owner"


    if access_state.get("subscription_status") == "paid_without_access_record":

        return "pagado (revisar acceso)"


    if access_state.get("has_active_access") and not access_state.get("expires_at"):

        return "permanente/free"


    labels = {
        "paid": "pagado",
        "free": "free",
        "code": "código",
        "telegram_member": "miembro Telegram",
        "unknown": "manual"
    }

    return labels.get(access_state.get("access_source"), access_state.get("access_source") or "manual")


def log_community_users_source_error(source, error):

    try:

        conn.rollback()

    except Exception:

        pass


    print(f"community_users_panel_source_error[{source}]:", str(error)[:500])


def extract_known_user_from_metadata(metadata):

    if not isinstance(metadata, dict):

        return {}


    nested_metadata = metadata.get("metadata")

    if isinstance(nested_metadata, dict):

        metadata = {
            **nested_metadata,
            **metadata
        }


    return {
        "username": metadata.get("username"),
        "first_name": metadata.get("first_name")
    }


def merge_known_free_user(known_users, user_id, username=None, first_name=None):

    if not user_id:

        return


    try:

        user_id = int(user_id)

    except Exception:

        return


    if user_id <= 0:

        return


    current = known_users.setdefault(user_id, {
        "user_id": user_id,
        "username": None,
        "first_name": None
    })

    if username and not current.get("username"):

        current["username"] = username

    if first_name and not current.get("first_name"):

        current["first_name"] = first_name


def log_free_community_sync_source_error(source, error, group_id, telegram_group_id=None):

    try:

        conn.rollback()

    except Exception:

        pass


    print(f"free_community_known_users_sync_source_error[{source}]:", str(error)[:500])
    log_event(
        "free_community_known_users_sync_source_error",
        category="access",
        severity="warning",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        message="No se pudo leer una fuente de usuarios conocidos para comunidad gratis.",
        metadata={
            "source": source,
            "error": str(error)[:500]
        }
    )


def collect_known_free_community_users(group_id, telegram_group_id):

    known_users = {}
    relevant_audit_events = (
        "user_join_detected",
        "access_unauthorized",
        "publicity_invite_join_detected",
        "publicity_invite_link_missing_on_join",
        "publicity_invite_link_not_matched"
    )


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT actor_user_id,
                       target_user_id,
                       metadata
                FROM audit_logs
                WHERE group_id=%s
                AND (
                    telegram_group_id=%s
                    OR telegram_group_id IS NULL
                )
                AND event_type = ANY(%s)
                AND (
                    actor_user_id IS NOT NULL
                    OR target_user_id IS NOT NULL
                )

            """, (
                group_id,
                telegram_group_id,
                list(relevant_audit_events)
            ))

            for actor_user_id, target_user_id, metadata in cur.fetchall():

                profile = extract_known_user_from_metadata(metadata)
                merge_known_free_user(
                    known_users,
                    target_user_id or actor_user_id,
                    profile.get("username"),
                    profile.get("first_name")
                )

    except Exception as e:

        log_free_community_sync_source_error(
            "audit_logs",
            e,
            group_id,
            telegram_group_id
        )


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id,
                       username,
                       first_name
                FROM bot_user_events
                WHERE group_id=%s
                AND user_id IS NOT NULL
                AND (
                    event_type = ANY(%s)
                    OR event_key = ANY(%s)
                )

            """, (
                group_id,
                list(relevant_audit_events),
                list(relevant_audit_events)
            ))

            for user_id, username, first_name in cur.fetchall():

                merge_known_free_user(
                    known_users,
                    user_id,
                    username,
                    first_name
                )

    except Exception as e:

        log_free_community_sync_source_error(
            "bot_user_events",
            e,
            group_id,
            telegram_group_id
        )


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id,
                       metadata
                FROM beta_monitor_events
                WHERE group_id=%s
                AND (
                    telegram_group_id=%s
                    OR telegram_group_id IS NULL
                )
                AND event_type='unauthorized_access'
                AND user_id IS NOT NULL

            """, (
                group_id,
                telegram_group_id
            ))

            for user_id, metadata in cur.fetchall():

                profile = extract_known_user_from_metadata(metadata)
                merge_known_free_user(
                    known_users,
                    user_id,
                    profile.get("username"),
                    profile.get("first_name")
                )

    except Exception as e:

        log_free_community_sync_source_error(
            "beta_monitor_events",
            e,
            group_id,
            telegram_group_id
        )


    return known_users


def sync_known_free_community_users(group_id, telegram_group_id, actor_user_id, bot_user_id=None):

    group = fetch_free_community_for_known_user_sync(group_id)


    if not group or group.get("telegram_group_id") != telegram_group_id:

        return {
            "ok": False,
            "reason": "not_free_group",
            "found_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "error_count": 0
        }


    log_event(
        "free_community_known_users_sync_started",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=actor_user_id,
        message="Sincronización de usuarios conocidos de comunidad gratis iniciada."
    )

    known_users = collect_known_free_community_users(
        group_id,
        telegram_group_id
    )
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    error_count = 0
    users_total_after_sync = None
    users_free_active_after_sync = None


    for known_user in known_users.values():

        target_user_id = known_user.get("user_id")


        if not target_user_id:

            skipped_count += 1
            continue


        if bot_user_id and target_user_id == bot_user_id:

            skipped_count += 1
            continue


        if target_user_id == ADMIN_ID:

            skipped_count += 1
            continue


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE users
                    SET username=COALESCE(%s, username),
                        first_name=COALESCE(%s, first_name),
                        expiration=NULL,
                        subscription_active=TRUE
                    WHERE user_id=%s
                    AND group_id=%s

                """, (
                    known_user.get("username"),
                    known_user.get("first_name"),
                    target_user_id,
                    group_id
                ))

                if cur.rowcount > 0:

                    updated_count += cur.rowcount

                else:

                    cur.execute("""

                        INSERT INTO users
                        (
                            user_id,
                            group_id,
                            username,
                            first_name,
                            expiration,
                            subscription_active
                        )
                        VALUES (%s, %s, %s, %s, NULL, TRUE)

                    """, (
                        target_user_id,
                        group_id,
                        known_user.get("username"),
                        known_user.get("first_name")
                    ))

                    inserted_count += 1

                conn.commit()

            log_event(
                "free_community_known_user_registered",
                category="access",
                severity="info",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                message="Usuario conocido sincronizado como acceso gratuito/permanente.",
                metadata={
                    "username": known_user.get("username"),
                    "first_name": known_user.get("first_name")
                }
            )

        except Exception as e:

            try:

                conn.rollback()

            except Exception:

                pass

            error_count += 1
            log_event(
                "free_community_known_user_register_failed",
                category="access",
                severity="error",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                message="No se pudo sincronizar usuario conocido de comunidad gratis.",
                metadata={
                    "error": str(e)[:500]
                }
            )


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM users
                WHERE group_id=%s

            """, (group_id,))
            users_total_after_sync = cur.fetchone()[0]

            cur.execute("""

                SELECT COUNT(*)
                FROM users
                WHERE group_id=%s
                AND COALESCE(subscription_active, FALSE)=TRUE
                AND expiration IS NULL

            """, (group_id,))
            users_free_active_after_sync = cur.fetchone()[0]

    except Exception as e:

        try:

            conn.rollback()

        except Exception:

            pass

        print("free_community_known_users_sync_count_error:", str(e)[:500])


    result = {
        "ok": True,
        "found_count": len(known_users),
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "users_total_after_sync": users_total_after_sync,
        "users_free_active_after_sync": users_free_active_after_sync
    }

    log_event(
        "free_community_known_users_sync_completed",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=actor_user_id,
        message="Sincronización de usuarios conocidos de comunidad gratis terminada.",
        metadata=result
    )

    return result


def fetch_community_user_rows(group_id):

    user_ids = set()
    profiles = {}
    users_source_count = 0
    group = fetch_free_community_for_known_user_sync(group_id)
    is_free_group = bool(group)


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id,
                       username,
                       first_name,
                       expiration,
                       COALESCE(subscription_active, FALSE)
                FROM users
                WHERE group_id=%s

            """, (group_id,))


            for row in cur.fetchall():

                if not row[0]:

                    continue


                users_source_count += 1
                user_ids.add(row[0])
                profiles[row[0]] = {
                    "user_id": row[0],
                    "username": row[1],
                    "first_name": row[2],
                    "expiration": row[3],
                    "subscription_active": row[4],
                    "created_at": None
                }

    except Exception as e:

        log_community_users_source_error("users", e)


    for table_name in ("subscriptions", "payment_transactions", "payments", "invite_links"):

        try:

            with conn.cursor() as cur:

                cur.execute(f"""

                    SELECT DISTINCT user_id
                    FROM {table_name}
                    WHERE group_id=%s
                    AND user_id IS NOT NULL

                """, (group_id,))
                user_ids.update(row[0] for row in cur.fetchall() if row and row[0])

        except Exception as e:

            log_community_users_source_error(table_name, e)


    rows = []


    for target_user_id in sorted(user_ids):

        row = profiles.get(target_user_id) or {
            "user_id": target_user_id,
            "username": None,
            "first_name": None,
            "expiration": None,
            "subscription_active": False,
            "created_at": None
        }

        access_state = None

        try:

            access_state = get_user_group_access_state(target_user_id, group_id)

        except Exception as e:

            try:

                conn.rollback()

            except Exception:

                pass

            print("community_user_access_state_error:", str(e)[:500])
            log_event(
                "community_user_access_state_error",
                category="access",
                severity="warning",
                scope="group",
                group_id=group_id,
                target_user_id=target_user_id,
                message="No se pudo resolver estado de acceso para usuario de comunidad.",
                metadata={"error": str(e)[:500]}
            )
            access_state = {
                "has_active_access": False,
                "access_source": "unknown",
                "subscription_status": "unknown",
                "expires_at": None
            }

        try:

            conn.rollback()

        except Exception as e:

            print("community_users_access_state_cleanup_error:", str(e)[:200])

        row["access_state"] = access_state
        row["is_active"] = bool(access_state.get("has_active_access"))
        row["expires_at"] = access_state.get("expires_at") or row.get("expiration")
        row["access_type"] = format_community_user_access_type(access_state)

        local_expiration = row.get("expiration")
        local_active = bool(row.get("subscription_active")) and (
            local_expiration is None or local_expiration > datetime.now()
        )

        if is_free_group and local_active and not row["is_active"]:

            row["is_active"] = True
            row["expires_at"] = local_expiration
            row["access_type"] = "permanente/free"
            row["access_state"] = {
                **(access_state or {}),
                "has_active_access": True,
                "access_source": "free",
                "subscription_status": "active",
                "expires_at": local_expiration,
                "reason": "local_free_access"
            }


        if (
            access_state.get("subscription_status") == "paid_without_access_record"
            and not row["is_active"]
        ):

            row["is_active"] = True
            row["access_type"] = "pagado (revisar acceso)"
            row["access_state"] = {
                **(access_state or {}),
                "has_active_access": True,
                "access_source": "paid",
                "subscription_status": "paid_without_access_record",
                "reason": "paid_without_access_record"
            }

        rows.append(row)


    rows.sort(key=lambda item: (0 if item.get("is_active") else 1, item.get("expires_at") or datetime.max, item.get("user_id") or 0))

    active_count = sum(1 for row in rows if row.get("is_active"))
    inactive_count = len(rows) - active_count
    log_event(
        "community_users_panel_debug_counts",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        message="Conteos internos del panel de usuarios de comunidad.",
        metadata={
            "users_source_count": users_source_count,
            "user_ids_count": len(user_ids),
            "active_count": active_count,
            "inactive_count": inactive_count,
            "is_free_group": is_free_group
        }
    )

    return rows


def build_community_users_page(group_id, segment="active", page=0):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    rows = fetch_community_user_rows(group_id)
    active_rows = [row for row in rows if row.get("is_active")]
    inactive_rows = [row for row in rows if not row.get("is_active")]
    selected_rows = active_rows if segment == "active" else inactive_rows
    total_pages = max(1, (len(selected_rows) + COMMUNITY_USERS_PAGE_SIZE - 1) // COMMUNITY_USERS_PAGE_SIZE)
    page = max(0, min(int(page or 0), total_pages - 1))
    offset = page * COMMUNITY_USERS_PAGE_SIZE
    page_rows = selected_rows[offset:offset + COMMUNITY_USERS_PAGE_SIZE]
    segment_title = "✅ Usuarios con acceso activo" if segment == "active" else "⚠️ Usuarios sin acceso activo / expirado"
    text = (
        f"👥 Usuarios de {group_name or f'Grupo {group_id}'}\n\n"
        f"✅ Activos: {len(active_rows)}\n"
        f"⚠️ Inactivos/expirados: {len(inactive_rows)}\n\n"
        f"{segment_title}\n"
        f"Página {page + 1}/{total_pages}\n\n"
    )


    if not page_rows:

        if not rows:

            text += "No hay usuarios registrados en esta comunidad todavía."

        else:

            text += "No hay usuarios en esta sección."

    else:

        for index, row in enumerate(page_rows, start=offset + 1):

            access_state = row.get("access_state") or {}
            expires_at = row.get("expires_at")
            expires_text = "permanente" if row.get("is_active") and not expires_at else format_commercial_datetime(expires_at)
            status_text = "activo" if row.get("is_active") else access_state.get("subscription_status") or "inactivo"
            text += (
                f"{index}. {format_community_user_display_name(row)} / ID: {row.get('user_id')}\n"
                f"Estado: {status_text}\n"
                f"Expira: {expires_text}\n"
                f"Tipo: {row.get('access_type')}\n\n"
            )


    keyboard = [[InlineKeyboardButton(
        "⚠️ Ver inactivos/expirados" if segment == "active" else "✅ Ver activos",
        callback_data=f"community_users_{group_id}_{'inactive' if segment == 'active' else 'active'}_0"
    )]]


    for row in page_rows:

        keyboard.append([InlineKeyboardButton(
            f"Gestionar · {format_community_user_display_name(row)}",
            callback_data=f"community_user_manage_{group_id}_{row.get('user_id')}"
        )])


    nav_row = []


    if page > 0:

        nav_row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"community_users_{group_id}_{segment}_{page - 1}"))


    if page + 1 < total_pages:

        nav_row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"community_users_{group_id}_{segment}_{page + 1}"))


    if nav_row:

        keyboard.append(nav_row)


    keyboard.append([InlineKeyboardButton("⬅️ Volver a usuarios y accesos", callback_data="owner_panel_users")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return text, InlineKeyboardMarkup(keyboard)


def fetch_community_user_profile(group_id, target_user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT username,
                   first_name,
                   expiration,
                   COALESCE(subscription_active, FALSE)
            FROM users
            WHERE user_id=%s
            AND group_id=%s
            LIMIT 1

        """, (target_user_id, group_id))
        row = cur.fetchone()


    return {
        "user_id": target_user_id,
        "username": row[0] if row else None,
        "first_name": row[1] if row else None,
        "expiration": row[2] if row else None,
        "subscription_active": row[3] if row else False
    }


def build_community_user_manage_keyboard(group_id, target_user_id, actor_user_id=None):

    keyboard = [
        [
            InlineKeyboardButton("+1 día", callback_data=f"community_user_add_days_{group_id}_{target_user_id}_1"),
            InlineKeyboardButton("+15 días", callback_data=f"community_user_add_days_{group_id}_{target_user_id}_15"),
            InlineKeyboardButton("+30 días", callback_data=f"community_user_add_days_{group_id}_{target_user_id}_30")
        ],
        [
            InlineKeyboardButton("-1 día", callback_data=f"community_user_subtract_days_{group_id}_{target_user_id}_1"),
            InlineKeyboardButton("-15 días", callback_data=f"community_user_subtract_days_{group_id}_{target_user_id}_15"),
            InlineKeyboardButton("-30 días", callback_data=f"community_user_subtract_days_{group_id}_{target_user_id}_30")
        ],
        [InlineKeyboardButton("🚫 Revocar acceso", callback_data=f"community_user_revoke_access_{group_id}_{target_user_id}")],
        [InlineKeyboardButton("🗑 Eliminar usuario de BD", callback_data=f"community_user_delete_{group_id}_{target_user_id}")]
    ]

    if actor_user_id and user_can_view_guardian_warnings(actor_user_id, group_id):

        guardian_allowed, _ = owner_can_use_guardian(actor_user_id, group_id)

        if guardian_allowed:

            keyboard.append([InlineKeyboardButton("⚠️ Guardian warnings", callback_data=f"guardian_user_warnings_{group_id}_{target_user_id}")])

    keyboard.append([InlineKeyboardButton("⬅️ Volver a lista", callback_data=f"community_users_{group_id}_active_0")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)














def fetch_recent_community_access_invite_link(group_id, target_user_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                AND (
                    created_at IS NULL
                    OR created_at > NOW() - INTERVAL '150 seconds'
                )
                ORDER BY created_at DESC NULLS LAST
                LIMIT 1

            """, (target_user_id, group_id))

            row = cur.fetchone()

    except Exception as e:

        try:

            conn.rollback()

        except Exception:

            pass

        print("community_link_recover_existing_lookup_error:", str(e)[:300])
        return None


    return row[0] if row else None


def save_community_access_invite_link(group_id, telegram_group_id, target_user_id, invite_link, access_state):

    expires_at = access_state.get("expires_at") if access_state else None

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE invite_links
            SET telegram_group_id=%s,
                invite_link=%s,
                is_active=TRUE,
                revoked_at=NULL
            WHERE user_id=%s
            AND group_id=%s

        """, (
            telegram_group_id,
            invite_link,
            target_user_id,
            group_id
        ))


        if cur.rowcount == 0:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, telegram_group_id, invite_link, is_active)
                VALUES (%s, %s, %s, %s, TRUE)

            """, (
                target_user_id,
                group_id,
                telegram_group_id,
                invite_link
            ))


        cur.execute("""

            UPDATE users
            SET expiration=%s,
                subscription_active=TRUE,
                last_invite_link=%s
            WHERE user_id=%s
            AND group_id=%s

        """, (
            expires_at,
            invite_link,
            target_user_id,
            group_id
        ))


        if cur.rowcount == 0:

            cur.execute("""

                INSERT INTO users
                (
                    user_id,
                    group_id,
                    expiration,
                    subscription_active,
                    last_invite_link
                )
                VALUES (%s, %s, %s, TRUE, %s)

            """, (
                target_user_id,
                group_id,
                expires_at,
                invite_link
            ))


    conn.commit()


def log_community_link_recover_generation_failed(group_id, telegram_group_id, target_user_id, reason, access_state=None, error=None, telegram_response=None):

    metadata = {
        "group_id": group_id,
        "telegram_group_id": telegram_group_id,
        "target_user_id": target_user_id,
        "has_active_access": bool((access_state or {}).get("has_active_access")),
        "reason": reason,
        "error": str(error)[:500] if error else None
    }


    if telegram_response:

        # Solo campos seguros: nunca guardar la respuesta completa ni invite_link.
        metadata["telegram_response_ok"] = telegram_response.get("response_ok")
        metadata["telegram_response_description"] = str(telegram_response.get("description") or "")[:500]
        metadata["telegram_error_code"] = telegram_response.get("error_code")
        metadata["retry_after"] = telegram_response.get("retry_after")


    log_event(
        "community_link_recover_generation_failed",
        category="access",
        severity="warning",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        target_user_id=target_user_id,
        message="No se pudo generar link de recuperación de acceso.",
        metadata=metadata
    )


def recover_or_create_community_access_link(group_id, target_user_id):

    group = fetch_group_basic_info(group_id)

    if not group:

        log_community_link_recover_generation_failed(
            group_id,
            None,
            target_user_id,
            "group_not_found"
        )

        return {"ok": False, "reason": "group_not_found"}


    _group_id, group_name, telegram_group_id, community_type = group

    if not telegram_group_id:

        log_community_link_recover_generation_failed(
            group_id,
            telegram_group_id,
            target_user_id,
            "missing_telegram_group_id"
        )

        return {"ok": False, "reason": "missing_telegram_group_id"}


    access_state = get_user_group_access_state(target_user_id, group_id)

    if (
        not access_state.get("has_active_access")
        and access_state.get("subscription_status") == "paid_without_access_record"
    ):

        log_community_link_recover_generation_failed(
            group_id,
            telegram_group_id,
            target_user_id,
            "paid_without_access_record",
            access_state=access_state
        )

        return {"ok": False, "reason": "paid_without_access_record", "access_state": access_state}


    if not access_state.get("has_active_access"):

        log_community_link_recover_generation_failed(
            group_id,
            telegram_group_id,
            target_user_id,
            "no_active_access",
            access_state=access_state
        )

        return {"ok": False, "reason": "no_active_access", "access_state": access_state}


    existing_link = fetch_recent_community_access_invite_link(group_id, target_user_id)

    if existing_link:

        return {
            "ok": True,
            "invite_link": existing_link,
            "source": "existing",
            "group_name": group_name,
            "access_state": access_state
        }


    expires_at = access_state.get("expires_at")
    # Este es el camino del botón "Pedir mi enlace", el que se le ofrece a quien
    # acaba de pagar y no ha recibido el suyo. Daba enlaces de 180 segundos: se
    # le decía que pulsara ahí y lo que recibía caducaba antes de leerlo.
    expire_seconds = ACCESS_LINK_EXPIRE_SECONDS


    if expires_at:

        remaining = int((expires_at - datetime.now()).total_seconds())

        if remaining <= 0:

            log_community_link_recover_generation_failed(
                group_id,
                telegram_group_id,
                target_user_id,
                "expired_access",
                access_state=access_state
            )

            return {"ok": False, "reason": "expired_access", "access_state": access_state}


        # El enlace nunca puede durar más que el acceso que abre.
        expire_seconds = max(60, min(ACCESS_LINK_EXPIRE_SECONDS, remaining))


    telegram_result = create_telegram_invite_link(
        TOKEN,
        telegram_group_id,
        expire_seconds=expire_seconds,
        member_limit=1,
        community_type=community_type,
        return_details=True
    )
    invite_link = telegram_result.get("invite_link") if telegram_result else None


    if not invite_link:

        reason = "telegram_api_failed"
        description = (telegram_result or {}).get("description") or ""
        error_code = (telegram_result or {}).get("error_code")
        retry_after = (telegram_result or {}).get("retry_after")


        if error_code == 429 or retry_after or "too many requests" in description.lower():

            reason = "telegram_rate_limited"

        elif "not enough rights" in description.lower() or "administrator" in description.lower() or "rights" in description.lower():

            reason = "bot_permission_failed"


        log_community_link_recover_generation_failed(
            group_id,
            telegram_group_id,
            target_user_id,
            reason,
            access_state=access_state,
            error=description,
            telegram_response=telegram_result
        )

        return {
            "ok": False,
            "reason": reason,
            "error": description[:300],
            "telegram_response_ok": (telegram_result or {}).get("response_ok"),
            "telegram_response_description": description[:300],
            "retry_after": retry_after,
            "access_state": access_state
        }


    try:

        save_community_access_invite_link(
            group_id,
            telegram_group_id,
            target_user_id,
            invite_link,
            access_state
        )

    except Exception as e:

        try:

            conn.rollback()

        except Exception:

            pass

        log_community_link_recover_generation_failed(
            group_id,
            telegram_group_id,
            target_user_id,
            "db_save_failed",
            access_state=access_state,
            error=e
        )

        return {
            "ok": False,
            "reason": "db_save_failed",
            "error": str(e)[:300],
            "access_state": access_state
        }


    return {
        "ok": True,
        "invite_link": invite_link,
        "source": "new",
        "group_name": group_name,
        "access_state": access_state
    }


async def send_recovered_community_access_link(context, group_id, target_user_id, actor_user_id):

    result = recover_or_create_community_access_link(group_id, target_user_id)

    if not result.get("ok"):

        log_event(
            "community_link_recover_user_link_failed",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            message="No se pudo recuperar o crear link de acceso para usuario activo.",
            metadata={
                "reason": result.get("reason"),
                "error": result.get("error")
            }
        )

        return result


    group_name = result.get("group_name") or f"Grupo {group_id}"
    invite_link = result.get("invite_link")
    access_state = result.get("access_state") or {}
    is_free = bool(access_state.get("is_free_group"))


    if is_free:

        text = (
            "🔓 Tu enlace de acceso gratuito\n\n"
            f"Hola, te enviamos el enlace para entrar a la comunidad gratuita “{group_name}”.\n\n"
            f"{invite_link}\n\n"
            "Si el enlace caduca o tienes problemas, vuelve a contactar con el administrador desde el bot."
        )

    else:

        text = (
            "🔗 Tu enlace de acceso\n\n"
            f"Hola, te reenviamos el enlace para entrar a la comunidad “{group_name}”.\n\n"
            f"Usa este enlace para acceder:\n{invite_link}\n\n"
            "Si el enlace caduca o tienes problemas, vuelve a contactar con el administrador desde el bot."
        )


    try:

        await context.bot.send_message(
            chat_id=target_user_id,
            text=text
        )

    except Exception as e:

        log_event(
            "community_link_recover_user_dm_failed",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            message="Link de acceso generado pero no se pudo enviar por privado.",
            metadata={
                "error": str(e)[:300],
                "invite_link": mask_invite_link(invite_link)
            }
        )

        return {
            **result,
            "ok": False,
            "reason": "dm_failed"
        }


    log_event(
        "community_link_recover_user_sent",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        message="Link de acceso reenviado a usuario activo.",
        metadata={
            "source": result.get("source"),
            "invite_link": mask_invite_link(invite_link)
        }
    )

    await send_guardian_event_log(
        context,
        group_id,
        "guardian_access_link_recovered",
        "Link de acceso reenviado a usuario activo.",
        severity="info",
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        metadata={
            "target_user_id": target_user_id,
            "source": result.get("source"),
            "is_free": is_free
        }
    )

    return result


def build_community_links_recover_menu_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"

    return (
        "🔗 Reenviar/recuperar link\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
        "Elige una opción:"
    )


def build_community_links_recover_menu_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 A un usuario específico", callback_data=f"community_links_recover_one_{group_id}_0")],
        [InlineKeyboardButton("👥 A todos los usuarios activos", callback_data=f"community_links_recover_all_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="owner_panel_users")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])






def format_owner_backup_frequency(frequency):

    labels = {
        "manual": "Manual",
        "daily": "Diario",
        "weekly": "Semanal",
        "monthly": "Mensual"
    }

    return labels.get((frequency or "manual").lower(), frequency or "-")


def format_owner_backup_file_size(size):

    try:

        size = int(size or 0)

    except Exception:

        return "-"


    if size >= 1024 * 1024:

        return f"{size / (1024 * 1024):.1f} MB"

    if size >= 1024:

        return f"{size / 1024:.1f} KB"

    return f"{size} B"


def build_owner_backup_panel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Crear backup ahora", callback_data="owner_backup_create")],
        [InlineKeyboardButton("📚 Ver últimos backups", callback_data="owner_backup_list")],
        [InlineKeyboardButton("⚙️ Configurar frecuencia", callback_data="owner_backup_frequency")],
        [InlineKeyboardButton("🛡 Backup de mensajes", callback_data="owner_backup_panel")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])




def user_can_access_owner_backup(user_id, group_id):

    return owner_can_use_backups(user_id, group_id)[0]
















async def process_due_owner_backups(context):

    summary = {
        "processed": 0,
        "created": 0,
        "failed": 0
    }

    for job in fetch_due_owner_backup_jobs(limit=10):

        summary["processed"] += 1
        owner_user_id = get_group_owner_user_id(job.get("group_id")) or job.get("owner_user_id")

        if not owner_user_id or not owner_has_feature(owner_user_id, "backups", group_id=job.get("group_id")):

            summary["skipped_missing_addon"] = int(summary.get("skipped_missing_addon", 0) or 0) + 1

            log_event(
                "owner_backup_auto_skipped_missing_addon",
                category="backup",
                severity="warning",
                scope="group",
                group_id=job.get("group_id"),
                actor_user_id=owner_user_id,
                target_user_id=owner_user_id,
                message="Backup automático omitido porque falta addon activo.",
                metadata={
                    "owner_user_id": owner_user_id,
                    "group_id": job.get("group_id"),
                    "job_id": job.get("id"),
                    "frequency": job.get("frequency"),
                    "required_feature": "backups"
                }
            )

            mark_owner_backup_job_run(
                job.get("id"),
                job.get("frequency"),
                success=False
            )

            continue

        try:

            backup = create_owner_backup(
                owner_user_id,
                job.get("group_id"),
                backup_type="automatic",
                job_id=job.get("id")
            )
            mark_owner_backup_job_run(
                job.get("id"),
                job.get("frequency"),
                success=True
            )
            summary["created"] += 1

            log_event(
                "owner_backup_auto_created",
                category="backup",
                severity="info",
                scope="group",
                group_id=job.get("group_id"),
                actor_user_id=owner_user_id,
                target_user_id=owner_user_id,
                message="Backup automático creado.",
                metadata={
                    "owner_user_id": owner_user_id,
                    "group_id": job.get("group_id"),
                    "job_id": job.get("id"),
                    "backup_id": backup.get("id"),
                    "file_size_bytes": backup.get("file_size_bytes"),
                    "frequency": job.get("frequency")
                }
            )

            try:

                await context.bot.send_message(
                    chat_id=owner_user_id,
                    text=(
                        "✅ Backup automático creado.\n\n"
                        f"Comunidad ID: {job.get('group_id')}\n"
                        f"Backup: #{backup.get('id')}\n"
                        f"Tamaño: {format_owner_backup_file_size(backup.get('file_size_bytes'))}"
                    )
                )

            except Exception:

                pass

        except Exception as e:

            try:

                conn.rollback()

            except Exception:

                pass

            mark_owner_backup_job_run(
                job.get("id"),
                job.get("frequency"),
                success=False
            )
            summary["failed"] += 1

            log_event(
                "owner_backup_auto_failed",
                category="backup",
                severity="error",
                scope="group",
                group_id=job.get("group_id"),
                actor_user_id=owner_user_id,
                target_user_id=owner_user_id,
                message="Error creando backup automático.",
                metadata={
                    "owner_user_id": owner_user_id,
                    "group_id": job.get("group_id"),
                    "job_id": job.get("id"),
                    "frequency": job.get("frequency"),
                    "error": str(e)[:300]
                }
            )

    return summary


































COMMERCIAL_PLAN_FIELDS = [

    "id",
    "product_type",
    "name",
    "duration_days",
    "amount",
    "currency",
    "stripe_price_id",
    "is_active",
    "created_at"

]




LEGACY_USER_PLATFORM_STRIPE_CALLBACK_PREFIX = (
    "user_trial_setup_"
    "platform_stripe_"
)

LEGACY_ADMIN_PLATFORM_STRIPE_CALLBACK_PREFIX = (
    "commercial_setup_"
    "platform_stripe_"
)

COMMERCIAL_ADVANCED_STATUSES = (
    "trial_active",
    "awaiting_creator_setup",
    "setup_in_progress",
    "setup_ready",
    "active",
    "trial_expired",
    "expired_pending_reactivation",
    "awaiting_payment",
    "awaiting_payment_setup"
)

COMMERCIAL_ARCHIVED_STATUSES = (
    "archived",
    "closed"
)

COMMERCIAL_ADVANCED_CREATOR_SETUP_STATUSES = (
    "awaiting_creator_setup",
    "pending_group_link",
    "setup_in_progress",
    "setup_ready"
)

DUPLICATE_COMMERCIAL_APPROVAL_MESSAGE = (
    "Esta solicitud ya está aprobada o en configuración. "
    "No se ha reenviado el flujo al usuario."
)


def row_to_commercial_request(row):

    if not row:

        return None


    return dict(zip(COMMERCIAL_REQUEST_FIELDS, row))


def row_to_commercial_plan(row):

    if not row:

        return None


    return dict(zip(COMMERCIAL_PLAN_FIELDS, row))


def row_to_commercial_request_message(row):

    if not row:

        return None


    return dict(zip(COMMERCIAL_REQUEST_MESSAGE_FIELDS, row))






def format_public_visibility(public_visibility):

    labels = {
        "start_home": "inicio",
        "explore_only": "explorar",
        "both": "inicio y explorar",
        "hidden": "oculta/borrador"
    }

    return labels.get(public_visibility, public_visibility or "-")


def commercial_request_has_linked_group(request_row):

    if not request_row:

        return False


    return (
        request_row.get("approved_group_id") is not None
        or request_row.get("approved_telegram_group_id") is not None
    )


def is_commercial_request_advanced(request_row):

    if not request_row:

        return False


    status = request_row.get("status") or ""
    creator_setup_status = request_row.get("creator_setup_status") or ""


    return (
        status in COMMERCIAL_ADVANCED_STATUSES
        or status in COMMERCIAL_ARCHIVED_STATUSES
        or (
            status != "pending"
            and creator_setup_status in COMMERCIAL_ADVANCED_CREATOR_SETUP_STATUSES
        )
        or commercial_request_has_linked_group(request_row)
    )


def is_commercial_request_archived(request_row):

    if not request_row:

        return False


    return (request_row.get("status") or "") in COMMERCIAL_ARCHIVED_STATUSES


def fetch_recoverable_creator_request_id(user_id):

    if not user_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id
            FROM commercial_requests
            WHERE user_id=%s
            AND request_type='shared_trial'
            AND COALESCE(status, 'pending') NOT IN (
                'pending',
                'rejected',
                'archived',
                'closed',
                'deleted_irreversible'
            )
            AND (
                status = ANY(%s)
                OR creator_setup_status = ANY(%s)
                OR approved_group_id IS NOT NULL
                OR approved_telegram_group_id IS NOT NULL
            )
            ORDER BY reviewed_at DESC NULLS LAST,
                     updated_at DESC NULLS LAST,
                     created_at DESC
            LIMIT 1

        """, (
            user_id,
            list(COMMERCIAL_ADVANCED_STATUSES) + ["approved"],
            list(COMMERCIAL_ADVANCED_CREATOR_SETUP_STATUSES)
        ))

        row = cur.fetchone()


    return row[0] if row else None






MARKETPLACE_FILTERS = [
    ("🔥 Tendencias", "trending"),
    ("⭐ Más populares", "popular"),
    ("🆕 Nuevas", "new"),
    ("🔓 Gratis", "free"),
    ("💎 Premium", "premium")
]

MARKETPLACE_FILTER_LABELS = {
    slug: label
    for label, slug in MARKETPLACE_FILTERS
}

MARKETPLACE_DEFAULT_FILTER = "trending"

COMMUNITY_STATS_COLUMNS = {
    "preview_views",
    "access_clicks"
}


def marketplace_trial_visibility_filter():

    return """
        NOT EXISTS (
            SELECT 1
            FROM commercial_requests cr
            WHERE (
                cr.approved_group_id = g.id
                OR cr.approved_telegram_group_id = g.telegram_group_id
            )
            AND (
                (
                    cr.status='trial_active'
                    AND cr.trial_ends_at IS NOT NULL
                    AND cr.trial_ends_at < NOW()
                    AND COALESCE(cr.commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
                )
                OR cr.status='expired_pending_reactivation'
            )
        )
    """


def build_expired_trial_recovery_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "💳 Reactivar pagando",
            callback_data=f"expired_trial_activate_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Reactivar con código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Ver configuración",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "🗑 Eliminar ahora definitivamente",
            callback_data=f"expired_trial_delete_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def build_expired_trial_reminder_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "💳 Reactivar pagando",
            callback_data=f"expired_trial_activate_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Usar código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Ver configuración",
            callback_data=f"configure_community_{request_id}"
        )]

    ])


def format_retention_days_left(delete_after):

    if not delete_after:

        return 0


    try:

        remaining_seconds = (delete_after - datetime.now()).total_seconds()
        remaining_days = int((remaining_seconds + 86399) // 86400)

        return max(remaining_days, 0)

    except Exception:

        return 0


def expired_community_message(days_left=None):

    text = (
        "Tu comunidad ha caducado.\n"
        "Tus datos se conservarán durante 15 días.\n"
        "Puedes reactivarla pagando o usando un código promocional."
    )


    if days_left is not None:

        text += f"\n\nTe quedan {days_left} días antes del borrado definitivo."


    return text


def mark_commercial_request_expired(cur, request_id):

    cur.execute(f"""

        UPDATE commercial_requests cr
        SET status='expired_pending_reactivation',
            commercial_subscription_status='expired',
            previous_public_visibility=COALESCE(
                NULLIF(cr.previous_public_visibility, 'hidden'),
                NULLIF(cr.requested_public_visibility, 'hidden'),
                NULLIF(g.public_visibility, 'hidden'),
                'explore_only'
            ),
            requested_public_visibility='hidden',
            expired_at=NOW(),
            delete_after=NOW() + INTERVAL '15 days',
            last_expiry_reminder_at=NOW(),
            updated_at=NOW()
        FROM groups g
        WHERE cr.id=%s
        AND (
            cr.approved_group_id = g.id
            OR cr.approved_telegram_group_id = g.telegram_group_id
        )
        RETURNING {", ".join("cr." + field for field in COMMERCIAL_REQUEST_FIELDS)}

    """, (request_id,))

    row = cur.fetchone()


    if not row:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='expired_pending_reactivation',
                commercial_subscription_status='expired',
                previous_public_visibility=COALESCE(
                    NULLIF(previous_public_visibility, 'hidden'),
                    NULLIF(requested_public_visibility, 'hidden'),
                    'explore_only'
                ),
                requested_public_visibility='hidden',
                expired_at=NOW(),
                delete_after=NOW() + INTERVAL '15 days',
                last_expiry_reminder_at=NOW(),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def hide_commercial_request_group(cur, request_row):

    approved_group_id = request_row.get("approved_group_id") if request_row else None
    approved_telegram_group_id = (
        request_row.get("approved_telegram_group_id")
        if request_row
        else None
    )


    if approved_group_id:

        cur.execute("""

            UPDATE groups
            SET public_visibility='hidden'
            WHERE id=%s

        """, (approved_group_id,))

    elif approved_telegram_group_id:

        cur.execute("""

            UPDATE groups
            SET public_visibility='hidden'
            WHERE telegram_group_id=%s

        """, (approved_telegram_group_id,))


def finalize_expired_commercial_request(cur, request_row):

    if not request_row:

        return None


    request_id = request_row.get("id")
    approved_group_id = request_row.get("approved_group_id")
    approved_telegram_group_id = request_row.get("approved_telegram_group_id")


    cur.execute(f"""

        UPDATE commercial_requests
        SET status='deleted_irreversible',
            commercial_subscription_status='cancelled',
            requested_public_visibility='hidden',
            updated_at=NOW()
        WHERE id=%s
        RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

    """, (request_id,))

    row = cur.fetchone()


    if approved_group_id:

        cur.execute("""

            UPDATE groups
            SET is_active=FALSE,
                public_visibility='hidden',
                preview_text=NULL,
                preview_image_file_id=NULL,
                preview_video_file_id=NULL,
                category=NULL,
                tags=NULL,
                marketplace_badge=NULL
            WHERE id=%s

        """, (approved_group_id,))

    elif approved_telegram_group_id:

        cur.execute("""

            UPDATE groups
            SET is_active=FALSE,
                public_visibility='hidden',
                preview_text=NULL,
                preview_image_file_id=NULL,
                preview_video_file_id=NULL,
                category=NULL,
                tags=NULL,
                marketplace_badge=NULL
            WHERE telegram_group_id=%s

        """, (approved_telegram_group_id,))


    request_row = row_to_commercial_request(row)


    if request_row:

        sync_commercial_creator_profile_from_request(
            request_row.get("user_id")
        )


    return request_row


async def process_expired_commercial_retention(context):

    newly_expired_requests = []
    reminder_requests = []
    finalized_requests = []
    summary = {
        "newly_expired": 0,
        "expiry_notices_sent": 0,
        "reminders_due": 0,
        "reminders_sent": 0,
        "finalized": 0,
        "admin_notices_sent": 0,
        "send_errors": 0,
        "skipped_without_user": 0
    }


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id
            FROM commercial_requests
            WHERE (
                (
                    status='trial_active'
                    AND trial_ends_at IS NOT NULL
                    AND trial_ends_at < NOW()
                    AND COALESCE(commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
                )
                OR (
                    status='active'
                    AND commercial_subscription_until IS NOT NULL
                    AND commercial_subscription_until < NOW()
                )
            )
            AND (
                approved_group_id IS NOT NULL
                OR approved_telegram_group_id IS NOT NULL
            )

        """)

        rows = cur.fetchall()


        for (request_id,) in rows:

            request_row = mark_commercial_request_expired(cur, request_id)
            hide_commercial_request_group(cur, request_row)


            if request_row:

                newly_expired_requests.append(request_row)


        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status='expired_pending_reactivation'
            AND delete_after IS NOT NULL
            AND delete_after <= NOW()

        """)

        rows = cur.fetchall()


        for row in rows:

            request_row = row_to_commercial_request(row)
            finalized_row = finalize_expired_commercial_request(
                cur,
                request_row
            )

            finalized_requests.append(finalized_row or request_row)


        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status='expired_pending_reactivation'
            AND delete_after IS NOT NULL
            AND delete_after > NOW()
            AND (
                last_expiry_reminder_at IS NULL
                OR last_expiry_reminder_at < NOW() - INTERVAL '1 day'
            )

        """)

        rows = cur.fetchall()


        for row in rows:

            request_row = row_to_commercial_request(row)

            cur.execute("""

                UPDATE commercial_requests
                SET last_expiry_reminder_at=NOW(),
                    updated_at=NOW()
                WHERE id=%s

            """, (request_row.get("id"),))

            reminder_requests.append(request_row)


    for request_row in newly_expired_requests:

        summary["newly_expired"] += 1
        user_id = request_row.get("user_id")


        if not user_id:

            summary["skipped_without_user"] += 1
            print(
                "Commercial expiry scheduler: solicitud sin user_id:",
                request_row.get("id")
            )
            continue


        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=expired_community_message(
                    format_retention_days_left(request_row.get("delete_after"))
                ),
                reply_markup=build_expired_trial_recovery_keyboard(
                    request_row.get("id")
                )
            )

            summary["expiry_notices_sent"] += 1

        except Exception as e:

            summary["send_errors"] += 1
            print("Error avisando comunidad caducada:", e)


    for request_row in reminder_requests:

        summary["reminders_due"] += 1
        user_id = request_row.get("user_id")


        if not user_id:

            summary["skipped_without_user"] += 1
            print(
                "Commercial expiry scheduler: recordatorio sin user_id:",
                request_row.get("id")
            )
            continue


        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Te quedan "
                    f"{format_retention_days_left(request_row.get('delete_after'))} días "
                    "para reactivar tu comunidad antes del borrado definitivo."
                ),
                reply_markup=build_expired_trial_reminder_keyboard(
                    request_row.get("id")
                )
            )

            summary["reminders_sent"] += 1

        except Exception as e:

            summary["send_errors"] += 1
            print("Error enviando recordatorio de comunidad caducada:", e)


    for request_row in finalized_requests:

        summary["finalized"] += 1

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "🗑 Comunidad marcada con borrado definitivo\n\n"
                    f"Solicitud #{request_row.get('id')}\n"
                    f"Usuario: {request_row.get('user_id')}\n"
                    "Se ocultó definitivamente y se limpió la configuración marketplace."
                )
            )

            summary["admin_notices_sent"] += 1

        except Exception as e:

            summary["send_errors"] += 1
            print("Error avisando borrado definitivo comercial:", e)

    active_count = sum(
        int(summary.get(key, 0) or 0)
        for key in (
            "newly_expired",
            "expiry_notices_sent",
            "reminders_due",
            "reminders_sent",
            "finalized",
            "admin_notices_sent",
            "send_errors"
        )
    )

    if active_count > 0:

        print(
            "Commercial expiry scheduler:",
            f"newly_expired={summary['newly_expired']}",
            f"expiry_notices_sent={summary['expiry_notices_sent']}",
            f"reminders_due={summary['reminders_due']}",
            f"reminders_sent={summary['reminders_sent']}",
            f"finalized={summary['finalized']}",
            f"admin_notices_sent={summary['admin_notices_sent']}",
            f"skipped_without_user={summary['skipped_without_user']}",
            f"send_errors={summary['send_errors']}"
        )

    return summary


async def expire_expired_commercial_trials(context):

    await process_expired_commercial_retention(context)


def marketplace_access_text(group):

    if group.get("is_free_group"):

        return "🔓 Entrar gratis"


    return "💳 Ver acceso"


def format_marketplace_number(value):

    try:

        value = int(value or 0)

    except Exception:

        value = 0


    return f"{value:,}".replace(",", ".")


def favorite_button_text(is_favorite):

    if is_favorite:

        return "💔 Quitar favorito"


    return "⭐ Guardar favorito"


def favorite_callback_data(group_id, is_favorite):

    if is_favorite:

        return f"unfavorite_group_{group_id}"


    return f"favorite_group_{group_id}"


def build_marketplace_filter_keyboard(active_filter="trending"):

    keyboard = []


    for label, slug in MARKETPLACE_FILTERS:

        text = label

        if slug == active_filter:

            text = f"• {label}"


        keyboard.append([InlineKeyboardButton(
            text,
            callback_data=f"marketplace_filter_{slug}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="public_back_start"
    )])

    return keyboard


def marketplace_filter_title(filter_kind):

    if filter_kind in MARKETPLACE_FILTER_LABELS:

        return MARKETPLACE_FILTER_LABELS.get(filter_kind)


    if filter_kind.startswith("category:"):

        category = filter_kind.split(":", 1)[1]

        return f"📂 {MARKETPLACE_CATEGORY_LABELS.get(category, category)}"


    if filter_kind.startswith("tag:"):

        tag = filter_kind.split(":", 1)[1].replace("-", " ")

        return f"🏷 {tag}"


    return MARKETPLACE_FILTER_LABELS.get(MARKETPLACE_DEFAULT_FILTER)


def build_marketplace_filter_menu_keyboard(active_filter=MARKETPLACE_DEFAULT_FILTER):

    keyboard = []


    for label, slug in MARKETPLACE_FILTERS:

        text = label

        if slug == active_filter:

            text = f"• {label}"


        keyboard.append([InlineKeyboardButton(
            text,
            callback_data=f"marketplace_filter_{slug}"
        )])


    keyboard.append([InlineKeyboardButton(
        "📂 Categoría",
        callback_data="marketplace_filter_category"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏷 Tags",
        callback_data="marketplace_filter_tags"
    )])

    keyboard.append([InlineKeyboardButton(
        "🧹 Quitar filtros",
        callback_data="start_explore_groups"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a comunidades",
        callback_data=marketplace_filter_callback_data(active_filter)
        if active_filter
        else "start_explore_groups"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_marketplace_category_filter_keyboard():

    keyboard = [
        [InlineKeyboardButton(
            label,
            callback_data=f"marketplace_filter_category_{slug}"
        )]
        for label, slug in MARKETPLACE_CATEGORIES
    ]

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a filtros",
        callback_data="marketplace_filters"
    )])

    return InlineKeyboardMarkup(keyboard)


def marketplace_tag_callback_slug(tag):

    normalized = (tag or "").strip().lower().replace(" ", "-")
    allowed = set(string.ascii_lowercase + string.digits + "-_")

    return "".join(
        char
        for char in normalized
        if char in allowed
    )[:32]


def fetch_marketplace_filter_tags(limit=8):

    tags = []


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT g.tags
            FROM groups g
            WHERE g.is_active=TRUE
            AND g.telegram_group_id != 0
            AND (
                COALESCE(g.is_marketplace_visible, FALSE)=TRUE
                OR COALESCE(g.public_visibility, 'start_home') IN ('explore_only', 'both')
            )
            AND g.tags IS NOT NULL
            AND g.tags != ''
            AND {marketplace_trial_visibility_filter()}
            LIMIT 80

        """)

        rows = cur.fetchall()


    seen = set()


    for row in rows:

        for raw_tag in (row[0] or "").split(","):

            tag = raw_tag.strip()
            slug = marketplace_tag_callback_slug(tag)


            if not tag or not slug or slug in seen:

                continue


            seen.add(slug)
            tags.append((tag, slug))


            if len(tags) >= limit:

                return tags


    return tags


def build_marketplace_tag_filter_keyboard():

    tags = fetch_marketplace_filter_tags()


    if not tags:

        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⬅️ Volver a filtros",
                callback_data="marketplace_filters"
            )]
        ])


    keyboard = [
        [InlineKeyboardButton(
            f"🏷 {tag}",
            callback_data=f"marketplace_filter_tag_{slug}"
        )]
        for tag, slug in tags
    ]

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a filtros",
        callback_data="marketplace_filters"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_marketplace_access_keyboard(
    group_id,
    is_free_group,
    back_callback="start_explore_groups",
    user_id=None
):

    keyboard = []
    access_state = get_user_group_access_state(user_id, group_id) if user_id else None
    community_type = (
        access_state.get("community_type")
        if access_state
        else get_community_type(group_id)
    )
    kind = format_community_kind(community_type)


    if user_id:

        is_favorite = is_group_favorite(user_id, group_id)

        keyboard.append([InlineKeyboardButton(
            favorite_button_text(is_favorite),
            callback_data=favorite_callback_data(group_id, is_favorite)
        )])


    if access_state and should_block_new_group_purchase(access_state):

        keyboard.extend(build_existing_group_access_keyboard(group_id, access_state).inline_keyboard)

        return InlineKeyboardMarkup(keyboard)


    keyboard.append([InlineKeyboardButton(
        f"🔓 Entrar al {kind}" if is_free_group else "💳 Ver acceso",
        callback_data=f"free_access_{group_id}" if is_free_group else f"group_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "🎟 Tengo código para esta comunidad",
        callback_data=f"group_user_promo_redeem_start_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=back_callback
    )])

    return InlineKeyboardMarkup(keyboard)


def build_marketplace_preview_keyboard(group, user_id=None):

    group_id = group.get("id")
    kind = format_community_kind(group.get("community_type"))
    keyboard = []
    access_state = get_user_group_access_state(user_id, group_id) if user_id else None


    if user_id:

        is_favorite = is_group_favorite(user_id, group_id)

        keyboard.append([InlineKeyboardButton(
            favorite_button_text(is_favorite),
            callback_data=favorite_callback_data(group_id, is_favorite)
        )])


    if (group.get("preview_mode") or "manual") in ("dynamic", "hybrid"):

        keyboard.append([InlineKeyboardButton(
            "⚡ Ver últimos vídeos",
            callback_data=f"marketplace_dynamic_preview_{group_id}"
        )])


    if access_state and should_block_new_group_purchase(access_state):

        keyboard.extend(build_existing_group_access_keyboard(group_id, access_state).inline_keyboard)

        return InlineKeyboardMarkup(keyboard)


    keyboard.append([InlineKeyboardButton(
        f"🔓 Entrar al {kind}" if group.get("is_free_group") else "💳 Ver acceso",
        callback_data=f"free_access_{group_id}" if group.get("is_free_group") else f"group_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "🎟 Canjear código de esta comunidad",
        callback_data=f"group_user_promo_redeem_start_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a comunidad",
        callback_data=f"marketplace_group_{group_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_marketplace_cards_keyboard(groups, user_id, active_filter="trending"):

    keyboard = []


    for group in groups:

        group_id = group.get("id")
        group_name = group.get("name") or "Comunidad privada"

        keyboard.append([InlineKeyboardButton(
            f"➡️ Ver comunidad — {group_name}",
            callback_data=f"marketplace_group_{group_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "💬 Ayuda sobre este menú",
        callback_data=CALLBACK_GROUP_PLANS_HELP
    )])

    keyboard.append([InlineKeyboardButton(
        "🔎 Filtrar grupos",
        callback_data="marketplace_filters"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return keyboard


def row_to_marketplace_group(row):

    if not row:

        return None


    fields = [
        "id",
        "name",
        "is_free_group",
        "preview_text",
        "preview_file_id",
        "preview_image_file_id",
        "preview_video_file_id",
        "category",
        "tags",
        "marketplace_badge",
        "preview_mode",
        "community_type",
        "preview_views",
        "access_clicks",
        "favorites_count",
        "member_count",
        "created_at",
        "entry_amount",
        "entry_currency",
        "entry_duration_days",
        "plan_count",
        "recent_joins",
        "can_deliver"
    ]

    return dict(zip(fields, row))


def get_marketplace_group_select():

    return """
        SELECT g.id,
               g.name,
               (
                   COALESCE(g.is_free_group, FALSE)
                   OR COALESCE(g.is_free, FALSE)
               ),
               g.preview_text,
               g.preview_file_id,
               g.preview_image_file_id,
               g.preview_video_file_id,
               g.category,
               g.tags,
               g.marketplace_badge,
               COALESCE(g.preview_mode, 'manual'),
               COALESCE(g.community_type, 'group'),
               COALESCE(cs.preview_views, 0),
               COALESCE(cs.access_clicks, 0),
               COALESCE(cs.favorites_count, 0),
               (
                   SELECT COUNT(*)
                   FROM users u
                   WHERE u.group_id = g.id
                   AND COALESCE(u.subscription_active, FALSE)=TRUE
                   AND (
                       u.expiration IS NULL
                       OR u.expiration > NOW()
                   )
               ) AS member_count,
               g.created_at,
               -- Precio de entrada y su duración. Se traen aquí para que la
               -- lista y la ficha puedan mostrar el precio sin una consulta
               -- por comunidad: antes el cliente no veía cuánto costaba hasta
               -- pulsar "Comprar acceso", dos toques más adelante.
               (
                   SELECT p.amount
                   FROM plans p
                   WHERE p.group_id = g.id
                     AND COALESCE(p.is_active, TRUE)=TRUE
                     AND p.amount IS NOT NULL
                     AND p.amount > 0
                   ORDER BY p.amount ASC
                   LIMIT 1
               ) AS entry_amount,
               (
                   SELECT COALESCE(NULLIF(p.currency, ''), 'EUR')
                   FROM plans p
                   WHERE p.group_id = g.id
                     AND COALESCE(p.is_active, TRUE)=TRUE
                     AND p.amount IS NOT NULL
                     AND p.amount > 0
                   ORDER BY p.amount ASC
                   LIMIT 1
               ) AS entry_currency,
               (
                   SELECT p.duration_days
                   FROM plans p
                   WHERE p.group_id = g.id
                     AND COALESCE(p.is_active, TRUE)=TRUE
                     AND p.amount IS NOT NULL
                     AND p.amount > 0
                   ORDER BY p.amount ASC
                   LIMIT 1
               ) AS entry_duration_days,
               (
                   SELECT COUNT(*)
                   FROM plans p
                   WHERE p.group_id = g.id
                     AND COALESCE(p.is_active, TRUE)=TRUE
                     AND p.amount IS NOT NULL
                     AND p.amount > 0
               ) AS plan_count,
               -- Entradas de los últimos 7 días. Es prueba social de verdad,
               -- sacada de los accesos concedidos: no se inventa nada ni se
               -- muestra si no ha entrado nadie.
               (
                   SELECT COUNT(*)
                   FROM users u2
                   WHERE u2.group_id = g.id
                     AND u2.created_at IS NOT NULL
                     AND u2.created_at > NOW() - INTERVAL '7 days'
               ) AS recent_joins,
               -- Si el bot ha perdido el permiso de invitar en el grupo, la
               -- compra se rechaza más adelante. Se dice aquí para no llevar a
               -- nadie a un callejón sin salida. NULL es "sin comprobar", que
               -- no es lo mismo que "cerrado".
               (
                   SELECT h.can_deliver
                   FROM group_delivery_health h
                   WHERE h.group_id = g.id
               ) AS can_deliver
        FROM groups g
        LEFT JOIN community_stats cs
        ON cs.group_id = g.id
    """


def fetch_marketplace_group(group_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            {get_marketplace_group_select()}
            WHERE g.id=%s
            AND g.is_active=TRUE
            AND g.telegram_group_id != 0
            AND {marketplace_trial_visibility_filter()}
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    return row_to_marketplace_group(row)


def get_marketplace_order_clause(filter_kind):

    if filter_kind == "popular":

        return "ORDER BY COALESCE(cs.favorites_count, 0) DESC, COALESCE(cs.preview_views, 0) DESC, g.id DESC"


    if filter_kind == "new":

        return "ORDER BY g.created_at DESC, g.id DESC"


    return """
        ORDER BY (
            COALESCE(cs.favorites_count, 0) * 3
            + COALESCE(cs.preview_views, 0)
            + COALESCE(cs.access_clicks, 0) * 2
        ) DESC,
        g.id DESC
    """


def marketplace_filter_callback_data(filter_kind):

    if filter_kind.startswith("category:"):

        return f"marketplace_filter_category_{filter_kind.split(':', 1)[1]}"


    if filter_kind.startswith("tag:"):

        return f"marketplace_filter_tag_{filter_kind.split(':', 1)[1]}"


    if filter_kind in MARKETPLACE_FILTER_LABELS:

        return f"marketplace_filter_{filter_kind}"


    return "start_explore_groups"


def fetch_marketplace_groups(filter_kind="trending", limit=8):

    filters = [
        "g.is_active=TRUE",
        "g.telegram_group_id != 0",
        "(\n            COALESCE(g.is_marketplace_visible, FALSE)=TRUE\n            OR COALESCE(g.public_visibility, 'start_home') IN ('explore_only', 'both')\n        )",
        marketplace_trial_visibility_filter()
    ]
    params = []


    if filter_kind == "free":

        filters.append("(\n            COALESCE(g.is_free_group, FALSE)=TRUE\n            OR COALESCE(g.is_free, FALSE)=TRUE\n        )")


    if filter_kind == "premium":

        filters.append("(\n            COALESCE(g.is_free_group, FALSE)=FALSE\n            AND COALESCE(g.is_free, FALSE)=FALSE\n        )")


    if filter_kind.startswith("category:"):

        filters.append("COALESCE(g.category, '')=%s")
        params.append(filter_kind.split(":", 1)[1])


    if filter_kind.startswith("tag:"):

        tag_slug = filter_kind.split(":", 1)[1].replace("-", " ")
        filters.append("LOWER(COALESCE(g.tags, '')) LIKE %s")
        params.append(f"%{tag_slug.lower()}%")


    where_clause = " AND ".join(filters)
    order_clause = get_marketplace_order_clause(filter_kind)


    with conn.cursor() as cur:

        cur.execute(f"""

            {get_marketplace_group_select()}
            WHERE {where_clause}
            {order_clause}
            LIMIT %s

        """, tuple(params + [limit]))

        rows = cur.fetchall()


    return [
        row_to_marketplace_group(row)
        for row in rows
    ]


def get_user_favorite_group_ids(user_id, group_ids):

    if not user_id or not group_ids:

        return set()


    with conn.cursor() as cur:

        cur.execute("""

            SELECT group_id
            FROM community_favorites
            WHERE user_id=%s
            AND group_id = ANY(%s)

        """, (
            user_id,
            group_ids
        ))

        rows = cur.fetchall()


    return {
        row[0]
        for row in rows
    }


def is_group_favorite(user_id, group_id):

    if not user_id or not group_id:

        return False


    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM community_favorites
            WHERE user_id=%s
            AND group_id=%s
            LIMIT 1

        """, (
            user_id,
            group_id
        ))

        return cur.fetchone() is not None


def attach_favorite_state(groups, user_id):

    group_ids = [
        group.get("id")
        for group in groups
        if group.get("id")
    ]
    favorite_group_ids = get_user_favorite_group_ids(user_id, group_ids)


    for group in groups:

        group["is_favorite"] = group.get("id") in favorite_group_ids


    return groups


def ensure_community_stats(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO community_stats (group_id)
            VALUES (%s)
            ON CONFLICT (group_id) DO NOTHING

        """, (group_id,))

        conn.commit()


def increment_community_stat(group_id, column_name):

    if column_name not in COMMUNITY_STATS_COLUMNS:

        return


    if not group_id:

        return


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO community_stats (group_id)
            VALUES (%s)
            ON CONFLICT (group_id) DO NOTHING

        """, (group_id,))

        cur.execute(f"""

            UPDATE community_stats
            SET {column_name}=GREATEST(COALESCE({column_name}, 0) + 1, 0),
                updated_at=NOW()
            WHERE group_id=%s

        """, (group_id,))

        conn.commit()


def refresh_community_favorites_count(group_id):

    if not group_id:

        return 0


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO community_stats (group_id)
            VALUES (%s)
            ON CONFLICT (group_id) DO NOTHING

        """, (group_id,))

        cur.execute("""

            UPDATE community_stats
            SET favorites_count=(
                    SELECT COUNT(*)
                    FROM community_favorites
                    WHERE group_id=%s
                ),
                updated_at=NOW()
            WHERE group_id=%s
            RETURNING favorites_count

        """, (
            group_id,
            group_id
        ))

        row = cur.fetchone()
        conn.commit()


    if not row:

        return 0


    return row[0]


def format_marketplace_social_proof(group, members_label="miembros"):
    """
    Líneas de prueba social, solo cuando hay algo real que contar.

    Antes se imprimían siempre los contadores, así que toda comunidad recién
    publicada le decía a cada visitante "⭐ 0 favoritos" y "👥 0 miembros". Eso
    no es información neutra: es el mejor argumento posible para no comprar.
    Aquí un cero simplemente no se menciona.
    """

    def numero(valor):

        try:

            return int(valor or 0)

        except Exception:

            return 0


    lineas = []

    miembros = numero(group.get("member_count"))

    if miembros > 0:

        etiqueta = members_label

        if miembros == 1:

            # "1 miembros" / "1 suscriptores" queda mal y se nota.
            etiqueta = "suscriptor" if members_label == "suscriptores" else "miembro"


        lineas.append(
            f"👥 {format_marketplace_number(miembros)} {etiqueta}"
        )


    recientes = numero(group.get("recent_joins"))

    if recientes > 0:

        if recientes == 1:

            lineas.append("🚀 1 persona ha entrado esta semana")

        else:

            lineas.append(
                f"🚀 {format_marketplace_number(recientes)} personas han "
                "entrado esta semana"
            )


    favoritos = numero(group.get("favorites_count"))

    if favoritos > 0:

        lineas.append(
            f"⭐ {format_marketplace_number(favoritos)} "
            f"{'favorito' if favoritos == 1 else 'favoritos'}"
        )


    # La comunidad no puede dar acceso ahora mismo, así que la compra se va a
    # rechazar. Se dice antes de que pulse, no después: llevar a alguien hasta el
    # pago para rechazarlo allí es peor que avisarle aquí. Solo cuando consta
    # comprobado: None es "sin comprobar" y no se menciona.
    if group.get("can_deliver") is False:

        lineas.append("⏸ Entrada cerrada temporalmente")


    return lineas


def format_plan_duration_short(duration_days):
    """Duración de un plan en corto, para caber en la etiqueta de un botón."""

    try:

        dias = int(duration_days) if duration_days not in (None, "") else None

    except Exception:

        return None


    if not dias or dias <= 0:

        # 0 o vacío significa acceso permanente en este bot.
        return "para siempre"


    if dias == 1:

        return "1 día"


    if dias % 365 == 0:

        años = dias // 365

        return "1 año" if años == 1 else f"{años} años"


    if dias % 30 == 0:

        meses = dias // 30

        return "1 mes" if meses == 1 else f"{meses} meses"


    return f"{dias} días"


def format_plans_summary(plans):
    """
    Los planes en texto, para que se lean antes de tocar ningún botón.

    Las filas llegan como (id, nombre, price_id, importe, moneda, proveedor,
    duración). Se resume una vez por plan: en los botones cada plan puede
    aparecer varias veces, una por método de pago disponible.
    """

    vistos = set()
    lineas = []

    for plan in plans or []:

        try:

            _, name, _, amount, currency, _, duration_days = plan

        except Exception:

            continue


        clave = (name, amount, currency, duration_days)

        if clave in vistos:

            continue


        vistos.add(clave)

        linea = f"• {name or 'Acceso'}"

        if amount and currency:

            linea += f" — {amount} {str(currency).upper()}"


        duracion = format_plan_duration_short(duration_days)

        if duracion:

            linea += f" · {duracion}"


        lineas.append(linea)


    if not lineas:

        return "• Acceso a la comunidad"


    return "\n".join(lineas)




def format_marketplace_price(group):
    """
    Precio de entrada tal y como se le dice al cliente.

    Antes esta información no aparecía hasta pulsar "Comprar acceso": en la
    lista y en la ficha solo se leía "💎 Premium", así que no se podían comparar
    comunidades sin entrar en cada una y dar otro toque.
    """

    amount = group.get("entry_amount")

    if amount in (None, ""):

        return None


    currency = (group.get("entry_currency") or "EUR").upper()

    try:

        amount_text = f"{int(amount)}" if float(amount) == int(amount) else f"{amount}"

    except Exception:

        amount_text = str(amount)


    precio = f"{amount_text} {currency}"

    # "desde" solo si hay más de un plan; con uno solo sería engañoso.
    try:

        if int(group.get("plan_count") or 0) > 1:

            precio = f"desde {precio}"

    except Exception:

        pass


    dias = group.get("entry_duration_days")

    try:

        dias = int(dias) if dias not in (None, "") else None

    except Exception:

        dias = None


    if dias:

        precio += f" · {dias} días" if dias != 1 else " · 1 día"


    return precio


def format_marketplace_kind(group):

    if group.get("is_free_group"):

        return "🔓 Gratis"


    badge = group.get("marketplace_badge") or "💎 Premium"
    precio = format_marketplace_price(group)

    if precio:

        return f"{badge} · 💰 {precio}"


    return badge


def format_marketplace_category(group):

    category = group.get("category")

    if not category:

        return "Otros"


    return MARKETPLACE_CATEGORY_LABELS.get(category, category)


def format_marketplace_card(group):

    kind_cap = format_community_kind_capitalized(group.get("community_type"))

    return (
        f"🔥 {group.get('name') or f'{kind_cap} privado'}\n"
        f"📡 Tipo: {kind_cap}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"{format_marketplace_kind(group)}"
    )


def format_marketplace_group_caption(group):

    preview_mode = group.get("preview_mode") or "manual"
    community_type = normalize_community_type(group.get("community_type"))
    kind_cap = format_community_kind_capitalized(community_type)
    members_label = "suscriptores" if community_type == "channel" else "miembros"
    # Los contadores en cero no se muestran: una comunidad recién publicada
    # anunciaba "⭐ 0 favoritos" y "👥 0 miembros" a cada visitante, que es
    # exactamente lo contrario de dar confianza para comprar.
    base_text = "\n".join(
        [
            f"🔥 {group.get('name') or 'Comunidad privada'}",
            f"📡 Tipo: {kind_cap}",
            f"📂 {format_marketplace_category(group)}"
        ]
        + format_marketplace_social_proof(group, members_label)
        + [format_marketplace_kind(group)]
    )


    if preview_mode == "private":

        return base_text


    if preview_mode == "dynamic":

        return (
            f"{base_text}\n\n"
            "⚡ Preview dinámico activo."
        )


    return (
        f"{base_text}\n\n"
        f"📝 {group.get('preview_text') or 'Preview manual pendiente de configurar.'}"
    )


def build_marketplace_group_keyboard(group, user_id=None):

    group_id = group.get("id")
    is_free_group = group.get("is_free_group")
    community_type = normalize_community_type(group.get("community_type"))
    kind = format_community_kind(community_type)
    preview_mode = group.get("preview_mode") or "manual"
    keyboard = []
    access_state = get_user_group_access_state(user_id, group_id) if user_id else None


    if preview_mode in ("manual", "hybrid"):

        keyboard.append([InlineKeyboardButton(
            "👁 Ver preview",
            callback_data=f"marketplace_preview_{group_id}"
        )])


    if preview_mode in ("dynamic", "hybrid"):

        keyboard.append([InlineKeyboardButton(
            "⚡ Preview dinámico",
            callback_data=f"marketplace_dynamic_preview_{group_id}"
        )])


    if user_id:

        is_favorite = is_group_favorite(user_id, group_id)
        keyboard.append([InlineKeyboardButton(
            favorite_button_text(is_favorite),
            callback_data=favorite_callback_data(group_id, is_favorite)
        )])


    if access_state and should_block_new_group_purchase(access_state):

        keyboard.extend(build_existing_group_access_keyboard(group_id, access_state).inline_keyboard)

        return InlineKeyboardMarkup(keyboard)


    keyboard.append([InlineKeyboardButton(
        f"🔓 Entrar al {kind}" if is_free_group else "💳 Comprar acceso",
        callback_data=f"free_access_{group_id}" if is_free_group else f"group_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "🎟 Canjear código de esta comunidad",
        callback_data=f"group_user_promo_redeem_start_{group_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver a explorar",
        callback_data="start_explore_groups"
    )])

    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(keyboard)


def fetch_dynamic_preview_videos(group_id, limit=3):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   video_file_id,
                   caption,
                   created_at,
                   message_id
            FROM group_preview_videos
            WHERE group_id=%s
            AND is_active=TRUE
            ORDER BY created_at DESC, id DESC
            LIMIT %s

        """, (
            group_id,
            limit
        ))

        rows = cur.fetchall()


    return [
        {
            "id": row[0],
            "video_file_id": row[1],
            "caption": row[2],
            "created_at": row[3],
            "message_id": row[4]
        }
        for row in rows
    ]




def format_dynamic_preview_video_caption(group, video, index, total):

    caption = video.get("caption") or "Vídeo publicado en la comunidad."


    if len(caption) > 700:

        caption = caption[:697] + "..."


    return (
        f"⚡ Preview dinámico {index}/{total}\n"
        f"🔥 {group.get('name') or 'Comunidad privada'}\n\n"
        f"{caption}"
    )


def format_dynamic_preview_video_caption_for_user(group, video, index, total, user_id=None):

    caption = format_dynamic_preview_video_caption(group, video, index, total)


    if index != total:

        return caption


    return append_existing_group_access_notice(
        caption,
        user_id,
        group.get("id")
    )


def build_dynamic_preview_access_keyboard(group, user_id=None):

    group_id = group.get("id")
    kind = format_community_kind(group.get("community_type"))
    access_state = get_user_group_access_state(user_id, group_id) if user_id else None


    if access_state and should_block_new_group_purchase(access_state):

        return build_existing_group_access_keyboard(group_id, access_state)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔓 Entrar al {kind}" if group.get("is_free_group") else "💳 Comprar acceso",
            callback_data=f"free_access_{group_id}" if group.get("is_free_group") else f"group_{group_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver a comunidad",
            callback_data=f"marketplace_group_{group_id}"
        )]
    ])


def format_marketplace_preview_caption(group):

    preview_mode = group.get("preview_mode") or "manual"
    community_type = normalize_community_type(group.get("community_type"))
    kind_cap = format_community_kind_capitalized(community_type)
    members_label = "suscriptores" if community_type == "channel" else "miembros"
    # Mismo criterio que en la ficha: los ceros no se anuncian.
    # Cada línea trae su propio salto para que, cuando no haya ninguna, no
    # quede un hueco en blanco en medio del texto.
    stats_text = "".join(
        f"{linea}\n"
        for linea in format_marketplace_social_proof(group, members_label)
    )


    if preview_mode == "private":

        return (
            f"🔥 {group.get('name') or 'Comunidad privada'}\n"
            f"📡 Tipo: {kind_cap}\n"
            f"📂 {format_marketplace_category(group)}\n"
            f"{stats_text}"
            f"{format_marketplace_kind(group)}"
        )


    if preview_mode == "dynamic":

        return (
            f"🔥 {group.get('name') or 'Comunidad privada'}\n"
            f"📡 Tipo: {kind_cap}\n"
            f"📂 {format_marketplace_category(group)}\n"
            f"{stats_text}"
            f"{format_marketplace_kind(group)}\n\n"
            "⚡ Preview dinámico activo. Se mostrarán los últimos 3 vídeos publicados en la comunidad desde que el owner lo activó."
        )


    text = (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📡 Tipo: {kind_cap}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"{stats_text}"
        f"{format_marketplace_kind(group)}\n\n"
        f"📝 {group.get('preview_text') or 'Preview manual pendiente de configurar.'}"
    )


    if preview_mode == "hybrid":

        text += (
            "\n\n"
            "💎 Preview mixto activo: este teaser se combina con los últimos vídeos dinámicos disponibles."
        )


    if group.get("tags"):

        text += f"\n🏷 {group.get('tags')}"


    return text


async def send_marketplace_group_card(context, chat_id, group, user_id=None):

    caption = format_marketplace_group_caption(group)
    caption = await append_existing_group_access_notice_async(
        context,
        caption,
        user_id,
        group.get("id")
    )
    keyboard = build_marketplace_group_keyboard(group, user_id=user_id)
    preview_mode = group.get("preview_mode") or "manual"


    if preview_mode in ("manual", "hybrid") and group.get("preview_video_file_id"):

        message = await context.bot.send_video(
            chat_id=chat_id,
            video=group.get("preview_video_file_id"),
            caption=caption,
            reply_markup=keyboard
        )
        remember_preview_message(context, chat_id, message)

        return


    if preview_mode in ("manual", "hybrid") and group.get("preview_image_file_id"):

        message = await context.bot.send_photo(
            chat_id=chat_id,
            photo=group.get("preview_image_file_id"),
            caption=caption,
            reply_markup=keyboard
        )
        remember_preview_message(context, chat_id, message)

        return


    await send_clean_message(
        context,
        chat_id,
        caption,
        reply_markup=keyboard
    )


async def send_marketplace_preview(context, chat_id, group, user_id=None):

    caption = format_marketplace_preview_caption(group)
    caption = await append_existing_group_access_notice_async(
        context,
        caption,
        user_id,
        group.get("id")
    )
    keyboard = build_marketplace_preview_keyboard(
        group,
        user_id=user_id
    )
    preview_mode = group.get("preview_mode") or "manual"


    if preview_mode not in ("manual", "hybrid"):

        await send_clean_message(
            context,
            chat_id,
            "Este grupo todavía no tiene preview manual.",
            reply_markup=keyboard
        )

        return


    if preview_mode in ("manual", "hybrid") and group.get("preview_video_file_id"):

        message = await context.bot.send_video(
            chat_id=chat_id,
            video=group.get("preview_video_file_id"),
            caption=caption,
            reply_markup=keyboard
        )
        remember_preview_message(context, chat_id, message)

        return


    if preview_mode in ("manual", "hybrid") and group.get("preview_image_file_id"):

        message = await context.bot.send_photo(
            chat_id=chat_id,
            photo=group.get("preview_image_file_id"),
            caption=caption,
            reply_markup=keyboard
        )
        remember_preview_message(context, chat_id, message)

        return


    if group.get("preview_file_id"):

        try:

            message = await context.bot.send_photo(
                chat_id=chat_id,
                photo=group.get("preview_file_id"),
                caption=caption,
                reply_markup=keyboard
            )
            remember_preview_message(context, chat_id, message)

            return

        except Exception:

            try:

                message = await context.bot.send_video(
                    chat_id=chat_id,
                    video=group.get("preview_file_id"),
                    caption=caption,
                    reply_markup=keyboard
                )
                remember_preview_message(context, chat_id, message)

                return

            except Exception as e:

                print("Error mostrando preview legacy:", e)


    if not group.get("preview_text"):

        await send_clean_message(
            context,
            chat_id,
            "Este grupo todavía no tiene preview manual.",
            reply_markup=keyboard
        )

        return


    await send_clean_message(
        context,
        chat_id,
        caption,
        reply_markup=keyboard
    )


async def send_marketplace_list(context, chat_id, user_id, filter_kind="trending"):

    groups = attach_favorite_state(
        fetch_marketplace_groups(filter_kind),
        user_id
    )
    title = marketplace_filter_title(filter_kind)


    if not groups:

        await send_clean_message(
            context,
            chat_id,
            "Todavía no hay comunidades publicadas.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🚀 Publicar mi comunidad",
                    callback_data="public_monetize_community"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return


    text_parts = [
        f"{title}\n\nElige una comunidad para abrir su ficha."
    ]


    for group in groups:

        text_parts.append(format_marketplace_card(group))


    await send_clean_message(
        context,
        chat_id,
        "\n\n".join(text_parts),
        reply_markup=InlineKeyboardMarkup(
            build_marketplace_cards_keyboard(groups, user_id, filter_kind)
        )
    )


def can_edit_marketplace_preview(request_row, user_id):

    return (
        is_super_admin(user_id)
        or commercial_request_belongs_to_user(request_row, user_id)
    )


def get_marketplace_group_id_for_request(request_row):

    group_row = resolve_commercial_request_group(request_row)

    if not group_row:

        return None


    return group_row[0]


def build_creator_marketplace_keyboard(request_id):

    return [
        [InlineKeyboardButton(
            "📝 Preview fijo/manual",
            callback_data=f"creator_preview_mode_set_{request_id}_manual"
        )],
        [InlineKeyboardButton(
            "⚡ Preview dinámico (últimos 3 vídeos)",
            callback_data=f"creator_preview_mode_set_{request_id}_dynamic"
        )],
        [InlineKeyboardButton(
            "💎 Preview mixto",
            callback_data=f"creator_preview_mode_set_{request_id}_hybrid"
        )],
        [InlineKeyboardButton(
            "🔒 Sin preview público",
            callback_data=f"creator_preview_mode_set_{request_id}_private"
        )],
        [InlineKeyboardButton(
            "⚙️ Ver explicación de modos",
            callback_data=f"creator_preview_mode_{request_id}"
        )],
        [InlineKeyboardButton(
            "🎬 Ver vídeos guardados",
            callback_data=f"creator_dynamic_preview_videos_{request_id}"
        )],
        [InlineKeyboardButton(
            "🗑 Borrar vídeo del preview",
            callback_data=f"creator_dynamic_preview_delete_{request_id}"
        )],
        [InlineKeyboardButton(
            "📝 Editar texto preview",
            callback_data=f"creator_preview_text_{request_id}"
        )],
        [InlineKeyboardButton(
            "🖼 Añadir imagen preview",
            callback_data=f"creator_preview_image_{request_id}"
        )],
        [InlineKeyboardButton(
            "🎬 Añadir vídeo preview",
            callback_data=f"creator_preview_video_{request_id}"
        )],
        [InlineKeyboardButton(
            "📂 Elegir categoría",
            callback_data=f"creator_preview_category_{request_id}"
        )],
        [InlineKeyboardButton(
            "🏷 Editar tags",
            callback_data=f"creator_preview_tags_{request_id}"
        )],
        [InlineKeyboardButton(
            "👁 Ver cómo quedará",
            callback_data=f"creator_preview_show_{request_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"configure_community_{request_id}"
        )]
    ]




















def format_commercial_datetime(value):

    if not value:

        return "-"


    try:

        return value.strftime("%Y-%m-%d %H:%M")

    except Exception:

        return str(value)






















def fetch_commercial_request(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE id=%s

            LIMIT 1

        """, (request_id,))

        row = cur.fetchone()


    request_row = row_to_commercial_request(row)


    if request_row:

        sync_commercial_creator_profile_from_request(
            request_row.get("user_id")
        )


    return request_row






def create_commercial_request_message(request_id, sender_type, sender_id, message_text):

    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO commercial_request_messages
            (
                commercial_request_id,
                sender_type,
                sender_id,
                message_text
            )
            VALUES (%s, %s, %s, %s)
            RETURNING {", ".join(COMMERCIAL_REQUEST_MESSAGE_FIELDS)}

        """, (
            request_id,
            sender_type,
            sender_id,
            message_text
        ))

        row = cur.fetchone()


    return row_to_commercial_request_message(row)


def update_commercial_request_last_interaction(request_id, user):

    if not request_id or not user:

        return


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE commercial_requests
            SET last_interaction_user_id=%s,
                last_interaction_username=%s,
                last_interaction_first_name=%s,
                last_interaction_at=NOW(),
                updated_at=NOW()
            WHERE id=%s

        """, (
            user.id,
            user.username,
            user.first_name,
            request_id
        ))




def fetch_active_commercial_plans(product_type):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_PLAN_FIELDS)}
            FROM commercial_plans
            WHERE product_type=%s
            AND is_active=TRUE
            ORDER BY duration_days ASC

        """, (product_type,))

        rows = cur.fetchall()


    return [
        row_to_commercial_plan(row)
        for row in rows
    ]


def fetch_commercial_plan(plan_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_PLAN_FIELDS)}
            FROM commercial_plans
            WHERE id=%s
            AND is_active=TRUE

            LIMIT 1

        """, (plan_id,))

        row = cur.fetchone()


    return row_to_commercial_plan(row)


def commercial_request_belongs_to_user(request_row, user_id):

    if not request_row:

        return False


    return int(request_row.get("user_id") or 0) == int(user_id)


def format_commercial_plan_price(plan):

    if plan.get("amount") is None:

        return "pendiente de precio"


    currency = plan.get("currency") or "EUR"
    amount = plan.get("amount")

    return f"{amount / 100:.2f} {currency}"


def resolve_commercial_request_group(request_row):

    if not request_row:

        return None


    approved_group_id = request_row.get("approved_group_id")
    approved_telegram_group_id = request_row.get("approved_telegram_group_id")


    try:

        with conn.cursor() as cur:

            if approved_group_id:

                cur.execute("""

                    SELECT id,
                           telegram_group_id
                    FROM groups
                    WHERE id=%s
                    LIMIT 1

                """, (approved_group_id,))

                row = cur.fetchone()


                if row:

                    return row


            if approved_telegram_group_id:

                cur.execute("""

                    SELECT id,
                           telegram_group_id
                    FROM groups
                    WHERE telegram_group_id=%s
                    LIMIT 1

                """, (approved_telegram_group_id,))

                row = cur.fetchone()


                if row:

                    return row

    except Exception as e:

        print("Error resolviendo grupo comercial:", e)


    return None


def assign_owner_for_commercial_request(request_row):

    group_row = resolve_commercial_request_group(request_row)


    if not group_row:

        return False, None


    group_id, telegram_group_id = group_row
    owner_user_id = request_row.get("user_id")


    if not owner_user_id:

        return False, group_id


    assigned = assign_group_owner_permissions(
        owner_user_id,
        group_id
    )


    if assigned:

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
                request_row.get("id")
            ))

            cur.execute("""

                UPDATE group_payment_settings
                SET group_id=%s,
                    updated_at=NOW()
                WHERE commercial_request_id=%s

            """, (
                group_id,
                request_row.get("id")
            ))


        public_visibility = request_row.get("requested_public_visibility")


        if public_visibility:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups
                    SET public_visibility=%s,
                        is_free_group=%s,
                        is_free=%s
                    WHERE id=%s

                """, (
                    public_visibility,
                    request_row.get("is_free_group") is True
                    or request_row.get("payment_mode") == "free",
                    request_row.get("is_free_group") is True
                    or request_row.get("payment_mode") == "free",
                    group_id
                ))


        else:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups
                    SET is_free_group=%s,
                        is_free=%s
                    WHERE id=%s

                """, (
                    request_row.get("is_free_group") is True
                    or request_row.get("payment_mode") == "free",
                    request_row.get("is_free_group") is True
                    or request_row.get("payment_mode") == "free",
                    group_id
                ))


    return assigned, group_id






def build_creator_setup_keyboard(request_id, payment_mode=None):

    keyboard = [

        [InlineKeyboardButton(
            "📡 Grupo o canal",
            callback_data=f"creator_setup_group_{request_id}"
        )],

        [InlineKeyboardButton(
            "📝 Textos y descripción",
            callback_data=f"creator_setup_texts_{request_id}"
        )],

        [InlineKeyboardButton(
            "💳 Tipo de acceso",
            callback_data=f"creator_setup_access_type_{request_id}"
        )],

        [InlineKeyboardButton(
            "📍 Restricción por ubicación",
            callback_data=f"creator_setup_location_gate_{request_id}"
        )]

    ]


    if payment_mode == "paid":

        keyboard.append([
            InlineKeyboardButton(
                "💳 Métodos de pago",
                callback_data=f"creator_setup_stripe_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "💰 Planes de acceso",
                callback_data=f"creator_setup_plans_{request_id}"
            )
        ])

    elif payment_mode == "free":

        keyboard.append([
            InlineKeyboardButton(
                "💰 Planes de acceso",
                callback_data=f"creator_setup_plans_not_applicable_{request_id}"
            )
        ])

    else:

        keyboard.append([
            InlineKeyboardButton(
                "💳 Métodos de pago",
                callback_data=f"creator_setup_stripe_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "💰 Planes de acceso",
                callback_data=f"creator_setup_plans_{request_id}"
            )
        ])


    keyboard.extend([

        [InlineKeyboardButton(
            "👁 Visibilidad pública",
            callback_data=f"creator_setup_visibility_{request_id}"
        )],

        [InlineKeyboardButton(
            "👁 Preview marketplace",
            callback_data=f"creator_setup_marketplace_{request_id}"
        )],

        [InlineKeyboardButton(
            "✅ Revisar configuración",
            callback_data=f"creator_setup_review_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Tengo un código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "🧭 Tutorial paso a paso",
            callback_data=f"creator_setup_tutorial_{request_id}"
        )],

        [InlineKeyboardButton(
            "🤖 Ayuda IA de configuración",
            callback_data=f"creator_setup_ai_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver al inicio",
            callback_data="public_back_start"
        )]

    ])

    return keyboard


def build_creator_setup_panel_text(group_id=None):

    text = (
        "📦 Configuración de tu comunidad\n\n"
        "Desde aquí puedes dejar preparada tu comunidad durante la prueba."
    )


    if not group_id:

        text += (
            "\n\n"
            "Estado del grupo: pendiente de crear/publicar grupo.\n\n"
            "Para vincular tu grupo:\n\n"
            "1. Pulsa 📡 Grupo o canal.\n"
            "2. Añade el bot a tu grupo como administrador.\n"
            "3. Espera 30 segundos.\n"
            "4. El bot te enviará el ID por privado.\n"
            "5. Vuelve a 📡 Grupo o canal.\n"
            "6. Pega ahí el ID recibido si no se vinculó automáticamente."
        )

    else:

        location_enabled, region_label = get_group_location_gate_display(group_id)
        location_status = "Activada" if location_enabled else "Desactivada"

        text += (
            "\n\n"
            f"📍 Ubicación: {location_status}\n"
            f"Región permitida: {region_label}"
        )


    return text


def start_creator_setup_state(context, request_id, action):

    clear_creator_onboarding_context(context)

    waiting_states = {
        "group": "creator_setup_waiting_group_reference",
        "texts": "creator_setup_waiting_text_name",
        "marketplace_preview_text": "creator_setup_waiting_preview_text",
        "marketplace_tags": "creator_setup_waiting_tags",
        # No hay entrada "stripe": ese paso pedía la clave secreta de Stripe del
        # creador y la guardaba sin cifrar para no usarla nunca. Dejar la
        # entrada aquí era la trampa: bastaba una llamada con action="stripe"
        # para reactivar la recogida de credenciales ajenas.
        "plan": "creator_setup_waiting_plan_name",
        "promo_code": "creator_setup_waiting_promo_code"
    }

    context.user_data["creator_setup"] = True
    context.user_data["creator_setup_request_id"] = request_id
    context.user_data["creator_setup_action"] = action
    context.user_data["creator_setup_step"] = 1
    context.user_data["creator_setup_data"] = {}
    context.user_data["creator_setup_waiting"] = waiting_states.get(action)


def clear_creator_onboarding_context(context):

    for key in (
        "commercial_form",
        "commercial_form_type",
        "commercial_form_step",
        "commercial_form_data",
        "commercial_form_waiting",
        "creator_setup",
        "creator_setup_request_id",
        "creator_setup_action",
        "creator_setup_step",
        "creator_setup_data",
        "creator_setup_waiting",
        "marketplace_preview_media",
        "marketplace_preview_request_id",
        "marketplace_preview_media_type",
        "marketplace_preview_target_mode"
    ):

        context.user_data.pop(key, None)




def build_user_activation_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "📦 Configurar comunidad",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Tengo un código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "💬 Ayuda",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )]

    ]


def build_user_trial_payment_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🏦 Configurar mi propio Stripe/cobro",
            callback_data=f"user_trial_setup_owner_stripe_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Configurar comunidad",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "💬 Ayuda",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )]

    ]


def build_user_trial_choice_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🆓 Mi comunidad será gratuita",
            callback_data=f"user_trial_setup_free_{request_id}"
        )],

        [InlineKeyboardButton(
            "💳 Mi comunidad será de pago",
            callback_data=f"user_trial_setup_paid_{request_id}"
        )],

        [InlineKeyboardButton(
            "💬 Ayuda",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )]

    ]


def build_commercial_plan_keyboard(request_id, plans):

    keyboard = []


    for plan in plans:

        plan_id = plan.get("id")
        label = (
            f"{plan.get('name') or '-'} — "
            f"{format_commercial_plan_price(plan)}"
        )

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"user_commercial_plan_{request_id}_{plan_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "💬 Ayuda",
            callback_data=CALLBACK_COMMERCIAL_HELP
        )
    ])

    return keyboard


def build_direct_activation_plan_keyboard(plans):

    keyboard = []


    for plan in plans:

        plan_id = plan.get("id")
        label = (
            f"{plan.get('name') or '-'} — "
            f"{format_commercial_plan_price(plan)}"
        )

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"commercial_direct_plan_{plan_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=CALLBACK_SHARED_BOT_SPACE
        )
    ])

    return keyboard


























def build_admin_commercial_request_chat_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "✍️ Responder",
            callback_data=f"admin_commercial_reply_{request_id}"
        )],

        [InlineKeyboardButton(
            "📩 Ver solicitud",
            callback_data=f"admin_commercial_review_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_commercial_requests"
        )]

    ])


def build_user_commercial_request_chat_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "Responder solicitud",
            callback_data=f"commercial_request_chat_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])
























def build_commercial_setup_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🆓 Grupo gratuito",
            callback_data=f"commercial_setup_free_group_{request_id}"
        )],

        [InlineKeyboardButton(
            "💳 Grupo de pago",
            callback_data=f"commercial_setup_paid_group_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏦 Stripe del dueño",
            callback_data=f"commercial_setup_owner_stripe_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_commercial_requests"
        )]

    ]


def extract_commercial_request_id(data, prefix):

    return parse_callback_int(data, prefix)






def update_commercial_request_trial_approved(request_id, reviewer_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='trial_active',
                reviewed_by=%s,
                reviewed_at=NOW(),
                trial_starts_at=NOW(),
                trial_ends_at=NOW() + INTERVAL '1 day',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, request_id))

        row = cur.fetchone()


    request_row = row_to_commercial_request(row)


    if request_row:

        sync_commercial_creator_profile_from_request(
            request_row.get("user_id")
        )


    return request_row


def update_commercial_request_trial_visibility(
    request_id,
    reviewer_id,
    public_visibility
):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='trial_active',
                reviewed_by=%s,
                reviewed_at=NOW(),
                trial_starts_at=COALESCE(trial_starts_at, NOW()),
                trial_ends_at=COALESCE(trial_ends_at, NOW() + INTERVAL '1 day'),
                requested_public_visibility=%s,
                creator_setup_status='awaiting_creator_setup',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, public_visibility, request_id))

        row = cur.fetchone()


    request_row = row_to_commercial_request(row)


    if not request_row:

        return None


    sync_commercial_creator_profile_from_request(
        request_row.get("user_id")
    )

    assign_owner_for_commercial_request(request_row)


    return request_row






def update_commercial_request_free_group(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET payment_mode='free',
                is_free_group=TRUE,
                status='trial_active',
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()

        request_row = row_to_commercial_request(row)


        if request_row and request_row.get("approved_group_id"):

            cur.execute("""

                UPDATE groups
                SET is_free_group=TRUE,
                    is_free=TRUE
                WHERE id=%s

            """, (request_row.get("approved_group_id"),))


    return row_to_commercial_request(row)


def update_commercial_request_paid_group(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET payment_mode='paid',
                is_free_group=FALSE,
                status='awaiting_payment_setup',
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()

        request_row = row_to_commercial_request(row)


        if request_row and request_row.get("approved_group_id"):

            cur.execute("""

                UPDATE groups
                SET is_free_group=FALSE,
                    is_free=FALSE
                WHERE id=%s

            """, (request_row.get("approved_group_id"),))


    return row_to_commercial_request(row)






def update_commercial_request_stripe_mode(request_id, stripe_mode):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET stripe_mode=%s,
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (stripe_mode, request_id))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def update_commercial_request_plan(request_id, plan_id, subscription_status):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET selected_commercial_plan_id=%s,
                commercial_subscription_status=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            plan_id,
            subscription_status,
            request_id
        ))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def disable_commercial_request_community(request_row):

    if not request_row:

        return None


    with conn.cursor() as cur:

        return finalize_expired_commercial_request(cur, request_row)


def extract_commercial_plan_selection(data):

    try:

        payload = data.replace("user_commercial_plan_", "", 1)
        request_id, plan_id = payload.split("_", 1)

        return int(request_id), int(plan_id)

    except Exception:

        return None, None


async def notify_commercial_admin(context, text, reply_markup=None):

    try:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            reply_markup=reply_markup
        )

        return True

    except Exception as e:

        print("Error avisando admin comercial:", e)

        return False


async def notify_commercial_request_user(context, request_row, text, reply_markup=None):

    user_id = request_row.get("user_id") if request_row else None


    if not user_id:

        return False


    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup
        )

        return True

    except Exception as e:

        print("Error avisando solicitud comercial:", e)

    return False


async def reply_duplicate_commercial_approval(query, request_id):

    await query.message.reply_text(
        DUPLICATE_COMMERCIAL_APPROVAL_MESSAGE,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "👁 Ver estado",
                callback_data=f"admin_commercial_review_{request_id}"
            )]
        ])
    )


async def handle_admin_trial_visibility_approval(
    context,
    query,
    user_id,
    request_id,
    public_visibility
):

    existing_request = fetch_commercial_request(request_id)


    if not existing_request:

        await query.message.reply_text(
            "❌ Solicitud comercial no encontrada."
        )

        return


    if is_commercial_request_advanced(existing_request):

        await reply_duplicate_commercial_approval(query, request_id)

        return


    request_row = update_commercial_request_trial_visibility(
        request_id,
        user_id,
        public_visibility
    )


    if not request_row:

        await query.message.reply_text(
            "❌ Solicitud comercial no encontrada."
        )

        return


    await notify_commercial_request_user(
        context,
        request_row,
        "✅ Tu prueba de 1 día ha sido aprobada.\n\n"
        "Ahora termina la configuración de tu comunidad.\n\n"
        "Primero elige cómo será el acceso para tus usuarios:\n\n"
        "🆓 Comunidad gratuita:\n"
        "Tus usuarios podrán entrar sin pagar, pero el acceso seguirá protegido por el bot.\n\n"
        "💳 Comunidad de pago:\n"
        "Tus usuarios pagarán directamente a través de tus propios cobros/Stripe.",
        reply_markup=InlineKeyboardMarkup(
            build_user_trial_choice_keyboard(request_id)
        )
    )

    await query.message.reply_text(
        "✅ Prueba de 1 día aprobada.\n\n"
        f"Ubicación inicial: {format_public_visibility(public_visibility)}.\n"
        "El creador ya recibió el flujo para terminar la configuración.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="admin_commercial_requests"
            )]
        ])
    )


def clear_commercial_request_chat_state(context):

    context.user_data.pop("replying_commercial_request", None)
    context.user_data.pop("replying_commercial_request_as", None)


def start_commercial_request_chat_reply(context, request_id, sender_type):

    context.user_data["replying_commercial_request"] = request_id
    context.user_data["replying_commercial_request_as"] = sender_type
    context.user_data["support_mode"] = False
    context.user_data["support_lookup_mode"] = False
    context.user_data.pop("replying_support_ticket", None)


async def receive_commercial_request_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:

        return


    request_id = context.user_data.get("replying_commercial_request")
    sender_type = context.user_data.get("replying_commercial_request_as")
    text = update.message.text.strip()
    user = update.effective_user
    message_user = update.message.from_user
    request_row = fetch_commercial_request(request_id)

    print(
        "commercial_request_chat_message:",
        f"request_id={request_id or '-'}",
        f"sender_type={sender_type or '-'}",
        f"effective_user.id={user.id if user else '-'}",
        f"message.from_user.id={message_user.id if message_user else '-'}",
        f"username={user.username if user and user.username else '-'}",
        f"first_name={user.first_name if user and user.first_name else '-'}",
        f"commercial_requests.user_id={request_row.get('user_id') if request_row else '-'}"
    )


    if not request_row:

        clear_commercial_request_chat_state(context)

        await update.message.reply_text(
            "❌ Solicitud comercial no encontrada."
        )

        return


    if sender_type == "admin":

        if not is_super_admin(user.id):

            clear_commercial_request_chat_state(context)

            await update.message.reply_text(
                "⛔ No tienes permisos para responder esta solicitud."
            )

            return


        create_commercial_request_message(
            request_id,
            "admin",
            user.id,
            text
        )

        update_commercial_request_last_interaction(
            request_id,
            user
        )

        clear_commercial_request_chat_state(context)

        await notify_commercial_request_user(
            context,
            request_row,
            "💬 Mensaje sobre tu solicitud comercial:\n\n"
            f"{text}",
            reply_markup=build_user_commercial_request_chat_keyboard(request_id)
        )

        await update.message.reply_text(
            "✅ Mensaje enviado al solicitante.",
            reply_markup=build_admin_commercial_request_chat_keyboard(request_id)
        )

        return


    if sender_type == "user":

        if int(request_row.get("user_id") or 0) != int(user.id):

            clear_commercial_request_chat_state(context)

            await update.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        create_commercial_request_message(
            request_id,
            "user",
            user.id,
            text
        )

        update_commercial_request_last_interaction(
            request_id,
            user
        )

        clear_commercial_request_chat_state(context)

        await notify_commercial_admin(
            context,
            "💬 Respuesta sobre solicitud comercial\n\n"
            f"Solicitud: #{request_id}\n"
            f"Usuario: {user.id}\n\n"
            f"{text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💬 Abrir conversación",
                    callback_data=f"admin_commercial_chat_{request_id}"
                )],
                [InlineKeyboardButton(
                    "👁 Ver solicitud",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await update.message.reply_text(
            "✅ Respuesta enviada sobre tu solicitud comercial.",
            reply_markup=build_user_commercial_request_chat_keyboard(request_id)
        )

        return


    clear_commercial_request_chat_state(context)

    await update.message.reply_text(
        "⚠️ No se pudo continuar esta conversación comercial."
    )


SUPPORT_TICKET_FIELDS = [
    "id",
    "user_id",
    "username",
    "first_name",
    "status",
    "created_at",
    "updated_at",
    "last_message_at",
    "group_id"
]


def row_to_support_ticket(row):

    if not row:

        return None


    return dict(zip(SUPPORT_TICKET_FIELDS, row))


def fetch_support_ticket(ticket_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
            FROM support_tickets
            WHERE id=%s
            LIMIT 1

        """, (ticket_id,))

        row = cur.fetchone()


    return row_to_support_ticket(row)


def fetch_user_support_ticket(ticket_id, user_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
            FROM support_tickets
            WHERE id=%s
            AND user_id=%s
            LIMIT 1

        """, (
            ticket_id,
            user_id
        ))

        row = cur.fetchone()


    return row_to_support_ticket(row)


def get_or_create_support_ticket(user, group_id=None):

    username = user.username if user and user.username else None
    first_name = user.first_name if user and user.first_name else None
    user_id = user.id if user else None

    print(
        "support_ticket_get_or_create:",
        f"effective_user.id={user_id or '-'}",
        f"username={username or '-'}",
        f"first_name={first_name or '-'}"
    )


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
            FROM support_tickets
            WHERE user_id=%s
            AND status IN ('open', 'answered')
            AND (
                (group_id IS NULL AND %s IS NULL)
                OR group_id=%s
            )
            ORDER BY last_message_at DESC
            LIMIT 1

        """, (
            user_id,
            group_id,
            group_id
        ))

        row = cur.fetchone()


        if row:

            cur.execute("""

                UPDATE support_tickets
                SET username=%s,
                    first_name=%s,
                    group_id=%s,
                    status='open',
                    updated_at=NOW(),
                    last_message_at=NOW()
                WHERE id=%s

            """, (
                username,
                first_name,
                group_id,
                row[0]
            ))

            return row_to_support_ticket(row)


        cur.execute(f"""

            INSERT INTO support_tickets
            (
                user_id,
                username,
                first_name,
                status,
                updated_at,
                last_message_at,
                group_id
            )
            VALUES (%s, %s, %s, 'open', NOW(), NOW(), %s)
            RETURNING {", ".join(SUPPORT_TICKET_FIELDS)}

        """, (
            user_id,
            username,
            first_name,
            group_id
        ))

        row = cur.fetchone()


    return row_to_support_ticket(row)

def create_support_message(ticket_id, sender_type, sender_id, message_text):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO support_messages
            (
                ticket_id,
                sender_type,
                sender_id,
                message_text
            )
            VALUES (%s, %s, %s, %s)

        """, (
            ticket_id,
            sender_type,
            sender_id,
            message_text
        ))


def update_support_ticket_status(ticket_id, status):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE support_tickets
            SET status=%s,
                updated_at=NOW(),
                last_message_at=NOW()
            WHERE id=%s

        """, (
            status,
            ticket_id
        ))


def fetch_support_messages(ticket_id, limit=8):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT sender_type,
                   sender_id,
                   message_text,
                   created_at
            FROM support_messages
            WHERE ticket_id=%s
            ORDER BY created_at DESC
            LIMIT %s

        """, (
            ticket_id,
            limit
        ))

        rows = cur.fetchall()


    return list(reversed(rows))


def fetch_recent_support_tickets(group_id=None):

    with conn.cursor() as cur:

        if group_id is None:

            cur.execute(f"""

                SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
                FROM support_tickets
                WHERE status IN ('open', 'answered')
                ORDER BY last_message_at DESC
                LIMIT 20

            """)

        else:

            cur.execute(f"""

                SELECT {", ".join(SUPPORT_TICKET_FIELDS)}
                FROM support_tickets
                WHERE status IN ('open', 'answered')
                AND group_id=%s
                ORDER BY last_message_at DESC
                LIMIT 20

            """, (group_id,))


        rows = cur.fetchall()


    return [
        row_to_support_ticket(row)
        for row in rows
    ]

def format_support_username(ticket):

    username = ticket.get("username") if ticket else None


    if not username:

        return "-"


    if not username.startswith("@"):

        return f"@{username}"


    return username


def format_support_messages(messages):

    if not messages:

        return "Sin mensajes todavía."


    lines = []


    for sender_type, sender_id, message_text, created_at in messages:

        label = "Usuario" if sender_type == "user" else "Admin"
        timestamp = format_commercial_datetime(created_at)
        lines.append(
            f"{label} ({sender_id}) · {timestamp}\n{message_text or '-'}"
        )


    return "\n\n".join(lines)


def build_support_ticket_detail_text(ticket):

    messages = fetch_support_messages(
        ticket.get("id"),
        limit=10
    )

    return (
        f"🛟 Ticket #{ticket.get('id')}\n\n"
        f"Estado: {ticket.get('status') or '-'}\n"
        f"Usuario: {ticket.get('user_id') or '-'}\n"
        f"Username: {format_support_username(ticket)}\n"
        f"Nombre: {ticket.get('first_name') or '-'}\n"
        f"Comunidad: {ticket.get('group_id') or 'Global'}\n"
        f"Último mensaje: {format_commercial_datetime(ticket.get('last_message_at'))}\n\n"
        f"{format_support_messages(messages)}"
    )






def build_support_user_navigation_keyboard():

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "🛟 Abrir soporte",
            callback_data="public_support"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def build_support_closed_ticket_keyboard():

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "🆕 Crear nuevo ticket",
            callback_data="public_support"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def clear_support_user_state(context):

    context.user_data["support_mode"] = False
    context.user_data["support_lookup_mode"] = False
    context.user_data.pop("replying_support_ticket", None)
    context.user_data.pop("support_replying_ticket", None)
    context.user_data.pop("support_group_id", None)
    context.user_data.pop("support_context", None)


def log_support_ticket_privacy_attempt(ticket_id, requester_user_id, owner_user_id=None):

    print(
        "Intento de acceso indebido a soporte:",
        f"ticket_id={ticket_id}",
        f"requester_user_id={requester_user_id}",
        f"owner_user_id={owner_user_id or '-'}"
    )


def support_ticket_belongs_to_user(ticket, user_id):

    try:

        return int(ticket.get("user_id")) == int(user_id)

    except Exception:

        return False


def build_support_tickets_text(tickets):

    if not tickets:

        return (
            "🛟 Soporte\n\n"
            "No hay tickets abiertos."
        )


    lines = ["🛟 Tickets de soporte"]


    for ticket in tickets:

        messages = fetch_support_messages(
            ticket.get("id"),
            limit=1
        )
        last_message = messages[-1][2] if messages else "-"

        lines.append(
            "\n"
            f"Ticket #{ticket.get('id')}\n"
            f"Estado: {ticket.get('status') or '-'}\n"
            f"Usuario: {ticket.get('user_id') or '-'}\n"
            f"Username: {format_support_username(ticket)}\n"
            f"Nombre: {ticket.get('first_name') or '-'}\n"
            f"Último: {last_message}\n"
            f"Fecha: {format_commercial_datetime(ticket.get('last_message_at'))}"
        )


    return "\n".join(lines)


def build_support_tickets_keyboard(tickets):

    keyboard = []


    for ticket in tickets:

        username = format_support_username(ticket)
        label_name = username if username != "-" else ticket.get("first_name") or ticket.get("user_id")

        keyboard.append([
            InlineKeyboardButton(
                f"📨 Ticket #{ticket.get('id')} - {label_name}",
                callback_data=f"admin_support_ticket_{ticket.get('id')}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "❓ Ayuda",
            callback_data="admin_help_support_tickets"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_global_panel"
        )
    ])

    return keyboard


async def notify_support_admin(context, ticket, message_text):

    try:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🛟 Nuevo mensaje de soporte\n\n"
                f"Usuario: {ticket.get('user_id')}\n"
                f"Username: {format_support_username(ticket)}\n"
                f"Ticket: #{ticket.get('id')}\n"
                f"Comunidad: {ticket.get('group_id') or 'Global'}\n\n"
                f"{message_text}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📨 Abrir ticket",
                    callback_data=f"admin_support_ticket_{ticket.get('id')}"
                )]
            ])
        )

        return True

    except Exception as e:

        print("Error avisando soporte admin:", e)

        return False


def build_support_photo_admin_caption(ticket, user, original_caption, context_text=None):

    username = user.username if user and user.username else "-"

    if username != "-" and not username.startswith("@"):

        username = f"@{username}"


    caption_parts = [
        "🛟 Captura recibida en soporte",
        "",
        f"Ticket: #{ticket.get('id')}",
        f"Comunidad: {ticket.get('group_id') or 'Global'}",
        f"Usuario ID: {user.id if user else '-'}",
        f"Nombre: {user.first_name if user and user.first_name else '-'}",
        f"Username: {username}"
    ]


    if context_text:

        caption_parts.extend([
            "",
            f"Contexto: {context_text}"
        ])


    caption_parts.extend([
        "",
        "Mensaje del usuario:",
        original_caption or "Sin caption."
    ])

    return "\n".join(caption_parts)[:1024]


async def notify_support_admin_photo(context, ticket, user, photo_file_id, original_caption=None):

    context_text = (
        context.user_data.get("support_context")
        or context.user_data.get("support_help_context")
        or context.user_data.get("help_context")
    )


    try:

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file_id,
            caption=build_support_photo_admin_caption(
                ticket,
                user,
                original_caption,
                context_text=context_text
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📨 Abrir ticket",
                    callback_data=f"admin_support_ticket_{ticket.get('id')}"
                )]
            ])
        )

        return True

    except Exception as e:

        print("Error avisando soporte admin con foto:", e)

        return False


async def handle_user_support_message(update, context, text):

    user = update.effective_user
    message_user = update.message.from_user if update.message else None

    print(
        "support_message_user:",
        f"effective_user.id={user.id if user else '-'}",
        f"message.from_user.id={message_user.id if message_user else '-'}",
        f"username={user.username if user and user.username else '-'}",
        f"first_name={user.first_name if user and user.first_name else '-'}"
    )

    group_id = context.user_data.get("support_group_id")
    ticket = get_or_create_support_ticket(user, group_id=group_id)

    log_user_event(
        update,
        "support_message",
        event_key="support_text",
        group_id=group_id,
        metadata={"ticket_id": ticket.get("id")}
    )

    create_support_message(
        ticket.get("id"),
        "user",
        user.id,
        text
    )

    update_support_ticket_status(
        ticket.get("id"),
        "open"
    )

    await notify_support_admin(
        context,
        ticket,
        text
    )

    log_event(
        "support_ticket_created",
        category="support",
        severity="info",
        scope="global",
        actor_user_id=user.id,
        target_user_id=user.id,
        message="Ticket o mensaje de soporte recibido durante beta.",
        metadata={
            "ticket_id": ticket.get("id"),
            "status": ticket.get("status"),
            "group_id": ticket.get("group_id")
        }
    )

    context.user_data["support_mode"] = False

    await update.message.reply_text(
        "✅ Mensaje enviado a soporte.\n"
        f"Tu número de ticket es #{ticket.get('id')}.\n"
        "Un administrador te responderá por aquí.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔎 Consultar ticket",
                callback_data="user_support_lookup_start"
            )],
            [InlineKeyboardButton(
                "⬅️ Volver al inicio",
                callback_data="public_back_start"
            )]
        ])
    )


async def handle_user_support_photo(update, context):

    user = update.effective_user
    message = update.message


    if not message or not message.photo:

        return


    photo_file_id = message.photo[-1].file_id
    original_caption = (message.caption or "").strip()
    group_id = context.user_data.get("support_group_id")
    ticket = get_or_create_support_ticket(user, group_id=group_id)
    stored_text = "📷 Captura recibida."

    log_user_event(
        update,
        "support_message",
        event_key="support_photo",
        group_id=group_id,
        metadata={"ticket_id": ticket.get("id"), "has_caption": bool(original_caption)}
    )


    if original_caption:

        stored_text += f"\nCaption: {original_caption}"


    create_support_message(
        ticket.get("id"),
        "user",
        user.id,
        stored_text
    )

    update_support_ticket_status(
        ticket.get("id"),
        "open"
    )

    await notify_support_admin_photo(
        context,
        ticket,
        user,
        photo_file_id,
        original_caption=original_caption
    )

    log_event(
        "support_ticket_created",
        category="support",
        severity="info",
        scope="global",
        actor_user_id=user.id,
        target_user_id=user.id,
        message="Captura de soporte recibida durante beta.",
        metadata={
            "ticket_id": ticket.get("id"),
            "group_id": ticket.get("group_id"),
            "has_caption": bool(original_caption),
            "content_type": "photo"
        }
    )

    await message.reply_text(
        "✅ Captura recibida. El soporte la revisará lo antes posible.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔎 Consultar ticket",
                callback_data="user_support_lookup_start"
            )],
            [InlineKeyboardButton(
                "⬅️ Volver al inicio",
                callback_data="public_back_start"
            )]
        ])
    )


async def handle_support_lookup_message(update, context, text):

    user_id = update.effective_user.id


    try:

        ticket_id = int(text.replace("#", "").strip())

    except Exception:

        context.user_data["support_lookup_mode"] = False

        await update.message.reply_text(
            "⚠️ No encontré ese ticket.",
            reply_markup=build_support_user_navigation_keyboard()
        )

        return


    ticket = fetch_support_ticket(ticket_id)

    context.user_data["support_lookup_mode"] = False


    if not ticket:

        await update.message.reply_text(
            "⚠️ No encontré ese ticket.",
            reply_markup=build_support_user_navigation_keyboard()
        )

        return


    if not support_ticket_belongs_to_user(ticket, user_id):

        log_support_ticket_privacy_attempt(
            ticket_id,
            user_id,
            ticket.get("user_id")
        )

        await update.message.reply_text(
            "⛔ No puedes acceder a este ticket.",
            reply_markup=build_support_user_navigation_keyboard()
        )

        return


    if ticket.get("status") == "closed":

        await update.message.reply_text(
            f"{build_support_ticket_detail_text(ticket)}\n\n"
            "📁 Este ticket está cerrado.",
            reply_markup=build_support_closed_ticket_keyboard()
        )

        return


    await update.message.reply_text(
        build_support_ticket_detail_text(ticket),
        reply_markup=build_support_user_navigation_keyboard()
    )


async def handle_admin_support_reply(update, context, text):

    admin_user = update.effective_user
    ticket_id = context.user_data.get("replying_support_ticket")
    ticket = fetch_support_ticket(ticket_id)


    can_reply = is_super_admin(admin_user.id)


    if not can_reply and ticket and ticket.get("group_id"):

        can_reply = user_has_group_permission_any(
            admin_user.id,
            ticket.get("group_id"),
            ["can_respond_group_support"]
        )


    if not can_reply:

        context.user_data.pop("replying_support_ticket", None)

        await update.message.reply_text(
            "⛔ No tienes permisos para responder soporte."
        )

        return


    if not ticket:

        context.user_data.pop("replying_support_ticket", None)

        await update.message.reply_text(
            "❌ Ticket de soporte no encontrado."
        )

        return


    if ticket.get("status") == "closed":

        context.user_data.pop("replying_support_ticket", None)

        await update.message.reply_text(
            "📁 Este ticket está cerrado.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🛟 Tickets abiertos",
                    callback_data="admin_support_tickets"
                )]
            ])
        )

        return


    create_support_message(
        ticket_id,
        "admin",
        admin_user.id,
        text
    )

    update_support_ticket_status(
        ticket_id,
        "answered"
    )

    if ticket.get("group_id"):

        log_event(
            "owner_support_ticket_replied",
            category="support",
            severity="info",
            scope="group",
            group_id=ticket.get("group_id"),
            actor_user_id=admin_user.id,
            target_user_id=ticket.get("user_id"),
            message="Owner respondió un ticket de soporte de comunidad.",
            metadata={"ticket_id": ticket_id}
        )

    context.user_data.pop("replying_support_ticket", None)


    try:

        await context.bot.send_message(
            chat_id=ticket.get("user_id"),
            text=(
                "🛟 Respuesta de soporte:\n\n"
                f"{text}"
            )
        )

    except Exception as e:

        print("Error enviando respuesta soporte al usuario:", e)


    if is_super_admin(admin_user.id):

        reply_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📨 Abrir ticket",
                callback_data=f"admin_support_ticket_{ticket_id}"
            )],
            [InlineKeyboardButton(
                "🛟 Tickets abiertos",
                callback_data="admin_support_tickets"
            )]
        ])

    else:

        reply_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📨 Abrir ticket",
                callback_data=f"owner_support_ticket_{ticket_id}"
            )],
            [InlineKeyboardButton(
                "🛟 Soporte de comunidad",
                callback_data="owner_support_tickets"
            )]
        ])


    await update.message.reply_text(
        "✅ Respuesta enviada al usuario.",
        reply_markup=reply_keyboard
    )


async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:

        return


    if update.message.photo and context.user_data.get("support_mode"):

        await handle_user_support_photo(
            update,
            context
        )

        return


    if not update.message.text:

        return


    text = update.message.text.strip()


    if context.user_data.get("replying_support_ticket"):

        await handle_admin_support_reply(
            update,
            context,
            text
        )

        return


    if context.user_data.get("support_lookup_mode"):

        await handle_support_lookup_message(
            update,
            context,
            text
        )

        return


    if context.user_data.get("support_mode"):

        await handle_user_support_message(
            update,
            context,
            text
        )

        return


async def receive_location_manual_review_form(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:

        return


    step = context.user_data.get("location_review_step")
    group_id = context.user_data.get("location_review_group_id")


    if not step or not group_id:

        return


    text = update.message.text.strip()


    if not text:

        await update.message.reply_text(
            "Escribe una respuesta breve para continuar."
        )

        return


    answers = context.user_data.setdefault(
        "location_review_answers",
        {}
    )


    if step == "reason":

        answers["reason"] = text
        context.user_data["location_review_step"] = "residence_proof"

        await update.message.reply_text(
            "2/3 ¿Cómo puedes justificar que resides habitualmente en la zona permitida?\n\n"
            "Puedes explicarlo con texto: padrón/certificado, contrato o alquiler, recibo/suministro, "
            "o una explicación verificable. No subas documentos en esta fase."
        )

        return


    if step == "residence_proof":

        answers["residence_proof"] = text
        context.user_data["location_review_step"] = "valid_location_eta"

        await update.message.reply_text(
            "3/3 ¿Cuándo podrás enviar una ubicación válida desde la zona permitida?\n\n"
            "Puedes indicar una fecha aproximada. Ejemplo: “El viernes vuelvo a Valencia y podré enviarla.”"
        )

        return


    if step != "valid_location_eta":

        clear_location_manual_review_state(context)

        await update.message.reply_text(
            "⚠️ No he podido continuar la solicitud. Vuelve a intentarlo desde la verificación de ubicación."
        )

        return


    answers["valid_location_eta"] = text
    group_details = fetch_group_location_review_details(group_id)


    if not group_details:

        clear_location_manual_review_state(context)

        await update.message.reply_text(
            "⚠️ No he podido encontrar esta comunidad. Vuelve a intentarlo más tarde.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    review, ticket = create_location_manual_review(
        update.effective_user,
        group_details,
        answers,
        failed_latitude=context.user_data.get("location_review_failed_latitude"),
        failed_longitude=context.user_data.get("location_review_failed_longitude")
    )

    log_user_event(
        update,
        "location_manual_review_form_completed",
        event_key="location_review_form",
        group_id=group_id,
        metadata=build_location_manual_review_metadata(
            review,
            ticket
        )
    )

    log_event(
        "location_manual_review_requested",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=update.effective_user.id,
        target_user_id=update.effective_user.id,
        message="Usuario solicitó revisión manual de ubicación.",
        metadata=build_location_manual_review_metadata(
            review,
            ticket
        )
    )

    log_event(
        "location_manual_review_ticket_created",
        category="support",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=update.effective_user.id,
        target_user_id=update.effective_user.id,
        message="Ticket creado para revisión manual de ubicación.",
        metadata=build_location_manual_review_metadata(
            review,
            ticket
        )
    )

    await notify_location_manual_review_admins(
        context,
        review,
        ticket
    )

    clear_location_manual_review_state(context)

    await update.message.reply_text(
        "Tu solicitud de revisión manual ha sido enviada. "
        "El equipo de la comunidad la revisará y te responderá por este ticket.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔎 Consultar ticket",
                callback_data="user_support_lookup_start"
            )],
            [InlineKeyboardButton(
                "🏠 Inicio",
                callback_data="public_back_start"
            )]
        ])
    )


async def create_free_access_for_user(context, chat_id, telegram_user, group_id):

    user_id = telegram_user.id
    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    if should_block_new_group_purchase(access_state):

        await send_existing_group_access_notice(
            context,
            chat_id,
            user_id,
            group_id,
            provider="free",
            event_type="free_access_blocked_existing_access",
            access_state=access_state
        )

        return


    link_result = get_or_create_free_group_invite_link(group_id)


    if not link_result.get("ok"):

        reason = link_result.get("reason")
        community_type = normalize_community_type(link_result.get("community_type"))
        community_kind = format_community_kind(community_type)

        if reason == "not_free_group":

            message = "Este grupo aún no está configurado como gratuito ni tiene planes activos."

        elif reason == "telegram_error":

            message = format_free_invite_link_error(
                link_result.get("telegram_result"),
                community_kind=community_kind
            )

        elif reason == "missing_telegram_group_id":

            message = "No he podido identificar el grupo de Telegram asociado a esta comunidad."

        else:

            message = "❌ Comunidad gratuita no encontrada o no disponible."


        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=build_group_recovery_keyboard(group_id)
        )

        return


    link = link_result.get("invite_link")
    group_name = link_result.get("group_name") or "Comunidad"


    try:

        with conn.cursor() as cur:

            increment_community_stat(group_id, "access_clicks")

            username = telegram_user.username
            first_name = telegram_user.first_name

            cur.execute("""

                INSERT INTO users
                (
                    user_id,
                    group_id,
                    username,
                    first_name,
                    expiration,
                    subscription_active,
                    last_invite_link
                )
                VALUES (%s, %s, %s, %s, NULL, TRUE, %s)
                ON CONFLICT (user_id, group_id)
                DO UPDATE SET
                    username=EXCLUDED.username,
                    first_name=EXCLUDED.first_name,
                    expiration=NULL,
                    subscription_active=TRUE,
                    last_invite_link=EXCLUDED.last_invite_link

            """, (
                user_id,
                group_id,
                username,
                first_name,
                link
            ))

            conn.commit()

    except Exception as e:

        log_event(
            "free_access_error",
            category="access",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error concediendo acceso gratuito.",
            metadata={
                "error": str(e)
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Error creando acceso gratuito.",
            reply_markup=build_group_recovery_keyboard(group_id)
        )

        return


    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ Acceso gratuito a {group_name}\n\n"
            "Pulsa el enlace para entrar:\n\n"
            f"{link}"
        ),
        reply_markup=ReplyKeyboardRemove()
    )


async def group_delivery_blocks_purchase(context, chat_id, user_id, group_id):
    """
    ¿Hay que rechazar esta compra porque la comunidad no puede dar acceso?

    Para crear el enlace, el bot tiene que seguir siendo administrador del grupo
    con permiso de invitar. Si lo ha perdido, el cobro salía bien y la entrega
    fallaba: el comprador pagaba y no entraba. Es mejor no cobrar.

    Solo rechaza cuando consta comprobado que no se puede, y antes de rechazar
    vuelve a preguntar a Telegram: perder una venta por un dato viejo sería peor
    que el fallo que se está evitando.
    """

    if group_can_deliver_access(group_id):

        return False


    info = fetch_group_basic_info(group_id)

    if not info:

        return False


    group_name = info[1] or f"Comunidad {group_id}"
    telegram_group_id = info[2]

    if not telegram_group_id:

        return False


    todavia_puede = await recheck_group_delivery_live(
        context,
        group_id,
        group_name,
        telegram_group_id
    )

    # None es "no se ha podido saber": se deja pasar la compra.
    if todavia_puede is not False:

        return False


    log_event(
        "purchase_blocked_no_delivery",
        category="payment",
        severity="warning",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Compra rechazada: la comunidad no puede crear enlaces de acceso.",
        metadata={"group_name": str(group_name)[:80]}
    )

    language = load_user_language(user_id)

    await context.bot.send_message(
        chat_id=chat_id,
        text=t("purchase.cannot_deliver", language, group=group_name),
        reply_markup=build_group_recovery_keyboard(group_id)
    )

    return True


async def create_checkout_for_user(context, chat_id, user_id, group_id, price_id,
                                   plan_switch=False):

    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    # plan_switch solo llega desde la rama switchplan_, que ya ha validado
    # contra la base de datos que el socio tiene acceso a ESA comunidad y que
    # el plan destino es de ella. El bloqueo existe para evitar el doble cobro
    # ACCIDENTAL; un cambio de plan pedido a propósito es justo el caso en el
    # que ese bloqueo estorba. El servidor lo vuelve a comprobar por su lado.
    if not plan_switch and should_block_new_group_purchase(access_state):

        await send_existing_group_access_notice(
            context,
            chat_id,
            user_id,
            group_id,
            provider="stripe",
            retry_callback=price_id if is_stripe_checkout_callback(price_id) else None,
            access_state=access_state
        )

        return

    # No se acepta dinero que no se va a poder entregar: si el bot ha perdido el
    # permiso de invitar, el enlace de acceso no se puede crear.
    if await group_delivery_blocks_purchase(context, chat_id, user_id, group_id):

        return



    if not is_stripe_payments_enabled():

        await context.bot.send_message(
            chat_id=chat_id,
            text="Este método de pago aún no está disponible.",
            reply_markup=build_group_recovery_keyboard(group_id)
        )

        return


    try:

        response = requests.post(

            f"{SERVER_URL}/create-checkout-session",

            json={

                "telegram_id": user_id,
                "plan": price_id,
                "group_id": group_id,
                "plan_switch": bool(plan_switch)

            }

        )

        payment_url = response.json()["url"]


        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "💳 Último paso: el pago\n\n"
                f"{payment_url}\n\n"
                "Se abre la página segura de Stripe. En cuanto el pago se "
                "confirme, recibes aquí mismo tu enlace de entrada, sin tener "
                "que hacer nada más.\n\n"
                "Si cierras la página sin pagar, no se te cobra nada y puedes "
                "volver a intentarlo cuando quieras."
            ),
            reply_markup=build_payment_link_keyboard(group_id)
        )

    except Exception as e:

        log_event(
            "checkout_creation_error",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error creando sesión de pago.",
            metadata={
                "price_id": price_id,
                "error": str(e)
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=PAYMENT_FAILED_TEXT,
            reply_markup=build_group_recovery_keyboard(
                group_id,
                retry_callback=price_id if is_stripe_checkout_callback(price_id) else None
            )
        )


async def create_paypal_group_checkout_for_user(context, chat_id, user_id, group_id, plan_id):

    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    if should_block_new_group_purchase(access_state):

        await send_existing_group_access_notice(
            context,
            chat_id,
            user_id,
            group_id,
            provider="paypal",
            access_state=access_state
        )

        return

    # No se acepta dinero que no se va a poder entregar: si el bot ha perdido el
    # permiso de invitar, el enlace de acceso no se puede crear.
    if await group_delivery_blocks_purchase(context, chat_id, user_id, group_id):

        return



    try:

        response = requests.post(

            f"{SERVER_URL}/create-paypal-group-order",

            json={

                "telegram_id": user_id,
                "group_id": group_id,
                "plan_id": plan_id

            },

            timeout=20

        )
        response_data = response.json()


        if response.status_code >= 400 or not response_data.get("url"):

            log_event(
                "paypal_group_checkout_failed",
                category="payment",
                severity="warning",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="No se pudo crear checkout PayPal de grupo.",
                metadata={
                    "plan_id": plan_id,
                    "status_code": response.status_code,
                    "error": response_data.get("error")
                }
            )

            await context.bot.send_message(
                chat_id=chat_id,
                text=response_data.get("error") or "PayPal no está disponible para esta comunidad.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ Checkout PayPal creado. Completa el pago para recibir acceso.\n\n"
                "El acceso se enviará cuando PayPal confirme el pago por webhook verificado."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🅿️ Pagar con PayPal", url=response_data["url"])]
            ])
        )

    except Exception as e:

        log_event(
            "paypal_group_checkout_failed",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error creando orden PayPal de grupo.",
            metadata={
                "plan_id": plan_id,
                "error": str(e)
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=PAYMENT_FAILED_TEXT,
            reply_markup=build_group_recovery_keyboard(group_id)
        )


async def create_revolut_group_checkout_for_user(context, chat_id, user_id, group_id, plan_id):

    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    if should_block_new_group_purchase(access_state):

        await send_existing_group_access_notice(
            context,
            chat_id,
            user_id,
            group_id,
            provider="revolut",
            access_state=access_state
        )

        return

    # No se acepta dinero que no se va a poder entregar: si el bot ha perdido el
    # permiso de invitar, el enlace de acceso no se puede crear.
    if await group_delivery_blocks_purchase(context, chat_id, user_id, group_id):

        return



    try:

        response = requests.post(

            f"{SERVER_URL}/create-revolut-group-order",

            json={

                "telegram_id": user_id,
                "group_id": group_id,
                "plan_id": plan_id

            },

            timeout=20

        )
        response_data = response.json()


        if response.status_code >= 400 or not response_data.get("url"):

            await context.bot.send_message(
                chat_id=chat_id,
                text=response_data.get("error") or "Revolut no está disponible para esta comunidad.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🏦 Paga con Revolut aquí:\n"
                f"{response_data['url']}\n\n"
                "El acceso se enviará cuando Revolut confirme el pago por webhook verificado."
            ),
            reply_markup=ReplyKeyboardRemove()
        )

    except Exception as e:

        log_event(
            "revolut_group_checkout_creation_error",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error creando orden Revolut de grupo.",
            metadata={
                "plan_id": plan_id,
                "error": str(e)
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=PAYMENT_FAILED_TEXT,
            reply_markup=build_group_recovery_keyboard(group_id)
        )


async def create_changenow_group_checkout_for_user(context, chat_id, user_id, group_id, plan_id):

    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    if should_block_new_group_purchase(access_state):

        await send_existing_group_access_notice(
            context,
            chat_id,
            user_id,
            group_id,
            provider="changenow",
            access_state=access_state
        )

        return

    # No se acepta dinero que no se va a poder entregar: si el bot ha perdido el
    # permiso de invitar, el enlace de acceso no se puede crear.
    if await group_delivery_blocks_purchase(context, chat_id, user_id, group_id):

        return



    try:

        response = requests.post(

            f"{SERVER_URL}/create-changenow-group-order",

            json={

                "telegram_id": user_id,
                "group_id": group_id,
                "plan_id": plan_id

            },

            timeout=20

        )
        response_data = response.json()


        if response.status_code >= 400:

            await context.bot.send_message(
                chat_id=chat_id,
                text=response_data.get("error") or "ChangeNOW no está disponible para esta comunidad.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text=build_changenow_payment_review_text(response_data),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛟 Contactar soporte", callback_data=f"public_support_group_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

    except Exception as e:

        log_event(
            "changenow_group_checkout_creation_error",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error creando orden ChangeNOW de grupo.",
            metadata={
                "plan_id": plan_id,
                "error": str(e)
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=PAYMENT_FAILED_TEXT,
            reply_markup=build_group_recovery_keyboard(group_id)
        )


async def create_guardarian_group_checkout_for_user(context, chat_id, user_id, group_id, plan_id):

    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    if should_block_new_group_purchase(access_state):

        await send_existing_group_access_notice(
            context,
            chat_id,
            user_id,
            group_id,
            provider="guardarian",
            access_state=access_state
        )

        return

    # No se acepta dinero que no se va a poder entregar: si el bot ha perdido el
    # permiso de invitar, el enlace de acceso no se puede crear.
    if await group_delivery_blocks_purchase(context, chat_id, user_id, group_id):

        return



    try:

        response = requests.post(

            f"{SERVER_URL}/create-guardarian-group-order",

            json={

                "telegram_id": user_id,
                "group_id": group_id,
                "plan_id": plan_id

            },

            timeout=20

        )
        response_data = response.json()


        if response.status_code >= 400:

            await context.bot.send_message(
                chat_id=chat_id,
                text=response_data.get("error") or "Guardarian no está disponible para esta comunidad.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text=build_guardarian_payment_text(response_data),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛟 Contactar soporte", callback_data=f"public_support_group_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

    except Exception as e:

        log_event(
            "guardarian_group_checkout_creation_error",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error creando orden Guardarian de grupo.",
            metadata={
                "plan_id": plan_id,
                "error": str(e)
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=PAYMENT_FAILED_TEXT,
            reply_markup=build_group_recovery_keyboard(group_id)
        )


async def receive_location_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("location_gate_pending"):

        return


    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    group_id = context.user_data.get("location_gate_group_id")
    action = context.user_data.get("location_gate_action")
    price_id = context.user_data.get("location_gate_price_id")

    allowed_actions = {
        "free_access",
        "checkout",
        "paypal_checkout",
        "revolut_checkout",
        "changenow_checkout",
        "guardarian_checkout",
        "location_only"
    }

    if not group_id or action not in allowed_actions:

        clear_location_flow_state(context)

        log_event(
            "location_gate_stale_state_cleared",
            category="access",
            severity="warning",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Estado obsoleto de verificación de ubicación limpiado.",
            metadata={
                "group_id": group_id,
                "action": action,
                "reason": "missing_or_invalid_state"
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="📍 La verificación de ubicación anterior ha caducado. Vuelve a iniciar el acceso desde la comunidad correcta.",
            reply_markup=ReplyKeyboardRemove()
        )

        return


    _enabled, allowed_region, region_type = get_group_location_gate(group_id)

    if not _enabled:

        clear_location_flow_state(context)

        log_event(
            "location_gate_stale_state_cleared",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Estado de ubicación limpiado porque el grupo ya no requiere ubicación.",
            metadata={
                "group_id": group_id,
                "action": action,
                "reason": "gate_disabled"
            }
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="📍 La verificación de ubicación anterior ya no está activa. Vuelve a iniciar el acceso desde la comunidad correcta.",
            reply_markup=ReplyKeyboardRemove()
        )

        return


    region_label = format_allowed_region(region_type, allowed_region)


    if not update.message or not update.message.location:

        metadata = build_location_log_metadata(
            region_type,
            allowed_region,
            region_label,
            {},
            "telegram_location_missing",
            action=action
        )
        metadata["message_type"] = "text_or_non_location"

        log_event(
            "location_missing_permission",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="El usuario no compartió ubicación real de Telegram durante una verificación regional.",
            metadata=metadata
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "📍 Para verificar tu ubicación debes pulsar el botón de Telegram "
                "“📍 Enviar ubicación”.\n\n"
                "No escribas tu ciudad manualmente: el bot solo puede validar una ubicación real compartida desde Telegram.\n\n"
                f"Región permitida: {region_label}\n\n"
                "Si estás dentro de la zona permitida y te sigue rechazando, contacta con soporte."
            ),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(
                    "📍 Enviar ubicación",
                    request_location=True
                )]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )

        return


    location = update.message.location

    log_user_event(
        update,
        "location_shared",
        event_key="location_gate",
        group_id=group_id,
        metadata={"action": action, "has_location": True}
    )


    try:

        resolved_region = resolve_location_region(
            location.latitude,
            location.longitude
        )

    except Exception as e:

        resolved_region = {}

        log_event(
            "location_geocode_failed",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Error interno resolviendo ubicación regional.",
            metadata=build_location_log_metadata(
                region_type,
                allowed_region,
                region_label,
                resolved_region,
                f"resolve_error:{e}",
                location=location,
                action=action
            )
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ No he podido validar la ubicación ahora mismo.\n\n"
                "Vuelve a intentarlo pulsando el botón de ubicación. "
                "Si el problema continúa, contacta con soporte."
            ),
            reply_markup=build_location_denied_keyboard()
        )

        return


    is_allowed = location_matches_allowed_region(
        resolved_region,
        region_type,
        allowed_region
    )


    if not is_allowed:

        reason_event, reason_message, detected_label = get_location_rejection_reason(
            resolved_region,
            region_type,
            allowed_region
        )
        metadata = build_location_log_metadata(
            region_type,
            allowed_region,
            region_label,
            resolved_region,
            reason_message,
            location=location,
            action=action
        )
        boundary_text = (
            "\n\nTu ubicación parece estar cerca del límite de la zona permitida. "
            "Si crees que es un error, contacta soporte."
            if resolved_region.get("near_boundary")
            else ""
        )


        try:

            save_group_location_verification(
                group_id,
                user_id,
                resolved_region,
                "rejected"
            )

        except Exception as e:

            print("Error guardando verificación de ubicación rechazada:", e)


        log_event(
            reason_event,
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Usuario rechazado por restricción de ubicación.",
            metadata=metadata
        )

        context.user_data["support_group_id"] = group_id
        context.user_data["support_context"] = (
            "Rechazo de ubicación. "
            f"Grupo: {group_id}. "
            f"Región permitida: {region_label}. "
            f"Detectado: {detected_label}. "
            f"Motivo: {reason_message}"
        )
        context.user_data["location_review_group_id"] = group_id
        context.user_data["location_review_failed_latitude"] = location.latitude
        context.user_data["location_review_failed_longitude"] = location.longitude
        context.user_data["location_review_allowed_region"] = allowed_region
        context.user_data["location_review_allowed_region_type"] = region_type
        context.user_data["location_review_detected_label"] = detected_label
        context.user_data["location_review_action"] = action
        context.user_data["location_review_price_id"] = price_id

        clear_location_gate_state(context)

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "📍 No hemos podido validar tu ubicación para esta comunidad.\n\n"
                "La ubicación enviada no coincide con la zona permitida.\n"
                "Si crees que se trata de un caso especial, puedes solicitar una revisión manual."
                f"{boundary_text}"
            ),
            reply_markup=ReplyKeyboardRemove()
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="Elige cómo quieres continuar:",
            reply_markup=build_location_denied_keyboard(group_id)
        )

        return


    try:

        save_group_location_verification(
            group_id,
            user_id,
            resolved_region,
            "verified"
        )

    except Exception as e:

        print("Error guardando verificación de ubicación:", e)


    log_event(
        "location_check_passed",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Usuario verificado correctamente por restricción de ubicación.",
        metadata=build_location_log_metadata(
            region_type,
            allowed_region,
            region_label,
            resolved_region,
            "allowed",
            location=location,
            action=action
        )
    )

    completed_review = mark_location_manual_review_completed(
        user_id,
        group_id
    )


    if completed_review:

        log_event(
            "location_manual_review_completed",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Revisión manual de ubicación completada con ubicación válida.",
            metadata=build_location_manual_review_metadata(completed_review)
        )

    clear_location_gate_state(context)


    if action == "free_access":

        await create_free_access_for_user(
            context,
            chat_id,
            update.effective_user,
            group_id
        )

        return


    if action == "checkout":

        await create_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return


    if action == "paypal_checkout":

        await create_paypal_group_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return


    if action == "revolut_checkout":

        await create_revolut_group_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return


    if action == "changenow_checkout":

        await create_changenow_group_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return


    if action == "guardarian_checkout":

        await create_guardarian_group_checkout_for_user(
            context,
            chat_id,
            user_id,
            group_id,
            price_id
        )

        return


    await context.bot.send_message(
        chat_id=chat_id,
        text="✅ Ubicación verificada.",
        reply_markup=ReplyKeyboardRemove()
    )


# =========================
# BOTONES
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    user_id = query.from_user.id


    callback_chat_id = getattr(query.message, "chat_id", None) if query.message else None

    try:

        is_private_callback_chat = callback_chat_id and int(callback_chat_id) > 0

    except Exception:

        is_private_callback_chat = False


    log_user_event(
        update,
        "callback",
        event_key=data,
        metadata={"chat_id": callback_chat_id}
    )


    if is_private_callback_chat:

        await delete_pending_preview_messages(
            context,
            callback_chat_id
        )


    # Tramo movido a location_review_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_location_review_callbacks(
        update, context, query, user_id, data
    ) is not LOCATION_REVIEW_NOT_HANDLED:

        return




    if data.startswith("retry_creator_group_verification_"):

        try:

            telegram_group_id = int(
                data.replace("retry_creator_group_verification_", "", 1)
            )

        except Exception:

            await query.message.reply_text(
                "❌ Grupo no válido para reintentar verificación."
            )

            return


        try:

            chat = await context.bot.get_chat(telegram_group_id)
            group_name = chat.title or str(telegram_group_id)
            community_type = "channel" if chat.type == "channel" else "group"

        except Exception as e:

            print("Error obteniendo grupo para reintentar verificación:", e)
            group_name = str(telegram_group_id)
            community_type = "group"


        asyncio.create_task(
            verificar_admin_despues(
                telegram_group_id,
                group_name,
                context.bot.id,
                context,
                user_id,
                query.from_user.username,
                query.from_user.first_name,
                community_type
            )
        )

        await query.message.reply_text(
            "🔁 Reintentando verificación.\n\n"
            "Comprobaré de nuevo si el bot ya tiene permisos de administrador."
        )

        return


    if data.startswith("confirm_creator_group_link_"):

        pending_id = extract_commercial_request_id(
            data,
            "confirm_creator_group_link_"
        )

        if pending_id is None:

            await query.message.reply_text(
                "❌ Solicitud de vinculación no válida."
            )

            return


        result = confirm_creator_group_link_request(
            pending_id,
            user_id
        )

        status = result.get("status")

        print(
            "creator_group_link_confirm_callback:",
            f"pending_id={pending_id}",
            f"query.from_user.id={query.from_user.id if query.from_user else '-'}",
            f"username={query.from_user.username if query.from_user and query.from_user.username else '-'}",
            f"first_name={query.from_user.first_name if query.from_user and query.from_user.first_name else '-'}",
            f"status={status}"
        )


        if status == "confirmed":

            community_type = normalize_community_type(result.get("community_type"))
            kind = format_community_kind(community_type)
            kind_cap = format_community_kind_capitalized(community_type)

            await query.message.reply_text(
                f"✅ {kind_cap} vinculado correctamente.\n\n"
                "El panel de gestión se activó para esta comunidad."
            )

            await query.message.reply_text(
                "📦 Puedes continuar configurando tu comunidad desde el panel.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📦 Configurar comunidad",
                        callback_data=f"configure_community_{result.get('request_id')}"
                    )],
                    [InlineKeyboardButton(
                        "🏠 Inicio",
                        callback_data="public_back_start"
                    )]
                ])
            )

            try:

                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"✅ {kind_cap} vinculado por creator\n\n"
                        f"{kind_cap}: {result.get('group_name')}\n"
                        f"Telegram ID: {result.get('telegram_group_id')}\n"
                        f"ID interno: {result.get('group_id')}\n"
                        f"Usuario: {user_id}\n"
                        f"Solicitud: #{result.get('request_id')}"
                    )
                )

            except Exception as e:

                print("Error avisando admin de vinculación:", e)

            return


        if status == "not_owner":

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if status == "owned_by_other":

            await query.message.reply_text(
                "⛔ Este grupo ya está vinculado a otra comunidad."
            )

            return


        if status == "no_capacity":

            await query.message.reply_text(
                "Has alcanzado el cupo máximo de grupos de tu suscripción."
            )

            return


        if status == "not_pending":

            await query.message.reply_text(
                "⚠️ Esta vinculación ya fue procesada."
            )

            return


        await query.message.reply_text(
            "⚠️ No se pudo confirmar esta vinculación. Vuelve a añadir el bot desde tu panel de configuración."
        )

        return


    if data.startswith("cancel_creator_group_link_"):

        pending_id = extract_commercial_request_id(
            data,
            "cancel_creator_group_link_"
        )

        if pending_id is None:

            await query.message.reply_text(
                "❌ Solicitud de vinculación no válida."
            )

            return


        result = cancel_creator_group_link_request(
            pending_id,
            user_id
        )

        status = result.get("status")


        if status == "cancelled":

            telegram_group_id = result.get("telegram_group_id")

            await query.message.reply_text(
                "❌ Vinculación cancelada.\n\n"
                "No se ha asociado este grupo a tu comunidad."
            )

            try:

                await context.bot.send_message(
                    chat_id=telegram_group_id,
                    text="⚠️ La vinculación fue cancelada. El bot saldrá del grupo."
                )

            except Exception as e:

                print("Error avisando grupo de cancelación:", e)


            await leave_chat_safely(
                context,
                telegram_group_id
            )

            return


        if status == "not_owner":

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if status == "not_pending":

            await query.message.reply_text(
                "⚠️ Esta vinculación ya fue procesada."
            )

            return


        await query.message.reply_text(
            "⚠️ No encontré esta vinculación pendiente."
        )

        return


    # =========================
    # BAJA DE AVISOS DE REENGANCHE
    # =========================

    if data == CALLBACK_REENGAGEMENT_STOP:

        try:

            opt_out_reengagement(user_id)

        except Exception as e:

            print("Reenganche: error dando de baja:", e)


        await query.answer("No recibirás más avisos.", show_alert=False)

        await send_clean_message(
            context,
            query.message.chat_id,
            "🔔 Hecho, no volveré a enviarte avisos de novedades.\n\n"
            "Puedes seguir usando el bot con normalidad y entrar cuando "
            "quieras a ver las comunidades disponibles.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔎 Ver comunidades",
                    callback_data="start_explore_groups"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return


    if data in (
        "public_back_start",
        CALLBACK_COMMERCIAL_BACK_START
    ):

        clear_support_user_state(context)
        await clear_location_flow_navigation(context, query.message.chat_id)

        await delete_query_message_safely(query)

        await send_start_menu(
            update,
            context,
            chat_id=query.message.chat_id
        )

        return


    if data in (
        CALLBACK_COMMERCIAL_BACK_SOLUTIONS,
        CALLBACK_COMMERCIAL_BACK
    ):

        await delete_query_message_safely(query)

        await send_clean_message(
            context,
            query.message.chat_id,
            COMMERCIAL_MENU_TEXT_ES,
            reply_markup=InlineKeyboardMarkup(
                build_commercial_menu_keyboard()
            )
        )

        return


    if data == "start_explore_groups":

        await clear_location_flow_navigation(context, query.message.chat_id)

        await expire_expired_commercial_trials(context)

        await send_marketplace_list(
            context,
            query.message.chat_id,
            user_id,
            MARKETPLACE_DEFAULT_FILTER
        )

        return


    if data == "marketplace_filters":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🔎 Filtrar grupos\n\nElige cómo quieres ordenar o acotar las comunidades.",
            reply_markup=build_marketplace_filter_menu_keyboard()
        )

        return


    if data == "marketplace_filter_category":

        await send_clean_message(
            context,
            query.message.chat_id,
            "📂 Filtrar por categoría\n\nElige una categoría para ver comunidades relacionadas.",
            reply_markup=build_marketplace_category_filter_keyboard()
        )

        return


    if data == "marketplace_filter_tags":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🏷 Filtrar por tags\n\nElige uno de los tags disponibles.",
            reply_markup=build_marketplace_tag_filter_keyboard()
        )

        return


    if data.startswith("marketplace_filter_category_"):

        await expire_expired_commercial_trials(context)

        category = data.replace("marketplace_filter_category_", "", 1)


        if category not in MARKETPLACE_CATEGORY_LABELS:

            category = "otros"


        await send_marketplace_list(
            context,
            query.message.chat_id,
            user_id,
            f"category:{category}"
        )

        return


    if data.startswith("marketplace_filter_tag_"):

        await expire_expired_commercial_trials(context)

        tag_slug = data.replace("marketplace_filter_tag_", "", 1)


        await send_marketplace_list(
            context,
            query.message.chat_id,
            user_id,
            f"tag:{tag_slug}"
        )

        return


    if data.startswith("marketplace_filter_"):

        await expire_expired_commercial_trials(context)

        filter_kind = data.replace("marketplace_filter_", "", 1)


        if filter_kind not in MARKETPLACE_FILTER_LABELS:

            filter_kind = "trending"


        await send_marketplace_list(
            context,
            query.message.chat_id,
            user_id,
            filter_kind
        )

        return


    if data.startswith("favorite_group_"):

        group_id = extract_commercial_request_id(
            data,
            "favorite_group_"
        )


        if not fetch_marketplace_group(group_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO community_favorites
                (user_id, group_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, group_id) DO NOTHING

            """, (
                user_id,
                group_id
            ))

            conn.commit()


        favorites_count = refresh_community_favorites_count(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            f"⭐ Comunidad guardada en favoritos.\n\n⭐ {format_marketplace_number(favorites_count)} favoritos",
            reply_markup=build_marketplace_access_keyboard(
                group_id,
                fetch_marketplace_group(group_id).get("is_free_group"),
                "start_explore_groups",
                user_id=user_id
            )
        )

        return


    if data.startswith("unfavorite_group_"):

        group_id = extract_commercial_request_id(
            data,
            "unfavorite_group_"
        )


        if not fetch_marketplace_group(group_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM community_favorites
                WHERE user_id=%s
                AND group_id=%s

            """, (
                user_id,
                group_id
            ))

            conn.commit()


        favorites_count = refresh_community_favorites_count(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            f"💔 Comunidad quitada de favoritos.\n\n⭐ {format_marketplace_number(favorites_count)} favoritos",
            reply_markup=build_marketplace_access_keyboard(
                group_id,
                fetch_marketplace_group(group_id).get("is_free_group"),
                "start_explore_groups",
                user_id=user_id
            )
        )

        return


    # ARREGLAR UN COBRO SIN ACCESO: el aviso de incidencia llevaba todos los
    # identificadores y ninguna forma de actuar. Aquí se concede el acceso —
    # lo hace una PERSONA con permiso sobre esa comunidad, y el permiso se
    # comprueba al pulsar, porque un callback se puede reenviar.

    # DEVOLVER UN PAGO: el aviso de comprador vetado terminaba diciendo "hay
    # que devolverle el pago" y no había forma de hacerlo sin entrar al panel
    # de Stripe a buscarlo entre todos. Dos pasos a propósito: la pantalla
    # dice el importe exacto y a quién, y el segundo toque es el que mueve el
    # dinero.

    if data.startswith("incident_refund_go_"):

        from incident_repair_service import close_incident, fetch_open_incident
        from refund_request_service import refund_last_payment

        resto = data[len("incident_refund_go_"):]

        if not resto.isdigit():

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        incident_id = int(resto)
        incidencia = fetch_open_incident(incident_id)

        if not incidencia:

            await query.message.reply_text(
                "✅ Esa incidencia ya estaba resuelta. No se ha devuelto nada "
                "otra vez."
            )

            return


        comprador_id, group_id, group_name = (
            incidencia[2], incidencia[3], incidencia[5]
        )

        if not (is_super_admin(user_id)
                or get_group_owner_user_id(group_id) == user_id):

            await query.answer("Solo el propietario puede hacerlo",
                               show_alert=True)

            return


        resultado = refund_last_payment(comprador_id, group_id, user_id)

        if not resultado["ok"]:

            motivos = {
                "no_payment": "No hay ningún pago cobrado que devolver.",
                "unsupported": (
                    "Ese cobro no se puede devolver por API con lo que "
                    "guardamos. Hazlo en el panel del proveedor y luego "
                    "marca la incidencia como resuelta."
                ),
                "already": "Alguien acaba de devolverlo.",
                "stripe_error": (
                    "Stripe ha rechazado la devolución. El pago sigue "
                    "marcado como cobrado y la incidencia, abierta."
                ),
            }

            await query.message.reply_text(
                "❌ " + motivos.get(resultado["reason"], "No se ha podido "
                                   "devolver el pago.")
            )

            return


        close_incident(incident_id, user_id)

        # El aviso al comprador y la retirada del acceso NO se hacen aquí: los
        # hace el webhook de la devolución cuando Stripe la confirma, que es
        # quien ya sabe revocar enlaces, expulsar y avisar.
        await query.message.reply_text(
            f"💸 Devolución de {resultado['importe']} pedida a Stripe para "
            f"{comprador_id}.\n\n"
            "Cuando Stripe la confirme, el bot retira el acceso, revoca sus "
            "enlaces y avisa a la persona: eso ya lo hace el webhook de "
            "devoluciones, no hace falta tocar nada más."
        )

        return


    if data.startswith("incident_refund_"):

        from incident_repair_service import fetch_open_incident
        from refund_request_service import describe_refundable

        resto = data[len("incident_refund_"):]

        if not resto.isdigit():

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        incident_id = int(resto)
        incidencia = fetch_open_incident(incident_id)

        if not incidencia:

            await query.message.reply_text("✅ Esa incidencia ya estaba resuelta.")

            return


        comprador_id, group_id, group_name = (
            incidencia[2], incidencia[3], incidencia[5]
        )

        if not (is_super_admin(user_id)
                or get_group_owner_user_id(group_id) == user_id):

            await query.answer("Solo el propietario puede hacerlo",
                               show_alert=True)

            return


        devolvible = describe_refundable(comprador_id, group_id)

        if not devolvible:

            await query.message.reply_text(
                f"No hay ningún pago cobrado de {comprador_id} en "
                f"{group_name} que devolver."
            )

            return


        if not devolvible["puede_api"]:

            await query.message.reply_text(
                f"El último cobro de {comprador_id} ({devolvible['importe']}) "
                "no se puede devolver desde aquí: la referencia guardada no "
                f"permite pedirlo por API ({devolvible['referencia']}).\n\n"
                "Hazlo en el panel del proveedor y resuelve la incidencia "
                "después."
            )

            return


        await query.message.reply_text(
            f"¿Devolver {devolvible['importe']} a {comprador_id}?\n\n"
            f"Comunidad: {group_name}\n"
            f"Plan cobrado: {devolvible['plan']}\n\n"
            "Se devuelve el último pago cobrado de esa persona en esta "
            "comunidad. Cuando Stripe confirme la devolución, el acceso se "
            "retira solo y se le avisa.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"💸 Sí, devolver {devolvible['importe']}",
                    callback_data=f"incident_refund_go_{incident_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ No, dejarlo",
                    callback_data="admin_back_main"
                )],
            ])
        )

        return


    if data.startswith("incident_fix_go_"):

        from incident_repair_service import fetch_open_incident, repair_incident

        resto = data[len("incident_fix_go_"):].split("_")

        if len(resto) != 2 or not all(p.isdigit() for p in resto):

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        incident_id, duration_days = int(resto[0]), int(resto[1])
        incidencia = fetch_open_incident(incident_id)

        if not incidencia:

            await query.message.reply_text(
                "✅ Esa incidencia ya estaba resuelta. No se ha concedido "
                "nada otra vez."
            )

            return


        group_id = incidencia[3]

        if not (is_super_admin(user_id)
                or get_group_owner_user_id(group_id) == user_id):

            await query.answer("Solo el propietario puede hacerlo",
                               show_alert=True)

            return


        resultado = await repair_incident(
            context, incident_id, user_id, duration_days
        )

        if not resultado["ok"]:

            await query.message.reply_text(
                "❌ No se ha podido conceder el acceso "
                f"({resultado['reason']}). El pago sigue registrado y la "
                "incidencia, abierta."
            )

            return


        entrega = ("Le hemos enviado su enlace de entrada."
                   if resultado["link_sent"]
                   else "OJO: no hemos podido escribirle (no ha abierto el "
                        "bot todavía). El acceso ya está concedido.")

        await query.message.reply_text(
            f"✅ Acceso concedido a {resultado['user_id']} durante "
            f"{duration_days} días.\n\n{entrega}\n\n"
            "No se ha registrado ningún pago nuevo: el cobro original ya "
            "estaba contado."
        )

        return


    if data.startswith("incident_fix_"):

        from incident_repair_service import (
            fetch_open_incident,
            fetch_repair_durations,
        )

        resto = data[len("incident_fix_"):]

        if not resto.isdigit():

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        incident_id = int(resto)
        incidencia = fetch_open_incident(incident_id)

        if not incidencia:

            await query.message.reply_text(
                "✅ Esa incidencia ya estaba resuelta."
            )

            return


        group_id, group_name = incidencia[3], incidencia[5]

        if not (is_super_admin(user_id)
                or get_group_owner_user_id(group_id) == user_id):

            await query.answer("Solo el propietario puede hacerlo",
                               show_alert=True)

            return


        duraciones = fetch_repair_durations(group_id)

        if not duraciones:

            await query.message.reply_text(
                f"⚠️ {group_name} no tiene ningún plan activo con duración "
                "válida, así que no hay duración que conceder. Arregla el "
                "plan y vuelve a pulsar."
            )

            return


        teclado = [
            [InlineKeyboardButton(
                f"{nombre} · {dias} días",
                callback_data=f"incident_fix_go_{incident_id}_{int(dias)}"
            )]
            for dias, nombre in duraciones
        ]

        await query.message.reply_text(
            f"¿Cuánto acceso le concedemos en {group_name}?\n\n"
            "Se le enviará su enlace en el momento. No se registra ningún "
            "pago nuevo: el cobro original ya está contado.",
            reply_markup=InlineKeyboardMarkup(teclado)
        )

        return


    # CAMBIO DE PLAN: el único caso en que un socio con acceso activo puede
    # pagar otra vez a propósito. Va antes que cualquier prefijo de compra y
    # se valida contra la base de datos (un callback se escribe a mano, la
    # consulta no): acceso activo a ESA comunidad, plan activo de ESA
    # comunidad, y renovación que no sea de PayPal — la salvaguarda que apaga
    # la anterior al anclar la nueva es de Stripe.
    if data.startswith("switchplan_"):

        from plan_switch_service import plan_is_switchable_target, switch_is_allowed

        partes = data[len("switchplan_"):].split("_")

        if len(partes) != 2 or not all(p.lstrip("-").isdigit() for p in partes):

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        group_id, plan_id = int(partes[0]), int(partes[1])

        permitido, motivo = switch_is_allowed(user_id, group_id, plan_id=plan_id)

        if not permitido:

            log_event(
                "plan_switch_rejected",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Cambio de plan rechazado.",
                metadata={"reason": motivo, "plan_id": plan_id}
            )

            await query.message.reply_text(
                "⚠️ Ese cambio de plan no está disponible para tu acceso.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        destino = plan_is_switchable_target(group_id, plan_id)
        price_id, provider = destino[0], destino[1]

        if (provider or "stripe").lower() != "stripe" or not price_id:

            await query.message.reply_text(
                "⚠️ Ese plan no admite el cambio automático. Escríbenos y lo "
                "hacemos a mano.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        log_event(
            "plan_switch_started",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Cambio de plan iniciado por el comprador.",
            metadata={"plan_id": plan_id, "price_id": price_id}
        )

        context.user_data["selected_group"] = group_id

        await create_checkout_for_user(
            context,
            query.message.chat_id,
            user_id,
            group_id,
            price_id,
            plan_switch=True
        )

        return


    if data.startswith("marketplace_group_"):

        await clear_location_flow_navigation(context, query.message.chat_id)

        await expire_expired_commercial_trials(context)

        group_id = extract_commercial_request_id(
            data,
            "marketplace_group_"
        )
        group = fetch_marketplace_group(group_id)


        if not group:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        group["is_favorite"] = is_group_favorite(user_id, group_id)

        # Queda registrado quién ha mirado esta comunidad. Las pulsaciones de
        # botón no se guardaban, así que no había forma de saber quién se
        # interesó y no compró — que es justo a quien tiene sentido escribir.
        log_user_event_by_ids(
            user_id,
            "community_viewed",
            event_key=f"marketplace_group_{group_id}",
            group_id=group_id
        )

        await delete_query_message_safely(query)
        await send_marketplace_group_card(
            context,
            query.message.chat_id,
            group,
            user_id=user_id
        )

        return


    if data.startswith("marketplace_dynamic_preview_"):

        group_id = extract_commercial_request_id(
            data,
            "marketplace_dynamic_preview_"
        )
        group = fetch_marketplace_group(group_id)


        if not group:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        videos = fetch_dynamic_preview_videos(group_id, limit=3)


        if not videos:

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚡ Preview dinámico\n\n"
                "Todavía no hay vídeos capturados para este grupo.\n\n"
                "Publica un vídeo nuevo en el grupo después de activar el modo dinámico.",
                reply_markup=build_dynamic_preview_access_keyboard(
                    group,
                    user_id=user_id
                )
            )

            return


        await delete_query_message_safely(query)
        total = len(videos)


        for index, video in enumerate(videos, start=1):

            reply_markup = (
                build_dynamic_preview_access_keyboard(
                    group,
                    user_id=user_id
                )
                if index == total
                else None
            )
            caption = format_dynamic_preview_video_caption(
                group,
                video,
                index,
                total
            )

            if index == total:

                caption = await append_existing_group_access_notice_async(
                    context,
                    caption,
                    user_id,
                    group.get("id")
                )

            message = await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video.get("video_file_id"),
                caption=caption,
                reply_markup=reply_markup
            )
            remember_preview_message(
                context,
                query.message.chat_id,
                message
            )

        return


    if data.startswith("marketplace_preview_"):

        group_id = extract_commercial_request_id(
            data,
            "marketplace_preview_"
        )
        group = fetch_marketplace_group(group_id)


        if not group:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        increment_community_stat(group_id, "preview_views")
        group = fetch_marketplace_group(group_id)
        group["is_favorite"] = is_group_favorite(user_id, group_id)

        await delete_query_message_safely(query)
        await send_marketplace_preview(
            context,
            query.message.chat_id,
            group,
            user_id=user_id
        )

        return


    if data == "start_no_groups":

        await send_clean_message(
            context,
            query.message.chat_id,
            "Todavía no hay comunidades publicadas.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🚀 Publicar mi comunidad",
                    callback_data="public_monetize_community"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return


    if data == "public_monetize_community":

        await delete_query_message_safely(query)

        await send_clean_message(
            context,
            query.message.chat_id,

            COMMERCIAL_MENU_TEXT_ES,

            reply_markup=InlineKeyboardMarkup(
                build_commercial_menu_keyboard()
            )

        )

        return


    if data.startswith("public_support_group_"):

        await clear_location_flow_navigation(context, query.message.chat_id)

        group_id = extract_commercial_request_id(
            data,
            "public_support_group_"
        )
        group = fetch_group_basic_info(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        _group_id, group_name, _telegram_group_id, *_ = group
        context.user_data["support_mode"] = True
        context.user_data["support_lookup_mode"] = False
        context.user_data["support_group_id"] = group_id
        context.user_data["support_context"] = f"Soporte vinculado a comunidad: {group_name or group_id} ({group_id})"
        context.user_data.pop("replying_support_ticket", None)
        context.user_data.pop("support_replying_ticket", None)

        await delete_query_message_safely(query)

        await send_clean_message(
            context,
            query.message.chat_id,
            "🛟 Soporte de comunidad\n\n"
            f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
            "Escribe tu mensaje o envía una captura. Quedará vinculado a esta comunidad.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Consultar ticket", callback_data="user_support_lookup_start")],
                [InlineKeyboardButton("⬅️ Volver", callback_data="public_back_start")]
            ])
        )

        return


    if data == "public_support":

        await clear_location_flow_navigation(context, query.message.chat_id)

        context.user_data["support_mode"] = True
        context.user_data["support_lookup_mode"] = False
        context.user_data.pop("support_group_id", None)
        context.user_data.pop("support_context", None)
        context.user_data.pop("replying_support_ticket", None)
        context.user_data.pop("support_replying_ticket", None)

        await delete_query_message_safely(query)

        keyboard = [

            [InlineKeyboardButton(
                "🔎 Consultar ticket",
                callback_data="user_support_lookup_start"
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="public_back_start"
            )],

            [InlineKeyboardButton(
                "💬 Ayuda sobre este menú",
                callback_data=CALLBACK_SUPPORT_HELP
            )]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "🛟 Soporte\n\n"
            "Escribe tu mensaje y se lo enviaremos a un administrador.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "user_support_lookup_start":

        context.user_data["support_mode"] = False
        context.user_data["support_lookup_mode"] = True
        context.user_data.pop("replying_support_ticket", None)
        context.user_data.pop("support_replying_ticket", None)

        await query.message.reply_text(
            "🔎 Consultar ticket\n\n"
            "Escribe el número de ticket que quieres consultar. Ejemplo: 12"
        )

        return


    if data == "public_ai_help":

        await clear_location_flow_navigation(context, query.message.chat_id)

        await activate_ai_help_context(
            update,
            context
        )

        return


    if data == "ai_buyer_panel":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🤖 Ayuda inteligente\n\n"
            "Puedo ayudarte con pagos, accesos, comunidades, soporte y ubicación usando solo información segura del bot.\n\n"
            "No invento precios ni estados de pago: si falta información te llevaré a soporte o al panel correcto.",
            reply_markup=build_buyer_ai_panel_keyboard()
        )

        return


    if data == "ai_ask_buyer":

        await activate_ai_help_context(
            update,
            context,
            help_context="buyer"
        )

        return


    buyer_ai_questions = {
        "ai_buyer_access_help": "Pagué y no me llegó el link. Dame pasos concretos para recuperar acceso.",
        "ai_buyer_payment_methods": "Explícame qué métodos de pago puedo ver en una comunidad y qué significa EUR a USDT.",
        "ai_buyer_location_help": "Explícame por qué una comunidad puede pedirme ubicación y qué hago si falla."
    }

    if data in buyer_ai_questions:

        result = build_contextual_ai_answer(
            user_id=user_id,
            question=buyer_ai_questions[data],
            role=AI_ROLE_BUYER,
            context_key=AI_CONTEXT_PUBLIC_MARKETPLACE
        )

        await send_ai_result_message(
            context,
            query.message.chat_id,
            result,
            back_callback="ai_buyer_panel"
        )

        return


    if data.startswith("ai_feedback_"):

        parts = data.split("_")

        if len(parts) >= 4 and parts[2].isdigit():
            interaction_id = int(parts[2])
            rating = parts[3]
            updated = update_ai_feedback(
                interaction_id,
                rating
            )
        else:
            interaction_id = None
            rating = None
            updated = False

        feedback_context = get_ai_interaction_feedback_context(interaction_id) if interaction_id else None
        role = feedback_context.get("role") if feedback_context else None


        if not feedback_context:

            log_user_event(
                update,
                "ai_feedback_missing_interaction",
                event_key=data,
                metadata={"interaction_id": interaction_id, "rating": rating}
            )


        await query.answer(
            "Valoración registrada." if updated else "Aviso recibido.",
            show_alert=False
        )


        if rating == "up":

            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Gracias por tu valoración.\n\nMe alegra que haya sido útil.",
                reply_markup=build_ai_feedback_next_keyboard(
                    interaction_id=interaction_id,
                    role=role
                )
            )

            return


        if rating == "down":

            await send_clean_message(
                context,
                query.message.chat_id,
                "Gracias. Lo tendremos en cuenta para mejorar esta respuesta.",
                reply_markup=build_ai_feedback_next_keyboard(
                    interaction_id=interaction_id,
                    role=role,
                    include_report=True,
                    include_support=True
                )
            )

            return


        if rating == "report":

            await send_clean_message(
                context,
                query.message.chat_id,
                (
                    "Gracias. Hemos registrado el problema para revisar esta respuesta."
                    if feedback_context
                    else
                    "No he podido encontrar la interacción original, pero he registrado el aviso."
                ),
                reply_markup=build_ai_feedback_next_keyboard(
                    interaction_id=interaction_id,
                    role=role,
                    include_support=True
                )
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "No he podido guardar esa valoración, pero puedes hacer otra pregunta o abrir soporte.",
            reply_markup=build_ai_feedback_next_keyboard(
                interaction_id=interaction_id,
                role=role,
                include_support=True
            )
        )

        return


    if data == "commercial_shared_bot_space":

        await delete_query_message_safely(query)

        keyboard = [

            [InlineKeyboardButton(
                "🎁 Solicitar prueba de 1 día",
                callback_data=CALLBACK_SHARED_TRIAL_START
            )],

            [InlineKeyboardButton(
                "💳 Activar directamente sin prueba",
                callback_data="commercial_direct_activate"
            )],

            [InlineKeyboardButton(
                "📩 Hablar con un asesor",
                callback_data=CALLBACK_COMMERCIAL_CONTACT
            )],

            [InlineKeyboardButton(
                "💬 Ayuda sobre este menú",
                callback_data=CALLBACK_COMMERCIAL_HELP
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK_SOLUTIONS
            )]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "📌 Publicar mi comunidad en este bot\n\n"
            "Esta opción es para creadores que quieren empezar rápido sin crear un bot propio.\n\n"
            "Tu comunidad aparecerá dentro de nuestro bot principal. "
            "Los usuarios podrán verla y consultar sus condiciones de acceso desde aquí.\n\n"
            "✅ Incluye:\n"
            "• Publicación de tu comunidad dentro del bot.\n"
            "• Planes o condiciones de acceso configurables.\n"
            "• Accesos protegidos por el sistema.\n"
            "• Links seguros para entrar al grupo.\n"
            "• Gestión básica desde el sistema.\n\n"
            "🎁 Prueba inicial:\n"
            "Puedes probar esta opción durante 1 día para publicar tu comunidad y comprobar cómo funciona.\n\n"
            "Después de la prueba, si quieres continuar, tendrás que activar una suscripción.\n\n"
            "Si una suscripción activa se detiene o no se renueva, la comunidad podrá dejar de mostrarse para nuevas compras. "
            "Aun así, guardaremos la configuración durante 15 días para que puedas reactivarla sin tener que empezar desde cero.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_shared_trial_start":

        print(
            "commercial_form_start:",
            f"query.from_user.id={query.from_user.id if query.from_user else '-'}",
            f"username={query.from_user.username if query.from_user and query.from_user.username else '-'}",
            f"first_name={query.from_user.first_name if query.from_user and query.from_user.first_name else '-'}",
            "request_type=shared_trial"
        )

        recoverable_request_id = fetch_recoverable_creator_request_id(user_id)

        if recoverable_request_id:

            clear_creator_onboarding_context(context)

            await send_clean_message(
                context,
                query.message.chat_id,
                "Ya tienes una prueba/configuración pendiente.\n\n"
                "Puedes continuar donde lo dejaste sin iniciar otra solicitud.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🔄 Recuperar configuración",
                        callback_data=f"configure_community_{recoverable_request_id}"
                    )],
                    [InlineKeyboardButton(
                        "📡 Añadir grupo/canal",
                        callback_data=f"creator_setup_group_{recoverable_request_id}"
                    )],
                    [InlineKeyboardButton(
                        "🎟 Tengo código promocional",
                        callback_data=f"creator_promo_code_start_{recoverable_request_id}"
                    )],
                    [InlineKeyboardButton(
                        "🛟 Soporte",
                        callback_data="public_support"
                    )],
                    [InlineKeyboardButton(
                        "🧹 Reiniciar configuración",
                        callback_data=f"creator_setup_reset_{recoverable_request_id}"
                    )],
                    [InlineKeyboardButton(
                        "🏠 Inicio",
                        callback_data="public_back_start"
                    )]
                ])
            )

            return

        context.user_data["commercial_form"] = True
        context.user_data["commercial_form_type"] = "shared_trial"
        context.user_data["commercial_form_step"] = 1
        context.user_data["commercial_form_data"] = {}
        context.user_data["commercial_form_waiting"] = "creator_setup_waiting_community_name"

        await send_clean_message(
            context,
            query.message.chat_id,
            "Indica el nombre de la comunidad.\n\n"
            "Ejemplo: GrupoStarsVip"
        )

        return


    if data == "commercial_direct_activate":

        from platform_plan_service import (
            describe_plan_period,
            fetch_purchasable_platform_plans,
            format_plan_amount,
        )

        # Solo los planes que SE PUEDEN cobrar. Antes se listaban todos, con
        # «pendiente de precio» al lado, y al pulsarlos el bot contestaba que el
        # pago estaba pendiente de conectar: una lista de botones que no podían
        # llevar a ningún sitio.
        planes = fetch_purchasable_platform_plans()

        if not planes:

            await send_clean_message(
                context,
                query.message.chat_id,
                "💳 Activar directamente\n\n"
                "Todavía no hay ninguna duración con precio publicado. "
                "Escríbenos y te decimos las condiciones.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📩 Hablar con un asesor",
                        callback_data=CALLBACK_COMMERCIAL_CONTACT
                    )],
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=CALLBACK_SHARED_BOT_SPACE
                    )],
                ])
            )

            return


        filas = []

        for plan in planes:

            filas.append([InlineKeyboardButton(
                f"{plan['name']} · {format_plan_amount(plan)} "
                f"{describe_plan_period(plan)}",
                callback_data=f"commercial_direct_plan_{plan['id']}"
            )])

        filas.append([InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=CALLBACK_SHARED_BOT_SPACE
        )])

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Publicar mi comunidad\n\n"
            "Elige la duración. Se paga con tarjeta y se renueva sola; puedes "
            "cancelarla cuando quieras.\n\n"
            "En cuanto se confirma el pago puedes publicar tu comunidad y "
            "empezar a cobrar suscripciones con acceso automático.",
            reply_markup=InlineKeyboardMarkup(filas)
        )

        return


    if data.startswith("commercial_direct_plan_"):

        from platform_plan_service import (
            create_platform_plan_checkout,
            describe_plan_period,
            fetch_platform_plan,
            format_plan_amount,
        )

        plan_id = extract_commercial_request_id(
            data,
            "commercial_direct_plan_"
        )

        # Se relee de la base y no del callback: un callback se puede reenviar,
        # y con él se elegiría un plan apagado o sin precio.
        plan = fetch_platform_plan(plan_id) if plan_id else None

        if not plan:

            await query.message.reply_text(
                "Esa duración ya no está disponible.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "⬅️ Ver las duraciones",
                    callback_data="commercial_direct_activate"
                )]])
            )

            return


        try:

            session = create_platform_plan_checkout(user_id, plan)

        except Exception as e:

            log_event(
                "platform_plan_checkout_failed",
                category="billing",
                severity="error",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Error creando el checkout del plan de publicación.",
                metadata={"plan_id": plan.get("id"), "error": str(e)[:300]}
            )

            await query.message.reply_text(
                "No he podido abrir el pago ahora mismo. Inténtalo en un "
                "momento o escríbenos y lo resolvemos.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "📩 Hablar con un asesor",
                    callback_data=CALLBACK_COMMERCIAL_CONTACT
                )]])
            )

            return


        log_event(
            "platform_plan_checkout_created",
            category="billing",
            severity="info",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Checkout del plan de publicación creado.",
            metadata={
                "plan_id": plan.get("id"),
                "stripe_session_id": session.get("id"),
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            f"💳 {plan.get('name')} · {format_plan_amount(plan)} "
            f"{describe_plan_period(plan)}\n\n"
            "Completa el pago y el bot te avisa aquí mismo en cuanto se "
            "confirme. Entonces ya puedes publicar tu comunidad.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Pagar", url=session.get("url"))],
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="commercial_direct_activate"
                )],
            ])
        )

        return


    if data == "commercial_custom_bot":

        await delete_query_message_safely(query)

        keyboard = [

            [InlineKeyboardButton(
                "🤖 Configurar mi bot personalizado",
                callback_data=CALLBACK_CUSTOM_BOT_START
            )],

            [InlineKeyboardButton(
                "📩 Hablar con un asesor",
                callback_data=CALLBACK_COMMERCIAL_CONTACT
            )],

            [InlineKeyboardButton(
                "💬 Ayuda sobre este menú",
                callback_data=CALLBACK_COMMERCIAL_HELP
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK_SOLUTIONS
            )]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "🤖 Crear mi bot personalizado\n\n"
            "Esta opción es para quien quiere una experiencia más profesional con su propio bot de Telegram.\n\n"
            "El cliente crea su bot en BotFather y configura su información, marca, textos, grupos y planes. "
            "Después de completar la configuración, realiza el pago y el sistema se activa.\n\n"
            "✅ Incluye:\n"
            "• Bot propio con nombre y marca del cliente.\n"
            "• Configuración de comunidades, grupos y planes.\n"
            "• Pagos y accesos automatizados.\n"
            "• Gestión de usuarios, links y permisos.\n"
            "• Posibilidad de usar IA y soporte dentro del sistema.\n\n"
            "⚠️ Importante:\n"
            "El bot personalizado no tiene prueba gratuita. "
            "Primero se prepara la configuración completa y, una vez pagado, el bot empieza a funcionar.\n\n"
            "Si la suscripción se detiene o no se renueva, el bot podrá quedar bloqueado o desactivado. "
            "Guardaremos la configuración durante 15 días para que puedas reactivar el servicio sin perder lo preparado.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_custom_bot_start":

        print(
            "commercial_form_start:",
            f"query.from_user.id={query.from_user.id if query.from_user else '-'}",
            f"username={query.from_user.username if query.from_user and query.from_user.username else '-'}",
            f"first_name={query.from_user.first_name if query.from_user and query.from_user.first_name else '-'}",
            "request_type=custom_bot"
        )

        context.user_data["commercial_form"] = True
        context.user_data["commercial_form_type"] = "custom_bot"
        context.user_data["commercial_form_step"] = 1
        context.user_data["commercial_form_data"] = {}
        context.user_data["commercial_form_waiting"] = "creator_setup_waiting_project_name"

        await send_clean_message(
            context,
            query.message.chat_id,
            "Indica el nombre del proyecto o comunidad."
        )

        return


    if data == "commercial_contact":

        await delete_query_message_safely(query)

        print(
            "commercial_contact_request:",
            f"query.from_user.id={query.from_user.id if query.from_user else '-'}",
            f"username={query.from_user.username if query.from_user and query.from_user.username else '-'}",
            f"first_name={query.from_user.first_name if query.from_user and query.from_user.first_name else '-'}"
        )

        request_id = create_commercial_request(
            query.from_user,
            "support_contact",
            {
                "contact_text": "Solicitud comercial desde botón Hablar con un asesor."
            }
        )

        await notify_commercial_request(
            context,
            request_id,
            "support_contact",
            query.from_user,
            {
                "contact_text": "Solicitud comercial desde botón Hablar con un asesor."
            }
        )

        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK_SOLUTIONS
            )]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "📩 Solicitud recibida\n\n"
            "Un administrador revisará la solicitud y podrá ayudarte con la mejor opción según lo que necesites.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="commercial"
        )

        return


    if data == "subscriptions_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="subscriptions"
        )

        return


    if data == "group_plans_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="group_plans"
        )

        return


    if data == "support_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="support"
        )

        return


    if data == "admin_users_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="admin_users"
        )

        return


    if data == "admin_groups_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="admin_groups"
        )

        return


    if data == "admin_payments_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="admin_payments"
        )

        return


    if data == "admin_logs_help":

        await activate_ai_help_context(
            update,
            context,
            help_context="admin_logs"
        )

        return


    if data == "public_admin_panel":

        await expire_expired_commercial_trials(context)

        if not has_any_admin_permission(user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ No tienes permisos de gestión."
            )

            return


        keyboard = build_admin_panel_keyboard(user_id)


        if not keyboard:

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ No tienes permisos de gestión."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,

            build_admin_home_text(user_id),

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # RBAC — BLOQUEAR CALLBACKS ADMIN
    # =========================

    if is_admin_callback(data):

        if is_super_admin(user_id):

            pass

        elif callback_requires_super_admin(data):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return

        elif not has_any_permission_any_group(
            user_id,
            get_required_permissions_for_callback(data)
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para usar esta sección."
            )

            return


    if is_ad_promo_ui_callback(data):

        if not await enforce_ad_promo_owner_addon_gate(query, context, data, user_id):

            return


    if data == "admin_global_panel":

        await send_clean_message(
            context,
            query.message.chat_id,
            "👑 Panel global del bot: índice principal de la plataforma.\n\n"
            "Desde aquí entras a monitor beta, satisfacción, soporte, marketplace, propietarios y los dos submenús separados de configuración y herramientas.",
            reply_markup=build_admin_global_panel_keyboard()
        )

        return


    # El panel de publicidad se ha movido a ad_promo_callbacks.py (cuarta fase de
    # partir este archivo). El despacho va AQUÍ y no arriba a propósito: las dos
    # puertas de permisos de encima caen hacia estas ramas, y subirlo se las
    # saltaría.
    if await handle_ad_promo_callbacks(
        update, context, query, user_id, data
    ) is not AD_PROMO_NOT_HANDLED:

        return




    if data == "admin_ai_center":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🧠 Centro IA\n\n"
            "Asistente interno para resumir errores, pagos, usuarios, encuestas, soporte y auditorías del bot.\n\n"
            "La IA solo diagnostica, resume y prepara borradores. No concede accesos, no marca pagos como pagados y no ejecuta cambios peligrosos sin confirmación.",
            reply_markup=build_admin_ai_center_keyboard()
        )

        return


    if data == "admin_ai_ask":

        await activate_ai_help_context(
            update,
            context,
            help_context="superadmin"
        )

        return


    if data == "admin_ai_feedback":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_admin_ai_feedback_text(),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Centro IA", callback_data="admin_ai_center")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    admin_ai_questions = {
        "admin_ai_errors": (AI_CONTEXT_SUPERADMIN_DASHBOARD, "Haz un diagnóstico de errores recientes del bot y dime dónde mirar primero."),
        "admin_ai_payments": (AI_CONTEXT_PAYMENT_DIAGNOSTICS, "Haz un diagnóstico de pagos por proveedor, scope y estados problemáticos."),
        "admin_ai_users": (AI_CONTEXT_USER_TRACKING, "Resume la actividad de usuarios dentro del bot y comunidades gestionadas."),
        "admin_ai_surveys": (AI_CONTEXT_SUPERADMIN_DASHBOARD, "Resume encuestas, satisfacción y señales de usuarios pendientes o problemas de respuesta."),
        "admin_ai_support": (AI_CONTEXT_SUPERADMIN_DASHBOARD, "Resume soporte reciente y detecta patrones por pagos, accesos, ubicación, códigos o comunidades."),
        "admin_ai_audits": (AI_CONTEXT_SUPERADMIN_DASHBOARD, "Resume auditorías de botones y paneles, y destaca callbacks o navegación que conviene revisar."),
        "admin_ai_codex_task": (AI_CONTEXT_SUPERADMIN_DASHBOARD, "Prepara una tarea breve para Codex con problema, contexto, restricciones, verificación y entrega esperada.")
    }


    if data in admin_ai_questions:

        context_key, question = admin_ai_questions[data]
        result = build_contextual_ai_answer(
            user_id,
            question,
            role=AI_ROLE_SUPERADMIN,
            context_key=context_key
        )

        await send_ai_result_message(
            context,
            query.message.chat_id,
            result,
            back_callback="admin_ai_center"
        )

        return


    if data.startswith("admin_help_"):

        help_key = data.replace("admin_help_", "", 1)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_admin_context_help_text(help_key),
            reply_markup=build_admin_context_help_keyboard(help_key)
        )

        return


    if data in (
        "admin_button_audit",
        "admin_button_audit_refresh"
    ):

        report = build_admin_button_audit_report()
        context.user_data["admin_button_audit_report"] = report

        await send_clean_message(
            context,
            query.message.chat_id,
            format_admin_button_audit_summary(report),
            reply_markup=build_admin_button_audit_keyboard()
        )

        return


    if data == "admin_button_audit_detail":

        report = context.user_data.get("admin_button_audit_report")


        if not report:

            report = build_admin_button_audit_report()
            context.user_data["admin_button_audit_report"] = report


        await send_clean_message(
            context,
            query.message.chat_id,
            format_admin_button_audit_detail(report),
            reply_markup=build_admin_button_audit_keyboard()
        )

        return


    if data == "admin_user_tracking":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_user_tracking_overview_text(),
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_user_tracking_search":

        context.user_data["admin_user_tracking_search"] = True

        await send_clean_message(
            context,
            query.message.chat_id,
            "👤 Buscar usuario\n\nEscribe un user_id o @username para ver actividad registrada dentro del bot.",
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_user_tracking_latest":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_user_tracking_events_text("🕒 Última actividad"),
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_user_tracking_groups":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_user_tracking_groups_text(),
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_user_tracking_payments":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_user_tracking_payments_text(),
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_user_tracking_codes":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_user_tracking_events_text("🎟 Códigos canjeados", event_type="code_redeemed"),
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_platform_plan_prices":

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Solo el super admin puede tocar los precios de la plataforma."
            )

            return


        from platform_plan_service import (
            PLATFORM_PLAN_PRODUCT,
            describe_plan_period,
            format_plan_amount,
        )

        # Se listan TODOS los planes, con precio o sin él: el que no lo tiene es
        # justo el que hay que arreglar, y esconderlo sería esconder el motivo de
        # que nadie pueda pagar.
        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name, duration_days, amount, COALESCE(currency, 'EUR')
                FROM commercial_plans
                WHERE product_type=%s
                ORDER BY duration_days ASC, id ASC

            """, (PLATFORM_PLAN_PRODUCT,))

            filas = cur.fetchall() or []


        lineas = [
            "💰 Precio de publicar comunidad",
            "",
            "Esto es lo que paga un creador por publicar su comunidad en el "
            "bot. Mientras ninguna duración tenga precio, nadie puede pagar: "
            "solo puede dejar una solicitud para que la revises a mano.",
        ]

        filas_teclado = []

        for plan_id, nombre, dias, importe, moneda in filas:

            plan = {"amount": importe, "currency": moneda,
                    "duration_days": dias}
            precio = format_plan_amount(plan) or "sin precio"

            lineas.append("")
            lineas.append(
                f"• {nombre}: {precio} {describe_plan_period(plan)}".rstrip()
            )

            filas_teclado.append([InlineKeyboardButton(
                f"✏️ {nombre} · {precio}",
                callback_data=f"admin_platform_plan_price_{plan_id}"
            )])


        filas_teclado.append([InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_global_commercial_plans"
        )])

        await send_clean_message(
            context,
            query.message.chat_id,
            "\n".join(lineas),
            reply_markup=InlineKeyboardMarkup(filas_teclado)
        )

        return


    if data.startswith("admin_platform_plan_price_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Solo el super admin puede tocar los precios de la plataforma."
            )

            return


        plan_id = data[len("admin_platform_plan_price_"):]

        if not plan_id.isdigit():

            await query.message.reply_text("❌ Plan no válido.")

            return


        context.user_data["setting_platform_plan_price_id"] = int(plan_id)

        await query.message.reply_text(
            "Escribe el precio EN EUROS (por ejemplo 29 o 29,50).\n\n"
            "Se cobrará con tarjeta y se renovará cada periodo del plan. Si "
            "cambias un precio ya publicado, solo afecta a las altas nuevas: "
            "quien ya esté suscrito conserva el suyo.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "⬅️ Cancelar",
                callback_data="admin_platform_plan_prices"
            )]])
        )

        return


    if data == "admin_user_tracking_support":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_user_tracking_events_text("🛟 Soporte", event_type="support_message"),
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_user_tracking_surveys":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_user_tracking_events_text("😊 Encuestas", event_type="survey_completed"),
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_user_tracking_locations":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_user_tracking_events_text("📍 Ubicaciones", event_type="location_shared"),
            reply_markup=build_user_tracking_panel_keyboard()
        )

        return


    if data == "admin_owners_panel":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🧑‍💼 Panel de propietarios: gestiona solicitudes, trials y cupos.\n\n"
            "No se mezcla con códigos de grupo, planes de acceso ni configuración de comunidades concretas.",
            reply_markup=build_admin_owners_panel_keyboard()
        )

        return


    # Tramo movido a admin_payment_provider_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_payment_provider_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_PAYMENT_PROVIDER_NOT_HANDLED:

        return




    # Tramo movido a admin_guardarian_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_guardarian_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_GUARDARIAN_NOT_HANDLED:

        return










    # Tramo movido a admin_changenow_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_changenow_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_CHANGENOW_NOT_HANDLED:

        return








    if data in (
        "admin_global_marketplace",
        "admin_global_commercial_plans",
        "admin_payment_providers",
        "admin_global_config",
        "admin_global_tools"
    ):

        info_texts = {
            "admin_global_marketplace": (
                "🏪 Marketplace global\n\n"
                "Vista de catálogo global. Desde aquí puedes abrir el marketplace como usuario y volver a configuración o propietarios."
            ),
            "admin_global_commercial_plans": (
                "💳 Planes comerciales del bot\n\n"
                "Zona informativa para revisar suscripciones comerciales, códigos globales y gestión de owners. No se mezcla con planes de acceso de cada grupo."
            ),
            "admin_payment_providers": build_payment_methods_admin_text(),
            "admin_global_config": (
                "⚙️ Configuración global\n\n"
                "Opciones de plataforma y configuración comercial. No incluye herramientas técnicas ni logs operativos para mantener el menú claro."
            ),
            "admin_global_tools": (
                "🛠 Herramientas internas\n\n"
                "Herramientas de diagnóstico, revisión beta y mantenimiento interno. No mezcla configuración comercial ni satisfacción."
            )
        }
        reply_markups = {
            "admin_global_marketplace": build_admin_global_marketplace_keyboard(),
            "admin_global_commercial_plans": build_admin_global_commercial_plans_keyboard(),
            "admin_payment_providers": build_admin_payment_providers_keyboard(),
            "admin_global_config": build_admin_global_config_keyboard(),
            "admin_global_tools": build_admin_global_tools_keyboard()
        }

        await send_clean_message(
            context,
            query.message.chat_id,
            info_texts[data],
            reply_markup=reply_markups.get(data, build_admin_global_panel_keyboard())
        )

        return


    # Tramo movido a admin_commercial_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_commercial_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_COMMERCIAL_NOT_HANDLED:

        return






    if data == "admin_customer_satisfaction":

        await send_clean_message(
            context,
            query.message.chat_id,
            "😊 Satisfacción de clientes\n\n"
            "Envía encuestas y revisa la opinión de usuarios, propietarios y administradores.\n\n"
            "Para que sea justo, el bot nunca reenvía por defecto a usuarios que ya respondieron.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    # Tramo movido a admin_satisfaction_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_satisfaction_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_SATISFACTION_NOT_HANDLED:

        return




    if data.startswith("satisfaction_start_"):

        survey_id = extract_commercial_request_id(
            data,
            "satisfaction_start_"
        )

        if survey_id is None:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        response_id = get_or_create_customer_satisfaction_response(
            survey_id,
            user_id
        )

        context.user_data["customer_satisfaction_response_id"] = response_id
        await send_customer_satisfaction_question(
            context,
            query.message.chat_id,
            response_id
        )

        return


    if data.startswith("satisfaction_rate_"):

        parts = data.split("_")

        if len(parts) != 5 or not all(part.isdigit() for part in parts[2:]):
            await query.message.reply_text("❌ Respuesta no válida.")
            return

        response_id = int(parts[2])
        question_id = int(parts[3])
        rating = int(parts[4])

        if not customer_satisfaction_response_belongs_to_user(
            response_id,
            user_id
        ):

            await query.message.reply_text("⛔ No puedes responder esta encuesta.")
            return

        if rating < 1 or rating > 5:
            await query.message.reply_text("❌ Respuesta no válida.")
            return

        save_customer_satisfaction_answer(
            response_id,
            question_id,
            rating=rating
        )

        await send_customer_satisfaction_question(
            context,
            query.message.chat_id,
            response_id
        )

        return


    if data == "satisfaction_detail":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_satisfaction_survey_list_text(user_id, context),
            reply_markup=build_satisfaction_survey_list_keyboard(user_id, context)
        )

        return


    if data.startswith("satisfaction_survey_") and not data.startswith("satisfaction_survey_users_") and not data.startswith("satisfaction_survey_summary_"):

        survey_id = extract_commercial_request_id(
            data,
            "satisfaction_survey_"
        )

        if survey_id is None:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        if not user_can_view_satisfaction_survey(user_id, survey_id):
            await query.message.reply_text("⛔ No tienes permiso para ver esta encuesta.")
            return

        await send_clean_message(
            context,
            query.message.chat_id,
            build_satisfaction_survey_detail_text(survey_id),
            reply_markup=build_satisfaction_survey_detail_keyboard(survey_id)
        )

        return


    if data.startswith("satisfaction_survey_users_"):

        payload = data.replace("satisfaction_survey_users_", "", 1)
        parts = payload.rsplit("_", 1)

        if len(parts) != 2 or not parts[0].isdigit():
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        survey_id = int(parts[0])
        status = parts[1]

        if not user_can_view_satisfaction_survey(user_id, survey_id):
            await query.message.reply_text("⛔ No tienes permiso para ver esta encuesta.")
            return

        await send_clean_message(
            context,
            query.message.chat_id,
            build_satisfaction_survey_users_text(survey_id, status),
            reply_markup=build_satisfaction_survey_users_keyboard(survey_id, status)
        )

        return


    if data.startswith("satisfaction_survey_summary_"):

        survey_id = extract_commercial_request_id(
            data,
            "satisfaction_survey_summary_"
        )

        if survey_id is None:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        if not user_can_view_satisfaction_survey(user_id, survey_id):
            await query.message.reply_text("⛔ No tienes permiso para ver esta encuesta.")
            return

        await send_clean_message(
            context,
            query.message.chat_id,
            build_satisfaction_summary_answers_text(survey_id),
            reply_markup=build_satisfaction_survey_detail_keyboard(survey_id)
        )

        return


    if data.startswith("satisfaction_response_"):

        response_id = extract_commercial_request_id(
            data,
            "satisfaction_response_"
        )

        if response_id is None:
            await query.message.reply_text("❌ Respuesta no válida.")
            return

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT survey_id
                    FROM customer_satisfaction_responses
                    WHERE id=%s
                    LIMIT 1
                """, (response_id,))
                row = cur.fetchone()
        except Exception:
            row = None

        survey_id = safe_satisfaction_value(row, 0)

        if not survey_id or not user_can_view_satisfaction_survey(user_id, survey_id):
            await query.message.reply_text("⛔ No tienes permiso para ver esta respuesta.")
            return

        await send_clean_message(
            context,
            query.message.chat_id,
            build_satisfaction_response_detail_text(response_id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver", callback_data=f"satisfaction_survey_{survey_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_backup_"):

        # Los backups del propietario viven en owner_backup_callbacks.py. Aquí
        # no basta con retornar siempre: en el tramo original había ramas que
        # caían a propósito hacia las de abajo, y un owner_backup_* que no
        # encajase con ninguna seguía hasta el resto de button(). El centinela
        # distingue "atendido" de "no encajó".
        if await handle_owner_backup_callbacks(
            update, context, query, user_id, data
        ) is not OWNER_BACKUP_NOT_HANDLED:

            return



    # Tramo movido a group_admin_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_group_admin_callbacks(
        update, context, query, user_id, data
    ) is not GROUP_ADMIN_NOT_HANDLED:

        return








    # Tramo movido a add_group_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_add_group_callbacks(
        update, context, query, user_id, data
    ) is not ADD_GROUP_NOT_HANDLED:

        return




    if data.startswith("gga_t_"):

        payload = data.replace("gga_t_", "", 1)

        try:

            group_id_text, target_user_id_text, permission_key = payload.split("_", 2)
            group_id = int(group_id_text)
            target_user_id = int(target_user_id_text)

        except Exception:

            await query.message.reply_text("❌ Permiso no válido.")

            return


        permission = GROUP_ADMIN_PERMISSION_BY_KEY.get(permission_key)


        if not permission:

            await query.message.reply_text("❌ Permiso no válido.")

            return


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if int(context.user_data.get("group_admin_target_user_id") or 0) != target_user_id:

            await query.message.reply_text(
                "❌ El usuario pendiente no coincide.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        permissions = context.user_data.setdefault(
            "group_admin_permissions",
            {
                current_permission: False
                for _key, _label, current_permission in GROUP_ADMIN_PERMISSION_OPTIONS
            }
        )
        permissions[permission] = not permissions.get(permission, False)

        await send_clean_message(
            context,
            query.message.chat_id,
            "Permisos del nuevo admin:\n\n"
            + format_group_admin_permission_list(permissions),
            reply_markup=build_group_admin_permissions_keyboard(
                group_id,
                target_user_id,
                permissions,
                "gga_t"
            )
        )

        return












    if data.startswith("edit_admin_permissions_user_"):

        payload = data.replace("edit_admin_permissions_user_", "", 1)

        try:

            group_id_text, target_user_id_text = payload.split("_", 1)
            group_id = int(group_id_text)
            target_user_id = int(target_user_id_text)

        except Exception:

            await query.message.reply_text("❌ Admin no válido.")

            return


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        admin_row = fetch_group_admin_permissions(group_id, target_user_id)


        if not admin_row or admin_row.get("role") == "GROUP_OWNER":

            await query.message.reply_text("❌ Admin no editable.")

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "✏️ Editar permisos\n\n"
            + format_group_admin_permission_list(admin_row["permissions"]),
            reply_markup=build_group_admin_edit_permissions_keyboard(
                group_id,
                target_user_id,
                admin_row["permissions"]
            )
        )

        return


    if data.startswith("gap_t_"):

        payload = data.replace("gap_t_", "", 1)

        try:

            group_id_text, target_user_id_text, permission_key = payload.split("_", 2)
            group_id = int(group_id_text)
            target_user_id = int(target_user_id_text)

        except Exception:

            await query.message.reply_text("❌ Permiso no válido.")

            return


        permission = GROUP_ADMIN_PERMISSION_BY_KEY.get(permission_key)


        if not permission:

            await query.message.reply_text("❌ Permiso no válido.")

            return


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        admin_row = fetch_group_admin_permissions(group_id, target_user_id)


        if not admin_row or admin_row.get("role") == "GROUP_OWNER":

            await query.message.reply_text("❌ Admin no editable.")

            return


        permissions = admin_row["permissions"]
        permissions[permission] = not permissions.get(permission, False)
        save_group_admin_permissions(
            group_id,
            target_user_id,
            permissions
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Permisos actualizados.\n\n"
            + format_group_admin_permission_list(permissions),
            reply_markup=build_group_admin_edit_permissions_keyboard(
                group_id,
                target_user_id,
                permissions
            )
        )

        return








    # Tramo movido a admin_support_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_support_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_SUPPORT_NOT_HANDLED:

        return














































    if data.startswith("commercial_request_chat_"):

        request_id = extract_commercial_request_id(
            data,
            "commercial_request_chat_"
        )

        request_row = fetch_commercial_request(request_id)


        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_commercial_request_chat_reply(
            context,
            request_id,
            "user"
        )

        await query.message.reply_text(
            f"💬 Responder solicitud comercial #{request_id}\n\n"
            "Escribe ahora tu respuesta."
        )

        return










    if data.startswith("admin_trial_visibility_start_home_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_trial_visibility_start_home_"
        )

        await handle_admin_trial_visibility_approval(
            context,
            query,
            user_id,
            request_id,
            "start_home"
        )

        return


    if data.startswith("admin_trial_visibility_explore_only_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_trial_visibility_explore_only_"
        )

        await handle_admin_trial_visibility_approval(
            context,
            query,
            user_id,
            request_id,
            "explore_only"
        )

        return


    if data.startswith("admin_trial_visibility_hidden_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_trial_visibility_hidden_"
        )

        await handle_admin_trial_visibility_approval(
            context,
            query,
            user_id,
            request_id,
            "hidden"
        )

        return






    if data.startswith("commercial_setup_free_group_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        await query.message.reply_text(
            "🆓 Grupo gratuito\n\n"
            "Este modo permitirá que la comunidad siga pasando por los filtros del bot aunque no cobre acceso. "
            "La configuración completa del grupo se hará en la siguiente fase."
        )

        return


    if data.startswith("commercial_setup_paid_group_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        await query.message.reply_text(
            "💳 Grupo de pago\n\n"
            "Este modo necesita planes y al menos un método de cobro configurado antes de activar ventas. "
            "Puede ser Stripe, PayPal, Revolut, ChangeNOW, Guardarian o promociones según el caso."
        )

        return


    if data.startswith("commercial_setup_owner_stripe_"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        await query.message.reply_text(
            "🏦 Stripe del dueño\n\n"
            "El dueño usará su propia cuenta de Stripe para cobrar. "
            "La conexión y validación de credenciales queda preparada para una fase posterior."
        )

        return


    if data.startswith(LEGACY_ADMIN_PLATFORM_STRIPE_CALLBACK_PREFIX):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        await query.message.reply_text(
            "Esta opción ya no está disponible.\n\n"
            "Si la comunidad será de pago, el creador debe configurar su propia cuenta o sistema de cobro."
        )

        return


    # =========================
    # MIS SUSCRIPCIONES ACTIVAS
    # =========================

    if data == "mis_subs":

        await clear_location_flow_navigation(context, query.message.chat_id)

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id


        try:

            with conn.cursor() as cur:

                # Se trae también la caducidad: antes la lista solo decía
                # "Tus suscripciones activas" y el cliente tenía que abrir cada
                # comunidad para saber cuánto le quedaba en cada una.
                # BOOL_OR(... IS NULL) distingue un acceso permanente de uno con
                # fecha, que MAX() por sí solo no podría.
                cur.execute("""

                    SELECT g.telegram_group_id,
                           g.name,
                           COALESCE(g.community_type, 'group'),
                           BOOL_OR(u.expiration IS NULL) AS es_permanente,
                           MAX(u.expiration) AS caduca

                    FROM users u

                    JOIN groups g
                    ON u.group_id = g.id

                    WHERE u.user_id=%s
                    AND COALESCE(u.subscription_active, FALSE)=TRUE
                    AND (
                        u.expiration IS NULL
                        OR u.expiration > NOW()
                    )
                    AND g.is_active=TRUE
                    AND g.telegram_group_id != 0

                    GROUP BY g.telegram_group_id,
                             g.name,
                             COALESCE(g.community_type, 'group')

                    ORDER BY g.name ASC

                """, (user_id,))

                rows = cur.fetchall()

        except Exception as e:

            print("Error cargando suscripciones:", e)

            await query.message.reply_text(
                "❌ Error cargando suscripciones."
            )

            return


        if not rows:

            await reply_with_recover_navigation(
                query,
                "⚠️ No tienes suscripciones activas."
            )

            return


        keyboard = []
        lineas = []


        for group_id, group_name, community_type, es_permanente, caduca in rows:

            kind_cap = format_community_kind_capitalized(community_type)

            if es_permanente:

                restante = "sin caducidad"

            elif caduca:

                restante = f"quedan {format_tiempo_restante(caduca)}"

            else:

                restante = "caducidad desconocida"


            lineas.append(f"📦 {group_name} · {kind_cap}\n   ⏳ {restante}")

            keyboard.append([

                InlineKeyboardButton(

                    f"📦 {group_name} · {kind_cap}",

                    callback_data=f"mysub_{group_id}"

                )

            ])


        keyboard.append([

            InlineKeyboardButton(

                "💬 Ayuda sobre este menú",

                callback_data=CALLBACK_SUBSCRIPTIONS_HELP

            )

        ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="back_groups"

            )

        ])


        plural = "acceso" if len(lineas) == 1 else "accesos"

        await query.message.reply_text(

            f"🎟 Tienes {len(lineas)} {plural} activo"
            f"{'' if len(lineas) == 1 else 's'}:\n\n"
            + "\n\n".join(lineas)
            + "\n\nToca una comunidad para recibir tu enlace de entrada.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # DETALLE DE SUSCRIPCIÓN
    # =========================

    # Tramo movido a mysub_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_mysub_callbacks(
        update, context, query, user_id, data
    ) is not MYSUB_NOT_HANDLED:

        return




    if data.startswith("free_access_"):

        try:

            await query.message.delete()

        except Exception:

            pass


        group_id = extract_commercial_request_id(
            data,
            "free_access_"
        )

        if group_id is None:

            await query.message.reply_text(
                "❌ Comunidad no válida."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(location_gate_enabled, FALSE),
                       allowed_region,
                       allowed_region_type
                FROM groups
                WHERE id=%s
                AND is_active=TRUE
                AND (
                    COALESCE(is_free_group, FALSE)=TRUE
                    OR COALESCE(is_free, FALSE)=TRUE
                )
                LIMIT 1

            """, (group_id,))

            group_row = cur.fetchone()


        if not group_row:

            await query.message.reply_text(
                "❌ Comunidad gratuita no encontrada o no disponible."
            )

            return


        access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


        if should_block_new_group_purchase(access_state):

            await send_existing_group_access_notice(
                context,
                query.message.chat_id,
                user_id,
                group_id,
                provider="free",
                event_type="free_access_blocked_existing_access",
                access_state=access_state
            )

            return


        location_gate_enabled, allowed_region, allowed_region_type = group_row


        if location_gate_enabled is True:

            await request_location_verification(
                context,
                query.message.chat_id,
                group_id,
                "free_access",
                telegram_user=query.from_user
            )

            return


        await create_free_access_for_user(
            context,
            query.message.chat_id,
            query.from_user,
            group_id
        )

        return


    # =========================
    # ENTRAR A GRUPO
    # =========================

    if is_numeric_group_callback(data):

        try:
            await query.message.delete()
        except:
            pass


        group_id = parse_callback_int(data, "group_")

        if group_id is None:

            await query.message.reply_text(
                "❌ Comunidad no válida."
            )

            return


        # =========================
        # GUARDAR GRUPO SELECCIONADO
        # =========================

        context.user_data["selected_group"] = group_id


        # =========================
        # OBTENER PLANES DEL GRUPO
        # =========================

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT (
                        COALESCE(is_free_group, FALSE)
                        OR COALESCE(is_free, FALSE)
                    )
                    FROM groups
                    WHERE id=%s
                    AND is_active=TRUE

                """, (group_id,))

                group_row = cur.fetchone()


                if not group_row:

                    await send_clean_message(
            context,
            query.message.chat_id,
                        "❌ Comunidad no encontrada o no disponible."
                    )

                    return


                is_free_group = group_row[0] is True

                increment_community_stat(group_id, "access_clicks")

                cur.execute("""

                    SELECT id,
                           name,
                           price_id,
                           amount,
                           currency,
                           COALESCE(NULLIF(payment_provider, ''), 'stripe'),
                           duration_days

                    FROM plans

                    WHERE group_id=%s
                    AND is_active=TRUE

                    ORDER BY amount ASC NULLS LAST, id ASC

                """, (group_id,))

                plans = cur.fetchall()

        except Exception as e:

            print("Error cargando planes:", e)

            await send_clean_message(
            context,
            query.message.chat_id,
                "❌ Error cargando planes."
            )

            return


        access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


        if should_block_new_group_purchase(access_state):

            await send_existing_group_access_notice(
                context,
                query.message.chat_id,
                user_id,
                group_id,
                provider="marketplace",
                access_state=access_state
            )

            return


        if is_free_group:

            await send_clean_message(
            context,
            query.message.chat_id,
                "Esta comunidad es gratuita, pero el acceso está protegido por el bot.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🔓 Entrar gratis",
                        callback_data=f"free_access_{group_id}"
                    )],
                    [InlineKeyboardButton(
                        "🎟 Canjear código de esta comunidad",
                        callback_data=f"group_user_promo_redeem_start_{group_id}"
                    )],
                    [InlineKeyboardButton(
                        "💬 Ayuda sobre este menú",
                        callback_data=CALLBACK_GROUP_PLANS_HELP
                    )],
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data="back_groups"
                    )]
                ])
            )

            return


        if not plans:

            await send_clean_message(
            context,
            query.message.chat_id,
                "Este grupo aún no está configurado como gratuito ni tiene planes activos."
            )

            return


        keyboard = []
        paypal_available = is_paypal_group_checkout_available(group_id)
        revolut_available = is_revolut_group_checkout_available(group_id)
        changenow_available = is_changenow_group_checkout_available(group_id)
        guardarian_available = is_guardarian_group_checkout_available(group_id)


        for plan_id, name, price_id, amount, currency, payment_provider, duration_days in plans:

            payment_provider = normalize_plan_payment_provider(payment_provider)

            # La duración va en la etiqueta: el cliente tenía que elegir entre
            # 15 EUR y 120 EUR sin ver cuánto duraba cada uno, y el nombre del
            # plan lo pone el dueño y no siempre lo dice.
            duracion_texto = format_plan_duration_short(duration_days)

            if amount and currency:

                button_text = f"{name} — {amount} {currency}"

                if duracion_texto:

                    button_text += f" · {duracion_texto}"

            else:

                button_text = name


            if payment_provider == OWNER_PAYMENT_PROVIDER_STRIPE:

                if not price_id:

                    continue

                keyboard.append([

                    InlineKeyboardButton(

                        f"💳 Tarjeta / Stripe — {button_text}",

                        callback_data=price_id

                    )

                ])


            if payment_provider == OWNER_PAYMENT_PROVIDER_PAYPAL and paypal_available:

                keyboard.append([

                    InlineKeyboardButton(

                        f"🅿️ PayPal — {button_text}",

                        callback_data=f"paypal_group_plan_{group_id}_{plan_id}"

                    )

                ])


            if payment_provider == OWNER_PAYMENT_PROVIDER_REVOLUT and revolut_available:

                keyboard.append([

                    InlineKeyboardButton(

                        f"🏦 Revolut — {button_text}",

                        callback_data=f"revolut_group_plan_{group_id}_{plan_id}"

                    )

                ])


            if payment_provider == OWNER_PAYMENT_PROVIDER_CHANGENOW and changenow_available:

                keyboard.append([

                    InlineKeyboardButton(

                        f"💱 Cripto / ChangeNOW — {button_text}",

                        callback_data=f"changenow_group_plan_{group_id}_{plan_id}"

                    )

                ])


            if payment_provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN and guardarian_available:

                keyboard.append([

                    InlineKeyboardButton(

                        f"💳 EUR → USDT / Guardarian — {button_text}",

                        callback_data=f"guardarian_group_plan_{group_id}_{plan_id}"

                    )

                ])


        keyboard.append([

            InlineKeyboardButton(

                "🎟 Canjear código de esta comunidad",

                callback_data=f"group_user_promo_redeem_start_{group_id}"

            )

        ])


        keyboard.append([

            InlineKeyboardButton(

                "💬 Ayuda sobre este menú",

                callback_data=CALLBACK_GROUP_PLANS_HELP

            )

        ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="back_groups"

            )

        ])


        # Antes esto abría con tres líneas sobre familias de métodos de pago,
        # que el cliente no ha preguntado, y los planes quedaban debajo. Ahora
        # primero va lo que compra y luego, en corto, cómo puede pagarlo.
        intro_text = (
            "💳 Elige tu acceso\n\n"
            f"{format_plans_summary(plans)}\n\n"
            "Recibes tu enlace de entrada al instante tras el pago.\n"
            "Puedes pagar con tarjeta, PayPal, Revolut o cripto, según lo que "
            "tenga activo esta comunidad."
        )


        if access_state.get("subscription_status") == "expired":

            intro_text = (
                "⚠️ Tu acceso anterior ha caducado\n\n"
                "Puedes recuperarlo eligiendo un plan:\n\n"
                f"{format_plans_summary(plans)}\n\n"
                "Recuperas el acceso al instante tras el pago."
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            intro_text,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # VOLVER A GRUPOS
    # =========================

    if data == "back_groups":

        try:
            await query.message.delete()
        except:
            pass

        await start(update, context)

        return


    if data.startswith("payment_status_group_"):

        group_id = extract_commercial_request_id(
            data,
            "payment_status_group_"
        )

        if group_id is None:

            await query.message.reply_text(
                "❌ Comunidad no válida.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        access_state = await resolve_group_access_state_for_user(
            context,
            query.from_user.id,
            group_id
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_existing_group_access_text(access_state),
            reply_markup=build_existing_group_access_keyboard(
                group_id,
                access_state
            )
        )

        return


    # =========================
    # RECUPERAR ACCESO
    # =========================

    # Tramo movido a recover_access_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_recover_access_callbacks(
        update, context, query, user_id, data
    ) is not RECOVER_ACCESS_NOT_HANDLED:

        return




    # =========================
    # BLOQUE: PROPIETARIOS Y COMUNIDADES
    # =========================

    if data == "admin_block_owners":

        if not is_super_admin(user_id):

            await query.answer("Solo el propietario principal.", show_alert=True)
            return


        try:
            await query.message.delete()
        except:
            pass

        keyboard = [
            [InlineKeyboardButton("🧑‍💼 Panel de propietarios", callback_data="admin_owners_panel")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("📦 Gestión de grupos", callback_data="menu_groups")],
            [InlineKeyboardButton("👥 Admins de grupos", callback_data="group_admin_panel")],
            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "🧑‍💼 PROPIETARIOS Y COMUNIDADES",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    # =========================
    # BLOQUE: USUARIOS Y ACCESOS
    # =========================

    if data == "admin_block_users":

        if not is_super_admin(user_id):

            await query.answer("Solo el propietario principal.", show_alert=True)
            return


        try:
            await query.message.delete()
        except:
            pass

        keyboard = [
            [InlineKeyboardButton("👥 Gestión de usuarios", callback_data="menu_users")],
            [InlineKeyboardButton("🎟 Accesos y códigos", callback_data="menu_codes")],
            [InlineKeyboardButton("🎟 Códigos por grupo", callback_data="admin_group_user_codes")],
            [InlineKeyboardButton("🎟 Códigos promocionales", callback_data="admin_commercial_promo_codes")],
            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "👥 USUARIOS Y ACCESOS",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    # =========================
    # BLOQUE: PAGOS Y NEGOCIO
    # =========================

    if data == "admin_block_business":

        if not is_super_admin(user_id):

            await query.answer("Solo el propietario principal.", show_alert=True)
            return


        try:
            await query.message.delete()
        except:
            pass

        keyboard = [
            [InlineKeyboardButton("💳 Gestión de pagos", callback_data="menu_payments")],
            [InlineKeyboardButton("📊 Negocio y estadísticas", callback_data="menu_business")],
            [InlineKeyboardButton("🛡 Backup premium", callback_data="owner_backup_panel")],
            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
        ]

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 PAGOS Y NEGOCIO",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    # =========================
    # MENÚ USUARIOS
    # =========================

    if data == "menu_users":

        try:
            await query.message.delete()
        except:
            pass

        permissions = get_admin_permissions(user_id)

        keyboard = []


        if has_any_permission(permissions, ["can_view_users", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("📋 Ver usuarios", callback_data="admin_users")])

            keyboard.append([InlineKeyboardButton("🔍 Buscar usuario", callback_data="admin_search_user")])


        if has_any_permission(permissions, ["can_kick_users", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("🚫 Expulsar usuario", callback_data="admin_kick_user")])


        if has_any_permission(permissions, ["can_ban_users", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("⛔ Banear usuario", callback_data="admin_ban_user")])


        if has_any_permission(permissions, ["can_unban_users", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("♻️ Desbanear usuario", callback_data="admin_unban_user")])


        if has_any_permission(permissions, ["can_reset_warnings", "can_manage_users"]):

            keyboard.append([InlineKeyboardButton("🔄 Reset warnings", callback_data="admin_reset_warnings")])


        if is_super_admin(user_id):

            keyboard.append([InlineKeyboardButton("🔀 Mover usuario grupo", callback_data="admin_move_user")])


        keyboard.append([InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_USERS_HELP)])

        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")])

        await send_clean_message(
            context,
            query.message.chat_id,

            "👥 GESTIÓN USUARIOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ADMIN — PERMITIR USUARIO
    # =========================

    if data.startswith("allow_user_"):

        parts = data.split("_")

        if (
            len(parts) < 4
            or not parts[2].isdigit()
            or not parts[3].isdigit()
        ):

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return

        user_id = int(parts[2])
        group_id = int(parts[3])

        if not user_has_group_permission_any(
            query.from_user.id,
            group_id,
            ["can_kick_users", "can_manage_users"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO users

                    (user_id, group_id, expiration)

                    VALUES (%s, %s, NULL)

                    ON CONFLICT
                    (user_id, group_id)

                    DO UPDATE SET expiration=NULL

                """, (

                    user_id,
                    group_id

                ))

                conn.commit()


            await query.message.reply_text(

                "✅ Usuario permitido permanentemente."

            )


        except Exception as e:

            print(
                "Error permitiendo usuario:",
                e
            )

        return


    # =========================
    # ADMIN — EXPULSAR USUARIO
    # =========================

    if data.startswith("deny_user_"):

        parts = data.split("_")

        if (
            len(parts) < 4
            or not parts[2].isdigit()
            or not parts[3].isdigit()
        ):

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return

        user_id = int(parts[2])
        group_id = int(parts[3])


        if not user_has_group_permission_any(
            query.from_user.id,
            group_id,
            ["can_kick_users", "can_manage_users"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT telegram_group_id

                    FROM groups

                    WHERE id=%s

                """, (group_id,))

                row = cur.fetchone()


            if row:

                telegram_group_id = row[0]


                kick_chat_member(
                    TOKEN,
                    telegram_group_id,
                    user_id
                )


            await query.message.reply_text(

                "❌ Usuario expulsado."

            )


        except Exception as e:

            print(
                "Error expulsando usuario:",
                e
            )

        return


    # =========================
    # MENÚ ACCESOS
    # =========================

    if data == "menu_codes":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📤 Crear código", callback_data="admin_create_code")],

            [InlineKeyboardButton("📋 Ver códigos", callback_data="admin_codes")],

            [InlineKeyboardButton("❌ Eliminar código", callback_data="admin_delete_code")],

        ]


        if is_super_admin(user_id):

            keyboard.append([InlineKeyboardButton("🔄 Revocar links", callback_data="admin_revoke_links")])

            keyboard.append([InlineKeyboardButton("📩 Reenviar links", callback_data="admin_resend_links")])


        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")])

        await send_clean_message(
            context,
            query.message.chat_id,

            "🎟️ GESTIÓN ACCESOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ GRUPOS
    # =========================

    if data == "menu_groups":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = []


        if is_super_admin(user_id):

            keyboard.append([
                InlineKeyboardButton("➕ Añadir grupo", callback_data="admin_add_group")
            ])


        keyboard.extend([

            [InlineKeyboardButton("✏️ Editar grupo", callback_data="admin_edit_group")],

            [InlineKeyboardButton("📋 Ver grupos", callback_data="admin_view_groups")],

            [InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_GROUPS_HELP)],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ])

        await send_clean_message(
            context,
            query.message.chat_id,

            "📦 GESTIÓN GRUPOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # CANCELAR CREACIÓN GRUPO
    # =========================

    if data == "cancel_create_group":

        context.user_data["creating_group"] = False
        context.user_data.pop("new_group_data", None)
        context.user_data.pop("group_step", None)

        keyboard = []


        if is_super_admin(user_id):

            keyboard.append([
                InlineKeyboardButton("➕ Añadir grupo", callback_data="admin_add_group")
            ])


        keyboard.extend([

            [InlineKeyboardButton("✏️ Editar grupo", callback_data="admin_edit_group")],

            [InlineKeyboardButton("📋 Ver grupos", callback_data="admin_view_groups")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ])

        await query.message.reply_text(

            "📦 GESTIÓN GRUPOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # VER GRUPOS
    # =========================

    # Tramo movido a admin_view_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_view_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_VIEW_NOT_HANDLED:

        return




    # =========================
    # MENÚ PAGOS
    # =========================

    if data == "menu_payments":

        try:
            await query.message.delete()
        except:
            pass

        permissions = get_admin_permissions(user_id)

        keyboard = []


        if has_any_permission(permissions, ["can_view_payments", "can_manage_payments"]):

            keyboard.append([InlineKeyboardButton("📋 Ver pagos", callback_data="admin_view_payments")])

            keyboard.append([InlineKeyboardButton("🔍 Buscar pago", callback_data="admin_search_payment")])


        if has_any_permission(permissions, ["can_manage_payments"]):

            keyboard.append([InlineKeyboardButton("📩 Reenviar acceso", callback_data="admin_resend_access")])

            keyboard.append([InlineKeyboardButton("❌ Cancelar suscripción", callback_data="admin_cancel_subscription")])


        keyboard.append([InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_PAYMENTS_HELP)])

        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")])

        await send_clean_message(
            context,
            query.message.chat_id,

            "💳 GESTIÓN PAGOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ NEGOCIO
    # =========================

    if data == "menu_business":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats")],

            [InlineKeyboardButton("👥 Usuarios activos", callback_data="admin_active_users")],

            [InlineKeyboardButton("💰 Ingresos", callback_data="admin_income")]

        ]


        if is_super_admin(user_id):

            # Cada avería avisa a su propietario, y eso depende de que ese
            # propietario lea y actúe. Esta pantalla es la foto agregada de
            # lo que está roto ahora mismo en toda la plataforma.
            keyboard.append([
                InlineKeyboardButton("🩺 Salud de comunidades",
                                     callback_data="admin_health")
            ])

            keyboard.append([
                InlineKeyboardButton("🔄 Revocar todos links", callback_data="admin_revoke_links")
            ])


        keyboard.append([
            InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")
        ])

        await send_clean_message(
            context,
            query.message.chat_id,

            "📊 GESTIÓN NEGOCIO",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ LOGS
    # =========================

    if data == "menu_logs":

        try:
            await query.message.delete()
        except:
            pass

        logs_label = (
            "📜 Logs del sistema"
            if is_super_admin(user_id)
            else "📜 Logs de mi grupo"
        )


        keyboard = [

            [InlineKeyboardButton(logs_label, callback_data="admin_logs")],

            [InlineKeyboardButton("👥 Logs usuarios", callback_data="admin_logs_users")],

            [InlineKeyboardButton("💳 Logs pagos", callback_data="admin_logs_payments")],

            [InlineKeyboardButton("🔐 Logs seguridad", callback_data="admin_logs_security")],

            [InlineKeyboardButton("💬 Ayuda sobre este menú", callback_data=CALLBACK_ADMIN_LOGS_HELP)],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await send_clean_message(
            context,
            query.message.chat_id,

            logs_label,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # VOLVER AL MENÚ PRINCIPAL
    # =========================

    if data == "admin_back_main":

        await expire_expired_commercial_trials(context)

        try:
            await query.message.delete()
        except:
            pass

        keyboard = build_admin_panel_keyboard(user_id)


        if not keyboard:

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ No tienes permisos de gestión."
            )

            return

        await send_clean_message(

            context,

            query.message.chat_id,

            build_admin_home_text(user_id),

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # AÑADIR GRUPO — INICIO WIZARD
    # =========================

    if data == "admin_add_group":

        try:
            await query.message.delete()
        except:
            pass

        context.user_data["creating_group"] = True
        context.user_data["group_step"] = 1
        context.user_data["new_group_data"] = {}

        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Cancelar creación",
                callback_data="cancel_create_group"
            )]

        ]

        await query.message.reply_text(

            "📦 CREAR NUEVO GRUPO\n\n"

            "Paso 1️⃣\n"
            "Introduce el nombre del grupo.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # CÓDIGOS POR GRUPO — SUPER ADMIN
    # =========================

    if data == "admin_group_user_codes":

        rows = fetch_admin_groups_for_permissions(
            user_id,
            ["can_manage_codes"]
        )


        if not rows:

            await query.message.reply_text(
                "⚠️ No hay grupos disponibles.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        keyboard = []

        for group_id, group_name, _telegram_group_id in rows:

            keyboard.append([InlineKeyboardButton(
                group_name or f"Grupo {group_id}",
                callback_data=f"group_user_code_select_group_{group_id}"
            )])


        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")])

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos por grupo\n\n"
            "Elige el grupo para gestionar códigos de acceso de usuarios finales.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    # Tramo movido a group_user_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_group_user_callbacks(
        update, context, query, user_id, data
    ) is not GROUP_USER_NOT_HANDLED:

        return




    # =========================
    # EDITAR GRUPO — LISTA
    # =========================

    if data == "admin_edit_group":

        try:
            await query.message.delete()
        except:
            pass


        try:

            with conn.cursor() as cur:

                rows = fetch_admin_groups_for_permissions(
                    user_id,
                    [
                        "can_manage_groups",
                        "can_manage_plans",
                        "can_manage_codes",
                        "can_manage_admins",
                        "can_edit_group_texts",
                        "can_edit_marketplace_preview"
                    ]
                )

                groups = [
                    (group_id, name)
                    for group_id, name, _telegram_group_id in rows
                ]

        except Exception as e:

            print("Error cargando grupos:", e)

            await query.message.reply_text(
                "❌ Error cargando grupos."
            )

            return


        if not groups:

            await query.message.reply_text(
                "⚠️ No hay grupos disponibles."
            )

            return


        keyboard = []


        for group_id, group_name in groups:

            keyboard.append([

                InlineKeyboardButton(

                    group_name,

                    callback_data=f"edit_group_{group_id}"

                )

            ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="admin_back_main"

            )

        ])


        panel_intro = (
            "🏪 Mis comunidades\n\n"
            "Selecciona una comunidad para abrir su panel de gestión:"
            if is_super_admin(user_id) or user_has_group_owner_role(user_id)
            else
            "👮 Panel admin de grupo\n\n"
            "Selecciona la comunidad donde tienes permisos. Solo verás accesos compatibles con tu rol:"
        )


        await query.message.reply_text(

            panel_intro,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if data == "owner_setup_assistant":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            [
                "can_manage_groups",
                "can_manage_plans",
                "can_manage_codes",
                "can_manage_admins",
                "can_edit_group_texts",
                "can_edit_marketplace_preview",
                "can_view_logs"
            ]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para abrir el asistente de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_setup_assistant_text(group_id),
            reply_markup=build_owner_setup_assistant_keyboard(user_id, group_id)
        )

        return


    if data == "owner_ai_panel":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs", "can_manage_plans", "can_respond_group_support"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para abrir el asistente IA de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id
        context.user_data["selected_group_admin"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            "🤖 Asistente de comunidad\n\n"
            "Puedo ayudarte a configurar la comunidad, entender pagos, revisar encuestas, usuarios, soporte y marketplace.\n\n"
            "No modifico nada automáticamente. Te doy diagnóstico, pasos y rutas seguras.",
            reply_markup=build_owner_ai_panel_keyboard()
        )

        return


    if data == "owner_ai_ask":

        await activate_ai_help_context(
            update,
            context,
            help_context="owner"
        )

        return


    owner_ai_questions = {
        "owner_ai_setup": (AI_CONTEXT_OWNER_DASHBOARD, "Ayúdame a configurar mi comunidad y dime qué revisar primero."),
        "owner_ai_payments": (AI_CONTEXT_OWNER_PAYMENTS, "Ayúdame a configurar métodos de pago y explica Stripe, PayPal, Revolut, ChangeNOW y Guardarian según el estado real."),
        "owner_ai_surveys": (AI_CONTEXT_OWNER_SURVEYS, "Analiza mis encuestas y dime qué acciones prácticas puedo tomar."),
        "owner_ai_users": (AI_CONTEXT_OWNER_USERS, "Analiza usuarios y accesos de esta comunidad y dime qué revisar."),
        "owner_ai_support": (AI_CONTEXT_SUPPORT_TICKET, "Ayúdame a revisar soporte de esta comunidad y preparar mejores respuestas."),
        "owner_ai_marketplace": (AI_CONTEXT_OWNER_DASHBOARD, "Sugiere mejoras para el texto de marketplace de mi comunidad sin inventar datos."),
        "owner_ai_diagnostics": (AI_CONTEXT_OWNER_DASHBOARD, "Haz un diagnóstico seguro de esta comunidad: pagos, accesos, soporte, encuestas y configuración.")
    }

    if data in owner_ai_questions:

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs", "can_manage_plans", "can_respond_group_support"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para usar IA en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context_key, question = owner_ai_questions[data]
        result = build_contextual_ai_answer(
            user_id=user_id,
            question=question,
            role=AI_ROLE_OWNER,
            context_key=context_key,
            group_id=group_id
        )

        await send_ai_result_message(
            context,
            query.message.chat_id,
            result,
            back_callback="owner_ai_panel"
        )

        return


    # Tramo movido a owner_panel_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_owner_panel_callbacks(
        update, context, query, user_id, data
    ) is not OWNER_PANEL_NOT_HANDLED:

        return




    # Tramo movido a owner_satisfaction_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_owner_satisfaction_callbacks(
        update, context, query, user_id, data
    ) is not OWNER_SATISFACTION_NOT_HANDLED:

        return






    # Tramo movido a owner_addon_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_owner_addon_callbacks(
        update, context, query, user_id, data
    ) is not OWNER_ADDON_NOT_HANDLED:

        return




    # Tramo movido a admin_guardian_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_guardian_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_GUARDIAN_NOT_HANDLED:

        return














    if (
        data in ("owner_addons_menu", "owner_addons_active")
        or data.startswith("owner_addon_product_")
        or data.startswith("owner_addon_checkout_")
    ):

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar servicios extra de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id


        if data == "owner_addons_menu":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_addons_menu_text(user_id, group_id),
                reply_markup=build_owner_addons_menu_keyboard(user_id)
            )

            return


        if data == "owner_addons_active":

            addon_owner_user_id = get_group_owner_user_id(group_id) or user_id

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_addons_active_text(addon_owner_user_id, group_id),
                reply_markup=build_owner_addons_active_keyboard(
                    addon_owner_user_id,
                    group_id=group_id
                )
            )

            return


        if data.startswith("owner_addon_checkout_"):

            addon_code = data.replace("owner_addon_checkout_", "", 1)
            product = fetch_owner_addon_product(addon_code)
            owner_user_id = get_group_owner_user_id(group_id) or user_id


            if not is_super_admin(user_id) and int(owner_user_id) != int(user_id):

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⛔ Solo el dueño real de la comunidad puede contratar servicios extra.",
                    reply_markup=build_owner_addons_menu_keyboard()
                )

                return


            if not product or not product.get("is_active"):

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ Servicio extra no encontrado o no disponible.",
                    reply_markup=build_owner_addons_menu_keyboard()
                )

                return


            if not product.get("stripe_price_id"):

                log_event(
                    "owner_addon_checkout_blocked_no_stripe_price",
                    category="billing",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Checkout de servicio extra bloqueado por falta de stripe_price_id.",
                    metadata={
                        "owner_user_id": owner_user_id,
                        "buyer_user_id": user_id,
                        "group_id": group_id,
                        "addon_code": addon_code
                    }
                )

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ Este servicio todavía no tiene precio de Stripe configurado.",
                    reply_markup=build_owner_addon_product_keyboard(product)
                )

                return


            if not is_stripe_payments_enabled():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ Stripe no está habilitado ahora mismo. No puedo crear el checkout mensual.",
                    reply_markup=build_owner_addon_product_keyboard(product)
                )

                return


            if not owner_addon_is_purchase_allowed(owner_user_id, addon_code, group_id=group_id):

                log_event(
                    "owner_addon_checkout_blocked_already_active",
                    category="billing",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Checkout de servicio extra bloqueado porque ya está activo.",
                    metadata={
                        "owner_user_id": owner_user_id,
                        "buyer_user_id": user_id,
                        "group_id": group_id,
                        "addon_code": addon_code
                    }
                )

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "✅ Este servicio ya está activo para esta comunidad.",
                    reply_markup=build_owner_addons_active_keyboard(
                        owner_user_id,
                        group_id=group_id
                    )
                )

                return


            try:

                session = create_owner_addon_stripe_checkout_session(
                    product,
                    owner_user_id,
                    user_id,
                    group_id
                )

                upsert_owner_addon_checkout_pending(
                    owner_user_id=owner_user_id,
                    group_id=group_id,
                    addon_code=addon_code,
                    stripe_price_id=product.get("stripe_price_id"),
                    stripe_customer_id=session.get("customer")
                )

                log_event(
                    "owner_addon_checkout_created",
                    category="billing",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Checkout Stripe de servicio extra creado.",
                    metadata={
                        "owner_user_id": owner_user_id,
                        "buyer_user_id": user_id,
                        "group_id": group_id,
                        "addon_code": addon_code,
                        "stripe_session_id": session.get("id")
                    }
                )

            except Exception as e:

                log_event(
                    "owner_addon_checkout_failed",
                    category="billing",
                    severity="error",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Error creando checkout Stripe de servicio extra.",
                    metadata={
                        "owner_user_id": owner_user_id,
                        "buyer_user_id": user_id,
                        "group_id": group_id,
                        "addon_code": addon_code,
                        "error": str(e)[:300]
                    }
                )

                await query.message.reply_text(
                    f"❌ No he podido crear el checkout de Stripe: {str(e)[:300]}",
                    reply_markup=build_owner_addons_menu_keyboard()
                )

                return


            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Checkout creado. Completa el pago mensual en Stripe para activar el servicio.",
                reply_markup=build_owner_addon_checkout_keyboard(product, session.url)
            )

            return


        addon_code = data.replace("owner_addon_product_", "", 1)
        product = fetch_owner_addon_product(addon_code)


        if not product or not product.get("is_active"):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚠️ Servicio extra no encontrado o no disponible.",
                reply_markup=build_owner_addons_menu_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_addon_product_text(product, group_id),
            reply_markup=build_owner_addon_product_keyboard(product)
        )

        return






    if data.startswith("owner_guardian_"):

        # Guardian vive en guardian_callbacks.py. Se retorna justo después
        # porque en el original todos los caminos de este bloque retornaban.
        await handle_guardian_callbacks(update, context, query, user_id, data)

        return







    # Tramo movido a owner_publicity_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_owner_publicity_callbacks(
        update, context, query, user_id, data
    ) is not OWNER_PUBLICITY_NOT_HANDLED:

        return




    # Tramo movido a owner_group_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_owner_group_callbacks(
        update, context, query, user_id, data
    ) is not OWNER_GROUP_NOT_HANDLED:

        return




    # Tramo movido a community_links_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_community_links_callbacks(
        update, context, query, user_id, data
    ) is not COMMUNITY_LINKS_NOT_HANDLED:

        return






    if data.startswith("community_link_recover_user_"):

        parsed = parse_community_user_callback(data, "community_link_recover_user_")


        if not parsed:

            await query.message.reply_text(
                "⚠️ No he podido identificar al usuario.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id, target_user_id = parsed


        if not user_can_recover_community_access_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para reenviar o recuperar links de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        result = await send_recovered_community_access_link(
            context,
            group_id,
            target_user_id,
            user_id
        )

        profile = fetch_community_user_profile(group_id, target_user_id)
        display_name = format_community_user_display_name(profile)


        if result.get("ok"):

            await send_clean_message(
                context,
                query.message.chat_id,
                f"✅ Link reenviado correctamente a {display_name}.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👤 Volver a usuarios activos", callback_data=f"community_links_recover_one_{group_id}_0")],
                    [InlineKeyboardButton("⬅️ Menú de links", callback_data=f"community_links_recover_menu_{group_id}")]
                ])
            )

            return


        if result.get("reason") == "dm_failed":

            await send_clean_message(
                context,
                query.message.chat_id,
                (
                    f"⚠️ Link generado para {display_name}, pero no se pudo enviar por privado.\n\n"
                    "El usuario debe abrir chat con el bot para recibir mensajes directos."
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👤 Volver a usuarios activos", callback_data=f"community_links_recover_one_{group_id}_0")],
                    [InlineKeyboardButton("⬅️ Menú de links", callback_data=f"community_links_recover_menu_{group_id}")]
                ])
            )

            return


        if result.get("reason") == "no_active_access":

            await query.message.reply_text(
                "⛔ Este usuario no tiene acceso activo a esta comunidad. No se ha generado ningún link.",
                reply_markup=build_community_user_manage_keyboard(group_id, target_user_id, user_id)
            )

            return


        await query.message.reply_text(
            "❌ No he podido generar o recuperar el link para este usuario.",
            reply_markup=build_community_user_manage_keyboard(group_id, target_user_id, user_id)
        )

        return






    if data.startswith("community_users_sync_known_yes_"):

        group_id = extract_commercial_request_id(
            data,
            "community_users_sync_known_yes_"
        )


        if not user_can_view_community_users(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para sincronizar usuarios de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_free_community_for_known_user_sync(group_id)


        if not group:

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para comunidades gratuitas.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        result = sync_known_free_community_users(
            group_id,
            group.get("telegram_group_id"),
            user_id,
            getattr(context.bot, "id", None)
        )


        if not result.get("ok"):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para comunidades gratuitas.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        text = (
            "✅ Sincronización terminada\n\n"
            f"Usuarios encontrados: {result.get('found_count')}\n"
            f"Insertados nuevos: {result.get('inserted_count')}\n"
            f"Actualizados: {result.get('updated_count')}\n"
            f"Omitidos: {result.get('skipped_count')}\n"
            f"Errores: {result.get('error_count')}\n"
            f"Usuarios en DB de esta comunidad: {result.get('users_total_after_sync') if result.get('users_total_after_sync') is not None else '-'}\n"
            f"Usuarios free activos en DB: {result.get('users_free_active_after_sync') if result.get('users_free_active_after_sync') is not None else '-'}\n\n"
            "Ahora puedes volver a “Ver usuarios de esta comunidad”."
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Ver usuarios de esta comunidad", callback_data=f"owner_group_users_{group_id}")],
            [InlineKeyboardButton("⬅️ Volver", callback_data="owner_panel_users")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=keyboard
        )

        return


    if data.startswith("community_users_sync_known_"):

        group_id = extract_commercial_request_id(
            data,
            "community_users_sync_known_"
        )


        if not user_can_view_community_users(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para sincronizar usuarios de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_free_community_for_known_user_sync(group_id)


        if not group:

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para comunidades gratuitas.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        text = (
            "⚠️ Esta acción buscará usuarios conocidos por el bot en logs/eventos de esta comunidad gratis "
            "y los registrará como acceso gratuito/permanente.\n\n"
            "No usa pagos, no crea suscripciones premium y no modifica comunidades de pago.\n\n"
            "¿Continuar?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sí, sincronizar", callback_data=f"community_users_sync_known_yes_{group_id}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="owner_panel_users")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=keyboard
        )

        return


    if data.startswith("community_users_"):

        payload = data.replace("community_users_", "", 1)
        parts = payload.split("_")


        if len(parts) != 3 or not parts[0].isdigit() or parts[1] not in ("active", "inactive") or not parts[2].isdigit():

            await query.message.reply_text("⚠️ No he podido identificar la lista de usuarios.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id = int(parts[0])
        segment = parts[1]
        page = int(parts[2])


        if not user_can_view_community_users(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para ver usuarios de esta comunidad.", reply_markup=build_owner_panel_nav_keyboard())
            return


        try:

            text, keyboard = build_community_users_page(group_id, segment, page)

        except Exception as e:

            print("community_users_panel_load_error:", str(e)[:500])
            await query.message.reply_text("❌ No he podido cargar usuarios de esta comunidad ahora mismo.", reply_markup=build_owner_panel_nav_keyboard())
            return

        await send_clean_message(context, query.message.chat_id, text, reply_markup=keyboard)
        return


    # Tramo movido a guardian_user_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_guardian_user_callbacks(
        update, context, query, user_id, data
    ) is not GUARDIAN_USER_NOT_HANDLED:

        return










    # Tramo movido a community_user_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_community_user_callbacks(
        update, context, query, user_id, data
    ) is not COMMUNITY_USER_NOT_HANDLED:

        return


















    if data in OWNER_PANEL_SECTIONS:

        title, description, required_permissions, section = OWNER_PANEL_SECTIONS[data]

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            required_permissions
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if section == "codes":

            set_group_user_promo_context(
                context,
                group_id,
                step="panel"
            )


        if section == "admins":

            context.user_data["selected_owner_group"] = group_id


        panel_text = f"{title}\n\nEsto sirve para: {description}"


        if section == "payments":

            panel_text = (
                "💳 Configuración de pagos del grupo\n\n"
                "Este grupo puede vender acceso con varios métodos. De pago no significa solo Stripe.\n\n"
                "💳 Pagos tradicionales\n"
                "- Stripe\n"
                "- PayPal\n"
                "- Revolut\n\n"
                "🪙 Cripto / USDT\n"
                "- ChangeNOW.io / Cripto\n"
                "- Tarjeta EUR → USDT / Guardarian\n\n"
                "🎟 Promociones\n"
                "- Códigos y promociones\n\n"
                "Marcar el grupo como de pago no obliga a usar Stripe. Puedes activar uno o varios métodos de pago.\n\n"
                "Guardarian permite que el comprador pague con tarjeta en euros y que tú recibas USDT en tu wallet.\n"
                "ChangeNOW sirve para pagos cripto y puede requerir revisión manual según configuración."
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            panel_text,
            reply_markup=build_owner_section_keyboard(
                user_id,
                group_id,
                section
            )
        )

        return








    if data.startswith(OWNER_PAYMENT_CALLBACK_PREFIXES):

        # El asistente de métodos de pago vive en owner_payment_callbacks.py.
        # Se retorna justo después porque en el original las 16 ramas de este
        # tramo terminaban todas en return.
        await handle_owner_payment_callbacks(update, context, query, user_id, data)

        return









    # Tramo movido a owner_support_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_owner_support_callbacks(
        update, context, query, user_id, data
    ) is not OWNER_SUPPORT_NOT_HANDLED:

        return




    # Tramo movido a owner_location_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_owner_location_callbacks(
        update, context, query, user_id, data
    ) is not OWNER_LOCATION_NOT_HANDLED:

        return






































    # =========================
    # MENÚ INTERNO DEL GRUPO
    # =========================

    # Tramo movido a edit_group_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_edit_group_callbacks(
        update, context, query, user_id, data
    ) is not EDIT_GROUP_NOT_HANDLED:

        return






























    # =========================
    # EDITAR PREVIEW
    # =========================




    # =========================
    # OMITIR PREVIEW
    # =========================

    if data == "skip_preview":

        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)
        context.user_data.pop("new_preview_file_type", None)
        context.user_data.pop("editing_preview_mode", None)

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            "⏭ Preview omitido.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # GUARDAR PREVIEW
    # =========================

    if data == "save_preview":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)"
            )

            return

        file_id = context.user_data.get("new_preview_file")
        file_type = context.user_data.get("new_preview_file_type")
        preview_mode = context.user_data.get("editing_preview_mode") or "manual"


        if not file_id:

            await query.message.reply_text(
                "❌ Debes enviar una imagen o vídeo antes de guardar."
            )

            return


        column_name = (
            "preview_video_file_id"
            if file_type == "video"
            else "preview_image_file_id"
        )


        try:

            with conn.cursor() as cur:

                cur.execute(f"""

                    UPDATE groups

                    SET {column_name}=%s,
                        preview_file_id=%s,
                        preview_mode=%s

                    WHERE id=%s

                """, (

                    file_id,
                    file_id,
                    preview_mode,
                    group_id

                ))

                conn.commit()

        except Exception as e:

            print("Error guardando preview:", e)


        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)
        context.user_data.pop("new_preview_file_type", None)
        context.user_data.pop("editing_preview_mode", None)


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            "✅ Preview manual guardado.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # CANCELAR PREVIEW
    # =========================

    if data == "cancel_preview":

        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)
        context.user_data.pop("new_preview_file_type", None)
        context.user_data.pop("editing_preview_mode", None)

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            "❌ Cambios descartados.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return



    # =========================
    # EDITAR PLANES — MENÚ
    # =========================



    # =========================
    # AÑADIR PLAN — INICIO
    # =========================





    # =========================
    # VER PLANES DEL GRUPO
    # =========================

    if data == "view_group_plans":

        try:
            await query.message.delete()
        except:
            pass


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id,
                           name,
                           amount,
                           currency,
                           duration_days,
                           COALESCE(NULLIF(payment_provider, ''), 'stripe')

                    FROM plans

                    WHERE group_id=%s
                    AND is_active=TRUE

                    ORDER BY id ASC

                """, (group_id,))

                plans = cur.fetchall()

        except Exception as e:

            print("Error cargando planes:", e)

            await query.message.reply_text(
                "❌ Error cargando planes."
            )

            return


        if not plans:

            keyboard = [

                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="edit_group_plans"
                )]

            ]

            await query.message.reply_text(

                "⚠️ Este grupo no tiene planes creados.",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

            return


        texto = "📋 PLANES DEL GRUPO\n\n"
        provider_statuses = list_group_payment_provider_statuses(group_id)


        for plan_id, name, amount, currency, duration, payment_provider in plans:

            payment_provider = normalize_plan_payment_provider(payment_provider)
            provider_status = get_group_payment_provider_status(
                provider_statuses,
                payment_provider
            )
            provider_state_line = ""

            if payment_provider == OWNER_PAYMENT_PROVIDER_PAYPAL and is_group_provider_globally_disabled(provider_status):

                provider_state_line = "Estado: deshabilitado globalmente\n"

            if duration == 0:

                duracion_texto = "♾️ Permanente"

            else:

                duracion_texto = f"{duration} días"


            if amount and currency:

                precio_texto = f"{amount} {currency}"

            else:

                precio_texto = "No definido"


            texto += (

                f"🆔 {plan_id}\n"

                f"📦 {name}\n"

                f"💰 {precio_texto}\n"

                f"💳 Método: {format_plan_payment_provider(payment_provider)}\n"

                f"{provider_state_line}"

                f"⏳ {duracion_texto}\n\n"

            )


        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )]

        ]


        await query.message.reply_text(

            texto,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # EDITAR PLAN — SELECCIÓN
    # =========================



    # =========================
    # ELIMINAR GRUPO — CONFIRMAR
    # =========================

    # Tramo movido a delete_group_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_delete_group_callbacks(
        update, context, query, user_id, data
    ) is not DELETE_GROUP_NOT_HANDLED:

        return




    # =========================
    # ELIMINAR PLAN — REAL
    # =========================

    if data.startswith("delete_plan_"):

        parts = data.split("_")


        if len(parts) < 3 or not parts[2].isdigit():

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        plan_id = int(parts[2])

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE plans

                    SET is_active=FALSE

                    WHERE id=%s
                    AND group_id=%s

                """, (
                    plan_id,
                    group_id
                ))


                # =========================
                # NUEVO — VERIFICAR SI QUEDAN PLANES
                # =========================

                cur.execute("""

                    SELECT COUNT(*)
                    FROM plans
                    WHERE group_id=%s
                    AND is_active=TRUE

                """, (group_id,))

                remaining_plans = cur.fetchone()[0]


                # =========================
                # NUEVO — SI NO QUEDAN PLANES
                # NO BORRAR GRUPO — SOLO INFORMAR
                # =========================

                conn.commit()

        except Exception as e:

            print("Error eliminando plan:", e)

            await query.message.reply_text(
                "❌ Error eliminando plan."
            )

            return


        # Quitar el ÚLTIMO plan deja la comunidad en el mercado sin nada que
        # vender: quien entre pulsará «Comprar» y no habrá nada. Antes esto
        # solo se imprimía en el registro del servidor, así que el único que
        # se enteraba era quien leyera los logs — nunca el propietario.
        if remaining_plans == 0:

            from platform_health_service import fetch_unsellable_but_visible

            visible = any(
                fila[0] == group_id
                for fila in fetch_unsellable_but_visible()
            )

            log_event(
                "group_left_without_plans",
                category="group",
                severity="warning" if visible else "info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="La comunidad se ha quedado sin planes activos.",
                metadata={"visible_en_venta": visible}
            )

            aviso = (
                "🗑 Plan eliminado.\n\n"
                "⚠️ Era el último plan activo de esta comunidad."
            )

            if visible:

                aviso += (
                    "\n\nLa comunidad sigue visible, así que quien entre "
                    "pulsará «Comprar acceso» y no encontrará nada. Crea otro "
                    "plan o quítala de la vista mientras lo preparas."
                )

            else:

                aviso += (
                    "\n\nNo está visible en el mercado ni en el menú, así que "
                    "nadie se va a topar con la tienda vacía. Cuando quieras "
                    "volver a vender, crea un plan primero."
                )

            await query.message.reply_text(
                aviso,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🚦 ¿Puedo vender?",
                        callback_data="owner_panel_ready"
                    )
                ]])
            )

            return


        await query.message.reply_text(
            "🗑 Plan eliminado correctamente."
        )

        return


    # =========================
    # ADMIN USERS
    # =========================

    if data == "admin_users":

        try:

            with conn.cursor() as cur:

                group_ids = get_admin_group_ids(
                    user_id,
                    ["can_view_users", "can_manage_users"]
                )


                if group_ids is None:

                    cur.execute("""

                        SELECT u.user_id,
                               u.username,
                               u.first_name,
                               u.expiration,
                               g.name
                        FROM users u
                        LEFT JOIN groups g
                        ON u.group_id = g.id
                        ORDER BY u.expiration DESC NULLS LAST

                    """)

                elif not group_ids:

                    users = []

                else:

                    cur.execute("""

                        SELECT u.user_id,
                               u.username,
                               u.first_name,
                               u.expiration,
                               g.name
                        FROM users u
                        LEFT JOIN groups g
                        ON u.group_id = g.id
                        WHERE u.group_id = ANY(%s)
                        ORDER BY u.expiration DESC NULLS LAST

                    """, (group_ids,))

                if group_ids is None or group_ids:

                    users = cur.fetchall()


            if not users:

                await query.message.reply_text(
                    "No hay usuarios activos."
                )

                return


            texto = f"👥 Usuarios activos: {len(users)}\n\n"


            for user_id, username, first_name, expiration, group_name in users:

                nombre = first_name if first_name else "Sin nombre"

                if username:
                    nombre += f" (@{username})"

                if expiration:

                    exp = expiration.strftime("%Y-%m-%d")

                else:

                    exp = "♾️ Permanente"


                texto += (

                    f"ID: {user_id}\n"
                    f"Grupo: {group_name or '-'}\n"
                    f"Nombre: {nombre}\n"
                    f"Expira: {exp}\n\n"

                )


            await query.message.reply_text(texto)

        except Exception as e:

            print("ERROR admin_users:", e)

            await query.message.reply_text(
                "❌ Error mostrando usuarios"
            )

        return


    # =========================
    # VER CÓDIGOS
    # =========================

    if data == "admin_codes":

        with conn.cursor() as cur:

            cur.execute("""

                SELECT code, duration, used
                FROM invite_codes
                ORDER BY code DESC
                LIMIT 20

            """)

            rows = cur.fetchall()


        if not rows:

            await query.message.reply_text(
                "No hay códigos creados."
            )

            return


        texto = "🎟️ Últimos códigos:\n\n"


        for code, duration, used in rows:

            if duration == 0:

                duracion_texto = "♾️ Permanente"

            elif duration < 1440:

                duracion_texto = f"{duration} min"

            else:

                duracion_texto = f"{duration//1440} días"


            estado = "❌ USADO" if used else "✅ ACTIVO"


            texto += (

                f"{code}\n"
                f"{duracion_texto} — {estado}\n\n"

            )


        await query.message.reply_text(texto)

        return


    # =========================
    # CREAR CÓDIGO
    # =========================

    if data == "admin_create_code":

        keyboard = [

            [InlineKeyboardButton("⏱️ 15 min", callback_data="gen_15")],
            [InlineKeyboardButton("📅 1 día", callback_data="gen_1440")],
            [InlineKeyboardButton("📅 7 días", callback_data="gen_10080")],
            [InlineKeyboardButton("📅 30 días", callback_data="gen_43200")],
            [InlineKeyboardButton("♾️ Permanente", callback_data="gen_perm")]

        ]


        await query.message.reply_text(

            "Selecciona duración:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ELIMINAR CÓDIGO
    # =========================

    if data == "admin_delete_code":

        context.user_data["delete_code"] = True

        await query.message.reply_text(
            "❌ Envia el código a eliminar"
        )

        return


    # =========================
    # BUSCAR USUARIO
    # =========================

    if data == "admin_search_user":

        context.user_data["search_user"] = True

        await query.message.reply_text(
            "🔍 Envia el ID del usuario"
        )

        return


    # =========================
    # EXPULSAR USUARIO
    # =========================

    if data == "admin_kick_user":

        context.user_data["kick_user"] = True

        await query.message.reply_text(
            "🚫 Envia el ID del usuario"
        )

        return


    # =========================
    # BAN PERMANENTE
    # =========================

    if data == "admin_ban_user":

        context.user_data["ban_user"] = True

        await query.message.reply_text(
            "⛔ Envia el ID del usuario a BANEAR"
        )

        return


    # =========================
    # DESBANEAR USUARIO
    # =========================

    if data == "admin_unban_user":

        context.user_data["unban_user"] = True

        await query.message.reply_text(
            "♻️ Envia el ID del usuario a DESBANEAR"
        )

        return


    # Tramo movido a admin_resend_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_resend_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_RESEND_NOT_HANDLED:

        return




    if data in (
        "admin_reset_warnings",
        "admin_cancel_subscription",
        "admin_move_user"
    ):

        log_event(
            "admin_placeholder_callback",
            category="ui",
            severity="info",
            scope="global",
            actor_user_id=user_id,
            message="Callback placeholder admin pulsado.",
            metadata={"callback_data": data}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "⚠️ Esta acción todavía no tiene un flujo seguro disponible.\n\n"
                "No se ha modificado ningún dato. Vuelve al panel y usa una acción disponible."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return




    if data == "admin_search_payment":

        await query.message.reply_text(
            "🔍 La búsqueda directa de pagos todavía no está disponible. Usa el listado filtrado de pagos."
        )

        return


    # =========================
    # ESTADÍSTICAS
    # =========================

    if data == "admin_stats":

        try:

            with conn.cursor() as cur:

                group_ids = get_admin_group_ids(
                    user_id,
                    ["can_view_stats"]
                )


                if group_ids is None:

                    group_filter = ""
                    params = ()

                elif not group_ids:

                    usuarios_activos = 0
                    usuarios_expirados = 0
                    usuarios_permanentes = 0
                    total_pagos = 0

                    raise StopIteration

                else:

                    group_filter = "AND group_id = ANY(%s)"
                    params = (group_ids,)


                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE (
                        expiration IS NULL
                        OR expiration > NOW()
                    )
                    {group_filter}

                """.format(group_filter=group_filter), params)

                usuarios_activos = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE expiration IS NOT NULL
                    AND expiration < NOW()
                    {group_filter}

                """.format(group_filter=group_filter), params)

                usuarios_expirados = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE expiration IS NULL
                    {group_filter}

                """.format(group_filter=group_filter), params)

                usuarios_permanentes = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM payments
                    WHERE 1=1
                    {group_filter}

                """.format(group_filter=group_filter), params)

                total_pagos = cur.fetchone()[0]


        except StopIteration:

            texto = (

                "📊 ESTADÍSTICAS\n\n"

                "👥 Activos: 0\n"
                "⛔ Expirados: 0\n"
                "♾️ Permanentes: 0\n\n"

                "💳 Pagos totales: 0"
            )


            await query.message.reply_text(texto)

            return

        try:

            texto = (

                "📊 ESTADÍSTICAS\n\n"

                f"👥 Activos: {usuarios_activos}\n"
                f"⛔ Expirados: {usuarios_expirados}\n"
                f"♾️ Permanentes: {usuarios_permanentes}\n\n"

                f"💳 Pagos totales: {total_pagos}"

            )


            await query.message.reply_text(texto)

        except Exception as e:

            print("ERROR admin_stats:", e)

            await query.message.reply_text(
                "❌ Error mostrando estadísticas"
            )

        return


    if data == "admin_active_users":

        group_ids = get_admin_group_ids(user_id, ["can_view_stats"])


        with conn.cursor() as cur:

            if group_ids is None:

                cur.execute("""

                    SELECT g.name,
                           COUNT(*)
                    FROM users u
                    LEFT JOIN groups g
                    ON u.group_id = g.id
                    WHERE u.expiration IS NULL
                    OR u.expiration > NOW()
                    GROUP BY g.name
                    ORDER BY g.name ASC

                """)

            elif not group_ids:

                rows = []

            else:

                cur.execute("""

                    SELECT g.name,
                           COUNT(*)
                    FROM users u
                    LEFT JOIN groups g
                    ON u.group_id = g.id
                    WHERE (
                        u.expiration IS NULL
                        OR u.expiration > NOW()
                    )
                    AND u.group_id = ANY(%s)
                    GROUP BY g.name
                    ORDER BY g.name ASC

                """, (group_ids,))


            if group_ids is None or group_ids:

                rows = cur.fetchall()


        if not rows:

            await query.message.reply_text(
                "👥 No hay usuarios activos."
            )

            return


        text = "👥 Usuarios activos por grupo\n\n"


        for group_name, total in rows:

            text += f"{group_name or '-'}: {total}\n"


        await query.message.reply_text(text)

        return


    if data == "admin_health":

        # Solo plataforma: es la foto de TODAS las comunidades, incluidas las
        # de otros propietarios.
        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        from platform_health_service import build_platform_health_text

        await query.message.reply_text(build_platform_health_text())

        return


    if data == "admin_income":

        # La versión vieja de esta pantalla tenía tres mentiras de dinero:
        # contaba devoluciones como ingreso, mezclaba monedas bajo
        # MAX(currency) y mostraba céntimos como si fueran unidades
        # ("1500 EUR" por 15 euros). Vive ahora en platform_revenue_service
        # con las mismas reglas que el panel del propietario.
        group_ids = get_admin_group_ids(
            user_id,
            ["can_view_payments", "can_view_stats"]
        )


        if group_ids is None:

            # Alcance total: la foto global de la plataforma, que no existía
            # en ningún sitio — ventanas con comparativa, proveedores, top de
            # comunidades y suscriptores.
            texto = build_platform_revenue_text()

        elif not group_ids:

            texto = "💰 No hay ingresos registrados en tus comunidades."

        else:

            texto = build_scoped_income_text(group_ids)


        await query.message.reply_text(texto)

        return


    # Tramo movido a admin_beta_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_admin_beta_callbacks(
        update, context, query, user_id, data
    ) is not ADMIN_BETA_NOT_HANDLED:

        return




    if data.startswith("admin_smoke"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        if data == "admin_smoke_run":

            try:

                report = run_beta_smoke_checks()
                run = save_beta_smoke_run(user_id, report)

                log_event(
                    "beta_smoke_test_run",
                    category="beta",
                    severity="warning" if run["failed_checks"] else "info",
                    message=(
                        f"Smoke test beta ejecutado: "
                        f"{run['passed_checks']} OK, "
                        f"{run['warning_checks']} warnings/manuales, "
                        f"{run['failed_checks']} fallos"
                    ),
                    actor_user_id=user_id,
                    metadata={
                        "run_id": run["id"],
                        "total_checks": run["total_checks"],
                        "passed_checks": run["passed_checks"],
                        "failed_checks": run["failed_checks"],
                        "warning_checks": run["warning_checks"]
                    }
                )

                await query.message.reply_text(
                    format_beta_smoke_report(run),
                    reply_markup=build_beta_smoke_test_keyboard()
                )

            except Exception as e:

                log_event(
                    "beta_smoke_test_error",
                    category="beta",
                    severity="warning",
                    message="Error ejecutando Smoke Test Beta",
                    actor_user_id=user_id,
                    metadata={"error": str(e)}
                )

                await query.message.reply_text(
                    "⚠️ No se pudo ejecutar el Smoke Test Beta.",
                    reply_markup=build_beta_smoke_test_keyboard()
                )

            return


        if data == "admin_smoke_manual":

            await query.message.reply_text(
                format_beta_smoke_manual_checklist(),
                reply_markup=build_beta_smoke_test_keyboard()
            )

            return


        if data == "admin_smoke_last":

            try:

                run = get_last_beta_smoke_run()
                text = format_beta_smoke_report(run)

            except Exception as e:

                text = (
                    "🧪 Smoke Test Beta\n\n"
                    f"⚠️ No se pudo cargar el último resultado: {e}"
                )


            await query.message.reply_text(
                text,
                reply_markup=build_beta_smoke_test_keyboard()
            )

            return


        if data == "admin_smoke_clear":

            try:

                affected = clear_beta_smoke_runs()

                log_event(
                    "beta_smoke_test_results_cleared",
                    category="beta",
                    severity="info",
                    message=f"Resultados Smoke Test Beta limpiados: {affected}",
                    actor_user_id=user_id
                )

                await query.message.reply_text(
                    f"🧹 Resultados eliminados: {affected}",
                    reply_markup=build_beta_smoke_test_keyboard()
                )

            except Exception as e:

                await query.message.reply_text(
                    f"⚠️ No se pudieron limpiar los resultados: {e}",
                    reply_markup=build_beta_smoke_test_keyboard()
                )

            return


        await query.message.reply_text(
            "🧪 Smoke Test Beta",
            reply_markup=build_beta_smoke_test_keyboard()
        )

        return


    # =========================
    # COPIA DE SEGURIDAD DE LA BASE DE DATOS
    # =========================
    # La base de datos se perdió una vez y no había copia propia. Desde aquí
    # se ve si existe una reciente y se puede pedir una al momento.

    if data == "admin_db_migrations":

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        from migrations_service import describe_migrations

        await query.message.reply_text(
            describe_migrations(),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Actualizar", callback_data="admin_db_migrations")],
                [InlineKeyboardButton("⬅️ Volver", callback_data="admin_global_tools")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("admin_db_backup"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        from db_backup_service import describe_last_backup

        backup_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗄️ Hacer copia ahora", callback_data="admin_db_backup_now")],
            [InlineKeyboardButton("🔄 Actualizar", callback_data="admin_db_backup")],
            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_global_tools")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])


        if data == "admin_db_backup_now":

            await query.message.reply_text(
                "🗄️ Creando la copia de seguridad…\n\n"
                "Puede tardar un momento. Te llegará como documento en este chat."
            )

            try:

                # asyncio ya está importado arriba. Importarlo AQUÍ lo convertía
                # en local de button() entera, y su uso anterior —el
                # asyncio.create_task que relanza la verificación del grupo
                # recién añadido— reventaba con UnboundLocalError. O sea que un
                # import escrito para una copia de seguridad rompía el botón de
                # «reintentar verificación» de quien acaba de dar de alta su
                # comunidad.
                from db_backup_service import run_backup_now

                # Volcar y subir es bloqueante: en un hilo para no congelar el bot.
                summary = await asyncio.to_thread(run_backup_now, True)

            except Exception as e:

                await query.message.reply_text(
                    f"❌ No se pudo crear la copia: {type(e).__name__}: {e}",
                    reply_markup=backup_keyboard
                )

                return


            if summary.get("sent"):

                await query.message.reply_text(
                    "✅ Copia creada y enviada.\n\n"
                    f"Fichero: {summary.get('filename')}\n"
                    f"Método: {summary.get('detail')}",
                    reply_markup=backup_keyboard
                )

            else:

                await query.message.reply_text(
                    "⚠️ No se pudo completar la copia.\n\n"
                    f"Motivo: {summary.get('detail') or 'desconocido'}",
                    reply_markup=backup_keyboard
                )


            return


        await query.message.reply_text(
            describe_last_backup(),
            reply_markup=backup_keyboard
        )

        return




    if data in (
        "admin_logs",
        "admin_logs_users",
        "admin_logs_payments",
        "admin_logs_security"
    ):

        group_ids = get_admin_group_ids(user_id, ["can_view_logs"])
        category_filter = None


        if data == "admin_logs_payments":

            category_filter = "payment"

        elif data == "admin_logs_security":

            category_filter = "access"

        elif data == "admin_logs_users":

            category_filter = "user"


        rows = list_recent_events(
            limit=50,
            group_ids=group_ids
        )


        if category_filter:

            rows = [
                row
                for row in rows
                if row[2] == category_filter
            ]


        if not rows:

            await query.message.reply_text(
                "📜 No hay logs registrados."
            )

            return


        text = (
            "📜 Logs del sistema\n\n"
            if group_ids is None
            else "📜 Logs de mi grupo\n\n"
        )


        for (
            created_at,
            event_type,
            category,
            severity,
            log_group_id,
            log_telegram_group_id,
            actor_user_id,
            target_user_id,
            message
        ) in rows[:30]:

            text += (
                f"Evento: {event_type or '-'}\n"
                f"Categoría: {category or '-'} / {severity or '-'}\n"
                f"Grupo: {log_group_id or '-'}"
                f" / {log_telegram_group_id or '-'}\n"
                f"Actor: {actor_user_id or '-'}\n"
                f"Usuario: {target_user_id or '-'}\n"
                f"Detalle: {message or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver", callback_data="menu_logs")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    # =========================
    # REVOCAR TODOS LOS LINKS
    # =========================

    if data == "admin_revoke_links":

        if not is_super_admin(query.from_user.id):
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT invite_link
                    FROM invite_links

                """)

                links = cur.fetchall()


            total = 0

            for (link,) in links:

                try:

                    # =========================
                    # OBTENER GRUPO REAL DEL LINK
                    # =========================

                    with conn.cursor() as cur2:

                        cur2.execute("""

                            SELECT COALESCE(telegram_group_id, group_id)
                            FROM invite_links
                            WHERE invite_link=%s

                        """, (link,))

                        group_row = cur2.fetchone()


                    if not group_row:
                        continue


                    telegram_group_id = group_row[0]


                    revoke_link(
                        telegram_group_id,
                        link
                    )

                    total += 1


                except Exception as e:

                    print(
                        "Error revocando link:",
                        e
                    )


            await query.message.reply_text(

                f"🔄 {total} links revocados correctamente."

            )

        except Exception as e:

            print("Error revocando todos:", e)

            await query.message.reply_text(
                "❌ Error revocando links"
            )

        return


    # =========================
    # REENVIAR LINKS NUEVOS
    # =========================






    # =========================
    # EDITAR PLAN — INICIO
    # =========================

    if data.startswith("edit_plan_"):

        parts = data.split("_")


        if len(parts) < 3 or not parts[2].isdigit():

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        plan_id = int(parts[2])
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(NULLIF(payment_provider, ''), 'stripe')
                FROM plans
                WHERE id=%s
                AND group_id=%s
                LIMIT 1

            """, (
                plan_id,
                group_id
            ))

            plan_row = cur.fetchone()


        if not plan_row:

            await query.message.reply_text(
                "⛔ No tienes permisos para editar este plan."
            )

            return

        clear_plan_wizard_state(
            context,
            user_id=user_id,
            action="start_edit_plan"
        )
        clear_owner_payment_provider_wizard_state(
            context,
            user_id=user_id,
            action="start_edit_plan"
        )

        context.user_data["editing_plan"] = True
        context.user_data["editing_plan_id"] = plan_id
        context.user_data["edit_plan_provider"] = normalize_plan_payment_provider(plan_row[0])
        context.user_data["edit_plan_step"] = 1

        await query.message.reply_text(

            "✏️ EDITAR PLAN\n\n"

            f"Método actual: {format_plan_payment_provider(plan_row[0])}\n"
            "Para cambiar método de pago, crea un nuevo plan. "
            "Puedes actualizar la referencia del proveedor actual.\n\n"

            "Paso 1️⃣\n"
            "Introduce el nuevo nombre del plan."

        )

        return


    # =========================
    # GENERAR CÓDIGOS
    # =========================

    if data.startswith("gen_"):

        await crear_codigo_callback(update, context)
        return


    # =========================
    # USAR CÓDIGO
    # =========================

    if data == "codigo":

        context.user_data["waiting_code"] = True

        await query.message.reply_text(
            "Introduce tu código:"
        )

        return








    if data.startswith("user_trial_setup_free_"):

        request_id = extract_commercial_request_id(data, "user_trial_setup_free_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        update_commercial_request_free_group(request_id)

        await notify_commercial_admin(
            context,
            (
                "🆓 Configuración comercial elegida\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}\n"
                "Modo: grupo gratuito"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"👁 Ver estado #{request_id}",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await query.message.reply_text(
            "🆓 Perfecto. Tu comunidad será gratis para los usuarios, pero el acceso seguirá protegido por el bot.\n\n"
            "Ahora puedes continuar la configuración de tu comunidad.\n\n"
            "Para mantener publicada tu comunidad después de la prueba, tendrás que activar una suscripción del servicio.",
            reply_markup=InlineKeyboardMarkup(build_user_activation_keyboard(request_id))
        )

        return


    if data.startswith("user_trial_setup_paid_"):

        request_id = extract_commercial_request_id(data, "user_trial_setup_paid_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        update_commercial_request_paid_group(request_id)

        await notify_commercial_admin(
            context,
            (
                "💳 Configuración comercial elegida\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}\n"
                "Modo: grupo de pago"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"👁 Ver estado #{request_id}",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await query.message.reply_text(
            "💳 Perfecto. Tu comunidad será de pago.\n\n"
            "Los pagos de tus usuarios deben ir a tu propia cuenta o sistema de cobro. "
            "Nosotros no recibiremos el dinero de tu comunidad.\n\n"
            "El siguiente paso será configurar tus planes y tus datos de cobro.",
            reply_markup=InlineKeyboardMarkup(build_user_trial_payment_keyboard(request_id))
        )

        return


    if data.startswith("user_trial_setup_owner_stripe_"):

        request_id = extract_commercial_request_id(data, "user_trial_setup_owner_stripe_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        update_commercial_request_stripe_mode(request_id, "owner_stripe")

        await notify_commercial_admin(
            context,
            (
                "🏦 Stripe propio seleccionado\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"👁 Ver estado #{request_id}",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await query.message.reply_text(
            "Perfecto. Has elegido configurar tu propio Stripe o sistema de cobro.\n\n"
            "El siguiente paso será dejar preparados tus planes, textos y datos de acceso.\n\n"
            "Para mantener publicada tu comunidad después de la prueba, tendrás que activar una suscripción del servicio.",
            reply_markup=InlineKeyboardMarkup(build_user_activation_keyboard(request_id))
        )

        return


    if data.startswith(LEGACY_USER_PLATFORM_STRIPE_CALLBACK_PREFIX):

        request_id = extract_commercial_request_id(
            data,
            LEGACY_USER_PLATFORM_STRIPE_CALLBACK_PREFIX
        )
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        await query.message.reply_text(
            "Esta opción ya no está disponible.\n\n"
            "Si tu comunidad será de pago, los cobros deben ir a tu propia cuenta o sistema de cobro.",
            reply_markup=InlineKeyboardMarkup(build_user_trial_payment_keyboard(request_id))
        )

        return


    if (
        data.startswith("configure_community_")
        or data.startswith("user_commercial_activate_")
    ):

        if data.startswith("configure_community_"):

            request_id = extract_commercial_request_id(data, "configure_community_")

        else:

            request_id = extract_commercial_request_id(data, "user_commercial_activate_")


        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        clear_creator_onboarding_context(context)

        _assigned, group_id = assign_owner_for_commercial_request(request_row)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_creator_setup_panel_text(group_id),
            reply_markup=InlineKeyboardMarkup(
                build_creator_setup_keyboard(
                    request_id,
                    request_row.get("payment_mode")
                )
            )
        )

        return


    # Tramo movido a creator_setup_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_creator_setup_callbacks(
        update, context, query, user_id, data
    ) is not CREATOR_SETUP_NOT_HANDLED:

        return






    if data.startswith("creator_promo_code_start_"):

        request_id = extract_commercial_request_id(data, "creator_promo_code_start_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "promo_code")

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Código promocional\n\n"
            "Envía ahora el código promocional que te dio el propietario principal."
        )

        return


    if data.startswith("expired_trial_activate_"):

        request_id = extract_commercial_request_id(data, "expired_trial_activate_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        plans = fetch_active_commercial_plans(PRODUCT_SHARED_BOT_SPACE)

        if not plans:

            await send_clean_message(
                context,
                query.message.chat_id,
                "💳 Activar suscripción\n\nTodavía no hay planes comerciales disponibles.",
                reply_markup=build_expired_trial_recovery_keyboard(request_id)
            )

            return


        keyboard = build_commercial_plan_keyboard(request_id, plans)
        keyboard.append([
            InlineKeyboardButton(
                "⬅️ Volver a opciones",
                callback_data=f"expired_trial_options_{request_id}"
            )
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Activar suscripción\n\nElige un plan comercial para volver a publicar tu comunidad.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data.startswith("expired_trial_options_"):

        request_id = extract_commercial_request_id(data, "expired_trial_options_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            expired_community_message(
                format_retention_days_left(request_row.get("delete_after"))
            ),
            reply_markup=build_expired_trial_recovery_keyboard(request_id)
        )

        return


    if (
        data.startswith("expired_trial_delete_")
        and not data.startswith("expired_trial_delete_confirm_")
    ):

        request_id = extract_commercial_request_id(data, "expired_trial_delete_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🗑 Eliminar comunidad definitivamente\n\n"
            "Esta acción ocultará y desactivará la comunidad. No se borrará físicamente por seguridad.\n\n"
            "¿Confirmas que quieres eliminarla?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Sí, eliminar comunidad",
                    callback_data=f"expired_trial_delete_confirm_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Cancelar",
                    callback_data=f"expired_trial_options_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("expired_trial_delete_confirm_"):

        request_id = extract_commercial_request_id(
            data,
            "expired_trial_delete_confirm_"
        )
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        disable_commercial_request_community(request_row)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Comunidad marcada con borrado definitivo.\n\n"
            "No se han borrado logs críticos, pero queda oculta, inactiva y fuera del marketplace.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🏠 Volver al inicio",
                    callback_data="public_back_start"
                )
            ]])
        )

        await notify_commercial_admin(
            context,
            (
                "🗑 Comunidad desactivada por el creador\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "👁 Ver estado",
                    callback_data=f"admin_commercial_review_{request_id}"
                )
            ]])
        )

        return




    # Tramo movido a creator_dynamic_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_creator_dynamic_callbacks(
        update, context, query, user_id, data
    ) is not CREATOR_DYNAMIC_NOT_HANDLED:

        return




    # Tramo movido a creator_preview_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_creator_preview_callbacks(
        update, context, query, user_id, data
    ) is not CREATOR_PREVIEW_NOT_HANDLED:

        return
























    # Tramo movido a creator_location_callbacks.py. El despacho va AQUÍ y no arriba: las
    # puertas de permisos de encima caen hacia estas ramas.
    if await handle_creator_location_callbacks(
        update, context, query, user_id, data
    ) is not CREATOR_LOCATION_NOT_HANDLED:

        return












    if data.startswith("user_commercial_plan_"):

        request_id, plan_id = extract_commercial_plan_selection(data)
        request_row = fetch_commercial_request(request_id)
        plan = fetch_commercial_plan(plan_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return

        if not plan:

            await query.message.reply_text(
                "❌ Plan comercial no encontrado."
            )

            return

        update_commercial_request_plan(request_id, plan_id, "pending")

        # Este era el segundo callejón: el mismo cobro sin conectar, en el
        # camino que recorre quien ya tiene una solicitud. Ahora los dos caminos
        # pasan por el mismo sitio, que es lo que evita que uno se arregle y el
        # otro se quede muerto.
        from platform_plan_service import (
            create_platform_plan_checkout,
            describe_plan_period,
            fetch_platform_plan,
            format_plan_amount,
        )

        plan_cobrable = fetch_platform_plan(plan_id)

        if not plan_cobrable:

            # Sin precio no se puede cobrar: se avisa al admin, que es quien
            # puede ponerlo, y al usuario se le dice algo que se entienda.
            await notify_commercial_admin(
                context,
                (
                    "📅 Plan comercial seleccionado sin precio\n\n"
                    f"Solicitud #{request_id}\n"
                    f"Usuario: {user_id}\n"
                    f"Plan: {plan.get('name') or '-'}\n"
                    "Ponle precio en «Planes comerciales del bot → Precio de "
                    "publicar comunidad» y podrá pagarlo solo."
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"👁 Ver estado #{request_id}",
                        callback_data=f"admin_commercial_review_{request_id}"
                    )]
                ])
            )

            await query.message.reply_text(
                "Esa duración todavía no tiene precio publicado. Ya hemos "
                "avisado y te escribimos con las condiciones."
            )

            return


        try:

            session = create_platform_plan_checkout(user_id, plan_cobrable)

        except Exception as e:

            log_event(
                "platform_plan_checkout_failed",
                category="billing",
                severity="error",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Error creando el checkout del plan de publicación.",
                metadata={
                    "plan_id": plan_cobrable.get("id"),
                    "commercial_request_id": request_id,
                    "error": str(e)[:300]
                }
            )

            await query.message.reply_text(
                "No he podido abrir el pago ahora mismo. Inténtalo en un "
                "momento o escríbenos y lo resolvemos."
            )

            return


        await query.message.reply_text(
            f"💳 {plan_cobrable.get('name')} · "
            f"{format_plan_amount(plan_cobrable)} "
            f"{describe_plan_period(plan_cobrable)}\n\n"
            "Completa el pago y el bot te avisa aquí mismo en cuanto se "
            "confirme.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "💳 Pagar", url=session.get("url")
            )]])
        )

        return


    # =========================
    # PAGOS PAYPAL DE GRUPO
    # =========================

    # COMPRA DE UN TOQUE DESDE /start. El escaparate ofrece la comunidad con
    # su precio y, cuando solo hay un plan, el botón lleva directo a pagar.
    #
    # No se puede usar el callback de Stripe a secas (el price_id) como hacen
    # los botones de la lista de planes: esa rama lee el grupo de
    # context.user_data["selected_group"], que en /start NO existe todavía —
    # el comprador no ha pasado por la pantalla que lo fija—. Así que el
    # botón lleva el grupo y el plan dentro, se validan contra la base de
    # datos (un callback se escribe a mano, la consulta no) y desde aquí sí
    # se fija el grupo antes de cobrar. Los demás proveedores ya llevan su
    # grupo en el callback y no necesitan esto.

    if data.startswith("startbuy_"):

        partes = data[len("startbuy_"):].split("_")

        if len(partes) != 2 or not all(p.isdigit() for p in partes):

            await query.message.reply_text(
                "⚠️ Esta opción ya no está disponible o no está configurada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        group_id, plan_id = int(partes[0]), int(partes[1])

        try:

            with conn.cursor() as cur:

                # La misma definición que el escaparate y el cobro: aquí
                # faltaba el NULLIF de price_id, así que un plan con las dos
                # columnas vacías devolvía «» y el cobro contestaba «Plan
                # inválido» al que ya había pulsado comprar.
                from weekly_offer_service import sql_precio_vigente

                # Con la persona delante: si tiene una oferta suya (el año con
                # descuento de quien ya probó una semana), el botón tiene que
                # llevar SU precio. Enseñarle el rebajado y mandar al cobro el
                # de tarifa sería cobrarle más de lo que ponía el botón.
                cur.execute("""

                    SELECT """ + sql_precio_vigente("p", "comprador") + """
                    FROM plans p
                    WHERE p.id=%(plan)s
                      AND p.group_id=%(grupo)s
                      AND COALESCE(p.is_active, TRUE)=TRUE
                      AND COALESCE(NULLIF(p.payment_provider, ''), 'stripe')='stripe'

                """, {
                    "plan": plan_id,
                    "grupo": group_id,
                    "comprador": query.from_user.id if query.from_user else None,
                })

                fila = cur.fetchone()

        except Exception as e:

            print("Compra desde inicio: error leyendo el plan:", str(e)[:200])
            fila = None


        if not fila or not fila[0]:

            await query.message.reply_text(
                "⚠️ Ese plan ya no está disponible. Mira las opciones de la "
                "comunidad y elige otra.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        context.user_data["selected_group"] = group_id

        log_user_event_by_ids(
            user_id,
            "start_offer_clicked",
            event_key=f"startbuy_{group_id}_{plan_id}",
            group_id=group_id
        )

        await create_checkout_for_user(
            context,
            query.message.chat_id,
            user_id,
            group_id,
            fila[0]
        )

        return


    if data.startswith("paypal_group_plan_"):

        payload = data.replace("paypal_group_plan_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el plan PayPal.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        group_id = int(parts[0])
        plan_id = int(parts[1])
        context.user_data["selected_group"] = group_id

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(NULLIF(payment_provider, ''), 'stripe')
                FROM plans
                WHERE id=%s
                AND group_id=%s
                AND is_active=TRUE
                LIMIT 1

            """, (
                plan_id,
                group_id
            ))

            plan_provider_row = cur.fetchone()


        if not plan_provider_row or normalize_plan_payment_provider(plan_provider_row[0]) != OWNER_PAYMENT_PROVIDER_PAYPAL:

            await query.message.reply_text(
                "⚠️ Este plan no está configurado para PayPal.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        if not is_paypal_group_checkout_available(group_id):

            provider_status = get_group_payment_provider_status(
                list_group_payment_provider_statuses(group_id),
                OWNER_PAYMENT_PROVIDER_PAYPAL
            )
            unavailable_text = "PayPal todavía no está configurado para esta comunidad."

            if is_group_provider_globally_disabled(provider_status):

                unavailable_text = (
                    "⚠️ PayPal está configurado para este plan, pero actualmente "
                    "está deshabilitado en la plataforma."
                )

            await query.message.reply_text(
                unavailable_text,
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


        if should_block_new_group_purchase(access_state):

            await send_existing_group_access_notice(
                context,
                query.message.chat_id,
                user_id,
                group_id,
                provider="paypal",
                access_state=access_state
            )

            return

        log_event(
            "plan_checkout_provider_routed",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Checkout de plan ruteado por proveedor.",
            metadata={
                "group_id": group_id,
                "user_id": user_id,
                "provider": OWNER_PAYMENT_PROVIDER_PAYPAL,
                "plan_id": plan_id
            }
        )


        if group_requires_location_gate(group_id):

            await request_location_verification(
                context,
                query.message.chat_id,
                group_id,
                "paypal_checkout",
                price_id=plan_id,
                telegram_user=query.from_user
            )

            return


        await create_paypal_group_checkout_for_user(
            context,
            query.message.chat_id,
            user_id,
            group_id,
            plan_id
        )

        return


    if data.startswith("revolut_group_plan_"):

        payload = data.replace("revolut_group_plan_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el plan Revolut.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        group_id = int(parts[0])
        plan_id = int(parts[1])
        context.user_data["selected_group"] = group_id


        if not is_revolut_group_checkout_available(group_id):

            await query.message.reply_text(
                "Revolut todavía no está configurado para esta comunidad.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


        if should_block_new_group_purchase(access_state):

            await send_existing_group_access_notice(
                context,
                query.message.chat_id,
                user_id,
                group_id,
                provider="revolut",
                access_state=access_state
            )

            return


        if group_requires_location_gate(group_id):

            await request_location_verification(
                context,
                query.message.chat_id,
                group_id,
                "revolut_checkout",
                price_id=plan_id,
                telegram_user=query.from_user
            )

            return


        await create_revolut_group_checkout_for_user(
            context,
            query.message.chat_id,
            user_id,
            group_id,
            plan_id
        )

        return


    if data.startswith("changenow_group_plan_"):

        payload = data.replace("changenow_group_plan_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el plan ChangeNOW.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        group_id = int(parts[0])
        plan_id = int(parts[1])
        context.user_data["selected_group"] = group_id


        if not is_changenow_group_checkout_available(group_id):

            await query.message.reply_text(
                "ChangeNOW todavía no está configurado para esta comunidad.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


        if should_block_new_group_purchase(access_state):

            await send_existing_group_access_notice(
                context,
                query.message.chat_id,
                user_id,
                group_id,
                provider="changenow",
                access_state=access_state
            )

            return


        if group_requires_location_gate(group_id):

            await request_location_verification(
                context,
                query.message.chat_id,
                group_id,
                "changenow_checkout",
                price_id=plan_id,
                telegram_user=query.from_user
            )

            return


        await create_changenow_group_checkout_for_user(
            context,
            query.message.chat_id,
            user_id,
            group_id,
            plan_id
        )

        return


    if data.startswith("guardarian_group_plan_"):

        payload = data.replace("guardarian_group_plan_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el plan Guardarian.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        group_id = int(parts[0])
        plan_id = int(parts[1])
        context.user_data["selected_group"] = group_id


        if not is_guardarian_group_checkout_available(group_id):

            await query.message.reply_text(
                "Guardarian todavía no está configurado para esta comunidad.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


        if should_block_new_group_purchase(access_state):

            await send_existing_group_access_notice(
                context,
                query.message.chat_id,
                user_id,
                group_id,
                provider="guardarian",
                access_state=access_state
            )

            return


        if group_requires_location_gate(group_id):

            await request_location_verification(
                context,
                query.message.chat_id,
                group_id,
                "guardarian_checkout",
                price_id=plan_id,
                telegram_user=query.from_user
            )

            return


        await create_guardarian_group_checkout_for_user(
            context,
            query.message.chat_id,
            user_id,
            group_id,
            plan_id
        )

        return


    # =========================
    # PAGOS STRIPE
    # =========================

    if data.startswith("group_"):

        log_event(
            "callback_unknown_group_prefixed",
            category="ui",
            severity="warning",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Callback con prefijo group_ no manejado por rutas específicas.",
            metadata={
                "callback_data": data
            }
        )

        await query.message.reply_text(
            "⚠️ Esta opción ya no está disponible o no está configurada.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return


    if is_legacy_callback(data):

        log_event(
            "legacy_callback_blocked",
            category="ui",
            severity="info",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Callback legacy bloqueado antes del fallback.",
            metadata={
                "callback_data": data
            }
        )

        await query.message.reply_text(
            "⚠️ Esta opción ya no está disponible o no está configurada.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return


    if not is_stripe_checkout_callback(data):

        log_event(
            "unknown_callback",
            category="ui",
            severity="info",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Callback desconocido o no configurado.",
            metadata={
                "callback_data": data
            }
        )

        await query.message.reply_text(
            "⚠️ Esta opción ya no está disponible o no está configurada.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return


    user_id = query.from_user.id

    group_id = context.user_data.get("selected_group")


    if not group_id:

        log_event(
            "checkout_callback_missing_group",
            category="payment",
            severity="warning",
            scope="global",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Callback de checkout sin grupo seleccionado.",
            metadata={
                "callback_data": data
            }
        )

        await query.message.reply_text(
            "⚠️ Esta opción ya no está disponible o no está configurada.",
            reply_markup=build_unknown_callback_keyboard()
        )

        return


    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    if should_block_new_group_purchase(access_state):

        await send_existing_group_access_notice(
            context,
            query.message.chat_id,
            user_id,
            group_id,
            provider="stripe",
            retry_callback=data,
            access_state=access_state
        )

        return


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   COALESCE(NULLIF(payment_provider, ''), 'stripe')
            FROM plans
            WHERE price_id=%s
            AND group_id=%s
            AND is_active=TRUE
            LIMIT 1

        """, (
            data,
            group_id
        ))

        stripe_plan_row = cur.fetchone()


    if not stripe_plan_row or normalize_plan_payment_provider(stripe_plan_row[1]) != OWNER_PAYMENT_PROVIDER_STRIPE:

        await query.message.reply_text(
            "⚠️ Este plan no está configurado para Stripe.",
            reply_markup=build_group_recovery_keyboard(group_id)
        )

        return

    log_event(
        "plan_checkout_provider_routed",
        category="payment",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Checkout de plan ruteado por proveedor.",
        metadata={
            "group_id": group_id,
            "user_id": user_id,
            "provider": OWNER_PAYMENT_PROVIDER_STRIPE,
            "plan_id": stripe_plan_row[0]
        }
    )


    if group_requires_location_gate(group_id):

        await request_location_verification(
            context,
            query.message.chat_id,
            group_id,
            "checkout",
            price_id=data,
            telegram_user=query.from_user
        )

        return


    await create_checkout_for_user(
        context,
        query.message.chat_id,
        user_id,
        group_id,
        data
    )
