import json
import os
import uuid

from decimal import Decimal, ROUND_HALF_UP

import requests

from audit_log_service import log_event
from db import conn
from payment_gateway_config import (
    amount_to_minor_units,
    PAYMENT_PROVIDER_PAYPAL,
    PAYMENT_SCOPE_GROUP,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_CANCELLED,
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    PROVIDER_CONFIG_SCOPE_GROUP,
    PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION,
    PURCHASE_TYPE_GROUP_ACCESS,
    PURCHASE_TYPE_OWNER_UPGRADE,
    PURCHASE_TYPE_PLATFORM_PRODUCT,
    get_payment_provider_config
)
from payment_access_service import grant_group_access_after_payment
from payment_secret_store import decrypt_provider_config
from payment_service import (
    PaymentProviderUnavailable,
    create_payment_transaction,
    fetch_group_payment_provider_config,
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

    return get_paypal_base_url_for_mode(
        get_paypal_mode()
    )


def get_paypal_base_url_for_mode(mode):

    if mode == "live":

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


def get_paypal_access_token_for_credentials(client_id, client_secret, mode="sandbox"):

    if not client_id or not client_secret:

        raise PaymentProviderUnavailable(
            "PayPal del grupo no tiene credenciales completas."
        )


    response = requests.post(
        f"{get_paypal_base_url_for_mode(mode)}/v1/oauth2/token",
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
            "PayPal no devolvió token de acceso para este grupo."
        )


    return access_token


def get_group_paypal_credentials(group_id):

    config_row = fetch_group_payment_provider_config(
        group_id,
        PAYMENT_PROVIDER_PAYPAL
    )


    if not config_row:

        raise PaymentProviderUnavailable(
            "PayPal no está configurado para esta comunidad."
        )


    if config_row.get("is_enabled") is not True:

        raise PaymentProviderUnavailable(
            "PayPal no está activo para esta comunidad."
        )


    encrypted_config = config_row.get("encrypted_config_json")


    if not encrypted_config:

        raise PaymentProviderUnavailable(
            "PayPal no tiene credenciales cifradas para esta comunidad."
        )


    decrypted = decrypt_provider_config(encrypted_config)
    mode = (decrypted.get("mode") or "sandbox").strip().lower()


    if mode != "live":

        mode = "sandbox"


    credentials = {
        "provider_config_id": config_row.get("id"),
        "owner_user_id": config_row.get("owner_user_id"),
        "group_id": group_id,
        "mode": mode,
        "client_id": decrypted.get("client_id"),
        "client_secret": decrypted.get("client_secret"),
        "webhook_id": decrypted.get("webhook_id"),
        "status": config_row.get("status")
    }


    if not credentials.get("client_id") or not credentials.get("client_secret"):

        raise PaymentProviderUnavailable(
            "PayPal del grupo no tiene client_id/client_secret completos."
        )


    if not credentials.get("webhook_id"):

        raise PaymentProviderUnavailable(
            "PayPal del grupo necesita webhook_id para activar checkout real."
        )


    return credentials


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
            "approval_url": approval_url,
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


def fetch_group_paypal_plan(group_id, plan_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT p.id,
                   p.name,
                   p.amount,
                   p.currency,
                   p.duration_days,
                   p.paypal_plan_id,
                   p.provider_price_id,
                   g.name
            FROM plans p
            JOIN groups g ON g.id=p.group_id
            WHERE p.id=%s
            AND p.group_id=%s
            AND p.is_active=TRUE
            AND COALESCE(NULLIF(p.payment_provider, ''), 'stripe')='paypal'
            AND g.is_active=TRUE
            LIMIT 1

        """, (
            plan_id,
            group_id
        ))

        row = cur.fetchone()


    if not row:

        return None


    return {
        "id": row[0],
        "name": row[1],
        "amount": row[2],
        "currency": row[3],
        "duration_days": row[4],
        "paypal_plan_id": row[5],
        "provider_price_id": row[6],
        "group_name": row[7]
    }


def get_group_paypal_plan_id(plan):

    return (
        plan.get("paypal_plan_id")
        or plan.get("provider_price_id")
    )


def create_group_paypal_order(
    user_id,
    group_id,
    plan_id,
    metadata=None
):

    provider_config = get_payment_provider_config(PAYMENT_PROVIDER_PAYPAL)


    if provider_config.get("enabled") is not True:

        raise PaymentProviderUnavailable(
            "PayPal no está habilitado globalmente."
        )


    plan = fetch_group_paypal_plan(
        group_id,
        plan_id
    )


    if not plan:

        raise ValueError("Plan inválido para esta comunidad.")

    paypal_plan_id = get_group_paypal_plan_id(plan)


    if not paypal_plan_id:

        raise PaymentProviderUnavailable(
            "PayPal para suscripciones todavía no está disponible para este plan."
        )


    # plans.amount está en euros (el propietario teclea 15). El webhook de
    # PayPal manda céntimos, y aquí se guardaba el valor en euros tal cual:
    # la validación comparaba 15 contra 1500 y rechazaba TODOS los pagos de
    # grupo por "amount mismatch". Nadie llegó a recibir acceso por PayPal.
    currency_code = (plan.get("currency") or "EUR").upper()
    amount_minor = amount_to_minor_units(plan.get("amount") or 0, currency_code)


    if amount_minor < 1:

        raise ValueError("El plan no tiene importe válido.")


    credentials = get_group_paypal_credentials(group_id)
    internal_reference = f"paypal_group_{uuid.uuid4().hex}"
    safe_metadata = sanitize_payment_metadata(metadata or {})
    safe_metadata.update({
        "source": "paypal_group_create_subscription",
        "paypal_mode": credentials.get("mode"),
        "internal_reference": internal_reference,
        "provider_config_id": credentials.get("provider_config_id"),
        "paypal_plan_id": paypal_plan_id
    })

    pending_transaction_id = create_payment_transaction(
        PAYMENT_PROVIDER_PAYPAL,
        status=PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_GROUP,
        purchase_type=PURCHASE_TYPE_GROUP_ACCESS,
        user_id=user_id,
        owner_user_id=credentials.get("owner_user_id"),
        group_id=group_id,
        plan_id=plan_id,
        provider_config_id=credentials.get("provider_config_id"),
        provider_config_scope=PROVIDER_CONFIG_SCOPE_GROUP,
        amount=amount_minor,
        currency=currency_code,
        idempotency_key=internal_reference,
        metadata=safe_metadata
    )


    if not pending_transaction_id:

        raise PaymentProviderUnavailable(
            "No se pudo registrar la transacción pendiente PayPal."
        )


    try:

        access_token = get_paypal_access_token_for_credentials(
            credentials.get("client_id"),
            credentials.get("client_secret"),
            credentials.get("mode")
        )
        payload = {
            "plan_id": paypal_plan_id,
            "custom_id": internal_reference,
            "quantity": "1",
            "application_context": {
                "brand_name": "TheStarVipBOT",
                "user_action": "PAY_NOW",
                "return_url": get_paypal_redirect_url("return"),
                "cancel_url": get_paypal_redirect_url("cancel")
            }
        }

        response = requests.post(
            f"{get_paypal_base_url_for_mode(credentials.get('mode'))}/v1/billing/subscriptions",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": internal_reference
            },
            json=payload,
            timeout=20
        )
        response.raise_for_status()

        subscription = response.json()
        subscription_id = subscription.get("id")
        approval_url = None


        for link in subscription.get("links", []):

            if link.get("rel") == "approve":

                approval_url = link.get("href")
                break


        if not subscription_id or not approval_url:

            raise PaymentProviderUnavailable(
                "PayPal no devolvió una URL de aprobación."
            )


        update_paypal_transaction_status(
            pending_transaction_id,
            PAYMENT_STATUS_PENDING,
            external_checkout_id=subscription_id,
            metadata={
                **safe_metadata,
                "approval_url": approval_url,
                "paypal_subscription_id": subscription_id
            }
        )

    except Exception as exc:

        update_paypal_transaction_status(
            pending_transaction_id,
            PAYMENT_STATUS_FAILED,
            metadata={
                **safe_metadata,
                "paypal_checkout_error": str(exc)[:500],
                "activation_status": "subscription_creation_failed"
            }
        )

        log_event(
            "paypal_group_checkout_failed",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="No se pudo crear la suscripción PayPal del grupo.",
            metadata={
                "transaction_id": pending_transaction_id,
                "plan_id": plan_id,
                "paypal_mode": credentials.get("mode"),
                "provider_config_id": credentials.get("provider_config_id"),
                "error": str(exc)[:500]
            }
        )

        raise


    log_event(
        "paypal_group_checkout_created",
        category="payment",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Checkout de suscripción PayPal de grupo creado.",
        metadata={
            "paypal_subscription_id": subscription_id,
            "plan_id": plan_id,
            "amount": amount_minor,
            "currency": currency_code,
            "paypal_mode": credentials.get("mode"),
            "provider_config_id": credentials.get("provider_config_id")
        }
    )

    return {
        "order_id": subscription_id,
        "subscription_id": subscription_id,
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
                       plan_id,
                       platform_product_key,
                       provider_config_id,
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
                       plan_id,
                       platform_product_key,
                       provider_config_id,
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


def fetch_paypal_transaction_by_subscription_id(subscription_id):

    if not subscription_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   provider,
                   status,
                   payment_scope,
                   purchase_type,
                   user_id,
                   owner_user_id,
                   group_id,
                   plan_id,
                   platform_product_key,
                   provider_config_id,
                   amount,
                   currency,
                   external_payment_id,
                   external_checkout_id,
                   idempotency_key,
                   metadata_json
            FROM payment_transactions
            WHERE provider=%s
            AND (
                external_checkout_id=%s
                OR COALESCE(metadata_json, '{}'::jsonb)->>'paypal_subscription_id'=%s
                OR COALESCE(metadata, '{}'::jsonb)->>'paypal_subscription_id'=%s
            )
            ORDER BY updated_at DESC NULLS LAST, id DESC
            LIMIT 1

        """, (
            PAYMENT_PROVIDER_PAYPAL,
            subscription_id,
            subscription_id,
            subscription_id
        ))

        row = cur.fetchone()


        if row:

            return row_to_paypal_transaction(row)


    return None


def row_to_paypal_transaction(row):

    metadata_json = row[16] or {}


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
        "plan_id": row[8],
        "platform_product_key": row[9],
        "provider_config_id": row[10],
        "amount": row[11],
        "currency": row[12],
        "external_payment_id": row[13],
        "external_checkout_id": row[14],
        "idempotency_key": row[15],
        "metadata_json": metadata_json
    }


