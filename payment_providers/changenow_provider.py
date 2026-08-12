import json
import uuid

import requests

from audit_log_service import log_event
from db import conn
from payment_gateway_config import (
    amount_to_minor_units,
    PAYMENT_PROVIDER_CHANGENOW,
    PAYMENT_SCOPE_GROUP,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_CONFIRMING,
    PAYMENT_STATUS_EXPIRED,
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_MANUAL_REVIEW,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    PAYMENT_STATUS_REFUNDED,
    PURCHASE_TYPE_GROUP_ACCESS,
    PURCHASE_TYPE_PLATFORM_PRODUCT
)
from payment_secret_store import decrypt_provider_config, mask_provider_config, mask_secret_value
from payment_service import (
    PaymentProviderUnavailable,
    create_payment_transaction,
    fetch_group_payment_provider_config,
    fetch_platform_payment_provider_config
)


CHANGENOW_API_BASE_URL = "https://api.changenow.io"
CHANGENOW_PROVIDER_LABEL = "ChangeNOW.io"
CHANGENOW_FINAL_STATUSES = {"finished"}
CHANGENOW_REVIEW_STATUSES = {"verifying", "hold", "overdue", "sending", "exchanging"}
CHANGENOW_CONFIRMING_STATUSES = {"confirming"}
CHANGENOW_PENDING_STATUSES = {"new", "waiting", "awaiting deposit", "awaiting_deposit"}
CHANGENOW_FAILED_STATUSES = {"failed"}
CHANGENOW_EXPIRED_STATUSES = {"expired"}
CHANGENOW_REFUNDED_STATUSES = {"refunded"}


def mask_wallet(value):

    return mask_secret_value(value)


def normalize_changenow_status(status):

    normalized = str(status or "").strip().lower()

    if normalized in CHANGENOW_FINAL_STATUSES:

        return PAYMENT_STATUS_PAID

    if normalized in CHANGENOW_CONFIRMING_STATUSES:

        return PAYMENT_STATUS_CONFIRMING

    if normalized in CHANGENOW_REVIEW_STATUSES:

        return PAYMENT_STATUS_MANUAL_REVIEW

    if normalized in CHANGENOW_FAILED_STATUSES:

        return PAYMENT_STATUS_FAILED

    if normalized in CHANGENOW_EXPIRED_STATUSES:

        return PAYMENT_STATUS_EXPIRED

    if normalized in CHANGENOW_REFUNDED_STATUSES:

        return PAYMENT_STATUS_REFUNDED

    if normalized in CHANGENOW_PENDING_STATUSES:

        return PAYMENT_STATUS_PENDING

    return PAYMENT_STATUS_MANUAL_REVIEW


def validate_changenow_config(config):

    required = (
        "api_key",
        "payout_currency",
        "payout_network",
        "payout_wallet",
        "payin_currency",
        "payin_network",
        "rate_mode"
    )
    missing = [key for key in required if not config.get(key)]

    if missing:

        return False, f"Faltan datos de ChangeNOW: {', '.join(missing)}"

    return True, None


def build_changenow_masked_summary(config):

    masked = mask_provider_config(config)

    return (
        f"payin={config.get('payin_currency')}/{config.get('payin_network')}; "
        f"payout={config.get('payout_currency')}/{config.get('payout_network')}; "
        f"wallet={mask_wallet(config.get('payout_wallet'))}; "
        f"api_key={masked.get('api_key') or '***'}; "
        f"mode={config.get('rate_mode') or 'fixed'}; "
        "manual_review=on"
    )


def fetch_group_plan(group_id, plan_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT p.id,
                   p.name,
                   p.amount,
                   p.currency,
                   p.group_id,
                   g.name,
                   g.telegram_group_id
            FROM plans p
            JOIN groups g ON g.id=p.group_id
            WHERE p.id=%s
            AND p.group_id=%s
            AND p.is_active=TRUE
            AND COALESCE(NULLIF(p.payment_provider, ''), 'stripe')='changenow'
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
        "plan_id": row[0],
        "plan_name": row[1],
        "amount": row[2],
        "currency": row[3],
        "group_id": row[4],
        "group_name": row[5],
        "telegram_group_id": row[6]
    }


