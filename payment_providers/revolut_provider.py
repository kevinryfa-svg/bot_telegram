import hashlib
import hmac
import json
import os
import time
import uuid

from decimal import Decimal, ROUND_HALF_UP

import requests

from audit_log_service import log_event
from db import conn
from payment_access_service import grant_group_access_after_payment
from payment_gateway_config import (
    PAYMENT_PROVIDER_REVOLUT,
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
from payment_secret_store import decrypt_provider_config
from payment_service import (
    PaymentProviderUnavailable,
    create_payment_transaction,
    fetch_group_payment_provider_config,
    sanitize_payment_metadata
)


REVOLUT_SANDBOX_BASE_URL = "https://sandbox-merchant.revolut.com"
REVOLUT_LIVE_BASE_URL = "https://merchant.revolut.com"
REVOLUT_DEFAULT_API_VERSION = "2024-09-01"
REVOLUT_ALLOWED_PLATFORM_PURCHASE_TYPES = {
    PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION,
    PURCHASE_TYPE_PLATFORM_PRODUCT,
    PURCHASE_TYPE_OWNER_UPGRADE,
    PURCHASE_TYPE_GROUP_ACCESS
}


def get_revolut_mode():

    mode = (os.environ.get("REVOLUT_MODE") or "sandbox").strip().lower()


    if mode == "live":

        return "live"


    return "sandbox"


def get_revolut_base_url():

    configured_url = os.environ.get("REVOLUT_BASE_URL")


    if configured_url:

        return configured_url.rstrip("/")


    if get_revolut_mode() == "live":

        return REVOLUT_LIVE_BASE_URL


    return REVOLUT_SANDBOX_BASE_URL


def get_revolut_base_url_for_config(config):

    configured_url = config.get("base_url")


    if configured_url:

        return configured_url.rstrip("/")


    if config.get("mode") == "live":

        return REVOLUT_LIVE_BASE_URL


    return REVOLUT_SANDBOX_BASE_URL


def get_revolut_api_version():

    return (
        os.environ.get("REVOLUT_API_VERSION")
        or REVOLUT_DEFAULT_API_VERSION
    )


def get_revolut_redirect_url(kind):

    env_name = "REVOLUT_RETURN_URL" if kind == "return" else "REVOLUT_CANCEL_URL"
    configured_url = os.environ.get(env_name)


    if configured_url:

        return configured_url


    server_url = (os.environ.get("SERVER_URL") or "").rstrip("/")


    if server_url:

        suffix = "revolut/return" if kind == "return" else "revolut/cancel"

        return f"{server_url}/{suffix}"


    return "https://t.me/TheStarVipBOT"


def is_revolut_platform_ready():

    config = get_payment_provider_config(PAYMENT_PROVIDER_REVOLUT)

    return config.get("enabled") is True and not config.get("missing_env")


def get_revolut_headers(idempotency_key=None):

    api_key = os.environ.get("REVOLUT_API_KEY")


    if not api_key:

        raise PaymentProviderUnavailable(
            "Revolut no está configurado."
        )


    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Revolut-Api-Version": get_revolut_api_version()
    }


    if idempotency_key:

        headers["Idempotency-Key"] = idempotency_key


    return headers


def get_revolut_headers_for_api_key(api_key, idempotency_key=None):

    if not api_key:

        raise PaymentProviderUnavailable(
            "Revolut del grupo no tiene API key completa."
        )


    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Revolut-Api-Version": get_revolut_api_version()
    }


    if idempotency_key:

        headers["Idempotency-Key"] = idempotency_key


    return headers


def revolut_amount_to_minor(value):

    if value is None:

        return None


    try:

        if isinstance(value, int):

            return value


        if isinstance(value, float):

            return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


        value_text = str(value).strip()


        if value_text.isdigit():

            return int(value_text)


        amount = Decimal(value_text) * Decimal("100")

        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    except Exception:

        return None


def get_group_revolut_credentials(group_id):

    config_row = fetch_group_payment_provider_config(
        group_id,
        PAYMENT_PROVIDER_REVOLUT
    )


    if not config_row:

        raise PaymentProviderUnavailable(
            "Revolut no está configurado para esta comunidad."
        )


    if config_row.get("is_enabled") is not True:

        raise PaymentProviderUnavailable(
            "Revolut no está activo para esta comunidad."
        )


    encrypted_config = config_row.get("encrypted_config_json")


    if not encrypted_config:

        raise PaymentProviderUnavailable(
            "Revolut no tiene credenciales cifradas para esta comunidad."
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
        "api_key": decrypted.get("api_key"),
        "webhook_secret": decrypted.get("webhook_secret"),
        "base_url": decrypted.get("base_url"),
        "status": config_row.get("status")
    }


    if not credentials.get("api_key") or not credentials.get("webhook_secret"):

        raise PaymentProviderUnavailable(
            "Revolut del grupo necesita API key y webhook secret completos."
        )


    return credentials


