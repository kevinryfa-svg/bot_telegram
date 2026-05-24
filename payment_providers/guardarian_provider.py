import json
import os
import uuid

import requests

from audit_log_service import log_event
from db import conn
from payment_access_service import grant_group_access_after_payment
from payment_gateway_config import (
    PAYMENT_PROVIDER_GUARDARIAN,
    PAYMENT_SCOPE_GROUP,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_CANCELLED,
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_MANUAL_REVIEW,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    PAYMENT_STATUS_REFUNDED,
    PAYMENT_STATUS_EXPIRED,
    PROVIDER_CONFIG_SCOPE_GROUP,
    PROVIDER_CONFIG_SCOPE_PLATFORM,
    PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION,
    PURCHASE_TYPE_GROUP_ACCESS,
    PURCHASE_TYPE_OWNER_UPGRADE,
    PURCHASE_TYPE_PLATFORM_PRODUCT
)
from payment_secret_store import decrypt_provider_config, mask_provider_config, mask_secret_value
from payment_service import (
    PaymentProviderUnavailable,
    create_payment_transaction,
    fetch_group_payment_provider_config,
    fetch_platform_payment_provider_config,
    sanitize_payment_metadata
)


GUARDARIAN_DEFAULT_BASE_URL = "https://api-payments.guardarian.com"
GUARDARIAN_FINAL_STATUSES = {"finished"}
GUARDARIAN_PENDING_STATUSES = {"new", "waitingfordeposit", "depositreceived", "depositcaptured", "paymentsubmitted", "cryptosent"}
GUARDARIAN_FAILED_STATUSES = {"failed", "depositfailed", "kycfailed"}
GUARDARIAN_CANCELLED_STATUSES = {"canceled", "cancelled"}
GUARDARIAN_EXPIRED_STATUSES = {"expired"}
GUARDARIAN_REFUNDED_STATUSES = {"refunded"}
GUARDARIAN_MANUAL_REVIEW_STATUSES = {"hold", "review", "manualreview", "kycstarted", "kycfinished", "kyc", "aml", "blocked", "unknown"}
GUARDARIAN_ALLOWED_PLATFORM_PURCHASE_TYPES = {
    PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION,
    PURCHASE_TYPE_PLATFORM_PRODUCT,
    PURCHASE_TYPE_OWNER_UPGRADE,
    PURCHASE_TYPE_GROUP_ACCESS
}


def mask_wallet(wallet):

    return mask_secret_value(wallet)


def mask_secret(value):

    return mask_secret_value(value)


def get_guardarian_base_url(config):

    return (
        config.get("base_url")
        or os.environ.get("GUARDARIAN_API_BASE_URL")
        or GUARDARIAN_DEFAULT_BASE_URL
    ).rstrip("/")


def normalize_guardarian_status(status):

    return str(status or "").strip().lower().replace("_", "").replace("-", "")


def map_guardarian_status_to_internal(status):

    normalized = normalize_guardarian_status(status)

    if normalized in GUARDARIAN_FINAL_STATUSES:

        return PAYMENT_STATUS_PAID

    if normalized in GUARDARIAN_PENDING_STATUSES:

        return PAYMENT_STATUS_PENDING

    if normalized in GUARDARIAN_FAILED_STATUSES:

        return PAYMENT_STATUS_FAILED

    if normalized in GUARDARIAN_CANCELLED_STATUSES:

        return PAYMENT_STATUS_CANCELLED

    if normalized in GUARDARIAN_EXPIRED_STATUSES:

        return PAYMENT_STATUS_EXPIRED

    if normalized in GUARDARIAN_REFUNDED_STATUSES:

        return PAYMENT_STATUS_REFUNDED

    return PAYMENT_STATUS_MANUAL_REVIEW


def is_guardarian_finished(status):

    return normalize_guardarian_status(status) in GUARDARIAN_FINAL_STATUSES


def is_guardarian_pending(status):

    return normalize_guardarian_status(status) in GUARDARIAN_PENDING_STATUSES


def is_guardarian_failed(status):

    return normalize_guardarian_status(status) in GUARDARIAN_FAILED_STATUSES | GUARDARIAN_CANCELLED_STATUSES | GUARDARIAN_EXPIRED_STATUSES | GUARDARIAN_REFUNDED_STATUSES


