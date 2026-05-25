import asyncio
import json
import os
import requests
import secrets
import string
import time
import unicodedata

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
    AI_ROLE_SUPERADMIN
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
from group_registration_handler import (
    cancel_creator_group_link_request,
    confirm_backup_destination_token,
    confirm_creator_group_link_request,
    leave_chat_safely,
    verificar_admin_despues
)
from invite_link_service import (
    create_telegram_invite_link,
    revoke_telegram_invite_link
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
from payment_access_service import (
    get_user_group_access_state,
    grant_group_access_after_payment,
    log_purchase_blocked_existing_access,
    should_block_new_group_purchase
)
from payment_providers.guardarian_provider import process_guardarian_webhook
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


TOKEN = os.environ.get("TOKEN")
SERVER_URL = os.environ.get("SERVER_URL")

revoke_link = None
get_group_id = None

OWNER_PAYMENT_PROVIDER_PAYPAL = "paypal"
OWNER_PAYMENT_PROVIDER_REVOLUT = "revolut"
OWNER_PAYMENT_PROVIDER_CHANGENOW = "changenow"
OWNER_PAYMENT_PROVIDER_GUARDARIAN = "guardarian"
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


def clear_owner_payment_provider_wizard(context):

    for key in OWNER_PAYMENT_PROVIDER_CONTEXT_KEYS:

        context.user_data.pop(key, None)


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


def build_owner_paypal_mode_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Sandbox", callback_data=f"owner_payment_paypal_mode_sandbox_{group_id}")],
        [InlineKeyboardButton("🚀 Live", callback_data=f"owner_payment_paypal_mode_live_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_paypal_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")]
    ])


def build_owner_revolut_mode_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Sandbox", callback_data=f"owner_payment_revolut_mode_sandbox_{group_id}")],
        [InlineKeyboardButton("🚀 Live", callback_data=f"owner_payment_revolut_mode_live_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_revolut_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")]
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


def build_owner_changenow_mode_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Fixed", callback_data=f"owner_payment_changenow_mode_fixed_{group_id}")],
        [InlineKeyboardButton("🌊 Floating", callback_data=f"owner_payment_changenow_mode_float_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_changenow_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")]
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


def build_platform_changenow_mode_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Fixed", callback_data="admin_payment_changenow_mode_fixed")],
        [InlineKeyboardButton("🌊 Floating", callback_data="admin_payment_changenow_mode_float")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_payment_changenow_cancel")],
        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")]
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


def build_owner_guardarian_mode_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Sandbox", callback_data=f"owner_payment_guardarian_mode_sandbox_{group_id}")],
        [InlineKeyboardButton("🚀 Live", callback_data=f"owner_payment_guardarian_mode_live_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_guardarian_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")]
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


def build_platform_guardarian_mode_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Sandbox", callback_data="admin_payment_guardarian_mode_sandbox")],
        [InlineKeyboardButton("🚀 Live", callback_data="admin_payment_guardarian_mode_live")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_payment_guardarian_cancel")],
        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")]
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


    keyboard.append([InlineKeyboardButton(
        "🏠 Inicio",
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(keyboard)


def format_access_expiration(expires_at):

    if not expires_at:
        return "permanente"

    try:
        return expires_at.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(expires_at)


def build_existing_group_access_text(access_state):

    group_name = access_state.get("group_name") or f"Grupo {access_state.get('group_id')}"
    expires_at = access_state.get("expires_at")

    if access_state.get("has_active_access"):

        return (
            f"✅ Ya tienes acceso activo a {group_name}.\n\n"
            f"Acceso: {format_access_expiration(expires_at)}\n\n"
            "Si necesitas volver a entrar, usa Recuperar/Reenviar enlace.\n"
            "Si crees que esto es un error, abre soporte."
        )

    if access_state.get("subscription_status") == "pending":

        provider = access_state.get("last_payment_provider") or "proveedor"

        return (
            f"⏳ Tienes un pago pendiente para {group_name}.\n\n"
            f"Proveedor: {provider}\n"
            f"Estado: {access_state.get('last_payment_status') or 'pending'}\n\n"
            "No crearé otro pago mientras este siga pendiente. Si tarda demasiado, abre soporte."
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


    if access_state.get("has_active_access"):

        keyboard.append([InlineKeyboardButton(
            "🔗 Recuperar/Reenviar enlace",
            callback_data=f"mysub_{telegram_group_id}" if telegram_group_id else "mis_subs"
        )])
        keyboard.append([InlineKeyboardButton(
            "📋 Ver mi suscripción",
            callback_data="mis_subs"
        )])

    elif access_state.get("subscription_status") == "pending":

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


def is_numeric_group_callback(callback_data):

    parts = (callback_data or "").split("_")

    return (
        len(parts) >= 2
        and parts[0] == "group"
        and parts[1].isdigit()
    )


def is_stripe_checkout_callback(callback_data):

    return (
        isinstance(callback_data, str)
        and callback_data.startswith("price_")
    )


LOCATION_REGION_TYPE_COUNTRY = "country"

LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY = (
    "spanish_autonomous_community"
)

COMUNIDAD_VALENCIANA_REGION = "comunidad_valenciana"

COMUNIDAD_VALENCIANA_LABEL = "Comunidad Valenciana"

HISPANIC_COUNTRIES = [
    ("ES", "España"),
    ("MX", "México"),
    ("AR", "Argentina"),
    ("CO", "Colombia"),
    ("CL", "Chile"),
    ("PE", "Perú"),
    ("VE", "Venezuela"),
    ("EC", "Ecuador"),
    ("BO", "Bolivia"),
    ("PY", "Paraguay"),
    ("UY", "Uruguay"),
    ("CR", "Costa Rica"),
    ("PA", "Panamá"),
    ("GT", "Guatemala"),
    ("HN", "Honduras"),
    ("SV", "El Salvador"),
    ("NI", "Nicaragua"),
    ("DO", "República Dominicana"),
    ("CU", "Cuba"),
    ("PR", "Puerto Rico"),
    ("GQ", "Guinea Ecuatorial")
]

HISPANIC_COUNTRY_LABELS = dict(HISPANIC_COUNTRIES)

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

SPANISH_AUTONOMOUS_COMMUNITIES = [
    ("all_spain", "Toda España"),
    ("andalucia", "Andalucía"),
    ("aragon", "Aragón"),
    ("asturias", "Asturias"),
    ("islas_baleares", "Islas Baleares"),
    ("canarias", "Canarias"),
    ("cantabria", "Cantabria"),
    ("castilla_la_mancha", "Castilla-La Mancha"),
    ("castilla_y_leon", "Castilla y León"),
    ("cataluna", "Cataluña"),
    (COMUNIDAD_VALENCIANA_REGION, COMUNIDAD_VALENCIANA_LABEL),
    ("extremadura", "Extremadura"),
    ("galicia", "Galicia"),
    ("comunidad_de_madrid", "Comunidad de Madrid"),
    ("region_de_murcia", "Región de Murcia"),
    ("navarra", "Comunidad Foral de Navarra"),
    ("pais_vasco", "País Vasco"),
    ("la_rioja", "La Rioja"),
    ("ceuta", "Ceuta"),
    ("melilla", "Melilla")
]

SPANISH_AUTONOMOUS_COMMUNITY_LABELS = dict(SPANISH_AUTONOMOUS_COMMUNITIES)

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


def build_location_denied_keyboard():

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


def build_location_country_keyboard(request_id):

    keyboard = []


    for country_code, country_name in HISPANIC_COUNTRIES:

        callback_data = (
            f"creator_location_spain_region_menu_{request_id}"
            if country_code == "ES"
            else f"creator_location_country_set_{request_id}_{country_code}"
        )

        keyboard.append([InlineKeyboardButton(
            country_name,
            callback_data=callback_data
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_location_gate_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_spanish_autonomous_community_keyboard(request_id):

    keyboard = []


    for slug, label in SPANISH_AUTONOMOUS_COMMUNITIES:

        callback_data = (
            f"creator_location_country_set_{request_id}_ES"
            if slug == "all_spain"
            else f"creator_location_spain_region_set_{request_id}_{slug}"
        )

        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=callback_data
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_location_gate_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


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


async def request_location_verification(
    context,
    chat_id,
    group_id,
    action,
    price_id=None
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


ADMIN_PERMISSION_COLUMNS = [
    "can_manage_users",
    "can_kick_users",
    "can_ban_users",
    "can_unban_users",
    "can_warn_users",
    "can_reset_warnings",
    "can_manage_plans",
    "can_manage_codes",
    "can_manage_groups",
    "can_manage_payments",
    "can_manage_admins",
    "can_view_users",
    "can_view_payments",
    "can_view_stats",
    "can_view_logs",
    "can_edit_group_texts",
    "can_edit_marketplace_preview",
    "can_respond_group_support",
    "can_resend_links"
]


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
        [InlineKeyboardButton("🧪 Smoke Test Beta", callback_data="admin_smoke_test")],
        [InlineKeyboardButton("🗓 Ciclo beta", callback_data="admin_beta_cycle")],
        [InlineKeyboardButton("🧪 Auditoría de botones", callback_data="admin_button_audit")],
        [InlineKeyboardButton("👁 Seguimiento de usuarios", callback_data="admin_user_tracking")],
        [InlineKeyboardButton("📜 Logs del sistema", callback_data="menu_logs")],
        [InlineKeyboardButton("📊 Monitor beta", callback_data="admin_beta_monitor")],
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


def get_customer_satisfaction_audience_label(audience):

    labels = {
        "global": "todos los usuarios elegibles",
        "users": "usuarios",
        "owners": "propietarios",
        "group_admins": "admins de grupo"
    }

    return labels.get(audience, audience)


def fetch_customer_satisfaction_questions(active_only=True):

    with conn.cursor() as cur:

        if active_only:

            cur.execute("""

                SELECT id, question_key, question_text, category, answer_type, sort_order
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL
                AND COALESCE(is_active, TRUE)=TRUE
                ORDER BY sort_order ASC, id ASC

            """)

        else:

            cur.execute("""

                SELECT id, question_key, question_text, category, answer_type, sort_order, is_active
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL
                ORDER BY sort_order ASC, id ASC

            """)

        return cur.fetchall()


def fetch_customer_satisfaction_recipients(audience, group_id=None):

    queries = []
    params = []

    group_filter_users = ""
    group_filter_admins = ""

    if group_id:
        group_filter_users = " AND group_id=%s"
        group_filter_admins = " AND group_id=%s"

    if audience in ("global", "users"):
        queries.append(f"""
            SELECT DISTINCT user_id
            FROM users
            WHERE user_id IS NOT NULL
            {group_filter_users}
        """)
        if group_id:
            params.append(group_id)

    if audience in ("global", "owners"):
        queries.append(f"""
            SELECT DISTINCT user_id
            FROM admins
            WHERE role='GROUP_OWNER'
            AND is_active=TRUE
            AND user_id IS NOT NULL
            {group_filter_admins}
        """)
        if group_id:
            params.append(group_id)

    if audience in ("global", "group_admins"):
        queries.append(f"""
            SELECT DISTINCT user_id
            FROM admins
            WHERE COALESCE(is_active, TRUE)=TRUE
            AND COALESCE(is_super_admin, FALSE)=FALSE
            AND COALESCE(role, '') <> 'GROUP_OWNER'
            AND user_id IS NOT NULL
            {group_filter_admins}
        """)
        if group_id:
            params.append(group_id)

    if audience == "global" and not group_id:
        queries.append("""
            SELECT DISTINCT user_id
            FROM commercial_requests
            WHERE user_id IS NOT NULL
        """)

    if not queries:
        return []

    with conn.cursor() as cur:
        cur.execute(" UNION ".join(queries), tuple(params))
        return sorted({row[0] for row in cur.fetchall() if row[0]})


def normalize_customer_satisfaction_campaign_id(campaign_id=None):

    return str(campaign_id or "default")


def create_customer_satisfaction_survey(
    created_by,
    audience,
    group_id=None,
    send_mode="pending",
    campaign_id=None
):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO customer_satisfaction_surveys
            (
                title,
                description,
                audience,
                status,
                created_by,
                group_id,
                campaign_id,
                send_mode
            )
            VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s)
            RETURNING id

        """, (
            "Encuesta de satisfacción beta",
            "Encuesta rápida de satisfacción para mejorar el bot.",
            audience,
            created_by,
            group_id,
            campaign_id,
            send_mode
        ))

        return cur.fetchone()[0]


def fetch_customer_satisfaction_survey(survey_id):

    with conn.cursor() as cur:
        cur.execute("""

            SELECT id,
                   audience,
                   status,
                   group_id,
                   COALESCE(campaign_id, 'default'),
                   COALESCE(send_mode, 'pending')
            FROM customer_satisfaction_surveys
            WHERE id=%s
            LIMIT 1

        """, (survey_id,))
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


def fetch_customer_satisfaction_completed_user_ids(audience, group_id=None):

    with conn.cursor() as cur:
        cur.execute("""

            SELECT DISTINCT r.user_id
            FROM customer_satisfaction_responses r
            JOIN customer_satisfaction_surveys s ON s.id=r.survey_id
            WHERE r.completed_at IS NOT NULL
            AND s.audience=%s
            AND COALESCE(s.group_id, 0)=COALESCE(%s, 0)
            AND r.user_id IS NOT NULL

        """, (audience, group_id))
        return {row[0] for row in cur.fetchall() if row[0]}


def fetch_customer_satisfaction_sent_user_ids(audience, group_id=None, campaign_id=None):

    params = [audience, group_id]
    campaign_filter = ""

    if campaign_id is not None:
        campaign_filter = "AND COALESCE(cs.campaign_id, 'default')=%s"
        params.append(normalize_customer_satisfaction_campaign_id(campaign_id))

    with conn.cursor() as cur:
        cur.execute(f"""

            SELECT DISTINCT cs.user_id
            FROM customer_satisfaction_sent cs
            JOIN customer_satisfaction_surveys s ON s.id=cs.survey_id
            WHERE s.audience=%s
            AND COALESCE(cs.group_id, 0)=COALESCE(%s, 0)
            {campaign_filter}
            AND cs.user_id IS NOT NULL

        """, tuple(params))
        return {row[0] for row in cur.fetchall() if row[0]}


def fetch_customer_satisfaction_failed_user_ids(audience, group_id=None, campaign_id=None):

    params = [audience, group_id]
    campaign_filter = ""

    if campaign_id is not None:
        campaign_filter = "AND COALESCE(cs.campaign_id, 'default')=%s"
        params.append(normalize_customer_satisfaction_campaign_id(campaign_id))

    with conn.cursor() as cur:
        cur.execute(f"""

            SELECT DISTINCT cs.user_id
            FROM customer_satisfaction_sent cs
            JOIN customer_satisfaction_surveys s ON s.id=cs.survey_id
            WHERE s.audience=%s
            AND COALESCE(cs.group_id, 0)=COALESCE(%s, 0)
            {campaign_filter}
            AND cs.status='failed'
            AND cs.user_id IS NOT NULL

        """, tuple(params))
        return {row[0] for row in cur.fetchall() if row[0]}


def build_customer_satisfaction_targeting(audience, mode, group_id=None, campaign_id=None):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)
    recipients = set(fetch_customer_satisfaction_recipients(audience, group_id=group_id))
    completed_users = fetch_customer_satisfaction_completed_user_ids(audience, group_id=group_id)
    sent_current_cycle = fetch_customer_satisfaction_sent_user_ids(
        audience,
        group_id=group_id,
        campaign_id=campaign_id
    )
    sent_any_cycle = fetch_customer_satisfaction_sent_user_ids(
        audience,
        group_id=group_id,
        campaign_id=None
    )
    failed_current_cycle = fetch_customer_satisfaction_failed_user_ids(
        audience,
        group_id=group_id,
        campaign_id=campaign_id
    )

    if mode == "resend_incomplete":
        targets = (sent_current_cycle | failed_current_cycle) & recipients
        targets -= completed_users
        skipped_already_sent = 0
    elif mode == "never_sent":
        targets = recipients - completed_users - sent_any_cycle
        skipped_already_sent = len(recipients - completed_users - targets)
    else:
        targets = recipients - completed_users - sent_current_cycle
        skipped_already_sent = len(recipients - completed_users - targets)

    return {
        "recipients": sorted(recipients),
        "targets": sorted(targets),
        "completed_users": sorted(completed_users & recipients),
        "sent_current_cycle": sorted(sent_current_cycle & recipients),
        "sent_any_cycle": sorted(sent_any_cycle & recipients),
        "failed_current_cycle": sorted(failed_current_cycle & recipients),
        "total": len(recipients),
        "target_count": len(targets),
        "skipped_completed": len(completed_users & recipients),
        "skipped_already_sent": skipped_already_sent
    }


def reserve_customer_satisfaction_delivery(
    survey_id,
    user_id,
    group_id,
    campaign_id,
    created_by,
    allow_existing=False
):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)

    with conn.cursor() as cur:
        cur.execute("""

            INSERT INTO customer_satisfaction_sent
            (
                survey_id,
                group_id,
                user_id,
                campaign_id,
                status,
                sent_at,
                created_by,
                updated_at
            )
            VALUES (%s, %s, %s, %s, 'sent', NOW(), %s, NOW())
            ON CONFLICT (survey_id, COALESCE(group_id, 0), user_id, COALESCE(campaign_id, 'default'))
            DO NOTHING
            RETURNING id

        """, (survey_id, group_id, user_id, campaign_id, created_by))
        row = cur.fetchone()

        if row:
            return True

        if allow_existing:
            cur.execute("""

                UPDATE customer_satisfaction_sent
                SET status='sent',
                    sent_at=NOW(),
                    failed_at=NULL,
                    failure_reason=NULL,
                    updated_at=NOW()
                WHERE survey_id=%s
                AND COALESCE(group_id, 0)=COALESCE(%s, 0)
                AND user_id=%s
                AND COALESCE(campaign_id, 'default')=%s

            """, (survey_id, group_id, user_id, campaign_id))
            return True

        return False


def mark_customer_satisfaction_delivery_failed(survey_id, user_id, group_id, campaign_id, error):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)
    reason = str(error)[:300]

    with conn.cursor() as cur:
        cur.execute("""

            UPDATE customer_satisfaction_sent
            SET status='failed',
                failed_at=NOW(),
                failure_reason=%s,
                updated_at=NOW()
            WHERE survey_id=%s
            AND COALESCE(group_id, 0)=COALESCE(%s, 0)
            AND user_id=%s
            AND COALESCE(campaign_id, 'default')=%s

        """, (reason, survey_id, group_id, user_id, campaign_id))


def mark_customer_satisfaction_delivery_skipped(
    survey_id,
    user_id,
    group_id,
    campaign_id,
    created_by,
    status
):

    if status not in ("skipped_completed", "skipped_already_sent"):
        return

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)

    with conn.cursor() as cur:
        cur.execute("""

            INSERT INTO customer_satisfaction_sent
            (
                survey_id,
                group_id,
                user_id,
                campaign_id,
                status,
                created_by,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (survey_id, COALESCE(group_id, 0), user_id, COALESCE(campaign_id, 'default'))
            DO UPDATE SET status=EXCLUDED.status,
                          updated_at=NOW()

        """, (survey_id, group_id, user_id, campaign_id, status, created_by))


def update_customer_satisfaction_sent_counts(
    survey_id,
    sent_count,
    failed_count,
    skipped_completed_count=0,
    skipped_already_sent_count=0
):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE customer_satisfaction_surveys
            SET status='sent',
                sent_at=NOW(),
                sent_count=%s,
                failed_count=%s,
                skipped_completed_count=%s,
                skipped_already_sent_count=%s
            WHERE id=%s

        """, (
            sent_count,
            failed_count,
            skipped_completed_count,
            skipped_already_sent_count,
            survey_id
        ))


def mark_customer_satisfaction_survey_sending(survey_id):

    with conn.cursor() as cur:
        cur.execute("""

            UPDATE customer_satisfaction_surveys
            SET status='sending'
            WHERE id=%s
            AND status='draft'
            RETURNING id

        """, (survey_id,))
        return cur.fetchone() is not None


def build_customer_satisfaction_delivery_status_text(audience="global", group_id=None, campaign_id="default"):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)
    targeting = build_customer_satisfaction_targeting(
        audience,
        "pending",
        group_id=group_id,
        campaign_id=campaign_id
    )

    with conn.cursor() as cur:
        cur.execute("""

            SELECT COUNT(*)
            FROM customer_satisfaction_sent cs
            JOIN customer_satisfaction_surveys s ON s.id=cs.survey_id
            WHERE s.audience=%s
            AND COALESCE(cs.group_id, 0)=COALESCE(%s, 0)
            AND COALESCE(cs.campaign_id, 'default')=%s
            AND cs.status='failed'

        """, (audience, group_id, campaign_id))
        failed_count = cur.fetchone()[0]

    scope_text = "global" if group_id is None else f"comunidad {group_id}"

    sent_without_response = len(set(targeting["sent_current_cycle"]) - set(targeting["completed_users"]))
    never_sent = len(set(targeting["recipients"]) - set(targeting["sent_any_cycle"]))

    return (
        "📊 Estado de envíos de satisfacción\n\n"
        f"Ámbito: {scope_text}\n"
        f"Audiencia: {get_customer_satisfaction_audience_label(audience)}\n"
        f"Campaña: {campaign_id}\n\n"
        f"Usuarios elegibles: {targeting['total']}\n"
        f"Completaron: {targeting['skipped_completed']}\n"
        f"Enviados sin responder: {sent_without_response}\n"
        f"Nunca enviados: {never_sent}\n"
        f"Fallidos: {failed_count}\n"
        f"Pendientes de enviar: {targeting['target_count']}\n\n"
        "Para que sea justo, el bot nunca reenvía por defecto a usuarios que ya respondieron."
    )


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
            expected_columns=12
        )
        return None

    if len(row) < 12:
        log_satisfaction_detail_row_issue(
            callback,
            user_id=user_id,
            group_id=group_id,
            screen=screen,
            row=row,
            expected_columns=12
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
        "skipped_count": safe_satisfaction_value(row, 11, 0) or 0
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
                       COUNT(DISTINCT cs.user_id) FILTER (WHERE cs.status IN ('sent', 'completed', 'failed')),
                       COUNT(DISTINCT r.user_id) FILTER (WHERE r.completed_at IS NOT NULL),
                       COUNT(DISTINCT cs.user_id) FILTER (WHERE cs.status='failed'),
                       COUNT(DISTINCT cs.user_id) FILTER (WHERE cs.status LIKE 'skipped%')
                FROM customer_satisfaction_surveys s
                LEFT JOIN groups g ON g.id=s.group_id
                LEFT JOIN customer_satisfaction_sent cs ON cs.survey_id=s.id
                LEFT JOIN customer_satisfaction_responses r ON r.survey_id=s.id
                {group_filter}
                GROUP BY s.id, s.title, s.group_id, g.name, s.campaign_id, s.status, s.created_at, s.sent_at
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

    lines = [
        "📋 Detalle de encuestas",
        "",
        "Elige una encuesta para ver enviados, pendientes, fallidos y respuestas persona por persona."
    ]

    for row in rows:
        survey = normalize_satisfaction_survey_row(
            row,
            user_id=user_id,
            group_id=group_id,
            screen="survey_list_text"
        )

        if not survey:
            continue

        pending_count = max(survey["sent_count"] - survey["completed_count"] - survey["failed_count"], 0)
        lines.append(
            f"\n#{survey['survey_id']} · {survey['title']}\n"
            f"Comunidad: {survey['group_name']} ({survey['group_id'] or 'global'})\n"
            f"Campaña: {survey['campaign_id']} · Estado: {survey['status']}\n"
            f"Enviados: {survey['sent_count']} · Completados: {survey['completed_count']} · Pendientes: {pending_count} · Fallidos: {survey['failed_count']} · Omitidos: {survey['skipped_count']}\n"
            f"Creada: {format_tracking_time(survey['created_at'])} · Enviada: {format_tracking_time(survey['sent_at'])}"
        )

    return "\n".join(lines) if len(lines) > 3 else "📋 Todavía no hay encuestas registradas para mostrar."


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


def build_customer_satisfaction_results_text():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*), COALESCE(SUM(sent_count), 0), COALESCE(SUM(failed_count), 0)
            FROM customer_satisfaction_surveys

        """)
        survey_count, sent_count, failed_count = cur.fetchone()

        cur.execute("""

            SELECT COUNT(*)
            FROM customer_satisfaction_responses
            WHERE completed_at IS NOT NULL

        """)
        completed_count = cur.fetchone()[0]

        cur.execute("""

            SELECT AVG(rating)
            FROM customer_satisfaction_answers
            WHERE rating IS NOT NULL

        """)
        average_rating = cur.fetchone()[0]

        cur.execute("""

            SELECT q.category, AVG(a.rating)
            FROM customer_satisfaction_answers a
            JOIN customer_satisfaction_questions q
            ON q.id=a.question_id
            WHERE a.rating IS NOT NULL
            GROUP BY q.category
            ORDER BY AVG(a.rating) ASC
            LIMIT 8

        """)
        category_rows = cur.fetchall()

        cur.execute("""

            SELECT q.question_text, a.text_answer
            FROM customer_satisfaction_answers a
            JOIN customer_satisfaction_questions q
            ON q.id=a.question_id
            WHERE a.text_answer IS NOT NULL
            AND LENGTH(TRIM(a.text_answer)) > 0
            ORDER BY a.created_at DESC
            LIMIT 5

        """)
        text_rows = cur.fetchall()

    response_rate = 0
    if sent_count:
        response_rate = round((completed_count / sent_count) * 100, 1)

    category_text = "\n".join(
        f"- {category}: {round(float(avg), 2)}/5"
        for category, avg in category_rows
    ) or "Sin puntuaciones todavía."

    latest_text = "\n".join(
        f"- {question}: {answer[:120]}"
        for question, answer in text_rows
    ) or "Sin respuestas de texto todavía."

    average_text = f"{round(float(average_rating), 2)}/5" if average_rating else "Sin datos"

    return (
        "📊 Resultados de satisfacción\n\n"
        f"Encuestas creadas: {survey_count}\n"
        f"Total enviados: {sent_count}\n"
        f"Fallidos: {failed_count}\n"
        f"Total respuestas: {completed_count}\n"
        f"Tasa respuesta: {response_rate}%\n"
        f"Media general: {average_text}\n\n"
        "Media por categoría:\n"
        f"{category_text}\n\n"
        "Últimas respuestas texto:\n"
        f"{latest_text}"
    )


def build_customer_satisfaction_questions_text():

    rows = fetch_customer_satisfaction_questions(active_only=False)

    if not rows:
        return "📝 Gestionar preguntas\n\nNo hay preguntas configuradas."

    lines = ["📝 Gestionar preguntas"]

    for row in rows:
        question_id, _key, text, category, answer_type, sort_order, is_active = row
        status = "activa" if is_active else "desactivada"
        lines.append(
            f"\n{sort_order or question_id}. {text}\n"
            f"Tipo: {answer_type} · Categoría: {category} · Estado: {status}"
        )

    return "\n".join(lines)


def build_customer_satisfaction_deactivate_keyboard():

    rows = fetch_customer_satisfaction_questions(active_only=True)
    keyboard = []

    for question_id, _key, text, _category, _answer_type, _sort_order in rows[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"🚫 {text[:35]}",
                callback_data=f"admin_satisfaction_deactivate_{question_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_customer_satisfaction")])

    return InlineKeyboardMarkup(keyboard)


def build_customer_satisfaction_edit_keyboard():

    rows = fetch_customer_satisfaction_questions(active_only=False)
    keyboard = []

    for question_id, _key, text, _category, _answer_type, _sort_order, _is_active in rows[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"✏️ {text[:35]}",
                callback_data=f"admin_satisfaction_edit_{question_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_customer_satisfaction")])

    return InlineKeyboardMarkup(keyboard)


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

        return [
            [InlineKeyboardButton("👑 Panel global del bot", callback_data="admin_global_panel")],
            [InlineKeyboardButton("🧑‍💼 Panel de propietarios", callback_data="admin_owners_panel")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ]


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


def build_beta_monitor_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Últimas 24h", callback_data="admin_beta_monitor_24h")],
        [InlineKeyboardButton("Críticos", callback_data="admin_beta_monitor_critical")],
        [InlineKeyboardButton("Warnings", callback_data="admin_beta_monitor_warning")],
        [InlineKeyboardButton("Pagos/accesos", callback_data="admin_beta_monitor_payments")],
        [InlineKeyboardButton("Códigos", callback_data="admin_beta_monitor_codes")],
        [InlineKeyboardButton("Backups", callback_data="admin_beta_monitor_backups")],
        [InlineKeyboardButton("🗓 Ciclo beta", callback_data="admin_beta_cycle")],
        [InlineKeyboardButton("▶️ Iniciar beta 1 semana", callback_data="admin_beta_cycle_start_beta_1")],
        [InlineKeyboardButton("🔁 Iniciar beta 2.0", callback_data="admin_beta_cycle_start_beta_2")],
        [InlineKeyboardButton("✅ Finalizar beta", callback_data="admin_beta_cycle_finish")],
        [InlineKeyboardButton("📋 Ver estado beta", callback_data="admin_beta_cycle_status")],
        [InlineKeyboardButton("🚀 Preparar lanzamiento final", callback_data="admin_beta_cycle_final_review")],
        [InlineKeyboardButton("Marcar resueltos", callback_data="admin_beta_monitor_resolve_all")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def format_beta_monitor_events_text(title, rows):

    if not rows:

        return f"{title}\n\nSin eventos registrados."


    text = f"{title}\n\n"


    for (
        event_id,
        created_at,
        event_type,
        severity,
        event_user_id,
        event_group_id,
        event_telegram_group_id,
        message,
        resolved
    ) in rows[:30]:

        status = "resuelto" if resolved else "pendiente"

        text += (
            f"#{event_id} · {event_type or '-'} · {severity or '-'} · {status}\n"
            f"Usuario: {event_user_id or '-'}\n"
            f"Grupo: {event_group_id or '-'} / {event_telegram_group_id or '-'}\n"
            f"Detalle: {message or '-'}\n"
            f"Fecha: {created_at or '-'}\n\n"
        )


    return text[:3900]


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


def format_beta_cycle_status_text():

    active_cycle = get_active_beta_cycle()
    latest_cycle = active_cycle or get_latest_beta_cycle()
    counts = get_beta_cycle_monitor_counts(hours=24)

    lines = [
        "🗓 Ciclo beta",
        "",
        format_beta_cycle_row(latest_cycle),
        "",
        "📊 Estado últimas 24h",
        f"Críticos abiertos: {counts.get('critical_open', 0)}",
        f"Warnings abiertos: {counts.get('warning_open', 0)}",
        f"Pagos: {counts.get('payments', 0)}",
        f"Accesos permitidos: {counts.get('access_allowed', 0)}",
        f"Códigos canjeados: {counts.get('codes', 0)}",
        f"Backups fallidos: {counts.get('backup_failed', 0)}",
        f"Tickets soporte: {counts.get('support_tickets', 0)}"
    ]

    return "\n".join(lines)


def format_final_launch_checklist():

    return (
        "🚀 Preparar lanzamiento final\n\n"
        "Antes de abrir comercialmente, revisa:\n\n"
        "☐ Bugs P0 cerrados\n"
        "☐ Bugs P1 cerrados o aceptados\n"
        "☐ Smoke test OK\n"
        "☐ Railway estable\n"
        "☐ Stripe probado\n"
        "☐ Backups probados\n"
        "☐ Soporte probado\n"
        "☐ Logs limpios\n\n"
        "Este checklist no cambia pagos, grupos ni datos de usuarios."
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
            and 'int(data.split("_")[1])' not in router_source,
            "El handler group_{id} valida prefijo numérico"
        ),
        (
            "Sin int(data.split(...)) peligroso",
            "int(data.split" not in router_source,
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


GROUP_ADMIN_PERMISSION_OPTIONS = [
    ("view_users", "Ver usuarios", "can_view_users"),
    ("manage_users", "Gestionar usuarios", "can_manage_users"),
    ("kick_users", "Expulsar usuarios", "can_kick_users"),
    ("ban_users", "Banear usuarios", "can_ban_users"),
    ("unban_users", "Desbanear usuarios", "can_unban_users"),
    ("warn_users", "Dar warnings", "can_warn_users"),
    ("reset_warnings", "Resetear warnings", "can_reset_warnings"),
    ("manage_links", "Gestionar enlaces", "can_resend_links"),
    ("view_stats", "Ver estadísticas", "can_view_stats"),
    ("manage_plans", "Gestionar planes", "can_manage_plans"),
    ("edit_texts", "Editar textos del grupo", "can_edit_group_texts"),
    ("edit_preview", "Editar preview marketplace", "can_edit_marketplace_preview"),
    ("support", "Responder soporte del grupo", "can_respond_group_support"),
    ("view_logs", "Ver logs del grupo", "can_view_logs")
]


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


def fetch_backup_owner_groups(user_id):

    with conn.cursor() as cur:

        if is_super_admin(user_id):

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       COALESCE(bot_is_admin, FALSE)
                FROM groups
                WHERE telegram_group_id IS NOT NULL
                AND telegram_group_id != 0
                AND COALESCE(is_active, TRUE)=TRUE
                ORDER BY name ASC NULLS LAST,
                         id ASC

            """)

        else:

            cur.execute("""

                SELECT g.id,
                       g.name,
                       g.telegram_group_id,
                       COALESCE(g.bot_is_admin, FALSE)
                FROM admins a
                JOIN groups g
                ON g.id = a.group_id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                AND g.telegram_group_id IS NOT NULL
                AND g.telegram_group_id != 0
                AND COALESCE(g.is_active, TRUE)=TRUE
                ORDER BY g.name ASC NULLS LAST,
                         g.id ASC

            """, (user_id,))


        return cur.fetchall()


def fetch_backup_config(config_id, user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   owner_user_id,
                   source_group_id,
                   source_telegram_group_id,
                   destination_group_id,
                   destination_telegram_group_id,
                   mode,
                   status,
                   COALESCE(show_original_author, FALSE)
            FROM group_backup_configs
            WHERE id=%s
            AND owner_user_id=%s
            LIMIT 1

        """, (
            config_id,
            user_id
        ))

        return cur.fetchone()


def fetch_owner_backup_configs(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT c.id,
                   c.status,
                   c.mode,
                   sg.name,
                   dg.name,
                   c.last_message_at,
                   c.source_group_id,
                   c.destination_group_id,
                   COALESCE(c.show_original_author, FALSE)
            FROM group_backup_configs c
            LEFT JOIN groups sg
            ON sg.id = c.source_group_id
            LEFT JOIN groups dg
            ON dg.id = c.destination_group_id
            WHERE c.owner_user_id=%s
            ORDER BY c.updated_at DESC,
                     c.created_at DESC

        """, (user_id,))

        return cur.fetchall()


def format_backup_panel_text(user_id):

    configs = fetch_owner_backup_configs(user_id)


    if not configs:

        return (
            "🛡 Backup premium\n\n"
            "Estado: sin configurar\n"
            "Modo disponible: texto\n\n"
            "Selecciona un grupo origen y un grupo destino para copiar "
            "mensajes de texto nuevos que el bot reciba."
        )


    text = "🛡 Backup premium\n\n"


    for config in configs[:3]:

        (
            config_id,
            status,
            mode,
            source_name,
            destination_name,
            last_message_at,
            _source_group_id,
            _destination_group_id,
            show_original_author
        ) = config

        text += (
            f"Config #{config_id}\n"
            f"Estado: {status or 'inactive'}\n"
            f"Origen: {source_name or '-'}\n"
            f"Destino: {destination_name or '-'}\n"
            f"Modo: {format_backup_mode(mode)}\n"
            f"Mostrar autor original: {'Activado' if show_original_author else 'Desactivado'}\n"
            f"Último mensaje copiado: {last_message_at or '-'}\n\n"
        )


    return text


def format_backup_mode(mode):

    if mode == "text_photos":

        return "Texto + fotos"


    if mode == "text_photos_videos":

        return "Texto + fotos + vídeos"


    return "Solo texto"


def build_backup_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Activar backup", callback_data="owner_backup_activate")],
        [InlineKeyboardButton("⏸ Pausar backup", callback_data="owner_backup_pause")],
        [InlineKeyboardButton("⚙️ Cambiar modo", callback_data="owner_backup_change_mode")],
        [InlineKeyboardButton("🔗 Vincular grupo destino con código", callback_data="owner_backup_destination_token")],
        [InlineKeyboardButton("👤 Mostrar autor original", callback_data="owner_backup_toggle_author")],
        [InlineKeyboardButton("🔁 Cambiar destino", callback_data="owner_backup_change_destination")],
        [InlineKeyboardButton("⚠️ Últimos errores", callback_data="owner_backup_errors")],
        [InlineKeyboardButton("📜 Últimos mensajes copiados", callback_data="owner_backup_messages")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def build_backup_group_select_keyboard(groups, prefix, back_callback="owner_backup_panel"):

    keyboard = []


    for group_id, name, _telegram_group_id, bot_is_admin in groups:

        label = name or f"Grupo {group_id}"


        if not bot_is_admin:

            label += " · bot sin admin"


        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"{prefix}{group_id}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)


def backup_group_by_id(groups, group_id):

    for group in groups:

        if int(group[0]) == int(group_id):

            return group


    return None


def build_backup_config_select_keyboard(configs, prefix, back_callback="owner_backup_panel"):

    keyboard = []


    for config in configs:

        (
            config_id,
            status,
            mode,
            source_name,
            destination_name,
            _last_message_at,
            _source_group_id,
            _destination_group_id,
            _show_original_author
        ) = config

        keyboard.append([
            InlineKeyboardButton(
                f"#{config_id} · {source_name or '-'} → {destination_name or '-'} · {format_backup_mode(mode)} · {status or 'inactive'}",
                callback_data=f"{prefix}{config_id}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)


def build_backup_mode_keyboard(config_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Solo texto", callback_data=f"owner_backup_set_mode_{config_id}_text")],
        [InlineKeyboardButton("Texto + fotos", callback_data=f"owner_backup_set_mode_{config_id}_text_photos")],
        [InlineKeyboardButton("Texto + fotos + vídeos", callback_data=f"owner_backup_set_mode_{config_id}_text_photos_videos")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="owner_backup_panel")]
    ])


def generate_backup_destination_token():

    alphabet = string.ascii_uppercase + string.digits

    return "BACKUP-" + "".join(
        secrets.choice(alphabet)
        for _ in range(5)
    )


def create_backup_destination_token(owner_user_id, source_group_id, source_telegram_group_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE backup_destination_tokens
            SET status='expired',
                updated_at=NOW()
            WHERE owner_user_id=%s
            AND source_group_id=%s
            AND status='pending'

        """, (
            owner_user_id,
            source_group_id
        ))


        for _attempt in range(5):

            token = generate_backup_destination_token()

            try:

                cur.execute("""

                    INSERT INTO backup_destination_tokens
                    (
                        token,
                        owner_user_id,
                        source_group_id,
                        source_telegram_group_id,
                        status,
                        expires_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, 'pending', NOW() + INTERVAL '24 hours', NOW())
                    RETURNING id, token, expires_at

                """, (
                    token,
                    owner_user_id,
                    source_group_id,
                    source_telegram_group_id
                ))

                row = cur.fetchone()
                conn.commit()

                return row

            except Exception:

                conn.rollback()


    return None


def fetch_backup_recent_messages(user_id, limit=20):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT l.created_at,
                   sg.name,
                   dg.name,
                   l.source_message_id,
                   l.destination_message_id,
                   l.message_type,
                   l.status
            FROM backup_message_log l
            JOIN group_backup_configs c
            ON c.id = l.config_id
            LEFT JOIN groups sg
            ON sg.id = l.source_group_id
            LEFT JOIN groups dg
            ON dg.id = l.destination_group_id
            WHERE c.owner_user_id=%s
            ORDER BY l.created_at DESC
            LIMIT %s

        """, (
            user_id,
            limit
        ))

        return cur.fetchall()


def fetch_backup_recent_errors(user_id, limit=20):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT e.created_at,
                   e.severity,
                   e.error_type,
                   e.message
            FROM backup_errors e
            WHERE e.owner_user_id=%s
            ORDER BY e.created_at DESC
            LIMIT %s

        """, (
            user_id,
            limit
        ))

        return cur.fetchall()


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
                   telegram_group_id
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


    resolved_group_id, _group_name, telegram_group_id = group
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


def fetch_group_user_promo_codes(group_id, active_only=False):

    with conn.cursor() as cur:

        active_filter = ""


        if active_only:

            active_filter = """
                AND is_active=TRUE
                AND (
                    expires_at IS NULL
                    OR expires_at > NOW()
                )
                AND (
                    max_uses=0
                    OR used_count < max_uses
                )
            """


        cur.execute(f"""

            SELECT id,
                   code,
                   duration_days,
                   is_permanent,
                   max_uses,
                   used_count,
                   is_active,
                   expires_at,
                   created_at
            FROM group_user_promo_codes
            WHERE group_id=%s
            {active_filter}
            ORDER BY created_at DESC
            LIMIT 50

        """, (group_id,))

        return cur.fetchall()


def fetch_group_user_promo_usage(group_id, limit=30):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT r.redeemed_at,
                   r.user_id,
                   c.code,
                   r.expiration
            FROM group_user_promo_redemptions r
            JOIN group_user_promo_codes c
            ON c.id = r.code_id
            WHERE r.group_id=%s
            ORDER BY r.redeemed_at DESC
            LIMIT %s

        """, (
            group_id,
            limit
        ))

        return cur.fetchall()


def format_group_user_promo_duration(duration_days, is_permanent):

    if is_permanent:

        return "permanente"


    return f"{duration_days} día(s)"


def format_group_user_promo_uses(max_uses, used_count):

    if max_uses == 0:

        return f"{used_count}/ilimitado"


    return f"{used_count}/{max_uses}"


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


def build_group_user_code_duration_keyboard(group_id=None):

    suffix = f"_{group_id}" if group_id else ""

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 día", callback_data=f"group_user_code_duration{suffix}_1")],
        [InlineKeyboardButton("7 días", callback_data=f"group_user_code_duration{suffix}_7")],
        [InlineKeyboardButton("30 días", callback_data=f"group_user_code_duration{suffix}_30")],
        [InlineKeyboardButton("Permanente", callback_data=f"group_user_code_duration{suffix}_permanent")],
        [InlineKeyboardButton("Personalizado", callback_data=f"group_user_code_duration{suffix}_custom")],
        [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))]
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


def build_group_user_code_kind_keyboard(group_id=None):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Código automático", callback_data=build_group_user_code_callback("group_user_code_auto", group_id))],
        [InlineKeyboardButton("Código manual", callback_data=build_group_user_code_callback("group_user_code_manual", group_id))],
        [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_code_create", group_id))]
    ])


def build_group_user_code_deactivate_keyboard(rows, group_id=None):

    keyboard = []


    for code_id, code, duration_days, is_permanent, max_uses, used_count, _is_active, _expires_at, _created_at in rows:

        keyboard.append([
            InlineKeyboardButton(
                f"{code} · {format_group_user_promo_duration(duration_days, is_permanent)} · {format_group_user_promo_uses(max_uses, used_count)}",
                callback_data=(
                    f"group_user_code_deactivate_{group_id}_{code_id}"
                    if group_id
                    else f"group_user_code_deactivate_{code_id}"
                )
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))])

    return InlineKeyboardMarkup(keyboard)


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


    _group_id, _group_name, telegram_group_id = group
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


async def grant_group_user_promo_access(context, chat_id, telegram_user, promo_row):

    (
        code_id,
        group_id,
        telegram_group_id,
        owner_user_id,
        code,
        duration_days,
        is_permanent,
        _max_uses,
        _used_count,
        _is_active,
        _expires_at,
        group_name,
        _group_is_active
    ) = promo_row

    user_id = telegram_user.id


    if not is_permanent and not duration_days:

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Este código no tiene una duración válida."
        )

        return


    expiration = None


    if not is_permanent:

        expiration = datetime.now() + timedelta(days=int(duration_days))


    link = create_telegram_invite_link(
        TOKEN,
        telegram_group_id,
        expire_seconds=180,
        member_limit=1
    )


    if not link:

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Error creando el enlace de acceso."
        )

        return


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE group_user_promo_codes
            SET used_count=used_count + 1
            WHERE id=%s
            AND is_active=TRUE
            AND (
                expires_at IS NULL
                OR expires_at > NOW()
            )
            AND (
                max_uses=0
                OR used_count < max_uses
            )
            RETURNING used_count

        """, (code_id,))

        code_update = cur.fetchone()


        if not code_update:

            conn.rollback()

            try:

                revoke_telegram_invite_link(
                    TOKEN,
                    telegram_group_id,
                    link
                )

            except Exception as e:

                print("Error revocando link de código no disponible:", e)


            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Este código ya no está disponible."
            )

            return


        cur.execute("""

            DELETE FROM invite_links
            WHERE user_id=%s
            AND (
                group_id=%s
                OR telegram_group_id=%s
                OR group_id=%s
            )

        """, (
            user_id,
            group_id,
            telegram_group_id,
            telegram_group_id
        ))

        cur.execute("""

            INSERT INTO invite_links
            (user_id, group_id, telegram_group_id, invite_link, is_active)
            VALUES (%s, %s, %s, %s, TRUE)

        """, (
            user_id,
            group_id,
            telegram_group_id,
            link
        ))

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
            VALUES (%s, %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (user_id, group_id)
            DO UPDATE SET
                username=EXCLUDED.username,
                first_name=EXCLUDED.first_name,
                expiration=EXCLUDED.expiration,
                subscription_active=TRUE,
                last_invite_link=EXCLUDED.last_invite_link

        """, (
            user_id,
            group_id,
            telegram_user.username,
            telegram_user.first_name,
            expiration,
            link
        ))

        cur.execute("""

            INSERT INTO group_user_promo_redemptions
            (
                code_id,
                group_id,
                user_id,
                invite_link,
                expiration
            )
            VALUES (%s, %s, %s, %s, %s)

        """, (
            code_id,
            group_id,
            user_id,
            link,
            expiration
        ))

        conn.commit()


    log_event(
        "group_user_promo_redeemed",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=user_id,
        target_user_id=owner_user_id,
        message="Código promocional de grupo canjeado.",
        metadata={
            "code_id": code_id,
            "code": code,
            "is_permanent": is_permanent,
            "duration_days": duration_days
        }
    )

    log_user_event_by_ids(
        user_id,
        "code_redeemed",
        event_key="group_user_promo_code",
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        group_id=group_id,
        metadata={
            "code_id": code_id,
            "duration_days": duration_days,
            "is_permanent": is_permanent
        }
    )


    try:

        await context.bot.send_message(
            chat_id=owner_user_id,
            text=(
                "🎟 Código de tu grupo canjeado\n\n"
                f"Grupo: {group_name or group_id}\n"
                f"Usuario: {user_id}\n"
                f"Código: {code}"
            )
        )

    except Exception as e:

        print("Error avisando al owner del canje de código:", e)


    expiration_text = "permanente" if expiration is None else expiration.strftime("%Y-%m-%d %H:%M")

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ Código canjeado correctamente.\n\n"
            f"Comunidad: {group_name or group_id}\n"
            f"Acceso: {expiration_text}\n\n"
            "Este enlace es personal y de un solo uso.\n"
            "No lo compartas.\n\n"
            f"{link}"
        ),
        reply_markup=ReplyKeyboardRemove()
    )


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