def fetch_revolut_group_plan(group_id, plan_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT p.id,
                   p.name,
                   p.amount,
                   p.currency,
                   g.name
            FROM plans p
            JOIN groups g ON g.id=p.group_id
            WHERE p.id=%s
            AND p.group_id=%s
            AND p.is_active=TRUE
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
        "group_name": row[4]
    }


def create_platform_revolut_order(
    user_id,
    amount,
    currency="EUR",
    purchase_type=PURCHASE_TYPE_PLATFORM_PRODUCT,
    platform_product_key=None,
    group_id=None,
    plan_id=None,
    description=None,
    metadata=None
):

    if not is_revolut_platform_ready():

        raise PaymentProviderUnavailable(
            "Revolut todavía no está disponible."
        )


    if purchase_type not in REVOLUT_ALLOWED_PLATFORM_PURCHASE_TYPES:

        raise ValueError("purchase_type no permitido para Revolut plataforma")


    if purchase_type == PURCHASE_TYPE_GROUP_ACCESS:

        if not group_id or not plan_id:

            raise ValueError("group_id y plan_id son obligatorios para acceso de grupo")


        plan = fetch_revolut_group_plan(
            group_id,
            plan_id
        )


        if not plan:

            raise ValueError("Plan inválido para esta comunidad.")


        amount = plan.get("amount")
        currency = plan.get("currency") or currency
        description = description or f"Acceso a {plan.get('group_name') or 'comunidad'} · {plan.get('name') or 'Plan'}"


    amount_minor = int(amount)


    if amount_minor < 1:

        raise ValueError("amount debe ser positivo")


    currency_code = (currency or "EUR").upper()
    internal_reference = f"revolut_platform_{uuid.uuid4().hex}"
    safe_metadata = sanitize_payment_metadata(metadata or {})
    safe_metadata.update({
        "source": "revolut_create_order",
        "revolut_mode": get_revolut_mode(),
        "internal_reference": internal_reference
    })

    create_payment_transaction(
        PAYMENT_PROVIDER_REVOLUT,
        status=PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_PLATFORM,
        purchase_type=purchase_type,
        user_id=user_id,
        group_id=group_id,
        plan_id=plan_id,
        platform_product_key=platform_product_key,
        amount=amount_minor,
        currency=currency_code,
        idempotency_key=internal_reference,
        metadata=safe_metadata
    )

    payload = {
        "amount": amount_minor,
        "currency": currency_code,
        "description": description or "Pago de plataforma",
        "redirect_url": get_revolut_redirect_url("return"),
        "merchant_order_ext_ref": internal_reference
    }

    response = requests.post(
        f"{get_revolut_base_url()}/api/orders",
        headers=get_revolut_headers(internal_reference),
        json=payload,
        timeout=20
    )
    response.raise_for_status()

    order = response.json()
    order_id = order.get("id") or order.get("order_id")
    checkout_url = (
        order.get("checkout_url")
        or order.get("checkoutUrl")
        or order.get("payment_url")
        or order.get("public_url")
    )


    if not order_id or not checkout_url:

        raise PaymentProviderUnavailable(
            "Revolut no devolvió una URL de pago."
        )


    create_payment_transaction(
        PAYMENT_PROVIDER_REVOLUT,
        status=PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_PLATFORM,
        purchase_type=purchase_type,
        user_id=user_id,
        group_id=group_id,
        plan_id=plan_id,
        platform_product_key=platform_product_key,
        amount=amount_minor,
        currency=currency_code,
        external_checkout_id=order_id,
        idempotency_key=internal_reference,
        metadata={
            **safe_metadata,
            "revolut_order_id": order_id
        }
    )

    log_event(
        "revolut_platform_order_created",
        category="payment",
        severity="info",
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Orden Revolut de plataforma creada.",
        metadata={
            "revolut_order_id": order_id,
            "purchase_type": purchase_type,
            "platform_product_key": platform_product_key,
            "group_id": group_id,
            "plan_id": plan_id,
            "amount": amount_minor,
            "currency": currency_code,
            "revolut_mode": get_revolut_mode()
        }
    )

    return {
        "order_id": order_id,
        "checkout_url": checkout_url,
        "internal_reference": internal_reference
    }