def update_paypal_transaction_status(transaction_id, status, external_payment_id=None, external_checkout_id=None, metadata=None):

    safe_metadata = sanitize_payment_metadata(metadata or {})

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE payment_transactions
            SET status=%s,
                external_payment_id=COALESCE(%s, external_payment_id),
                external_checkout_id=COALESCE(%s, external_checkout_id),
                metadata_json=COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                metadata=COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s

        """, (
            status,
            external_payment_id,
            external_checkout_id,
            json.dumps(safe_metadata),
            json.dumps(safe_metadata),
            transaction_id
        ))

    conn.commit()


def verify_paypal_webhook(headers, event_body, transaction=None):

    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID")
    access_token = None
    base_url = get_paypal_base_url()


    if transaction and transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP:

        credentials = get_group_paypal_credentials(
            transaction.get("group_id")
        )
        webhook_id = credentials.get("webhook_id")
        access_token = get_paypal_access_token_for_credentials(
            credentials.get("client_id"),
            credentials.get("client_secret"),
            credentials.get("mode")
        )
        base_url = get_paypal_base_url_for_mode(
            credentials.get("mode")
        )


    if not webhook_id:

        return False


    if not access_token:

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
        f"{base_url}/v1/notifications/verify-webhook-signature",
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

    if event_type == "PAYMENT.SALE.COMPLETED":

        return PAYMENT_STATUS_PAID


    if event_type in (
        "PAYMENT.SALE.DENIED",
        "PAYMENT.SALE.REFUNDED",
        "PAYMENT.SALE.REVERSED"
    ):

        return PAYMENT_STATUS_FAILED


    if event_type == "PAYMENT.CAPTURE.COMPLETED":

        return PAYMENT_STATUS_PAID


    if event_type in (
        "PAYMENT.CAPTURE.DENIED",
        "PAYMENT.CAPTURE.DECLINED"
    ):

        return PAYMENT_STATUS_FAILED


    return None


def extract_paypal_subscription_payment_context(event_body):

    resource = event_body.get("resource") or {}
    event_type = event_body.get("event_type")


    if event_type not in (
        "PAYMENT.SALE.COMPLETED",
        "PAYMENT.SALE.DENIED",
        "PAYMENT.SALE.REFUNDED",
        "PAYMENT.SALE.REVERSED"
    ):

        return None


    amount = resource.get("amount") or {}
    amount_value = amount.get("total") or amount.get("value") or "0"
    currency = amount.get("currency") or amount.get("currency_code") or ""

    return {
        "subscription_id": resource.get("billing_agreement_id"),
        "sale_id": resource.get("id"),
        "status": resource.get("state") or resource.get("status"),
        "amount": paypal_amount_to_minor(amount_value),
        "currency": currency.upper(),
        "event_type": event_type,
        "event_id": event_body.get("id")
    }


def extract_paypal_subscription_lifecycle_context(event_body):

    resource = event_body.get("resource") or {}
    event_type = event_body.get("event_type")


    if event_type not in (
        "BILLING.SUBSCRIPTION.ACTIVATED",
        "BILLING.SUBSCRIPTION.CANCELLED",
        "BILLING.SUBSCRIPTION.SUSPENDED",
        "BILLING.SUBSCRIPTION.EXPIRED",
        "BILLING.SUBSCRIPTION.PAYMENT.FAILED"
    ):

        return None


    return {
        "subscription_id": resource.get("id"),
        "status": resource.get("status"),
        "event_type": event_type,
        "event_id": event_body.get("id")
    }


def log_paypal_webhook_verified(transaction, event_body):

    log_event(
        "paypal_webhook_verified",
        category="payment",
        severity="info",
        scope="group" if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP else "global",
        group_id=transaction.get("group_id"),
        actor_user_id=transaction.get("user_id"),
        target_user_id=transaction.get("user_id"),
        message="Webhook PayPal verificado correctamente.",
        metadata={
            "transaction_id": transaction.get("id"),
            "payment_scope": transaction.get("payment_scope"),
            "event_type": event_body.get("event_type"),
            "event_id": event_body.get("id")
        }
    )


def log_paypal_webhook_unverified(transaction, event_body):

    log_event(
        "paypal_webhook_unverified",
        category="payment",
        severity="warning",
        scope="group" if transaction and transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP else "global",
        group_id=transaction.get("group_id") if transaction else None,
        actor_user_id=transaction.get("user_id") if transaction else None,
        target_user_id=transaction.get("user_id") if transaction else None,
        message="Webhook PayPal rechazado por firma no válida.",
        metadata={
            "transaction_id": transaction.get("id") if transaction else None,
            "payment_scope": transaction.get("payment_scope") if transaction else None,
            "event_type": event_body.get("event_type"),
            "event_id": event_body.get("id")
        }
    )


def process_paypal_group_subscription_payment(transaction, payment_context):

    if transaction.get("purchase_type") != PURCHASE_TYPE_GROUP_ACCESS:

        return {
            "ok": False,
            "status_code": 400,
            "message": "Invalid group purchase type"
        }


    if (
        transaction.get("status") == PAYMENT_STATUS_PAID
        and transaction.get("external_payment_id") == payment_context.get("sale_id")
    ):

        return {
            "ok": True,
            "status_code": 200,
            "message": "Already processed"
        }


    expected_amount = int(transaction.get("amount") or 0)
    expected_currency = (transaction.get("currency") or "").upper()


    if expected_amount != payment_context.get("amount") or expected_currency != payment_context.get("currency"):

        log_event(
            "paypal_amount_mismatch",
            category="payment",
            severity="error",
            scope="group",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Webhook PayPal de suscripción rechazado por importe o moneda no coincidente.",
            metadata={
                "transaction_id": transaction.get("id"),
                "expected_amount": expected_amount,
                "received_amount": payment_context.get("amount"),
                "expected_currency": expected_currency,
                "received_currency": payment_context.get("currency"),
                "event_id": payment_context.get("event_id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Amount mismatch"
        }


    new_status = get_paypal_status_from_event(
        payment_context.get("event_type")
    )


    if not new_status:

        return {
            "ok": True,
            "status_code": 200,
            "message": "Ignored PayPal event"
        }


    activation_status = "payment_failed_no_access"


    if new_status == PAYMENT_STATUS_PAID:

        grant_result = grant_group_access_after_payment(
            PAYMENT_PROVIDER_PAYPAL,
            transaction.get("user_id"),
            transaction.get("group_id"),
            transaction.get("plan_id"),
            external_payment_id=payment_context.get("sale_id"),
            external_checkout_id=payment_context.get("subscription_id"),
            amount=expected_amount,
            currency=expected_currency,
            transaction_id=transaction.get("id")
        )


        if not grant_result.get("ok"):

            return {
                "ok": False,
                "status_code": 500,
                "message": "Access grant failed"
            }


        activation_status = "access_granted"

        log_event(
            "paypal_group_access_activated",
            category="access",
            severity="info",
            scope="group",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Acceso de grupo activado tras pago PayPal verificado.",
            metadata={
                "transaction_id": transaction.get("id"),
                "plan_id": transaction.get("plan_id"),
                "paypal_subscription_id": payment_context.get("subscription_id"),
                "paypal_sale_id": payment_context.get("sale_id")
            }
        )


    update_paypal_transaction_status(
        transaction.get("id"),
        new_status,
        external_payment_id=payment_context.get("sale_id"),
        metadata={
            "paypal_event_id": payment_context.get("event_id"),
            "paypal_subscription_id": payment_context.get("subscription_id"),
            "paypal_sale_id": payment_context.get("sale_id"),
            "paypal_event_type": payment_context.get("event_type"),
            "activation_status": activation_status
        }
    )

    log_event(
        "paypal_group_payment_completed" if new_status == PAYMENT_STATUS_PAID else "paypal_group_payment_failed",
        category="payment",
        severity="info" if new_status == PAYMENT_STATUS_PAID else "warning",
        scope="group",
        group_id=transaction.get("group_id"),
        actor_user_id=transaction.get("user_id"),
        target_user_id=transaction.get("user_id"),
        message="Pago PayPal de suscripción de grupo procesado por webhook verificado.",
        metadata={
            "transaction_id": transaction.get("id"),
            "plan_id": transaction.get("plan_id"),
            "paypal_subscription_id": payment_context.get("subscription_id"),
            "paypal_sale_id": payment_context.get("sale_id"),
            "paypal_event_type": payment_context.get("event_type"),
            "payment_status": new_status,
            "amount": expected_amount,
            "currency": expected_currency
        }
    )

    return {
        "ok": True,
        "status_code": 200,
        "message": "PayPal group subscription payment processed"
    }


def process_paypal_group_subscription_lifecycle(transaction, lifecycle_context):

    event_type = lifecycle_context.get("event_type")


    if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":

        update_paypal_transaction_status(
            transaction.get("id"),
            PAYMENT_STATUS_PENDING,
            metadata={
                "paypal_event_id": lifecycle_context.get("event_id"),
                "paypal_subscription_id": lifecycle_context.get("subscription_id"),
                "paypal_subscription_status": lifecycle_context.get("status"),
                "activation_status": "subscription_active_waiting_payment"
            }
        )

        log_event(
            "paypal_group_payment_ignored",
            category="payment",
            severity="info",
            scope="group",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Suscripción PayPal activada, esperando confirmación de pago antes de conceder acceso.",
            metadata={
                "transaction_id": transaction.get("id"),
                "plan_id": transaction.get("plan_id"),
                "paypal_subscription_id": lifecycle_context.get("subscription_id"),
                "paypal_event_type": event_type
            }
        )

        return {
            "ok": True,
            "status_code": 200,
            "message": "Subscription activated without access grant"
        }


    status = PAYMENT_STATUS_FAILED
    event_name = "paypal_group_payment_failed"


    if event_type in (
        "BILLING.SUBSCRIPTION.CANCELLED",
        "BILLING.SUBSCRIPTION.EXPIRED"
    ):

        status = PAYMENT_STATUS_CANCELLED
        event_name = "paypal_group_subscription_cancelled"


    if event_type == "BILLING.SUBSCRIPTION.SUSPENDED":

        event_name = "paypal_group_subscription_suspended"


    update_paypal_transaction_status(
        transaction.get("id"),
        status,
        metadata={
            "paypal_event_id": lifecycle_context.get("event_id"),
            "paypal_subscription_id": lifecycle_context.get("subscription_id"),
            "paypal_subscription_status": lifecycle_context.get("status"),
            "paypal_event_type": event_type,
            "activation_status": "subscription_lifecycle_no_new_access"
        }
    )

    log_event(
        event_name,
        category="payment",
        severity="warning",
        scope="group",
        group_id=transaction.get("group_id"),
        actor_user_id=transaction.get("user_id"),
        target_user_id=transaction.get("user_id"),
        message="Evento de ciclo de vida PayPal procesado sin conceder acceso nuevo.",
        metadata={
            "transaction_id": transaction.get("id"),
            "plan_id": transaction.get("plan_id"),
            "paypal_subscription_id": lifecycle_context.get("subscription_id"),
            "paypal_event_type": event_type,
            "payment_status": status
        }
    )

    return {
        "ok": True,
        "status_code": 200,
        "message": "PayPal subscription lifecycle processed"
    }


def process_paypal_webhook(event_body, headers):

    subscription_payment_context = extract_paypal_subscription_payment_context(event_body)
    subscription_lifecycle_context = extract_paypal_subscription_lifecycle_context(event_body)
    subscription_context = subscription_payment_context or subscription_lifecycle_context


    if subscription_context:

        transaction = fetch_paypal_transaction_by_subscription_id(
            subscription_context.get("subscription_id")
        )


        if not transaction:

            log_event(
                "paypal_transaction_not_found",
                category="payment",
                severity="warning",
                message="Webhook PayPal de suscripción recibido sin transacción interna asociada.",
                metadata=subscription_context
            )

            return {
                "ok": False,
                "status_code": 404,
                "message": "Transaction not found"
            }


        if not verify_paypal_webhook(headers, event_body, transaction=transaction):

            log_paypal_webhook_unverified(transaction, event_body)

            return {
                "ok": False,
                "status_code": 400,
                "message": "Invalid webhook signature"
            }


        log_paypal_webhook_verified(transaction, event_body)


        if transaction.get("payment_scope") != PAYMENT_SCOPE_GROUP:

            log_event(
                "paypal_group_payment_ignored",
                category="payment",
                severity="warning",
                actor_user_id=transaction.get("user_id"),
                target_user_id=transaction.get("user_id"),
                message="Webhook PayPal de suscripción ignorado por scope no group.",
                metadata={
                    "transaction_id": transaction.get("id"),
                    "payment_scope": transaction.get("payment_scope"),
                    "event_id": subscription_context.get("event_id")
                }
            )

            return {
                "ok": True,
                "status_code": 200,
                "message": "Ignored non-group PayPal subscription event"
            }


        if subscription_payment_context:

            return process_paypal_group_subscription_payment(
                transaction,
                subscription_payment_context
            )


        return process_paypal_group_subscription_lifecycle(
            transaction,
            subscription_lifecycle_context
        )


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


    if not verify_paypal_webhook(headers, event_body, transaction=transaction):

        log_paypal_webhook_unverified(transaction, event_body)

        log_event(
            "paypal_webhook_verification_failed",
            category="payment",
            severity="warning",
            scope="group" if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP else "global",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Webhook PayPal rechazado por firma no válida.",
            metadata={
                "transaction_id": transaction.get("id"),
                "payment_scope": transaction.get("payment_scope"),
                "event_type": event_body.get("event_type"),
                "event_id": event_body.get("id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Invalid webhook signature"
        }


    log_paypal_webhook_verified(transaction, event_body)


    if transaction.get("status") == PAYMENT_STATUS_PAID:

        return {
            "ok": True,
            "status_code": 200,
            "message": "Already processed"
        }


    if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP:

        if transaction.get("purchase_type") != PURCHASE_TYPE_GROUP_ACCESS:

            return {
                "ok": False,
                "status_code": 400,
                "message": "Invalid group purchase type"
            }


        expected_amount = int(transaction.get("amount") or 0)
        expected_currency = (transaction.get("currency") or "").upper()


        if expected_amount != capture_context.get("amount") or expected_currency != capture_context.get("currency"):

            log_event(
                "paypal_amount_mismatch",
                category="payment",
                severity="error",
                scope="group",
                group_id=transaction.get("group_id"),
                actor_user_id=transaction.get("user_id"),
                target_user_id=transaction.get("user_id"),
                message="Webhook PayPal de grupo rechazado por importe o moneda no coincidente.",
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


        activation_status = "payment_failed_no_access"


        if new_status == PAYMENT_STATUS_PAID:

            grant_result = grant_group_access_after_payment(
                PAYMENT_PROVIDER_PAYPAL,
                transaction.get("user_id"),
                transaction.get("group_id"),
                transaction.get("plan_id"),
                external_payment_id=capture_context.get("capture_id"),
                external_checkout_id=capture_context.get("order_id"),
                amount=expected_amount,
                currency=expected_currency,
                transaction_id=transaction.get("id")
            )


            if not grant_result.get("ok"):

                return {
                    "ok": False,
                    "status_code": 500,
                    "message": "Access grant failed"
                }


            activation_status = "access_granted"


        update_paypal_transaction_status(
            transaction.get("id"),
            new_status,
            external_payment_id=capture_context.get("capture_id"),
            metadata={
                "paypal_event_id": capture_context.get("event_id"),
                "paypal_order_id": capture_context.get("order_id"),
                "paypal_capture_id": capture_context.get("capture_id"),
                "activation_status": activation_status
            }
        )

        log_event(
            "paypal_group_payment_confirmed" if new_status == PAYMENT_STATUS_PAID else "paypal_group_payment_failed",
            category="payment",
            severity="info" if new_status == PAYMENT_STATUS_PAID else "warning",
            scope="group",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Pago PayPal de grupo procesado por webhook verificado.",
            metadata={
                "transaction_id": transaction.get("id"),
                "plan_id": transaction.get("plan_id"),
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
            "message": "PayPal group payment processed"
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

    transaction = fetch_paypal_transaction(order_id=order_id)
    mode = get_paypal_mode()


    if transaction and (transaction.get("metadata_json") or {}).get("paypal_subscription_id"):

        return {
            "ok": True,
            "message": "PayPal subscription return received; waiting for webhook"
        }


    if transaction and transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP:

        credentials = get_group_paypal_credentials(
            transaction.get("group_id")
        )
        access_token = get_paypal_access_token_for_credentials(
            credentials.get("client_id"),
            credentials.get("client_secret"),
            credentials.get("mode")
        )
        mode = credentials.get("mode")

    else:

        access_token = get_paypal_access_token()


    response = requests.post(
        f"{get_paypal_base_url_for_mode(mode)}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": f"capture_{order_id}"
        },
        timeout=20
    )
    response.raise_for_status()

    capture = response.json()


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