def fetch_group_admin_manageable_groups(user_id):

    return fetch_admin_groups_for_permissions(
        user_id,
        ["can_manage_admins"]
    )


def fetch_group_admin_context_groups(context, user_id):

    focused_group_id = context.user_data.get("selected_owner_group")


    if focused_group_id and can_manage_group_admins(user_id, focused_group_id):

        return [
            (
                focused_group_id,
                fetch_group_name(focused_group_id),
                None
            )
        ]


    return fetch_group_admin_manageable_groups(user_id)


def build_group_admin_error_keyboard():

    return InlineKeyboardMarkup([
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


def build_group_admin_group_select_keyboard(groups, callback_prefix, back_callback="group_admin_panel"):

    keyboard = []


    for group_id, name, _telegram_group_id in groups:

        keyboard.append([InlineKeyboardButton(
            name or f"Grupo {group_id}",
            callback_data=f"{callback_prefix}{group_id}"
        )])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)


def fetch_group_admins(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT user_id,
                   role,
                   can_view_users,
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
                   is_active
            FROM admins
            WHERE group_id=%s
            AND is_super_admin=FALSE
            ORDER BY role DESC, user_id ASC

        """, (group_id,))

        return cur.fetchall()


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


def disable_group_admin(group_id, target_user_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE admins
            SET is_active=FALSE
            WHERE group_id=%s
            AND user_id=%s
            AND is_super_admin=FALSE
            AND COALESCE(role, '') != 'GROUP_OWNER'
            RETURNING id

        """, (
            group_id,
            target_user_id
        ))

        return cur.fetchone() is not None


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


def build_group_admins_text(group_id):

    rows = fetch_group_admins(group_id)
    group_name = fetch_group_name(group_id)


    if not rows:

        return f"👥 Admins de mi grupo\n\nGrupo: {group_name}\n\nNo hay admins activos."


    lines = [
        f"👥 Admins de mi grupo\n\nGrupo: {group_name}"
    ]


    for row in rows:

        target_user_id = row[0]
        role = row[1] or "GROUP_ADMIN"
        is_active = row[-1] is True
        permissions = {
            permission: row[index + 2] is True
            for index, (_key, _label, permission) in enumerate(GROUP_ADMIN_PERMISSION_OPTIONS)
        }
        status = "activo" if is_active else "inactivo"
        lines.append(
            "\n"
            f"Usuario: {target_user_id}\n"
            f"Rol: {role}\n"
            f"Estado: {status}\n"
            f"{format_group_admin_permission_list(permissions)}"
        )


    return "\n".join(lines)


def build_group_admin_user_select_keyboard(group_id, callback_prefix, include_owner=False):

    rows = fetch_group_admins(group_id)
    keyboard = []


    for row in rows:

        target_user_id = row[0]
        role = row[1] or "GROUP_ADMIN"
        is_active = row[-1] is True


        if not include_owner and role == "GROUP_OWNER":

            continue


        if not is_active:

            continue


        keyboard.append([InlineKeyboardButton(
            f"{target_user_id} — {role}",
            callback_data=f"{callback_prefix}{group_id}_{target_user_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="group_admin_panel"
    )])

    return InlineKeyboardMarkup(keyboard)


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


OWNER_QUICK_STATUS_PERMISSIONS = {
    "can_view_users": "ver usuarios",
    "can_manage_users": "gestionar usuarios",
    "can_kick_users": "expulsar usuarios",
    "can_ban_users": "banear usuarios",
    "can_unban_users": "desbanear usuarios",
    "can_warn_users": "gestionar warnings",
    "can_reset_warnings": "reiniciar warnings",
    "can_resend_links": "reenviar enlaces",
    "can_recover_access": "recuperar accesos",
    "can_manage_codes": "gestionar códigos",
    "can_manage_plans": "gestionar planes",
    "can_manage_payments": "gestionar pagos",
    "can_view_payments": "ver pagos",
    "can_manage_groups": "configurar comunidad",
    "can_manage_admins": "gestionar admins",
    "can_view_logs": "ver logs",
    "can_edit_group_texts": "editar textos",
    "can_edit_marketplace_preview": "editar marketplace",
}


def get_group_permission_summary(user_id, group_id):

    if is_super_admin(user_id):

        return "Puedes gestionar: todo el panel de esta comunidad."


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT role, """ + ", ".join(ADMIN_PERMISSION_COLUMNS) + """
                FROM admins
                WHERE user_id=%s
                AND group_id=%s
                AND is_active=TRUE
                LIMIT 1

            """, (user_id, group_id))

            row = cur.fetchone()

    except Exception as e:

        print("Error cargando permisos del grupo:", e)

        return "Puedes gestionar: permisos no disponibles ahora."


    if not row:

        return "Puedes gestionar: ninguna sección de esta comunidad."


    role = row[0]

    if role == "GROUP_OWNER":

        return "Puedes gestionar: todo el panel owner de esta comunidad."


    granted = [
        OWNER_QUICK_STATUS_PERMISSIONS[column]
        for index, column in enumerate(ADMIN_PERMISSION_COLUMNS, start=1)
        if row[index] and column in OWNER_QUICK_STATUS_PERMISSIONS
    ]


    if not granted:

        return "Puedes gestionar: permisos limitados sin accesos rápidos activos."


    return "Puedes gestionar: " + ", ".join(granted[:8]) + ("..." if len(granted) > 8 else "") + "."


def fetch_owner_group_quick_status(group_id):

    status = {
        "name": "Comunidad",
        "is_free_group": False,
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

                SELECT name, COALESCE(is_free_group, FALSE), COALESCE(public_visibility, 'start_home')
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            group_row = cur.fetchone()

            if group_row:

                status["name"] = group_row[0] or "Comunidad"
                status["is_free_group"] = bool(group_row[1])
                status["public_visibility"] = group_row[2] or "start_home"


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


def build_owner_quick_status_text(user_id, group_id):

    status = fetch_owner_group_quick_status(group_id)
    access_type = "Gratis" if status["is_free_group"] else "Pago"
    backup_text = "Activo" if status["backup_active"] else "No activo"
    errors_text = "Sin errores críticos recientes"


    if status["critical_errors"]:

        errors_text = "\n".join(
            f"- {event_type or 'error'}: {message or 'sin detalle'}"
            for event_type, message in status["critical_errors"]
        )


    return (
        "✅ Estado rápido de esta comunidad\n\n"
        f"Comunidad: {status['name']}\n"
        f"Tipo: {access_type}\n"
        f"Visibilidad marketplace: {status['public_visibility']}\n"
        f"Usuarios activos: {status['active_users']}\n"
        f"Planes activos: {status['active_plans']}\n"
        f"Códigos activos: {status['active_codes']}\n"
        f"Admins activos: {status['active_admins']}\n"
        f"Backup: {backup_text}\n"
        f"Errores críticos recientes: {errors_text}\n\n"
        f"{get_group_permission_summary(user_id, group_id)}\n\n"
        "🏪 Panel de comunidad\n"
        "Elige el apartado que quieres gestionar."
    )


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
        keyboard.append([InlineKeyboardButton("🛡 Backup opcional", callback_data="owner_panel_backup")])


    keyboard.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return InlineKeyboardMarkup(keyboard)


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
            InlineKeyboardButton("🛡 Backup premium", callback_data="owner_panel_backup")
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


def build_owner_section_keyboard(user_id, group_id, section):

    keyboard = []


    if section == "users":

        if user_has_group_permission_any(user_id, group_id, ["can_view_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("📋 Ver usuarios de esta comunidad", callback_data=f"owner_group_users_{group_id}")])

        if user_has_group_permission_any(user_id, group_id, ["can_kick_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("🚫 Expulsar usuario", callback_data="admin_kick_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_ban_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("⛔ Banear usuario", callback_data="admin_ban_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_unban_users", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("♻️ Desbanear usuario", callback_data="admin_unban_user")])

        if user_has_group_permission_any(user_id, group_id, ["can_warn_users", "can_reset_warnings", "can_manage_users"]):
            keyboard.append([InlineKeyboardButton("⚠️ Warnings", callback_data="admin_reset_warnings")])

        if user_has_group_permission_any(user_id, group_id, ["can_resend_links", "can_recover_access"]):
            keyboard.append([InlineKeyboardButton("📩 Reenviar / recuperar link", callback_data="admin_resend_access")])

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
                [InlineKeyboardButton("🎟 Códigos y promociones", callback_data="owner_panel_codes")]
            ])


        if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]) and not owner_can_manage_payment_methods:
            keyboard.append([InlineKeyboardButton("🔗 Estado Stripe", callback_data="edit_group_stripe")])

        if owner_can_manage_payment_methods:
            keyboard.append([InlineKeyboardButton("💳 Métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")])

        if user_has_group_permission_any(user_id, group_id, ["can_view_payments", "can_manage_payments"]):
            keyboard.append([InlineKeyboardButton("💳 Pagos recibidos", callback_data=f"owner_group_payments_{group_id}")])
            keyboard.append([InlineKeyboardButton("📌 Suscripciones activas", callback_data=f"owner_group_subscriptions_{group_id}")])

    elif section == "security":

        if user_has_group_permission_any(user_id, group_id, ["can_view_logs"]):
            keyboard.append([InlineKeyboardButton("📜 Logs de accesos", callback_data=f"owner_group_logs_access_{group_id}")])

        if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):
            keyboard.append([InlineKeyboardButton("📍 Ubicación permitida", callback_data="owner_panel_location_info")])
            keyboard.append([InlineKeyboardButton("🛡 Anti-intrusos", callback_data="owner_panel_security_info")])
            keyboard.append([InlineKeyboardButton("🔗 Anti-links", callback_data="owner_panel_security_info")])

    elif section == "marketplace":

        keyboard.extend([
            [InlineKeyboardButton("✏️ Editar ficha", callback_data="edit_group_name")],
            [InlineKeyboardButton("🎬 Editar preview", callback_data="edit_group_preview")],
            [InlineKeyboardButton("👁 Preview manual/dinámico/mixto", callback_data="edit_group_preview")],
            [InlineKeyboardButton("📂 Categoría/tags", callback_data="edit_group_preview")]
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

        keyboard.extend([
            [InlineKeyboardButton("🛟 Ver solicitudes de soporte", callback_data="owner_support_tickets")],
            [InlineKeyboardButton("💬 Abrir soporte sobre esta comunidad", callback_data=f"public_support_group_{group_id}")]
        ])

    elif section == "backup":

        keyboard.extend([
            [InlineKeyboardButton("🛡 Estado backup", callback_data="owner_backup_panel")],
            [InlineKeyboardButton("🔗 Configurar origen/destino", callback_data="owner_backup_destination_token")],
            [InlineKeyboardButton("⚙️ Cambiar modo", callback_data="owner_backup_change_mode")],
            [InlineKeyboardButton("📜 Últimos mensajes copiados", callback_data="owner_backup_messages")],
            [InlineKeyboardButton("⚠️ Últimos errores", callback_data="owner_backup_errors")]
        ])

    elif section == "general":

        keyboard.extend([
            [InlineKeyboardButton("✏️ Nombre comunidad", callback_data="edit_group_name")],
            [InlineKeyboardButton("📝 Descripción", callback_data="edit_group_name")],
            [InlineKeyboardButton("🔓 Tipo gratis/pago", callback_data="owner_panel_commercial_config")],
            [InlineKeyboardButton("🔢 Cupo/configuración", callback_data="owner_panel_general_info")],
            [InlineKeyboardButton("🧹 Reiniciar configuración segura", callback_data="owner_panel_general_info")]
        ])


    keyboard.append([
        InlineKeyboardButton("❓ Ayuda", callback_data=f"owner_panel_help_{section}")
    ])

    keyboard.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return InlineKeyboardMarkup(keyboard)


OWNER_PANEL_SECTIONS = {
    "owner_panel_users": (
        "👥 Usuarios y accesos",
        "Gestiona entradas, expulsiones, bans, warnings y recuperación de acceso.",
        ["can_view_users", "can_manage_users", "can_kick_users", "can_ban_users", "can_unban_users", "can_warn_users", "can_reset_warnings", "can_resend_links", "can_recover_access"],
        "users"
    ),
    "owner_panel_codes": (
        "🎟 Códigos y promociones",
        "Crea y revisa códigos de acceso exclusivos para esta comunidad.",
        ["can_manage_codes"],
        "codes"
    ),
    "owner_panel_payments": (
        "💳 Planes y pagos del grupo",
        "Gestiona planes y métodos de pago: Stripe, PayPal, Revolut, ChangeNOW, Guardarian y promociones.",
        ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"],
        "payments"
    ),
    "owner_panel_security": (
        "🛡 Seguridad del grupo",
        "Revisa protección de acceso, anti-intrusos, anti-links y ubicación permitida.",
        ["can_manage_groups", "can_view_logs"],
        "security"
    ),
    "owner_panel_marketplace": (
        "🖼 Marketplace y preview",
        "Configura visibilidad pública, ficha, previews, categoría y tags.",
        ["can_manage_groups", "can_edit_group_texts", "can_edit_marketplace_preview"],
        "marketplace"
    ),
    "owner_panel_admins": (
        "👑 Administradores del grupo",
        "Añade admins de grupo y ajusta sus permisos por comunidad.",
        ["can_manage_admins"],
        "admins"
    ),
    "owner_panel_logs": (
        "📜 Logs y actividad del grupo",
        "Consulta accesos, pagos, códigos, backups y errores de esta comunidad.",
        ["can_view_logs"],
        "logs"
    ),
    "owner_panel_support": (
        "🛟 Solicitudes de soporte",
        "Revisa el acceso al soporte de esta comunidad sin mezclar tickets globales.",
        ["can_respond_group_support"],
        "support"
    ),
    "owner_panel_satisfaction": (
        "😊 Encuestas de comunidad",
        "Envía encuestas solo a usuarios de esta comunidad sin duplicar completados.",
        ["can_manage_groups", "can_view_logs"],
        "satisfaction"
    ),
    "owner_panel_backup": (
        "🛡 Backup premium",
        "Configura copia de seguridad de mensajes nuevos recibidos por el bot.",
        ["can_manage_groups"],
        "backup"
    ),
    "owner_panel_general": (
        "⚙️ Configuración de la comunidad",
        "Edita datos básicos, tipo de acceso y ajustes seguros de la comunidad.",
        ["can_manage_groups", "can_edit_group_texts"],
        "general"
    )
}


OWNER_PANEL_ALLOWED_REPEATED_CALLBACKS = {
    "public_back_start",
    "admin_edit_group",
    "edit_group_back",
    "back_admin",
    "back_owner",
    "owner_panel_users",
    "owner_panel_codes",
    "owner_panel_payments",
    "owner_panel_security",
    "owner_panel_marketplace",
    "owner_panel_admins",
    "owner_panel_logs",
    "owner_panel_support",
    "owner_panel_satisfaction",
    "owner_panel_backup",
    "owner_panel_general",
    "owner_panel_commercial_config",
    "owner_panel_location_info",
    "owner_panel_audit"
}


OWNER_PANEL_ALLOWED_REPEATED_PREFIXES = (
    "owner_panel_help_",
    "owner_group_logs_",
    "owner_group_users_"
)


def classify_owner_panel_repeated_callback(callback_data, placeholder_callbacks=None):

    placeholder_callbacks = placeholder_callbacks or {}

    if callback_data in OWNER_PANEL_ALLOWED_REPEATED_CALLBACKS:
        return "allowed_navigation"

    if any(callback_data.startswith(prefix) for prefix in OWNER_PANEL_ALLOWED_REPEATED_PREFIXES):
        return "allowed_navigation"

    if callback_data in placeholder_callbacks:
        return "allowed_informational"

    return "suspicious"


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


def build_owner_location_regions_keyboard(group_id):

    keyboard = []


    for slug, label in SPANISH_AUTONOMOUS_COMMUNITIES:

        if slug == "all_spain":

            continue


        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"owner_location_region_set_{group_id}_{slug}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="owner_panel_location_info")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


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


def set_group_location_rule(group_id, enabled=None, region_type=None, allowed_region=None):

    updates = []
    params = []


    if enabled is not None:

        updates.append("location_gate_enabled=%s")
        params.append(enabled)


    if region_type is not None:

        updates.append("allowed_region_type=%s")
        params.append(region_type)


    if allowed_region is not None:

        updates.append("allowed_region=%s")
        params.append(allowed_region)


    if not updates:

        return False


    params.append(group_id)

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE groups
            SET {", ".join(updates)}
            WHERE id=%s

        """, params)

        conn.commit()

    return True


def build_owner_security_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    location_enabled, region_label = get_group_location_gate_display(group_id)
    location_status = "Activada" if location_enabled else "Desactivada"

    return (
        "🛡 Seguridad del grupo\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
        "Estado actual:\n"
        "- Anti-intrusos: activo con validación de users e invite_links.\n"
        "- Links no registrados: se bloquean desde el control de entrada.\n"
        f"- Restricción por ubicación: {location_status}.\n"
        f"- Región permitida: {region_label}.\n\n"
        "Acciones disponibles ahora:\n"
        "- Gestionar ubicación permitida.\n"
        "- Revisar logs de accesos y bloqueos.\n"
        "- Gestionar usuarios/warnings desde Usuarios y accesos.\n\n"
        "Próximamente: interruptores separados para anti-links y políticas avanzadas. "
        "No aparecen como botones porque todavía no existen como configuración independiente segura."
    )


def build_owner_security_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 Gestionar ubicación", callback_data="owner_panel_location_info")],
        [InlineKeyboardButton("📜 Logs de accesos", callback_data=f"owner_group_logs_access_{group_id}")],
        [InlineKeyboardButton("👥 Usuarios y accesos", callback_data="owner_panel_users")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="owner_panel_help_security")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_users_panel_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"

    return (
        "👥 Usuarios y accesos\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
        "Desde aquí puedes revisar usuarios de esta comunidad y abrir acciones de acceso. "
        "Las acciones usan el grupo seleccionado para evitar mezclar usuarios de otras comunidades.\n\n"
        "Acciones disponibles según permisos:\n"
        "- Ver usuarios de esta comunidad.\n"
        "- Expulsar, banear o desbanear usuarios.\n"
        "- Gestionar warnings si tu rol lo permite.\n"
        "- Reenviar o recuperar enlaces de acceso."
    )


def build_owner_backup_panel_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"

    return (
        "🛡 Backup premium\n\n"
        f"Comunidad actual: {group_name or f'Grupo {group_id}'}\n\n"
        "El backup premium copia mensajes nuevos que el bot recibe, usando solo Telegram Bot API. "
        "No descarga archivos y no usa cuentas de usuario.\n\n"
        "Desde aquí puedes abrir el panel real de backup, configurar origen/destino con código, "
        "cambiar modo, revisar mensajes copiados y ver errores."
    )


def build_owner_general_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    telegram_group_id = group[2] if group else None
    access_type = "No configurado"
    public_visibility = "-"


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT is_free_group,
                       public_visibility
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            row = cur.fetchone()


        if row:

            access_type = "Gratis" if row[0] else "Pago"
            public_visibility = row[1] or "-"

    except Exception as e:

        print("Error cargando configuración general owner:", e)


    return (
        "⚙️ Configuración de la comunidad\n\n"
        f"Nombre: {group_name or f'Grupo {group_id}'}\n"
        f"ID interno: {group_id}\n"
        f"Telegram ID: {telegram_group_id or '-'}\n"
        f"Tipo de acceso: {access_type}\n"
        f"Visibilidad marketplace: {public_visibility}\n\n"
        "Esta pantalla agrupa rutas seguras de configuración. Los cambios sensibles, como pagos o visibilidad, "
        "se abren en pantallas específicas para evitar tocar checkout o accesos por accidente."
    )


