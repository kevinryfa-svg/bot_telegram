"""
admin_payment_provider_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_payment_changenow, admin_payment_guardarian

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import log_event
from payment_secret_store import (
    encrypt_provider_config,
    has_payment_encryption_key,
    mask_secret_value,
)
from payment_service import (
    clear_platform_payment_provider_config,
    disable_platform_payment_provider_config,
    ensure_platform_payment_provider_config,
    fetch_platform_payment_provider_config,
    save_platform_payment_provider_encrypted_config,
)
from plan_payment_provider_helpers import (
    PLAN_PAYMENT_PROVIDER_CHANGENOW,
    PLAN_PAYMENT_PROVIDER_GUARDARIAN,
)
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from ui_menu_helpers import send_clean_message


# =========================
# CONSTANTES DE ESTE TRAMO
# =========================
# Viven aquí y las importa callback_router, no al revés: un envoltorio
# diferido no sirve para una constante, devolvería una función.

OWNER_PAYMENT_PROVIDER_CHANGENOW = PLAN_PAYMENT_PROVIDER_CHANGENOW


OWNER_PAYMENT_PROVIDER_GUARDARIAN = PLAN_PAYMENT_PROVIDER_GUARDARIAN



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_admin_payment_providers_keyboard(*args, **kwargs):
    from callback_router import build_admin_payment_providers_keyboard as impl
    return impl(*args, **kwargs)


def build_changenow_safe_summary(*args, **kwargs):
    from callback_router import build_changenow_safe_summary as impl
    return impl(*args, **kwargs)


def build_changenow_tutorial_text(*args, **kwargs):
    from callback_router import build_changenow_tutorial_text as impl
    return impl(*args, **kwargs)


def build_guardarian_safe_summary(*args, **kwargs):
    from callback_router import build_guardarian_safe_summary as impl
    return impl(*args, **kwargs)


def build_guardarian_tutorial_text(*args, **kwargs):
    from callback_router import build_guardarian_tutorial_text as impl
    return impl(*args, **kwargs)


def build_platform_changenow_cancel_keyboard(*args, **kwargs):
    from callback_router import build_platform_changenow_cancel_keyboard as impl
    return impl(*args, **kwargs)


def build_platform_guardarian_cancel_keyboard(*args, **kwargs):
    from callback_router import build_platform_guardarian_cancel_keyboard as impl
    return impl(*args, **kwargs)


def clear_owner_payment_provider_wizard(*args, **kwargs):
    from callback_router import clear_owner_payment_provider_wizard as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_platform_changenow_mode_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Fixed", callback_data="admin_payment_changenow_mode_fixed")],
        [InlineKeyboardButton("🌊 Floating", callback_data="admin_payment_changenow_mode_float")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_payment_changenow_cancel")],
        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data="admin_payment_changenow")]
    ])


def build_platform_guardarian_mode_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Sandbox", callback_data="admin_payment_guardarian_mode_sandbox")],
        [InlineKeyboardButton("🚀 Live", callback_data="admin_payment_guardarian_mode_live")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_payment_guardarian_cancel")],
        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data="admin_payment_guardarian")]
    ])



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_payment_provider_callbacks(update, context, query, user_id, data):

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

    return NOT_HANDLED