def create_group_revolut_order(
    user_id,
    group_id,
    plan_id,
    metadata=None
):

    provider_config = get_payment_provider_config(PAYMENT_PROVIDER_REVOLUT)


    if provider_config.get("enabled") is not True:

        raise PaymentProviderUnavailable(
            "Revolut no está habilitado globalmente."
        )


    plan = fetch_revolut_group_plan(
        group_id,
        plan_id
    )


    if not plan:

        raise ValueError("Plan inválido para esta comunidad.")


    amount_minor = int(plan.get("amount") or 0)


    if amount_minor < 1:

        raise ValueError("El plan no tiene importe válido.")


    currency_code = (plan.get("currency") or "EUR").upper()
    credentials = get_group_revolut_credentials(group_id)
    internal_reference = f"revolut_group_{uuid.uuid4().hex}"
    safe_metadata = sanitize_payment_metadata(metadata or {})
    safe_metadata.update({
        "source": "revolut_group_create_order",
        "revolut_mode": credentials.get("mode"),
        "internal_reference": internal_reference,
        "provider_config_id": credentials.get("provider_config_id")
    })

    create_payment_transaction(
        PAYMENT_PROVIDER_REVOLUT,
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

    payload = {
        "amount": amount_minor,
        "currency": currency_code,
        "description": f"Acceso a {plan.get('group_name') or 'comunidad'} · {plan.get('name') or 'Plan'}",
        "redirect_url": get_revolut_redirect_url("return"),
        "merchant_order_ext_ref": internal_reference
    }

    response = requests.post(
        f"{get_revolut_base_url_for_config(credentials)}/api/orders",
        headers=get_revolut_headers_for_api_key(
            credentials.get("api_key"),
            internal_reference
        ),
        json=payload,
        timeout=20
    )
    response.raise_for_status()

    order = response.json()
    order_id = order.get("id") or order.get("order_id")
    checkout_url = (
        order.get("checkout_url")
        or order.get("checkoutUrl")
        or order.get("payment_url")
        or order.get("public_url")
    )


    if not order_id or not checkout_url:

        raise PaymentProviderUnavailable(
            "Revolut no devolvió una URL de pago."
        )


    create_payment_transaction(
        PAYMENT_PROVIDER_REVOLUT,
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
        external_checkout_id=order_id,
        idempotency_key=internal_reference,
        metadata={
            **safe_metadata,
            "revolut_order_id": order_id
        }
    )

    log_event(
        "revolut_group_order_created",
        category="payment",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Orden Revolut de grupo creada.",
        metadata={
            "revolut_order_id": order_id,
            "plan_id": plan_id,
            "amount": amount_minor,
            "currency": currency_code,
            "revolut_mode": credentials.get("mode"),
            "provider_config_id": credentials.get("provider_config_id")
        }
    )

    return {
        "order_id": order_id,
        "checkout_url": checkout_url,
        "internal_reference": internal_reference
    }


def row_to_revolut_transaction(row):

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


def fetch_revolut_transaction(order_id=None, internal_reference=None):

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
                PAYMENT_PROVIDER_REVOLUT,
                order_id
            ))

            row = cur.fetchone()


            if row:

                return row_to_revolut_transaction(row)


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
                PAYMENT_PROVIDER_REVOLUT,
                internal_reference
            ))

            row = cur.fetchone()


            if row:

                return row_to_revolut_transaction(row)


    return None


def update_revolut_transaction_status(transaction_id, status, external_payment_id=None, metadata=None):

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


def parse_revolut_signature(signature_header):

    signatures = []


    for part in (signature_header or "").split(","):

        value = part.strip()


        if not value:

            continue


        if "=" in value:

            key, value = value.split("=", 1)


            if key.strip() != "v1":

                continue


        signatures.append(value.strip())


    return signatures


def normalize_revolut_timestamp(timestamp):

    try:

        value = float(timestamp)


        if value > 9999999999:

            value = value / 1000


        return value

    except Exception:

        return None


def verify_revolut_webhook(headers, raw_body, transaction=None):

    webhook_secret = os.environ.get("REVOLUT_WEBHOOK_SECRET")


    if transaction and transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP:

        credentials = get_group_revolut_credentials(
            transaction.get("group_id")
        )
        webhook_secret = credentials.get("webhook_secret")


    if not webhook_secret:

        return False


    timestamp = (
        headers.get("Revolut-Request-Timestamp")
        or headers.get("revolut-request-timestamp")
    )
    signature_header = (
        headers.get("Revolut-Signature")
        or headers.get("revolut-signature")
    )


    if not timestamp or not signature_header:

        return False


    normalized_timestamp = normalize_revolut_timestamp(timestamp)


    if normalized_timestamp is None:

        return False


    if abs(time.time() - normalized_timestamp) > 300:

        return False


    signed_payload = f"v1.{timestamp}.{raw_body}".encode("utf-8")
    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256
    ).hexdigest()


    for received_signature in parse_revolut_signature(signature_header):

        if hmac.compare_digest(expected_signature, received_signature):

            return True


    return False