def build_owner_general_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Nombre / descripción", callback_data="edit_group_name")],
        [InlineKeyboardButton("🔓 Configuración comercial", callback_data="owner_panel_commercial_config")],
        [InlineKeyboardButton("🖼 Marketplace y preview", callback_data="owner_panel_marketplace")],
        [InlineKeyboardButton("📍 Ubicación permitida", callback_data="owner_panel_location_info")],
        [InlineKeyboardButton("🛡 Seguridad del grupo", callback_data="owner_panel_security")],
        [InlineKeyboardButton("💳 Métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="owner_panel_help_general")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_commercial_config_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    is_free_group = None
    active_plans = 0
    active_payment_methods = 0


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT is_free_group
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            row = cur.fetchone()

            is_free_group = row[0] if row else None

            cur.execute("""

                SELECT COUNT(*)
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE

            """, (group_id,))
            active_plans = cur.fetchone()[0]

            cur.execute("""

                SELECT COUNT(*)
                FROM group_payment_provider_configs
                WHERE group_id=%s
                AND is_enabled=TRUE
                AND status='active'

            """, (group_id,))
            active_payment_methods = cur.fetchone()[0]

    except Exception as e:

        print("Error cargando configuración comercial owner:", e)


    access_type = "Gratis" if is_free_group is True else "Pago" if is_free_group is False else "No configurado"

    return (
        "💳 Configuración de pagos del grupo\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n"
        f"Tipo de acceso actual: {access_type}\n"
        f"Planes activos: {active_plans}\n"
        f"Métodos de pago del grupo activos: {active_payment_methods}\n\n"
        "Marcar el grupo como de pago no obliga a usar Stripe. Puedes activar uno o varios métodos de pago para cobrar tus suscripciones.\n\n"
        "💳 Pagos tradicionales\n"
        "- Stripe\n"
        "- PayPal\n"
        "- Revolut\n\n"
        "🪙 Cripto / USDT\n"
        "- ChangeNOW.io / Cripto\n"
        "- Tarjeta EUR → USDT / Guardarian\n\n"
        "🎟 Promociones\n"
        "- Códigos y promociones\n\n"
        "Guardarian permite que el comprador pague con tarjeta en euros y que tú recibas USDT en tu wallet.\n"
        "ChangeNOW sirve para pagos cripto y puede requerir revisión manual según configuración."
    )


def build_owner_commercial_config_keyboard(group_id, user_id=None):

    keyboard = []
    owner_can_manage_payment_methods = (
        user_id is not None
        and (
            is_super_admin(user_id)
            or get_group_owner_user_id(group_id) == user_id
        )
    )


    if owner_can_manage_payment_methods:

        keyboard.extend([
            [InlineKeyboardButton("💳 Stripe", callback_data="edit_group_stripe")],
            [InlineKeyboardButton("🅿️ PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")],
            [InlineKeyboardButton("🏦 Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")],
            [InlineKeyboardButton("💱 ChangeNOW.io / Cripto", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")],
            [InlineKeyboardButton("💳 Tarjeta EUR → USDT / Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")],
            [InlineKeyboardButton("💳 Ver todos los métodos", callback_data=f"owner_group_payment_methods_{group_id}")]
        ])


    keyboard.extend([
        [InlineKeyboardButton("🎟 Códigos y promociones", callback_data="owner_panel_codes")],
        [InlineKeyboardButton("📋 Ver planes", callback_data="view_group_plans")],
        [InlineKeyboardButton("➕ Crear/editar planes", callback_data="edit_group_plans")],
        [InlineKeyboardButton("🖼 Marketplace y preview", callback_data="owner_panel_marketplace")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="owner_panel_help_payments")],
        [InlineKeyboardButton("⬅️ Volver a configuración", callback_data="owner_panel_general")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_owner_panel_help_text(section):

    help_texts = {
        "users": "👥 Usuarios y accesos\n\nSirve para revisar usuarios, recuperar enlaces, expulsar, banear y gestionar warnings. Úsalo cuando un usuario tenga problemas de entrada o incumpla normas.",
        "codes": "🎟 Códigos y promociones\n\nCrea códigos de acceso para esta comunidad. Solo afectan a este grupo y no se mezclan con códigos comerciales globales.",
        "payments": "💳 Planes y pagos\n\nGestiona planes, pagos recibidos, suscripciones activas y métodos de pago del grupo. De pago no significa solo Stripe: puedes activar Stripe, PayPal, Revolut, ChangeNOW, Guardarian o códigos/promociones según tu configuración.",
        "security": "🛡 Seguridad\n\nMuestra controles de acceso, logs, anti-intrusos y ubicación. Las acciones que afectan a usuarios reales quedan en logs.",
        "marketplace": "🖼 Marketplace y preview\n\nEdita la ficha pública, previews, categoría y tags de la comunidad.",
        "admins": "👑 Administradores\n\nAñade o retira admins de grupo y define permisos concretos por comunidad.",
        "logs": "📜 Logs y actividad\n\nRevisa actividad importante de esta comunidad: accesos, pagos, códigos, soporte, backups y errores. Owner/admin solo ve su grupo.",
        "support": "🛟 Soporte\n\nMuestra tickets vinculados a esta comunidad. El owner solo ve tickets de sus grupos; el soporte global queda para super admin.",
        "satisfaction": "😊 Encuestas de comunidad\n\nEnvía encuestas solo a usuarios de esta comunidad. Por justicia, quienes ya respondieron no vuelven a recibirla por defecto.",
        "backup": "🛡 Backup premium\n\nConfigura copia de mensajes nuevos que el bot recibe. No descarga archivos ni usa cuentas usuario.",
        "general": "⚙️ Configuración general\n\nAgrupa datos básicos y opciones seguras de comunidad. Los cambios sensibles usan confirmación o pantallas específicas."
    }

    return help_texts.get(
        section,
        "🏪 Panel de comunidad\n\nGestiona esta comunidad por apartados. Usa Volver para regresar al panel y Inicio para salir."
    )


def build_owner_panel_audit_report(user_id, group_id):

    router_source = load_callback_router_source()
    handler_source = router_source.split("async def button", 1)[-1]
    menu_specs = [{
        "name": "Panel de comunidad",
        "keyboard": InlineKeyboardMarkup(build_group_settings_keyboard(user_id, group_id))
    }]


    for callback_data, (_title, _description, required_permissions, section) in OWNER_PANEL_SECTIONS.items():

        if user_has_group_permission_any(user_id, group_id, required_permissions):

            menu_specs.append({
                "name": f"Sección {section}",
                "keyboard": build_owner_section_keyboard(user_id, group_id, section)
            })


    all_buttons = []


    for menu in menu_specs:

        all_buttons.extend(
            flatten_keyboard_buttons(
                menu.get("name"),
                menu.get("keyboard")
            )
        )


    placeholder_callbacks = {
        "owner_panel_general_info": "solo informativo: configuración general avanzada pendiente",
        "edit_group_stripe": "solo informativo: Stripe propio por grupo pendiente"
    }
    editable_callbacks = {
        "owner_panel_users",
        "owner_panel_security",
        "owner_panel_backup",
        "owner_panel_general",
        "owner_panel_commercial_config",
        "owner_panel_access_type_info",
        "owner_panel_location_info",
        "owner_panel_security_info",
        "owner_support_tickets",
        "owner_panel_satisfaction",
        "owner_satisfaction_send_pending",
        "owner_satisfaction_resend_incomplete",
        "owner_satisfaction_send_never_sent",
        "owner_satisfaction_delivery_status",
        "owner_satisfaction_force_new_cycle",
        "owner_panel_logs",
        "owner_panel_codes",
        "owner_panel_payments",
        "owner_panel_admins",
        "owner_panel_marketplace"
    }
    occurrences = {}


    for button in all_buttons:

        occurrences.setdefault(button.get("callback_data"), []).append(button)


    details = []
    missing_handlers = 0
    repeated_allowed = 0
    repeated_suspicious = 0
    placeholders = 0
    editable = 0


    for button in all_buttons:

        callback_data = button.get("callback_data")
        observations = []
        state = "✅ OK"


        if not callback_has_handler(callback_data, handler_source):

            state = "❌ Problema"
            missing_handlers += 1
            observations.append("callback sin handler")


        if callback_data in placeholder_callbacks:

            if state == "✅ OK":

                state = "ℹ️ Informativo"


            placeholders += 1
            observations.append(placeholder_callbacks[callback_data])


        if callback_data in editable_callbacks or callback_data.startswith("owner_location_") or callback_data.startswith("owner_group_logs_") or callback_data.startswith("owner_group_users_"):

            editable += 1
            observations.append("funcional para esta comunidad")


        if len(occurrences.get(callback_data, [])) > 1:

            duplicate_kind = classify_owner_panel_repeated_callback(
                callback_data,
                placeholder_callbacks
            )


            if duplicate_kind == "suspicious":

                if state == "✅ OK":

                    state = "⚠️ Revisar"


                repeated_suspicious += 1
                observations.append("callback repetido sospechoso en el panel")

            elif duplicate_kind == "allowed_informational":

                repeated_allowed += 1
                observations.append("Repetido permitido: acción informativa compartida")

            else:

                repeated_allowed += 1
                observations.append("Repetido permitido: navegación común")


        required_permissions = get_required_permissions_for_callback(callback_data)

        details.append({
            "menu": button.get("menu"),
            "text": button.get("text"),
            "callback_data": callback_data,
            "state": state,
            "permissions": ", ".join(required_permissions) if required_permissions else "público/validación interna",
            "observation": "; ".join(observations) or "sin observaciones"
        })


    return {
        "group_id": group_id,
        "total_buttons": len(all_buttons),
        "missing_handlers": missing_handlers,
        "repeated_allowed": repeated_allowed,
        "repeated_suspicious": repeated_suspicious,
        "placeholders": placeholders,
        "editable": editable,
        "details": details
    }


def format_owner_panel_audit_summary(report):

    state = "✅ OK"


    if report.get("missing_handlers"):

        state = "❌ Problema"

    elif report.get("repeated_suspicious"):

        state = "⚠️ Revisar"


    return (
        "🧪 Auditoría del panel de comunidad\n\n"
        f"Estado: {state}\n"
        f"Comunidad: {report.get('group_id')}\n"
        f"Botones visibles revisados: {report.get('total_buttons')}\n"
        f"Acciones funcionales/editables detectadas: {report.get('editable')}\n"
        f"Callbacks sin handler: {report.get('missing_handlers')}\n"
        f"Callbacks repetidos permitidos/navegación: {report.get('repeated_allowed')}\n"
        f"Callbacks repetidos sospechosos: {report.get('repeated_suspicious')}\n"
        f"Acciones informativas/próximamente: {report.get('placeholders')}\n\n"
        "Usa Ver detalle para revisar botón por botón."
    )


def format_owner_panel_audit_detail(report, limit=60):

    lines = [
        "📋 Detalle auditoría comunidad",
        ""
    ]


    for index, detail in enumerate((report.get("details") or [])[:limit], start=1):

        lines.extend([
            f"{index}. {detail.get('state')} {detail.get('menu')}",
            f"Botón: {detail.get('text')}",
            f"Callback: {detail.get('callback_data')}",
            f"Permisos: {detail.get('permissions')}",
            f"Observación: {detail.get('observation')}",
            ""
        ])


    return "\n".join(lines)[:3900]


def build_owner_panel_audit_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver detalle", callback_data="owner_panel_audit_detail")],
        [InlineKeyboardButton("🔁 Repetir auditoría", callback_data="owner_panel_audit")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def fetch_owner_group_logs(group_id, category_filter=None, event_types=None, limit=30):

    rows = list_recent_events(
        limit=80,
        group_ids=[group_id]
    )


    if category_filter:

        rows = [row for row in rows if row[2] == category_filter]


    if event_types:

        rows = [row for row in rows if row[1] in event_types]


    return rows[:limit]


def build_owner_group_logs_text(group_id, rows, title):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"


    if not rows:

        return (
            f"{title}\n\n"
            f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
            "Todavía no hay actividad registrada para este filtro."
        )


    text = f"{title}\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\n"


    for created_at, event_type, category, severity, log_group_id, log_telegram_group_id, actor_user_id, target_user_id, message in rows:

        text += (
            f"Evento: {event_type or '-'}\n"
            f"Categoría: {category or '-'} / {severity or '-'}\n"
            f"Actor: {actor_user_id or '-'}\n"
            f"Usuario: {target_user_id or '-'}\n"
            f"Detalle: {message or '-'}\n"
            f"Fecha: {created_at or '-'}\n\n"
        )


    return text[:3900]


def build_owner_group_logs_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver a logs", callback_data="owner_panel_logs")],
        [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def resolve_group_user_codes_group(context, user_id, permissions, group_id=None):

    if group_id:

        try:

            group_id = int(group_id)

        except Exception:

            return None


        if not user_has_group_permission_any(user_id, group_id, permissions):

            return None


        if not set_group_user_promo_context(context, group_id):

            return None


        return group_id


    return get_selected_group_for_permissions(
        context,
        user_id,
        permissions
    )


def parse_group_user_code_group_callback(data, prefix):

    if data == prefix:

        return None


    if not data.startswith(f"{prefix}_"):

        return None


    payload = data.replace(f"{prefix}_", "", 1)


    if not payload.isdigit():

        return None


    return int(payload)


def parse_group_user_code_step_callback(data, prefix):

    payload = data.replace(prefix, "", 1).strip("_")


    if not payload:

        return None, None


    parts = payload.split("_", 1)


    if len(parts) == 2 and parts[0].isdigit():

        return int(parts[0]), parts[1]


    return None, payload


COMMERCIAL_REQUEST_FIELDS = [

    "id",
    "user_id",
    "username",
    "first_name",
    "request_type",
    "status",
    "community_name",
    "community_description",
    "telegram_group_link",
    "bot_name",
    "bot_username",
    "project_description",
    "contact_text",
    "created_at",
    "updated_at",
    "reviewed_by",
    "reviewed_at",
    "admin_notes",
    "trial_starts_at",
    "trial_ends_at",
    "payment_mode",
    "stripe_mode",
    "is_free_group",
    "approved_group_id",
    "approved_telegram_group_id",
    "approved_bot_username",
    "selected_commercial_plan_id",
    "commercial_subscription_status",
    "commercial_subscription_until",
    "requested_public_visibility",
    "creator_setup_status",
    "creator_preview_text",
    "max_groups_allowed",
    "expired_at",
    "delete_after",
    "last_expiry_reminder_at",
    "previous_public_visibility",
    "last_interaction_user_id",
    "last_interaction_username",
    "last_interaction_first_name",
    "last_interaction_at"

]


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


COMMERCIAL_REQUEST_MESSAGE_FIELDS = [

    "id",
    "commercial_request_id",
    "sender_type",
    "sender_id",
    "message_text",
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


def format_commercial_request_type(request_type):

    labels = {
        "shared_trial": "prueba comunidad compartida",
        "custom_bot": "bot personalizado",
        "support_contact": "contacto comercial"
    }

    return labels.get(request_type, request_type or "-")


def format_commercial_request_status(status):

    labels = {
        "pending": "pendiente",
        "approved": "aprobada",
        "rejected": "rechazada",
        "trial_active": "trial activo",
        "trial_expired": "trial caducado",
        "awaiting_creator_setup": "pendiente de configuración",
        "setup_in_progress": "configuración en curso",
        "setup_ready": "configuración lista",
        "awaiting_payment_setup": "pendiente de cobro",
        "awaiting_payment": "pendiente de pago",
        "active": "activa",
        "disabled": "desactivada",
        "expired_pending_reactivation": "pendiente de reactivación",
        "archived": "archivada",
        "closed": "cerrada"
    }

    return labels.get(status, status or "-")


def format_public_visibility(public_visibility):

    labels = {
        "start_home": "inicio",
        "explore_only": "explorar",
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


MARKETPLACE_CATEGORIES = [
    ("Trading", "trading"),
    ("Cripto", "cripto"),
    ("IA", "ia"),
    ("Cursos", "cursos"),
    ("Fitness", "fitness"),
    ("Gaming", "gaming"),
    ("VIP", "vip"),
    ("Otros", "otros")
]

MARKETPLACE_CATEGORY_LABELS = {
    slug: label
    for label, slug in MARKETPLACE_CATEGORIES
}

PREVIEW_MODE_LABELS = {
    "private": "sin preview público",
    "manual": "preview fijo/manual",
    "dynamic": "preview dinámico",
    "hybrid": "preview mixto"
}


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
            AND COALESCE(g.public_visibility, 'start_home')='explore_only'
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
        "🔓 Entrar gratis" if is_free_group else "💳 Ver acceso",
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
        "🔓 Entrar gratis" if group.get("is_free_group") else "💳 Ver acceso",
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
        "preview_views",
        "access_clicks",
        "favorites_count",
        "member_count",
        "created_at"
    ]

    return dict(zip(fields, row))


def get_marketplace_group_select():

    return """
        SELECT g.id,
               g.name,
               COALESCE(g.is_free_group, FALSE),
               g.preview_text,
               g.preview_file_id,
               g.preview_image_file_id,
               g.preview_video_file_id,
               g.category,
               g.tags,
               g.marketplace_badge,
               COALESCE(g.preview_mode, 'manual'),
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
               g.created_at
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
        "COALESCE(g.public_visibility, 'start_home')='explore_only'",
        marketplace_trial_visibility_filter()
    ]
    params = []


    if filter_kind == "free":

        filters.append("COALESCE(g.is_free_group, FALSE)=TRUE")


    if filter_kind == "premium":

        filters.append("COALESCE(g.is_free_group, FALSE)=FALSE")


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


def format_marketplace_kind(group):

    if group.get("is_free_group"):

        return "🔓 Gratis"


    return group.get("marketplace_badge") or "💎 Premium"


def format_marketplace_category(group):

    category = group.get("category")

    if not category:

        return "Otros"


    return MARKETPLACE_CATEGORY_LABELS.get(category, category)


def format_marketplace_card(group):

    return (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"{format_marketplace_kind(group)}"
    )


def format_marketplace_group_caption(group):

    preview_mode = group.get("preview_mode") or "manual"
    base_text = (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"⭐ {format_marketplace_number(group.get('favorites_count'))} favoritos\n"
        f"👥 {format_marketplace_number(group.get('member_count'))} miembros\n"
        f"{format_marketplace_kind(group)}"
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
        "🔓 Entrar gratis" if is_free_group else "💳 Comprar acceso",
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


def deactivate_dynamic_preview_video(video_id, group_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE group_preview_videos
            SET is_active=FALSE
            WHERE id=%s
            AND group_id=%s
            RETURNING id

        """, (
            video_id,
            group_id
        ))

        return cur.fetchone() is not None


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
    access_state = get_user_group_access_state(user_id, group_id) if user_id else None


    if access_state and should_block_new_group_purchase(access_state):

        return build_existing_group_access_keyboard(group_id, access_state)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔓 Entrar gratis" if group.get("is_free_group") else "💳 Comprar acceso",
            callback_data=f"free_access_{group_id}" if group.get("is_free_group") else f"group_{group_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver a comunidad",
            callback_data=f"marketplace_group_{group_id}"
        )]
    ])


def format_marketplace_preview_caption(group):

    preview_mode = group.get("preview_mode") or "manual"
    stats_text = (
        f"⭐ {format_marketplace_number(group.get('favorites_count'))} favoritos\n"
        f"👥 {format_marketplace_number(group.get('member_count'))} miembros"
    )


    if preview_mode == "private":

        return (
            f"🔥 {group.get('name') or 'Comunidad privada'}\n"
            f"📂 {format_marketplace_category(group)}\n"
            f"{stats_text}\n"
            f"{format_marketplace_kind(group)}"
        )


    if preview_mode == "dynamic":

        return (
            f"🔥 {group.get('name') or 'Comunidad privada'}\n"
            f"📂 {format_marketplace_category(group)}\n"
            f"{stats_text}\n"
            f"{format_marketplace_kind(group)}\n\n"
            "⚡ Preview dinámico activo. Se mostrarán los últimos 3 vídeos publicados en la comunidad desde que el owner lo activó."
        )


    text = (
        f"🔥 {group.get('name') or 'Comunidad privada'}\n"
        f"📂 {format_marketplace_category(group)}\n"
        f"{stats_text}\n"
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
    caption = append_existing_group_access_notice(
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
    caption = append_existing_group_access_notice(
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


def build_preview_mode_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📝 Preview fijo/manual",
            callback_data=f"creator_preview_mode_set_{request_id}_manual"
        )],
        [InlineKeyboardButton(
            "⚡ Preview dinámico: últimos 3 vídeos",
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
            "⬅️ Volver",
            callback_data=f"creator_setup_marketplace_{request_id}"
        )]
    ])


def build_group_preview_mode_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📝 Preview manual",
            callback_data="edit_group_preview_mode_manual"
        )],
        [InlineKeyboardButton(
            "⚡ Preview dinámico",
            callback_data="edit_group_preview_mode_dynamic"
        )],
        [InlineKeyboardButton(
            "💎 Preview mixto",
            callback_data="edit_group_preview_mode_hybrid"
        )],
        [InlineKeyboardButton(
            "🔒 Sin preview público",
            callback_data="edit_group_preview_mode_private"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="edit_group_back"
        )]
    ])


def preview_mode_selection_text():

    return (
        "¿Qué tipo de preview quieres para este grupo?\n\n"
        "📝 Manual:\n"
        "Subes una imagen o vídeo fijo que verán los usuarios antes de entrar.\n\n"
        "⚡ Dinámico:\n"
        "El bot mostrará los últimos 3 vídeos publicados en el grupo desde que actives este modo.\n\n"
        "💎 Mixto:\n"
        "Muestra primero el preview manual y además permite ver los últimos vídeos dinámicos.\n\n"
        "🔒 Sin preview:\n"
        "No se mostrará contenido previo, solo la ficha del grupo."
    )


def build_preview_category_keyboard(request_id):

    keyboard = [
        [InlineKeyboardButton(
            label,
            callback_data=f"creator_preview_category_set_{request_id}_{slug}"
        )]
        for label, slug in MARKETPLACE_CATEGORIES
    ]

    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_marketplace_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_creator_marketplace_text(group_id):

    text = (
        "👁 Preview marketplace\n\n"
        "¿Qué tipo de preview quieres mostrar?\n\n"
        "📝 Preview fijo/manual: texto, imagen, vídeo teaser, categoría y tags.\n\n"
        "⚡ Preview dinámico: muestra los últimos 3 vídeos publicados después de activarlo. El bot no descarga vídeos; solo guarda el file_id de Telegram.\n\n"
        "💎 Preview mixto: combina tu teaser manual con los últimos vídeos dinámicos si existen.\n\n"
        "🔒 Sin preview público: muestra una ficha mínima sin enseñar contenido."
    )


    if not group_id:

        return (
            f"{text}\n\n"
            "Estado: pendiente de grupo/canal vinculado.\n"
            "Primero vincula un grupo real para guardar imagen, vídeo, categoría y tags."
        )


    group = fetch_marketplace_group(group_id)


    if not group:

        return f"{text}\n\nEstado: comunidad no disponible o pendiente de publicación."


    return (
        f"{text}\n\n"
        f"Nivel de preview: {PREVIEW_MODE_LABELS.get(group.get('preview_mode'), group.get('preview_mode') or 'manual')}\n"
        f"Texto preview: {'configurado' if group.get('preview_text') else 'pendiente'}\n"
        f"Imagen preview: {'configurada' if group.get('preview_image_file_id') else 'pendiente'}\n"
        f"Vídeo preview: {'configurado' if group.get('preview_video_file_id') else 'pendiente'}\n"
        f"Categoría: {format_marketplace_category(group)}\n"
        f"Tags: {group.get('tags') or 'pendiente'}"
    )


def set_group_preview_mode(group_id, preview_mode):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE groups
            SET preview_mode=%s
            WHERE id=%s

        """, (
            preview_mode,
            group_id
        ))

        conn.commit()


def group_has_manual_preview(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT preview_text,
                   preview_file_id,
                   preview_image_file_id,
                   preview_video_file_id
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,))

        row = cur.fetchone()


    if not row:

        return False


    return any(row)


def format_owner_dynamic_videos_text(group_id):

    videos = fetch_dynamic_preview_videos(group_id, limit=10)


    if not videos:

        return (
            "🎬 Vídeos guardados\n\n"
            "Todavía no hay vídeos guardados. Solo se guardarán vídeos publicados en el grupo después de activar el preview dinámico."
        )


    lines = ["🎬 Vídeos guardados"]


    for index, video in enumerate(videos, start=1):

        caption = video.get("caption") or "sin caption"


        if len(caption) > 80:

            caption = caption[:77] + "..."


        lines.append(
            "\n"
            f"{index}. ID interno: {video.get('id')}\n"
            f"Mensaje: {video.get('message_id') or '-'}\n"
            f"Caption: {caption}"
        )


    return "\n".join(lines)


def build_dynamic_video_delete_keyboard(request_id, group_id):

    videos = fetch_dynamic_preview_videos(group_id, limit=10)
    keyboard = []


    for index, video in enumerate(videos, start=1):

        keyboard.append([InlineKeyboardButton(
            f"🗑 Borrar vídeo {index}",
            callback_data=f"creator_dynamic_preview_delete_video_{request_id}_{video.get('id')}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_marketplace_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def format_commercial_datetime(value):

    if not value:

        return "-"


    try:

        return value.strftime("%Y-%m-%d %H:%M")

    except Exception:

        return str(value)


def get_commercial_request_title(request_row):

    return (
        request_row.get("community_name")
        or request_row.get("bot_name")
        or request_row.get("project_description")
        or "-"
    )


def get_owner_groups_summary(user_id):

    if not user_id:

        return 0, "Sin grupos"


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT g.name
                FROM admins a
                JOIN groups g
                ON g.id=a.group_id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                ORDER BY g.name ASC

            """, (user_id,))

            names = [
                row[0] or "Sin nombre"
                for row in cur.fetchall()
            ]

    except Exception as e:

        print("Error cargando grupos del propietario:", e)

        names = []


    if not names:

        return 0, "Sin grupos"


    shown = ", ".join(names[:3])

    if len(names) > 3:

        shown += f" +{len(names) - 3} más"


    return len(names), shown


def build_owner_groups_detail_text(request_row):

    user_id = request_row.get("user_id") if request_row else None

    if not user_id:

        return "🏪 Grupos del propietario\n\nNo hay usuario asociado a esta solicitud."


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT g.id, g.name, g.telegram_group_id, COALESCE(g.is_active, TRUE)
                FROM groups g
                JOIN admins a
                ON a.group_id = g.id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                ORDER BY g.name ASC

            """, (user_id,))

            rows = cur.fetchall()

    except Exception as e:

        print("Error cargando detalle de grupos del propietario:", e)

        rows = []


    if not rows:

        return "🏪 Grupos del propietario\n\nEste propietario todavía no tiene grupos vinculados."


    lines = [
        "🏪 Grupos del propietario",
        "",
        format_owner_request_card(request_row)
    ]


    for group_id, name, telegram_group_id, is_active in rows:

        lines.append(
            "\n"
            f"Grupo: {name or 'Sin nombre'}\n"
            f"ID interno: {group_id}\n"
            f"Telegram ID: {telegram_group_id or '-'}\n"
            f"Estado: {'activo' if is_active else 'inactivo'}"
        )


    return "\n".join(lines)


def format_owner_request_card(request_row):

    username = request_row.get("username") or "Sin username"

    if username != "Sin username" and not username.startswith("@"):

        username = f"@{username}"


    first_name = request_row.get("first_name") or "Sin nombre disponible"
    user_id = request_row.get("user_id")
    status = request_row.get("status") or "-"
    max_groups, _quota_source = get_creator_group_quota_source(user_id, request_row)
    used_groups, group_names = get_owner_groups_summary(user_id)
    trial_until = request_row.get("trial_ends_at")
    subscription_until = request_row.get("commercial_subscription_until")
    last_activity = (
        request_row.get("last_interaction_at")
        or request_row.get("updated_at")
        or request_row.get("created_at")
    )

    trial_text = "inactivo"
    if status == "trial_active":
        trial_text = f"activo hasta {format_commercial_datetime(trial_until)}"

    commercial_text = "activo" if status == "active" else "inactivo"
    if subscription_until:
        commercial_text = f"{commercial_text} hasta {format_commercial_datetime(subscription_until)}"

    return (
        f"👤 Nombre: {first_name} {username}\n"
        f"🆔 Usuario: {user_id or '-'}\n"
        f"📌 Estado: {format_commercial_request_status(status)}\n"
        f"📦 Cupo: {used_groups}/{max_groups}\n"
        f"🧪 Trial: {trial_text}\n"
        f"💳 Comercial: {commercial_text}\n"
        f"🏪 Grupos: {used_groups} · {group_names}\n"
        f"🕒 Última actividad: {format_commercial_datetime(last_activity)}"
    )


def format_owner_request_button_label(request_row, prefix="👁 Ver"):

    first_name = request_row.get("first_name") or "Sin nombre"
    username = request_row.get("username") or "Sin username"

    if username != "Sin username" and not username.startswith("@"):

        username = f"@{username}"


    return (
        f"{prefix} · {first_name} {username} "
        f"#{request_row.get('id')}"
    )[:64]


def fetch_pending_commercial_requests():

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status='pending'
            ORDER BY created_at ASC
            LIMIT 10

        """)

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def fetch_archived_commercial_requests():

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status IN ('archived', 'closed')
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 20

        """)

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def fetch_commercial_requests_by_statuses(statuses, limit=20):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status = ANY(%s)
            ORDER BY updated_at DESC, created_at DESC
            LIMIT %s

        """, (statuses, limit))

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def build_commercial_status_list_text(title, requests):

    if not requests:

        return f"{title}\n\nNo hay solicitudes en esta vista."


    lines = [title]


    for request_row in requests:

        lines.append("\n" + format_owner_request_card(request_row))


    return "\n".join(lines)


def build_commercial_status_list_keyboard(requests, back_callback="admin_owners_panel"):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "👁 Ver estado"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton("🧑‍💼 Propietarios", callback_data=back_callback)
    ])

    keyboard.append([
        InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")
    ])

    return keyboard


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


def archive_commercial_request(request_id, archived_by):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='archived',
                reviewed_by=COALESCE(reviewed_by, %s),
                reviewed_at=COALESCE(reviewed_at, NOW()),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            archived_by,
            request_id
        ))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def reopen_archived_commercial_request(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='setup_ready',
                updated_at=NOW()
            WHERE id=%s
            AND status IN ('archived', 'closed')
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()


    return row_to_commercial_request(row)


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


def fetch_commercial_request_messages(request_id, limit=10):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_MESSAGE_FIELDS)}
            FROM commercial_request_messages
            WHERE commercial_request_id=%s
            ORDER BY created_at DESC, id DESC
            LIMIT %s

        """, (
            request_id,
            limit
        ))

        rows = cur.fetchall()


    messages = [
        row_to_commercial_request_message(row)
        for row in rows
    ]

    return list(reversed(messages))


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
                        is_free_group=%s
                    WHERE id=%s

                """, (
                    public_visibility,
                    request_row.get("is_free_group") is True
                    or request_row.get("payment_mode") == "free",
                    group_id
                ))


        else:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups
                    SET is_free_group=%s
                    WHERE id=%s

                """, (
                    request_row.get("is_free_group") is True
                    or request_row.get("payment_mode") == "free",
                    group_id
                ))


    return assigned, group_id


def get_group_payment_settings(request_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT is_configured,
                   owner_stripe_secret_key,
                   owner_stripe_webhook_secret,
                   owner_stripe_publishable_key
            FROM group_payment_settings
            WHERE commercial_request_id=%s
            LIMIT 1

        """, (request_id,))

        return cur.fetchone()


def get_creator_plan_count(group_id):

    if not group_id:

        return 0


    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*)
            FROM plans
            WHERE group_id=%s
            AND is_active=TRUE

        """, (group_id,))

        return cur.fetchone()[0]


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
        "stripe": "creator_setup_waiting_stripe_secret",
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


def build_creator_setup_summary(request_row):

    request_id = request_row.get("id")
    assigned, group_id = assign_owner_for_commercial_request(request_row)


    if group_id and not assigned:

        owner_status = "pendiente"

    elif group_id:

        owner_status = "asignado"

    else:

        owner_status = "pendiente"


    payment_settings = get_group_payment_settings(request_id)
    stripe_status = "configurado" if payment_settings and payment_settings[0] else "pendiente"
    plan_count = get_creator_plan_count(group_id)
    group_status = "configurado" if group_id else "pendiente"
    texts_status = (
        "configurado"
        if request_row.get("community_name")
        and request_row.get("community_description")
        else "pendiente"
    )
    visibility = format_public_visibility(
        request_row.get("requested_public_visibility")
    )
    location_enabled, region_label = get_group_location_gate_display(group_id)
    location_status = "Activada" if location_enabled else "Desactivada"
    setup_ready = (
        group_status == "configurado"
        and texts_status == "configurado"
        and (
            request_row.get("payment_mode") != "paid"
            or (
                stripe_status == "configurado"
                and plan_count > 0
            )
        )
    )
    setup_status = "setup_ready" if setup_ready else "setup_in_progress"


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE commercial_requests
            SET creator_setup_status=%s,
                updated_at=NOW()
            WHERE id=%s

        """, (
            setup_status,
            request_id
        ))


    return (
        "✅ Revisar configuración\n\n"
        f"Grupo/canal: {group_status}\n"
        f"Textos: {texts_status}\n"
        f"Stripe propio: {stripe_status}\n"
        f"Planes: {plan_count}\n"
        f"Visibilidad: {visibility}\n"
        f"📍 Ubicación: {location_status}\n"
        f"Región permitida: {region_label}\n"
        f"Estado owner: {owner_status}\n"
        f"Estado setup: {setup_status}\n\n"
        "El checkout real con Stripe del creador todavía está pendiente de conectar."
    )


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


def build_admin_trial_visibility_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🏠 Publicar en inicio",
            callback_data=f"admin_trial_visibility_start_home_{request_id}"
        )],

        [InlineKeyboardButton(
            "🔎 Publicar en explorar",
            callback_data=f"admin_trial_visibility_explore_only_{request_id}"
        )],

        [InlineKeyboardButton(
            "🙈 Dejar oculta/borrador",
            callback_data=f"admin_trial_visibility_hidden_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"admin_commercial_review_{request_id}"
        )]

    ]


def build_commercial_requests_text(requests):

    if not requests:

        return (
            "📩 Solicitudes comerciales\n\n"
            "No hay solicitudes pendientes."
        )


    lines = [
        "🕓 Solicitudes pendientes\n\n"
        "Gestiona aquí a los dueños de comunidades: solicitudes, pruebas, cupos, grupos y estado comercial."
    ]


    for request_row in requests:

        lines.append(
            "\n"
            f"{format_owner_request_card(request_row)}\n"
            f"Tipo: {format_commercial_request_type(request_row.get('request_type'))}\n"
            f"Solicitud: {get_commercial_request_title(request_row)}\n"
            f"Contacto: {request_row.get('contact_text') or '-'}"
        )


    return "\n".join(lines)


def build_commercial_requests_keyboard(requests):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "📄 Ver detalle"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "📁 Solicitudes archivadas",
            callback_data="admin_commercial_archived_requests"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_archived_commercial_requests_text(requests):

    if not requests:

        return (
            "📁 Solicitudes archivadas\n\n"
            "No hay solicitudes archivadas."
        )


    lines = [
        "📁 Archivados\n\n"
        "Solicitudes finalizadas o cerradas sin borrar sus datos."
    ]


    for request_row in requests:

        lines.append("\n" + format_owner_request_card(request_row))


    return "\n".join(lines)


def build_archived_commercial_requests_keyboard(requests):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "👁 Ver estado"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_request_detail_text(request_row):

    username = request_row.get("username") or "-"
    profile_quota, quota_source = get_creator_group_quota_source(
        request_row.get("user_id"),
        request_row
    )

    if username != "-" and not username.startswith("@"):

        username = f"@{username}"


    return (
        "📩 Solicitud comercial\n\n"
        f"{format_owner_request_card(request_row)}\n\n"
        f"ID: {request_row.get('id')}\n"
        f"Estado: {request_row.get('status') or '-'}\n"
        f"Tipo: {format_commercial_request_type(request_row.get('request_type'))}\n"
        f"Usuario: {request_row.get('user_id') or '-'}\n"
        f"Username: {username}\n"
        f"Nombre Telegram: {request_row.get('first_name') or '-'}\n\n"
        f"Comunidad/proyecto: {request_row.get('community_name') or '-'}\n"
        f"Descripción comunidad: {request_row.get('community_description') or '-'}\n"
        f"Link grupo/canal: {request_row.get('telegram_group_link') or '-'}\n"
        f"Nombre bot: {request_row.get('bot_name') or '-'}\n"
        f"Username bot: {request_row.get('bot_username') or '-'}\n"
        f"Descripción proyecto: {request_row.get('project_description') or '-'}\n"
        f"Contacto: {request_row.get('contact_text') or '-'}\n\n"
        f"Creada: {format_commercial_datetime(request_row.get('created_at'))}\n"
        f"Revisada por: {request_row.get('reviewed_by') or '-'}\n"
        f"Revisada: {format_commercial_datetime(request_row.get('reviewed_at'))}\n"
        f"Inicio prueba: {format_commercial_datetime(request_row.get('trial_starts_at'))}\n"
        f"Fin prueba: {format_commercial_datetime(request_row.get('trial_ends_at'))}\n"
        f"Modo pago: {request_row.get('payment_mode') or '-'}\n"
        f"Modo Stripe: {request_row.get('stripe_mode') or '-'}\n"
        f"Grupo vinculado: {request_row.get('approved_group_id') or '-'}\n"
        f"Telegram group ID: {request_row.get('approved_telegram_group_id') or '-'}\n"
        f"Ubicación pública solicitada: {format_public_visibility(request_row.get('requested_public_visibility'))}\n"
        f"Estado configuración creador: {request_row.get('creator_setup_status') or '-'}\n"
        f"Preview creador: {request_row.get('creator_preview_text') or '-'}\n"
        f"Cupo actual del creator: {profile_quota}\n"
        f"Cupo de esta solicitud: {request_row.get('max_groups_allowed') or 1}\n"
        f"Fuente de cupo: {quota_source}\n"
        f"Último user_id interacción: {request_row.get('last_interaction_user_id') or '-'}\n"
        f"Último username interacción: {request_row.get('last_interaction_username') or '-'}\n"
        f"Último nombre interacción: {request_row.get('last_interaction_first_name') or '-'}\n"
        f"Última interacción: {format_commercial_datetime(request_row.get('last_interaction_at'))}\n"
        f"Plan comercial: {request_row.get('selected_commercial_plan_id') or '-'}\n"
        f"Estado suscripción comercial: {request_row.get('commercial_subscription_status') or '-'}\n"
        f"Suscripción comercial hasta: {format_commercial_datetime(request_row.get('commercial_subscription_until'))}"
    )


def build_commercial_contact_button(request_row):

    return InlineKeyboardButton(
        "💬 Hablar con solicitante",
        callback_data=f"admin_commercial_chat_{request_row.get('id')}"
    )


def build_commercial_advanced_review_keyboard(request_row):

    request_id = request_row.get("id")
    keyboard = []
    contact_button = build_commercial_contact_button(request_row)


    keyboard.append([contact_button])


    keyboard.append([
        InlineKeyboardButton(
            "📄 Ver detalle completo",
            callback_data=f"admin_commercial_status_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🏪 Ver sus grupos",
            callback_data=f"admin_commercial_owner_groups_{request_id}"
        )
    ])

    if not is_commercial_request_archived(request_row):

        keyboard.append([
            InlineKeyboardButton(
                "🔢 Cambiar cupo",
                callback_data=f"admin_commercial_group_limit_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "🗄 Finalizar solicitud",
                callback_data=f"admin_commercial_archive_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "📝 Añadir nota interna",
                callback_data=f"admin_commercial_internal_note_{request_id}"
            )
        ])

    else:

        keyboard.append([
            InlineKeyboardButton(
                "📁 Archivada",
                callback_data=f"admin_commercial_status_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "♻️ Reabrir solicitud",
                callback_data=f"admin_commercial_reopen_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_archive_confirm_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Confirmar archivo",
            callback_data=f"admin_commercial_archive_confirm_{request_id}"
        )],
        [InlineKeyboardButton(
            "❌ Cancelar",
            callback_data=f"admin_commercial_archive_cancel_{request_id}"
        )]
    ])


def build_commercial_pending_review_keyboard(request_row):

    request_id = request_row.get("id")
    request_type = request_row.get("request_type")
    keyboard = [
        [build_commercial_contact_button(request_row)]
    ]

    keyboard.append([
        InlineKeyboardButton(
            "📄 Ver detalle completo",
            callback_data=f"admin_commercial_status_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🏪 Ver sus grupos",
            callback_data=f"admin_commercial_owner_groups_{request_id}"
        )
    ])


    if request_type == "shared_trial":

        keyboard.append([
            InlineKeyboardButton(
                "✅ Aprobar prueba",
                callback_data=f"admin_commercial_approve_trial_{request_id}"
            )
        ])

    elif request_type == "custom_bot":

        keyboard.append([
            InlineKeyboardButton(
                "✅ Aprobar personalizada",
                callback_data=f"admin_commercial_approve_custom_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "❌ Rechazar",
            callback_data=f"admin_commercial_reject_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "📦 Cambiar cupo",
            callback_data=f"admin_commercial_group_limit_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "📝 Añadir nota interna",
            callback_data=f"admin_commercial_internal_note_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_review_keyboard(request_row):

    if is_commercial_request_advanced(request_row):

        return build_commercial_advanced_review_keyboard(request_row)


    return build_commercial_pending_review_keyboard(request_row)


def build_commercial_request_chat_text(request_row, messages):

    request_id = request_row.get("id")
    title = get_commercial_request_title(request_row)


    lines = [
        "💬 Chat de solicitud comercial",
        "",
        f"Solicitud: #{request_id}",
        f"Solicitante: {request_row.get('user_id') or '-'}",
        f"Proyecto: {title}",
        ""
    ]


    if not messages:

        lines.append("Todavía no hay mensajes en esta conversación.")

    else:

        lines.append("Historial reciente:")


        for message in messages:

            sender_label = (
                "Admin"
                if message.get("sender_type") == "admin"
                else "Solicitante"
            )
            created_at = format_commercial_datetime(message.get("created_at"))
            text = (message.get("message_text") or "").strip()

            lines.append(
                "\n"
                f"{sender_label} · {created_at}\n"
                f"{text}"
            )


    return "\n".join(lines)


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


def build_commercial_group_limit_text(request_row):

    profile_quota, quota_source = get_creator_group_quota_source(
        request_row.get("user_id"),
        request_row
    )

    return (
        "🔢 Cupo de grupos\n\n"
        f"Solicitud: #{request_row.get('id')}\n"
        f"Creador: {request_row.get('user_id') or '-'}\n"
        f"Cupo actual del creator: {profile_quota}\n"
        f"Cupo de esta solicitud: {request_row.get('max_groups_allowed') or 1}\n"
        f"Fuente: {quota_source}\n\n"
        "Elige el máximo de comunidades que este creador puede añadir."
    )


def build_commercial_group_limit_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "1 grupo",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_1"
        )],

        [InlineKeyboardButton(
            "2 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_2"
        )],

        [InlineKeyboardButton(
            "5 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_5"
        )],

        [InlineKeyboardButton(
            "10 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_10"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"admin_commercial_review_{request_id}"
        )]

    ]


COMMERCIAL_PROMO_DURATIONS = {
    "15d": (15, "15 días"),
    "1m": (30, "1 mes"),
    "3m": (90, "3 meses"),
    "1y": (365, "1 año")
}


def generate_commercial_promo_code():

    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(
        secrets.choice(alphabet)
        for _ in range(8)
    )

    return f"OWNER-{suffix}"


def create_commercial_promo_code(duration_days, created_by):

    for _ in range(5):

        code = generate_commercial_promo_code()

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO commercial_promo_codes
                    (
                        code,
                        duration_days,
                        max_uses,
                        uses_count,
                        is_active,
                        created_by,
                        updated_at
                    )
                    VALUES (%s, %s, 1, 0, TRUE, %s, NOW())
                    RETURNING id, code, duration_days

                """, (
                    code,
                    duration_days,
                    created_by
                ))

                return cur.fetchone()

        except Exception as e:

            print("Error creando código promocional comercial:", e)


    return None


def fetch_active_commercial_promo_codes():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   code,
                   duration_days,
                   max_uses,
                   uses_count,
                   created_by,
                   created_at
            FROM commercial_promo_codes
            WHERE is_active=TRUE
            AND uses_count < max_uses
            ORDER BY created_at DESC
            LIMIT 20

        """)

        return cur.fetchall()


