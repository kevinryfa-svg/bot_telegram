"""
owner_addon_callbacks: tramo extraído de callback_router.py.

Prefijos: owner_addon_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import stripe

from audit_log_service import log_event
from datetime import datetime
from db import conn
from owner_addon_service import (
    fetch_owner_addon_product,
    fetch_owner_addon_subscription,
    update_owner_addon_cancel_at_period_end,
    update_owner_addon_plan_from_stripe,
    update_owner_addon_subscription_from_stripe,
)
from rbac_helpers import is_super_admin
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

OWNER_ADDON_PLAN_CHANGE_CODES = (
    "ad_promo",
    "backups",
    "bundle_ads_backups"
)



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):
    from callback_router import fetch_group_basic_info as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)


def format_owner_addon_price(*args, **kwargs):
    from callback_router import format_owner_addon_price as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def mask_owner_addon_stripe_subscription_id(stripe_subscription_id):

    if not stripe_subscription_id:

        return "-"


    return f"{str(stripe_subscription_id)[:8]}***"


def owner_addon_status_meaning(status):

    return {
        "active": "Servicio activo",
        "trialing": "Servicio activo",
        "past_due": "Pago pendiente o fallido",
        "unpaid": "Pago pendiente o fallido",
        "checkout_pending": "Checkout creado, pago pendiente",
        "canceled": "Servicio cancelado",
        "incomplete": "Checkout o suscripción incompleta",
        "incomplete_expired": "Checkout incompleto caducado"
    }.get(status, "Estado no reconocido")


def user_can_view_owner_addon_subscription(user_id, subscription):

    if is_super_admin(user_id):

        return True


    group_id = subscription.get("group_id")

    if group_id:

        return user_has_group_permission_any(user_id, group_id, ["can_manage_groups"])


    return int(subscription.get("owner_user_id") or 0) == int(user_id)


def user_can_manage_owner_addon_billing(user_id, subscription):

    if is_super_admin(user_id):

        return True


    return int(subscription.get("owner_user_id") or 0) == int(user_id)


def owner_addon_can_change_plan(subscription, user_id):

    if not subscription:

        return False

    if subscription.get("addon_code") not in OWNER_ADDON_PLAN_CHANGE_CODES:

        return False

    if subscription.get("status") not in ("active", "trialing", "past_due"):

        return False

    if not subscription.get("stripe_subscription_id"):

        return False

    if not user_can_manage_owner_addon_billing(user_id, subscription):

        return False

    product = fetch_owner_addon_product(subscription.get("addon_code"))

    return bool(product and product.get("is_active"))


def owner_addon_subscription_supports_plan_change(subscription):

    if not subscription:

        return False

    return (
        subscription.get("addon_code") in OWNER_ADDON_PLAN_CHANGE_CODES
        and subscription.get("status") in ("active", "trialing", "past_due")
        and bool(subscription.get("stripe_subscription_id"))
        and bool(fetch_owner_addon_product(subscription.get("addon_code")))
    )


def build_owner_addon_manage_text(subscription):

    product = fetch_owner_addon_product(subscription.get("addon_code")) or {}
    group_id = subscription.get("group_id")
    group = fetch_group_basic_info(group_id) if group_id else None
    group_name = group[1] if group else "Todas tus comunidades" if group_id is None else f"Comunidad {group_id}"
    status = subscription.get("status") or "-"
    cancel_text = "sí" if subscription.get("cancel_at_period_end") else "no"

    return (
        "📦 Gestión de servicio extra\n\n"
        f"Servicio: {product.get('name') or subscription.get('addon_code')}\n"
        f"Comunidad: {group_name}\n"
        f"Estado: {status}\n"
        f"Significado: {owner_addon_status_meaning(status)}\n"
        f"Precio: {format_owner_addon_price(product) if product else '-'}\n"
        f"Fin del periodo: {format_commercial_datetime(subscription.get('current_period_end'))}\n"
        f"Cancelación programada: {cancel_text}\n"
        f"Stripe subscription: {mask_owner_addon_stripe_subscription_id(subscription.get('stripe_subscription_id'))}"
    )


def build_owner_addon_manage_keyboard(subscription, can_manage_billing=True):

    keyboard = []
    subscription_id = subscription.get("id")
    status = subscription.get("status")

    if status in ("active", "trialing") and can_manage_billing:

        if subscription.get("cancel_at_period_end"):

            keyboard.append([InlineKeyboardButton(
                "✅ Reactivar renovación",
                callback_data=f"owner_addon_reactivate_{subscription_id}"
            )])

        else:

            keyboard.append([InlineKeyboardButton(
                "🚫 Cancelar renovación",
                callback_data=f"owner_addon_cancel_{subscription_id}"
            )])


    if can_manage_billing and owner_addon_subscription_supports_plan_change(subscription):

        keyboard.append([InlineKeyboardButton(
            "🔁 Cambiar plan",
            callback_data=f"owner_addon_change_plan_{subscription_id}"
        )])


    if status in ("past_due", "unpaid"):

        keyboard.append([InlineKeyboardButton("🧩 Ver servicios extra", callback_data="owner_addons_menu")])

    elif status == "canceled":

        keyboard.append([InlineKeyboardButton(
            "💳 Contratar de nuevo",
            callback_data=f"owner_addon_product_{subscription.get('addon_code')}"
        )])


    keyboard.extend([
        [InlineKeyboardButton("⬅️ Mis servicios", callback_data="owner_addons_active")],
        [InlineKeyboardButton("🧩 Servicios extra", callback_data="owner_addons_menu")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_owner_addon_cancel_confirm_text(subscription):

    return (
        "⚠️ ¿Seguro que quieres cancelar la renovación?\n\n"
        "El servicio seguirá activo hasta el final del periodo actual.\n"
        "Las herramientas premium seguirán disponibles hasta esa fecha si Stripe mantiene la suscripción activa.\n"
        "No se procesan reembolsos desde el bot."
    )


def build_owner_addon_cancel_confirm_keyboard(subscription_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Sí, cancelar renovación",
            callback_data=f"owner_addon_cancel_yes_{subscription_id}"
        )],
        [InlineKeyboardButton(
            "❌ No, volver",
            callback_data=f"owner_addon_manage_{subscription_id}"
        )]
    ])


def build_owner_addon_change_plan_text(subscription):

    current_product = fetch_owner_addon_product(subscription.get("addon_code")) or {}
    group_id = subscription.get("group_id")
    group = fetch_group_basic_info(group_id) if group_id else None
    group_name = group[1] if group else "Todas tus comunidades" if group_id is None else f"Comunidad {group_id}"
    lines = [
        "🔁 Cambiar plan",
        "",
        f"Servicio actual: {current_product.get('name') or subscription.get('addon_code')}",
        f"Precio actual: {format_owner_addon_price(current_product) if current_product else '-'}",
        f"Comunidad: {group_name}",
        f"Estado: {subscription.get('status') or '-'}",
        "",
        "El cambio se aplicará sobre la suscripción mensual existente en Stripe.",
        ""
    ]

    products = [
        fetch_owner_addon_product(code)
        for code in OWNER_ADDON_PLAN_CHANGE_CODES
        if code != subscription.get("addon_code")
    ]

    unavailable = [
        product
        for product in products
        if product and (not product.get("is_active") or not product.get("stripe_price_id"))
    ]

    if unavailable:

        lines.append("Planes no disponibles ahora:")

        for product in unavailable:

            reason = "sin precio Stripe" if not product.get("stripe_price_id") else "inactivo"
            lines.append(f"- {product.get('name')}: {reason}")


    return "\n".join(lines)


def build_owner_addon_change_plan_keyboard(subscription):

    subscription_id = subscription.get("id")
    keyboard = []

    for code in OWNER_ADDON_PLAN_CHANGE_CODES:

        if code == subscription.get("addon_code"):

            continue

        product = fetch_owner_addon_product(code)

        if not product or not product.get("is_active") or not product.get("stripe_price_id"):

            continue

        keyboard.append([InlineKeyboardButton(
            f"{product.get('name')} · {format_owner_addon_price(product)}",
            callback_data=f"owner_addon_change_plan_to_{subscription_id}_{code}"
        )])


    keyboard.extend([
        [InlineKeyboardButton("⬅️ Volver", callback_data=f"owner_addon_manage_{subscription_id}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_owner_addon_change_plan_confirm_text(subscription, target_product):

    current_product = fetch_owner_addon_product(subscription.get("addon_code")) or {}

    return (
        "⚠️ ¿Confirmas el cambio de plan?\n\n"
        f"Plan actual: {current_product.get('name') or subscription.get('addon_code')}\n"
        f"Nuevo plan: {target_product.get('name') or target_product.get('code')}\n"
        f"Precio actual: {format_owner_addon_price(current_product) if current_product else '-'}\n"
        f"Nuevo precio: {format_owner_addon_price(target_product)}\n\n"
        "Stripe puede aplicar prorrateos o ajustes según la configuración de tu cuenta.\n"
        "No se crean ni eliminan accesos de usuarios.\n"
        "El cambio solo afecta a herramientas del owner."
    )


def build_owner_addon_change_plan_confirm_keyboard(subscription_id, target_code):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Confirmar cambio",
            callback_data=f"owner_addon_change_plan_confirm_{subscription_id}_{target_code}"
        )],
        [InlineKeyboardButton(
            "❌ Cancelar",
            callback_data=f"owner_addon_manage_{subscription_id}"
        )]
    ])


def extract_owner_addon_plan_change_payload(data, prefix):

    if not data.startswith(prefix):

        return None, None

    payload = data.replace(prefix, "", 1)
    subscription_text, target_code = payload.split("_", 1) if "_" in payload else (payload, "")

    if not subscription_text.isdigit():

        return None, None

    if target_code not in OWNER_ADDON_PLAN_CHANGE_CODES:

        return None, None

    return int(subscription_text), target_code


def extract_owner_addon_stripe_periods(stripe_subscription):

    current_period_start = None
    current_period_end = None

    try:

        current_period_start = datetime.fromtimestamp(
            int(stripe_subscription.get("current_period_start"))
        ) if stripe_subscription.get("current_period_start") else None

    except Exception:

        current_period_start = None


    try:

        current_period_end = datetime.fromtimestamp(
            int(stripe_subscription.get("current_period_end"))
        ) if stripe_subscription.get("current_period_end") else None

    except Exception:

        current_period_end = None


    return current_period_start, current_period_end


def apply_owner_addon_stripe_subscription_update(subscription_id, stripe_subscription):

    status = stripe_subscription.get("status")
    current_period_end = None

    try:

        current_period_end = datetime.fromtimestamp(
            int(stripe_subscription.get("current_period_end"))
        ) if stripe_subscription.get("current_period_end") else None

    except Exception:

        current_period_end = None


    current_period_start = None

    try:

        current_period_start = datetime.fromtimestamp(
            int(stripe_subscription.get("current_period_start"))
        ) if stripe_subscription.get("current_period_start") else None

    except Exception:

        current_period_start = None


    stripe_price_id = None
    items = (stripe_subscription.get("items") or {}).get("data") or []

    if items:

        stripe_price_id = ((items[0].get("price") or {}).get("id"))


    subscription = fetch_owner_addon_subscription(subscription_id)

    if not subscription:

        return None


    return update_owner_addon_subscription_from_stripe(
        subscription.get("stripe_subscription_id"),
        stripe_customer_id=stripe_subscription.get("customer"),
        stripe_price_id=stripe_price_id,
        status=status,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        cancel_at_period_end=stripe_subscription.get("cancel_at_period_end") is True
    )



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_owner_addon_callbacks(update, context, query, user_id, data):

    if (
        data.startswith("owner_addon_change_plan_confirm_")
        or data.startswith("owner_addon_change_plan_to_")
        or data.startswith("owner_addon_change_plan_")
    ):

        if data.startswith("owner_addon_change_plan_confirm_"):

            subscription_id, target_code = extract_owner_addon_plan_change_payload(
                data,
                "owner_addon_change_plan_confirm_"
            )

        elif data.startswith("owner_addon_change_plan_to_"):

            subscription_id, target_code = extract_owner_addon_plan_change_payload(
                data,
                "owner_addon_change_plan_to_"
            )

        else:

            subscription_id = extract_commercial_request_id(
                data,
                "owner_addon_change_plan_"
            )
            target_code = None


        subscription = fetch_owner_addon_subscription(subscription_id)

        if not subscription or not owner_addon_can_change_plan(subscription, user_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar este plan.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if subscription.get("group_id"):

            context.user_data["selected_group_admin"] = subscription.get("group_id")
            context.user_data["selected_owner_group"] = subscription.get("group_id")


        if data.startswith("owner_addon_change_plan_") and not data.startswith("owner_addon_change_plan_to_") and not data.startswith("owner_addon_change_plan_confirm_"):

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_addon_change_plan_text(subscription),
                reply_markup=build_owner_addon_change_plan_keyboard(subscription)
            )

            return


        target_product = fetch_owner_addon_product(target_code)

        if not target_product or not target_product.get("is_active"):

            await query.message.reply_text(
                "⚠️ El plan seleccionado no está disponible.",
                reply_markup=build_owner_addon_change_plan_keyboard(subscription)
            )

            return


        if not target_product.get("stripe_price_id"):

            await query.message.reply_text(
                "⚠️ Este plan todavía no tiene precio de Stripe configurado.",
                reply_markup=build_owner_addon_change_plan_keyboard(subscription)
            )

            return


        if data.startswith("owner_addon_change_plan_to_"):

            log_event(
                "owner_addon_plan_change_requested",
                category="billing",
                severity="info",
                scope="group",
                group_id=subscription.get("group_id"),
                actor_user_id=user_id,
                target_user_id=subscription.get("owner_user_id"),
                message="Cambio de plan de servicio extra solicitado.",
                metadata={
                    "owner_user_id": subscription.get("owner_user_id"),
                    "actor_user_id": user_id,
                    "group_id": subscription.get("group_id"),
                    "subscription_id": subscription_id,
                    "stripe_subscription_id": subscription.get("stripe_subscription_id"),
                    "from_addon_code": subscription.get("addon_code"),
                    "to_addon_code": target_code,
                    "from_price_id": subscription.get("stripe_price_id"),
                    "to_price_id": target_product.get("stripe_price_id")
                }
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_addon_change_plan_confirm_text(subscription, target_product),
                reply_markup=build_owner_addon_change_plan_confirm_keyboard(subscription_id, target_code)
            )

            return


        stripe_subscription_id = subscription.get("stripe_subscription_id")

        try:

            stripe_subscription = stripe.Subscription.retrieve(stripe_subscription_id)
            items = (stripe_subscription.get("items") or {}).get("data") or []
            item_id = (items[0] or {}).get("id") if items else None

            if not item_id:

                raise ValueError("No se encontró el item de suscripción en Stripe.")


            metadata = dict(stripe_subscription.get("metadata") or {})
            metadata.update({
                "purpose": "owner_addon",
                "owner_user_id": str(subscription.get("owner_user_id") or ""),
                "group_id": str(subscription.get("group_id") or ""),
                "addon_code": target_code
            })

            stripe_subscription = stripe.Subscription.modify(
                stripe_subscription_id,
                cancel_at_period_end=False,
                items=[{
                    "id": item_id,
                    "price": target_product.get("stripe_price_id")
                }],
                proration_behavior="create_prorations",
                metadata=metadata
            )

        except Exception as e:

            log_event(
                "owner_addon_plan_change_failed",
                category="billing",
                severity="error",
                scope="group",
                group_id=subscription.get("group_id"),
                actor_user_id=user_id,
                target_user_id=subscription.get("owner_user_id"),
                message="Error cambiando plan de servicio extra en Stripe.",
                metadata={
                    "owner_user_id": subscription.get("owner_user_id"),
                    "actor_user_id": user_id,
                    "group_id": subscription.get("group_id"),
                    "subscription_id": subscription_id,
                    "stripe_subscription_id": stripe_subscription_id,
                    "from_addon_code": subscription.get("addon_code"),
                    "to_addon_code": target_code,
                    "from_price_id": subscription.get("stripe_price_id"),
                    "to_price_id": target_product.get("stripe_price_id"),
                    "error": str(e)[:300]
                }
            )

            await query.message.reply_text(
                f"❌ No he podido cambiar el plan en Stripe: {str(e)[:300]}",
                reply_markup=build_owner_addon_manage_keyboard(subscription)
            )

            return


        current_period_start, current_period_end = extract_owner_addon_stripe_periods(stripe_subscription)

        try:

            updated_subscription = update_owner_addon_plan_from_stripe(
                subscription_id,
                target_code,
                target_product.get("stripe_price_id"),
                status=stripe_subscription.get("status"),
                current_period_start=current_period_start,
                current_period_end=current_period_end,
                cancel_at_period_end=stripe_subscription.get("cancel_at_period_end") is True
            )

            if not updated_subscription:

                raise RuntimeError("No se actualizó la suscripción local.")

        except Exception as e:

            try:

                conn.rollback()

            except Exception:

                pass

            log_event(
                "owner_addon_plan_change_local_update_failed",
                category="billing",
                severity="critical",
                scope="group",
                group_id=subscription.get("group_id"),
                actor_user_id=user_id,
                target_user_id=subscription.get("owner_user_id"),
                message="Stripe actualizó cambio de plan, pero falló actualización local.",
                metadata={
                    "owner_user_id": subscription.get("owner_user_id"),
                    "actor_user_id": user_id,
                    "group_id": subscription.get("group_id"),
                    "subscription_id": subscription_id,
                    "stripe_subscription_id": stripe_subscription_id,
                    "from_addon_code": subscription.get("addon_code"),
                    "to_addon_code": target_code,
                    "from_price_id": subscription.get("stripe_price_id"),
                    "to_price_id": target_product.get("stripe_price_id"),
                    "stripe_status": stripe_subscription.get("status"),
                    "error": str(e)[:300]
                }
            )

            await query.message.reply_text(
                "⚠️ Stripe actualizó el plan, pero no he podido actualizar el registro local. Revisa logs.",
                reply_markup=build_owner_addon_manage_keyboard(subscription)
            )

            return


        log_event(
            "owner_addon_plan_change_confirmed",
            category="billing",
            severity="info",
            scope="group",
            group_id=updated_subscription.get("group_id"),
            actor_user_id=user_id,
            target_user_id=updated_subscription.get("owner_user_id"),
            message="Plan de servicio extra actualizado.",
            metadata={
                "owner_user_id": updated_subscription.get("owner_user_id"),
                "actor_user_id": user_id,
                "group_id": updated_subscription.get("group_id"),
                "subscription_id": subscription_id,
                "stripe_subscription_id": stripe_subscription_id,
                "from_addon_code": subscription.get("addon_code"),
                "to_addon_code": target_code,
                "from_price_id": subscription.get("stripe_price_id"),
                "to_price_id": target_product.get("stripe_price_id"),
                "stripe_status": stripe_subscription.get("status")
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Plan actualizado correctamente.\n\n"
            f"Nuevo servicio: {target_product.get('name')}\n"
            f"Estado: {updated_subscription.get('status') or '-'}\n"
            f"Fin del periodo: {format_commercial_datetime(updated_subscription.get('current_period_end'))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Ver servicio", callback_data=f"owner_addon_manage_{subscription_id}")],
                [InlineKeyboardButton("📦 Mis servicios", callback_data="owner_addons_active")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    if (
        data.startswith("owner_addon_manage_")
        or data.startswith("owner_addon_cancel_yes_")
        or data.startswith("owner_addon_cancel_")
        or data.startswith("owner_addon_reactivate_")
    ):

        if data.startswith("owner_addon_manage_"):

            subscription_id = extract_commercial_request_id(
                data,
                "owner_addon_manage_"
            )
            subscription = fetch_owner_addon_subscription(subscription_id)

            if not subscription or not user_can_view_owner_addon_subscription(user_id, subscription):

                await query.message.reply_text(
                    "⛔ No tienes permiso para ver este servicio extra.",
                    reply_markup=build_owner_panel_nav_keyboard()
                )

                return


            if subscription.get("group_id"):

                context.user_data["selected_group_admin"] = subscription.get("group_id")
                context.user_data["selected_owner_group"] = subscription.get("group_id")


            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_addon_manage_text(subscription),
                reply_markup=build_owner_addon_manage_keyboard(
                    subscription,
                    can_manage_billing=user_can_manage_owner_addon_billing(user_id, subscription)
                )
            )

            return


        if data.startswith("owner_addon_cancel_yes_"):

            subscription_id = extract_commercial_request_id(
                data,
                "owner_addon_cancel_yes_"
            )
            subscription = fetch_owner_addon_subscription(subscription_id)

            if not subscription or not user_can_manage_owner_addon_billing(user_id, subscription):

                await query.message.reply_text("⛔ No tienes permiso para cancelar esta renovación.")
                return


            if subscription.get("group_id"):

                context.user_data["selected_group_admin"] = subscription.get("group_id")
                context.user_data["selected_owner_group"] = subscription.get("group_id")


            stripe_subscription_id = subscription.get("stripe_subscription_id")

            if not stripe_subscription_id:

                await query.message.reply_text(
                    "⚠️ Esta suscripción no tiene ID de Stripe asociado. No puedo gestionarla desde el bot.",
                    reply_markup=build_owner_addon_manage_keyboard(subscription)
                )

                return


            try:

                stripe_subscription = stripe.Subscription.modify(
                    stripe_subscription_id,
                    cancel_at_period_end=True
                )
                subscription = apply_owner_addon_stripe_subscription_update(
                    subscription_id,
                    stripe_subscription
                ) or update_owner_addon_cancel_at_period_end(subscription_id, True)

                log_event(
                    "owner_addon_cancel_renewal_requested",
                    category="billing",
                    severity="info",
                    scope="group",
                    group_id=subscription.get("group_id"),
                    actor_user_id=user_id,
                    target_user_id=subscription.get("owner_user_id"),
                    message="Cancelación de renovación de servicio extra solicitada.",
                    metadata={
                        "owner_user_id": subscription.get("owner_user_id"),
                        "buyer_user_id": user_id,
                        "group_id": subscription.get("group_id"),
                        "addon_code": subscription.get("addon_code"),
                        "stripe_subscription_id": stripe_subscription_id
                    }
                )

            except Exception as e:

                log_event(
                    "owner_addon_cancel_renewal_failed",
                    category="billing",
                    severity="error",
                    scope="group",
                    group_id=subscription.get("group_id"),
                    actor_user_id=user_id,
                    target_user_id=subscription.get("owner_user_id"),
                    message="Error cancelando renovación de servicio extra.",
                    metadata={
                        "owner_user_id": subscription.get("owner_user_id"),
                        "buyer_user_id": user_id,
                        "group_id": subscription.get("group_id"),
                        "addon_code": subscription.get("addon_code"),
                        "stripe_subscription_id": stripe_subscription_id,
                        "error": str(e)[:300]
                    }
                )

                await query.message.reply_text(
                    f"❌ No he podido cancelar la renovación en Stripe: {str(e)[:300]}",
                    reply_markup=build_owner_addon_manage_keyboard(subscription)
                )

                return


            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Renovación cancelada. El servicio seguirá activo hasta el final del periodo.",
                reply_markup=build_owner_addon_manage_keyboard(subscription)
            )

            return


        if data.startswith("owner_addon_cancel_"):

            subscription_id = extract_commercial_request_id(
                data,
                "owner_addon_cancel_"
            )
            subscription = fetch_owner_addon_subscription(subscription_id)

            if not subscription or not user_can_manage_owner_addon_billing(user_id, subscription):

                await query.message.reply_text("⛔ No tienes permiso para cancelar esta renovación.")
                return


            if subscription.get("group_id"):

                context.user_data["selected_group_admin"] = subscription.get("group_id")
                context.user_data["selected_owner_group"] = subscription.get("group_id")


            if not subscription.get("stripe_subscription_id"):

                await query.message.reply_text(
                    "⚠️ Esta suscripción no tiene ID de Stripe asociado. No puedo gestionarla desde el bot.",
                    reply_markup=build_owner_addon_manage_keyboard(subscription)
                )

                return


            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_addon_cancel_confirm_text(subscription),
                reply_markup=build_owner_addon_cancel_confirm_keyboard(subscription_id)
            )

            return


        if data.startswith("owner_addon_reactivate_"):

            subscription_id = extract_commercial_request_id(
                data,
                "owner_addon_reactivate_"
            )
            subscription = fetch_owner_addon_subscription(subscription_id)

            if not subscription or not user_can_manage_owner_addon_billing(user_id, subscription):

                await query.message.reply_text("⛔ No tienes permiso para reactivar esta renovación.")
                return


            if subscription.get("group_id"):

                context.user_data["selected_group_admin"] = subscription.get("group_id")
                context.user_data["selected_owner_group"] = subscription.get("group_id")


            stripe_subscription_id = subscription.get("stripe_subscription_id")

            if not stripe_subscription_id:

                await query.message.reply_text(
                    "⚠️ Esta suscripción no tiene ID de Stripe asociado. No puedo gestionarla desde el bot.",
                    reply_markup=build_owner_addon_manage_keyboard(subscription)
                )

                return


            try:

                stripe_subscription = stripe.Subscription.modify(
                    stripe_subscription_id,
                    cancel_at_period_end=False
                )
                subscription = apply_owner_addon_stripe_subscription_update(
                    subscription_id,
                    stripe_subscription
                ) or update_owner_addon_cancel_at_period_end(subscription_id, False)

                log_event(
                    "owner_addon_renewal_reactivated",
                    category="billing",
                    severity="info",
                    scope="group",
                    group_id=subscription.get("group_id"),
                    actor_user_id=user_id,
                    target_user_id=subscription.get("owner_user_id"),
                    message="Renovación de servicio extra reactivada.",
                    metadata={
                        "owner_user_id": subscription.get("owner_user_id"),
                        "buyer_user_id": user_id,
                        "group_id": subscription.get("group_id"),
                        "addon_code": subscription.get("addon_code"),
                        "stripe_subscription_id": stripe_subscription_id
                    }
                )

            except Exception as e:

                log_event(
                    "owner_addon_renewal_reactivate_failed",
                    category="billing",
                    severity="error",
                    scope="group",
                    group_id=subscription.get("group_id"),
                    actor_user_id=user_id,
                    target_user_id=subscription.get("owner_user_id"),
                    message="Error reactivando renovación de servicio extra.",
                    metadata={
                        "owner_user_id": subscription.get("owner_user_id"),
                        "buyer_user_id": user_id,
                        "group_id": subscription.get("group_id"),
                        "addon_code": subscription.get("addon_code"),
                        "stripe_subscription_id": stripe_subscription_id,
                        "error": str(e)[:300]
                    }
                )

                await query.message.reply_text(
                    f"❌ No he podido reactivar la renovación en Stripe: {str(e)[:300]}",
                    reply_markup=build_owner_addon_manage_keyboard(subscription)
                )

                return


            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Renovación reactivada.",
                reply_markup=build_owner_addon_manage_keyboard(subscription)
            )

            return

    return NOT_HANDLED