def is_guardarian_manual_review(status):

    normalized = normalize_guardarian_status(status)

    return normalized in GUARDARIAN_MANUAL_REVIEW_STATUSES or not (
        is_guardarian_finished(normalized)
        or is_guardarian_pending(normalized)
        or is_guardarian_failed(normalized)
    )


def validate_guardarian_config(config):

    required = (
        "api_key",
        "payout_wallet",
        "payout_network",
        "fiat_currency",
        "payout_currency"
    )
    missing = [key for key in required if not config.get(key)]

    if missing:

        return False, f"Faltan datos de Guardarian: {', '.join(missing)}"

    if str(config.get("fiat_currency") or "").upper() != "EUR":

        return False, "Guardarian está preparado para pagos EUR en esta fase."

    if str(config.get("payout_currency") or "").upper() != "USDT":

        return False, "Guardarian está preparado para liquidación USDT en esta fase."

    return True, None


def build_guardarian_masked_summary(config):

    masked = mask_provider_config(config)

    return (
        f"fiat={str(config.get('fiat_currency') or 'EUR').upper()}; "
        f"payout=USDT/{config.get('payout_network') or '-'}; "
        f"wallet={mask_wallet(config.get('payout_wallet'))}; "
        f"api_key={masked.get('api_key') or '***'}; "
        "auto=finished_only"
    )


def get_platform_guardarian_config():

    config_row = fetch_platform_payment_provider_config(PAYMENT_PROVIDER_GUARDARIAN)

    if not config_row or not config_row.get("encrypted_config_json"):

        raise PaymentProviderUnavailable("Guardarian plataforma no está configurado.")

    config = decrypt_provider_config(config_row.get("encrypted_config_json"))
    is_valid, error = validate_guardarian_config(config)

    if not is_valid:

        raise PaymentProviderUnavailable(error)

    if config_row.get("is_enabled") is not True:

        raise PaymentProviderUnavailable("Guardarian plataforma está desactivado.")

    return config_row, config


def get_group_guardarian_config(group_id):

    config_row = fetch_group_payment_provider_config(group_id, PAYMENT_PROVIDER_GUARDARIAN)

    if not config_row or not config_row.get("encrypted_config_json"):

        raise PaymentProviderUnavailable("Guardarian no está configurado para esta comunidad.")

    config = decrypt_provider_config(config_row.get("encrypted_config_json"))
    is_valid, error = validate_guardarian_config(config)

    if not is_valid:

        raise PaymentProviderUnavailable(error)

    if config_row.get("is_enabled") is not True:

        raise PaymentProviderUnavailable("Guardarian está desactivado para esta comunidad.")

    return config_row, config


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


def build_guardarian_headers(config):

    api_key = config.get("api_key")

    if not api_key:

        raise PaymentProviderUnavailable("Guardarian necesita API key configurada.")

    return {
        "Content-Type": "application/json",
        "x-api-key": api_key
    }


def create_guardarian_transaction(config, amount_eur, user_id, group_id, plan_id, transaction_id):

    internal_reference = f"bot_tx_{transaction_id}"
    payload = {
        "from_currency": "EUR",
        "from_network": "EUR",
        "from_amount": str(amount_eur),
        "expected_from_amount": str(amount_eur),
        "to_currency": "USDT",
        "to_network": config.get("payout_network"),
        "payout_address": config.get("payout_wallet"),
        "payment_category": config.get("payment_category") or "VISA_MC",
        "deposit_payment_category": config.get("payment_category") or "VISA_MC",
        "external_partner_link_id": internal_reference,
        "redirects_successful": config.get("success_url") or os.environ.get("GUARDARIAN_SUCCESS_URL") or os.environ.get("SERVER_URL") or "https://t.me/TheStarVipBOT",
        "redirects_failed": config.get("failed_url") or os.environ.get("GUARDARIAN_FAILED_URL") or "https://t.me/TheStarVipBOT",
        "redirects_cancelled": config.get("cancel_url") or os.environ.get("GUARDARIAN_CANCEL_URL") or "https://t.me/TheStarVipBOT",
        "metadata": {
            "payment_transaction_id": transaction_id,
            "user_id": user_id,
            "group_id": group_id,
            "plan_id": plan_id
        }
    }

    response = requests.post(
        f"{get_guardarian_base_url(config)}/v1/transaction",
        headers=build_guardarian_headers(config),
        json=payload,
        timeout=30
    )
    response.raise_for_status()

    return response.json()


