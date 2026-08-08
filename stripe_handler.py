import time
import stripe

from flask import request

from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from i18n_service import DEFAULT_LANGUAGE, load_user_language, t

from bot_config import TOKEN, ADMIN_ID, STRIPE_WEBHOOK_SECRET
from audit_log_service import log_event
from db import conn
from group_service import format_community_kind, normalize_community_type
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link,
    format_access_link_validity
)
from notification_service import notify_super_admins, send_telegram_message
from owner_addon_service import (
    activate_owner_addon_subscription_from_stripe,
    cancel_owner_addon_subscription_from_stripe,
    fetch_owner_addon_subscription_by_stripe_subscription_id,
    mark_owner_addon_subscription_payment_failed,
    update_owner_addon_subscription_from_stripe
)
from payment_gateway_config import (
    PAYMENT_PROVIDER_STRIPE,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_PAID,
    PURCHASE_TYPE_GROUP_ACCESS
)
from payment_service import create_payment_transaction
from rbac_helpers import get_group_owner_user_id


def get_payment_owner_user_id(group_id, telegram_group_id):

    owner_user_id = get_group_owner_user_id(group_id)


    if owner_user_id:

        return owner_user_id


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id
                FROM commercial_requests
                WHERE (
                    approved_group_id=%s
                    OR approved_telegram_group_id=%s
                )
                AND user_id IS NOT NULL
                ORDER BY updated_at DESC NULLS LAST,
                         created_at DESC
                LIMIT 1

            """, (
                group_id,
                telegram_group_id
            ))

            row = cur.fetchone()


        if row:

            return row[0]

    except Exception as e:

        print("Error buscando owner de pago:", e)


    return None


def format_payment_amount(amount, currency):

    if amount is None:

        return "-"


    try:

        return f"{int(amount) / 100:.2f} {(currency or '').upper()}".strip()

    except Exception:

        return f"{amount} {(currency or '').upper()}".strip()


# =========================
# MENSAJE DE COMPRA CONFIRMADA
# =========================
# Es el mensaje que más importa del bot: lo lee alguien que acaba de pagar.
# Antes era el enlace a secas, y eso deja al cliente sin saber si el cobro
# ha ido bien, qué ha comprado, cuánto le dura ni a quién preguntar.

def build_purchase_confirmation_text(group_name, plan_name, amount_total,
                                     currency, expiration, expire_seconds,
                                     link, language=DEFAULT_LANGUAGE):

    lines = [
        t("purchase.title", language),
        "",
        t("purchase.community", language, group=group_name)
    ]


    if plan_name:

        lines.append(t("purchase.plan", language, plan=plan_name))


    if amount_total is not None:

        lines.append(
            t(
                "purchase.amount",
                language,
                amount=format_payment_amount(amount_total, currency)
            )
        )


    lines.append("")

    if expiration is None:

        lines.append(t("purchase.permanent", language))

    else:

        try:

            fecha = expiration.strftime("%d/%m/%Y")

        except Exception:

            fecha = str(expiration)


        lines.append(t("purchase.until", language, date=fecha))


    lines.extend([
        "",
        t("purchase.link_title", language),
        str(link or ""),
        "",
        t(
            "purchase.link_validity",
            language,
            validity=format_access_link_validity(expire_seconds, language)
        ),
        "",
        t("purchase.keep_this", language)
    ])

    return "\n".join(lines)


def build_purchase_confirmation_keyboard(telegram_group_id, language=DEFAULT_LANGUAGE):
    """
    Botones del mensaje de compra: pedir otro enlace y hablar con soporte.

    Sin esto, alguien cuyo enlace fallara no tenía a dónde ir desde el propio
    mensaje del pago.
    """

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("button.my_access_now", language),
            callback_data=f"mysub_{telegram_group_id}"
        )],
        [InlineKeyboardButton(
            t("button.support", language),
            callback_data="public_support"
        )]
    ])


def mask_invite_link(invite_link):

    if not invite_link:

        return None


    return f"{str(invite_link)[:12]}***"


def stripe_timestamp_to_datetime(value):

    if not value:

        return None


    try:

        return datetime.fromtimestamp(int(value))

    except Exception:

        return None


def format_owner_addon_log_datetime(value):

    if not value:

        return None


    try:

        return value.isoformat()

    except Exception:

        return str(value)


def extract_owner_addon_subscription_payload(subscription):

    if not subscription:

        return {}


    items = (subscription.get("items") or {}).get("data") or []
    first_item = items[0] if items else {}
    price = first_item.get("price") or {}

    return {
        "stripe_subscription_id": subscription.get("id"),
        "stripe_customer_id": subscription.get("customer"),
        "stripe_price_id": price.get("id"),
        "status": subscription.get("status"),
        "current_period_start": stripe_timestamp_to_datetime(
            subscription.get("current_period_start")
        ),
        "current_period_end": stripe_timestamp_to_datetime(
            subscription.get("current_period_end")
        ),
        "cancel_at_period_end": subscription.get("cancel_at_period_end")
    }


def extract_stripe_subscription_id(value):

    if isinstance(value, dict):

        return value.get("id")


    return value


def owner_addon_subscription_metadata(subscription):

    return subscription.get("metadata") or {}


def is_owner_addon_subscription_object(subscription):

    metadata = owner_addon_subscription_metadata(subscription)

    return metadata.get("purpose") == "owner_addon"


def safe_notify_owner_addon(owner_user_id, text):

    if not owner_user_id:

        return None


    try:

        return send_telegram_message(
            TOKEN,
            owner_user_id,
            text
        )

    except Exception as e:

        print("Error notificando owner addon:", e)
        return None


def build_owner_addon_lifecycle_metadata(subscription_row, payload, event_type):

    subscription_row = subscription_row or {}
    payload = payload or {}

    return {
        "owner_user_id": subscription_row.get("owner_user_id"),
        "group_id": subscription_row.get("group_id"),
        "addon_code": subscription_row.get("addon_code"),
        "stripe_subscription_id": payload.get("stripe_subscription_id") or subscription_row.get("stripe_subscription_id"),
        "stripe_customer_id": payload.get("stripe_customer_id") or subscription_row.get("stripe_customer_id"),
        "stripe_price_id": payload.get("stripe_price_id") or subscription_row.get("stripe_price_id"),
        "status": payload.get("status") or subscription_row.get("status"),
        "current_period_end": format_owner_addon_log_datetime(
            payload.get("current_period_end") or subscription_row.get("current_period_end")
        ),
        "cancel_at_period_end": payload.get("cancel_at_period_end"),
        "event_type": event_type
    }


def process_owner_addon_checkout_completed(session):

    metadata = session.get("metadata") or {}
    stripe_session_id = session.get("id")

    try:

        owner_user_id = int(metadata.get("owner_user_id"))
        buyer_user_id = int(metadata.get("buyer_user_id") or owner_user_id)
        group_id = int(metadata.get("group_id"))
        addon_code = metadata.get("addon_code")
        stripe_subscription_id = extract_stripe_subscription_id(
            session.get("subscription")
        )
        stripe_customer_id = session.get("customer")
        payment_status = session.get("payment_status")
        subscription_status = None
        subscription_retrieved = False

        if not addon_code:

            raise ValueError("addon_code ausente")


        current_period_start = None
        current_period_end = None
        stripe_price_id = None
        resolved_status = "checkout_pending"
        cancel_at_period_end = False

        if stripe_subscription_id:

            try:

                subscription = stripe.Subscription.retrieve(stripe_subscription_id)
                subscription_retrieved = True
                payload = extract_owner_addon_subscription_payload(subscription)
                subscription_status = payload.get("status")
                current_period_start = payload.get("current_period_start")
                current_period_end = payload.get("current_period_end")
                stripe_price_id = payload.get("stripe_price_id")
                cancel_at_period_end = payload.get("cancel_at_period_end") is True

            except Exception as e:

                print("No se pudo obtener suscripción Stripe owner addon:", e)


        if subscription_retrieved:

            if subscription_status in ("active", "trialing"):

                resolved_status = subscription_status

        elif payment_status == "paid":

            resolved_status = "active"


        activate_owner_addon_subscription_from_stripe(
            owner_user_id=owner_user_id,
            group_id=group_id,
            addon_code=addon_code,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            stripe_price_id=stripe_price_id,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
            status=resolved_status
        )

        log_event(
            "owner_addon_checkout_completed",
            category="billing",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=buyer_user_id,
            target_user_id=owner_user_id,
            message="Checkout Stripe de servicio extra completado.",
            metadata={
                "owner_user_id": owner_user_id,
                "buyer_user_id": buyer_user_id,
                "group_id": group_id,
                "addon_code": addon_code,
                "status": resolved_status,
                "payment_status": payment_status,
                "subscription_status": subscription_status,
                "stripe_session_id": stripe_session_id,
                "stripe_subscription_id": stripe_subscription_id
            }
        )

        if resolved_status in ("active", "trialing"):

            send_telegram_message(
                TOKEN,
                owner_user_id,
                "✅ Servicio extra activado\n\n"
                f"Servicio: {addon_code}\n"
                f"Comunidad: {group_id}\n\n"
                "Ya puedes usar las herramientas asociadas a este servicio."
            )

        return False

    except Exception as e:

        print("Error procesando checkout owner addon:", e)

        log_event(
            "owner_addon_checkout_failed",
            category="billing",
            severity="error",
            scope="group",
            group_id=metadata.get("group_id"),
            actor_user_id=metadata.get("buyer_user_id"),
            target_user_id=metadata.get("owner_user_id"),
            message="Error procesando webhook Stripe de servicio extra.",
            metadata={
                "owner_user_id": metadata.get("owner_user_id"),
                "buyer_user_id": metadata.get("buyer_user_id"),
                "group_id": metadata.get("group_id"),
                "addon_code": metadata.get("addon_code"),
                "stripe_session_id": stripe_session_id,
                "stripe_subscription_id": session.get("subscription"),
                "payment_status": session.get("payment_status"),
                "error": str(e)[:300]
            }
        )

        return False


def process_owner_addon_subscription_updated(subscription, event_type):

    payload = extract_owner_addon_subscription_payload(subscription)
    stripe_subscription_id = payload.get("stripe_subscription_id")
    existing_row = fetch_owner_addon_subscription_by_stripe_subscription_id(
        stripe_subscription_id
    )

    if not is_owner_addon_subscription_object(subscription) and not existing_row:

        return False


    subscription_row = update_owner_addon_subscription_from_stripe(**payload)

    if not subscription_row:

        subscription_row = existing_row


    if not subscription_row:

        return False


    log_event(
        "owner_addon_subscription_updated",
        category="billing",
        severity="info",
        scope="group",
        group_id=subscription_row.get("group_id"),
        actor_user_id=subscription_row.get("owner_user_id"),
        target_user_id=subscription_row.get("owner_user_id"),
        message="Suscripción Stripe de servicio extra actualizada.",
        metadata=build_owner_addon_lifecycle_metadata(
            subscription_row,
            payload,
            event_type
        )
    )

    if payload.get("cancel_at_period_end") is True:

        safe_notify_owner_addon(
            subscription_row.get("owner_user_id"),
            "ℹ️ Tu servicio extra seguirá activo hasta el final del periodo."
        )

    elif payload.get("status") in ("active", "trialing"):

        safe_notify_owner_addon(
            subscription_row.get("owner_user_id"),
            "✅ Servicio extra actualizado."
        )


    return True


def process_owner_addon_subscription_deleted(subscription, event_type):

    payload = extract_owner_addon_subscription_payload(subscription)
    stripe_subscription_id = payload.get("stripe_subscription_id")
    existing_row = fetch_owner_addon_subscription_by_stripe_subscription_id(
        stripe_subscription_id
    )

    if not is_owner_addon_subscription_object(subscription) and not existing_row:

        return False


    subscription_row = cancel_owner_addon_subscription_from_stripe(
        stripe_subscription_id,
        status="canceled",
        cancel_at_period_end=payload.get("cancel_at_period_end")
    ) or existing_row

    if not subscription_row:

        return False


    log_event(
        "owner_addon_subscription_canceled",
        category="billing",
        severity="info",
        scope="group",
        group_id=subscription_row.get("group_id"),
        actor_user_id=subscription_row.get("owner_user_id"),
        target_user_id=subscription_row.get("owner_user_id"),
        message="Suscripción Stripe de servicio extra cancelada.",
        metadata=build_owner_addon_lifecycle_metadata(
            subscription_row,
            payload,
            event_type
        )
    )

    safe_notify_owner_addon(
        subscription_row.get("owner_user_id"),
        "❌ Servicio extra cancelado. Las herramientas premium asociadas dejarán de estar disponibles."
    )

    return True


def process_owner_addon_invoice_paid(invoice, event_type):

    stripe_subscription_id = extract_stripe_subscription_id(
        invoice.get("subscription")
    )
    subscription_row = fetch_owner_addon_subscription_by_stripe_subscription_id(
        stripe_subscription_id
    )

    if not subscription_row:

        return False


    payload = {
        "stripe_subscription_id": stripe_subscription_id,
        "stripe_customer_id": invoice.get("customer")
    }

    try:

        subscription = stripe.Subscription.retrieve(stripe_subscription_id)
        payload.update(extract_owner_addon_subscription_payload(subscription))

    except Exception as e:

        print("No se pudo obtener suscripción Stripe en invoice.paid owner addon:", e)
        payload["status"] = subscription_row.get("status")


    updated_row = update_owner_addon_subscription_from_stripe(**payload) or subscription_row

    log_event(
        "owner_addon_invoice_paid",
        category="billing",
        severity="info",
        scope="group",
        group_id=updated_row.get("group_id"),
        actor_user_id=updated_row.get("owner_user_id"),
        target_user_id=updated_row.get("owner_user_id"),
        message="Pago mensual de servicio extra recibido.",
        metadata=build_owner_addon_lifecycle_metadata(
            updated_row,
            payload,
            event_type
        )
    )

    safe_notify_owner_addon(
        updated_row.get("owner_user_id"),
        "✅ Pago mensual recibido. Tu servicio extra sigue activo."
    )

    return True


def process_owner_addon_invoice_payment_failed(invoice, event_type):

    stripe_subscription_id = extract_stripe_subscription_id(
        invoice.get("subscription")
    )
    subscription_row = fetch_owner_addon_subscription_by_stripe_subscription_id(
        stripe_subscription_id
    )

    if not subscription_row:

        return False


    payload = {
        "stripe_subscription_id": stripe_subscription_id,
        "stripe_customer_id": invoice.get("customer"),
        "status": "past_due"
    }

    try:

        subscription = stripe.Subscription.retrieve(stripe_subscription_id)
        payload.update(extract_owner_addon_subscription_payload(subscription))
        payload["status"] = payload.get("status") or "past_due"

    except Exception as e:

        print("No se pudo obtener suscripción Stripe en invoice.payment_failed owner addon:", e)


    updated_row = mark_owner_addon_subscription_payment_failed(
        stripe_subscription_id,
        stripe_customer_id=payload.get("stripe_customer_id"),
        status=payload.get("status") or "past_due"
    ) or subscription_row

    if payload.get("stripe_price_id") or payload.get("current_period_end") or payload.get("cancel_at_period_end") is not None:

        updated_row = update_owner_addon_subscription_from_stripe(
            stripe_subscription_id,
            stripe_customer_id=payload.get("stripe_customer_id"),
            stripe_price_id=payload.get("stripe_price_id"),
            status=payload.get("status") or "past_due",
            current_period_start=payload.get("current_period_start"),
            current_period_end=payload.get("current_period_end"),
            cancel_at_period_end=payload.get("cancel_at_period_end")
        ) or updated_row


    log_event(
        "owner_addon_invoice_payment_failed",
        category="billing",
        severity="warning",
        scope="group",
        group_id=updated_row.get("group_id"),
        actor_user_id=updated_row.get("owner_user_id"),
        target_user_id=updated_row.get("owner_user_id"),
        message="Falló el pago mensual de servicio extra.",
        metadata=build_owner_addon_lifecycle_metadata(
            updated_row,
            payload,
            event_type
        )
    )

    safe_notify_owner_addon(
        updated_row.get("owner_user_id"),
        "⚠️ Ha fallado el pago mensual de tu servicio extra. Revisa tu método de pago para evitar perder el acceso."
    )

    return True


def process_owner_addon_lifecycle_event(event):

    event_type = event.get("type")
    data_object = event["data"]["object"]

    try:

        if event_type == "customer.subscription.updated":

            return process_owner_addon_subscription_updated(
                data_object,
                event_type
            )


        if event_type == "customer.subscription.deleted":

            return process_owner_addon_subscription_deleted(
                data_object,
                event_type
            )


        if event_type == "invoice.paid":

            return process_owner_addon_invoice_paid(
                data_object,
                event_type
            )


        if event_type == "invoice.payment_failed":

            return process_owner_addon_invoice_payment_failed(
                data_object,
                event_type
            )

    except Exception as e:

        print("Error procesando lifecycle owner addon:", e)

        log_event(
            "owner_addon_lifecycle_webhook_failed",
            category="billing",
            severity="error",
            scope="global",
            message="Error procesando webhook lifecycle de servicio extra.",
            metadata={
                "event_type": event_type,
                "error": str(e)[:300]
            }
        )

        return True


    return False


# =========================
# WEBHOOK STRIPE
# =========================

def stripe_webhook():

    payload = request.data
    sig_header = request.headers.get("stripe-signature")

    try:

        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            STRIPE_WEBHOOK_SECRET
        )

    except Exception as e:

        print("Webhook error:", e)
        return "Error", 400


    if event["type"] in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed"
    ):

        if process_owner_addon_lifecycle_event(event):

            return "OK"


    if event["type"] == "checkout.session.completed":

        session = event["data"]["object"]
        metadata = session.get("metadata") or {}

        if metadata.get("purpose") == "owner_addon":

            process_owner_addon_checkout_completed(session)
            return "OK"

        user_id = int(
            session["metadata"]["telegram_id"]
        )
        stripe_session_id = session.get("id")
        stripe_payment_id = session.get("payment_intent") or stripe_session_id
        amount_total = session.get("amount_total")
        currency = (session.get("currency") or "").upper() or None


        # =========================
        # COMPROBAR SI ESTÁ BANEADO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id
                FROM banned_users
                WHERE user_id=%s

            """, (user_id,))

            banned = cur.fetchone()

            if banned:

                print("Usuario baneado intentó pagar:", user_id)

                log_event(
                    "payment_blocked_banned_user",
                    category="payment",
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Usuario baneado intentó completar un pago.",
                    metadata={
                        "stripe_session_id": stripe_session_id,
                        "stripe_payment_id": stripe_payment_id
                    }
                )

                return "OK"


        # =========================
        # OBTENER PLAN PAGADO
        # =========================

        line_items = stripe.checkout.Session.list_line_items(
            session["id"]
        )

        price_id = line_items["data"][0]["price"]["id"]

        metadata_group_id = int(
            session["metadata"]["group_id"]
        )

        create_payment_transaction(
            PAYMENT_PROVIDER_STRIPE,
            status=PAYMENT_STATUS_PAID,
            payment_scope=PAYMENT_SCOPE_PLATFORM,
            purchase_type=PURCHASE_TYPE_GROUP_ACCESS,
            user_id=user_id,
            group_id=metadata_group_id,
            amount=amount_total,
            currency=currency,
            external_payment_id=stripe_payment_id,
            external_checkout_id=stripe_session_id,
            idempotency_key=stripe_session_id,
            metadata={
                "price_id": price_id,
                "source": "stripe_webhook"
            }
        )

        # =========================
        # CALCULAR DURACIÓN
        # =========================

        try:

            metadata_group_id = int(
                session["metadata"]["group_id"]
            )

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT duration_days, name

                    FROM plans

                    WHERE COALESCE(stripe_price_id, price_id)=%s
                    AND group_id=%s
                    AND COALESCE(NULLIF(payment_provider, ''), 'stripe')='stripe'

                """, (

                    price_id,
                    metadata_group_id

                ))

                row = cur.fetchone()


            if not row:

                print(
                    "ERROR: plan no encontrado:",
                    price_id,
                    metadata_group_id
                )

                expiration = None
                plan_name = "Desconocido"

            else:

                duration_days, plan_name = row

                # plans.duration_days siempre está expresado en DÍAS.
                # El valor 0 se reserva para planes permanentes explícitos.

                if duration_days is None or duration_days == 0:

                    expiration = None

                else:

                    duration_value = int(duration_days)

                    if duration_value < 1 or duration_value > 3650:

                        print(
                            "ERROR: duración de plan fuera de rango:",
                            duration_value,
                            price_id,
                            metadata_group_id
                        )

                        log_event(
                            "payment_plan_duration_invalid",
                            category="payment",
                            severity="error",
                            scope="group",
                            group_id=metadata_group_id,
                            actor_user_id=user_id,
                            target_user_id=user_id,
                            message="Pago recibido con duración de plan fuera de rango.",
                            metadata={
                                "stripe_session_id": stripe_session_id,
                                "stripe_payment_id": stripe_payment_id,
                                "price_id": price_id,
                                "duration_days": duration_value
                            }
                        )

                        return "OK"


                    expiration = datetime.now() + timedelta(
                        days=duration_value
                    )

        except Exception as e:

            print(
                "Error calculando duración:",
                e
            )

            expiration = None
            plan_name = "Error"


        # =========================
        # GUARDAR USUARIO
        # =========================

        # =========================
        # CREAR LINK VIP (1 uso)
        # =========================

        group_id = int(
            session["metadata"]["group_id"]
        )

        # Obtener telegram_group_id real

        with conn.cursor() as cur:

            cur.execute("""

                SELECT telegram_group_id,
                       name,
                       COALESCE(community_type, 'group')

                FROM groups

                WHERE id=%s

            """, (group_id,))

            row = cur.fetchone()

            if not row:

                print("ERROR: grupo no encontrado en DB:", group_id)

                log_event(
                    "payment_group_not_found",
                    category="payment",
                    severity="error",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Pago recibido pero no se encontró el grupo interno.",
                    metadata={
                        "stripe_session_id": stripe_session_id,
                        "stripe_payment_id": stripe_payment_id,
                        "plan": plan_name,
                        "amount": amount_total,
                        "currency": currency
                    }
                )

                return "OK"

            telegram_group_id = row[0]
            group_name = row[1] or f"Grupo {group_id}"
            community_type = normalize_community_type(row[2])
            community_kind = format_community_kind(community_type)


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        # 24 h por defecto (ACCESS_LINK_EXPIRE_SECONDS) en vez de 180 s: el
        # enlace es de un solo uso y al entrar se comprueba el acceso, así que
        # los tres minutos solo dejaban fuera a clientes que ya habían pagado.
        max_expire = int(time.time()) + max(ACCESS_LINK_EXPIRE_SECONDS, 60)

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


        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=expire_seconds,
            member_limit=1,
            community_type=community_type
        )


        print(
            "Invite link creado:",
            f"group_id={group_id}",
            f"telegram_group_id={telegram_group_id}",
            f"user_id={user_id}",
            "status=created" if link else "status=failed",
            f"link_masked={mask_invite_link(link)}"
        )


        if not link:

            print("ERROR creando invite link")

            log_event(
                "payment_invite_link_error",
                category="payment",
                severity="error",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message=f"Pago confirmado pero no se pudo crear invite link para {community_kind}.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id,
                    "plan": plan_name,
                    "amount": amount_total,
                    "currency": currency,
                    "community_type": community_type
                }
            )

            notify_super_admins(
                TOKEN,
                "⚠️ Pago recibido pero no se pudo crear el link de acceso.\n\n"
                f"{format_community_kind(community_type).capitalize()}: {group_name}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}",
                fallback_admin_id=ADMIN_ID
            )

            return "OK"


        # =========================
        # GUARDAR LINK EN DATABASE
        # =========================

        try:

            with conn.cursor() as cur:

                # guardar acceso activo del comprador

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
                    ON CONFLICT (user_id, group_id)
                    DO UPDATE SET
                        expiration=EXCLUDED.expiration,
                        subscription_active=TRUE,
                        last_invite_link=EXCLUDED.last_invite_link

                """, (

                    user_id,
                    group_id,
                    expiration,
                    link

                ))


                # registrar pago

                cur.execute("""

                    INSERT INTO payments
                    (
                        user_id,
                        group_id,
                        stripe_payment_id,
                        amount,
                        currency,
                        status,
                        plan
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)

                """, (

                    user_id,
                    group_id,
                    stripe_payment_id,
                    amount_total,
                    currency,
                    "paid",
                    plan_name

                ))


                # borrar links antiguos del mismo usuario y grupo

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


                # guardar nuevo

                cur.execute("""

                    INSERT INTO invite_links
                    (
                        user_id,
                        group_id,
                        telegram_group_id,
                        invite_link,
                        is_active
                    )

                    VALUES (%s, %s, %s, %s, TRUE)

                """, (

                    user_id,
                    group_id,
                    telegram_group_id,
                    link

                ))


                conn.commit()

        except Exception as e:

            print("Error guardando invite link:", e)

            log_event(
                "payment_storage_error",
                category="payment",
                severity="error",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Pago confirmado pero falló el guardado del acceso/link.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id,
                    "plan": plan_name,
                    "amount": amount_total,
                    "currency": currency,
                    "error": str(e)
                }
            )

            notify_super_admins(
                TOKEN,
                "⚠️ Pago recibido pero falló el guardado del acceso.\n\n"
                f"Grupo: {group_name}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}",
                fallback_admin_id=ADMIN_ID
            )

            return "OK"


        log_event(
            "payment_confirmed",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Pago confirmado y acceso activado.",
            metadata={
                "stripe_session_id": stripe_session_id,
                "stripe_payment_id": stripe_payment_id,
                "plan": plan_name,
                "amount": amount_total,
                "currency": currency,
                "expiration": expiration
            }
        )

        log_event(
            "invite_link_created",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Invite link creado tras pago confirmado.",
            metadata={
                "stripe_session_id": stripe_session_id,
                "stripe_payment_id": stripe_payment_id
            }
        )


        # =========================
        # ENVIAR LINK AL USUARIO
        # =========================

        # Antes esto era una sola línea: "🔗 Tu acceso VIP:" y el enlace. Quien
        # acababa de pagar no veía confirmado el cobro, ni qué había comprado,
        # ni hasta cuándo, ni qué hacer si el enlace no funcionaba. Y sin
        # botones, la única salida era buscarse la vida por los menús.
        user_response = send_telegram_message(
            TOKEN,
            user_id,
            build_purchase_confirmation_text(
                group_name=group_name,
                plan_name=plan_name,
                amount_total=amount_total,
                currency=currency,
                expiration=expiration,
                expire_seconds=expire_seconds,
                link=link,
                language=load_user_language(user_id)
            ),
            reply_markup=build_purchase_confirmation_keyboard(
                telegram_group_id,
                language=load_user_language(user_id)
            ).to_dict()
        )


        if not user_response or not user_response.get("ok"):

            log_event(
                "payment_buyer_notification_error",
                category="notification",
                severity="warning",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="No se pudo notificar el link de acceso al comprador.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id
                }
            )


        # =========================
        # AVISAR AL ADMIN
        # =========================

        amount_text = format_payment_amount(
            amount_total,
            currency
        )


        admin_text = (
            f"💳 Nuevo pago recibido\n\n"
            f"Grupo: {group_name}\n"
            f"Usuario: {user_id}\n"
            f"Plan: {plan_name}\n"
            f"Importe: {amount_text}\n"
            "Acceso: activo"
        )

        sent_admins = notify_super_admins(
            TOKEN,
            admin_text,
            fallback_admin_id=ADMIN_ID
        )


        if sent_admins:

            log_event(
                "payment_admin_notified",
                category="notification",
                severity="info",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=ADMIN_ID,
                message="Super admin notificado de pago confirmado.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id,
                    "sent_admin_count": sent_admins
                }
            )

        else:

            log_event(
                "payment_admin_notification_error",
                category="notification",
                severity="error",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=ADMIN_ID,
                message="No se pudo notificar a ningún super admin del pago.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id
                }
            )

        owner_user_id = get_payment_owner_user_id(
            group_id,
            telegram_group_id
        )

        if owner_user_id and int(owner_user_id) != int(ADMIN_ID):

            owner_response = send_telegram_message(
                TOKEN,
                owner_user_id,
                f"💳 Nuevo pago en tu comunidad\n\n"
                f"Grupo: {group_name}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}\n"
                f"Importe: {amount_text}\n"
                "Acceso: activo"
            )


            if owner_response and owner_response.get("ok"):

                log_event(
                    "payment_owner_notified",
                    category="notification",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Owner notificado de nuevo pago.",
                    metadata={
                        "stripe_session_id": stripe_session_id,
                        "stripe_payment_id": stripe_payment_id
                    }
                )

            else:

                log_event(
                    "payment_owner_notification_error",
                    category="notification",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="No se pudo notificar al owner del pago.",
                    metadata={
                        "stripe_session_id": stripe_session_id,
                        "stripe_payment_id": stripe_payment_id
                    }
                )

        elif not owner_user_id:

            log_event(
                "payment_owner_not_found",
                category="payment",
                severity="warning",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Pago recibido pero no se encontró owner del grupo.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id,
                    "plan": plan_name,
                    "amount": amount_total,
                    "currency": currency
                }
            )

            notify_super_admins(
                TOKEN,
                "⚠️ Pago recibido pero no encontré owner del grupo\n\n"
                f"Grupo: {group_name}\n"
                f"ID interno: {group_id}\n"
                f"Telegram ID: {telegram_group_id}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}",
                fallback_admin_id=ADMIN_ID
            )


        print("Pago confirmado:", user_id)


    return "OK"