def extract_revolut_event_context(event_body):

    data = event_body.get("data") or event_body.get("payload") or {}


    if not isinstance(data, dict):

        data = {}


    merchant_order_data = data.get("merchant_order_data") or event_body.get("merchant_order_data") or {}


    if not isinstance(merchant_order_data, dict):

        merchant_order_data = {}


    amount = (
        data.get("amount")
        or event_body.get("amount")
        or data.get("order_amount")
        or event_body.get("order_amount")
    )
    currency = (
        data.get("currency")
        or event_body.get("currency")
        or data.get("order_currency")
        or event_body.get("order_currency")
    )

    return {
        "event_id": event_body.get("id") or event_body.get("event_id"),
        "event_type": (
            event_body.get("event")
            or event_body.get("type")
            or event_body.get("event_type")
        ),
        "order_id": (
            data.get("order_id")
            or data.get("id")
            or event_body.get("order_id")
            or event_body.get("order_id")
        ),
        "internal_reference": (
            merchant_order_data.get("reference")
            or data.get("merchant_order_ext_ref")
            or event_body.get("merchant_order_ext_ref")
            or data.get("reference")
            or event_body.get("reference")
        ),
        "amount": revolut_amount_to_minor(amount),
        "currency": (currency or "").upper()
    }


def get_revolut_status_from_event(event_type):

    normalized = (event_type or "").upper()


    if normalized in (
        "ORDER_COMPLETED",
        "ORDER_PAID",
        "PAYMENT_COMPLETED"
    ):

        return PAYMENT_STATUS_PAID


    if normalized in (
        "ORDER_CANCELLED",
        "PAYMENT_CANCELLED"
    ):

        return PAYMENT_STATUS_CANCELLED


    if normalized in (
        "ORDER_FAILED",
        "PAYMENT_FAILED"
    ):

        return PAYMENT_STATUS_FAILED


    return None


