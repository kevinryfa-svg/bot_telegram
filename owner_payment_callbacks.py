"""
Métodos de pago del propietario: elegir modo, cancelar, guardar y borrar.

Segunda fase de partir callback_router.py. Aquí viven los 16 botones del
asistente de proveedores de cobro del dueño de una comunidad — ChangeNOW,
Guardarian, PayPal y Revolut — en sus cuatro acciones.

Se ha movido tal cual, sin reescribir nada, y se ha comprobado botón por botón
que produce exactamente el mismo texto y los mismos teclados que antes.

Por qué quien llama puede retornar justo después: en el original las 16 ramas
terminaban todas en return, así que un callback que encajara con cualquiera de
los 16 prefijos ya salía de button() sin evaluar nada más. El guardián de la
llamada es la unión exacta de esos 16 prefijos, ni uno más: un callback
owner_payment_* que no encaje con ninguno sigue cayendo hacia las ramas de
después, igual que antes.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from audit_log_service import log_event
from payment_secret_store import (
    encrypt_provider_config,
    has_payment_encryption_key,
    mask_provider_config,
    mask_secret_value
)
from payment_service import (
    clear_group_payment_provider_config,
    save_group_payment_provider_encrypted_config
)
from plan_payment_provider_helpers import (
    PLAN_PAYMENT_PROVIDER_CHANGENOW as OWNER_PAYMENT_PROVIDER_CHANGENOW,
    PLAN_PAYMENT_PROVIDER_GUARDARIAN as OWNER_PAYMENT_PROVIDER_GUARDARIAN,
    PLAN_PAYMENT_PROVIDER_PAYPAL as OWNER_PAYMENT_PROVIDER_PAYPAL,
    PLAN_PAYMENT_PROVIDER_REVOLUT as OWNER_PAYMENT_PROVIDER_REVOLUT
)
from rbac_helpers import get_group_owner_user_id, is_super_admin
from ui_menu_helpers import send_clean_message
from wizard_state_helpers import clear_plan_wizard_state


# =========================
# PREFIJOS QUE ATIENDE ESTE MÓDULO
# =========================
# Esta lista es el contrato con callback_router: son exactamente los prefijos
# que antes tenían su propia rama dentro de button(). Se deja explícita para
# que se vea que el guardián no captura ni un callback de más.

OWNER_PAYMENT_CALLBACK_PREFIXES = (
    "owner_payment_changenow_mode_",
    "owner_payment_guardarian_mode_",
    "owner_payment_paypal_mode_",
    "owner_payment_revolut_mode_",
    "owner_payment_changenow_cancel_",
    "owner_payment_guardarian_cancel_",
    "owner_payment_paypal_cancel_",
    "owner_payment_revolut_cancel_",
    "owner_payment_changenow_save_",
    "owner_payment_guardarian_save_",
    "owner_payment_paypal_save_",
    "owner_payment_revolut_save_",
    "owner_payment_guardarian_confirm_delete_",
    "owner_payment_changenow_confirm_delete_",
    "owner_payment_paypal_confirm_delete_",
    "owner_payment_revolut_confirm_delete_",
)


# =========================
# AYUDANTES QUE SE QUEDAN EN callback_router
# =========================
# Los usan también los manejadores de texto del asistente, así que se quedan
# donde estaban. Se llaman de forma diferida porque callback_router importa este
# módulo: importarlo de vuelta arriba sería una importación circular.
#
# Los envoltorios existen para que el código movido quede idéntico al original.

def build_changenow_safe_summary(*args, **kwargs):

    from callback_router import build_changenow_safe_summary as impl

    return impl(*args, **kwargs)


def build_guardarian_safe_summary(*args, **kwargs):

    from callback_router import build_guardarian_safe_summary as impl

    return impl(*args, **kwargs)


def build_owner_changenow_cancel_keyboard(*args, **kwargs):

    from callback_router import build_owner_changenow_cancel_keyboard as impl

    return impl(*args, **kwargs)


def build_owner_guardarian_cancel_keyboard(*args, **kwargs):

    from callback_router import build_owner_guardarian_cancel_keyboard as impl

    return impl(*args, **kwargs)


def build_owner_panel_nav_keyboard(*args, **kwargs):

    from callback_router import build_owner_panel_nav_keyboard as impl

    return impl(*args, **kwargs)


def build_owner_paypal_cancel_keyboard(*args, **kwargs):

    from callback_router import build_owner_paypal_cancel_keyboard as impl

    return impl(*args, **kwargs)


def build_owner_paypal_safe_summary(*args, **kwargs):

    from callback_router import build_owner_paypal_safe_summary as impl

    return impl(*args, **kwargs)


def build_owner_revolut_cancel_keyboard(*args, **kwargs):

    from callback_router import build_owner_revolut_cancel_keyboard as impl

    return impl(*args, **kwargs)


def build_owner_revolut_safe_summary(*args, **kwargs):

    from callback_router import build_owner_revolut_safe_summary as impl

    return impl(*args, **kwargs)


def clear_owner_payment_provider_wizard(*args, **kwargs):

    from callback_router import clear_owner_payment_provider_wizard as impl

    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):

    from callback_router import extract_commercial_request_id as impl

    return impl(*args, **kwargs)



# =========================
# DESPACHO
# =========================

async def handle_owner_payment_callbacks(update, context, query, user_id, data):
    """
    Atiende los botones del asistente de métodos de pago del propietario.

    Quien llama comprueba OWNER_PAYMENT_CALLBACK_PREFIXES y retorna justo
    después: en el original las 16 ramas retornaban siempre.
    """

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


        clear_plan_wizard_state(
            context,
            user_id=user_id,
            action="owner_payment_changenow_mode"
        )

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


        clear_plan_wizard_state(
            context,
            user_id=user_id,
            action="owner_payment_guardarian_mode"
        )

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


        clear_plan_wizard_state(
            context,
            user_id=user_id,
            action="owner_payment_paypal_mode"
        )

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


        clear_plan_wizard_state(
            context,
            user_id=user_id,
            action="owner_payment_revolut_mode"
        )

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
                "Estado: configurado, pendiente de prueba real.\n"
                "Los cobros PayPal reales respetan ENABLE_PAYPAL_PAYMENTS y solo conceden acceso tras webhook verificado."
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


    # Ningún prefijo encajó. No puede ocurrir mientras el guardián de
    # callback_router sea la unión exacta de OWNER_PAYMENT_CALLBACK_PREFIXES,
    # pero deja la función con una salida explícita.
    return