def get_platform_changenow_config():

    config_row = fetch_platform_payment_provider_config(PAYMENT_PROVIDER_CHANGENOW)

    if not config_row or not config_row.get("encrypted_config_json"):

        raise PaymentProviderUnavailable("ChangeNOW plataforma no está configurado.")

    config = decrypt_provider_config(config_row.get("encrypted_config_json"))
    is_valid, error = validate_changenow_config(config)

    if not is_valid:

        raise PaymentProviderUnavailable(error)

    if config_row.get("is_enabled") is not True:

        raise PaymentProviderUnavailable("ChangeNOW plataforma está desactivado.")

    return config_row, config


def get_group_changenow_config(group_id):

    config_row = fetch_group_payment_provider_config(group_id, PAYMENT_PROVIDER_CHANGENOW)

    if not config_row or not config_row.get("encrypted_config_json"):

        raise PaymentProviderUnavailable("ChangeNOW no está configurado para esta comunidad.")

    config = decrypt_provider_config(config_row.get("encrypted_config_json"))
    is_valid, error = validate_changenow_config(config)

    if not is_valid:

        raise PaymentProviderUnavailable(error)

    if config_row.get("is_enabled") is not True:

        raise PaymentProviderUnavailable("ChangeNOW está desactivado para esta comunidad.")

    return config_row, config


def create_changenow_exchange(config, amount_value, internal_reference, contact_email=None):

    api_key = config.get("api_key")

    if not api_key:

        raise PaymentProviderUnavailable("ChangeNOW necesita API key configurada.")

    payload = {
        "fromCurrency": config.get("payin_currency"),
        "toCurrency": config.get("payout_currency"),
        "fromNetwork": config.get("payin_network"),
        "toNetwork": config.get("payout_network"),
        "fromAmount": str(amount_value or ""),
        "toAmount": "",
        "address": config.get("payout_wallet"),
        "extraId": config.get("payout_extra_id") or "",
        "refundAddress": config.get("refund_address") or "",
        "refundExtraId": config.get("refund_extra_id") or "",
        "userId": str(internal_reference),
        "payload": str(internal_reference),
        "contactEmail": contact_email or config.get("contact_email") or "",
        "source": config.get("source") or "telegram_bot",
        "flow": "standard",
        "type": "direct",
        "rateId": config.get("rate_id") or ""
    }

    response = requests.post(
        f"{CHANGENOW_API_BASE_URL}/v2/exchange",
        headers={
            "Content-Type": "application/json",
            "x-changenow-api-key": api_key
        },
        json=payload,
        timeout=20
    )
    response.raise_for_status()

    return response.json()


def create_platform_changenow_order(
    user_id,
    amount=None,
    currency=None,
    purchase_type=PURCHASE_TYPE_PLATFORM_PRODUCT,
    platform_product_key=None,
    description=None,
    metadata=None
):

    config_row, config = get_platform_changenow_config()
    internal_reference = f"changenow_platform_{uuid.uuid4().hex}"
    metadata = metadata or {}
    manual_only = config.get("manual_only", True) is True
    transaction_id = create_payment_transaction(
        PAYMENT_PROVIDER_CHANGENOW,
        status=PAYMENT_STATUS_MANUAL_REVIEW if manual_only else PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_PLATFORM,
        purchase_type=purchase_type,
        user_id=user_id,
        platform_product_key=platform_product_key,
        amount=amount,
        currency=currency,
        idempotency_key=internal_reference,
        provider_config_id=config_row.get("id"),
        metadata={
            **metadata,
            "source": "create_changenow_platform_order",
            "manual_review_required": True,
            "description": description
        }
    )

    exchange = None

    if not manual_only and amount:

        exchange = create_changenow_exchange(
            config,
            amount,
            internal_reference
        )
        update_changenow_transaction_reference(
            transaction_id,
            exchange.get("id"),
            exchange
        )

    log_event(
        "changenow_platform_payment_created",
        category="payment",
        severity="warning",
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Pago ChangeNOW de plataforma creado en revisión manual.",
        metadata={
            "transaction_id": transaction_id,
            "external_payment_id": exchange.get("id") if exchange else None,
            "manual_review_required": True
        }
    )

    return build_changenow_order_response(transaction_id, config, exchange)