def process_revolut_webhook(event_body, headers, raw_body):

    event_context = extract_revolut_event_context(event_body)


    if not event_context.get("order_id") and not event_context.get("internal_reference"):

        if not verify_revolut_webhook(headers, raw_body):

            log_event(
                "revolut_webhook_verification_failed",
                category="payment",
                severity="warning",
                message="Webhook Revolut sin transacción rechazado por firma no válida.",
                metadata={
                    "event_id": event_context.get("event_id"),
                    "event_type": event_context.get("event_type")
                }
            )

            return {
                "ok": False,
                "status_code": 400,
                "message": "Invalid webhook signature"
            }


        return {
            "ok": True,
            "status_code": 200,
            "message": "Ignored Revolut event"
        }


    transaction = fetch_revolut_transaction(
        order_id=event_context.get("order_id"),
        internal_reference=event_context.get("internal_reference")
    )


    if not transaction:

        if not verify_revolut_webhook(headers, raw_body):

            log_event(
                "revolut_webhook_verification_failed",
                category="payment",
                severity="warning",
                message="Webhook Revolut sin transacción interna rechazado por firma no válida.",
                metadata={
                    "event_id": event_context.get("event_id"),
                    "event_type": event_context.get("event_type")
                }
            )

            return {
                "ok": False,
                "status_code": 400,
                "message": "Invalid webhook signature"
            }

        log_event(
            "revolut_transaction_not_found",
            category="payment",
            severity="warning",
            message="Webhook Revolut recibido sin transacción interna asociada.",
            metadata=event_context
        )

        return {
            "ok": False,
            "status_code": 404,
            "message": "Transaction not found"
        }


    if not verify_revolut_webhook(headers, raw_body, transaction=transaction):

        log_event(
            "revolut_webhook_verification_failed",
            category="payment",
            severity="warning",
            scope="group" if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP else "global",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Webhook Revolut rechazado por firma no válida.",
            metadata={
                "transaction_id": transaction.get("id"),
                "payment_scope": transaction.get("payment_scope"),
                "event_type": event_context.get("event_type"),
                "event_id": event_context.get("event_id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Invalid webhook signature"
        }


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


    elif transaction.get("payment_scope") != PAYMENT_SCOPE_PLATFORM:

        log_event(
            "revolut_scope_mismatch",
            category="payment",
            severity="error",
            scope="group" if transaction.get("group_id") else "global",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Webhook Revolut intentó confirmar una transacción que no es platform.",
            metadata={
                "transaction_id": transaction.get("id"),
                "payment_scope": transaction.get("payment_scope"),
                "event_id": event_context.get("event_id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Invalid payment scope"
        }


    if (
        transaction.get("payment_scope") == PAYMENT_SCOPE_PLATFORM
        and transaction.get("purchase_type") not in REVOLUT_ALLOWED_PLATFORM_PURCHASE_TYPES
    ):

        return {
            "ok": False,
            "status_code": 400,
            "message": "Invalid purchase type"
        }


    expected_amount = int(transaction.get("amount") or 0)
    expected_currency = (transaction.get("currency") or "").upper()
    received_amount = event_context.get("amount")
    received_currency = event_context.get("currency")


    if received_amount is not None and expected_amount != received_amount:

        log_event(
            "revolut_amount_mismatch",
            category="payment",
            severity="error",
            scope="group" if transaction.get("group_id") else "global",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Webhook Revolut rechazado por importe no coincidente.",
            metadata={
                "transaction_id": transaction.get("id"),
                "expected_amount": expected_amount,
                "received_amount": received_amount,
                "event_id": event_context.get("event_id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Amount mismatch"
        }


    if received_currency and expected_currency != received_currency:

        log_event(
            "revolut_currency_mismatch",
            category="payment",
            severity="error",
            scope="group" if transaction.get("group_id") else "global",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="Webhook Revolut rechazado por moneda no coincidente.",
            metadata={
                "transaction_id": transaction.get("id"),
                "expected_currency": expected_currency,
                "received_currency": received_currency,
                "event_id": event_context.get("event_id")
            }
        )

        return {
            "ok": False,
            "status_code": 400,
            "message": "Currency mismatch"
        }


    new_status = get_revolut_status_from_event(
        event_context.get("event_type")
    )


    if not new_status:

        return {
            "ok": True,
            "status_code": 200,
            "message": "Ignored Revolut event"
        }


    activation_status = "paid_pending_platform_fulfillment"


    if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP:

        activation_status = "payment_failed_no_access"


    if new_status != PAYMENT_STATUS_PAID:

        activation_status = "payment_failed_no_fulfillment"


    if (
        new_status == PAYMENT_STATUS_PAID
        and transaction.get("purchase_type") == PURCHASE_TYPE_GROUP_ACCESS
        and transaction.get("group_id")
        and transaction.get("plan_id")
    ):

        grant_result = grant_group_access_after_payment(
            PAYMENT_PROVIDER_REVOLUT,
            transaction.get("user_id"),
            transaction.get("group_id"),
            transaction.get("plan_id"),
            external_payment_id=event_context.get("event_id") or event_context.get("order_id"),
            external_checkout_id=event_context.get("order_id"),
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


    update_revolut_transaction_status(
        transaction.get("id"),
        new_status,
        external_payment_id=event_context.get("event_id") or event_context.get("order_id"),
        metadata={
            "revolut_event_id": event_context.get("event_id"),
            "revolut_order_id": event_context.get("order_id"),
            "revolut_event_type": event_context.get("event_type"),
            "revolut_mode": get_revolut_mode(),
            "activation_status": activation_status
        }
    )

    if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP:

        event_type = "revolut_group_payment_confirmed"

    else:

        event_type = "revolut_platform_payment_confirmed"


    if new_status != PAYMENT_STATUS_PAID:

        event_type = (
            "revolut_group_payment_failed"
            if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP
            else "revolut_platform_payment_failed"
        )


    log_event(
        event_type,
        category="payment",
        severity="info" if new_status == PAYMENT_STATUS_PAID else "warning",
        scope="group" if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP else "global",
        group_id=transaction.get("group_id"),
        actor_user_id=transaction.get("user_id"),
        target_user_id=transaction.get("user_id"),
        message="Pago Revolut procesado por webhook verificado.",
        metadata={
            "transaction_id": transaction.get("id"),
            "purchase_type": transaction.get("purchase_type"),
            "platform_product_key": transaction.get("platform_product_key"),
            "group_id": transaction.get("group_id"),
            "plan_id": transaction.get("plan_id"),
            "revolut_order_id": event_context.get("order_id"),
            "revolut_event_type": event_context.get("event_type"),
            "payment_status": new_status,
            "amount": expected_amount,
            "currency": expected_currency
        }
    )

    return {
        "ok": True,
        "status_code": 200,
        "message": "Revolut payment processed"
    }