def get_guardarian_transaction(config, guardarian_transaction_id):

    response = requests.get(
        f"{get_guardarian_base_url(config)}/v1/transaction/{guardarian_transaction_id}",
        headers=build_guardarian_headers(config),
        timeout=20
    )
    response.raise_for_status()

    return response.json()


def extract_guardarian_transaction_id(payload):

    if not isinstance(payload, dict):

        return None

    event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload

    return (
        event_payload.get("id")
        or event_payload.get("transaction_id")
        or event_payload.get("order_id")
        or payload.get("id")
        or payload.get("transaction_id")
        or payload.get("order_id")
    )


def extract_guardarian_payment_url(transaction):

    if not isinstance(transaction, dict):

        return None

    for key in (
        "payment_url",
        "paymentUrl",
        "checkout_url",
        "checkoutUrl",
        "redirect_url",
        "redirectUrl",
        "url"
    ):

        if transaction.get(key):

            return transaction.get(key)

    return None


def fetch_guardarian_transaction(provider_order_id=None, transaction_id=None):

    try:

        with conn.cursor() as cur:

            if transaction_id:

                cur.execute("""

                    SELECT id,
                           status,
                           payment_scope,
                           purchase_type,
                           user_id,
                           owner_user_id,
                           group_id,
                           plan_id,
                           amount,
                           currency,
                           external_payment_id,
                           external_checkout_id,
                           provider_config_id,
                           provider_config_scope,
                           metadata_json
                    FROM payment_transactions
                    WHERE id=%s
                    AND provider=%s
                    LIMIT 1

                """, (
                    transaction_id,
                    PAYMENT_PROVIDER_GUARDARIAN
                ))

            else:

                cur.execute("""

                    SELECT id,
                           status,
                           payment_scope,
                           purchase_type,
                           user_id,
                           owner_user_id,
                           group_id,
                           plan_id,
                           amount,
                           currency,
                           external_payment_id,
                           external_checkout_id,
                           provider_config_id,
                           provider_config_scope,
                           metadata_json
                    FROM payment_transactions
                    WHERE external_checkout_id=%s
                    AND provider=%s
                    LIMIT 1

                """, (
                    provider_order_id,
                    PAYMENT_PROVIDER_GUARDARIAN
                ))

            row = cur.fetchone()

    except Exception as e:

        print("Error buscando transacción Guardarian:", e)
        return None

    if not row:

        return None

    return {
        "id": row[0],
        "status": row[1],
        "payment_scope": row[2],
        "purchase_type": row[3],
        "user_id": row[4],
        "owner_user_id": row[5],
        "group_id": row[6],
        "plan_id": row[7],
        "amount": row[8],
        "currency": row[9],
        "external_payment_id": row[10],
        "external_checkout_id": row[11],
        "provider_config_id": row[12],
        "provider_config_scope": row[13],
        "metadata_json": row[14] or {}
    }


