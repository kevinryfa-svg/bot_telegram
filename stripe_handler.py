import json
import time
import stripe

from flask import request

from datetime import datetime, timedelta

from i18n_service import load_user_language, t

from bot_config import TOKEN, ADMIN_ID, STRIPE_WEBHOOK_SECRET
from audit_log_service import log_event
from db import conn
from group_service import format_community_kind, normalize_community_type
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link
)
from notification_service import notify_super_admins, send_telegram_message
from owner_addon_service import (
    activate_owner_addon_subscription_from_stripe,
    cancel_owner_addon_subscription_from_stripe,
    fetch_owner_addon_subscription_by_stripe_subscription_id,
    mark_owner_addon_subscription_payment_failed,
    update_owner_addon_subscription_from_stripe
)
from payment_access_service import MAX_PLAN_DURATION_DAYS
from payment_gateway_config import (
    PAYMENT_PROVIDER_STRIPE,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_PAID,
    PURCHASE_TYPE_GROUP_ACCESS
)
from payment_incident_service import (
    INCIDENT_BANNED_BUYER,
    INCIDENT_GROUP_MISSING,
    INCIDENT_PLAN_INVALID,
    INCIDENT_STORAGE_FAILED,
    report_payment_incident,
    resolve_incidents_for
)
from group_subscription_service import (
    align_expiration_with_trial,
    attach_subscription_to_member,
    extraer_subscription_id,
    process_group_subscription_lifecycle_event,
    recurso_plano
)
from purchase_message_service import build_buyer_message
from refund_service import (
    REFUND_REASON_DISPUTE,
    REFUND_REASON_REFUND,
    process_refund
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


# Los mensajes al comprador viven en purchase_message_service.py: los usan
# también los otros cuatro proveedores de cobro, y tenerlos duplicados aquí es
# lo que hizo que se arreglaran en un camino y no en el otro.


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


def process_platform_plan_checkout_completed(session):
    """El pago del plan de publicación: le da el cupo a quien lo ha pagado.

    Aquí no se escribe un pago en la tabla de pagos de comunidades: esto no es
    la compra de un acceso, es la cuota de la plataforma. Mezclarlas
    desvirtuaría los ingresos de los propietarios, que es la regla 7.
    """

    from platform_plan_service import activate_platform_plan

    metadata = session.get("metadata") or {}

    try:

        user_id = int(metadata.get("user_id"))

    except (TypeError, ValueError):

        log_event(
            "platform_plan_checkout_without_user",
            category="billing",
            severity="error",
            scope="global",
            message="Checkout del plan de publicación sin user_id utilizable.",
            metadata={"stripe_session_id": session.get("id")},
        )

        return False

    stripe_subscription_id = extract_stripe_subscription_id(
        session.get("subscription")
    )
    commercial_plan_id = metadata.get("commercial_plan_id")

    period_end = None
    estado = "active"

    if stripe_subscription_id:

        try:

            suscripcion = recurso_plano(
                stripe.Subscription.retrieve(stripe_subscription_id)
            )

            # El recurso del SDK no es un diccionario (regla 1): recurso_plano
            # antes de tocar nada.
            estado_stripe = suscripcion.get("status")

            # trialing cuenta como activo: la prueba la promete el catálogo, y
            # durante ella tiene que poder publicar o la prueba no prueba nada.
            if estado_stripe in ("active", "trialing"):
                estado = "active"

            fin = suscripcion.get("current_period_end")

            if fin:
                period_end = datetime.fromtimestamp(int(fin))

        except Exception as e:

            # Sin la fecha se activa igual: quien ha pagado no puede quedarse
            # esperando porque una segunda llamada a Stripe fallara.
            print("Plan de plataforma: no se pudo leer la suscripción:",
                  str(e)[:200])

    activado = activate_platform_plan(
        user_id,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=session.get("customer"),
        period_end=period_end,
        status=estado,
    )

    log_event(
        "platform_plan_checkout_completed",
        category="billing",
        severity="info" if activado else "error",
        scope="global",
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Checkout del plan de publicación procesado.",
        metadata={
            "stripe_session_id": session.get("id"),
            "commercial_plan_id": commercial_plan_id,
            "activated": bool(activado),
        },
    )

    if activado:

        try:

            send_telegram_message(
                TOKEN,
                user_id,
                "✅ Plan activado\n\n"
                "Ya puedes publicar tu comunidad en el bot y cobrar "
                "suscripciones con acceso automático.\n\n"
                "Abre el menú y pulsa «🚀 Publicar mi comunidad» para "
                "configurarla."
            )

        except Exception as e:

            print("Plan de plataforma: no se pudo avisar al propietario:",
                  str(e)[:200])

    return activado


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

                subscription = recurso_plano(
            stripe.Subscription.retrieve(stripe_subscription_id)
        )
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

        subscription = recurso_plano(
            stripe.Subscription.retrieve(stripe_subscription_id)
        )
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

        subscription = recurso_plano(
            stripe.Subscription.retrieve(stripe_subscription_id)
        )
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

        stripe.Webhook.construct_event(
            payload,
            sig_header,
            STRIPE_WEBHOOK_SECRET
        )

    except Exception as e:

        print("Webhook error:", e)
        return "Error", 400


    # LA FRONTERA. construct_event verifica la firma, pero en stripe 15.x
    # devuelve StripeObjects que NO son diccionarios: no tienen .get(), y todo
    # este fichero (y los procesadores de extras) usa .get() a cada paso — el
    # primer evento real habría reventado el cobro con "AttributeError: get",
    # el mismo fallo que ya tumbó la autoconfiguración del webhook en
    # producción. La firma ya está verificada, así que se trabaja con el JSON
    # verificado en crudo, que es un dict de verdad.
    event = json.loads(payload)


    if event["type"] in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed"
    ):

        if process_owner_addon_lifecycle_event(event):

            return "OK"

        # Renovación automática del acceso a comunidades: cada despacho
        # reconoce solo lo suyo por su propia ancla, así que el orden entre
        # este y el de extras no importa.
        if process_group_subscription_lifecycle_event(event):

            return "OK"


    # =========================
    # DEVOLUCIONES Y DISPUTAS
    # =========================
    # Estos eventos no se escuchaban. Alguien podía pagar, entrar, pedir la
    # devolución y quedarse dentro para siempre; y en una disputa de tarjeta
    # perdías el dinero y el acceso seguía dado.

    if event["type"] in ("charge.refunded", "charge.refund.updated"):

        objeto = event["data"]["object"]

        # En charge.refunded el objeto es el cargo; en charge.refund.updated es
        # el reembolso, que trae el cargo dentro y no la misma información.
        es_reembolso = event["type"] == "charge.refund.updated"

        payment_intent = (
            objeto.get("payment_intent")
            or (objeto.get("charge") if isinstance(objeto.get("charge"), str) else None)
        )

        # charge.refund.updated también salta cuando un reembolso falla o se
        # cancela. Ahí no se ha devuelto nada: retirar el acceso dejaría al
        # cliente pagado y fuera, que es peor que el fallo que se arregla aquí.
        if es_reembolso and objeto.get("status") != "succeeded":

            log_event(
                "refund_not_succeeded_ignored",
                category="payment",
                severity="info",
                message="Reembolso no completado: el acceso se mantiene.",
                metadata={
                    "payment_intent": str(payment_intent or "")[:64],
                    "refund_status": str(objeto.get("status") or "")[:32]
                }
            )

            return "OK"


        # Un reembolso parcial no quita el acceso: se ha devuelto parte, pero lo
        # que compró sigue siendo suyo.
        #
        # El cargo trae los dos importes y se puede decidir aquí. El objeto
        # reembolso solo trae lo devuelto, así que la comparación la hace
        # process_refund contra el importe del pago que tenemos guardado.
        if es_reembolso:

            importe = None
            devuelto = objeto.get("amount")

        else:

            importe = objeto.get("amount")
            devuelto = objeto.get("amount_refunded")


        if (
            importe is not None
            and devuelto is not None
            and int(devuelto) < int(importe)
        ):

            log_event(
                "refund_partial_ignored",
                category="payment",
                severity="info",
                message="Devolución parcial: no se retira el acceso.",
                metadata={
                    "payment_intent": str(payment_intent or "")[:64],
                    "amount": importe,
                    "amount_refunded": devuelto
                }
            )

            return "OK"


        process_refund(
            external_payment_id=payment_intent,
            reason=REFUND_REASON_REFUND,
            refunded_amount=devuelto
        )

        return "OK"


    if event["type"] in (
        "charge.dispute.created",
        "charge.dispute.closed"
    ):

        disputa = event["data"]["object"]

        # Si la disputa se cierra a tu favor, no hay nada que retirar.
        if (
            event["type"] == "charge.dispute.closed"
            and disputa.get("status") == "won"
        ):

            log_event(
                "dispute_won_no_action",
                category="payment",
                severity="info",
                message="Disputa ganada: el acceso se mantiene.",
                metadata={"dispute_id": str(disputa.get("id") or "")[:64]}
            )

            return "OK"


        process_refund(
            external_payment_id=disputa.get("payment_intent"),
            reason=REFUND_REASON_DISPUTE,
            refunded_amount=disputa.get("amount")
        )

        return "OK"


    # =========================
    # EL PAGO QUE CONFIRMA DESPUÉS
    # =========================
    # No todos los métodos confirman en el acto. Con Bancontact o iDEAL, Stripe
    # manda «completed» con la sesión SIN pagar —y ahí no se concede nada, que
    # para eso está la comprobación de más abajo— y horas después manda
    # «async_payment_succeeded» con el dinero ya dentro. Ese segundo evento
    # entra por la MISMA puerta: el acceso se concede igual, con el mismo
    # camino, la misma idempotencia y el mismo aviso.
    if event["type"] == "checkout.session.async_payment_failed":

        sesion_fallida = event["data"]["object"]
        metadata_fallida = sesion_fallida.get("metadata") or {}

        try:

            comprador = int(metadata_fallida.get("telegram_id") or 0)

        except (TypeError, ValueError):

            comprador = 0

        log_event(
            "checkout_async_payment_failed",
            category="payment",
            severity="warning",
            scope="global",
            actor_user_id=comprador or None,
            target_user_id=comprador or None,
            message="El pago diferido de una sesión no llegó a confirmarse.",
            metadata={
                "session": sesion_fallida.get("id"),
                "group_id": metadata_fallida.get("group_id"),
            },
        )

        # Se le dice. Quedarse callado deja a alguien esperando un acceso que
        # no va a llegar, convencido de que ha pagado.
        if comprador and TOKEN:

            try:

                send_telegram_message(
                    TOKEN,
                    comprador,
                    "❌ Tu pago no se ha completado\n\n"
                    "El banco no lo ha confirmado, así que no se te ha cobrado "
                    "nada y no se ha activado ningún acceso.\n\n"
                    "Puedes volver a intentarlo cuando quieras."
                )

            except Exception as e:

                print("No se pudo avisar del pago diferido fallido:", str(e)[:160])

        return "OK"


    if event["type"] in (
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    ):

        session = event["data"]["object"]
        metadata = session.get("metadata") or {}

        if metadata.get("purpose") == "owner_addon":

            process_owner_addon_checkout_completed(session)
            return "OK"

        if metadata.get("purpose") == "platform_plan":

            process_platform_plan_checkout_completed(session)
            return "OK"

        user_id = int(
            session["metadata"]["telegram_id"]
        )
        stripe_session_id = session.get("id")
        stripe_payment_id = session.get("payment_intent") or stripe_session_id
        amount_total = session.get("amount_total")
        currency = (session.get("currency") or "").upper() or None


        # =========================
        # ¿ESTÁ PAGADO DE VERDAD?
        # =========================
        # «checkout.session.completed» NO significa «pagado». Significa que el
        # comprador terminó el formulario. Con tarjeta las dos cosas coinciden
        # casi siempre —por eso esto nunca se notó—, pero la cuenta de Stripe de
        # este bot tiene activos Klarna, Link, Bancontact, Revolut Pay y varios
        # más, y algunos confirman el cobro DESPUÉS, en un evento aparte. El día
        # que se ofrezca cualquiera de ellos, esta rama estaría regalando el
        # acceso al terminar el formulario, sin que hubiera entrado un euro.
        #
        # «no_payment_required» sí entra: es lo que contesta Stripe cuando el
        # total queda a cero (un cupón del 100%), y ahí no hay nada que cobrar.
        estado_del_pago = (session.get("payment_status") or "").strip().lower()

        if estado_del_pago and estado_del_pago not in ("paid", "no_payment_required"):

            print(
                "Stripe: sesión terminada SIN pagar (", estado_del_pago,
                ") — no se concede acceso:", stripe_session_id
            )

            log_event(
                "checkout_completed_unpaid",
                category="payment",
                severity="warning",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message=(
                    "Sesión de pago terminada sin pagar: no se concede acceso."
                ),
                metadata={
                    "payment_status": estado_del_pago,
                    "session": stripe_session_id,
                },
            )

            return "OK"


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

                # Se le ha cobrado. Callarse es lo peor de las dos opciones: hay
                # que decírselo y avisar para que le devuelvan el dinero.
                # El grupo aún no se ha resuelto aquí, así que se saca de la
                # metadata de la sesión; puede no venir, y el aviso funciona
                # igual porque lo que importa es el pago y la persona.
                try:

                    banned_group_id = int(metadata.get("group_id"))

                except (TypeError, ValueError):

                    banned_group_id = None


                report_payment_incident(
                    INCIDENT_BANNED_BUYER,
                    user_id,
                    banned_group_id,
                    provider=PAYMENT_PROVIDER_STRIPE,
                    external_payment_id=stripe_payment_id,
                    detail=f"stripe_session_id={stripe_session_id}"
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

            # El número del plan, si el cobro lo mandó. Es la única referencia
            # que no cambia: el precio se puede recrear (cambiar el importe crea
            # uno nuevo), y entonces buscar por precio ya no encuentra el plan
            # que esta persona compró.
            plan_id_metadata = (session.get("metadata") or {}).get("plan_id")

            with conn.cursor() as cur:

                row = None

                if plan_id_metadata:

                    try:

                        cur.execute("""

                            SELECT duration_days, name
                            FROM plans
                            WHERE id = %s AND group_id = %s

                        """, (int(plan_id_metadata), metadata_group_id))

                        row = cur.fetchone()

                    except (TypeError, ValueError):

                        row = None

                if not row:

                    # La misma definición del precio efectivo que usan el
                    # escaparate y el cobro. Antes era COALESCE sin NULLIF, así
                    # que un plan con la columna a cadena vacía no se encontraba
                    # —y no encontrarlo concedía el acceso SIN caducidad—.
                    from plan_price_service import sql_precio_efectivo

                    cur.execute("""

                        SELECT duration_days, name

                        FROM plans

                        WHERE """ + sql_precio_efectivo() + """=%s
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

                # El acceso se concede igual —el dinero ha entrado y dejar sin
                # entrar a quien acaba de pagar es peor que cualquier otra
                # cosa—, pero SIN CADUCIDAD, o sea de por vida. Eso no puede
                # pasar en silencio: quien pagó 360 días se queda para siempre
                # y el propietario pierde todas las renovaciones sin enterarse.
                log_event(
                    "payment_plan_not_found",
                    category="payment",
                    severity="critical",
                    scope="group",
                    group_id=metadata_group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message=(
                        "Pago cobrado sin encontrar su plan: se ha concedido "
                        "acceso SIN caducidad."
                    ),
                    metadata={
                        "price_id": price_id,
                        "plan_id_metadata": plan_id_metadata,
                    },
                )

                try:

                    # Nada de importar aquí lo que ya está importado arriba
                    # (TOKEN, ADMIN_ID, send_telegram_message): un import dentro
                    # de la función convierte ese nombre en local para TODA la
                    # función, y sus usos anteriores dejan de existir. El cobro
                    # entero se caía con UnboundLocalError.
                    if ADMIN_ID and TOKEN:

                        send_telegram_message(
                            TOKEN,
                            int(ADMIN_ID),
                            "🚨 Un pago se ha cobrado sin encontrar su plan\n\n"
                            f"Comunidad {metadata_group_id}, precio {price_id}.\n\n"
                            "Se le ha dado acceso PARA SIEMPRE, porque sin plan "
                            "no hay duración que aplicar. Revisa ese plan: "
                            "mientras siga así, cada compra regala acceso de por "
                            "vida."
                        )

                except Exception as e:

                    print("No se pudo avisar del plan no encontrado:", str(e)[:200])

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

                    if (duration_value < 1
                            or duration_value > MAX_PLAN_DURATION_DAYS):

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

                        report_payment_incident(
                            INCIDENT_PLAN_INVALID,
                            user_id,
                            metadata_group_id,
                            provider=PAYMENT_PROVIDER_STRIPE,
                            external_payment_id=stripe_payment_id,
                            detail=f"price_id={price_id} duration_days={duration_value}"
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

                report_payment_incident(
                    INCIDENT_GROUP_MISSING,
                    user_id,
                    group_id,
                    provider=PAYMENT_PROVIDER_STRIPE,
                    external_payment_id=stripe_payment_id,
                    detail=f"stripe_session_id={stripe_session_id}"
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

        # Aquí antes había un "return OK": si el enlace fallaba, se avisaba a los
        # administradores y al cliente NO se le decía nada. Peor aún, el acceso se
        # guarda más abajo, así que quien había pagado se quedaba sin mensaje y
        # sin acceso: en «Mis accesos» no le aparecía nada y el pago parecía
        # perdido.
        #
        # El pago es real y el derecho de acceso también; el enlace solo es la
        # entrega. Así que se sigue adelante: se guarda el acceso y el pago
        # igualmente, y más abajo se le explica lo ocurrido con un botón para
        # pedir el enlace él mismo, que ya funcionará porque el acceso existe.


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


                # guardar nuevo (solo si de verdad hay enlace que guardar)

                if link:

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

            # Se avisaba a los administradores y al comprador no. Y aquí se
            # contesta "OK", así que Stripe no va a reintentar: para él este caso
            # no se arregla solo, al contrario que en los demás proveedores.
            report_payment_incident(
                INCIDENT_STORAGE_FAILED,
                user_id,
                group_id,
                provider=PAYMENT_PROVIDER_STRIPE,
                external_payment_id=stripe_payment_id,
                detail=str(e),
                will_retry=False
            )

            return "OK"


        # El acceso ha quedado guardado: si había una incidencia abierta de un
        # intento anterior, se cierra para no perseguir un problema resuelto.
        resolve_incidents_for(user_id, group_id)


        # Si el checkout era una SUSCRIPCIÓN (renovación automática), anclarla
        # al socio: sin este ancla, ningún evento posterior de Stripe
        # (renovación, fallo de cobro, baja) sería atribuible a esta persona.
        suscripcion_creada = extraer_subscription_id(session.get("subscription"))

        if suscripcion_creada:

            attach_subscription_to_member(
                user_id,
                group_id,
                suscripcion_creada,
                stripe_customer_id=session.get("customer")
            )

            # Si la suscripción arranca en PRUEBA, lo cubierto es la prueba,
            # no la duración entera del plan: la expiración se recorta al fin
            # del trial y el primer invoice.paid real la extiende.
            align_expiration_with_trial(user_id, group_id, suscripcion_creada)


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
        texto_comprador, teclado_comprador = build_buyer_message(
            group_name=group_name,
            plan_name=plan_name,
            amount_total=amount_total,
            currency=currency,
            expiration=expiration,
            expire_seconds=expire_seconds,
            link=link,
            telegram_group_id=telegram_group_id,
            language=load_user_language(user_id)
        )

        user_response = send_telegram_message(
            TOKEN,
            user_id,
            texto_comprador,
            reply_markup=teclado_comprador.to_dict()
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
