import json
import os
import uuid

from decimal import Decimal, ROUND_HALF_UP

import requests

from audit_log_service import log_event
from db import conn
from payment_gateway_config import (
    PAYMENT_PROVIDER_PAYPAL,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_CANCELLED,
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION,
    PURCHASE_TYPE_OWNER_UPGRADE,
    PURCHASE_TYPE_PLATFORM_PRODUCT,
    get_payment_provider_config
)
from payment_service import (
    PaymentProviderUnavailable,
    create_payment_transaction,
    sanitize_payment_metadata
)


PAYPAL_SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
PAYPAL_LIVE_BASE_URL = "https://api-m.paypal.com"
PAYPAL_ALLOWED_PLATFORM_PURCHASE_TYPES = {
    PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION,
    PURCHASE_TYPE_PLATFORM_PRODUCT,
    PURCHASE_TYPE_OWNER_UPGRADE
}


def get_paypal_mode():

    mode = (os.environ.get("PAYPAL_MODE") or "sandbox").strip().lower()


    if mode == "live":

        return "live"


    return "sandbox"


def get_paypal_base_url():

    if get_paypal_mode() == "live":

        return PAYPAL_LIVE_BASE_URL


    return PAYPAL_SANDBOX_BASE_URL


def get_paypal_redirect_url(kind):

    env_name = "PAYPAL_RETURN_URL" if kind == "return" else "PAYPAL_CANCEL_URL"
    configured_url = os.environ.get(env_name)


    if configured_url:

        return configured_url


    server_url = (os.environ.get("SERVER_URL") or "").rstrip("/")


    if server_url:

        suffix = "paypal/return" if kind == "return" else "paypal/cancel"

        return f"{server_url}/{suffix}"


    return "https://t.me/TheStarVipBOT"


def is_paypal_platform_ready():

    config = get_payment_provider_config(PAYMENT_PROVIDER_PAYPAL)

    return config.get("enabled") is True and not config.get("missing_env")


def format_paypal_amount(amount_minor):

    amount = Decimal(int(amount_minor)) / Decimal("100")

    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def paypal_amount_to_minor(value):

    amount = Decimal(str(value)) * Decimal("100")

    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_paypal_access_token():

    client_id = os.environ.get("PAYPAL_CLIENT_ID")
    client_secret = os.environ.get("PAYPAL_CLIENT_SECRET")


    if not client_id or not client_secret:

        raise PaymentProviderUnavailable(
            "PayPal no está configurado."
        )


    response = requests.post(
        f"{get_paypal_base_url()}/v1/oauth2/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=20
    )
    response.raise_for_status()

    data = response.json()
    access_token = data.get("access_token")


    if not access_token:

        raise PaymentProviderUnavailable(
            "PayPal no devolvió token de acceso."
        )


    return access_token