def create_group_changenow_order(user_id, group_id, plan_id, metadata=None):

    plan = fetch_group_plan(group_id, plan_id)

    if not plan:

        raise ValueError("Plan inválido para esta comunidad.")

    config_row, config = get_group_changenow_config(group_id)
    internal_reference = f"changenow_group_{uuid.uuid4().hex}"
    metadata = metadata or {}
    manual_only = config.get("manual_only", True) is True
    transaction_id = create_payment_transaction(
        PAYMENT_PROVIDER_CHANGENOW,
        status=PAYMENT_STATUS_MANUAL_REVIEW if manual_only else PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_GROUP,
        purchase_type=PURCHASE_TYPE_GROUP_ACCESS,
        user_id=user_id,
        owner_user_id=config_row.get("owner_user_id"),
        group_id=group_id,
        plan_id=plan_id,
        # En céntimos, como el resto de transacciones: las pantallas dividen
        # entre 100. Lo que paga el cliente en cripto lo calcula ChangeNOW y
        # sale de su respuesta, no de aquí.
        amount=amount_to_minor_units(
            plan.get("amount") or 0,
            plan.get("currency")
        ),
        currency=plan.get("currency"),
        idempotency_key=internal_reference,
        provider_config_id=config_row.get("id"),
        metadata={
            **metadata,
            "source": "create_changenow_group_order",
            "manual_review_required": True,
            "plan_name": plan.get("plan_name")
        }
    )

    exchange = None

    if not manual_only and config.get("payin_amount"):

        exchange = create_changenow_exchange(
            config,
            config.get("payin_amount"),
            internal_reference
        )
        update_changenow_transaction_reference(
            transaction_id,
            exchange.get("id"),
            exchange
        )

    log_event(
        "changenow_group_payment_created",
        category="payment",
        severity="warning",
        scope="group",
        group_id=group_id,
        telegram_group_id=plan.get("telegram_group_id"),
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Pago ChangeNOW de grupo creado en revisión manual.",
        metadata={
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "external_payment_id": exchange.get("id") if exchange else None,
            "manual_review_required": True
        }
    )

    return build_changenow_order_response(transaction_id, config, exchange, plan=plan)


def update_changenow_transaction_reference(transaction_id, external_payment_id, exchange):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET external_payment_id=%s,
                    external_checkout_id=%s,
                    metadata_json=COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                    metadata=COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s

            """, (
                external_payment_id,
                external_payment_id,
                json.dumps({
                    "changenow_exchange_id": external_payment_id,
                    "changenow_status": exchange.get("status"),
                    "payin_currency": exchange.get("fromCurrency"),
                    "payout_currency": exchange.get("toCurrency"),
                    "valid_until": exchange.get("validUntil")
                }),
                json.dumps({
                    "changenow_exchange_id": external_payment_id,
                    "changenow_status": exchange.get("status"),
                    "payin_currency": exchange.get("fromCurrency"),
                    "payout_currency": exchange.get("toCurrency"),
                    "valid_until": exchange.get("validUntil")
                }),
                transaction_id
            ))

        conn.commit()

    except Exception as e:

        conn.rollback()
        print("Error actualizando referencia ChangeNOW:", e)


def build_changenow_order_response(transaction_id, config, exchange=None, plan=None):

    response = {
        "transaction_id": transaction_id,
        "provider": PAYMENT_PROVIDER_CHANGENOW,
        "status": PAYMENT_STATUS_MANUAL_REVIEW,
        "manual_review": True,
        "payin_currency": config.get("payin_currency"),
        "payin_network": config.get("payin_network"),
        "payout_currency": config.get("payout_currency"),
        "payout_network": config.get("payout_network"),
        "payout_wallet_masked": mask_wallet(config.get("payout_wallet")),
        "rate_mode": config.get("rate_mode") or "fixed",
        "instructions": "Pago cripto en revisión manual. El acceso se activará tras confirmación segura."
    }

    if plan:

        response.update({
            "plan_id": plan.get("plan_id"),
            "plan_name": plan.get("plan_name"),
            "amount": plan.get("amount"),
            "currency": plan.get("currency")
        })

    if exchange:

        response.update({
            "external_payment_id": exchange.get("id"),
            "payin_address": exchange.get("payinAddress"),
            "payin_extra_id": exchange.get("payinExtraId"),
            "expected_amount_from": exchange.get("expectedAmountFrom") or exchange.get("amountFrom"),
            "expected_amount_to": exchange.get("expectedAmountTo") or exchange.get("amountTo"),
            "valid_until": exchange.get("validUntil"),
            "provider_status": exchange.get("status")
        })

    return response


def fetch_changenow_transaction(external_payment_id=None, transaction_id=None):

    try:

        with conn.cursor() as cur:

            if transaction_id:

                cur.execute("""

                    SELECT id,
                           status,
                           payment_scope,
                           user_id,
                           owner_user_id,
                           group_id,
                           plan_id,
                           amount,
                           currency,
                           external_payment_id,
                           provider_config_id,
                           metadata_json
                    FROM payment_transactions
                    WHERE id=%s
                    AND provider=%s
                    LIMIT 1

                """, (
                    transaction_id,
                    PAYMENT_PROVIDER_CHANGENOW
                ))

            else:

                cur.execute("""

                    SELECT id,
                           status,
                           payment_scope,
                           user_id,
                           owner_user_id,
                           group_id,
                           plan_id,
                           amount,
                           currency,
                           external_payment_id,
                           provider_config_id,
                           metadata_json
                    FROM payment_transactions
                    WHERE external_payment_id=%s
                    AND provider=%s
                    LIMIT 1

                """, (
                    external_payment_id,
                    PAYMENT_PROVIDER_CHANGENOW
                ))

            row = cur.fetchone()

    except Exception as e:

        print("Error buscando transacción ChangeNOW:", e)
        return None

    if not row:

        return None

    return {
        "id": row[0],
        "status": row[1],
        "payment_scope": row[2],
        "user_id": row[3],
        "owner_user_id": row[4],
        "group_id": row[5],
        "plan_id": row[6],
        "amount": row[7],
        "currency": row[8],
        "external_payment_id": row[9],
        "provider_config_id": row[10],
        "metadata_json": row[11] or {}
    }


def update_changenow_transaction_status(transaction_id, status, metadata=None):

    metadata = metadata or {}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET status=%s,
                    metadata_json=COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                    metadata=COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s

            """, (
                status,
                json.dumps(metadata),
                json.dumps(metadata),
                transaction_id
            ))

        conn.commit()
        return True

    except Exception as e:

        conn.rollback()
        print("Error actualizando transacción ChangeNOW:", e)
        return False