def update_guardarian_transaction_reference(transaction_id, provider_order_id, provider_transaction):

    metadata = sanitize_payment_metadata({
        "guardarian_transaction_id": provider_order_id,
        "guardarian_status": provider_transaction.get("status") if isinstance(provider_transaction, dict) else None,
        "guardarian_payment_url_present": bool(extract_guardarian_payment_url(provider_transaction))
    })

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET external_checkout_id=%s,
                    external_payment_id=COALESCE(%s, external_payment_id),
                    metadata_json=COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                    metadata=COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s

            """, (
                provider_order_id,
                provider_order_id,
                json.dumps(metadata),
                json.dumps(metadata),
                transaction_id
            ))

        conn.commit()
        return True

    except Exception as e:

        conn.rollback()
        print("Error guardando referencia Guardarian:", e)
        return False


def update_guardarian_transaction_status(transaction_id, status, external_payment_id=None, metadata=None):

    metadata = sanitize_payment_metadata(metadata or {})

    try:

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
                json.dumps(metadata),
                json.dumps(metadata),
                transaction_id
            ))

        conn.commit()
        return True

    except Exception as e:

        conn.rollback()
        print("Error actualizando transacción Guardarian:", e)
        return False


def create_platform_guardarian_order(user_id, amount, currency="EUR", purchase_type=PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION, platform_product_key=None, description=None, metadata=None):

    if str(currency or "").upper() != "EUR":

        raise ValueError("Guardarian plataforma solo acepta EUR en esta fase.")

    if purchase_type not in GUARDARIAN_ALLOWED_PLATFORM_PURCHASE_TYPES:

        raise ValueError("Tipo de compra de plataforma no permitido para Guardarian.")

    config_row, config = get_platform_guardarian_config()
    internal_reference = f"guardarian_platform_{uuid.uuid4().hex}"
    transaction_id = create_payment_transaction(
        PAYMENT_PROVIDER_GUARDARIAN,
        status=PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_PLATFORM,
        purchase_type=purchase_type,
        user_id=user_id,
        platform_product_key=platform_product_key,
        amount=amount,
        currency="EUR",
        idempotency_key=internal_reference,
        provider_config_id=config_row.get("id"),
        provider_config_scope=PROVIDER_CONFIG_SCOPE_PLATFORM,
        metadata={
            **(metadata or {}),
            "description": description,
            "source": "create_guardarian_platform_order",
            "auto_rule": "status_finished_only"
        }
    )

    if not transaction_id:

        raise RuntimeError("No se pudo registrar la transacción Guardarian.")

    provider_transaction = create_guardarian_transaction(
        config,
        amount,
        user_id,
        None,
        None,
        transaction_id
    )
    provider_order_id = str(provider_transaction.get("id") or provider_transaction.get("transaction_id") or provider_transaction.get("order_id") or "")

    if not provider_order_id:

        update_guardarian_transaction_status(
            transaction_id,
            PAYMENT_STATUS_MANUAL_REVIEW,
            metadata={"reason": "missing_guardarian_transaction_id"}
        )
        raise RuntimeError("Guardarian no devolvió identificador de transacción.")

    update_guardarian_transaction_reference(transaction_id, provider_order_id, provider_transaction)

    log_event(
        "guardarian_platform_order_created",
        category="payment",
        severity="info",
        scope="global",
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Orden Guardarian plataforma creada.",
        metadata={
            "transaction_id": transaction_id,
            "guardarian_transaction_id": provider_order_id,
            "purchase_type": purchase_type,
            "amount": amount,
            "currency": "EUR"
        }
    )

    return build_guardarian_order_response(transaction_id, config, provider_transaction)


def create_group_guardarian_order(user_id, group_id, plan_id, metadata=None):

    plan = fetch_group_plan(group_id, plan_id)

    if not plan:

        raise ValueError("Plan no válido para esta comunidad.")

    if str(plan.get("currency") or "EUR").upper() != "EUR":

        raise ValueError("Guardarian solo acepta planes en EUR en esta fase.")

    config_row, config = get_group_guardarian_config(group_id)
    internal_reference = f"guardarian_group_{uuid.uuid4().hex}"
    transaction_id = create_payment_transaction(
        PAYMENT_PROVIDER_GUARDARIAN,
        status=PAYMENT_STATUS_PENDING,
        payment_scope=PAYMENT_SCOPE_GROUP,
        purchase_type=PURCHASE_TYPE_GROUP_ACCESS,
        user_id=user_id,
        owner_user_id=config_row.get("owner_user_id"),
        group_id=group_id,
        plan_id=plan_id,
        amount=plan.get("amount"),
        currency="EUR",
        idempotency_key=internal_reference,
        provider_config_id=config_row.get("id"),
        provider_config_scope=PROVIDER_CONFIG_SCOPE_GROUP,
        metadata={
            **(metadata or {}),
            "source": "create_guardarian_group_order",
            "auto_rule": "status_finished_only",
            "plan_name": plan.get("plan_name"),
            "group_name": plan.get("group_name")
        }
    )

    if not transaction_id:

        raise RuntimeError("No se pudo registrar la transacción Guardarian.")

    provider_transaction = create_guardarian_transaction(
        config,
        plan.get("amount"),
        user_id,
        group_id,
        plan_id,
        transaction_id
    )
    provider_order_id = str(provider_transaction.get("id") or provider_transaction.get("transaction_id") or provider_transaction.get("order_id") or "")

    if not provider_order_id:

        update_guardarian_transaction_status(
            transaction_id,
            PAYMENT_STATUS_MANUAL_REVIEW,
            metadata={"reason": "missing_guardarian_transaction_id"}
        )
        raise RuntimeError("Guardarian no devolvió identificador de transacción.")

    update_guardarian_transaction_reference(transaction_id, provider_order_id, provider_transaction)

    log_event(
        "guardarian_group_order_created",
        category="payment",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Orden Guardarian de grupo creada.",
        metadata={
            "transaction_id": transaction_id,
            "guardarian_transaction_id": provider_order_id,
            "plan_id": plan_id,
            "amount": plan.get("amount"),
            "currency": "EUR"
        }
    )

    return build_guardarian_order_response(transaction_id, config, provider_transaction, plan=plan)


def build_guardarian_order_response(transaction_id, config, provider_transaction=None, plan=None):

    provider_transaction = provider_transaction or {}

    return {
        "transaction_id": transaction_id,
        "provider_order_id": provider_transaction.get("id") or provider_transaction.get("transaction_id") or provider_transaction.get("order_id"),
        "payment_url": extract_guardarian_payment_url(provider_transaction),
        "url": extract_guardarian_payment_url(provider_transaction),
        "status": provider_transaction.get("status") or PAYMENT_STATUS_PENDING,
        "fiat_currency": "EUR",
        "payout_currency": "USDT",
        "payout_network": config.get("payout_network"),
        "payout_wallet_masked": mask_wallet(config.get("payout_wallet")),
        "amount": plan.get("amount") if plan else provider_transaction.get("expected_from_amount"),
        "plan_name": plan.get("plan_name") if plan else None,
        "auto_activation": "finished_only"
    }


def load_config_for_transaction(transaction):

    if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP:

        config_row = fetch_group_payment_provider_config(transaction.get("group_id"), PAYMENT_PROVIDER_GUARDARIAN)

    else:

        config_row = fetch_platform_payment_provider_config(PAYMENT_PROVIDER_GUARDARIAN)

    if not config_row or not config_row.get("encrypted_config_json"):

        raise PaymentProviderUnavailable("No se encontró configuración cifrada de Guardarian.")

    config = decrypt_provider_config(config_row.get("encrypted_config_json"))
    is_valid, error = validate_guardarian_config(config)

    if not is_valid:

        raise PaymentProviderUnavailable(error)

    return config_row, config


def validate_guardarian_official_status(transaction, official_transaction):

    status = official_transaction.get("status")
    mapped_status = map_guardarian_status_to_internal(status)
    expected_currency = str(transaction.get("currency") or "EUR").upper()
    received_currency = str(
        official_transaction.get("from_currency")
        or official_transaction.get("initial_from_currency")
        or expected_currency
    ).upper()

    if received_currency and received_currency != expected_currency:

        return PAYMENT_STATUS_MANUAL_REVIEW, "currency_mismatch"

    expected_amount = transaction.get("amount")
    received_amount = (
        official_transaction.get("expected_from_amount")
        or official_transaction.get("from_amount")
        or official_transaction.get("from_amount_in_eur")
    )

    if received_amount is not None and expected_amount is not None:

        try:

            if int(float(received_amount)) != int(expected_amount):

                return PAYMENT_STATUS_MANUAL_REVIEW, "amount_mismatch"

        except Exception:

            return PAYMENT_STATUS_MANUAL_REVIEW, "amount_unreadable"

    return mapped_status, None


def process_guardarian_webhook(event_body):

    event_body = event_body or {}
    provider_order_id = extract_guardarian_transaction_id(event_body)

    if not provider_order_id:

        log_event(
            "guardarian_webhook_missing_transaction_id",
            category="payment",
            severity="warning",
            message="Webhook Guardarian sin id de transacción.",
            metadata={"received_keys": list(event_body.keys())[:20]}
        )

        return {"status_code": 202, "message": "Missing transaction id"}

    transaction = fetch_guardarian_transaction(provider_order_id=str(provider_order_id))

    if not transaction:

        log_event(
            "guardarian_webhook_unmatched",
            category="payment",
            severity="warning",
            message="Webhook Guardarian recibido sin transacción interna asociada.",
            metadata={"guardarian_transaction_id": provider_order_id}
        )

        return {"status_code": 202, "message": "Transaction not found"}

    if transaction.get("status") == PAYMENT_STATUS_PAID:

        return {"status_code": 200, "message": "Already processed"}

    try:

        _config_row, config = load_config_for_transaction(transaction)
        official_transaction = get_guardarian_transaction(config, provider_order_id)

    except Exception as e:

        update_guardarian_transaction_status(
            transaction.get("id"),
            PAYMENT_STATUS_MANUAL_REVIEW,
            metadata={
                "guardarian_transaction_id": provider_order_id,
                "status_check_error": str(e),
                "manual_review_reason": "status_api_error"
            }
        )
        log_event(
            "guardarian_status_check_failed",
            category="payment",
            severity="warning",
            scope="group" if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP else "global",
            group_id=transaction.get("group_id"),
            actor_user_id=transaction.get("user_id"),
            target_user_id=transaction.get("user_id"),
            message="No se pudo verificar Guardarian por API oficial.",
            metadata={
                "transaction_id": transaction.get("id"),
                "guardarian_transaction_id": provider_order_id,
                "error": str(e)
            }
        )

        return {"status_code": 202, "message": "Manual review"}

    official_status = official_transaction.get("status")
    new_status, review_reason = validate_guardarian_official_status(transaction, official_transaction)
    activation_status = "pending"

    if new_status == PAYMENT_STATUS_PAID:

        if (
            transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP
            and transaction.get("purchase_type") == PURCHASE_TYPE_GROUP_ACCESS
            and transaction.get("group_id")
            and transaction.get("plan_id")
            and transaction.get("user_id")
        ):

            grant_result = grant_group_access_after_payment(
                PAYMENT_PROVIDER_GUARDARIAN,
                transaction.get("user_id"),
                transaction.get("group_id"),
                transaction.get("plan_id"),
                external_payment_id=provider_order_id,
                external_checkout_id=provider_order_id,
                amount=transaction.get("amount"),
                currency=transaction.get("currency"),
                transaction_id=transaction.get("id")
            )

            if not grant_result.get("ok"):

                update_guardarian_transaction_status(
                    transaction.get("id"),
                    PAYMENT_STATUS_MANUAL_REVIEW,
                    external_payment_id=provider_order_id,
                    metadata={
                        "guardarian_status": official_status,
                        "manual_review_reason": grant_result.get("reason")
                    }
                )

                return {"status_code": 500, "message": "Access grant failed"}

            activation_status = "access_granted"

        else:

            activation_status = "paid_pending_platform_fulfillment"

    elif new_status == PAYMENT_STATUS_PENDING:

        activation_status = "pending_guardarian_confirmation"

    elif new_status == PAYMENT_STATUS_MANUAL_REVIEW:

        activation_status = review_reason or "manual_review"

    else:

        activation_status = "payment_not_successful"

    update_guardarian_transaction_status(
        transaction.get("id"),
        new_status,
        external_payment_id=provider_order_id,
        metadata={
            "guardarian_status": official_status,
            "guardarian_transaction_id": provider_order_id,
            "activation_status": activation_status,
            "status_source": "GET /v1/transaction/{id}",
            "review_reason": review_reason
        }
    )

    log_event(
        "guardarian_payment_processed",
        category="payment",
        severity="info" if new_status == PAYMENT_STATUS_PAID else "warning",
        scope="group" if transaction.get("payment_scope") == PAYMENT_SCOPE_GROUP else "global",
        group_id=transaction.get("group_id"),
        actor_user_id=transaction.get("user_id"),
        target_user_id=transaction.get("user_id"),
        message="Pago Guardarian procesado tras consultar estado oficial.",
        metadata={
            "transaction_id": transaction.get("id"),
            "guardarian_transaction_id": provider_order_id,
            "official_status": official_status,
            "stored_status": new_status,
            "activation_status": activation_status,
            "payment_scope": transaction.get("payment_scope"),
            "plan_id": transaction.get("plan_id")
        }
    )

    return {"status_code": 200, "message": "OK"}