def create_platform_paypal_order(
    user_id,
    amount,
    currency="EUR",
    purchase_type=PURCHASE_TYPE_PLATFORM_PRODUCT,
    platform_product_key=None,
    description=None,
    metadata=None
):

    if not is_paypal_platform_ready():

        raise PaymentProviderUnavailable(
            "PayPal todavía no está disponible."
        )


    if purchase_type not in PAYPAL_ALLOWED_PLATFORM_PURCHASE_TYPES:

        raise ValueError("purchase_type no permitido para PayPal plataforma")


    amount_minor = int(amount)


    if amount_minor < 1:

        raise ValueError("amount debe ser positivo")


    currency_code = (currency or "EUR").upper()
    internal_reference = f"paypal_platform_{uuid.uuid4().hex}"
    safe_metadata = sanitize_payment_metadata(metadata or {})
    safe_metadata.update({
        "source": "paypal_create_order",
        "paypal_mode": get_paypal_mode(),
        "internal_reference": internal_reference
    })

    create_payment_transaction(
        PAYMENT_PROVIDER_PAYPAL,
        status=PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_PLATFORM,
        purchase_type=purchase_type,
        user_id=user_id,
        platform_product_key=platform_product_key,
        amount=amount_minor,
        currency=currency_code,
        idempotency_key=internal_reference,
        metadata=safe_metadata
    )

    access_token = get_paypal_access_token()
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": internal_reference,
            "custom_id": internal_reference,
            "description": description or "Pago de plataforma",
            "amount": {
                "currency_code": currency_code,
                "value": format_paypal_amount(amount_minor)
            }
        }],
        "application_context": {
            "brand_name": "TheStarVipBOT",
            "landing_page": "LOGIN",
            "user_action": "PAY_NOW",
            "return_url": get_paypal_redirect_url("return"),
            "cancel_url": get_paypal_redirect_url("cancel")
        }
    }

    response = requests.post(
        f"{get_paypal_base_url()}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": internal_reference
        },
        json=payload,
        timeout=20
    )
    response.raise_for_status()

    order = response.json()
    order_id = order.get("id")
    approval_url = None


    for link in order.get("links", []):

        if link.get("rel") == "approve":

            approval_url = link.get("href")
            break


    if not order_id or not approval_url:

        raise PaymentProviderUnavailable(
            "PayPal no devolvió una URL de aprobación."
        )


    create_payment_transaction(
        PAYMENT_PROVIDER_PAYPAL,
        status=PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_PLATFORM,
        purchase_type=purchase_type,
        user_id=user_id,
        platform_product_key=platform_product_key,
        amount=amount_minor,
        currency=currency_code,
        external_checkout_id=order_id,
        idempotency_key=internal_reference,
        metadata={
            **safe_metadata,
            "paypal_order_id": order_id
        }
    )

    log_event(
        "paypal_platform_order_created",
        category="payment",
        severity="info",
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Orden PayPal de plataforma creada.",
        metadata={
            "paypal_order_id": order_id,
            "purchase_type": purchase_type,
            "platform_product_key": platform_product_key,
            "amount": amount_minor,
            "currency": currency_code,
            "paypal_mode": get_paypal_mode()
        }
    )

    return {
        "order_id": order_id,
        "approval_url": approval_url,
        "internal_reference": internal_reference
    }


def fetch_paypal_transaction(order_id=None, internal_reference=None):

    with conn.cursor() as cur:

        if order_id:

            cur.execute("""

                SELECT id,
                       provider,
                       status,
                       payment_scope,
                       purchase_type,
                       user_id,
                       owner_user_id,
                       group_id,
                       platform_product_key,
                       amount,
                       currency,
                       external_payment_id,
                       external_checkout_id,
                       idempotency_key,
                       metadata_json
                FROM payment_transactions
                WHERE provider=%s
                AND external_checkout_id=%s
                LIMIT 1

            """, (
                PAYMENT_PROVIDER_PAYPAL,
                order_id
            ))

            row = cur.fetchone()


            if row:

                return row_to_paypal_transaction(row)


        if internal_reference:

            cur.execute("""

                SELECT id,
                       provider,
                       status,
                       payment_scope,
                       purchase_type,
                       user_id,
                       owner_user_id,
                       group_id,
                       platform_product_key,
                       amount,
                       currency,
                       external_payment_id,
                       external_checkout_id,
                       idempotency_key,
                       metadata_json
                FROM payment_transactions
                WHERE provider=%s
                AND idempotency_key=%s
                LIMIT 1

            """, (
                PAYMENT_PROVIDER_PAYPAL,
                internal_reference
            ))

            row = cur.fetchone()


            if row:

                return row_to_paypal_transaction(row)


    return None


def row_to_paypal_transaction(row):

    metadata_json = row[14] or {}


    if isinstance(metadata_json, str):

        try:

            metadata_json = json.loads(metadata_json)

        except Exception:

            metadata_json = {}


    return {
        "id": row[0],
        "provider": row[1],
        "status": row[2],
        "payment_scope": row[3],
        "purchase_type": row[4],
        "user_id": row[5],
        "owner_user_id": row[6],
        "group_id": row[7],
        "platform_product_key": row[8],
        "amount": row[9],
        "currency": row[10],
        "external_payment_id": row[11],
        "external_checkout_id": row[12],
        "idempotency_key": row[13],
        "metadata_json": metadata_json
    }