def process_changenow_webhook(event_body):

    event_body = event_body or {}
    external_payment_id = (
        event_body.get("id")
        or event_body.get("transaction_id")
        or event_body.get("exchange_id")
        or event_body.get("order_id")
    )
    provider_status = event_body.get("status")
    mapped_status = normalize_changenow_status(provider_status)

    transaction = fetch_changenow_transaction(external_payment_id=external_payment_id)

    if not transaction:

        log_event(
            "changenow_webhook_unmatched",
            category="payment",
            severity="warning",
            message="Webhook ChangeNOW recibido sin transacción interna asociada.",
            metadata={
                "external_payment_id": external_payment_id,
                "provider_status": provider_status
            }
        )

        return {
            "status_code": 202,
            "message": "Accepted for manual review"
        }

    next_status = mapped_status

    if mapped_status == PAYMENT_STATUS_PAID:

        next_status = PAYMENT_STATUS_MANUAL_REVIEW

    update_changenow_transaction_status(
        transaction.get("id"),
        next_status,
        metadata={
            "changenow_webhook_status": provider_status,
            "mapped_status": mapped_status,
            "manual_review_required": True
        }
    )

    # Una devolución tiene que retirar el acceso. El estado ya se detectaba pero
    # nadie actuaba: quien devolvía el pago se quedaba dentro del grupo.
    if mapped_status == PAYMENT_STATUS_REFUNDED:

        from refund_service import REFUND_REASON_REFUND, process_refund

        process_refund(
            external_payment_id=external_payment_id,
            reason=REFUND_REASON_REFUND,
            user_id=transaction.get("user_id"),
            group_id=transaction.get("group_id")
        )

    log_event(
        "changenow_webhook_received",
        category="payment",
        severity="warning" if mapped_status == PAYMENT_STATUS_PAID else "info",
        scope=transaction.get("payment_scope") or "global",
        group_id=transaction.get("group_id"),
        actor_user_id=transaction.get("user_id"),
        target_user_id=transaction.get("user_id"),
        message="Webhook ChangeNOW recibido. Pago queda en revisión manual.",
        metadata={
            "transaction_id": transaction.get("id"),
            "external_payment_id": external_payment_id,
            "provider_status": provider_status,
            "mapped_status": mapped_status,
            "stored_status": next_status
        }
    )

    return {
        "status_code": 200,
        "message": "OK"
    }