def deactivate_commercial_promo_code(code_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE commercial_promo_codes
            SET is_active=FALSE,
                updated_at=NOW()
            WHERE id=%s
            RETURNING code

        """, (code_id,))

        row = cur.fetchone()

    return row[0] if row else None


def format_commercial_promo_duration(days):

    if days == 15:

        return "15 días"

    if days == 30:

        return "1 mes"

    if days == 90:

        return "3 meses"

    if days == 365:

        return "1 año"

    return f"{days} días"


def build_commercial_promo_codes_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Crear código 15 días",
            callback_data="admin_commercial_promo_create_15d"
        )],
        [InlineKeyboardButton(
            "Crear código 1 mes",
            callback_data="admin_commercial_promo_create_1m"
        )],
        [InlineKeyboardButton(
            "Crear código 3 meses",
            callback_data="admin_commercial_promo_create_3m"
        )],
        [InlineKeyboardButton(
            "Crear código 1 año",
            callback_data="admin_commercial_promo_create_1y"
        )],
        [InlineKeyboardButton(
            "Ver códigos activos",
            callback_data="admin_commercial_promo_active"
        )],
        [InlineKeyboardButton(
            "Desactivar código",
            callback_data="admin_commercial_promo_deactivate_menu"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_back_main"
        )]
    ])


def build_commercial_promo_active_text(rows):

    if not rows:

        return "🎟 Códigos promocionales\n\nNo hay códigos activos."


    lines = ["🎟 Códigos promocionales activos"]


    for row in rows:

        code_id, code, duration_days, max_uses, uses_count, created_by, created_at = row
        lines.append(
            "\n"
            f"ID: {code_id}\n"
            f"Código: {code}\n"
            f"Duración: {format_commercial_promo_duration(duration_days)}\n"
            f"Usos: {uses_count}/{max_uses}\n"
            f"Creado por: {created_by or '-'}\n"
            f"Fecha: {format_commercial_datetime(created_at)}"
        )


    return "\n".join(lines)


def build_commercial_promo_deactivate_keyboard(rows):

    keyboard = []


    for row in rows:

        code_id, code, *_rest = row
        keyboard.append([InlineKeyboardButton(
            f"Desactivar {code}",
            callback_data=f"admin_commercial_promo_deactivate_{code_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="admin_commercial_promo_codes"
    )])

    return InlineKeyboardMarkup(keyboard)


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

    try:

        return int(data.replace(prefix, "", 1))

    except Exception:

        return None


def extract_commercial_group_limit_selection(data):

    prefix = "admin_commercial_set_group_limit_"


    try:

        raw_value = data.replace(prefix, "", 1)
        request_id_text, limit_text = raw_value.rsplit("_", 1)
        request_id = int(request_id_text)
        limit = int(limit_text)

    except Exception:

        return None, None


    if limit not in (1, 2, 5, 10):

        return None, None


    return request_id, limit


def update_commercial_request_group_limit(request_id, max_groups_allowed):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET max_groups_allowed=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            max_groups_allowed,
            request_id
        ))

        row = cur.fetchone()


    request_row = row_to_commercial_request(row)


    if request_row:

        set_creator_group_quota(
            request_row.get("user_id"),
            max_groups_allowed,
            request_row.get("status")
        )

        with conn.cursor() as cur:

            cur.execute(f"""

                UPDATE commercial_requests
                SET max_groups_allowed=%s,
                    updated_at=NOW()
                WHERE user_id=%s
                RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

            """, (
                max_groups_allowed,
                request_row.get("user_id")
            ))


    return request_row


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


def update_commercial_request_custom_approved(request_id, reviewer_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='awaiting_payment',
                reviewed_by=%s,
                reviewed_at=NOW(),
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


def update_commercial_request_rejected(request_id, reviewer_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='rejected',
                reviewed_by=%s,
                reviewed_at=NOW(),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, request_id))

        row = cur.fetchone()


    return row_to_commercial_request(row)


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
                SET is_free_group=TRUE
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
                SET is_free_group=FALSE
                WHERE id=%s

            """, (request_row.get("approved_group_id"),))


    return row_to_commercial_request(row)


def update_commercial_request_access_type(request_id, payment_mode):

    is_free = payment_mode == "free"


    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET payment_mode=%s,
                is_free_group=%s,
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            payment_mode,
            is_free,
            request_id
        ))

        row = cur.fetchone()
        request_row = row_to_commercial_request(row)


        if request_row and request_row.get("approved_group_id"):

            cur.execute("""

                UPDATE groups
                SET is_free_group=%s
                WHERE id=%s

            """, (
                is_free,
                request_row.get("approved_group_id")
            ))


    return request_row


def build_access_type_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔓 Comunidad gratuita",
            callback_data=f"creator_setup_access_free_{request_id}"
        )],
        [InlineKeyboardButton(
            "💎 Comunidad de pago",
            callback_data=f"creator_setup_access_paid_{request_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"configure_community_{request_id}"
        )]
    ])


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