def update_paypal_transaction_status(transaction_id, status, external_payment_id=None, metadata=None):

    safe_metadata = sanitize_payment_metadata(metadata or {})

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE payment_transactions
            SET status=%s,
                external_payment_id=COALESCE(%s, external_payment_id),
                metadata_json=COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                metadata=COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s

        """, (
            status,
            external_payment_id,
            json.dumps(safe_metadata),
            json.dumps(safe_metadata),
            transaction_id
        ))

    conn.commit()


def verify_paypal_webhook(headers, event_body):

    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID")


    if not webhook_id:

        return False


    access_token = get_paypal_access_token()
    verification_payload = {
        "auth_algo": headers.get("PAYPAL-AUTH-ALGO"),
        "cert_url": headers.get("PAYPAL-CERT-URL"),
        "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": webhook_id,
        "webhook_event": event_body
    }

    response = requests.post(
        f"{get_paypal_base_url()}/v1/notifications/verify-webhook-signature",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        },
        json=verification_payload,
        timeout=20
    )
    response.raise_for_status()

    result = response.json()

    return result.get("verification_status") == "SUCCESS"


def extract_paypal_capture_context(event_body):

    resource = event_body.get("resource") or {}
    event_type = event_body.get("event_type")


    if event_type not in (
        "PAYMENT.CAPTURE.COMPLETED",
        "PAYMENT.CAPTURE.DENIED",
        "PAYMENT.CAPTURE.DECLINED"
    ):

        return None


    amount = resource.get("amount") or {}
    related_ids = (
        resource.get("supplementary_data") or {}
    ).get("related_ids") or {}

    return {
        "capture_id": resource.get("id"),
        "order_id": related_ids.get("order_id"),
        "internal_reference": resource.get("custom_id"),
        "status": resource.get("status"),
        "amount": paypal_amount_to_minor(amount.get("value") or "0"),
        "currency": (amount.get("currency_code") or "").upper(),
        "event_type": event_type,
        "event_id": event_body.get("id")
    }


def get_paypal_status_from_event(event_type):

    if event_type == "PAYMENT.CAPTURE.COMPLETED":

        return PAYMENT_STATUS_PAID


    if event_type in (
        "PAYMENT.CAPTURE.DENIED",
        "PAYMENT.CAPTURE.DECLINED"
    ):

        return PAYMENT_STATUS_FAILED


    return None


def process_paypal_webhook(event_body, headers):

    if not verify_paypal_webhook(headers, event_body):

        log_event(
            "paypal_webhook_verification_failed",
            category="payment",
            severity="warning",
            message="Webhook PayPal rechazado por firma no válida.",
            metadata={
                "event_type": event_body.get("event_type"),
                "event_id": event_body.get("id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Invalid webhook signature"
        }


    capture_context = extract_paypal_capture_context(event_body)


    if not capture_context:

        return {
            "ok": True,
            "status_code": 200,
            "message": "Ignored PayPal event"
        }


    transaction = fetch_paypal_transaction(
        order_id=capture_context.get("order_id"),
        internal_reference=capture_context.get("internal_reference")
    )


    if not transaction:

        log_event(
            "paypal_transaction_not_found",
            category="payment",
            severity="warning",
            message="Webhook PayPal recibido sin transacción interna asociada.",
            metadata=capture_context
        )

        return {
            "ok": False,
            "status_code": 404,
            "message": "Transaction not found"
        }


    if transaction.get("status") == PAYMENT_STATUS_PAID:

        return {
            "ok": True,
            "status_code": 200,
            "message": "Already processed"
        }


    if transaction.get("payment_scope") != PAYMENT_SCOPE_PLATFORM:

        log_event(
            "paypal_scope_mismatch",
            category="payment",
            severity="error",
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Webhook PayPal intentó confirmar una transacción no platform.",
            metadata={
                "transaction_id": transaction.get("id"),
                "payment_scope": transaction.get("payment_scope"),
                "event_id": capture_context.get("event_id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Invalid payment scope"
        }


    if transaction.get("purchase_type") not in PAYPAL_ALLOWED_PLATFORM_PURCHASE_TYPES:

        return {
            "ok": False,
            "status_code": 400,
            "message": "Invalid purchase type"
        }


    expected_amount = int(transaction.get("amount") or 0)
    expected_currency = (transaction.get("currency") or "").upper()


    if expected_amount != capture_context.get("amount") or expected_currency != capture_context.get("currency"):

        log_event(
            "paypal_amount_mismatch",
            category="payment",
            severity="error",
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Webhook PayPal rechazado por importe o moneda no coincidente.",
            metadata={
                "transaction_id": transaction.get("id"),
                "expected_amount": expected_amount,
                "received_amount": capture_context.get("amount"),
                "expected_currency": expected_currency,
                "received_currency": capture_context.get("currency"),
                "event_id": capture_context.get("event_id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Amount mismatch"
        }


    new_status = get_paypal_status_from_event(
        capture_context.get("event_type")
    )


    if not new_status:

        return {
            "ok": True,
            "status_code": 200,
            "message": "Ignored PayPal event"
        }


    activation_status = "paid_pending_platform_fulfillment"

    if new_status != PAYMENT_STATUS_PAID:

        activation_status = "payment_failed_no_fulfillment"


    update_paypal_transaction_status(
        transaction.get("id"),
        new_status,
        external_payment_id=capture_context.get("capture_id"),
        metadata={
            "paypal_event_id": capture_context.get("event_id"),
            "paypal_order_id": capture_context.get("order_id"),
            "paypal_capture_id": capture_context.get("capture_id"),
            "paypal_mode": get_paypal_mode(),
            "activation_status": activation_status
        }
    )

    event_type = "paypal_platform_payment_confirmed"

    if new_status != PAYMENT_STATUS_PAID:

        event_type = "paypal_platform_payment_failed"


    log_event(
        event_type,
        category="payment",
        severity="info" if new_status == PAYMENT_STATUS_PAID else "warning",
        actor_user_id=transaction.get("user_id"),
        target_user_id=transaction.get("user_id"),
        message="Pago PayPal de plataforma procesado por webhook verificado.",
        metadata={
            "transaction_id": transaction.get("id"),
            "purchase_type": transaction.get("purchase_type"),
            "platform_product_key": transaction.get("platform_product_key"),
            "paypal_order_id": capture_context.get("order_id"),
            "paypal_capture_id": capture_context.get("capture_id"),
            "paypal_event_type": capture_context.get("event_type"),
            "payment_status": new_status,
            "amount": expected_amount,
            "currency": expected_currency
        }
    )

    return {
        "ok": True,
        "status_code": 200,
        "message": "PayPal payment processed"
    }


def capture_paypal_order(order_id):

    access_token = get_paypal_access_token()
    response = requests.post(
        f"{get_paypal_base_url()}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": f"capture_{order_id}"
        },
        timeout=20
    )
    response.raise_for_status()

    capture = response.json()
    transaction = fetch_paypal_transaction(order_id=order_id)


    if transaction:

        update_paypal_transaction_status(
            transaction.get("id"),
            transaction.get("status") or PAYMENT_STATUS_PENDING,
            metadata={
                "paypal_capture_return_status": capture.get("status"),
                "paypal_order_id": order_id,
                "activation_status": "waiting_verified_webhook"
            }
        )

    return capture


def cancel_paypal_order(order_id):

    transaction = fetch_paypal_transaction(order_id=order_id)


    if transaction and transaction.get("status") == PAYMENT_STATUS_PENDING:

        update_paypal_transaction_status(
            transaction.get("id"),
            PAYMENT_STATUS_CANCELLED,
            metadata={
                "paypal_order_id": order_id,
                "cancelled_from": "paypal_cancel_return"
            }
        )

    return transaction
