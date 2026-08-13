"""
add_group_callbacks: tramo extraído de callback_router.py.

Prefijos: add_group_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from admin_payment_provider_callbacks import (
    OWNER_PAYMENT_PROVIDER_CHANGENOW,
    OWNER_PAYMENT_PROVIDER_GUARDARIAN,
)
from audit_log_service import log_event
from owner_group_callbacks import (
    OWNER_PAYMENT_PROVIDER_PAYPAL,
    OWNER_PAYMENT_PROVIDER_REVOLUT,
)
from payment_service import (
    is_paypal_group_checkout_available,
    is_stripe_payments_enabled,
    list_group_payment_provider_statuses,
)
from plan_payment_provider_helpers import (
    PLAN_PAYMENT_PROVIDER_LABELS,
    PLAN_PAYMENT_PROVIDER_STRIPE,
    format_plan_payment_provider,
)
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from ui_menu_helpers import send_clean_message
from wizard_state_helpers import (
    clear_owner_payment_provider_wizard_state,
    clear_plan_wizard_state,
)


# =========================
# CONSTANTES DE ESTE TRAMO
# =========================
# Viven aquí y las importa callback_router, no al revés: un envoltorio
# diferido no sirve para una constante, devolvería una función.

OWNER_PAYMENT_PROVIDER_STRIPE = PLAN_PAYMENT_PROVIDER_STRIPE


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



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_group_admin_error_keyboard(*args, **kwargs):
    from callback_router import build_group_admin_error_keyboard as impl
    return impl(*args, **kwargs)


def build_group_admin_panel_keyboard(*args, **kwargs):
    from callback_router import build_group_admin_panel_keyboard as impl
    return impl(*args, **kwargs)


def build_group_admin_permissions_keyboard(*args, **kwargs):
    from callback_router import build_group_admin_permissions_keyboard as impl
    return impl(*args, **kwargs)


def build_unknown_callback_keyboard(*args, **kwargs):
    from callback_router import build_unknown_callback_keyboard as impl
    return impl(*args, **kwargs)


def can_manage_group_admins(*args, **kwargs):
    from callback_router import can_manage_group_admins as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_group_name(*args, **kwargs):
    from callback_router import fetch_group_name as impl
    return impl(*args, **kwargs)


def format_group_admin_permission_list(*args, **kwargs):
    from callback_router import format_group_admin_permission_list as impl
    return impl(*args, **kwargs)


def get_group_payment_provider_status(*args, **kwargs):
    from callback_router import get_group_payment_provider_status as impl
    return impl(*args, **kwargs)


def get_selected_group_for_permissions(*args, **kwargs):
    from callback_router import get_selected_group_for_permissions as impl
    return impl(*args, **kwargs)


def is_group_provider_globally_disabled(*args, **kwargs):
    from callback_router import is_group_provider_globally_disabled as impl
    return impl(*args, **kwargs)


def save_group_admin_permissions(*args, **kwargs):
    from callback_router import save_group_admin_permissions as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def is_group_provider_configurable_for_plan(provider_status):

    if not provider_status:

        return False

    provider = provider_status.get("provider")

    if provider == OWNER_PAYMENT_PROVIDER_STRIPE:

        return provider_status.get("global_enabled") is True

    if provider in (
        OWNER_PAYMENT_PROVIDER_PAYPAL,
        OWNER_PAYMENT_PROVIDER_REVOLUT,
        OWNER_PAYMENT_PROVIDER_CHANGENOW,
        OWNER_PAYMENT_PROVIDER_GUARDARIAN
    ):

        return (
            provider_status.get("group_enabled") is True
            and provider_status.get("status") == "active"
            and provider_status.get("has_encrypted_config") is True
        )

    return False


def get_group_plan_configurable_payment_providers(group_id):

    provider_statuses = list_group_payment_provider_statuses(group_id)
    stripe_status = get_group_payment_provider_status(
        provider_statuses,
        OWNER_PAYMENT_PROVIDER_STRIPE
    )
    paypal_status = get_group_payment_provider_status(
        provider_statuses,
        OWNER_PAYMENT_PROVIDER_PAYPAL
    )
    providers = []


    for provider in (
        OWNER_PAYMENT_PROVIDER_STRIPE,
        OWNER_PAYMENT_PROVIDER_PAYPAL,
        OWNER_PAYMENT_PROVIDER_REVOLUT,
        OWNER_PAYMENT_PROVIDER_CHANGENOW,
        OWNER_PAYMENT_PROVIDER_GUARDARIAN
    ):

        provider_status = get_group_payment_provider_status(
            provider_statuses,
            provider
        )

        if is_group_provider_configurable_for_plan(provider_status):

            providers.append(provider)


    log_event(
        "plan_provider_detection",
        category="payment",
        severity="info",
        scope="group",
        group_id=group_id,
        message="Detección de proveedores configurables para creación de planes.",
        metadata={
            "group_id": group_id,
            "stripe_configurable": is_group_provider_configurable_for_plan(stripe_status),
            "stripe_checkout_available": is_stripe_payments_enabled(),
            "paypal_configurable": is_group_provider_configurable_for_plan(paypal_status),
            "paypal_checkout_available": is_paypal_group_checkout_available(group_id),
            "providers_for_plan_creation": providers
        }
    )

    return providers


def build_plan_provider_global_warning(group_id, provider):

    provider_status = get_group_payment_provider_status(
        list_group_payment_provider_statuses(group_id),
        provider
    )

    if provider == OWNER_PAYMENT_PROVIDER_PAYPAL and is_group_provider_globally_disabled(provider_status):

        return (
            "⚠️ PayPal está configurado para esta comunidad, pero el pago PayPal está "
            "deshabilitado globalmente. Podrás crear el plan, pero los clientes no podrán "
            "pagarlo hasta que se active ENABLE_PAYPAL_PAYMENTS.\n\n"
        )

    return ""


def build_plan_provider_selection_keyboard(providers):

    keyboard = []

    for provider in providers:

        keyboard.append([InlineKeyboardButton(
            format_plan_payment_provider(provider),
            callback_data=f"add_group_plan_provider_{provider}"
        )])


    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="edit_group_plans")])

    return InlineKeyboardMarkup(keyboard)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_add_group_callbacks(update, context, query, user_id, data):

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


        clear_plan_wizard_state(
            context,
            user_id=user_id,
            action="start_add_group_plan"
        )
        clear_owner_payment_provider_wizard_state(
            context,
            user_id=user_id,
            action="start_add_group_plan"
        )

        providers = get_group_plan_configurable_payment_providers(group_id)

        if not providers:

            log_event(
                "plan_provider_missing_config",
                category="payment",
                severity="warning",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Intento de crear plan sin proveedores de pago configurados.",
                metadata={
                    "group_id": group_id,
                    "user_id": user_id
                }
            )

            await query.message.reply_text(
                "⚠️ Primero configura al menos un método de pago para esta comunidad.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚙️ Configurar pagos", callback_data="owner_panel_payments")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data="edit_group_plans")]
                ])
            )

            return


        if len(providers) > 1:

            await query.message.reply_text(
                "➕ CREAR NUEVO PLAN\n\n"
                "Elige para qué método de pago quieres crear este plan:",
                reply_markup=build_plan_provider_selection_keyboard(providers)
            )

            return


        context.user_data["adding_plan"] = True
        context.user_data["add_plan_step"] = 1
        context.user_data["new_plan"] = {
            "payment_provider": providers[0]
        }
        provider_warning = build_plan_provider_global_warning(group_id, providers[0])

        log_event(
            "plan_wizard_provider_selected",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Proveedor único seleccionado automáticamente para nuevo plan.",
            metadata={
                "group_id": group_id,
                "user_id": user_id,
                "provider": providers[0]
            }
        )


        await query.message.reply_text(

            "➕ CREAR NUEVO PLAN\n\n"
            f"Método seleccionado: {format_plan_payment_provider(providers[0])}\n\n"
            f"{provider_warning}"

            "Paso 1️⃣\n"
            "Introduce el nombre del plan.\n\n"

            "Ejemplo:\n"
            "VIP Mensual"

        )

        return

    if data.startswith("add_group_plan_provider_"):

        provider = data.replace("add_group_plan_provider_", "", 1).strip().lower()

        if provider not in PLAN_PAYMENT_PROVIDER_LABELS:

            await query.message.reply_text(
                "⚠️ Método de pago no reconocido.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return

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


        providers = get_group_plan_configurable_payment_providers(group_id)

        if provider not in providers:

            await query.message.reply_text(
                "⚠️ Este método de pago no está configurado para esta comunidad.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚙️ Configurar pagos", callback_data="owner_panel_payments")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data="edit_group_plans")]
                ])
            )

            return


        clear_plan_wizard_state(
            context,
            user_id=user_id,
            action="start_add_group_plan_provider"
        )
        clear_owner_payment_provider_wizard_state(
            context,
            user_id=user_id,
            action="start_add_group_plan_provider"
        )

        context.user_data["adding_plan"] = True
        context.user_data["add_plan_step"] = 1
        context.user_data["new_plan"] = {
            "payment_provider": provider
        }
        provider_warning = build_plan_provider_global_warning(group_id, provider)

        log_event(
            "plan_wizard_provider_selected",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Proveedor seleccionado para nuevo plan.",
            metadata={
                "group_id": group_id,
                "user_id": user_id,
                "provider": provider
            }
        )

        await query.message.reply_text(
            "➕ CREAR NUEVO PLAN\n\n"
            f"Método seleccionado: {format_plan_payment_provider(provider)}\n\n"
            f"{provider_warning}"
            "Paso 1️⃣\n"
            "Introduce el nombre del plan.\n\n"
            "Ejemplo:\n"
            "VIP Mensual"
        )

        return

    return NOT_HANDLED