def build_owner_support_ticket_keyboard(ticket):

    ticket_id = ticket.get("id") if isinstance(ticket, dict) else ticket
    ticket_status = ticket.get("status") if isinstance(ticket, dict) else None
    keyboard = []


    if ticket_status != "closed":

        keyboard.append([InlineKeyboardButton("✍️ Responder", callback_data=f"owner_support_reply_{ticket_id}")])
        keyboard.append([InlineKeyboardButton("🤖 Sugerir respuesta", callback_data=f"owner_support_ai_{ticket_id}")])
        keyboard.append([InlineKeyboardButton("✅ Cerrar ticket", callback_data=f"owner_support_close_{ticket_id}")])


    keyboard.append([InlineKeyboardButton("⬅️ Volver a soporte de comunidad", callback_data="owner_support_tickets")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return keyboard


def build_support_ticket_keyboard(ticket):

    if isinstance(ticket, dict):

        ticket_id = ticket.get("id")
        ticket_status = ticket.get("status")

    else:

        ticket_id = ticket
        ticket_status = None


    if ticket_status == "closed":

        return [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="admin_support_tickets"
            )]

        ]


    return [

        [InlineKeyboardButton(
            "✍️ Responder",
            callback_data=f"admin_support_reply_{ticket_id}"
        )],

        [InlineKeyboardButton(
            "🤖 Sugerir respuesta",
            callback_data=f"admin_support_ai_{ticket_id}"
        )],

        [InlineKeyboardButton(
            "✅ Cerrar ticket",
            callback_data=f"admin_support_close_{ticket_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_support_tickets"
        )]

    ]


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


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT name,
                       telegram_group_id
                FROM groups
                WHERE id=%s
                AND is_active=TRUE
                AND COALESCE(is_free_group, FALSE)=TRUE
                LIMIT 1

            """, (group_id,))

            group_row = cur.fetchone()


            if not group_row:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Comunidad gratuita no encontrada o no disponible.",
                    reply_markup=build_group_recovery_keyboard(group_id)
                )

                return


            group_name, telegram_group_id = group_row

            increment_community_stat(group_id, "access_clicks")

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )
                AND is_active=TRUE

            """, (
                user_id,
                group_id,
                telegram_group_id,
                telegram_group_id
            ))

            old_links = cur.fetchall()


        for (old_link,) in old_links:

            try:

                revoke_telegram_invite_link(
                    TOKEN,
                    telegram_group_id,
                    old_link
                )

            except Exception as e:

                print("Error revocando link gratuito anterior:", e)


        link = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=180,
            member_limit=1
        )


        if not link:

            log_event(
                "free_access_invite_link_error",
                category="access",
                severity="warning",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="No se pudo crear enlace de acceso gratuito."
            )

            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Error creando acceso.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        username = telegram_user.username
        first_name = telegram_user.first_name


        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (
                user_id,
                group_id,
                telegram_group_id,
                telegram_group_id
            ))

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, telegram_group_id, invite_link, is_active)
                VALUES (%s, %s, %s, %s, TRUE)

            """, (
                user_id,
                group_id,
                telegram_group_id,
                link
            ))

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
            "✅ Acceso gratuito concedido.\n\n"
            "Este enlace es personal y de un solo uso.\n"
            "No lo compartas.\n\n"
            f"{link}"
        ),
        reply_markup=ReplyKeyboardRemove()
    )


async def create_checkout_for_user(context, chat_id, user_id, group_id, price_id):

    access_state = await resolve_group_access_state_for_user(context, user_id, group_id)


    if should_block_new_group_purchase(access_state):

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
                "group_id": group_id

            }

        )

        payment_url = response.json()["url"]


        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💳 Paga aquí:\n{payment_url}",
            reply_markup=ReplyKeyboardRemove()
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
            text="❌ Error creando pago",
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

            await context.bot.send_message(
                chat_id=chat_id,
                text=response_data.get("error") or "PayPal no está disponible para esta comunidad.",
                reply_markup=build_group_recovery_keyboard(group_id)
            )

            return


        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🅿️ Paga con PayPal aquí:\n"
                f"{response_data['url']}\n\n"
                "El acceso se enviará cuando PayPal confirme el pago por webhook verificado."
            ),
            reply_markup=ReplyKeyboardRemove()
        )

    except Exception as e:

        log_event(
            "paypal_group_checkout_creation_error",
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
            text="❌ Error creando pago PayPal",
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
            text="❌ Error creando pago Revolut",
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
                [InlineKeyboardButton("🛟 Contactar soporte", callback_data=f"support_group_{group_id}")],
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
            text="❌ Error creando pago ChangeNOW",
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
                [InlineKeyboardButton("🛟 Contactar soporte", callback_data=f"support_group_{group_id}")],
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
            text="❌ Error creando pago Guardarian",
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
    _enabled, allowed_region, region_type = get_group_location_gate(group_id)
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

        clear_location_gate_state(context)

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⛔ No he podido validar tu ubicación para esta comunidad.\n\n"
                f"Región permitida: {region_label}\n"
                f"Detectado: {detected_label}\n"
                f"Motivo: {reason_message}\n\n"
                "Asegúrate de pulsar el botón de ubicación de Telegram, no escribir la ciudad manualmente."
                f"{boundary_text}"
            ),
            reply_markup=ReplyKeyboardRemove()
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="Si estás dentro de la zona permitida y crees que es un error, contacta con soporte.",
            reply_markup=build_location_denied_keyboard()
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

        except Exception as e:

            print("Error obteniendo grupo para reintentar verificación:", e)
            group_name = str(telegram_group_id)


        asyncio.create_task(
            verificar_admin_despues(
                telegram_group_id,
                group_name,
                context.bot.id,
                context,
                user_id,
                query.from_user.username,
                query.from_user.first_name
            )
        )

        await query.message.reply_text(
            "🔁 Reintentando verificación.\n\n"
            "Comprobaré de nuevo si el bot ya tiene permisos de administrador."
        )

        return


    if data.startswith("confirm_creator_group_link_"):

        try:

            pending_id = int(data.replace("confirm_creator_group_link_", "", 1))

        except Exception:

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

            await query.message.reply_text(
                "✅ Grupo vinculado correctamente.\n\n"
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
                        "✅ Grupo vinculado por creator\n\n"
                        f"Grupo: {result.get('group_name')}\n"
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

        try:

            pending_id = int(data.replace("cancel_creator_group_link_", "", 1))

        except Exception:

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


    if data in (
        "public_back_start",
        CALLBACK_COMMERCIAL_BACK_START
    ):

        clear_support_user_state(context)
        clear_location_gate_state(context)

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


    if data.startswith("marketplace_group_"):

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

            message = await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video.get("video_file_id"),
                caption=format_dynamic_preview_video_caption_for_user(
                    group,
                    video,
                    index,
                    total,
                    user_id=user_id
                ),
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


        _group_id, group_name, _telegram_group_id = group
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

        plans = fetch_active_commercial_plans(PRODUCT_SHARED_BOT_SPACE)

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Activar directamente sin prueba\n\n"
            "Elige la duración comercial para publicar tu comunidad sin prueba.\n\n"
            "Si el plan no tiene pago automático configurado, un administrador debe añadir el price_id de Stripe.",
            reply_markup=InlineKeyboardMarkup(
                build_direct_activation_plan_keyboard(plans)
            )
        )

        return


    if data.startswith("commercial_direct_plan_"):

        plan_id = extract_commercial_request_id(
            data,
            "commercial_direct_plan_"
        )
        plan = fetch_commercial_plan(plan_id)


        if not plan:

            await query.message.reply_text(
                "❌ Plan comercial no encontrado."
            )

            return


        if not plan.get("stripe_price_id"):

            await query.message.reply_text(
                "Este plan todavía no tiene pago automático configurado. Un administrador debe añadir el price_id de Stripe."
            )

            await notify_commercial_admin(
                context,
                (
                    "💳 Activación directa solicitada\n\n"
                    f"Usuario: {user_id}\n"
                    f"Plan: {plan.get('name') or '-'}\n"
                    "Falta stripe_price_id."
                )
            )

            return


        await query.message.reply_text(
            "El pago automático comercial todavía está pendiente de conectar."
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


    if data == "admin_global_panel":

        await send_clean_message(
            context,
            query.message.chat_id,
            "👑 Panel global del bot: índice principal de la plataforma.\n\n"
            "Desde aquí entras a monitor beta, satisfacción, soporte, marketplace, propietarios y los dos submenús separados de configuración y herramientas.",
            reply_markup=build_admin_global_panel_keyboard()
        )

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


    if data == "admin_payment_changenow":

        config_row = fetch_platform_payment_provider_config(OWNER_PAYMENT_PROVIDER_CHANGENOW)
        summary = (config_row or {}).get("masked_public_summary") or "sin configuración guardada"
        status = (config_row or {}).get("status") or "not_configured"
        enabled = "activo" if (config_row or {}).get("is_enabled") else "inactivo"

        await send_clean_message(
            context,
            query.message.chat_id,
            build_changenow_tutorial_text("la plataforma")
            + "\n\nEstado plataforma:\n"
            + f"Estado: {status} / {enabled}\n"
            + f"Resumen seguro: {summary}\n\n"
            + "Los pagos ChangeNOW quedan en revisión manual y no conceden acceso automáticamente.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📘 Cómo funciona", callback_data="admin_payment_changenow_help")],
                [InlineKeyboardButton("⚙️ Configurar ChangeNOW", callback_data="admin_payment_changenow_connect")],
                [InlineKeyboardButton("🧪 Estado / revisión", callback_data="admin_changenow_manual_review")],
                [InlineKeyboardButton("⛔ Desactivar", callback_data="admin_payment_changenow_disable")],
                [InlineKeyboardButton("🗑 Borrar configuración", callback_data="admin_payment_changenow_delete")],
                [InlineKeyboardButton("⬅️ Métodos de pago", callback_data="admin_payment_providers")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_changenow_help":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_changenow_tutorial_text("la plataforma")
            + "\n\nPaso a paso para superadmin:\n"
            "1. Crea o revisa tu cuenta/API key de ChangeNOW.\n"
            "2. Decide moneda y red destino.\n"
            "3. Pega la wallet destino con cuidado.\n"
            "4. Guarda cifrado.\n"
            "5. Revisa manualmente cada pago antes de activar nada.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_changenow_connect":

        if not has_payment_encryption_key():

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚠️ ChangeNOW no puede configurarse todavía\n\n"
                "Falta PAYMENT_CONFIG_ENCRYPTION_KEY. Por seguridad no se guardan credenciales reales sin cifrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        clear_owner_payment_provider_wizard(context)
        context.user_data["configuring_platform_payment_provider"] = True
        context.user_data["platform_payment_provider"] = OWNER_PAYMENT_PROVIDER_CHANGENOW
        context.user_data["platform_payment_step"] = "mode"
        context.user_data["platform_payment_payload"] = {}
        ensure_platform_payment_provider_config(OWNER_PAYMENT_PROVIDER_CHANGENOW, status="pending")

        await send_clean_message(
            context,
            query.message.chat_id,
            build_changenow_tutorial_text("la plataforma")
            + "\n\nElige el modo de tasa que quieres preparar.",
            reply_markup=build_platform_changenow_mode_keyboard()
        )

        return


    if data.startswith("admin_payment_changenow_mode_"):

        mode = data.replace("admin_payment_changenow_mode_", "", 1)

        if mode not in ("fixed", "float"):

            await query.message.reply_text(
                "⚠️ No he podido identificar el modo ChangeNOW.",
                reply_markup=build_admin_payment_providers_keyboard()
            )

            return


        context.user_data["configuring_platform_payment_provider"] = True
        context.user_data["platform_payment_provider"] = OWNER_PAYMENT_PROVIDER_CHANGENOW
        context.user_data["platform_payment_payload"] = {"rate_mode": mode}
        context.user_data["platform_payment_step"] = "api_key"

        await send_clean_message(
            context,
            query.message.chat_id,
            ("Modo seleccionado: fixed\n\n" if mode == "fixed" else "Modo seleccionado: floating\n\n")
            + "Envía ahora la API key de ChangeNOW para plataforma. Intentaré borrar el mensaje después de recibirlo.",
            reply_markup=build_platform_changenow_cancel_keyboard()
        )

        return


    if data == "admin_payment_changenow_cancel":

        clear_owner_payment_provider_wizard(context)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración ChangeNOW cancelada. No se ha guardado ningún secreto.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_changenow_save":

        payload = context.user_data.get("platform_payment_payload") or {}
        required_keys = ("rate_mode", "api_key", "payout_currency", "payout_network", "payout_wallet", "payin_currency", "payin_network")

        if any(not payload.get(key) for key in required_keys):

            await query.message.reply_text(
                "⚠️ Faltan datos para guardar ChangeNOW plataforma.",
                reply_markup=build_platform_changenow_cancel_keyboard()
            )

            return


        safe_config = {
            "provider": OWNER_PAYMENT_PROVIDER_CHANGENOW,
            "rate_mode": payload.get("rate_mode"),
            "api_key": payload.get("api_key"),
            "payout_currency": payload.get("payout_currency"),
            "payout_network": payload.get("payout_network"),
            "payout_wallet": payload.get("payout_wallet"),
            "payin_currency": payload.get("payin_currency"),
            "payin_network": payload.get("payin_network"),
            "manual_only": True
        }

        try:

            encrypted_config = encrypt_provider_config(safe_config)
            masked_summary = (
                f"payin={payload.get('payin_currency')}/{payload.get('payin_network')}; "
                f"payout={payload.get('payout_currency')}/{payload.get('payout_network')}; "
                f"wallet={mask_secret_value(payload.get('payout_wallet'))}; "
                "manual_review=on"
            )
            saved = save_platform_payment_provider_encrypted_config(
                OWNER_PAYMENT_PROVIDER_CHANGENOW,
                encrypted_config,
                masked_summary,
                public_config_json={
                    "rate_mode": payload.get("rate_mode"),
                    "payin_currency": payload.get("payin_currency"),
                    "payin_network": payload.get("payin_network"),
                    "payout_currency": payload.get("payout_currency"),
                    "payout_network": payload.get("payout_network"),
                    "manual_review_required": True,
                    "checkout_enabled": True,
                    "webhook_configured": False
                },
                verified_by=user_id
            )

        except Exception:

            saved = False

        clear_owner_payment_provider_wizard(context)

        if saved:

            log_event(
                "platform_payment_provider_credentials_saved",
                category="payment",
                severity="info",
                actor_user_id=user_id,
                message="Credenciales ChangeNOW plataforma guardadas cifradas.",
                metadata={
                    "provider": OWNER_PAYMENT_PROVIDER_CHANGENOW,
                    "rate_mode": payload.get("rate_mode"),
                    "manual_review_required": True
                }
            )

        await send_clean_message(
            context,
            query.message.chat_id,
            ("✅ ChangeNOW plataforma guardado de forma segura\n\n" if saved else "⚠️ No pude guardar ChangeNOW plataforma\n\n")
            + (
                f"{build_changenow_safe_summary(payload)}\n\n"
                "Estado: activo para pagos cripto en revisión manual."
                if saved
                else "Revisa la configuración y vuelve a intentarlo."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")],
                [InlineKeyboardButton("💳 Métodos de pago", callback_data="admin_payment_providers")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_changenow_disable":

        updated = disable_platform_payment_provider_config(OWNER_PAYMENT_PROVIDER_CHANGENOW)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ ChangeNOW plataforma desactivado." if updated else "⚠️ No pude desactivar ChangeNOW plataforma.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_changenow_delete":

        updated = clear_platform_payment_provider_config(OWNER_PAYMENT_PROVIDER_CHANGENOW)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración ChangeNOW plataforma borrada." if updated else "⚠️ No pude borrar ChangeNOW plataforma.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_guardarian":

        config_row = fetch_platform_payment_provider_config(OWNER_PAYMENT_PROVIDER_GUARDARIAN)
        summary = (config_row or {}).get("masked_public_summary") or "sin configuración guardada"
        status = (config_row or {}).get("status") or "not_configured"
        enabled = "activo" if (config_row or {}).get("is_enabled") else "inactivo"

        await send_clean_message(
            context,
            query.message.chat_id,
            build_guardarian_tutorial_text("la plataforma")
            + "\n\nEstado plataforma:\n"
            + f"Estado: {status} / {enabled}\n"
            + f"Resumen seguro: {summary}\n\n"
            + "Automático: sí, únicamente cuando Guardarian devuelve status finished al consultar GET /v1/transaction/{id}.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📘 Cómo funciona", callback_data="admin_payment_guardarian_help")],
                [InlineKeyboardButton("🧾 Qué necesitas", callback_data="admin_payment_guardarian_help")],
                [InlineKeyboardButton("🧪 Estado de configuración", callback_data="admin_payment_guardarian")],
                [InlineKeyboardButton("⚙️ Configurar Guardarian", callback_data="admin_payment_guardarian_connect")],
                [InlineKeyboardButton("✅ Activar / reconectar método", callback_data="admin_payment_guardarian_connect")],
                [InlineKeyboardButton("🔁 Reconsultar pagos pendientes", callback_data="admin_guardarian_recheck_pending")],
                [InlineKeyboardButton("🧪 Estado / revisión", callback_data="admin_guardarian_manual_review")],
                [InlineKeyboardButton("⛔ Desactivar", callback_data="admin_payment_guardarian_disable")],
                [InlineKeyboardButton("🗑 Borrar configuración", callback_data="admin_payment_guardarian_delete")],
                [InlineKeyboardButton("⬅️ Métodos de pago", callback_data="admin_payment_providers")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_guardarian_help":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_guardarian_tutorial_text("la plataforma")
            + "\n\nPaso a paso para superadmin:\n"
            "1. Crea o revisa tu cuenta/API key de Guardarian.\n"
            "2. Configura wallet USDT y red correcta.\n"
            "3. Guarda cifrado desde este bot.\n"
            "4. Usa el webhook solo como aviso; el bot siempre reconsulta Guardarian.\n"
            "5. Revisa manualmente solo pagos retenidos, dudosos o no verificables.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_guardarian_connect":

        if not has_payment_encryption_key():

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚠️ Guardarian no puede configurarse todavía\n\n"
                "Falta PAYMENT_CONFIG_ENCRYPTION_KEY. Por seguridad no se guardan credenciales reales sin cifrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        clear_owner_payment_provider_wizard(context)
        context.user_data["configuring_platform_payment_provider"] = True
        context.user_data["platform_payment_provider"] = OWNER_PAYMENT_PROVIDER_GUARDARIAN
        context.user_data["platform_payment_step"] = "mode"
        context.user_data["platform_payment_payload"] = {}
        ensure_platform_payment_provider_config(OWNER_PAYMENT_PROVIDER_GUARDARIAN, status="pending")

        await send_clean_message(
            context,
            query.message.chat_id,
            build_guardarian_tutorial_text("la plataforma")
            + "\n\nElige el entorno que quieres preparar.",
            reply_markup=build_platform_guardarian_mode_keyboard()
        )

        return


    if data.startswith("admin_payment_guardarian_mode_"):

        mode = data.replace("admin_payment_guardarian_mode_", "", 1)

        if mode not in ("sandbox", "live"):

            await query.message.reply_text(
                "⚠️ No he podido identificar el modo Guardarian.",
                reply_markup=build_admin_payment_providers_keyboard()
            )

            return


        context.user_data["configuring_platform_payment_provider"] = True
        context.user_data["platform_payment_provider"] = OWNER_PAYMENT_PROVIDER_GUARDARIAN
        context.user_data["platform_payment_payload"] = {
            "mode": mode,
            "fiat_currency": "EUR",
            "payout_currency": "USDT"
        }
        context.user_data["platform_payment_step"] = "api_key"

        await send_clean_message(
            context,
            query.message.chat_id,
            ("Modo seleccionado: sandbox\n\n" if mode == "sandbox" else "Modo seleccionado: live\n\n")
            + "Envía ahora la API key de Guardarian para plataforma. Intentaré borrar el mensaje después de recibirlo.",
            reply_markup=build_platform_guardarian_cancel_keyboard()
        )

        return


    if data == "admin_payment_guardarian_cancel":

        clear_owner_payment_provider_wizard(context)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración Guardarian cancelada. No se ha guardado ningún secreto.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_guardarian_save":

        payload = context.user_data.get("platform_payment_payload") or {}
        required_keys = ("mode", "api_key", "payout_network", "payout_wallet")

        if any(not payload.get(key) for key in required_keys):

            await query.message.reply_text(
                "⚠️ Faltan datos para guardar Guardarian plataforma.",
                reply_markup=build_platform_guardarian_cancel_keyboard()
            )

            return


        safe_config = {
            "provider": OWNER_PAYMENT_PROVIDER_GUARDARIAN,
            "mode": payload.get("mode"),
            "api_key": payload.get("api_key"),
            "webhook_secret": payload.get("webhook_secret"),
            "base_url": payload.get("base_url"),
            "fiat_currency": "EUR",
            "payout_currency": "USDT",
            "payout_network": payload.get("payout_network"),
            "payout_wallet": payload.get("payout_wallet")
        }

        try:

            encrypted_config = encrypt_provider_config(safe_config)
            masked_summary = (
                f"mode={payload.get('mode')}; "
                "fiat=EUR; payout=USDT; "
                f"network={payload.get('payout_network')}; "
                f"wallet={mask_secret_value(payload.get('payout_wallet'))}; "
                f"webhook_secret={'configured' if payload.get('webhook_secret') else 'pending'}; "
                "auto=finished"
            )
            saved = save_platform_payment_provider_encrypted_config(
                OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                encrypted_config,
                masked_summary,
                public_config_json={
                    "mode": payload.get("mode"),
                    "fiat_currency": "EUR",
                    "payout_currency": "USDT",
                    "payout_network": payload.get("payout_network"),
                    "webhook_configured": bool(payload.get("webhook_secret")),
                    "checkout_enabled": True,
                    "auto_verified_status": "finished",
                    "base_url_configured": bool(payload.get("base_url"))
                },
                verified_by=user_id
            )

        except Exception:

            saved = False

        clear_owner_payment_provider_wizard(context)

        if saved:

            log_event(
                "platform_payment_provider_credentials_saved",
                category="payment",
                severity="info",
                actor_user_id=user_id,
                message="Credenciales Guardarian plataforma guardadas cifradas.",
                metadata={
                    "provider": OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                    "mode": payload.get("mode"),
                    "webhook_configured": bool(payload.get("webhook_secret")),
                    "auto_verified_status": "finished"
                }
            )

        await send_clean_message(
            context,
            query.message.chat_id,
            ("✅ Guardarian plataforma guardado de forma segura\n\n" if saved else "⚠️ No pude guardar Guardarian plataforma\n\n")
            + (
                f"{build_guardarian_safe_summary(payload)}\n\n"
                "Estado: activo para pagos EUR → USDT. Solo status finished concede acceso."
                if saved
                else "Revisa la configuración y vuelve a intentarlo."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")],
                [InlineKeyboardButton("💳 Métodos de pago", callback_data="admin_payment_providers")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_guardarian_disable":

        updated = disable_platform_payment_provider_config(OWNER_PAYMENT_PROVIDER_GUARDARIAN)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Guardarian plataforma desactivado." if updated else "⚠️ No pude desactivar Guardarian plataforma.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_payment_guardarian_delete":

        updated = clear_platform_payment_provider_config(OWNER_PAYMENT_PROVIDER_GUARDARIAN)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración Guardarian plataforma borrada." if updated else "⚠️ No pude borrar Guardarian plataforma.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_guardarian_manual_review":

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       user_id,
                       group_id,
                       plan_id,
                       amount,
                       currency,
                       status,
                       external_payment_id,
                       external_checkout_id,
                       created_at
                FROM payment_transactions
                WHERE provider=%s
                AND status=%s
                ORDER BY created_at DESC
                LIMIT 20

            """, (
                OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                "manual_review"
            ))

            rows = cur.fetchall()

        lines = [
            "🧪 Pagos Guardarian en revisión",
            "",
            "Estos pagos no se pudieron verificar automáticamente como finished. Reconsulta o decide manualmente con cuidado."
        ]
        keyboard = []

        if not rows:

            lines.append("\nNo hay pagos Guardarian pendientes de revisión.")

        for row in rows:

            transaction_id, tx_user_id, tx_group_id, tx_plan_id, amount, currency, status, external_payment_id, external_checkout_id, created_at = row
            lines.extend([
                "",
                f"#{transaction_id} Usuario: {tx_user_id}",
                f"Grupo: {tx_group_id or '-'} Plan: {tx_plan_id or '-'}",
                f"Importe: {amount or '-'} {currency or ''}",
                f"Estado: {status}",
                f"Provider id: {external_payment_id or external_checkout_id or '-'}",
                f"Fecha: {created_at}"
            ])
            keyboard.append([
                InlineKeyboardButton(f"✅ Confirmar #{transaction_id}", callback_data=f"admin_guardarian_mark_paid_{transaction_id}"),
                InlineKeyboardButton(f"❌ Rechazar #{transaction_id}", callback_data=f"admin_guardarian_reject_{transaction_id}")
            ])

        keyboard.extend([
            [InlineKeyboardButton("🔁 Reconsultar pagos pendientes", callback_data="admin_guardarian_recheck_pending")],
            [InlineKeyboardButton("⬅️ Guardarian", callback_data="admin_payment_guardarian")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "admin_guardarian_recheck_pending":

        with conn.cursor() as cur:

            cur.execute("""

                SELECT external_checkout_id
                FROM payment_transactions
                WHERE provider=%s
                AND status IN (%s, %s)
                AND external_checkout_id IS NOT NULL
                ORDER BY created_at ASC
                LIMIT 20

            """, (
                OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                "pending",
                "manual_review"
            ))
            rows = cur.fetchall()

        checked = 0

        for row in rows:

            provider_order_id = row[0]

            if not provider_order_id:

                continue

            process_guardarian_webhook({"id": provider_order_id})
            checked += 1

        await send_clean_message(
            context,
            query.message.chat_id,
            f"🔁 Reconsulta Guardarian terminada. Pagos revisados: {checked}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Ver revisión", callback_data="admin_guardarian_manual_review")],
                [InlineKeyboardButton("⬅️ Guardarian", callback_data="admin_payment_guardarian")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("admin_guardarian_reject_"):

        transaction_id = extract_commercial_request_id(data, "admin_guardarian_reject_")

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET status='failed',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                AND provider=%s
                RETURNING id

            """, (
                transaction_id,
                OWNER_PAYMENT_PROVIDER_GUARDARIAN
            ))
            updated = cur.fetchone()

        conn.commit()

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Pago Guardarian rechazado." if updated else "⚠️ No encontré ese pago Guardarian.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Volver a revisión", callback_data="admin_guardarian_manual_review")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("admin_guardarian_mark_paid_"):

        transaction_id = extract_commercial_request_id(data, "admin_guardarian_mark_paid_")

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       user_id,
                       group_id,
                       plan_id,
                       amount,
                       currency,
                       external_payment_id,
                       external_checkout_id,
                       status
                FROM payment_transactions
                WHERE id=%s
                AND provider=%s
                LIMIT 1

            """, (
                transaction_id,
                OWNER_PAYMENT_PROVIDER_GUARDARIAN
            ))
            row = cur.fetchone()

        if not row:

            await query.message.reply_text(
                "⚠️ No encontré ese pago Guardarian.",
                reply_markup=build_admin_payment_providers_keyboard()
            )

            return


        _tx_id, tx_user_id, tx_group_id, tx_plan_id, amount, currency, external_payment_id, external_checkout_id, tx_status = row

        if tx_status == "paid":

            result = {"ok": True, "reason": "already_paid"}
            new_status = "paid"

        elif tx_group_id and tx_plan_id:

            result = grant_group_access_after_payment(
                OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                tx_user_id,
                tx_group_id,
                tx_plan_id,
                external_payment_id=external_payment_id,
                external_checkout_id=external_checkout_id,
                amount=amount,
                currency=currency,
                transaction_id=transaction_id
            )
            new_status = "paid" if result.get("ok") else "manual_review"

        else:

            result = {"ok": True, "reason": "platform_manual_mark_paid"}
            new_status = "paid"

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET status=%s,
                    metadata_json=COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                    metadata=COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s

            """, (
                new_status,
                json.dumps({"manual_confirmed_by": user_id, "manual_result": result}),
                json.dumps({"manual_confirmed_by": user_id, "manual_result": result}),
                transaction_id
            ))

        conn.commit()

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Pago Guardarian confirmado manualmente." if result.get("ok") else "⚠️ No pude conceder el acceso. El pago sigue en revisión.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Volver a revisión", callback_data="admin_guardarian_manual_review")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "admin_changenow_manual_review":

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       user_id,
                       group_id,
                       plan_id,
                       amount,
                       currency,
                       status,
                       external_payment_id,
                       created_at
                FROM payment_transactions
                WHERE provider=%s
                AND status=%s
                ORDER BY created_at DESC
                LIMIT 20

            """, (
                OWNER_PAYMENT_PROVIDER_CHANGENOW,
                "manual_review"
            ))

            rows = cur.fetchall()

        lines = [
            "🧪 Pagos ChangeNOW en revisión",
            "",
            "Estos pagos NO conceden acceso automático. Revisa wallet, importe y estado antes de confirmar."
        ]
        keyboard = []

        if not rows:

            lines.append("\nNo hay pagos ChangeNOW pendientes de revisión.")

        for row in rows:

            transaction_id, tx_user_id, tx_group_id, tx_plan_id, amount, currency, status, external_payment_id, created_at = row
            lines.extend([
                "",
                f"#{transaction_id} Usuario: {tx_user_id}",
                f"Grupo: {tx_group_id or '-'} Plan: {tx_plan_id or '-'}",
                f"Importe: {amount or '-'} {currency or ''}",
                f"Estado: {status}",
                f"Provider id: {external_payment_id or '-'}",
                f"Fecha: {created_at}"
            ])
            keyboard.append([
                InlineKeyboardButton(f"✅ Confirmar #{transaction_id}", callback_data=f"admin_changenow_mark_paid_{transaction_id}"),
                InlineKeyboardButton(f"❌ Rechazar #{transaction_id}", callback_data=f"admin_changenow_reject_{transaction_id}")
            ])

        keyboard.extend([
            [InlineKeyboardButton("⬅️ ChangeNOW", callback_data="admin_payment_changenow")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data.startswith("admin_changenow_reject_"):

        transaction_id = extract_commercial_request_id(data, "admin_changenow_reject_")

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET status='failed',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                AND provider=%s
                RETURNING id

            """, (
                transaction_id,
                OWNER_PAYMENT_PROVIDER_CHANGENOW
            ))
            updated = cur.fetchone()

        conn.commit()

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Pago ChangeNOW rechazado." if updated else "⚠️ No encontré ese pago ChangeNOW.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Volver a revisión", callback_data="admin_changenow_manual_review")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("admin_changenow_mark_paid_"):

        transaction_id = extract_commercial_request_id(data, "admin_changenow_mark_paid_")

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       user_id,
                       group_id,
                       plan_id,
                       amount,
                       currency,
                       external_payment_id,
                       external_checkout_id,
                       status
                FROM payment_transactions
                WHERE id=%s
                AND provider=%s
                LIMIT 1

            """, (
                transaction_id,
                OWNER_PAYMENT_PROVIDER_CHANGENOW
            ))
            row = cur.fetchone()

        if not row:

            await query.message.reply_text(
                "⚠️ No encontré ese pago ChangeNOW.",
                reply_markup=build_admin_payment_providers_keyboard()
            )

            return


        _tx_id, tx_user_id, tx_group_id, tx_plan_id, amount, currency, external_payment_id, external_checkout_id, tx_status = row

        if tx_group_id and tx_plan_id:

            result = grant_group_access_after_payment(
                OWNER_PAYMENT_PROVIDER_CHANGENOW,
                tx_user_id,
                tx_group_id,
                tx_plan_id,
                external_payment_id=external_payment_id,
                external_checkout_id=external_checkout_id,
                amount=amount,
                currency=currency,
                transaction_id=transaction_id
            )
            new_status = "paid" if result.get("ok") else "manual_review"

        else:

            result = {"ok": True, "reason": "platform_manual_mark_paid"}
            new_status = "paid"

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET status=%s,
                    metadata_json=COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                    metadata=COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s

            """, (
                new_status,
                json.dumps({"manual_confirmed_by": user_id, "manual_result": result}),
                json.dumps({"manual_confirmed_by": user_id, "manual_result": result}),
                transaction_id
            ))

        conn.commit()

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Pago ChangeNOW confirmado manualmente." if result.get("ok") else "⚠️ No pude conceder el acceso. El pago sigue en revisión.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Volver a revisión", callback_data="admin_changenow_manual_review")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

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


    if data in (
        "admin_commercial_active_requests",
        "admin_commercial_trials_active",
        "admin_commercial_subscriptions",
        "admin_commercial_group_limits",
        "admin_commercial_owner_tools",
        "admin_commercial_reassign_owner_group"
    ):

        if data == "admin_commercial_active_requests":

            requests = fetch_commercial_requests_by_statuses([
                "approved",
                "awaiting_creator_setup",
                "setup_in_progress",
                "setup_ready",
                "active"
            ])

            title = "✅ Solicitudes activas"

        elif data == "admin_commercial_trials_active":

            requests = fetch_commercial_requests_by_statuses([
                "trial_active"
            ])

            title = "⏳ Trials activos"

        elif data == "admin_commercial_subscriptions":

            requests = fetch_commercial_requests_by_statuses([
                "active",
                "trial_expired",
                "expired_pending_reactivation"
            ])

            title = "💳 Suscripciones comerciales"

        else:

            requests = fetch_commercial_requests_by_statuses([
                "approved",
                "trial_active",
                "awaiting_creator_setup",
                "setup_in_progress",
                "setup_ready",
                "active"
            ])

            title = (
                "🔢 Cupos de grupos"
                if data == "admin_commercial_group_limits"
                else (
                    "🔁 Reasignar owner/grupo"
                    if data == "admin_commercial_reassign_owner_group"
                    else "🔎 Buscar propietario"
                )
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            build_commercial_status_list_text(title, requests),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_status_list_keyboard(requests)
            )
        )

        return


    if data == "admin_commercial_owner_summary":

        pending_requests = fetch_pending_commercial_requests()
        active_requests = fetch_commercial_requests_by_statuses([
            "approved",
            "awaiting_creator_setup",
            "setup_in_progress",
            "setup_ready",
            "active"
        ])
        trial_requests = fetch_commercial_requests_by_statuses([
            "trial_active"
        ])
        subscription_requests = fetch_commercial_requests_by_statuses([
            "active",
            "trial_expired",
            "expired_pending_reactivation"
        ])
        archived_requests = fetch_archived_commercial_requests()

        await send_clean_message(
            context,
            query.message.chat_id,
            "📊 Resumen propietarios\n\n"
            f"🕓 Solicitudes pendientes: {len(pending_requests)}\n"
            f"✅ Propietarios activos/configurando: {len(active_requests)}\n"
            f"🧪 Trials activos: {len(trial_requests)}\n"
            f"💳 Suscripciones/recoveries: {len(subscription_requests)}\n"
            f"📁 Archivados: {len(archived_requests)}\n\n"
            "Usa los botones del panel de propietarios para abrir cada vista y revisar casos concretos.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🕓 Solicitudes pendientes", callback_data="admin_commercial_requests")],
                [InlineKeyboardButton("✅ Propietarios activos", callback_data="admin_commercial_active_requests")],
                [InlineKeyboardButton("🧑‍💼 Propietarios", callback_data="admin_owners_panel")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

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


    if data in (
        "admin_satisfaction_send_pending",
        "admin_satisfaction_resend_incomplete",
        "admin_satisfaction_send_never_sent",
        "admin_satisfaction_force_new_cycle"
    ):

        mode_by_callback = {
            "admin_satisfaction_send_pending": "pending",
            "admin_satisfaction_resend_incomplete": "resend_incomplete",
            "admin_satisfaction_send_never_sent": "never_sent",
            "admin_satisfaction_force_new_cycle": "pending"
        }
        mode = mode_by_callback[data]
        campaign_id = "default"

        if data == "admin_satisfaction_force_new_cycle":
            campaign_id = f"cycle_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        survey_id = create_customer_satisfaction_survey(
            user_id,
            "global",
            send_mode=mode,
            campaign_id=campaign_id
        )
        targeting = build_customer_satisfaction_targeting(
            "global",
            mode,
            campaign_id=campaign_id
        )

        mode_text = {
            "pending": "Enviar a pendientes",
            "resend_incomplete": "Reenviar a no completados",
            "never_sent": "Enviar solo a nunca enviados"
        }.get(mode, mode)

        await send_clean_message(
            context,
            query.message.chat_id,
            "📤 Confirmar envío de encuesta\n\n"
            f"Modo: {mode_text}\n"
            f"Audiencia: {get_customer_satisfaction_audience_label('global')}\n"
            f"Campaña: {campaign_id}\n\n"
            f"Se enviará la encuesta a {targeting['target_count']} usuarios.\n"
            f"Se omitirán {targeting['skipped_completed']} usuarios que ya la completaron.\n"
            f"Se omitirán {targeting['skipped_already_sent']} usuarios que ya la recibieron en este ciclo.\n\n"
            "Para que sea justo, el bot nunca reenvía por defecto a usuarios que ya respondieron.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar envío", callback_data=f"admin_satisfaction_confirm_{survey_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="admin_customer_satisfaction")]
            ])
        )

        return


    if data.startswith("admin_satisfaction_send_"):

        audience_slug = data.replace("admin_satisfaction_send_", "", 1)
        audience = {
            "global": "global",
            "users": "users",
            "owners": "owners",
            "group_admins": "group_admins"
        }.get(audience_slug)

        if not audience:
            await query.message.reply_text(
                "❌ Audiencia no válida.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        survey_id = create_customer_satisfaction_survey(
            user_id,
            audience,
            send_mode="pending",
            campaign_id="default"
        )
        targeting = build_customer_satisfaction_targeting(
            audience,
            "pending",
            campaign_id="default"
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "📤 Confirmar envío de encuesta\n\n"
            f"Audiencia: {get_customer_satisfaction_audience_label(audience)}\n"
            f"Usuarios elegibles: {targeting['total']}\n\n"
            f"Se enviará la encuesta a {targeting['target_count']} usuarios.\n"
            f"Se omitirán {targeting['skipped_completed']} usuarios que ya la completaron.\n"
            f"Se omitirán {targeting['skipped_already_sent']} usuarios que ya la recibieron en este ciclo.\n\n"
            "¿Confirmas?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar envío", callback_data=f"admin_satisfaction_confirm_{survey_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="admin_customer_satisfaction")]
            ])
        )

        return


    if data == "admin_satisfaction_delivery_status":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_delivery_status_text("global"),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_confirm_"):

        try:
            survey_id = int(data.replace("admin_satisfaction_confirm_", "", 1))
        except Exception:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        survey = fetch_customer_satisfaction_survey(survey_id)

        if not survey:
            await query.message.reply_text(
                "❌ Encuesta no encontrada.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        if survey["status"] != "draft":
            await query.message.reply_text(
                "⚠️ Esta encuesta ya fue enviada o está en proceso. No se duplicará.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        if not mark_customer_satisfaction_survey_sending(survey_id):
            await query.message.reply_text(
                "⚠️ Esta encuesta ya se está enviando o ya fue enviada. No se duplicará.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        targeting = build_customer_satisfaction_targeting(
            survey["audience"],
            survey["send_mode"],
            group_id=survey["group_id"],
            campaign_id=survey["campaign_id"]
        )
        sent_count = 0
        failed_count = 0

        for skipped_user_id in targeting["completed_users"]:
            mark_customer_satisfaction_delivery_skipped(
                survey_id,
                skipped_user_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                "skipped_completed"
            )

        already_sent_users = set(targeting["sent_current_cycle"]) - set(targeting["targets"])
        already_sent_users -= set(targeting["completed_users"])

        for skipped_user_id in sorted(already_sent_users):
            mark_customer_satisfaction_delivery_skipped(
                survey_id,
                skipped_user_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                "skipped_already_sent"
            )

        for recipient_id in targeting["targets"]:
            reserved = reserve_customer_satisfaction_delivery(
                survey_id,
                recipient_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                allow_existing=survey["send_mode"] == "resend_incomplete"
            )

            if not reserved:
                continue

            try:
                await context.bot.send_message(
                    chat_id=recipient_id,
                    text=(
                        "Queremos mejorar el bot. Responde esta encuesta rápida de 1 a 5.\n\n"
                        "Tus respuestas ayudan a mejorar menús, acceso, pagos, soporte y seguridad."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📝 Responder encuesta", callback_data=f"satisfaction_start_{survey_id}")]
                    ])
                )
                sent_count += 1
                log_user_event_by_ids(
                    recipient_id,
                    "survey_sent",
                    event_key="customer_satisfaction",
                    group_id=survey["group_id"],
                    metadata={
                        "survey_id": survey_id,
                        "campaign_id": survey["campaign_id"],
                        "send_mode": survey["send_mode"]
                    }
                )
            except Exception as e:
                failed_count += 1
                mark_customer_satisfaction_delivery_failed(
                    survey_id,
                    recipient_id,
                    survey["group_id"],
                    survey["campaign_id"],
                    e
                )
                log_event(
                    "survey_send_failed",
                    category="satisfaction",
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=recipient_id,
                    group_id=survey["group_id"],
                    message="No se pudo entregar una encuesta de satisfacción.",
                    metadata={
                        "survey_id": survey_id,
                        "audience": survey["audience"],
                        "error": str(e)[:200]
                    }
                )

        update_customer_satisfaction_sent_counts(
            survey_id,
            sent_count,
            failed_count,
            targeting["skipped_completed"],
            targeting["skipped_already_sent"]
        )

        log_event(
            "survey_sent",
            category="satisfaction",
            severity="info",
            actor_user_id=user_id,
            group_id=survey["group_id"],
            message="Encuesta de satisfacción enviada.",
            metadata={
                "survey_id": survey_id,
                "audience": survey["audience"],
                "campaign_id": survey["campaign_id"],
                "send_mode": survey["send_mode"],
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_completed": targeting["skipped_completed"],
                "skipped_already_sent": targeting["skipped_already_sent"]
            }
        )
        record_beta_event(
            "survey_sent",
            severity="info",
            user_id=user_id,
            group_id=survey["group_id"],
            message="Encuesta de satisfacción enviada.",
            metadata={
                "survey_id": survey_id,
                "audience": survey["audience"],
                "campaign_id": survey["campaign_id"],
                "send_mode": survey["send_mode"],
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_completed": targeting["skipped_completed"],
                "skipped_already_sent": targeting["skipped_already_sent"]
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Encuesta enviada\n\n"
            f"Enviados: {sent_count}\n"
            f"Fallidos: {failed_count}\n"
            f"Omitidos por completada: {targeting['skipped_completed']}\n"
            f"Omitidos por ya enviada: {targeting['skipped_already_sent']}",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_results":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_results_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_questions":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_questions_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_deactivate_menu":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🚫 Desactivar pregunta\n\nElige una pregunta activa para ocultarla en próximas encuestas.",
            reply_markup=build_customer_satisfaction_deactivate_keyboard()
        )

        return


    if data == "admin_satisfaction_edit_menu":

        await send_clean_message(
            context,
            query.message.chat_id,
            "✏️ Editar preguntas\n\nElige la pregunta cuyo texto quieres actualizar.",
            reply_markup=build_customer_satisfaction_edit_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_edit_"):

        try:
            question_id = int(data.replace("admin_satisfaction_edit_", "", 1))
        except Exception:
            await query.message.reply_text("❌ Pregunta no válida.")
            return

        context.user_data["customer_satisfaction_admin_edit_question_id"] = question_id

        await query.message.reply_text(
            "✏️ Editar pregunta\n\nEscribe el nuevo texto de la pregunta.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_deactivate_"):

        try:
            question_id = int(data.replace("admin_satisfaction_deactivate_", "", 1))
        except Exception:
            await query.message.reply_text("❌ Pregunta no válida.")
            return

        with conn.cursor() as cur:
            cur.execute("""

                UPDATE customer_satisfaction_questions
                SET is_active=FALSE
                WHERE id=%s

            """, (question_id,))

        await query.message.reply_text(
            "✅ Pregunta desactivada.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_add_rating":

        context.user_data["customer_satisfaction_admin_add_question"] = "rating_1_5"
        await query.message.reply_text(
            "➕ Añadir pregunta\n\nEscribe el texto de la pregunta. Se guardará como valoración 1-5.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_add_text":

        context.user_data["customer_satisfaction_admin_add_question"] = "text"
        await query.message.reply_text(
            "➕ Añadir pregunta texto\n\nEscribe el texto de la pregunta. El usuario responderá con texto libre.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_latest":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_results_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("satisfaction_start_"):

        try:
            survey_id = int(data.replace("satisfaction_start_", "", 1))
        except Exception:
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

        try:
            survey_id = int(data.replace("satisfaction_survey_", "", 1))
        except Exception:
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

        try:
            survey_id = int(data.replace("satisfaction_survey_summary_", "", 1))
        except Exception:
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

        try:
            response_id = int(data.replace("satisfaction_response_", "", 1))
        except Exception:
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


    if data == "owner_backup_panel":

        groups = fetch_backup_owner_groups(user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes grupos propios con permisos para configurar backup."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            format_backup_panel_text(user_id),
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data in (
        "owner_backup_activate",
        "owner_backup_change_destination",
        "owner_backup_destination_token"
    ):

        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]


        if not groups:

            await query.message.reply_text(
                "⚠️ Necesitas al menos un grupo origen propio con el bot añadido como administrador.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🛡 Backup premium\n\nSelecciona el grupo origen. Después generaré un código para vincular el grupo destino.",
            reply_markup=build_backup_group_select_keyboard(
                groups,
                "owner_backup_source_"
            )
        )

        return


    if data == "owner_backup_change_mode":

        configs = fetch_owner_backup_configs(user_id)


        if not configs:

            await query.message.reply_text(
                "⚠️ No tienes ninguna configuración de backup activa para cambiar el modo.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚙️ Cambiar modo de backup\n\n"
            "Solo texto copia mensajes de texto.\n"
            "Texto + fotos copia texto, captions y fotos nuevas sin descargar archivos.\n"
            "Texto + fotos + vídeos añade vídeos nuevos usando Telegram, sin descargar archivos.",
            reply_markup=build_backup_config_select_keyboard(
                configs,
                "owner_backup_mode_config_"
            )
        )

        return


    if data.startswith("owner_backup_mode_config_"):

        try:

            config_id = int(
                data.replace("owner_backup_mode_config_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚙️ Elige el modo de backup\n\n"
            "Solo texto: copia únicamente mensajes de texto.\n"
            "Texto + fotos: copia mensajes de texto, captions y fotos nuevas usando Telegram, sin descargar imágenes.\n"
            "Texto + fotos + vídeos: también copia vídeos nuevos con copy_message, sin guardar binarios.",
            reply_markup=build_backup_mode_keyboard(config_id)
        )

        return


    if data.startswith("owner_backup_set_mode_"):

        try:

            payload = data.replace("owner_backup_set_mode_", "", 1)
            config_id_text, selected_mode = payload.split("_", 1)
            config_id = int(config_id_text)

        except Exception:

            await query.message.reply_text("❌ Modo de backup no válido.")

            return


        if selected_mode not in (
            "text",
            "text_photos",
            "text_photos_videos"
        ):

            await query.message.reply_text("❌ Modo de backup no válido.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET mode=%s,
                    updated_at=NOW()
                WHERE id=%s
                AND owner_user_id=%s

            """, (
                selected_mode,
                config_id,
                user_id
            ))

            conn.commit()


        log_event(
            "backup_mode_changed",
            category="backup",
            severity="info",
            scope="group",
            group_id=config[2],
            telegram_group_id=config[3],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Modo de backup premium actualizado.",
            metadata={
                "config_id": config_id,
                "mode": selected_mode
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Modo de backup actualizado.\n\n"
            f"Modo activo: {format_backup_mode(selected_mode)}",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_toggle_author":

        configs = fetch_owner_backup_configs(user_id)


        if not configs:

            await query.message.reply_text(
                "⚠️ No tienes ninguna configuración de backup para cambiar esta opción.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "👤 Mostrar autor original\n\n"
            "Elige la configuración donde quieres activar o desactivar la atribución.",
            reply_markup=build_backup_config_select_keyboard(
                configs,
                "owner_backup_author_config_"
            )
        )

        return


    if data.startswith("owner_backup_author_config_"):

        try:

            config_id = int(
                data.replace("owner_backup_author_config_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET show_original_author=NOT COALESCE(show_original_author, FALSE),
                    updated_at=NOW()
                WHERE id=%s
                AND owner_user_id=%s
                RETURNING COALESCE(show_original_author, FALSE)

            """, (
                config_id,
                user_id
            ))

            show_original_author = cur.fetchone()[0]
            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Preferencia actualizada.\n\n"
            f"Mostrar autor original: {'Activado' if show_original_author else 'Desactivado'}",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_confirm_destination_"):

        try:

            token_id = int(
                data.replace("owner_backup_confirm_destination_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Código de backup no válido.")

            return


        result = await confirm_backup_destination_token(
            token_id,
            user_id,
            context
        )


        await send_clean_message(
            context,
            query.message.chat_id,
            result["message"],
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_source_"):

        try:

            source_group_id = int(
                data.replace("owner_backup_source_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Grupo origen no válido.")

            return


        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]
        source_group = backup_group_by_id(groups, source_group_id)


        if not source_group:

            await query.message.reply_text(
                "⛔ Este grupo no pertenece a tu panel o el bot no está como administrador."
            )

            return


        token_row = create_backup_destination_token(
            user_id,
            source_group[0],
            source_group[2]
        )


        if not token_row:

            await query.message.reply_text(
                "❌ No pude generar el código de vinculación del backup.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        token_id, token, expires_at = token_row
        command = f"/backup_{token}"


        log_event(
            "backup_destination_token_created",
            category="backup",
            severity="info",
            scope="group",
            group_id=source_group[0],
            telegram_group_id=source_group[2],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Token de destino backup creado.",
            metadata={
                "token_id": token_id,
                "expires_at": expires_at
            }
        )


        await send_clean_message(
            context,
            query.message.chat_id,
            "🛡 Backup premium\n\n"
            f"Origen: {source_group[1] or source_group_id}\n\n"
            "Crea un grupo nuevo o usa un grupo vacío como destino.\n"
            "Añade este bot como administrador.\n"
            "Dentro del grupo destino escribe este comando:\n\n"
            f"{command}\n\n"
            "El código caduca en 24 horas y solo puede usarse una vez.",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_dest_"):

        try:

            payload = data.replace("owner_backup_dest_", "", 1)
            source_group_text, destination_group_text = payload.split("_", 1)
            source_group_id = int(source_group_text)
            destination_group_id = int(destination_group_text)

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        if source_group_id == destination_group_id:

            await query.message.reply_text(
                "⚠️ El origen y el destino no pueden ser el mismo grupo."
            )

            return


        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]
        source_group = backup_group_by_id(groups, source_group_id)
        destination_group = backup_group_by_id(groups, destination_group_id)


        if not source_group or not destination_group:

            await query.message.reply_text(
                "⛔ Solo puedes configurar backup entre grupos propios donde el bot esté como administrador."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO backup_subscriptions
                (
                    owner_user_id,
                    status,
                    plan_type,
                    updated_at
                )
                VALUES (%s, 'active', 'text', NOW())
                RETURNING id

            """, (user_id,))

            subscription_id = cur.fetchone()[0]

            cur.execute("""

                INSERT INTO group_backup_configs
                (
                    owner_user_id,
                    source_group_id,
                    source_telegram_group_id,
                    destination_group_id,
                    destination_telegram_group_id,
                    subscription_id,
                    mode,
                    status,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'text', 'active', NOW())
                ON CONFLICT (owner_user_id, source_group_id, destination_group_id)
                DO UPDATE SET
                    source_telegram_group_id=EXCLUDED.source_telegram_group_id,
                    destination_telegram_group_id=EXCLUDED.destination_telegram_group_id,
                    subscription_id=EXCLUDED.subscription_id,
                    mode='text',
                    status='active',
                    updated_at=NOW()
                RETURNING id

            """, (
                user_id,
                source_group[0],
                source_group[2],
                destination_group[0],
                destination_group[2],
                subscription_id
            ))

            config_id = cur.fetchone()[0]

            conn.commit()


        log_event(
            "backup_activated",
            category="backup",
            severity="info",
            scope="group",
            group_id=source_group_id,
            telegram_group_id=source_group[2],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Backup premium texto activado.",
            metadata={
                "config_id": config_id,
                "destination_group_id": destination_group_id,
                "destination_telegram_group_id": destination_group[2],
                "mode": "text"
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Backup premium activado.\n\n"
            f"Origen: {source_group[1] or source_group_id}\n"
            f"Destino: {destination_group[1] or destination_group_id}\n"
            "Modo: texto",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_pause":

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET status='paused',
                    updated_at=NOW()
                WHERE owner_user_id=%s
                AND status='active'

            """, (user_id,))

            affected = cur.rowcount
            conn.commit()


        log_event(
            "backup_paused",
            category="backup",
            severity="info",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Backup premium pausado por owner.",
            metadata={
                "configs_paused": affected
            }
        )

        await query.message.reply_text(
            f"⏸ Backup pausado en {affected} configuración(es).",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_messages":

        rows = fetch_backup_recent_messages(user_id)


        if not rows:

            await query.message.reply_text(
                "📜 Todavía no hay mensajes copiados.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        text = "📜 Últimos mensajes copiados\n\n"


        for created_at, source_name, destination_name, source_message_id, destination_message_id, message_type, status in rows[:20]:

            text += (
                f"Origen: {source_name or '-'}\n"
                f"Destino: {destination_name or '-'}\n"
                f"Tipo: {message_type or '-'}\n"
                f"Mensaje origen: {source_message_id or '-'}\n"
                f"Mensaje destino: {destination_message_id or '-'}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_errors":

        rows = fetch_backup_recent_errors(user_id)


        if not rows:

            await query.message.reply_text(
                "✅ No hay errores recientes de backup.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        text = "⚠️ Últimos errores de backup\n\n"


        for created_at, severity, error_type, message in rows[:20]:

            text += (
                f"Tipo: {error_type or '-'}\n"
                f"Severidad: {severity or '-'}\n"
                f"Detalle: {message or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "group_admin_panel":

        context.user_data["adding_group_admin"] = False
        context.user_data.pop("group_admin_target_user_id", None)
        context.user_data.pop("group_admin_target_display", None)
        context.user_data.pop("group_admin_selected_group_id", None)
        context.user_data.pop("group_admin_permissions", None)

        groups = fetch_group_admin_manageable_groups(user_id)


        if not groups:

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "👥 Admins de mi grupo\n\nGestiona admins y permisos por comunidad.",
            reply_markup=build_group_admin_panel_keyboard()
        )

        return


    if data == "group_admin_permissions_info":

        text = (
            "📖 Permisos disponibles\n\n"
            "Estos permisos se aplican solo al group_id interno de la comunidad seleccionada.\n\n"
            + "\n".join(
                f"• {label}"
                for _key, label, _permission in GROUP_ADMIN_PERMISSION_OPTIONS
            )
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=build_group_admin_panel_keyboard()
        )

        return


    if data == "group_admin_add":

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        context.user_data["adding_group_admin"] = True
        context.user_data.pop("group_admin_target_user_id", None)
        context.user_data.pop("group_admin_target_display", None)
        context.user_data.pop("group_admin_permissions", None)

        await send_clean_message(
            context,
            query.message.chat_id,
            "➕ Añadir admin\n\n"
            "Envía el user_id del usuario.\n\n"
            "También puedes enviar @username si ese usuario ya existe en la base de datos.",
            reply_markup=build_group_admin_error_keyboard()
        )

        return


    if data.startswith("add_group_admin_select_group_"):

        group_id = extract_commercial_request_id(
            data,
            "add_group_admin_select_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        target_user_id = context.user_data.get("group_admin_target_user_id")


        if not target_user_id:

            await query.message.reply_text(
                "❌ No hay usuario pendiente para añadir.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        context.user_data["group_admin_selected_group_id"] = group_id
        context.user_data["group_admin_permissions"] = {
            permission: False
            for _key, _label, permission in GROUP_ADMIN_PERMISSION_OPTIONS
        }

        await send_clean_message(
            context,
            query.message.chat_id,
            "Permisos del nuevo admin:\n\n"
            + format_group_admin_permission_list(
                context.user_data["group_admin_permissions"]
            ),
            reply_markup=build_group_admin_permissions_keyboard(
                group_id,
                target_user_id,
                context.user_data["group_admin_permissions"],
                "gga_t"
            )
        )

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


    if data.startswith("add_group_admin_save_"):

        group_id = extract_commercial_request_id(
            data,
            "add_group_admin_save_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        target_user_id = context.user_data.get("group_admin_target_user_id")
        permissions = context.user_data.get("group_admin_permissions") or {}


        if not target_user_id:

            await query.message.reply_text(
                "❌ No hay usuario pendiente para añadir.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        save_group_admin_permissions(
            group_id,
            target_user_id,
            permissions
        )

        context.user_data["adding_group_admin"] = False
        context.user_data.pop("group_admin_target_user_id", None)
        context.user_data.pop("group_admin_target_display", None)
        context.user_data.pop("group_admin_selected_group_id", None)
        context.user_data.pop("group_admin_permissions", None)

        try:

            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    "✅ Has sido añadido como admin de una comunidad.\n\n"
                    f"Grupo: {fetch_group_name(group_id)}"
                )
            )

        except Exception as e:

            print("Error avisando admin de grupo:", e)


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Admin guardado correctamente.",
            reply_markup=build_group_admin_panel_keyboard()
        )

        return


    if data == "group_admin_view":

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if len(groups) == 1:

            group_id = groups[0][0]

            await send_clean_message(
                context,
                query.message.chat_id,
                build_group_admins_text(group_id),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Volver", callback_data="group_admin_panel")
                ]])
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "📋 Ver admins\n\nSelecciona una comunidad.",
            reply_markup=build_group_admin_group_select_keyboard(
                groups,
                "group_admin_view_group_"
            )
        )

        return


    if data.startswith("group_admin_view_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_admin_view_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_group_admins_text(group_id),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Volver", callback_data="group_admin_panel")
            ]])
        )

        return


    if data == "group_admin_edit":

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if len(groups) == 1:

            data = f"group_admin_edit_group_{groups[0][0]}"

        else:

            await send_clean_message(
                context,
                query.message.chat_id,
                "✏️ Editar permisos\n\nSelecciona una comunidad.",
                reply_markup=build_group_admin_group_select_keyboard(
                    groups,
                    "group_admin_edit_group_"
                )
            )

            return


    if data.startswith("group_admin_edit_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_admin_edit_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "✏️ Editar permisos\n\nSelecciona el admin.",
            reply_markup=build_group_admin_user_select_keyboard(
                group_id,
                "edit_admin_permissions_user_"
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


    if data == "group_admin_remove":

        groups = fetch_group_admin_context_groups(context, user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if len(groups) == 1:

            data = f"group_admin_remove_group_{groups[0][0]}"

        else:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Quitar admin\n\nSelecciona una comunidad.",
                reply_markup=build_group_admin_group_select_keyboard(
                    groups,
                    "group_admin_remove_group_"
                )
            )

            return


    if data.startswith("group_admin_remove_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_admin_remove_group_"
        )


        if not can_manage_group_admins(user_id, group_id):

            await query.message.reply_text(
                "⛔ Esta comunidad no pertenece a tu panel."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "❌ Quitar admin\n\nSelecciona el admin.",
            reply_markup=build_group_admin_user_select_keyboard(
                group_id,
                "group_admin_remove_user_"
            )
        )

        return


    if data.startswith("group_admin_remove_user_"):

        payload = data.replace("group_admin_remove_user_", "", 1)

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


        removed = disable_group_admin(group_id, target_user_id)


        if not removed:

            await query.message.reply_text("❌ Admin no encontrado o no editable.")

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Admin quitado correctamente.",
            reply_markup=build_group_admin_panel_keyboard()
        )

        return


    if data == "admin_support_tickets":

        tickets = fetch_recent_support_tickets()

        await send_clean_message(
            context,
            query.message.chat_id,
            build_support_tickets_text(tickets),
            reply_markup=InlineKeyboardMarkup(
                build_support_tickets_keyboard(tickets)
            )
        )

        return


    if data.startswith("admin_support_ai_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_ai_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        result = build_support_reply_suggestion(
            user_id,
            AI_ROLE_SUPERADMIN,
            ticket_id,
            group_id=ticket.get("group_id")
        )
        keyboard = [
            [InlineKeyboardButton("✍️ Usar como base", callback_data=f"admin_support_use_ai_{ticket_id}")],
            [InlineKeyboardButton("⬅️ Volver al ticket", callback_data=f"admin_support_ticket_{ticket_id}")]
        ]


        if result.get("interaction_id"):

            for label, callback_data in build_ai_feedback_keyboard_rows(result.get("interaction_id")):

                keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])


        await query.message.reply_text(
            "🤖 Borrador sugerido para soporte\n\n"
            f"{result.get('answer') or 'No tengo suficiente información para preparar un borrador.'}\n\n"
            "No se enviará automáticamente. Puedes usarlo como base y editarlo antes de responder.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data.startswith("admin_support_use_ai_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_use_ai_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Usa el borrador anterior como base, edítalo si hace falta y escribe ahora la respuesta final para el usuario.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Cancelar", callback_data=f"admin_support_ticket_{ticket_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("admin_support_ticket_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_ticket_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        await query.message.reply_text(
            build_support_ticket_detail_text(ticket),
            reply_markup=InlineKeyboardMarkup(
                build_support_ticket_keyboard(ticket)
            )
        )

        return


    if data.startswith("admin_support_reply_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_reply_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        if ticket.get("status") == "closed":

            await query.message.reply_text(
                "📁 Este ticket está cerrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🛟 Tickets abiertos",
                        callback_data="admin_support_tickets"
                    )]
                ])
            )

            return


        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Escribe ahora la respuesta para el usuario."
        )

        return


    if data.startswith("admin_support_close_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_close_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        update_support_ticket_status(
            ticket_id,
            "closed"
        )

        try:

            await context.bot.send_message(
                chat_id=ticket.get("user_id"),
                text=f"✅ Tu ticket #{ticket_id} ha sido cerrado."
            )

        except Exception as e:

            print("Error avisando cierre soporte:", e)


        await query.message.reply_text(
            f"✅ Ticket #{ticket_id} cerrado.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🛟 Tickets abiertos",
                    callback_data="admin_support_tickets"
                )]
            ])
        )

        return


    if data == "admin_commercial_promo_codes":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos promocionales\n\nCrea códigos para que dueños de grupos publiquen su comunidad sin pasar por checkout durante el periodo elegido.",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return


    if data.startswith("admin_commercial_promo_create_"):

        slug = data.replace("admin_commercial_promo_create_", "", 1)
        duration = COMMERCIAL_PROMO_DURATIONS.get(slug)


        if not duration:

            await query.message.reply_text(
                "❌ Duración no válida.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_commercial_promo_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        duration_days, duration_label = duration
        row = create_commercial_promo_code(duration_days, user_id)


        if not row:

            await query.message.reply_text("❌ Error creando código promocional.")

            return


        _code_id, code, _duration_days = row

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Código promocional creado\n\n"
            f"Código: {code}\n"
            f"Duración: {duration_label}\n"
            "Uso: 1 vez\n\n"
            "El dueño debe usarlo desde 📦 Configurar comunidad > 🎟 Tengo un código promocional.",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return


    if data == "admin_commercial_promo_active":

        rows = fetch_active_commercial_promo_codes()

        await send_clean_message(
            context,
            query.message.chat_id,
            build_commercial_promo_active_text(rows),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "Desactivar código",
                    callback_data="admin_commercial_promo_deactivate_menu"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_promo_codes"
                )]
            ])
        )

        return


    if data == "admin_commercial_promo_deactivate_menu":

        rows = fetch_active_commercial_promo_codes()

        await send_clean_message(
            context,
            query.message.chat_id,
            "❌ Desactivar código\n\nElige el código promocional que quieres desactivar.",
            reply_markup=build_commercial_promo_deactivate_keyboard(rows)
        )

        return


    if data.startswith("admin_commercial_promo_deactivate_"):

        code_id = extract_commercial_request_id(
            data,
            "admin_commercial_promo_deactivate_"
        )
        code = deactivate_commercial_promo_code(code_id)


        if not code:

            await query.message.reply_text("❌ Código promocional no encontrado.")

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            f"✅ Código desactivado: {code}",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return


    if data == "admin_commercial_requests":

        requests = fetch_pending_commercial_requests()

        await query.message.reply_text(
            build_commercial_requests_text(requests),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_requests_keyboard(requests)
            )
        )

        return


    if data == "admin_commercial_archived_requests":

        requests = fetch_archived_commercial_requests()

        await query.message.reply_text(
            build_archived_commercial_requests_text(requests),
            reply_markup=InlineKeyboardMarkup(
                build_archived_commercial_requests_keyboard(requests)
            )
        )

        return


    if data.startswith("admin_commercial_status_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_status_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_request_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return


    if data.startswith("admin_commercial_owner_groups_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_owner_groups_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_owner_groups_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📄 Ver detalle completo",
                    callback_data=f"admin_commercial_status_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver al panel de propietarios",
                    callback_data="admin_owners_panel"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_internal_note_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_internal_note_"
        )

        await query.message.reply_text(
            "📝 Añadir nota interna\n\n"
            "Este acceso deja claro dónde irá la nota interna. "
            "La edición de notas se conectará al flujo de texto seguro en una fase posterior.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📄 Ver detalle completo",
                    callback_data=f"admin_commercial_status_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver al panel de propietarios",
                    callback_data="admin_owners_panel"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_archive_confirm_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_confirm_"
        )

        request_row = archive_commercial_request(request_id, user_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            "🗄 Solicitud archivada.\n\n"
            "No se han borrado datos, grupo, owner ni conversación comercial.",
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return


    if data.startswith("admin_commercial_archive_cancel_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_cancel_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_request_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return


    if data.startswith("admin_commercial_archive_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        if is_commercial_request_archived(request_row):

            await query.message.reply_text(
                "📁 Esta solicitud ya está archivada.",
                reply_markup=InlineKeyboardMarkup(
                    build_commercial_review_keyboard(request_row)
                )
            )

            return


        await query.message.reply_text(
            "🗄 Finalizar solicitud\n\n"
            "Se archivará la solicitud comercial sin borrar datos, grupo, owner ni conversación comercial.",
            reply_markup=build_commercial_archive_confirm_keyboard(request_id)
        )

        return


    if data.startswith("admin_commercial_reopen_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reopen_"
        )

        request_row = reopen_archived_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud archivada no encontrada."
            )

            return


        await query.message.reply_text(
            "♻️ Solicitud reabierta.",
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return


    if data.startswith("admin_commercial_chat_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_chat_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        messages = fetch_commercial_request_messages(request_id)

        await query.message.reply_text(
            build_commercial_request_chat_text(request_row, messages),
            reply_markup=build_admin_commercial_request_chat_keyboard(request_id)
        )

        return


    if data.startswith("admin_commercial_reply_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reply_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        start_commercial_request_chat_reply(
            context,
            request_id,
            "admin"
        )

        await query.message.reply_text(
            f"✍️ Responder solicitud comercial #{request_id}\n\n"
            "Escribe ahora el mensaje para el solicitante."
        )

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


    if data.startswith("admin_commercial_group_limit_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_group_limit_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_group_limit_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_group_limit_keyboard(request_id)
            )
        )

        return


    if data.startswith("admin_commercial_set_group_limit_"):

        request_id, max_groups_allowed = extract_commercial_group_limit_selection(
            data
        )


        if not request_id or not max_groups_allowed:

            await query.message.reply_text(
                "❌ Cupo de grupos no válido."
            )

            return


        request_row = update_commercial_request_group_limit(
            request_id,
            max_groups_allowed
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            f"✅ Cupo actualizado a {max_groups_allowed} grupo(s).",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔎 Volver a solicitud",
                    callback_data=f"admin_commercial_review_{request_id}"
                )],
                [InlineKeyboardButton(
                    "🔢 Cambiar cupo",
                    callback_data=f"admin_commercial_group_limit_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_review_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_review_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_request_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return


    if data.startswith("admin_commercial_approve_trial_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_approve_trial_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        if is_commercial_request_advanced(request_row):

            await reply_duplicate_commercial_approval(query, request_id)

            return


        await query.message.reply_text(
            "✅ Aprobar prueba de comunidad\n\n"
            "Elige dónde quieres colocar esta comunidad inicialmente:\n\n"
            "🏠 Inicio: aparecerá directamente en /start.\n"
            "🔎 Explorar: aparecerá dentro de Explorar comunidades privadas.\n"
            "🙈 Oculta/Borrador: no aparecerá públicamente todavía.",
            reply_markup=InlineKeyboardMarkup(
                build_admin_trial_visibility_keyboard(request_id)
            )
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


    if data.startswith("admin_commercial_approve_custom_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_approve_custom_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        if is_commercial_request_advanced(request_row):

            await reply_duplicate_commercial_approval(query, request_id)

            return


        request_row = update_commercial_request_custom_approved(
            request_id,
            user_id
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "✅ Tu solicitud de bot personalizado ha sido aprobada. "
            "El siguiente paso será completar configuración y pago para activar el servicio."
        )

        await query.message.reply_text(
            "✅ Configuración aprobada.\n\n"
            "La solicitud queda en espera de configuración y pago.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
        )

        return


    if data.startswith("admin_commercial_reject_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reject_"
        )

        existing_request = fetch_commercial_request(request_id)


        if is_commercial_request_advanced(existing_request):

            await query.message.reply_text(
                "Esta solicitud ya está aprobada, configurada o archivada. No se ha rechazado.",
                reply_markup=InlineKeyboardMarkup(
                    build_commercial_review_keyboard(existing_request)
                )
            )

            return


        request_row = update_commercial_request_rejected(
            request_id,
            user_id
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "❌ Tu solicitud no ha sido aprobada por ahora.\n\n"
            "Puedes volver a intentarlo más adelante o contactar con soporte si necesitas revisar la propuesta."
        )

        await query.message.reply_text(
            "❌ Solicitud comercial rechazada.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
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

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT DISTINCT g.telegram_group_id, g.name

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


        for group_id, group_name in rows:

            keyboard.append([

                InlineKeyboardButton(

                    f"📦 {group_name}",

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


        await query.message.reply_text(

            "📦 Tus suscripciones activas:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # DETALLE DE SUSCRIPCIÓN
    # =========================

    if data.startswith("mysub_"):

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id
        mysub_parts = data.split("_")


        if len(mysub_parts) < 2 or not mysub_parts[1].lstrip("-").isdigit():

            await reply_with_recover_navigation(
                query,
                "⚠️ Esta opción ya no está disponible o no está configurada."
            )

            return

        telegram_group_id = int(
            mysub_parts[1]
        )


        try:

            with conn.cursor() as cur:

                # =========================
                # OBTENER NOMBRE GRUPO
                # =========================

                cur.execute("""

                    SELECT name

                    FROM groups

                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                group_row = cur.fetchone()


                if not group_row:

                    await query.message.reply_text(
                        "❌ Grupo no encontrado."
                    )

                    return


                group_name = group_row[0]


                # =========================
                # OBTENER group_id REAL
                # =========================

                cur.execute("""

                    SELECT id

                    FROM groups

                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                group_id_row = cur.fetchone()


                if not group_id_row:

                    await query.message.reply_text(
                        "❌ Grupo no encontrado."
                    )

                    return


                real_group_id = group_id_row[0]


                # =========================
                # OBTENER EXPIRATION
                # =========================

                cur.execute("""

                    SELECT expiration

                    FROM users

                    WHERE user_id=%s
                    AND group_id=%s
                    AND COALESCE(subscription_active, FALSE)=TRUE
                    AND (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    LIMIT 1

                """, (

                    user_id,
                    real_group_id

                ))

                user_row = cur.fetchone()


                if not user_row:

                    await reply_with_recover_navigation(
                        query,
                        "No tienes una suscripción activa para este grupo."
                    )

                    return


                expiration = user_row[0]


                # =========================
                # OBTENER LINK ACTUAL
                # =========================

                cur.execute("""

                    SELECT invite_link

                    FROM invite_links

                    WHERE user_id=%s
                    AND (
                        group_id=%s
                        OR telegram_group_id=%s
                        OR group_id=%s
                    )
                    AND is_active=TRUE

                    ORDER BY created_at DESC

                    LIMIT 1

                """, (

                    user_id,
                    real_group_id,
                    telegram_group_id,
                    telegram_group_id

                ))

                link_row = cur.fetchone()


        except Exception as e:

            print("Error cargando detalle suscripción:", e)

            await query.message.reply_text(
                "❌ Error cargando suscripción."
            )

            return


        # =========================
        # FORMATEAR TIEMPO
        # =========================

        tiempo_texto = format_tiempo_restante(
            expiration
        )


        # =========================
        # REVOCAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link

                FROM invite_links

                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
                telegram_group_id

            ))

            old_links = cur.fetchall()


            for (old_link,) in old_links:

                try:

                    revoke_link(
                        telegram_group_id,
                        old_link
                    )

                    cur.execute("""

                        UPDATE invite_links

                        SET is_active=FALSE,
                            revoked_at=NOW()

                        WHERE invite_link=%s

                    """, (old_link,))

                except Exception as e:

                    print(
                        "Error revocando link:",
                        e
                    )


            cur.execute("""

                DELETE FROM invite_links

                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
                telegram_group_id

            ))

            conn.commit()


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        max_expire = int(time.time()) + 180

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        # =========================
        # CREAR LINK NUEVO
        # =========================

        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=expire_seconds,
            member_limit=1
        )


        if not link:

            await query.message.reply_text(
                "❌ Error creando acceso."
            )

            return


        # =========================
        # GUARDAR LINK NUEVO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, telegram_group_id, invite_link)

                VALUES (%s, %s, %s, %s)

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
                link

            ))

            conn.commit()


        keyboard = [

            [

                InlineKeyboardButton(

                    "💬 Ayuda sobre este menú",

                    callback_data=CALLBACK_SUBSCRIPTIONS_HELP

                )

            ],

            [

                InlineKeyboardButton(

                    "⬅️ Volver",

                    callback_data="mis_subs"

                )

            ]

        ]


        mensaje = (

            f"📦 {group_name}\n\n"

            f"⏳ Tiempo restante:\n"
            f"{tiempo_texto}\n\n"

            "⚠️ Este link expirará en 3 minutos.\n\n"

            f"🔗 Tu nuevo acceso:\n"
            f"{link}"

        )


        await query.message.reply_text(

            mensaje,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if data.startswith("free_access_"):

        try:

            await query.message.delete()

        except Exception:

            pass


        try:

            group_id = int(data.replace("free_access_", "", 1))

        except Exception:

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
                AND COALESCE(is_free_group, FALSE)=TRUE
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
                "free_access"
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


        group_callback_parts = data.split("_")
        group_id = int(group_callback_parts[1])


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

                    SELECT COALESCE(is_free_group, FALSE)
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
                           currency

                    FROM plans

                    WHERE group_id=%s
                    AND is_active=TRUE

                    ORDER BY id ASC

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
                "⚠️ Este grupo no tiene planes disponibles."
            )

            return


        keyboard = []
        paypal_available = is_paypal_group_checkout_available(group_id)
        revolut_available = is_revolut_group_checkout_available(group_id)
        changenow_available = is_changenow_group_checkout_available(group_id)
        guardarian_available = is_guardarian_group_checkout_available(group_id)


        for plan_id, name, price_id, amount, currency in plans:

            if amount and currency:

                button_text = f"{name} — {amount} {currency}"

            else:

                button_text = name


            keyboard.append([

                InlineKeyboardButton(

                    f"💳 Tarjeta / Stripe — {button_text}",

                    callback_data=price_id

                )

            ])


            if paypal_available:

                keyboard.append([

                    InlineKeyboardButton(

                        f"🅿️ PayPal — {button_text}",

                        callback_data=f"paypal_group_plan_{group_id}_{plan_id}"

                    )

                ])


            if revolut_available:

                keyboard.append([

                    InlineKeyboardButton(

                        f"🏦 Revolut — {button_text}",

                        callback_data=f"revolut_group_plan_{group_id}_{plan_id}"

                    )

                ])


            if changenow_available:

                keyboard.append([

                    InlineKeyboardButton(

                        f"💱 Cripto / ChangeNOW — {button_text}",

                        callback_data=f"changenow_group_plan_{group_id}_{plan_id}"

                    )

                ])


            if guardarian_available:

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


        intro_text = (
            "Selecciona un plan:\n\n"
            "💳 Pagos tradicionales: tarjeta/Stripe, PayPal o Revolut.\n"
            "🪙 Cripto / USDT: ChangeNOW para cripto y Guardarian para tarjeta EUR con liquidación USDT.\n"
            "Solo verás métodos activos para esta comunidad."
        )


        if access_state.get("subscription_status") == "expired":

            intro_text = (
                "⚠️ Tu acceso anterior está vencido.\n\n"
                "Puedes renovar el acceso seleccionando un plan:\n\n"
                "💳 Pagos tradicionales: tarjeta/Stripe, PayPal o Revolut.\n"
                "🪙 Cripto / USDT: ChangeNOW para cripto y Guardarian para tarjeta EUR con liquidación USDT.\n"
                "Solo verás métodos activos para esta comunidad."
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

        try:

            group_id = int(data.replace("payment_status_group_", "", 1))

        except Exception:

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

    if data == "recover_access":

        user_id = query.from_user.id

        with conn.cursor() as cur:

            cur.execute("""

                SELECT expiration
                FROM users
                WHERE user_id=%s
                AND group_id=%s
                AND COALESCE(subscription_active, FALSE)=TRUE
                AND (
                    expiration IS NULL
                    OR expiration > NOW()
                )

                LIMIT 1

            """, (user_id, get_group_id()))

            row = cur.fetchone()

        if not row:

            await reply_with_recover_navigation(
                query,
                "No tienes una suscripción activa para este grupo."
            )

            return


        expiration = row[0]

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s
                ORDER BY created_at DESC
                LIMIT 1

            """, (

                user_id,
                get_group_id()

            ))

            link_row = cur.fetchone()


        # =========================
        # REVOCAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            old_links = cur.fetchall()


        for (old_link,) in old_links:

            try:

                revoke_telegram_invite_link(
                    TOKEN,
                    get_group_id(),
                    old_link
                )

            except Exception as e:

                print(
                    "Error revocando link:",
                    e
                )


        # =========================
        # BORRAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            conn.commit()


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        max_expire = int(time.time()) + 180

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        # =========================
        # CREAR LINK NUEVO TEMPORAL
        # =========================

        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            get_group_id(),
            expire_seconds=expire_seconds,
            member_limit=1
        )


        if not link:

            await query.message.reply_text(
                "❌ Error creando acceso."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, invite_link)

                VALUES (%s, %s, %s)

            """, (

                user_id,
                get_group_id(),
                link

            ))

            conn.commit()


        await query.message.reply_text(

            f"🔗 Tu acceso VIP:\n{link}"

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

    if data == "admin_view_groups":

        try:
            await query.message.delete()
        except:
            pass

        try:

            with conn.cursor() as cur:

                groups = fetch_admin_groups_for_permissions(
                    user_id,
                    ["can_manage_groups", "can_manage_plans"]
                )

            log_event(
                "admin_view_groups_loaded",
                category="admin",
                severity="info",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Listado de grupos cargado desde panel admin.",
                metadata={
                    "groups_count": len(groups)
                }
            )

        except Exception as e:

            log_event(
                "admin_view_groups_error",
                category="admin",
                severity="error",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Error cargando grupos desde panel admin.",
                metadata={
                    "error": str(e)
                }
            )

            await query.message.reply_text(
                f"❌ Error cargando grupos:\n{str(e)}"
            )

            return


        if not groups:

            await query.message.reply_text(
                "⚠️ No hay grupos registrados."
            )

            return


        texto = "📋 GRUPOS REGISTRADOS\n\n"


        try:

            for group_id, name, telegram_id in groups:

                texto += (

                    f"🆔 ID interno: {group_id}\n"
                    f"📦 Nombre: {name}\n"
                    f"📡 Telegram ID: {telegram_id}\n\n"

                )

        except Exception as e:

            print("ERROR construyendo texto:", e)

            await query.message.reply_text(
                f"❌ Error procesando grupos:\n{str(e)}"
            )

            return


        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="menu_groups"
            )]

        ]


        await query.message.reply_text(

            texto,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

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


    if data.startswith("group_user_code_select_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_user_code_select_group_"
        )


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_manage_codes"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar códigos en esta comunidad.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_group_user_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        group = set_group_user_promo_context(
            context,
            group_id,
            step="panel"
        )


        if not group:

            await query.message.reply_text(
                "❌ Grupo no encontrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_group_user_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        _group_id, group_name, _telegram_group_id = group

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos de mi grupo\n\n"
            f"Grupo: {group_name or group_id}\n\n"
            "Crea códigos para usuarios finales de esta comunidad.",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

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


    if data == "owner_panel_satisfaction":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )

        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar encuestas de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            "😊 Encuestas de comunidad\n\n"
            "Envía encuestas solo a usuarios de esta comunidad.\n\n"
            "Para que sea justo, el bot nunca reenvía por defecto a usuarios que ya respondieron.",
            reply_markup=build_owner_satisfaction_panel_keyboard()
        )

        return


    if data in (
        "owner_satisfaction_send_pending",
        "owner_satisfaction_resend_incomplete",
        "owner_satisfaction_send_never_sent",
        "owner_satisfaction_force_new_cycle"
    ):

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )

        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para enviar encuestas de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        mode_by_callback = {
            "owner_satisfaction_send_pending": "pending",
            "owner_satisfaction_resend_incomplete": "resend_incomplete",
            "owner_satisfaction_send_never_sent": "never_sent",
            "owner_satisfaction_force_new_cycle": "pending"
        }
        mode = mode_by_callback[data]
        campaign_id = "default"

        if data == "owner_satisfaction_force_new_cycle":
            campaign_id = f"group_{group_id}_cycle_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        survey_id = create_customer_satisfaction_survey(
            user_id,
            "global",
            group_id=group_id,
            send_mode=mode,
            campaign_id=campaign_id
        )
        targeting = build_customer_satisfaction_targeting(
            "global",
            mode,
            group_id=group_id,
            campaign_id=campaign_id
        )

        mode_text = {
            "pending": "Enviar a pendientes",
            "resend_incomplete": "Reenviar a no completados",
            "never_sent": "Enviar solo a nunca enviados"
        }.get(mode, mode)

        await send_clean_message(
            context,
            query.message.chat_id,
            "📤 Confirmar encuesta de comunidad\n\n"
            f"Modo: {mode_text}\n"
            f"Comunidad: {group_id}\n"
            f"Campaña: {campaign_id}\n\n"
            f"Se enviará la encuesta a {targeting['target_count']} usuarios.\n"
            f"Se omitirán {targeting['skipped_completed']} usuarios que ya la completaron.\n"
            f"Se omitirán {targeting['skipped_already_sent']} usuarios que ya la recibieron en este ciclo.\n\n"
            "¿Confirmas el envío?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar envío", callback_data=f"owner_satisfaction_confirm_{survey_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="owner_panel_satisfaction")]
            ])
        )

        return


    if data == "owner_satisfaction_delivery_status":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )

        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver encuestas de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_delivery_status_text("global", group_id=group_id),
            reply_markup=build_owner_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("owner_satisfaction_confirm_"):

        try:
            survey_id = int(data.replace("owner_satisfaction_confirm_", "", 1))
        except Exception:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        survey = fetch_customer_satisfaction_survey(survey_id)

        if not survey or not survey["group_id"]:
            await query.message.reply_text(
                "❌ Encuesta de comunidad no encontrada.",
                reply_markup=build_owner_satisfaction_panel_keyboard()
            )
            return

        if not user_has_group_permission_any(
            user_id,
            survey["group_id"],
            ["can_manage_groups", "can_view_logs"]
        ):
            await query.message.reply_text(
                "⛔ No tienes permiso para enviar encuestas de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )
            return

        if survey["status"] != "draft":
            await query.message.reply_text(
                "⚠️ Esta encuesta ya fue enviada o está en proceso. No se duplicará.",
                reply_markup=build_owner_satisfaction_panel_keyboard()
            )
            return

        if not mark_customer_satisfaction_survey_sending(survey_id):
            await query.message.reply_text(
                "⚠️ Esta encuesta ya se está enviando o ya fue enviada. No se duplicará.",
                reply_markup=build_owner_satisfaction_panel_keyboard()
            )
            return

        targeting = build_customer_satisfaction_targeting(
            survey["audience"],
            survey["send_mode"],
            group_id=survey["group_id"],
            campaign_id=survey["campaign_id"]
        )
        sent_count = 0
        failed_count = 0

        for skipped_user_id in targeting["completed_users"]:
            mark_customer_satisfaction_delivery_skipped(
                survey_id,
                skipped_user_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                "skipped_completed"
            )

        already_sent_users = set(targeting["sent_current_cycle"]) - set(targeting["targets"])
        already_sent_users -= set(targeting["completed_users"])

        for skipped_user_id in sorted(already_sent_users):
            mark_customer_satisfaction_delivery_skipped(
                survey_id,
                skipped_user_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                "skipped_already_sent"
            )

        for recipient_id in targeting["targets"]:
            reserved = reserve_customer_satisfaction_delivery(
                survey_id,
                recipient_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                allow_existing=survey["send_mode"] == "resend_incomplete"
            )

            if not reserved:
                continue

            try:
                await context.bot.send_message(
                    chat_id=recipient_id,
                    text=(
                        "Queremos mejorar esta comunidad. Responde esta encuesta rápida de 1 a 5.\n\n"
                        "Tus respuestas ayudan a mejorar acceso, soporte, pagos y seguridad."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📝 Responder encuesta", callback_data=f"satisfaction_start_{survey_id}")]
                    ])
                )
                sent_count += 1
                log_user_event_by_ids(
                    recipient_id,
                    "survey_sent",
                    event_key="customer_satisfaction_group",
                    group_id=survey["group_id"],
                    metadata={
                        "survey_id": survey_id,
                        "campaign_id": survey["campaign_id"],
                        "send_mode": survey["send_mode"]
                    }
                )
            except Exception as e:
                failed_count += 1
                mark_customer_satisfaction_delivery_failed(
                    survey_id,
                    recipient_id,
                    survey["group_id"],
                    survey["campaign_id"],
                    e
                )
                log_event(
                    "survey_send_failed",
                    category="satisfaction",
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=recipient_id,
                    group_id=survey["group_id"],
                    message="No se pudo entregar una encuesta de comunidad.",
                    metadata={"survey_id": survey_id, "error": str(e)[:200]}
                )

        update_customer_satisfaction_sent_counts(
            survey_id,
            sent_count,
            failed_count,
            targeting["skipped_completed"],
            targeting["skipped_already_sent"]
        )

        log_event(
            "survey_sent",
            category="satisfaction",
            severity="info",
            actor_user_id=user_id,
            group_id=survey["group_id"],
            message="Encuesta de comunidad enviada.",
            metadata={
                "survey_id": survey_id,
                "campaign_id": survey["campaign_id"],
                "send_mode": survey["send_mode"],
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_completed": targeting["skipped_completed"],
                "skipped_already_sent": targeting["skipped_already_sent"]
            }
        )
        record_beta_event(
            "survey_sent",
            severity="info",
            user_id=user_id,
            group_id=survey["group_id"],
            message="Encuesta de comunidad enviada.",
            metadata={
                "survey_id": survey_id,
                "campaign_id": survey["campaign_id"],
                "send_mode": survey["send_mode"],
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_completed": targeting["skipped_completed"],
                "skipped_already_sent": targeting["skipped_already_sent"]
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Encuesta de comunidad enviada\n\n"
            f"Enviados: {sent_count}\n"
            f"Fallidos: {failed_count}\n"
            f"Omitidos por completada: {targeting['skipped_completed']}\n"
            f"Omitidos por ya enviada: {targeting['skipped_already_sent']}",
            reply_markup=build_owner_satisfaction_panel_keyboard()
        )

        return


    if data in ("owner_panel_audit", "owner_panel_audit_detail"):

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para auditar este panel de comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        report = context.user_data.get("owner_panel_audit_report")


        if data == "owner_panel_audit" or not report or report.get("group_id") != group_id:

            report = build_owner_panel_audit_report(user_id, group_id)
            context.user_data["owner_panel_audit_report"] = report


        text = (
            format_owner_panel_audit_detail(report)
            if data == "owner_panel_audit_detail"
            else format_owner_panel_audit_summary(report)
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=build_owner_panel_audit_keyboard()
        )

        return


    if data.startswith("owner_panel_help_"):

        section = data.replace("owner_panel_help_", "", 1)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_panel_help_text(section),
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    if data in (
        "owner_panel_users",
        "owner_panel_security",
        "owner_panel_backup",
        "owner_panel_general"
    ):

        title, description, required_permissions, section = OWNER_PANEL_SECTIONS[data]

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            required_permissions
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para abrir esta sección de la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id


        if data == "owner_panel_users":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_users_panel_text(group_id),
                reply_markup=build_owner_section_keyboard(
                    user_id,
                    group_id,
                    section
                )
            )

            return


        if data == "owner_panel_security":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_security_text(group_id),
                reply_markup=build_owner_security_keyboard(group_id)
            )

            return


        if data == "owner_panel_backup":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_backup_panel_text(group_id),
                reply_markup=build_owner_section_keyboard(
                    user_id,
                    group_id,
                    section
                )
            )

            return


        if data == "owner_panel_general":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_general_text(group_id),
                reply_markup=build_owner_general_keyboard(group_id)
            )

            return


    if data == "owner_panel_commercial_config" or data == "owner_panel_access_type_info":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_manage_plans", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para abrir la configuración comercial de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_commercial_config_text(group_id),
            reply_markup=build_owner_commercial_config_keyboard(group_id, user_id)
        )

        return


    if data.startswith("owner_group_users_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_users_"
        )


        if not user_can_view_group_panel(user_id, group_id, ["can_view_users", "can_manage_users"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver usuarios de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        group = fetch_group_basic_info(group_id)
        group_name = group[1] if group else f"Grupo {group_id}"

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id,
                           username,
                           first_name,
                           expiration,
                           subscription_active
                    FROM users
                    WHERE group_id=%s
                    ORDER BY expiration DESC NULLS LAST,
                             created_at DESC
                    LIMIT 50

                """, (group_id,))

                rows = cur.fetchall()

        except Exception as e:

            print("Error cargando usuarios de comunidad:", e)

            await query.message.reply_text(
                "❌ No he podido cargar usuarios de esta comunidad ahora mismo.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Volver a usuarios y accesos", callback_data="owner_panel_users")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])


        if not rows:

            await send_clean_message(
                context,
                query.message.chat_id,
                f"👥 Usuarios de esta comunidad\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\nTodavía no hay usuarios activos registrados en esta comunidad.",
                reply_markup=keyboard
            )

            return


        text = f"👥 Usuarios de esta comunidad\n\nComunidad: {group_name or f'Grupo {group_id}'}\nUsuarios mostrados: {len(rows)}\n\n"


        for member_user_id, username, first_name, expiration, subscription_active in rows:

            name = first_name or "Sin nombre"

            if username:

                name += f" (@{username})"


            expiration_text = expiration.strftime("%Y-%m-%d") if expiration else "♾️ Permanente"
            active_text = "activo" if subscription_active else "registrado"

            text += (
                f"Usuario: {member_user_id}\n"
                f"Nombre: {name}\n"
                f"Acceso: {active_text}\n"
                f"Expira: {expiration_text}\n\n"
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=keyboard
        )

        return


    if data.startswith("owner_group_logs_"):

        payload = data.replace("owner_group_logs_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[1].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar los logs de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        log_filter = parts[0]
        group_id = int(parts[1])


        if not user_can_view_group_panel(user_id, group_id, ["can_view_logs"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver logs de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id
        context.user_data["selected_group_admin"] = group_id

        title = "📜 Actividad reciente del grupo"
        category_filter = None
        event_types = None


        if log_filter == "access":

            title = "👥 Logs de accesos"
            category_filter = "access"

        elif log_filter == "payment":

            title = "💳 Logs de pagos"
            category_filter = "payment"

        elif log_filter == "support":

            title = "🛟 Logs de soporte"
            event_types = ["support_ticket_created"]

        elif log_filter == "security":

            title = "🛡 Seguridad / errores"
            event_types = [
                "access_unauthorized",
                "location_check_failed",
                "location_region_mismatch",
                "location_geocode_failed",
                "owner_location_gate_updated",
                "telegram_handler_error"
            ]


        rows = fetch_owner_group_logs(
            group_id,
            category_filter=category_filter,
            event_types=event_types
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_group_logs_text(group_id, rows, title),
            reply_markup=build_owner_group_logs_keyboard()
        )

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
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
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


    if data.startswith("owner_group_payment_methods_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_payment_methods_"
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver métodos de pago de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        group_id, group_name, telegram_group_id = group

        keyboard_rows = []
        provider_statuses = list_group_payment_provider_statuses(group_id)
        grouped_provider_statuses = group_payment_provider_statuses_by_ux(
            provider_statuses
        )


        for group_key in PAYMENT_UX_GROUP_ORDER:

            for provider_status in grouped_provider_statuses.get(group_key) or []:

                provider = provider_status.get("provider")
                label = provider_status.get("label") or provider
                group_label = PAYMENT_UX_GROUP_LABELS.get(group_key, "Métodos")

                keyboard_rows.append([
                    InlineKeyboardButton(
                        f"⚙️ {group_label} · {label}",
                        callback_data=f"owner_group_payment_provider_{group_id}_{provider}"
                    )
                ])


        keyboard_rows.extend([
            [InlineKeyboardButton("🎟 Códigos y promociones", callback_data="owner_panel_codes")],
            [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        keyboard = InlineKeyboardMarkup(keyboard_rows)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_group_payment_methods_text(
                group_id,
                group_name,
                telegram_group_id,
                owner_user_id
            ),
            reply_markup=keyboard
        )

        return


    if data.startswith("owner_group_payment_provider_"):

        payload = data.replace("owner_group_payment_provider_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        provider = parts[1]
        group = fetch_group_basic_info(group_id)
        owner_user_id = get_group_owner_user_id(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver este método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        provider_statuses = {
            item.get("provider"): item
            for item in list_group_payment_provider_statuses(group_id)
        }
        provider_status = provider_statuses.get(provider)


        if not provider_status:

            await query.message.reply_text(
                "⚠️ Proveedor no disponible.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id
        _group_id, group_name, _telegram_group_id = group

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔌 Configurar / conectar", callback_data=f"owner_group_payment_connect_{group_id}_{provider}")],
            [InlineKeyboardButton("🚫 Desactivar", callback_data=f"owner_group_payment_disable_{group_id}_{provider}")],
            [InlineKeyboardButton("🗑 Borrar configuración", callback_data=f"owner_group_payment_delete_{group_id}_{provider}")],
            [InlineKeyboardButton("⬅️ Volver a métodos de pago", callback_data=f"owner_group_payment_methods_{group_id}")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            build_group_payment_provider_detail_text(
                group_id,
                group_name,
                provider_status
            ),
            reply_markup=keyboard
        )

        return


    if data.startswith("owner_group_payment_connect_"):

        payload = data.replace("owner_group_payment_connect_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        provider = parts[1]
        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para configurar este método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        ensure_group_payment_provider_config(
            owner_user_id or user_id,
            group_id,
            provider,
            status="pending"
        )
        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        provider_name = provider.upper()


        if provider == OWNER_PAYMENT_PROVIDER_PAYPAL:

            if not has_payment_encryption_key():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ PayPal no puede configurarse todavía\n\n"
                    "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot.\n\n"
                    "Por seguridad no se piden ni se guardan credenciales reales sin cifrado.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Volver a PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                    ])
                )

                return


            clear_owner_payment_provider_wizard(context)
            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_PAYPAL
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_step"] = "mode"
            context.user_data["owner_payment_payload"] = {}

            await send_clean_message(
                context,
                query.message.chat_id,
                "🔌 Conectar PayPal al grupo\n\n"
                "Necesitarás estos datos de tu cuenta PayPal Developer:\n"
                "- PAYPAL_CLIENT_ID\n"
                "- PAYPAL_CLIENT_SECRET\n"
                "- PAYPAL_WEBHOOK_ID opcional, para una fase posterior\n"
                "- modo sandbox o live\n\n"
                "Las claves se cifran antes de guardarse, no se muestran completas y no deben enviarse por soporte.\n\n"
                "Importante: esto solo prepara la configuración. Todavía no activa cobros PayPal reales para compradores del grupo.",
                reply_markup=build_owner_paypal_mode_keyboard(group_id)
            )

            return

        if provider == OWNER_PAYMENT_PROVIDER_REVOLUT:

            if not has_payment_encryption_key():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ Revolut no puede configurarse todavía\n\n"
                    "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot.\n\n"
                    "Por seguridad no se piden ni se guardan credenciales reales sin cifrado.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Volver a Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                    ])
                )

                return


            clear_owner_payment_provider_wizard(context)
            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_REVOLUT
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_step"] = "mode"
            context.user_data["owner_payment_payload"] = {}

            await send_clean_message(
                context,
                query.message.chat_id,
                "🔌 Conectar Revolut al grupo\n\n"
                "Necesitarás estos datos de tu cuenta Revolut Merchant:\n"
                "- REVOLUT_API_KEY\n"
                "- REVOLUT_WEBHOOK_SECRET\n"
                "- modo sandbox o live\n"
                "- REVOLUT_BASE_URL opcional\n\n"
                "Las claves se cifran antes de guardarse, no se muestran completas y no deben enviarse por soporte.\n\n"
                "Importante: estas credenciales son del owner/grupo y no usan las variables Railway de la plataforma.",
                reply_markup=build_owner_revolut_mode_keyboard(group_id)
            )

            return

        if provider == OWNER_PAYMENT_PROVIDER_CHANGENOW:

            if not has_payment_encryption_key():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ ChangeNOW no puede configurarse todavía\n\n"
                    "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot.\n\n"
                    "Por seguridad no se piden ni se guardan credenciales reales sin cifrado.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                    ])
                )

                return


            clear_owner_payment_provider_wizard(context)
            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_CHANGENOW
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_step"] = "mode"
            context.user_data["owner_payment_payload"] = {}

            await send_clean_message(
                context,
                query.message.chat_id,
                build_changenow_tutorial_text("esta comunidad")
                + "\n\nPulsa el modo de tasa que quieres preparar para esta comunidad.",
                reply_markup=build_owner_changenow_mode_keyboard(group_id)
            )

            return


        if provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN:

            if not has_payment_encryption_key():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ Guardarian no puede configurarse todavía\n\n"
                    "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot.\n\n"
                    "Por seguridad no se piden ni se guardan credenciales reales sin cifrado.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                    ])
                )

                return


            clear_owner_payment_provider_wizard(context)
            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_GUARDARIAN
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_step"] = "mode"
            context.user_data["owner_payment_payload"] = {}

            await send_clean_message(
                context,
                query.message.chat_id,
                build_guardarian_tutorial_text("esta comunidad")
                + "\n\nPulsa el entorno que quieres preparar para esta comunidad.",
                reply_markup=build_owner_guardarian_mode_keyboard(group_id)
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🔌 Configurar método de pago del grupo\n\n"
            f"Proveedor: {provider_name}\n\n"
            "Las credenciales propias del owner se introducirán desde el bot, no en Railway.\n\n"
            "Por seguridad, todavía no se piden secretos en esta fase. Antes de guardar credenciales reales debe existir PAYMENT_CONFIG_ENCRYPTION_KEY y el wizard debe borrar/ocultar mensajes sensibles.\n\n"
            "Para PayPal se necesitará client_id, client_secret, webhook_id y modo sandbox/live. No se mostrarán secretos completos en Telegram.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver al proveedor", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_changenow_mode_"):

        payload = data.replace("owner_payment_changenow_mode_", "", 1)
        mode, _, group_text = payload.partition("_")


        if mode not in ("fixed", "float") or not group_text.isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el modo de ChangeNOW.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(group_text)
        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⛔ No tienes permiso para configurar ChangeNOW en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not context.user_data.get("configuring_owner_payment_provider"):

            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_CHANGENOW
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_payload"] = {}


        owner_payload = context.user_data.get("owner_payment_payload") or {}
        owner_payload["rate_mode"] = mode
        context.user_data["owner_payment_payload"] = owner_payload
        context.user_data["owner_payment_step"] = "api_key"

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "Modo seleccionado: fixed\n\n"
                if mode == "fixed"
                else "Modo seleccionado: floating\n\n"
            )
            + "Envía ahora la API key de ChangeNOW. Intentaré borrar el mensaje después de recibirlo.",
            reply_markup=build_owner_changenow_cancel_keyboard(group_id)
        )

        return


    if data.startswith("owner_payment_guardarian_mode_"):

        payload = data.replace("owner_payment_guardarian_mode_", "", 1)
        mode, _, group_text = payload.partition("_")


        if mode not in ("sandbox", "live") or not group_text.isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el modo de Guardarian.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(group_text)
        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⛔ No tienes permiso para configurar Guardarian en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not context.user_data.get("configuring_owner_payment_provider"):

            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_GUARDARIAN
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_payload"] = {}


        owner_payload = context.user_data.get("owner_payment_payload") or {}
        owner_payload["mode"] = mode
        owner_payload["fiat_currency"] = "EUR"
        owner_payload["payout_currency"] = "USDT"
        context.user_data["owner_payment_payload"] = owner_payload
        context.user_data["owner_payment_step"] = "api_key"

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "Modo seleccionado: sandbox\n\n"
                if mode == "sandbox"
                else "Modo seleccionado: live\n\n"
            )
            + "Envía ahora la API key de Guardarian. Intentaré borrar el mensaje después de recibirlo.",
            reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
        )

        return


    if data.startswith("owner_payment_paypal_mode_"):

        payload = data.replace("owner_payment_paypal_mode_", "", 1)
        mode, _, group_text = payload.partition("_")


        if mode not in ("sandbox", "live") or not group_text.isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el modo de PayPal.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(group_text)
        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⛔ No tienes permiso para configurar PayPal en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not context.user_data.get("configuring_owner_payment_provider"):

            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_PAYPAL
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_payload"] = {}


        owner_payload = context.user_data.get("owner_payment_payload") or {}
        owner_payload["mode"] = mode
        context.user_data["owner_payment_payload"] = owner_payload
        context.user_data["owner_payment_step"] = "client_id"

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "Modo seleccionado: sandbox\n\n"
                if mode == "sandbox"
                else "Modo seleccionado: live\n\n"
            )
            + "Envía ahora el PAYPAL_CLIENT_ID.\n\n"
            + "Intentaré borrar el mensaje del chat después de recibirlo para no dejar datos sensibles visibles.",
            reply_markup=build_owner_paypal_cancel_keyboard(group_id)
        )

        return


    if data.startswith("owner_payment_revolut_mode_"):

        payload = data.replace("owner_payment_revolut_mode_", "", 1)
        mode, _, group_text = payload.partition("_")


        if mode not in ("sandbox", "live") or not group_text.isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el modo de Revolut.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(group_text)
        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⛔ No tienes permiso para configurar Revolut en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not context.user_data.get("configuring_owner_payment_provider"):

            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_REVOLUT
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_payload"] = {}


        owner_payload = context.user_data.get("owner_payment_payload") or {}
        owner_payload["mode"] = mode
        context.user_data["owner_payment_payload"] = owner_payload
        context.user_data["owner_payment_step"] = "api_key"

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "Modo seleccionado: sandbox\n\n"
                if mode == "sandbox"
                else "Modo seleccionado: live\n\n"
            )
            + "Envía ahora la REVOLUT_API_KEY del comercio.\n\n"
            + "Intentaré borrar el mensaje del chat después de recibirlo para no dejar datos sensibles visibles.",
            reply_markup=build_owner_revolut_cancel_keyboard(group_id)
        )

        return


    if data.startswith("owner_payment_changenow_cancel_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_changenow_cancel_"
        )
        clear_owner_payment_provider_wizard(context)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración de ChangeNOW cancelada. No se ha guardado ningún secreto.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_guardarian_cancel_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_guardarian_cancel_"
        )
        clear_owner_payment_provider_wizard(context)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración de Guardarian cancelada. No se ha guardado ningún secreto.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_paypal_cancel_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_paypal_cancel_"
        )
        clear_owner_payment_provider_wizard(context)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración de PayPal cancelada. No se ha guardado ningún secreto.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_revolut_cancel_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_revolut_cancel_"
        )
        clear_owner_payment_provider_wizard(context)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración de Revolut cancelada. No se ha guardado ningún secreto.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_changenow_save_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_changenow_save_"
        )
        owner_user_id = get_group_owner_user_id(group_id)


        if not group_id or (not is_super_admin(user_id) and owner_user_id != user_id):

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⛔ No tienes permiso para guardar ChangeNOW en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        provider = context.user_data.get("owner_payment_provider")
        payload = context.user_data.get("owner_payment_payload") or {}


        if provider != OWNER_PAYMENT_PROVIDER_CHANGENOW or context.user_data.get("owner_payment_group_id") != group_id:

            await query.message.reply_text(
                "⚠️ No hay una configuración de ChangeNOW lista para guardar.",
                reply_markup=build_owner_changenow_cancel_keyboard(group_id)
            )

            return


        required_keys = ("rate_mode", "api_key", "payout_currency", "payout_network", "payout_wallet", "payin_currency", "payin_network")


        if any(not payload.get(key) for key in required_keys):

            await query.message.reply_text(
                "⚠️ Faltan datos para guardar ChangeNOW. Vuelve a iniciar la conexión.",
                reply_markup=build_owner_changenow_cancel_keyboard(group_id)
            )

            return


        if not has_payment_encryption_key():

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⚠️ Falta PAYMENT_CONFIG_ENCRYPTION_KEY. No se guardan credenciales sin cifrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        safe_config = {
            "provider": OWNER_PAYMENT_PROVIDER_CHANGENOW,
            "rate_mode": payload.get("rate_mode"),
            "api_key": payload.get("api_key"),
            "payout_currency": payload.get("payout_currency"),
            "payout_network": payload.get("payout_network"),
            "payout_wallet": payload.get("payout_wallet"),
            "payin_currency": payload.get("payin_currency"),
            "payin_network": payload.get("payin_network"),
            "manual_only": True
        }


        try:

            encrypted_config = encrypt_provider_config(safe_config)
            masked_summary = (
                f"payin={payload.get('payin_currency')}/{payload.get('payin_network')}; "
                f"payout={payload.get('payout_currency')}/{payload.get('payout_network')}; "
                f"wallet={mask_secret_value(payload.get('payout_wallet'))}; "
                "manual_review=on"
            )
            saved = save_group_payment_provider_encrypted_config(
                owner_user_id or user_id,
                group_id,
                OWNER_PAYMENT_PROVIDER_CHANGENOW,
                encrypted_config,
                masked_summary,
                public_config_json={
                    "rate_mode": payload.get("rate_mode"),
                    "payin_currency": payload.get("payin_currency"),
                    "payin_network": payload.get("payin_network"),
                    "payout_currency": payload.get("payout_currency"),
                    "payout_network": payload.get("payout_network"),
                    "manual_review_required": True,
                    "checkout_enabled": True,
                    "webhook_configured": False
                },
                verified_by=user_id
            )

        except Exception:

            saved = False

        clear_owner_payment_provider_wizard(context)


        if saved:

            log_event(
                "group_payment_provider_credentials_saved",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Credenciales ChangeNOW de grupo guardadas cifradas.",
                metadata={
                    "provider": OWNER_PAYMENT_PROVIDER_CHANGENOW,
                    "rate_mode": payload.get("rate_mode"),
                    "manual_review_required": True,
                    "status": "active"
                }
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            ("✅ ChangeNOW guardado de forma segura\n\n" if saved else "⚠️ No pude guardar ChangeNOW\n\n")
            + (
                f"{build_changenow_safe_summary(payload)}\n\n"
                "Estado: activo para pagos cripto en revisión manual.\n"
                "El acceso NO se concede automáticamente."
                if saved
                else "Revisa la configuración y vuelve a intentarlo."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")],
                [InlineKeyboardButton("💳 Métodos del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_guardarian_save_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_guardarian_save_"
        )
        owner_user_id = get_group_owner_user_id(group_id)


        if not group_id or (not is_super_admin(user_id) and owner_user_id != user_id):

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⛔ No tienes permiso para guardar Guardarian en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        provider = context.user_data.get("owner_payment_provider")
        payload = context.user_data.get("owner_payment_payload") or {}


        if provider != OWNER_PAYMENT_PROVIDER_GUARDARIAN or context.user_data.get("owner_payment_group_id") != group_id:

            await query.message.reply_text(
                "⚠️ No hay una configuración de Guardarian lista para guardar.",
                reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
            )

            return


        required_keys = ("mode", "api_key", "payout_network", "payout_wallet")


        if any(not payload.get(key) for key in required_keys):

            await query.message.reply_text(
                "⚠️ Faltan datos para guardar Guardarian. Vuelve a iniciar la conexión.",
                reply_markup=build_owner_guardarian_cancel_keyboard(group_id)
            )

            return


        if not has_payment_encryption_key():

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⚠️ Falta PAYMENT_CONFIG_ENCRYPTION_KEY. No se guardan credenciales sin cifrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        safe_config = {
            "provider": OWNER_PAYMENT_PROVIDER_GUARDARIAN,
            "mode": payload.get("mode"),
            "api_key": payload.get("api_key"),
            "webhook_secret": payload.get("webhook_secret"),
            "base_url": payload.get("base_url"),
            "fiat_currency": "EUR",
            "payout_currency": "USDT",
            "payout_network": payload.get("payout_network"),
            "payout_wallet": payload.get("payout_wallet")
        }


        try:

            encrypted_config = encrypt_provider_config(safe_config)
            masked_summary = (
                f"mode={payload.get('mode')}; "
                "fiat=EUR; payout=USDT; "
                f"network={payload.get('payout_network')}; "
                f"wallet={mask_secret_value(payload.get('payout_wallet'))}; "
                f"webhook_secret={'configured' if payload.get('webhook_secret') else 'pending'}; "
                "auto=finished"
            )
            saved = save_group_payment_provider_encrypted_config(
                owner_user_id or user_id,
                group_id,
                OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                encrypted_config,
                masked_summary,
                public_config_json={
                    "mode": payload.get("mode"),
                    "fiat_currency": "EUR",
                    "payout_currency": "USDT",
                    "payout_network": payload.get("payout_network"),
                    "webhook_configured": bool(payload.get("webhook_secret")),
                    "checkout_enabled": True,
                    "auto_verified_status": "finished",
                    "base_url_configured": bool(payload.get("base_url"))
                },
                verified_by=user_id
            )

        except Exception:

            saved = False

        clear_owner_payment_provider_wizard(context)


        if saved:

            log_event(
                "group_payment_provider_credentials_saved",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Credenciales Guardarian de grupo guardadas cifradas.",
                metadata={
                    "provider": OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                    "mode": payload.get("mode"),
                    "webhook_configured": bool(payload.get("webhook_secret")),
                    "status": "active",
                    "auto_verified_status": "finished"
                }
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            ("✅ Guardarian guardado de forma segura\n\n" if saved else "⚠️ No pude guardar Guardarian\n\n")
            + (
                f"{build_guardarian_safe_summary(payload)}\n\n"
                "Estado: activo para checkout EUR → USDT.\n"
                "El acceso solo se concede cuando GET /v1/transaction/{id} devuelve status finished."
                if saved
                else "Revisa la configuración y vuelve a intentarlo."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")],
                [InlineKeyboardButton("💳 Métodos del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_paypal_save_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_paypal_save_"
        )
        owner_user_id = get_group_owner_user_id(group_id)


        if not group_id or (not is_super_admin(user_id) and owner_user_id != user_id):

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⛔ No tienes permiso para guardar PayPal en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        provider = context.user_data.get("owner_payment_provider")
        payload = context.user_data.get("owner_payment_payload") or {}


        if provider != OWNER_PAYMENT_PROVIDER_PAYPAL or context.user_data.get("owner_payment_group_id") != group_id:

            await query.message.reply_text(
                "⚠️ No hay una configuración de PayPal lista para guardar.",
                reply_markup=build_owner_paypal_cancel_keyboard(group_id)
            )

            return


        required_keys = ("mode", "client_id", "client_secret")


        if any(not payload.get(key) for key in required_keys):

            await query.message.reply_text(
                "⚠️ Faltan datos para guardar PayPal. Vuelve a iniciar la conexión.",
                reply_markup=build_owner_paypal_cancel_keyboard(group_id)
            )

            return


        if not has_payment_encryption_key():

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⚠️ Falta PAYMENT_CONFIG_ENCRYPTION_KEY. No se guardan credenciales sin cifrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        safe_config = {
            "provider": OWNER_PAYMENT_PROVIDER_PAYPAL,
            "mode": payload.get("mode"),
            "client_id": payload.get("client_id"),
            "client_secret": payload.get("client_secret"),
            "webhook_id": payload.get("webhook_id")
        }


        try:

            encrypted_config = encrypt_provider_config(safe_config)
            masked_config = mask_provider_config(safe_config)
            masked_summary = (
                f"mode={masked_config.get('mode')}; "
                f"client_id={mask_secret_value(masked_config.get('client_id'))}; "
                f"webhook_id={'configured' if payload.get('webhook_id') else 'pending'}"
            )
            saved = save_group_payment_provider_encrypted_config(
                owner_user_id or user_id,
                group_id,
                OWNER_PAYMENT_PROVIDER_PAYPAL,
                encrypted_config,
                masked_summary,
                public_config_json={
                    "mode": payload.get("mode"),
                    "webhook_configured": bool(payload.get("webhook_id")),
                    "checkout_enabled": False
                },
                verified_by=user_id
            )

        except Exception:

            saved = False

        clear_owner_payment_provider_wizard(context)


        if saved:

            log_event(
                "group_payment_provider_credentials_saved",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Credenciales PayPal de grupo guardadas cifradas.",
                metadata={
                    "provider": OWNER_PAYMENT_PROVIDER_PAYPAL,
                    "mode": payload.get("mode"),
                    "webhook_configured": bool(payload.get("webhook_id")),
                    "status": "pending"
                }
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            ("✅ PayPal guardado de forma segura\n\n" if saved else "⚠️ No pude guardar PayPal\n\n")
            + (
                f"{build_owner_paypal_safe_summary(payload)}\n\n"
                "Estado: pendiente de verificación.\n"
                "Los cobros PayPal reales para compradores del grupo siguen desactivados hasta una fase posterior."
                if saved
                else "Revisa la configuración y vuelve a intentarlo."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")],
                [InlineKeyboardButton("💳 Métodos del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_revolut_save_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_revolut_save_"
        )
        owner_user_id = get_group_owner_user_id(group_id)


        if not group_id or (not is_super_admin(user_id) and owner_user_id != user_id):

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⛔ No tienes permiso para guardar Revolut en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        provider = context.user_data.get("owner_payment_provider")
        payload = context.user_data.get("owner_payment_payload") or {}


        if provider != OWNER_PAYMENT_PROVIDER_REVOLUT or context.user_data.get("owner_payment_group_id") != group_id:

            await query.message.reply_text(
                "⚠️ No hay una configuración de Revolut lista para guardar.",
                reply_markup=build_owner_revolut_cancel_keyboard(group_id)
            )

            return


        required_keys = ("mode", "api_key", "webhook_secret")


        if any(not payload.get(key) for key in required_keys):

            await query.message.reply_text(
                "⚠️ Faltan datos para guardar Revolut. Vuelve a iniciar la conexión.",
                reply_markup=build_owner_revolut_cancel_keyboard(group_id)
            )

            return


        if not has_payment_encryption_key():

            clear_owner_payment_provider_wizard(context)
            await query.message.reply_text(
                "⚠️ Falta PAYMENT_CONFIG_ENCRYPTION_KEY. No se guardan credenciales sin cifrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        safe_config = {
            "provider": OWNER_PAYMENT_PROVIDER_REVOLUT,
            "mode": payload.get("mode"),
            "api_key": payload.get("api_key"),
            "webhook_secret": payload.get("webhook_secret"),
            "base_url": payload.get("base_url")
        }


        try:

            encrypted_config = encrypt_provider_config(safe_config)
            masked_config = mask_provider_config(safe_config)
            masked_summary = (
                f"mode={masked_config.get('mode')}; "
                f"api_key={masked_config.get('api_key')}; "
                f"webhook_secret=configured"
            )
            saved = save_group_payment_provider_encrypted_config(
                owner_user_id or user_id,
                group_id,
                OWNER_PAYMENT_PROVIDER_REVOLUT,
                encrypted_config,
                masked_summary,
                public_config_json={
                    "mode": payload.get("mode"),
                    "webhook_configured": True,
                    "checkout_enabled": True,
                    "base_url_configured": bool(payload.get("base_url"))
                },
                verified_by=user_id
            )

        except Exception:

            saved = False

        clear_owner_payment_provider_wizard(context)


        if saved:

            log_event(
                "group_payment_provider_credentials_saved",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Credenciales Revolut de grupo guardadas cifradas.",
                metadata={
                    "provider": OWNER_PAYMENT_PROVIDER_REVOLUT,
                    "mode": payload.get("mode"),
                    "webhook_configured": True,
                    "status": "active"
                }
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            ("✅ Revolut guardado de forma segura\n\n" if saved else "⚠️ No pude guardar Revolut\n\n")
            + (
                f"{build_owner_revolut_safe_summary(payload)}\n\n"
                "Estado: activo para checkout de grupo.\n"
                "El acceso solo se concede cuando Revolut confirme el pago por webhook verificado."
                if saved
                else "Revisa la configuración y vuelve a intentarlo."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")],
                [InlineKeyboardButton("💳 Métodos del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_guardarian_confirm_delete_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_guardarian_confirm_delete_"
        )
        owner_user_id = get_group_owner_user_id(group_id)


        if not group_id or (not is_super_admin(user_id) and owner_user_id != user_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para borrar Guardarian en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        updated = clear_group_payment_provider_config(
            group_id,
            OWNER_PAYMENT_PROVIDER_GUARDARIAN
        )


        if updated:

            log_event(
                "group_payment_provider_config_deleted",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Configuración Guardarian de grupo borrada.",
                metadata={"provider": OWNER_PAYMENT_PROVIDER_GUARDARIAN}
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración Guardarian borrada." if updated else "⚠️ No pude borrar la configuración Guardarian.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a métodos de pago", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_changenow_confirm_delete_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_changenow_confirm_delete_"
        )
        owner_user_id = get_group_owner_user_id(group_id)


        if not group_id or (not is_super_admin(user_id) and owner_user_id != user_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para borrar ChangeNOW en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        updated = clear_group_payment_provider_config(
            group_id,
            OWNER_PAYMENT_PROVIDER_CHANGENOW
        )


        if updated:

            log_event(
                "group_payment_provider_config_deleted",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Configuración ChangeNOW de grupo borrada.",
                metadata={"provider": OWNER_PAYMENT_PROVIDER_CHANGENOW}
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración ChangeNOW borrada." if updated else "⚠️ No pude borrar la configuración ChangeNOW.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a métodos de pago", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_paypal_confirm_delete_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_paypal_confirm_delete_"
        )
        owner_user_id = get_group_owner_user_id(group_id)


        if not group_id or (not is_super_admin(user_id) and owner_user_id != user_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para borrar PayPal en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        updated = clear_group_payment_provider_config(
            group_id,
            OWNER_PAYMENT_PROVIDER_PAYPAL
        )


        if updated:

            log_event(
                "group_payment_provider_config_deleted",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Configuración PayPal de grupo borrada.",
                metadata={"provider": OWNER_PAYMENT_PROVIDER_PAYPAL}
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración PayPal borrada." if updated else "⚠️ No pude borrar la configuración PayPal.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a métodos de pago", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_payment_revolut_confirm_delete_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_payment_revolut_confirm_delete_"
        )
        owner_user_id = get_group_owner_user_id(group_id)


        if not group_id or (not is_super_admin(user_id) and owner_user_id != user_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para borrar Revolut en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        updated = clear_group_payment_provider_config(
            group_id,
            OWNER_PAYMENT_PROVIDER_REVOLUT
        )


        if updated:

            log_event(
                "group_payment_provider_config_deleted",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Configuración Revolut de grupo borrada.",
                metadata={"provider": OWNER_PAYMENT_PROVIDER_REVOLUT}
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración Revolut borrada." if updated else "⚠️ No pude borrar la configuración Revolut.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a métodos de pago", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_group_payment_disable_") or data.startswith("owner_group_payment_delete_"):

        deleting = data.startswith("owner_group_payment_delete_")
        prefix = "owner_group_payment_delete_" if deleting else "owner_group_payment_disable_"
        payload = data.replace(prefix, "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        provider = parts[1]
        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para modificar este método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if deleting and provider == OWNER_PAYMENT_PROVIDER_CHANGENOW:

            await send_clean_message(
                context,
                query.message.chat_id,
                "🗑 Borrar configuración ChangeNOW\n\n"
                "Esto eliminará las credenciales cifradas guardadas para esta comunidad. "
                "No afecta a Stripe, PayPal ni Revolut.\n\n"
                "¿Confirmas el borrado?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirmar borrado", callback_data=f"owner_payment_changenow_confirm_delete_{group_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if deleting and provider == OWNER_PAYMENT_PROVIDER_PAYPAL:

            await send_clean_message(
                context,
                query.message.chat_id,
                "🗑 Borrar configuración PayPal\n\n"
                "Esto eliminará las credenciales cifradas guardadas para esta comunidad. "
                "No afecta a PayPal plataforma ni a Stripe global.\n\n"
                "¿Confirmas el borrado?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirmar borrado", callback_data=f"owner_payment_paypal_confirm_delete_{group_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if deleting and provider == OWNER_PAYMENT_PROVIDER_REVOLUT:

            await send_clean_message(
                context,
                query.message.chat_id,
                "🗑 Borrar configuración Revolut\n\n"
                "Esto eliminará las credenciales cifradas guardadas para esta comunidad. "
                "No afecta a Revolut plataforma, PayPal ni Stripe.\n\n"
                "¿Confirmas el borrado?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirmar borrado", callback_data=f"owner_payment_revolut_confirm_delete_{group_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if deleting and provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN:

            await send_clean_message(
                context,
                query.message.chat_id,
                "🗑 Borrar configuración Guardarian\n\n"
                "Esto eliminará las credenciales cifradas guardadas para esta comunidad. "
                "No afecta a Stripe, PayPal, Revolut ni ChangeNOW.\n\n"
                "¿Confirmas el borrado?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirmar borrado", callback_data=f"owner_payment_guardarian_confirm_delete_{group_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if deleting:

            updated = clear_group_payment_provider_config(group_id, provider)
            event_type = "group_payment_provider_config_deleted"
            message = "Configuración de método de pago del grupo borrada."

        else:

            updated = disable_group_payment_provider_config(group_id, provider)
            event_type = "group_payment_provider_config_disabled"
            message = "Método de pago del grupo desactivado."


        if updated:

            log_event(
                event_type,
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message=message,
                metadata={"provider": provider}
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            ("✅ " if updated else "⚠️ ") + (
                "Configuración borrada." if deleting else "Método desactivado."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a métodos de pago", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_group_payments_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_payments_"
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        owner_user_id = get_group_owner_user_id(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver pagos de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id
        _group_id, group_name, _telegram_group_id = group

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           amount,
                           currency,
                           status,
                           payment_date
                    FROM payments
                    WHERE group_id=%s
                    ORDER BY payment_date DESC
                    LIMIT 30

                """, (group_id,))

                rows = cur.fetchall()

                cur.execute("""

                    SELECT user_id,
                           plan_id,
                           amount,
                           currency,
                           status,
                           created_at,
                           provider,
                           id
                    FROM payment_transactions
                    WHERE group_id=%s
                    AND provider='changenow'
                    ORDER BY created_at DESC
                    LIMIT 20

                """, (group_id,))

                changenow_rows = cur.fetchall()

        except Exception as e:

            print("Error cargando pagos de grupo:", e)

            await query.message.reply_text(
                "❌ No he podido cargar los pagos de esta comunidad ahora mismo.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])


        if not rows and not changenow_rows:

            await send_clean_message(
                context,
                query.message.chat_id,
                f"💳 Pagos recibidos\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\nTodavía no hay pagos recibidos para esta comunidad.",
                reply_markup=keyboard
            )

            return


        text = f"💳 Pagos recibidos\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\n"


        for payment_user_id, plan_name, amount, currency, status, payment_date in rows:

            text += (
                f"Usuario: {payment_user_id}\n"
                f"Plan: {plan_name or '-'}\n"
                f"Importe: {amount or '-'} {currency or ''}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {payment_date or '-'}\n\n"
            )


        if changenow_rows:

            text += "💱 ChangeNOW en revisión/manual\n\n"


        for payment_user_id, plan_id, amount, currency, status, payment_date, provider, transaction_id in changenow_rows:

            text += (
                f"Referencia: #{transaction_id}\n"
                f"Usuario: {payment_user_id}\n"
                f"Plan ID: {plan_id or '-'}\n"
                f"Importe plan: {amount or '-'} {currency or ''}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {payment_date or '-'}\n"
                "Acceso: pendiente de revisión manual\n\n"
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            text[:3900],
            reply_markup=keyboard
        )

        return


    if data.startswith("owner_group_subscriptions_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_subscriptions_"
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        owner_user_id = get_group_owner_user_id(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver suscripciones de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id
        _group_id, group_name, _telegram_group_id = group

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id,
                           username,
                           first_name,
                           expiration,
                           subscription_active,
                           created_at
                    FROM users
                    WHERE group_id=%s
                    AND COALESCE(subscription_active, FALSE)=TRUE
                    AND (
                        expiration IS NULL
                        OR expiration > NOW()
                    )
                    ORDER BY expiration ASC NULLS LAST,
                             created_at DESC
                    LIMIT 30

                """, (group_id,))

                rows = cur.fetchall()

        except Exception as e:

            print("Error cargando suscripciones de grupo:", e)

            await query.message.reply_text(
                "❌ No he podido cargar las suscripciones de esta comunidad ahora mismo.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])


        if not rows:

            await send_clean_message(
                context,
                query.message.chat_id,
                f"📌 Suscripciones activas\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\nTodavía no hay suscripciones activas para esta comunidad.",
                reply_markup=keyboard
            )

            return


        text = f"📌 Suscripciones activas\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\n"


        for subscriber_user_id, username, first_name, expiration, _subscription_active, created_at in rows:

            name = first_name or "Sin nombre"

            if username:

                name += f" (@{username})"


            expiration_text = "permanente" if expiration is None else str(expiration)

            text += (
                f"Usuario: {subscriber_user_id}\n"
                f"Nombre: {name}\n"
                f"Acceso: {expiration_text}\n"
                f"Alta: {created_at or '-'}\n\n"
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            text[:3900],
            reply_markup=keyboard
        )

        return


    if data == "owner_support_tickets":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_respond_group_support"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver soporte de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id
        tickets = fetch_recent_support_tickets(group_id=group_id)
        keyboard = []


        for ticket in tickets:

            username = format_support_username(ticket)
            label_name = username if username != "-" else ticket.get("first_name") or ticket.get("user_id")

            keyboard.append([
                InlineKeyboardButton(
                    f"📨 Ticket #{ticket.get('id')} - {label_name}",
                    callback_data=f"owner_support_ticket_{ticket.get('id')}"
                )
            ])


        if is_super_admin(user_id):

            keyboard.append([InlineKeyboardButton("🛟 Abrir bandeja global", callback_data="admin_support_tickets")])


        keyboard.extend([
            [InlineKeyboardButton("⬅️ Volver al apartado soporte", callback_data="owner_panel_support")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            build_support_tickets_text(tickets).replace("🛟 Tickets de soporte", "🛟 Tickets de soporte de esta comunidad"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data.startswith("owner_support_ai_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_ai_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket or not ticket.get("group_id"):

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_has_group_permission_any(user_id, ticket.get("group_id"), ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para usar IA en este ticket.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        result = build_support_reply_suggestion(
            user_id,
            AI_ROLE_OWNER,
            ticket_id,
            group_id=ticket.get("group_id")
        )
        keyboard = [
            [InlineKeyboardButton("✍️ Usar como base", callback_data=f"owner_support_use_ai_{ticket_id}")],
            [InlineKeyboardButton("⬅️ Volver al ticket", callback_data=f"owner_support_ticket_{ticket_id}")]
        ]


        if result.get("interaction_id"):

            for label, callback_data in build_ai_feedback_keyboard_rows(result.get("interaction_id")):

                keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])


        await query.message.reply_text(
            "🤖 Borrador sugerido para soporte\n\n"
            f"{result.get('answer') or 'No tengo suficiente información para preparar un borrador.'}\n\n"
            "No se enviará automáticamente. Puedes usarlo como base y editarlo antes de responder.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data.startswith("owner_support_use_ai_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_use_ai_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket or not ticket.get("group_id"):

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_has_group_permission_any(user_id, ticket.get("group_id"), ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para responder este ticket.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = ticket.get("group_id")
        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Usa el borrador anterior como base, edítalo si hace falta y escribe ahora la respuesta final para el usuario.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Cancelar", callback_data=f"owner_support_ticket_{ticket_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_support_ticket_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_ticket_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        ticket_group_id = ticket.get("group_id")


        if not ticket_group_id or not user_has_group_permission_any(user_id, ticket_group_id, ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver este ticket de soporte.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = ticket_group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            build_support_ticket_detail_text(ticket),
            reply_markup=InlineKeyboardMarkup(build_owner_support_ticket_keyboard(ticket))
        )

        return


    if data.startswith("owner_support_reply_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_reply_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket or not ticket.get("group_id"):

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_has_group_permission_any(user_id, ticket.get("group_id"), ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para responder este ticket.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if ticket.get("status") == "closed":

            await query.message.reply_text(
                "📁 Este ticket está cerrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver a soporte de comunidad", callback_data="owner_support_tickets")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        context.user_data["selected_owner_group"] = ticket.get("group_id")
        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Escribe ahora la respuesta para el usuario.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Cancelar", callback_data=f"owner_support_ticket_{ticket_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("owner_support_close_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_close_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket or not ticket.get("group_id"):

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_has_group_permission_any(user_id, ticket.get("group_id"), ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cerrar este ticket.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        update_support_ticket_status(ticket_id, "closed")
        context.user_data["selected_owner_group"] = ticket.get("group_id")

        log_event(
            "owner_support_ticket_closed",
            category="support",
            severity="info",
            scope="group",
            group_id=ticket.get("group_id"),
            actor_user_id=user_id,
            target_user_id=ticket.get("user_id"),
            message="Owner cerró un ticket de soporte de comunidad.",
            metadata={"ticket_id": ticket_id}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Ticket cerrado.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a soporte de comunidad", callback_data="owner_support_tickets")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data == "owner_panel_location_info":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_location_management_text(group_id),
            reply_markup=build_owner_location_management_keyboard(group_id)
        )

        return


    if data == "owner_panel_security_info":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para revisar seguridad en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_security_text(group_id),
            reply_markup=build_owner_security_keyboard(group_id)
        )

        return


    if data.startswith("owner_location_regions_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_location_regions_"
        )


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            "📂 Elegir comunidad autónoma\n\nSelecciona la región permitida para esta comunidad.",
            reply_markup=build_owner_location_regions_keyboard(group_id)
        )

        return


    if data.startswith("owner_location_enable_") or data.startswith("owner_location_disable_"):

        enabled = data.startswith("owner_location_enable_")
        prefix = "owner_location_enable_" if enabled else "owner_location_disable_"
        group_id = extract_commercial_request_id(data, prefix)


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        set_group_location_rule(group_id, enabled=enabled)
        context.user_data["selected_owner_group"] = group_id

        log_event(
            "owner_location_gate_updated",
            category="security",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Owner actualizó el estado de restricción por ubicación.",
            metadata={"enabled": enabled}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Restricción por ubicación actualizada.\n\n" + build_owner_location_management_text(group_id),
            reply_markup=build_owner_location_management_keyboard(group_id)
        )

        return


    if data.startswith("owner_location_country_set_"):

        payload = data.replace("owner_location_country_set_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        country_code = parts[1]


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        set_group_location_rule(
            group_id,
            enabled=True,
            region_type=LOCATION_REGION_TYPE_COUNTRY,
            allowed_region=country_code
        )
        context.user_data["selected_owner_group"] = group_id

        log_event(
            "owner_location_gate_updated",
            category="security",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Owner actualizó país permitido por ubicación.",
            metadata={"allowed_region": country_code, "region_type": LOCATION_REGION_TYPE_COUNTRY}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n" + build_owner_location_management_text(group_id),
            reply_markup=build_owner_location_management_keyboard(group_id)
        )

        return


    if data.startswith("owner_location_region_set_"):

        payload = data.replace("owner_location_region_set_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        region_slug = parts[1]


        if region_slug not in SPANISH_AUTONOMOUS_COMMUNITY_LABELS:

            await query.message.reply_text(
                "⚠️ Región no válida.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        set_group_location_rule(
            group_id,
            enabled=True,
            region_type=LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
            allowed_region=region_slug
        )
        context.user_data["selected_owner_group"] = group_id

        log_event(
            "owner_location_gate_updated",
            category="security",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Owner actualizó comunidad autónoma permitida por ubicación.",
            metadata={"allowed_region": region_slug, "region_type": LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n" + build_owner_location_management_text(group_id),
            reply_markup=build_owner_location_management_keyboard(group_id)
        )

        return


    if data in (
        "owner_panel_access_type_info",
        "owner_panel_general_info"
    ):

        info_texts = {
            "owner_panel_access_type_info": (
                "🔓 Tipo gratis/pago\n\n"
                "El tipo de acceso se revisa desde Configuración de pagos del grupo. "
                "De pago no significa solo Stripe: puedes activar Stripe, PayPal, Revolut, ChangeNOW, Guardarian o códigos."
            ),
            "owner_panel_general_info": (
                "⚙️ Configuración general\n\n"
                "Estos ajustes se gestionan con flujos seguros existentes. "
                "No se reinicia ni borra configuración sin confirmación específica."
            )
        }

        await query.message.reply_text(
            info_texts.get(data, "Información no disponible."),
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    # =========================
    # MENÚ INTERNO DEL GRUPO
    # =========================

    edit_group_parts = data.split("_")


    if (
        data.startswith("edit_group_")
        and len(edit_group_parts) >= 3
        and edit_group_parts[2].isdigit()
    ):

        try:
            await query.message.delete()
        except:
            pass


        group_id = int(edit_group_parts[2])


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_manage_groups", "can_manage_plans"]
            + ["can_manage_codes", "can_manage_admins"]
            + ["can_edit_group_texts", "can_edit_marketplace_preview"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        # Guardar grupo seleccionado

        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            build_owner_quick_status_text(user_id, group_id)
            + "\nSolo verás secciones compatibles con tus permisos en esta comunidad.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if data == "edit_group_back":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_manage_plans"]
            + ["can_manage_codes", "can_manage_admins"]
            + ["can_edit_group_texts", "can_edit_marketplace_preview"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        await query.message.reply_text(
            build_owner_quick_status_text(user_id, group_id),
            reply_markup=InlineKeyboardMarkup(
                build_group_settings_keyboard(user_id, group_id)
            )
        )

        return


    if data in (
        "edit_group_name",
        "edit_group_stripe",
        "edit_group_admins",
        "edit_group_user_codes"
    ):

        required_permissions = ["can_manage_groups"]


        if data == "edit_group_name":

            required_permissions = ["can_edit_group_texts", "can_manage_groups"]


        if data == "edit_group_admins":

            required_permissions = ["can_manage_admins"]

        if data == "edit_group_user_codes":

            required_permissions = ["can_manage_codes"]

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            required_permissions
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if data == "edit_group_admins":

            context.user_data["selected_owner_group"] = group_id

            await send_clean_message(
                context,
                query.message.chat_id,
                "👥 Admins de mi grupo\n\nGestiona admins y permisos por comunidad.",
                reply_markup=build_group_admin_panel_keyboard()
            )

            return


        if data == "edit_group_user_codes":

            set_group_user_promo_context(
                context,
                group_id,
                step="panel"
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                "🎟 Códigos de mi grupo\n\n"
                "Crea códigos para usuarios finales de esta comunidad. "
                "Estos códigos solo funcionan en este grupo y no se mezclan con los códigos promocionales comerciales.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        if data == "edit_group_stripe":

            group = fetch_group_basic_info(group_id)
            group_name = group[1] if group else f"Grupo {group_id}"

            await send_clean_message(
                context,
                query.message.chat_id,
                "🔗 Stripe/configuración pagos\n\n"
                f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
                "Stripe global sigue funcionando para los pagos actuales del bot.\n\n"
                "La configuración de Stripe propio por grupo todavía no está disponible. "
                "Se activará en una fase posterior, con almacenamiento seguro y validación de webhooks por comunidad.\n\n"
                "Por seguridad, todavía no se piden ni se guardan credenciales Stripe del owner desde este panel.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Ver métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
                    [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        await query.message.reply_text(
            "⚠️ Esta acción todavía no tiene un flujo seguro disponible.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    if data == "group_user_codes_panel" or data.startswith("group_user_codes_panel_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_codes_panel"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="panel"
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos de mi grupo\n\n"
            "Estos códigos dan acceso a usuarios finales solo para esta comunidad.",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if data == "group_user_code_create" or data.startswith("group_user_code_create_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_create"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="duration"
        )
        clear_group_user_promo_wizard(context, keep_group=True)
        context.user_data["group_user_promo_step"] = "duration"

        await send_clean_message(
            context,
            query.message.chat_id,
            "➕ Crear código\n\nElige la duración del acceso para el usuario final.",
            reply_markup=build_group_user_code_duration_keyboard(group_id)
        )

        return


    if data.startswith("group_user_code_duration_"):

        callback_group_id, slug = parse_group_user_code_step_callback(
            data,
            "group_user_code_duration"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="uses"
        )


        if slug == "custom":

            context.user_data["group_user_promo_waiting"] = "custom_duration"

            await query.message.reply_text(
                "Envía la duración en días, entre 1 y 3650.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        if slug == "permanent":

            context.user_data["group_user_promo_duration_days"] = None
            context.user_data["group_user_promo_is_permanent"] = True

        else:

            try:

                duration_days = int(slug)

            except Exception:

                await query.message.reply_text(
                    "❌ Duración no válida.",
                    reply_markup=build_group_user_codes_error_keyboard()
                )

                return


            if not 1 <= duration_days <= 3650:

                await query.message.reply_text(
                    "❌ Duración no válida.",
                    reply_markup=build_group_user_codes_error_keyboard()
                )

                return


            context.user_data["group_user_promo_duration_days"] = duration_days
            context.user_data["group_user_promo_is_permanent"] = False


        await send_clean_message(
            context,
            query.message.chat_id,
            "Elige cuántos usos tendrá el código.",
            reply_markup=build_group_user_code_uses_keyboard(group_id)
        )

        return


    if data.startswith("group_user_code_uses_"):

        callback_group_id, uses_text = parse_group_user_code_step_callback(
            data,
            "group_user_code_uses"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            max_uses = int(uses_text)

        except Exception:

            await query.message.reply_text(
                "❌ Número de usos no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        if max_uses not in (0, 1, 5, 10):

            await query.message.reply_text(
                "❌ Número de usos no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="code_kind"
        )
        context.user_data["group_user_promo_max_uses"] = max_uses

        await send_clean_message(
            context,
            query.message.chat_id,
            "Elige cómo quieres generar el código.",
            reply_markup=build_group_user_code_kind_keyboard(group_id)
        )

        return


    if data == "group_user_code_manual" or data.startswith("group_user_code_manual_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_manual"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="manual_code"
        )
        context.user_data["group_user_promo_waiting"] = "manual_code"

        await query.message.reply_text(
            "Envía el código manual.\n\n"
            "Usa entre 4 y 32 caracteres: letras, números, guion o guion bajo.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))]
            ])
        )

        return


    if data == "group_user_code_auto" or data.startswith("group_user_code_auto_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_auto"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        duration_days = context.user_data.get("group_user_promo_duration_days")
        is_permanent = context.user_data.get("group_user_promo_is_permanent") is True
        max_uses = context.user_data.get("group_user_promo_max_uses")


        if max_uses is None:

            await query.message.reply_text(
                "❌ Falta completar la configuración del código.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            row = create_group_user_promo_code(
                group_id,
                user_id,
                duration_days,
                is_permanent,
                max_uses
            )

        except Exception as e:

            print("Error creando código de grupo:", e)

            await query.message.reply_text(
                "❌ Error creando el código.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        if not row:

            await query.message.reply_text(
                "❌ Error creando el código.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        clear_group_user_promo_wizard(context, keep_group=True)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Código creado\n\n"
            f"Código: {row[1]}\n"
            f"Duración: {format_group_user_promo_duration(row[2], row[3])}\n"
            f"Usos máximos: {'ilimitado' if row[4] == 0 else row[4]}",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if data == "group_user_codes_active" or data.startswith("group_user_codes_active_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_codes_active"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_codes(group_id, active_only=True)


        if not rows:

            await query.message.reply_text(
                "📋 No hay códigos activos para este grupo.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        text = "📋 Códigos activos de mi grupo\n\n"


        for _code_id, code, duration_days, is_permanent, max_uses, used_count, _is_active, expires_at, _created_at in rows:

            text += (
                f"Código: {code}\n"
                f"Duración: {format_group_user_promo_duration(duration_days, is_permanent)}\n"
                f"Usos: {format_group_user_promo_uses(max_uses, used_count)}\n"
                f"Caduca: {expires_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if data == "group_user_code_deactivate_menu" or data.startswith("group_user_code_deactivate_menu_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_deactivate_menu"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para desactivar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_codes(group_id, active_only=True)


        await query.message.reply_text(
            "🚫 Desactivar código\n\nElige el código que quieres desactivar.",
            reply_markup=build_group_user_code_deactivate_keyboard(rows, group_id)
        )

        return


    if data.startswith("group_user_code_deactivate_"):

        payload = data.replace("group_user_code_deactivate_", "", 1)
        callback_group_id = None
        code_id_text = payload


        if "_" in payload:

            maybe_group_id, maybe_code_id = payload.split("_", 1)


            if maybe_group_id.isdigit() and maybe_code_id.isdigit():

                callback_group_id = int(maybe_group_id)
                code_id_text = maybe_code_id


        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para desactivar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            code_id = int(code_id_text)

        except Exception:

            await query.message.reply_text(
                "❌ Código no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_user_promo_codes
                SET is_active=FALSE
                WHERE id=%s
                AND group_id=%s
                RETURNING code

            """, (
                code_id,
                group_id
            ))

            row = cur.fetchone()
            conn.commit()


        if not row:

            await query.message.reply_text(
                "❌ Código no encontrado.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        await query.message.reply_text(
            f"🚫 Código desactivado:\n{row[0]}",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    if data == "group_user_code_usage" or data.startswith("group_user_code_usage_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_usage"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver usos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_usage(group_id)


        if not rows:

            await query.message.reply_text(
                "📊 Todavía no hay usos de códigos en este grupo.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        text = "📊 Usos de códigos\n\n"


        for redeemed_at, redeemed_user_id, code, expiration in rows:

            text += (
                f"Código: {code}\n"
                f"Usuario: {redeemed_user_id}\n"
                f"Canjeado: {redeemed_at}\n"
                f"Expira: {expiration or 'permanente'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return


    # =========================
    # EDITAR PREVIEW
    # =========================

    if data == "edit_group_preview":

        try:
            await query.message.delete()
        except:
            pass


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return


        await query.message.reply_text(
            preview_mode_selection_text(),
            reply_markup=build_group_preview_mode_keyboard()

        )

        return


    if data.startswith("edit_group_preview_mode_"):

        preview_mode = data.replace("edit_group_preview_mode_", "", 1)

        if preview_mode not in PREVIEW_MODE_LABELS:

            await query.message.reply_text("❌ Nivel de preview no válido.")

            return


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET preview_mode=%s
                WHERE id=%s

            """, (
                preview_mode,
                group_id
            ))

            conn.commit()


        if preview_mode in ("manual", "hybrid"):

            context.user_data["editing_preview"] = True
            context.user_data["editing_preview_mode"] = preview_mode

            await query.message.reply_text(
                "✅ Tipo de preview actualizado.\n\n"
                "Envía ahora una imagen o vídeo para guardarlo como preview manual.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data="edit_group_back"
                    )]
                ])
            )

            return


        message = "✅ Preview dinámico activado."

        if preview_mode == "dynamic":

            message = (
                "✅ Preview dinámico activado.\n\n"
                "Solo capturará vídeos nuevos publicados en el grupo después de activar este modo."
            )

        elif preview_mode == "private":

            message = "✅ Sin preview público activado."


        await query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(
                build_group_settings_keyboard(user_id, group_id)
            )
        )

        return

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
                "⛔ No tienes permiso para realizar esta acción en esta comunidad."
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

    if data == "edit_group_plans":

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


        keyboard = [

            [InlineKeyboardButton(
                "📋 Ver planes",
                callback_data="view_group_plans"
            )],

            [InlineKeyboardButton(
                "➕ Añadir plan",
                callback_data="add_group_plan"
            )],

            [InlineKeyboardButton(
                "✏️ Editar plan",
                callback_data="edit_group_plan_select"
            )],

            [InlineKeyboardButton(
                "🗑 Eliminar plan",
                callback_data="delete_group_plan_select"
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=f"edit_group_{group_id}"
            )]

        ]


        await query.message.reply_text(

            "💳 GESTIÓN DE PLANES\n\n"
            "Selecciona una opción:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # AÑADIR PLAN — INICIO
    # =========================

    if data == "add_group_plan":

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


        context.user_data["adding_plan"] = True
        context.user_data["add_plan_step"] = 1
        context.user_data["new_plan"] = {}


        await query.message.reply_text(

            "➕ CREAR NUEVO PLAN\n\n"

            "Paso 1️⃣\n"
            "Introduce el nombre del plan.\n\n"

            "Ejemplo:\n"
            "VIP Mensual"

        )

        return


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
                           duration_days

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


        for plan_id, name, amount, currency, duration in plans:

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

    if data == "edit_group_plan_select":

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

                SELECT id, name
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE
                ORDER BY id ASC

            """, (group_id,))

            plans = cur.fetchall()


        if not plans:

            await query.message.reply_text(
                "⚠️ No hay planes disponibles."
            )

            return


        keyboard = []


        for plan_id, name in plans:

            keyboard.append([

                InlineKeyboardButton(
                    name,
                    callback_data=f"edit_plan_{plan_id}"
                )

            ])


        keyboard.append([

            InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )

        ])


        await query.message.reply_text(

            "✏️ Selecciona el plan a editar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ELIMINAR GRUPO — CONFIRMAR
    # =========================

    if data == "delete_group_confirm":

        group_id = context.user_data.get("selected_group_admin")

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return

        if not group_id:

            await query.message.reply_text(
                "❌ No se encontró el grupo."
            )

            return

        try:

            with conn.cursor() as cur:

                # =========================
                # BORRAR PLANES
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM plans
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando plans:", e)


                # =========================
                # BORRAR USUARIOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM users
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando users:", e)


                # =========================
                # BORRAR LINKS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM invite_links
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando invite_links:", e)


                # =========================
                # BORRAR WARNINGS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM link_warnings
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando link_warnings:", e)


                # =========================
                # BORRAR PAGOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM payments
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando payments:", e)


                # =========================
                # BORRAR SUBSCRIPTIONS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM subscriptions
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando subscriptions:", e)


                # =========================
                # BORRAR BANEADOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM banned_users
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando banned_users:", e)


                # =========================
                # BORRAR ADMINS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM admins
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando admins:", e)


                # =========================
                # BORRAR GRUPO
                # =========================

                cur.execute("""

                    DELETE FROM groups
                    WHERE id=%s

                """, (group_id,))


                conn.commit()


            await query.message.reply_text(
                "🗑 Grupo eliminado correctamente."
            )

        except Exception as e:

            print("Error eliminando grupo:", e)

            await query.message.reply_text(
                "❌ Error eliminando grupo."
            )

        return


    # =========================
    # ELIMINAR PLAN — SELECCIÓN
    # =========================

    if data == "delete_group_plan_select":

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

                SELECT id, name
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE
                ORDER BY id ASC

            """, (group_id,))

            plans = cur.fetchall()


        if not plans:

            await query.message.reply_text(
                "⚠️ No hay planes disponibles."
            )

            return


        keyboard = []


        for plan_id, name in plans:

            keyboard.append([

                InlineKeyboardButton(
                    name,
                    callback_data=f"delete_plan_{plan_id}"
                )

            ])


        keyboard.append([

            InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )

        ])


        await query.message.reply_text(

            "🗑 Selecciona el plan a eliminar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

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

                if remaining_plans == 0:

                    print(
                        "Grupo sin planes restantes:",
                        group_id
                    )


                conn.commit()

        except Exception as e:

            print("Error eliminando plan:", e)

            await query.message.reply_text(
                "❌ Error eliminando plan."
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


    if data in (
        "admin_reset_warnings",
        "admin_resend_access",
        "admin_cancel_subscription",
        "admin_move_user"
    ):

        await query.message.reply_text(
            "⚠️ Esta acción todavía no tiene un flujo seguro disponible."
        )

        return


    if data == "admin_view_payments":

        group_ids = get_admin_group_ids(
            user_id,
            ["can_view_payments", "can_manage_payments"]
        )


        try:

            with conn.cursor() as cur:

                if group_ids is None:

                    cur.execute("""

                        SELECT p.user_id,
                               g.name,
                               p.amount,
                               p.currency,
                               p.status,
                               p.payment_date
                        FROM payments p
                        LEFT JOIN groups g
                        ON p.group_id = g.id
                        ORDER BY p.payment_date DESC
                        LIMIT 20

                    """)

                elif not group_ids:

                    payments = []

                else:

                    cur.execute("""

                        SELECT p.user_id,
                               g.name,
                               p.amount,
                               p.currency,
                               p.status,
                               p.payment_date
                        FROM payments p
                        LEFT JOIN groups g
                        ON p.group_id = g.id
                        WHERE p.group_id = ANY(%s)
                        ORDER BY p.payment_date DESC
                        LIMIT 20

                    """, (group_ids,))


                if group_ids is None or group_ids:

                    payments = cur.fetchall()

        except Exception as e:

            print("Error cargando pagos admin:", e)

            await query.message.reply_text(
                "❌ Error cargando pagos."
            )

            return


        if not payments:

            await query.message.reply_text(
                "⚠️ No hay pagos registrados."
            )

            return


        text = "💳 Últimos pagos\n\n"


        for payment_user_id, group_name, amount, currency, status, payment_date in payments:

            text += (
                f"Usuario: {payment_user_id}\n"
                f"Grupo: {group_name or '-'}\n"
                f"Importe: {amount or '-'} {currency or ''}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {payment_date or '-'}\n\n"
            )


        await query.message.reply_text(text)

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


    if data == "admin_income":

        group_ids = get_admin_group_ids(
            user_id,
            ["can_view_payments", "can_view_stats"]
        )


        with conn.cursor() as cur:

            if group_ids is None:

                cur.execute("""

                    SELECT g.name,
                           COALESCE(SUM(p.amount), 0),
                           MAX(p.currency)
                    FROM payments p
                    LEFT JOIN groups g
                    ON p.group_id = g.id
                    GROUP BY g.name
                    ORDER BY g.name ASC

                """)

            elif not group_ids:

                rows = []

            else:

                cur.execute("""

                    SELECT g.name,
                           COALESCE(SUM(p.amount), 0),
                           MAX(p.currency)
                    FROM payments p
                    LEFT JOIN groups g
                    ON p.group_id = g.id
                    WHERE p.group_id = ANY(%s)
                    GROUP BY g.name
                    ORDER BY g.name ASC

                """, (group_ids,))


            if group_ids is None or group_ids:

                rows = cur.fetchall()


        if not rows:

            await query.message.reply_text(
                "💰 No hay ingresos registrados."
            )

            return


        text = "💰 Ingresos por grupo\n\n"


        for group_name, amount, currency in rows:

            text += f"{group_name or '-'}: {amount or 0} {currency or ''}\n"


        await query.message.reply_text(text)

        return


    if data.startswith("admin_beta_cycle"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        if data in (
            "admin_beta_cycle",
            "admin_beta_cycle_status"
        ):

            await query.message.reply_text(
                format_beta_cycle_status_text(),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data in (
            "admin_beta_cycle_start_beta_1",
            "admin_beta_cycle_start_beta_2"
        ):

            complete_expired_beta_cycles()

            phase = (
                "beta_2"
                if data == "admin_beta_cycle_start_beta_2"
                else "beta_1"
            )

            cycle, active_cycle = create_beta_cycle(
                created_by=user_id,
                phase=phase,
                duration_days=7
            )

            if active_cycle:

                await query.message.reply_text(
                    (
                        "⚠️ Ya hay un ciclo beta activo.\n\n"
                        f"{format_beta_cycle_row(active_cycle)}"
                    ),
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            if not cycle:

                await query.message.reply_text(
                    "⚠️ No se pudo iniciar el ciclo beta.",
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            phase_label = "Beta 2.0" if phase == "beta_2" else "Beta cerrada"

            log_event(
                "beta_cycle_started",
                category="beta",
                severity="info",
                message=f"{phase_label} iniciada",
                actor_user_id=user_id,
                metadata={
                    "cycle_id": cycle[0],
                    "phase": phase,
                    "ends_at": str(cycle[5])
                }
            )

            await query.message.reply_text(
                (
                    f"✅ {phase_label} iniciada hasta {cycle[5]}.\n\n"
                    f"{format_beta_cycle_row(cycle)}"
                ),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data == "admin_beta_cycle_finish":

            cycle = complete_active_beta_cycle(
                notes="Finalizada manualmente desde el panel beta."
            )

            if not cycle:

                await query.message.reply_text(
                    "⚠️ No hay una beta activa para finalizar.",
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            log_event(
                "beta_cycle_completed",
                category="beta",
                severity="info",
                message="Ciclo beta finalizado manualmente",
                actor_user_id=user_id,
                metadata={
                    "cycle_id": cycle[0],
                    "phase": cycle[3]
                }
            )

            await query.message.reply_text(
                (
                    "✅ Beta finalizada.\n\n"
                    f"{format_beta_cycle_row(cycle)}"
                ),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data == "admin_beta_cycle_final_review":

            await query.message.reply_text(
                format_final_launch_checklist(),
                reply_markup=build_beta_monitor_keyboard()
            )

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


    if data.startswith("admin_beta_monitor"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        if data == "admin_beta_monitor_resolve_all":

            affected = mark_beta_monitor_events_resolved(hours=24)

            await query.message.reply_text(
                f"✅ Eventos marcados como resueltos: {affected}",
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        title = "📊 Monitor beta"
        severity = None
        event_types = None


        if data == "admin_beta_monitor_critical":

            title = "🚨 Monitor beta · Críticos"
            severity = "critical"

        elif data == "admin_beta_monitor_warning":

            title = "⚠️ Monitor beta · Warnings"
            severity = "warning"

        elif data == "admin_beta_monitor_payments":

            title = "💳 Monitor beta · Pagos/accesos"
            event_types = [
                "payment_confirmed",
                "payment_failed",
                "invite_link_created",
                "invite_link_failed",
                "access_allowed",
                "unauthorized_access"
            ]

        elif data == "admin_beta_monitor_codes":

            title = "🎟 Monitor beta · Códigos"
            event_types = [
                "group_code_redeemed",
                "group_code_failed"
            ]

        elif data == "admin_beta_monitor_backups":

            title = "🛡 Monitor beta · Backups"
            event_types = [
                "backup_message_failed",
                "backup_permission_error"
            ]


        if data == "admin_beta_monitor":

            text = summarize_beta_monitor_events(hours=6)

        else:

            rows = list_beta_monitor_events(
                hours=24,
                severity=severity,
                event_types=event_types,
                limit=50
            )
            text = format_beta_monitor_events_text(
                title,
                rows
            )


        await query.message.reply_text(
            text,
            reply_markup=build_beta_monitor_keyboard()
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

    if data == "admin_resend_links":

        if not is_super_admin(query.from_user.id):
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id
                    FROM users

                    WHERE
                    (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    AND user_id NOT IN (

                        SELECT user_id
                        FROM banned_users

                    )

                """)

                users = cur.fetchall()


            enviados = 0

            for (user_id,) in users:

                try:

                    # =========================
                    # OBTENER TELEGRAM_GROUP_ID REAL
                    # =========================

                    with conn.cursor() as cur2:

                        cur2.execute("""

                            SELECT telegram_group_id

                            FROM groups

                            WHERE id=(

                                SELECT group_id
                                FROM users
                                WHERE user_id=%s
                                LIMIT 1

                            )

                        """, (user_id,))

                        group_row = cur2.fetchone()


                    if not group_row:
                        continue


                    telegram_group_id = group_row[0]


                    link = create_telegram_invite_link(
                        TOKEN,
                        telegram_group_id,
                        expire_seconds=60,
                        member_limit=1
                    )


                    if not link:

                        print(
                            "Error creando link para usuario:",
                            user_id
                        )

                        continue


                    with conn.cursor() as cur:

                        cur.execute("""

                            DELETE FROM invite_links
                            WHERE user_id=%s

                        """, (user_id,))


                        cur.execute("""

                            INSERT INTO invite_links
                            (user_id, group_id, telegram_group_id, invite_link)

                            VALUES (%s, %s, %s, %s)

                        """, (

                            user_id,
                            get_group_id(),
                            telegram_group_id,
                            link

                        ))

                        conn.commit()


                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                        json={
                            "chat_id": user_id,
                            "text": f"🔗 Nuevo acceso VIP:\n{link}"
                        }

                    )

                    enviados += 1

                except Exception as e:

                    print("Error enviando link:", e)


            await query.message.reply_text(

                f"📩 {enviados} nuevos links enviados."

            )

        except Exception as e:

            print("Error reenviando:", e)

            await query.message.reply_text(
                "❌ Error reenviando links"
            )

        return





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

                SELECT 1
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

        context.user_data["editing_plan"] = True
        context.user_data["editing_plan_id"] = plan_id
        context.user_data["edit_plan_step"] = 1

        await query.message.reply_text(

            "✏️ EDITAR PLAN\n\n"

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


    if data == "group_user_promo_redeem_start":

        await query.message.reply_text(
            "🎟 Código de comunidad\n\n"
            "El canje de códigos se hace desde la ficha de una comunidad concreta.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("group_user_promo_redeem_start_"):

        try:

            redeem_group_id = int(data.replace("group_user_promo_redeem_start_", "", 1))

        except Exception:

            await query.message.reply_text(
                "❌ Comunidad no válida.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return

        context.user_data["group_user_promo_waiting"] = "redeem_code"
        context.user_data["group_user_promo_redeem_group_id"] = redeem_group_id

        await query.message.reply_text(
            "🎟 Canjear código de esta comunidad\n\n"
            "Envía ahora el código de acceso. Solo será válido si pertenece a esta comunidad.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a comunidad", callback_data=f"marketplace_group_{redeem_group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if data.startswith("group_user_promo_confirm_"):

        try:

            code_id = int(data.replace("group_user_promo_confirm_", "", 1))

        except Exception:

            await query.message.reply_text(
                "❌ Código no válido.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        pending_code_id = context.user_data.get("group_user_promo_pending_code_id")


        if int(pending_code_id or 0) != code_id:

            await query.message.reply_text(
                "❌ No hay un código pendiente para confirmar.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


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
                       COALESCE(g.is_active, TRUE)
                FROM group_user_promo_codes c
                JOIN groups g
                ON g.id = c.group_id
                WHERE c.id=%s
                LIMIT 1

            """, (code_id,))

            promo_row = cur.fetchone()


        valid, error_message = validate_group_user_promo_row(promo_row)
        selected_group_id = context.user_data.get("group_user_promo_redeem_group_id")


        if valid and selected_group_id and int(promo_row[1]) != int(selected_group_id):

            valid = False
            error_message = "❌ Este código no pertenece a esta comunidad."


        if not valid:

            await query.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver a comunidad",
                        callback_data=f"marketplace_group_{selected_group_id}"
                        if selected_group_id
                        else "start_explore_groups"
                    )],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        try:

            await grant_group_user_promo_access(
                context,
                query.message.chat_id,
                query.from_user,
                promo_row
            )

            context.user_data.pop("group_user_promo_pending_code_id", None)
            context.user_data.pop("group_user_promo_waiting", None)
            context.user_data.pop("group_user_promo_redeem_group_id", None)

        except Exception as e:

            print("Error canjeando código de grupo:", e)

            await query.message.reply_text(
                "❌ Error canjeando el código.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
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


    if data.startswith("creator_setup_reset_confirm_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_reset_confirm_"
        )
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        clear_creator_onboarding_context(context)

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE commercial_requests
                SET updated_at=NOW()
                WHERE id=%s

            """, (request_id,))


        await send_clean_message(
            context,
            query.message.chat_id,
            "🧹 Configuración reiniciada.\n\n"
            "La prueba y el cupo asignado se mantienen. Puedes continuar desde el panel.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔄 Recuperar configuración",
                    callback_data=f"configure_community_{request_id}"
                )],
                [InlineKeyboardButton(
                    "📡 Añadir grupo/canal",
                    callback_data=f"creator_setup_group_{request_id}"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_reset_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_reset_"
        )
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
            "🧹 Reiniciar configuración\n\n"
            "Esto limpiará los pasos temporales abiertos en este chat, pero no borrará tu prueba, cupo ni solicitud comercial.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Confirmar reinicio",
                    callback_data=f"creator_setup_reset_confirm_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver a configuración",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

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


    if data.startswith("creator_setup_marketplace_"):

        request_id = extract_commercial_request_id(data, "creator_setup_marketplace_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_creator_marketplace_text(group_id),
            reply_markup=InlineKeyboardMarkup(
                build_creator_marketplace_keyboard(request_id)
            )
        )

        return


    if (
        data.startswith("creator_dynamic_preview_enable_")
        or data.startswith("creator_dynamic_preview_disable_")
        or data.startswith("creator_dynamic_preview_videos_")
        or data.startswith("creator_dynamic_preview_delete_")
    ):

        if data.startswith("creator_dynamic_preview_enable_"):

            request_id = extract_commercial_request_id(
                data,
                "creator_dynamic_preview_enable_"
            )
            action = "enable"

        elif data.startswith("creator_dynamic_preview_disable_"):

            request_id = extract_commercial_request_id(
                data,
                "creator_dynamic_preview_disable_"
            )
            action = "disable"

        elif data.startswith("creator_dynamic_preview_videos_"):

            request_id = extract_commercial_request_id(
                data,
                "creator_dynamic_preview_videos_"
            )
            action = "videos"

        elif data.startswith("creator_dynamic_preview_delete_video_"):

            payload = data.replace(
                "creator_dynamic_preview_delete_video_",
                "",
                1
            )

            try:

                request_id_text, video_id_text = payload.rsplit("_", 1)
                request_id = int(request_id_text)
                video_id = int(video_id_text)

            except Exception:

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "❌ Vídeo no válido."
                )

                return

            action = "delete_video"

        else:

            request_id = extract_commercial_request_id(
                data,
                "creator_dynamic_preview_delete_"
            )
            action = "delete"


        request_row = fetch_commercial_request(request_id)


        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "👁 Preview marketplace\n\nPrimero vincula un grupo/canal real para gestionar el preview dinámico.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        if action == "enable":

            set_group_preview_mode(group_id, "dynamic")

            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Preview dinámico activado.\n\n"
                "A partir de ahora se guardarán los vídeos que se publiquen en el grupo mientras el bot los reciba.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        if action == "disable":

            set_group_preview_mode(group_id, "manual")

            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Preview dinámico desactivado.\n\n"
                "Los vídeos guardados no se borran, pero ya no se capturarán nuevos vídeos para el preview dinámico.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        if action == "videos":

            await send_clean_message(
                context,
                query.message.chat_id,
                format_owner_dynamic_videos_text(group_id),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"creator_setup_marketplace_{request_id}"
                    )]
                ])
            )

            return


        if action == "delete":

            await send_clean_message(
                context,
                query.message.chat_id,
                format_owner_dynamic_videos_text(group_id),
                reply_markup=build_dynamic_video_delete_keyboard(
                    request_id,
                    group_id
                )
            )

            return


        if action == "delete_video":

            deleted = deactivate_dynamic_preview_video(
                video_id,
                group_id
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                (
                    "✅ Vídeo eliminado del preview."
                    if deleted
                    else "❌ Vídeo no encontrado."
                ),
                reply_markup=build_dynamic_video_delete_keyboard(
                    request_id,
                    group_id
                )
            )

            return


    if (
        data.startswith("creator_preview_mode_")
        and not data.startswith("creator_preview_mode_set_")
    ):

        request_id = extract_commercial_request_id(data, "creator_preview_mode_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "¿Qué tipo de preview quieres mostrar?\n\n"
            "📝 Preview fijo/manual: enseña un texto, imagen o vídeo teaser que tú configuras.\n\n"
            "⚡ Preview dinámico: enseña los últimos 3 vídeos publicados después de activar este modo. El bot no descarga vídeos, solo usa file_id.\n\n"
            "💎 Preview mixto: combina tu teaser manual con vídeos dinámicos recientes.\n\n"
            "🔒 Sin preview público: solo muestra información mínima de la comunidad.",
            reply_markup=build_preview_mode_keyboard(request_id)
        )

        return


    if data.startswith("creator_preview_mode_set_"):

        prefix = "creator_preview_mode_set_"
        remainder = data.replace(prefix, "", 1)

        try:

            request_id_text, preview_mode = remainder.rsplit("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Nivel de preview no válido."
            )

            return


        if preview_mode not in PREVIEW_MODE_LABELS:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Nivel de preview no válido."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "👁 Preview marketplace\n\n"
                "Primero vincula un grupo/canal real para guardar el nivel de preview.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET preview_mode=%s
                WHERE id=%s

            """, (
                preview_mode,
                group_id
            ))

            conn.commit()


        message = "✅ Tipo de preview actualizado."

        if preview_mode == "dynamic":

            message += (
                "\n\n"
                "A partir de ahora se guardarán los vídeos nuevos que se publiquen en el grupo mientras el bot los reciba. Solo se mostrarán los últimos 3."
            )

        elif preview_mode == "hybrid":

            if not group_has_manual_preview(group_id):

                context.user_data["marketplace_preview_media"] = True
                context.user_data["marketplace_preview_request_id"] = request_id
                context.user_data["marketplace_preview_media_type"] = "hybrid_manual"
                context.user_data["marketplace_preview_target_mode"] = "hybrid"

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "✅ Preview mixto activado.\n\n"
                    "Muestra primero el preview manual y además permite ver los últimos vídeos dinámicos.\n\n"
                    "Ahora envía una foto o vídeo fijo para el preview manual."
                )

                return


            message += (
                "\n\n"
                "Tu preview combinará el teaser manual con los últimos vídeos dinámicos disponibles."
            )

        elif preview_mode == "manual":

            context.user_data["marketplace_preview_media"] = True
            context.user_data["marketplace_preview_request_id"] = request_id
            context.user_data["marketplace_preview_media_type"] = "manual"
            context.user_data["marketplace_preview_target_mode"] = "manual"

            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Preview manual activado.\n\n"
                "Manual: subes una imagen o vídeo fijo que verán los usuarios antes de entrar.\n\n"
                "Envía ahora una foto o vídeo para guardarlo como preview manual."
            )

            return

        elif preview_mode == "private":

            message += (
                "\n\n"
                "La ficha pública mostrará solo información mínima."
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            message,
            reply_markup=InlineKeyboardMarkup(
                build_creator_marketplace_keyboard(request_id)
            )
        )

        return


    if data.startswith("creator_preview_text_"):

        request_id = extract_commercial_request_id(data, "creator_preview_text_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "marketplace_preview_text")

        await send_clean_message(
            context,
            query.message.chat_id,
            "📝 Editar texto preview\n\n"
            "Escribe el preview corto que quieres mostrar en el marketplace."
        )

        return


    if data.startswith("creator_preview_image_"):

        request_id = extract_commercial_request_id(data, "creator_preview_image_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if not get_marketplace_group_id_for_request(request_row):

            await send_clean_message(
                context,
                query.message.chat_id,
                "🖼 Añadir imagen preview\n\n"
                "Primero vincula un grupo/canal real para guardar la imagen preview.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        context.user_data["marketplace_preview_media"] = True
        context.user_data["marketplace_preview_request_id"] = request_id
        context.user_data["marketplace_preview_media_type"] = "image"

        await send_clean_message(
            context,
            query.message.chat_id,
            "🖼 Añadir imagen preview\n\n"
            "Envía ahora la foto que quieres usar como preview del marketplace."
        )

        return


    if data.startswith("creator_preview_video_"):

        request_id = extract_commercial_request_id(data, "creator_preview_video_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if not get_marketplace_group_id_for_request(request_row):

            await send_clean_message(
                context,
                query.message.chat_id,
                "🎬 Añadir vídeo preview\n\n"
                "Primero vincula un grupo/canal real para guardar el vídeo preview.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        context.user_data["marketplace_preview_media"] = True
        context.user_data["marketplace_preview_request_id"] = request_id
        context.user_data["marketplace_preview_media_type"] = "video"

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎬 Añadir vídeo preview\n\n"
            "Envía ahora el vídeo corto que quieres usar como preview del marketplace."
        )

        return


    if data.startswith("creator_preview_category_set_"):

        prefix = "creator_preview_category_set_"
        remainder = data.replace(prefix, "", 1)

        try:

            request_id_text, category = remainder.rsplit("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Categoría no válida."
            )

            return


        if category not in MARKETPLACE_CATEGORY_LABELS:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Categoría no válida."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📂 Elegir categoría\n\n"
                "Primero vincula un grupo/canal real para guardar la categoría.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET category=%s
                WHERE id=%s

            """, (
                category,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            f"✅ Categoría guardada: {MARKETPLACE_CATEGORY_LABELS.get(category)}",
            reply_markup=InlineKeyboardMarkup(
                build_creator_marketplace_keyboard(request_id)
            )
        )

        return


    if data.startswith("creator_preview_category_"):

        request_id = extract_commercial_request_id(data, "creator_preview_category_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "📂 Elegir categoría\n\n"
            "Selecciona la categoría principal de tu comunidad.",
            reply_markup=build_preview_category_keyboard(request_id)
        )

        return


    if data.startswith("creator_preview_tags_"):

        request_id = extract_commercial_request_id(data, "creator_preview_tags_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if not get_marketplace_group_id_for_request(request_row):

            await send_clean_message(
                context,
                query.message.chat_id,
                "🏷 Editar tags\n\n"
                "Primero vincula un grupo/canal real para guardar tags.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        start_creator_setup_state(context, request_id, "marketplace_tags")

        await send_clean_message(
            context,
            query.message.chat_id,
            "🏷 Editar tags\n\n"
            "Escribe los tags separados por comas. Ejemplo: señales, trading, vip"
        )

        return


    if data.startswith("creator_preview_show_"):

        request_id = extract_commercial_request_id(data, "creator_preview_show_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "👁 Ver cómo quedará\n\n"
                "Primero vincula un grupo/canal real para previsualizar la ficha.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_marketplace_keyboard(request_id)
                )
            )

            return


        group = fetch_marketplace_group(group_id)

        if not group:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad no encontrada o no disponible."
            )

            return


        await send_marketplace_preview(
            context,
            query.message.chat_id,
            group
        )

        return


    if data.startswith("creator_setup_group_"):

        request_id = extract_commercial_request_id(data, "creator_setup_group_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "group")

        await send_clean_message(
            context,
            query.message.chat_id,
            "📡 Grupo o canal\n\n"
            "Flujo recomendado:\n\n"
            "1️⃣ Añade este bot a tu grupo o canal.\n"
            "2️⃣ Dale permisos de administrador para gestionar enlaces, usuarios y mensajes de acceso.\n"
            "3️⃣ Espera 30 segundos.\n"
            "4️⃣ El bot detectará automáticamente el ID del grupo.\n"
            "5️⃣ Recibirás un mensaje privado para confirmar la vinculación.\n\n"
            "No necesitas usar bots externos para obtener el ID.\n\n"
            "Si quieres, puedes enviar aquí el link del grupo como referencia. "
            "El link no se usará para sacar el ID real; el ID real se detecta cuando añades el bot al grupo."
        )

        return


    if data.startswith("creator_setup_texts_"):

        request_id = extract_commercial_request_id(data, "creator_setup_texts_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "texts")

        await send_clean_message(
            context,
            query.message.chat_id,
            "📝 Textos y descripción\n\n"
            "Paso 1: escribe el nombre público de tu comunidad.\n\n"
            "Ejemplo: GrupoStarsVip"
        )

        return


    if data.startswith("creator_setup_stripe_"):

        request_id = extract_commercial_request_id(data, "creator_setup_stripe_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if request_row.get("payment_mode") == "free":

            await send_clean_message(
            context,
            query.message.chat_id,
                "💳 Métodos de pago\n\n"
                "Esta comunidad está marcada como gratuita. Puedes configurar grupo/canal y textos sin activar métodos de pago.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        keyboard = []


        if group_id:

            keyboard.extend([
                [InlineKeyboardButton("💳 Abrir métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("📋 Ver planes", callback_data="view_group_plans")],
                [InlineKeyboardButton("➕ Crear/editar planes", callback_data="edit_group_plans")]
            ])


        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=f"configure_community_{request_id}")])
        keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Configuración de pagos del grupo\n\n"
            "Marcar la comunidad como de pago no obliga a usar Stripe. Puedes activar uno o varios métodos de pago.\n\n"
            "💳 Pagos tradicionales\n"
            "- Stripe\n"
            "- PayPal\n"
            "- Revolut\n\n"
            "🪙 Cripto / USDT\n"
            "- ChangeNOW.io / Cripto\n"
            "- Tarjeta EUR → USDT / Guardarian\n\n"
            "🎟 Promociones\n"
            "- Códigos y promociones\n\n"
            "Guardarian permite que el comprador pague con tarjeta en euros y que tú recibas USDT en tu wallet.\n"
            "ChangeNOW sirve para pagos cripto y puede requerir revisión manual según configuración.\n\n"
            + (
                "Abre Métodos de pago del grupo para configurar cada proveedor."
                if group_id
                else
                "Primero vincula tu grupo/canal. Después podrás abrir Métodos de pago del grupo para configurar cada proveedor."
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data.startswith("creator_setup_plans_not_applicable_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_plans_not_applicable_"
        )
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
            "💰 Planes de acceso\n\n"
            "No aplica para comunidad gratuita.\n\n"
            "Puedes configurar grupo/canal y textos. No se pedirá Stripe ni price_id mientras el modo sea gratuito.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_plans_"):

        request_id = extract_commercial_request_id(data, "creator_setup_plans_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if request_row.get("payment_mode") == "free":

            await send_clean_message(
            context,
            query.message.chat_id,
                "💰 Planes de acceso\n\n"
                "No aplica para comunidad gratuita.\n\n"
                "No se pedirá Stripe ni price_id en este modo.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        _assigned, group_id = assign_owner_for_commercial_request(request_row)


        if not group_id:

            await send_clean_message(
            context,
            query.message.chat_id,
                "💰 Planes de acceso\n\n"
                "Pendiente de crear/publicar grupo.\n\n"
                "La tabla actual de planes necesita un groups.id real. "
                "No existe una estructura segura de planes pendientes por solicitud, así que primero hay que vincular el grupo/canal.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_setup_keyboard(
                        request_id,
                        request_row.get("payment_mode")
                    )
                )
            )

            return


        plan_count = get_creator_plan_count(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            "💰 Planes de acceso\n\n"
            f"Planes activos configurados: {plan_count}\n\n"
            "El price_id debe pertenecer al Stripe propio del creador. "
            "No se mezcla con el Stripe global del bot.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "➕ Crear plan",
                    callback_data=f"creator_setup_add_plan_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_add_plan_"):

        request_id = extract_commercial_request_id(data, "creator_setup_add_plan_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        _assigned, group_id = assign_owner_for_commercial_request(request_row)


        if not group_id:

            await send_clean_message(
            context,
            query.message.chat_id,
                "⚠️ No se puede crear un plan todavía.\n\n"
                "Falta un groups.id real asociado a tu solicitud.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_setup_keyboard(
                        request_id,
                        request_row.get("payment_mode")
                    )
                )
            )

            return


        start_creator_setup_state(context, request_id, "plan")

        await send_clean_message(
            context,
            query.message.chat_id,
            "💰 Crear plan de acceso\n\n"
            "Paso 1: escribe el nombre del plan."
        )

        return


    if data.startswith("creator_setup_access_type_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_type_")
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
            "💳 Tipo de acceso\n\n"
            "Elige cómo entrarán los usuarios a tu comunidad. Puedes cambiarlo mientras configuras la comunidad.",
            reply_markup=build_access_type_keyboard(request_id)
        )

        return


    if data.startswith("creator_setup_access_free_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_free_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        request_row = update_commercial_request_access_type(request_id, "free")

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Tipo de acceso actualizado.\n\n"
            "Tu comunidad queda como gratuita. No se pedirá Stripe ni price_id y se mostrará Entrar gratis.",
            reply_markup=InlineKeyboardMarkup(
                build_creator_setup_keyboard(
                    request_id,
                    request_row.get("payment_mode")
                )
            )
        )

        return


    if data.startswith("creator_setup_access_paid_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_paid_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        request_row = update_commercial_request_access_type(request_id, "paid")

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Tipo de acceso actualizado.\n\n"
            "Tu comunidad queda como de pago.\n\n"
            "Ahora configura planes y elige uno o varios métodos de pago: Stripe, PayPal, Revolut, ChangeNOW o Guardarian EUR → USDT.\n\n"
            "Marcarla como de pago no obliga a usar Stripe.",
            reply_markup=InlineKeyboardMarkup(
                build_creator_setup_keyboard(
                    request_id,
                    request_row.get("payment_mode")
                )
            )
        )

        return


    if data.startswith("creator_setup_location_gate_"):

        request_id = extract_commercial_request_id(data, "creator_setup_location_gate_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Restricción por ubicación\n\n"
                "Primero debes vincular tu grupo o canal. Después podrás activar esta restricción.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )],
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        enabled, region_label = get_group_location_gate_display(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            "📍 Restricción por ubicación\n\n"
            f"Estado: {'Activada' if enabled else 'Desactivada'}\n"
            f"Región permitida: {region_label}\n\n"
            "Si está activada, antes de entrar el usuario deberá enviar ubicación desde el botón oficial de Telegram.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_gate_enable_"):

        request_id = extract_commercial_request_id(data, "creator_location_gate_enable_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=COALESCE(allowed_region, %s),
                    allowed_region_type=COALESCE(allowed_region_type, %s)
                WHERE id=%s

            """, (
                "ES",
                LOCATION_REGION_TYPE_COUNTRY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Restricción por ubicación activada.\n\n"
            "Puedes restringir por país. En España también puedes restringir por comunidad autónoma.\n\n"
            "Región permitida: España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_gate_disable_"):

        request_id = extract_commercial_request_id(data, "creator_location_gate_disable_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if group_id:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups
                    SET location_gate_enabled=FALSE
                    WHERE id=%s

                """, (group_id,))

                conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Restricción por ubicación desactivada.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_country_menu_"):

        request_id = extract_commercial_request_id(data, "creator_location_country_menu_")
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
            "🌎 Elegir país\n\n"
            "Puedes restringir por país. En España también puedes restringir por comunidad autónoma.",
            reply_markup=build_location_country_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_spain_region_menu_"):

        request_id = extract_commercial_request_id(data, "creator_location_spain_region_menu_")
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
            "🇪🇸 España\n\n"
            "Elige toda España o una comunidad autónoma concreta.",
            reply_markup=build_spanish_autonomous_community_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_country_set_"):

        payload = data.replace("creator_location_country_set_", "", 1)

        try:

            request_id_text, country_code = payload.split("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ País no válido."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if (
            country_code not in HISPANIC_COUNTRY_LABELS
            or not commercial_request_belongs_to_user(request_row, user_id)
        ):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                country_code,
                LOCATION_REGION_TYPE_COUNTRY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            f"Región permitida: {HISPANIC_COUNTRY_LABELS.get(country_code)}.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_spain_region_set_"):

        payload = data.replace("creator_location_spain_region_set_", "", 1)

        try:

            request_id_text, region_slug = payload.split("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad autónoma no válida."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if (
            region_slug not in SPANISH_AUTONOMOUS_COMMUNITY_LABELS
            or region_slug == "all_spain"
            or not commercial_request_belongs_to_user(request_row, user_id)
        ):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                region_slug,
                LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            f"Región permitida: {SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(region_slug)}, España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_region_cv_"):

        request_id = extract_commercial_request_id(data, "creator_location_region_cv_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                COMUNIDAD_VALENCIANA_REGION,
                LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            "Región permitida: Comunidad Valenciana, España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_setup_visibility_"):

        request_id = extract_commercial_request_id(data, "creator_setup_visibility_")
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
            "👁 Visibilidad pública\n\n"
            f"Ubicación elegida: {format_public_visibility(request_row.get('requested_public_visibility'))}\n\n"
            "La visibilidad la define el propietario principal al aprobar la prueba.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_review_"):

        request_id = extract_commercial_request_id(data, "creator_setup_review_")
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
            build_creator_setup_summary(request_row),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_tutorial_"):

        request_id = extract_commercial_request_id(data, "creator_setup_tutorial_")
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
            "🧭 Tutorial paso a paso\n\n"
            "1. Crea o entra en tu cuenta de Stripe.\n"
            "2. En Stripe, busca las claves de desarrollador para copiar STRIPE_SECRET_KEY.\n"
            "3. Configura un webhook en Stripe y guarda el STRIPE_WEBHOOK_SECRET.\n"
            "4. Crea tus productos y precios en Stripe.\n"
            "5. Copia el price_id de cada precio y úsalo al crear planes en el bot.\n"
            "6. Prepara tu grupo/canal de Telegram y añade el bot.\n"
            "7. Asegúrate de que el bot tenga permisos de administrador para gestionar accesos.\n"
            "8. Vuelve a este panel y revisa la configuración.\n\n"
            "No inventes precios ni claves. Copia siempre los datos desde Stripe.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return


    if data.startswith("creator_setup_ai_"):

        request_id = extract_commercial_request_id(data, "creator_setup_ai_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await activate_ai_help_context(
            update,
            context,
            help_context="creator_setup"
        )

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

        if not plan.get("stripe_price_id"):

            await notify_commercial_admin(
                context,
                (
                    "📅 Plan comercial seleccionado\n\n"
                    f"Solicitud #{request_id}\n"
                    f"Usuario: {user_id}\n"
                    f"Plan: {plan.get('name') or '-'}\n"
                    "Falta stripe_price_id."
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"👁 Ver estado #{request_id}",
                        callback_data=f"admin_commercial_review_{request_id}"
                    )]
                ])
            )

            await query.message.reply_text(
                "Este plan todavía no tiene pago automático configurado. Un administrador debe añadir el price_id de Stripe."
            )

            return

        await notify_commercial_admin(
            context,
            (
                "📅 Plan comercial seleccionado\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan.get('name') or '-'}\n"
                "El pago automático comercial todavía está pendiente de conectar."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"👁 Ver estado #{request_id}",
                    callback_data=f"admin_commercial_review_{request_id}"
                )]
            ])
        )

        await query.message.reply_text(
            "El pago automático comercial todavía está pendiente de conectar."
        )

        return


    # =========================
    # PAGOS PAYPAL DE GRUPO
    # =========================

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


        if not is_paypal_group_checkout_available(group_id):

            await query.message.reply_text(
                "PayPal todavía no está configurado para esta comunidad.",
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


        if group_requires_location_gate(group_id):

            await request_location_verification(
                context,
                query.message.chat_id,
                group_id,
                "paypal_checkout",
                price_id=plan_id
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
                price_id=plan_id
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
                price_id=plan_id
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
                price_id=plan_id
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


    if group_requires_location_gate(group_id):

        await request_location_verification(
            context,
            query.message.chat_id,
            group_id,
            "checkout",
            price_id=data
        )

        return


    await create_checkout_for_user(
        context,
        query.message.chat_id,
        user_id,
        group_id,
        data
    )
