import json

from datetime import datetime, timedelta

from db import conn


# =========================
# PAYMENT SERVICE — GET PLAN BY PRICE
# =========================

def get_active_plan_by_price(price_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       price_id,
                       duration_days,
                       amount,
                       currency,
                       group_id

                FROM plans

                WHERE price_id=%s
                AND group_id=%s
                AND is_active=TRUE

                LIMIT 1

            """, (

                price_id,
                group_id

            ))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo plan activo por price_id:",
            e
        )

        return None


# =========================
# PAYMENT SERVICE — CALCULATE EXPIRATION
# duration_days currently stores minutes for test plans when value < 1440.
# =========================

def calculate_expiration_from_duration(duration_days):

    if duration_days is None or duration_days == 0:

        return None


    duration_value = int(duration_days)


    if duration_value < 1440:

        return datetime.now() + timedelta(
            minutes=duration_value
        )


    return datetime.now() + timedelta(
        days=duration_value // 1440
    )


# =========================
# PAYMENT SERVICE — SAVE PAYMENT
# =========================

def save_payment(user_id, plan_name, group_id=None, amount=None, currency=None, stripe_payment_id=None, status="paid"):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO payments
                (user_id, group_id, stripe_payment_id, amount, currency, status, plan)

                VALUES (%s, %s, %s, %s, %s, %s, %s)

            """, (

                user_id,
                group_id,
                stripe_payment_id,
                amount,
                currency,
                status,
                plan_name

            ))

            conn.commit()

            return True

    except Exception as e:

        conn.rollback()

        print(
            "Error guardando pago:",
            e
        )

        return False


# =========================
# PAYMENT SERVICE — LIST PAYMENTS
# =========================

def list_recent_payments(limit=50, group_id=None):

    try:

        with conn.cursor() as cur:

            if group_id is None:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           group_id,
                           amount,
                           currency,
                           status,
                           payment_date

                    FROM payments

                    ORDER BY payment_date DESC

                    LIMIT %s

                """, (limit,))

            else:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           group_id,
                           amount,
                           currency,
                           status,
                           payment_date

                    FROM payments

                    WHERE group_id=%s

                    ORDER BY payment_date DESC

                    LIMIT %s

                """, (

                    group_id,
                    limit

                ))


            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando pagos:",
            e
        )

        return []


# =========================
# PAYMENT SERVICE — MULTIGATEWAY PHASE 1
# =========================

from payment_gateway_config import (
    PAYMENT_DESTINATION_GROUP_CONFIG,
    PAYMENT_DESTINATION_OWNER_ACCOUNT,
    PAYMENT_DESTINATION_PLATFORM_ACCOUNT,
    PAYMENT_PROVIDER_CHANGENOW,
    PAYMENT_PROVIDER_CRYPTO,
    PAYMENT_PROVIDER_PAYPAL,
    PAYMENT_PROVIDER_REVOLUT,
    PAYMENT_PROVIDER_STRIPE,
    PAYMENT_SCOPE_GROUP,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_PENDING,
    PROVIDER_CONFIG_SCOPE_GROUP,
    PROVIDER_CONFIG_SCOPE_PLATFORM,
    PURCHASE_TYPE_GROUP_ACCESS,
    is_payment_provider_enabled,
    list_payment_provider_configs
)
from payment_secret_store import (
    SECRET_STATUS_ACTIVE,
    SECRET_STATUS_DISABLED,
    SECRET_STATUS_NOT_CONFIGURED,
    SECRET_STATUS_PENDING,
    has_payment_encryption_key
)


class PaymentProviderUnavailable(Exception):

    pass


def get_enabled_payment_providers(include_disabled=False):

    providers = list_payment_provider_configs()


    if include_disabled:

        return providers


    return [
        provider
        for provider in providers
        if provider.get("enabled")
    ]


def is_stripe_payments_enabled():

    return is_payment_provider_enabled(PAYMENT_PROVIDER_STRIPE)


def normalize_payment_scope(scope):

    normalized = (scope or PAYMENT_SCOPE_PLATFORM).strip().lower()


    if normalized == PAYMENT_SCOPE_GROUP:

        return PAYMENT_SCOPE_GROUP


    return PAYMENT_SCOPE_PLATFORM


def sanitize_payment_metadata(metadata=None):

    metadata = metadata or {}


    if not isinstance(metadata, dict):

        return {}


    blocked_terms = (
        "secret",
        "token",
        "password",
        "key",
        "invite_link",
        "webhook_secret"
    )


    sanitized = {}


    for key, value in metadata.items():

        key_text = str(key)


        if any(term in key_text.lower() for term in blocked_terms):

            sanitized[key_text] = "[redacted]"

        else:

            sanitized[key_text] = value


    return sanitized


def build_payment_metadata(metadata=None, **context):

    merged = {}
    merged.update(metadata or {})
    merged.update({
        key: value
        for key, value in context.items()
        if value is not None
    })

    return sanitize_payment_metadata(merged)


def get_payment_provider_status(provider):

    for provider_config in list_payment_provider_configs():

        if provider_config.get("provider") == provider:

            return provider_config


    return None


def get_payment_destination_context(scope, provider, group_id=None, owner_user_id=None):

    normalized_scope = normalize_payment_scope(scope)


    if normalized_scope == PAYMENT_SCOPE_GROUP:

        config_row = fetch_group_payment_provider_config(group_id, provider)


        if config_row:

            return {
                "payment_scope": PAYMENT_SCOPE_GROUP,
                "provider_config_scope": PROVIDER_CONFIG_SCOPE_GROUP,
                "provider_config_id": config_row.get("id"),
                "destination_type": config_row.get("destination_type") or PAYMENT_DESTINATION_GROUP_CONFIG,
                "destination_ref": config_row.get("destination_ref"),
                "owner_user_id": config_row.get("owner_user_id") or owner_user_id,
                "group_id": group_id
            }


        return {
            "payment_scope": PAYMENT_SCOPE_GROUP,
            "provider_config_scope": PROVIDER_CONFIG_SCOPE_GROUP,
            "provider_config_id": None,
            "destination_type": PAYMENT_DESTINATION_GROUP_CONFIG,
            "destination_ref": None,
            "owner_user_id": owner_user_id,
            "group_id": group_id
        }


    return {
        "payment_scope": PAYMENT_SCOPE_PLATFORM,
        "provider_config_scope": PROVIDER_CONFIG_SCOPE_PLATFORM,
        "provider_config_id": None,
        "destination_type": PAYMENT_DESTINATION_PLATFORM_ACCOUNT,
        "destination_ref": "platform",
        "owner_user_id": owner_user_id,
        "group_id": group_id
    }


def is_provider_available_for_scope(provider, scope, group_id=None, owner_user_id=None):

    provider_status = get_payment_provider_status(provider)


    if not provider_status or not provider_status.get("enabled"):

        return False


    normalized_scope = normalize_payment_scope(scope)


    if normalized_scope == PAYMENT_SCOPE_PLATFORM:

        if provider == PAYMENT_PROVIDER_CHANGENOW:

            config_row = fetch_platform_payment_provider_config(PAYMENT_PROVIDER_CHANGENOW)

            return bool(
                config_row
                and config_row.get("is_enabled") is True
                and config_row.get("status") == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
                and config_row.get("encrypted_config_json")
            )


        return not provider_status.get("missing_env")


    config_row = fetch_group_payment_provider_config(group_id, provider)


    if not config_row:

        return False


    if owner_user_id and config_row.get("owner_user_id") != owner_user_id:

        return False


    if provider in (
        PAYMENT_PROVIDER_PAYPAL,
        PAYMENT_PROVIDER_REVOLUT,
        PAYMENT_PROVIDER_CHANGENOW
    ):

        return (
            config_row.get("is_enabled") is True
            and config_row.get("status") == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
            and bool(config_row.get("encrypted_config_json"))
        )


    return (
        not provider_status.get("missing_env")
        and config_row.get("is_enabled") is True
        and config_row.get("status") == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
    )


def get_available_payment_methods_for_platform_purchase(purchase_type=None, include_disabled=False):

    methods = []


    for provider_config in list_payment_provider_configs():

        provider = provider_config.get("provider")
        enabled = provider_config.get("enabled") is True
        configured = not provider_config.get("missing_env")

        if provider == PAYMENT_PROVIDER_CHANGENOW:

            platform_config = fetch_platform_payment_provider_config(PAYMENT_PROVIDER_CHANGENOW)
            configured = bool(
                platform_config
                and platform_config.get("is_enabled") is True
                and platform_config.get("status") == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
                and platform_config.get("encrypted_config_json")
            )


        available = enabled and configured
        methods.append({
            "provider": provider,
            "label": provider_config.get("label"),
            "payment_scope": PAYMENT_SCOPE_PLATFORM,
            "purchase_type": purchase_type,
            "provider_config_scope": PROVIDER_CONFIG_SCOPE_PLATFORM,
            "destination_type": PAYMENT_DESTINATION_PLATFORM_ACCOUNT,
            "available": available,
            "reason": "activo para plataforma" if available else ("faltan credenciales" if enabled else "deshabilitado globalmente"),
            "missing_env": provider_config.get("missing_env") or []
        })


    if include_disabled:

        return methods


    return [method for method in methods if method.get("available")]


def get_available_payment_methods_for_group_purchase(group_id, user_id=None, include_unavailable=False):

    methods = []


    for provider in list_group_payment_provider_statuses(group_id):

        if provider.get("provider") in (
            PAYMENT_PROVIDER_PAYPAL,
            PAYMENT_PROVIDER_REVOLUT,
            PAYMENT_PROVIDER_CHANGENOW
        ):

            available = (
                provider.get("global_enabled") is True
                and provider.get("group_enabled") is True
                and provider.get("status") == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
                and provider.get("has_encrypted_config") is True
            )

        else:

            available = (
                provider.get("global_enabled") is True
                and not provider.get("missing_env")
                and provider.get("group_enabled") is True
                and provider.get("status") == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
            )

        methods.append({
            "provider": provider.get("provider"),
            "label": provider.get("label"),
            "payment_scope": PAYMENT_SCOPE_GROUP,
            "purchase_type": PURCHASE_TYPE_GROUP_ACCESS,
            "provider_config_scope": PROVIDER_CONFIG_SCOPE_GROUP,
            "destination_type": PAYMENT_DESTINATION_GROUP_CONFIG,
            "available": available,
            "reason": provider.get("status_label"),
            "missing_env": provider.get("missing_env") or [],
            "user_id": user_id,
            "group_id": group_id
        })


    if include_unavailable:

        return methods


    return [method for method in methods if method.get("available")]


def is_paypal_group_checkout_available(group_id):

    return is_provider_available_for_scope(
        PAYMENT_PROVIDER_PAYPAL,
        PAYMENT_SCOPE_GROUP,
        group_id=group_id
    )


def is_revolut_group_checkout_available(group_id):

    return is_provider_available_for_scope(
        PAYMENT_PROVIDER_REVOLUT,
        PAYMENT_SCOPE_GROUP,
        group_id=group_id
    )


def is_changenow_group_checkout_available(group_id):

    return is_provider_available_for_scope(
        PAYMENT_PROVIDER_CHANGENOW,
        PAYMENT_SCOPE_GROUP,
        group_id=group_id
    )


def create_payment_transaction(
    provider,
    status=PAYMENT_STATUS_PENDING,
    payment_scope=PAYMENT_SCOPE_PLATFORM,
    purchase_type=None,
    user_id=None,
    owner_user_id=None,
    group_id=None,
    plan_id=None,
    platform_product_key=None,
    amount=None,
    currency=None,
    external_payment_id=None,
    external_checkout_id=None,
    idempotency_key=None,
    provider_config_id=None,
    provider_config_scope=None,
    destination_type=None,
    destination_ref=None,
    metadata=None
):

    normalized_scope = normalize_payment_scope(payment_scope)
    destination_context = get_payment_destination_context(
        normalized_scope,
        provider,
        group_id=group_id,
        owner_user_id=owner_user_id
    )
    metadata_json = build_payment_metadata(
        metadata,
        provider=provider,
        payment_scope=normalized_scope,
        purchase_type=purchase_type
    )


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO payment_transactions
                (
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
                    provider_config_scope,
                    destination_type,
                    destination_ref,
                    amount,
                    currency,
                    external_payment_id,
                    external_checkout_id,
                    idempotency_key,
                    metadata,
                    metadata_json
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s::jsonb, %s::jsonb
                )
                ON CONFLICT (idempotency_key) DO UPDATE
                SET status=EXCLUDED.status,
                    payment_scope=EXCLUDED.payment_scope,
                    purchase_type=EXCLUDED.purchase_type,
                    owner_user_id=EXCLUDED.owner_user_id,
                    group_id=EXCLUDED.group_id,
                    plan_id=EXCLUDED.plan_id,
                    platform_product_key=EXCLUDED.platform_product_key,
                    provider_config_id=EXCLUDED.provider_config_id,
                    provider_config_scope=EXCLUDED.provider_config_scope,
                    destination_type=EXCLUDED.destination_type,
                    destination_ref=EXCLUDED.destination_ref,
                    amount=COALESCE(EXCLUDED.amount, payment_transactions.amount),
                    currency=COALESCE(EXCLUDED.currency, payment_transactions.currency),
                    external_payment_id=COALESCE(EXCLUDED.external_payment_id, payment_transactions.external_payment_id),
                    external_checkout_id=COALESCE(EXCLUDED.external_checkout_id, payment_transactions.external_checkout_id),
                    metadata=EXCLUDED.metadata,
                    metadata_json=EXCLUDED.metadata_json,
                    updated_at=CURRENT_TIMESTAMP
                RETURNING id

            """, (
                provider,
                status,
                normalized_scope,
                purchase_type,
                user_id,
                owner_user_id or destination_context.get("owner_user_id"),
                group_id,
                plan_id,
                platform_product_key,
                provider_config_id or destination_context.get("provider_config_id"),
                provider_config_scope or destination_context.get("provider_config_scope"),
                destination_type or destination_context.get("destination_type"),
                destination_ref or destination_context.get("destination_ref"),
                amount,
                currency,
                external_payment_id,
                external_checkout_id,
                idempotency_key,
                json.dumps(metadata_json),
                json.dumps(metadata_json)
            ))

            row = cur.fetchone()

        conn.commit()

        return row[0] if row else None

    except Exception as e:

        conn.rollback()

        print(
            "Error creando transacción de pago:",
            e
        )

        return None


def create_placeholder_checkout(provider, **kwargs):

    if provider in (
        PAYMENT_PROVIDER_PAYPAL,
        PAYMENT_PROVIDER_REVOLUT,
        PAYMENT_PROVIDER_CRYPTO
    ):

        raise PaymentProviderUnavailable(
            "Este método de pago aún no está disponible."
        )


    raise PaymentProviderUnavailable(
        "Proveedor de pago no soportado en esta fase."
    )


def build_payment_methods_admin_text():

    lines = [
        "💳 Métodos de pago",
        "",
        "Pagos de plataforma: el dinero entra en la cuenta del dueño del bot.",
        "Sirven para mensualidades de owners, publicar comunidades, bots personalizados, upgrades y módulos premium.",
        "",
        "Stripe sigue siendo el proveedor activo para compras de acceso a grupos.",
        "PayPal ya puede usarse en sandbox/live para pagos de plataforma si sus credenciales globales están completas.",
        "Revolut ya puede usarse en sandbox/live para pagos de plataforma si sus credenciales globales están completas.",
        "ChangeNOW.io queda preparado para pagos cripto en revisión manual. No concede acceso automáticamente hasta confirmar verificación oficial segura.",
        ""
    ]


    for provider in list_payment_provider_configs():

        enabled = "activo" if provider.get("enabled") else "desactivado"
        missing = provider.get("missing_env") or []
        missing_text = "ninguna" if not missing else ", ".join(missing)

        lines.extend([
            f"{provider.get('label')}",
            f"Scope: platform",
            f"Destino: cuenta de plataforma",
            f"Estado: {enabled}",
            f"Flag: {provider.get('flag')}",
            f"Variables pendientes: {missing_text}",
            ""
        ])


    lines.extend([
        "Seguridad:",
        "- payment_scope=platform identifica cobros de la plataforma.",
        "- payment_scope=group queda reservado para cobros propios de owners/grupos.",
        "- PayPal y Revolut plataforma confirman pagos únicamente con webhook verificado.",
        "- PayPal owner/grupo todavía no concede accesos.",
        "- No se guardan secretos en logs ni en el repo.",
        "- El acceso se concede solo cuando el proveedor confirma pago por webhook verificado."
    ])


    return "\n".join(lines)


def build_payment_gateway_architecture_notes():

    return {
        "provider": "stripe/paypal/revolut/changenow/crypto",
        "status": PAYMENT_STATUS_PENDING,
        "payment_scope": "platform/group",
        "destination_type": "platform_account/owner_account/group_config",
        "idempotency": "external_checkout_id + provider + event id",
        "access_rule": "no conceder acceso hasta webhook confirmado",
        "crypto_recommendation": "Coinbase Commerce para fase inicial alojada o BTCPay Server si se quiere autocustodia y más control."
    }



# =========================
# PAYMENT SERVICE — PLATFORM PROVIDER SETTINGS
# =========================

def fetch_platform_payment_provider_config(provider):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       provider,
                       is_enabled,
                       status,
                       provider_config_scope,
                       destination_type,
                       destination_ref,
                       public_config_json,
                       secret_ref,
                       encrypted_config_json,
                       secret_status,
                       last_verified_at,
                       verified_by,
                       verification_error,
                       masked_public_summary,
                       updated_at
                FROM platform_payment_provider_configs
                WHERE provider=%s
                LIMIT 1

            """, (provider,))

            row = cur.fetchone()


            if not row:

                return None


            return {
                "id": row[0],
                "provider": row[1],
                "is_enabled": row[2],
                "status": row[3],
                "provider_config_scope": row[4],
                "destination_type": row[5],
                "destination_ref": row[6],
                "public_config_json": row[7],
                "secret_ref": row[8],
                "encrypted_config_json": row[9],
                "secret_status": row[10],
                "last_verified_at": row[11],
                "verified_by": row[12],
                "verification_error": row[13],
                "masked_public_summary": row[14],
                "updated_at": row[15]
            }

    except Exception as e:

        print("Error obteniendo configuración de proveedor de plataforma:", e)

        return None


def ensure_platform_payment_provider_config(provider, status="not_configured"):

    valid_providers = [
        provider_config.get("provider")
        for provider_config in list_payment_provider_configs()
    ]


    if provider not in valid_providers:

        return None


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO platform_payment_provider_configs
                (
                    provider,
                    is_enabled,
                    status,
                    provider_config_scope,
                    destination_type,
                    public_config_json,
                    metadata_json
                )
                VALUES (%s, FALSE, %s, %s, %s, '{}'::jsonb, '{}'::jsonb)
                ON CONFLICT (provider)
                DO UPDATE SET provider_config_scope=EXCLUDED.provider_config_scope,
                              destination_type=EXCLUDED.destination_type,
                              updated_at=CURRENT_TIMESTAMP
                RETURNING id

            """, (
                provider,
                status,
                PROVIDER_CONFIG_SCOPE_PLATFORM,
                PAYMENT_DESTINATION_PLATFORM_ACCOUNT
            ))

            row = cur.fetchone()

        conn.commit()

        return row[0] if row else None

    except Exception as e:

        conn.rollback()

        print("Error preparando configuración de proveedor de plataforma:", e)

        return None


def save_platform_payment_provider_encrypted_config(
    provider,
    encrypted_config_json,
    masked_public_summary,
    public_config_json=None,
    verified_by=None
):

    ensure_platform_payment_provider_config(provider, status=GROUP_PAYMENT_PROVIDER_STATUS_PENDING)

    safe_public_config = public_config_json or {}
    manual_review_provider = (
        provider == PAYMENT_PROVIDER_CHANGENOW
        and safe_public_config.get("manual_review_required") is True
        and safe_public_config.get("checkout_enabled") is True
    )
    target_status = (
        GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
        if manual_review_provider or safe_public_config.get("webhook_configured") is True
        else GROUP_PAYMENT_PROVIDER_STATUS_PENDING
    )
    target_secret_status = (
        SECRET_STATUS_ACTIVE
        if target_status == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
        else SECRET_STATUS_PENDING
    )


    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE platform_payment_provider_configs
                SET is_enabled=%s,
                    status=%s,
                    provider_config_scope=%s,
                    destination_type=%s,
                    public_config_json=%s::jsonb,
                    encrypted_config_json=%s,
                    secret_ref=NULL,
                    secret_status=%s,
                    last_verified_at=NULL,
                    verified_by=%s,
                    verification_error=NULL,
                    masked_public_summary=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE provider=%s

            """, (
                target_status == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE,
                target_status,
                PROVIDER_CONFIG_SCOPE_PLATFORM,
                PAYMENT_DESTINATION_PLATFORM_ACCOUNT,
                json.dumps(safe_public_config),
                encrypted_config_json,
                target_secret_status,
                verified_by,
                masked_public_summary,
                provider
            ))

        conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print("Error guardando configuración cifrada de proveedor de plataforma:", e)

        return False


def disable_platform_payment_provider_config(provider):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE platform_payment_provider_configs
                SET is_enabled=FALSE,
                    status=%s,
                    secret_status=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE provider=%s

            """, (
                GROUP_PAYMENT_PROVIDER_STATUS_DISABLED,
                SECRET_STATUS_DISABLED,
                provider
            ))

        conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print("Error desactivando proveedor de pago de plataforma:", e)

        return False


def clear_platform_payment_provider_config(provider):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE platform_payment_provider_configs
                SET is_enabled=FALSE,
                    status=%s,
                    encrypted_config_json=NULL,
                    secret_ref=NULL,
                    secret_status=%s,
                    last_verified_at=NULL,
                    verified_by=NULL,
                    verification_error=NULL,
                    masked_public_summary=NULL,
                    public_config_json='{}'::jsonb,
                    metadata_json='{}'::jsonb,
                    updated_at=CURRENT_TIMESTAMP
                WHERE provider=%s

            """, (
                GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED,
                SECRET_STATUS_NOT_CONFIGURED,
                provider
            ))

        conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print("Error borrando configuración de proveedor de plataforma:", e)

        return False


def is_changenow_platform_checkout_available():

    if not is_payment_provider_enabled(PAYMENT_PROVIDER_CHANGENOW):

        return False


    config_row = fetch_platform_payment_provider_config(PAYMENT_PROVIDER_CHANGENOW)

    return bool(
        config_row
        and config_row.get("is_enabled") is True
        and config_row.get("status") == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
        and config_row.get("encrypted_config_json")
    )


# =========================
# PAYMENT SERVICE — GROUP PROVIDER SETTINGS PHASE 1B
# =========================

GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED = "not_configured"
GROUP_PAYMENT_PROVIDER_STATUS_PENDING = "pending"
GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE = "active"
GROUP_PAYMENT_PROVIDER_STATUS_DISABLED = "disabled"
GROUP_PAYMENT_PROVIDER_STATUS_ERROR = "error"


GROUP_PAYMENT_PROVIDER_STATUS_LABELS = {
    GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED: "pendiente / no configurado",
    GROUP_PAYMENT_PROVIDER_STATUS_PENDING: "pendiente",
    GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE: "activo",
    GROUP_PAYMENT_PROVIDER_STATUS_DISABLED: "deshabilitado",
    GROUP_PAYMENT_PROVIDER_STATUS_ERROR: "error"
}


def fetch_group_payment_provider_config(group_id, provider):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       owner_user_id,
                       group_id,
                       provider,
                       is_enabled,
                       status,
                       provider_config_scope,
                       destination_type,
                       destination_ref,
                       public_config_json,
                       secret_ref,
                       encrypted_config_json,
                       secret_status,
                       last_verified_at,
                       verified_by,
                       verification_error,
                       masked_public_summary,
                       updated_at
                FROM group_payment_provider_configs
                WHERE group_id=%s
                AND provider=%s
                LIMIT 1

            """, (
                group_id,
                provider
            ))

            row = cur.fetchone()


            if not row:

                return None


            return {
                "id": row[0],
                "owner_user_id": row[1],
                "group_id": row[2],
                "provider": row[3],
                "is_enabled": row[4],
                "status": row[5],
                "provider_config_scope": row[6],
                "destination_type": row[7],
                "destination_ref": row[8],
                "public_config_json": row[9],
                "secret_ref": row[10],
                "encrypted_config_json": row[11],
                "secret_status": row[12],
                "last_verified_at": row[13],
                "verified_by": row[14],
                "verification_error": row[15],
                "masked_public_summary": row[16],
                "updated_at": row[17]
            }

    except Exception as e:

        print(
            "Error obteniendo configuración de proveedor de grupo:",
            e
        )

        return None


def ensure_group_payment_provider_config(owner_user_id, group_id, provider, status=GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED):

    valid_providers = [
        provider_config.get("provider")
        for provider_config in list_payment_provider_configs()
    ]


    if provider not in valid_providers:

        return None


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO group_payment_provider_configs
                (
                    owner_user_id,
                    group_id,
                    provider,
                    is_enabled,
                    status,
                    provider_config_scope,
                    destination_type,
                    public_config_json,
                    metadata_json
                )
                VALUES (%s, %s, %s, FALSE, %s, %s, %s, '{}'::jsonb, '{}'::jsonb)
                ON CONFLICT (group_id, provider)
                DO UPDATE SET owner_user_id=EXCLUDED.owner_user_id,
                              provider_config_scope=EXCLUDED.provider_config_scope,
                              destination_type=EXCLUDED.destination_type,
                              updated_at=CURRENT_TIMESTAMP
                RETURNING id,
                          owner_user_id,
                          group_id,
                          provider,
                          is_enabled,
                          status,
                          updated_at

            """, (
                owner_user_id,
                group_id,
                provider,
                status,
                PROVIDER_CONFIG_SCOPE_GROUP,
                PAYMENT_DESTINATION_GROUP_CONFIG
            ))

            row = cur.fetchone()

            conn.commit()

            return row

    except Exception as e:

        conn.rollback()

        print(
            "Error preparando configuración de proveedor de grupo:",
            e
        )

        return None


def list_group_payment_provider_statuses(group_id):

    saved_rows = {}


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       owner_user_id,
                       group_id,
                       provider,
                       is_enabled,
                       status,
                       provider_config_scope,
                       destination_type,
                       destination_ref,
                       public_config_json,
                       secret_ref,
                       encrypted_config_json,
                       secret_status,
                       last_verified_at,
                       verified_by,
                       verification_error,
                       masked_public_summary,
                       updated_at
                FROM group_payment_provider_configs
                WHERE group_id=%s

            """, (group_id,))

            saved_rows = {
                row[3]: {
                    "id": row[0],
                    "owner_user_id": row[1],
                    "group_id": row[2],
                    "provider": row[3],
                    "is_enabled": row[4],
                    "status": row[5],
                    "provider_config_scope": row[6],
                    "destination_type": row[7],
                    "destination_ref": row[8],
                    "public_config_json": row[9],
                    "secret_ref": row[10],
                    "encrypted_config_json": row[11],
                    "secret_status": row[12],
                    "last_verified_at": row[13],
                    "verified_by": row[14],
                    "verification_error": row[15],
                    "masked_public_summary": row[16],
                    "updated_at": row[17]
                }
                for row in cur.fetchall()
            }

    except Exception as e:

        print(
            "Error listando proveedores de pago del grupo:",
            e
        )


    statuses = []


    for provider_config in list_payment_provider_configs():

        provider = provider_config.get("provider")
        saved = saved_rows.get(provider)
        global_enabled = provider_config.get("enabled") is True


        if saved:

            is_enabled = saved.get("is_enabled")
            status = saved.get("status")
            secret_ref = saved.get("secret_ref")
            encrypted_config_json = saved.get("encrypted_config_json")
            secret_status = saved.get("secret_status") or SECRET_STATUS_NOT_CONFIGURED
            last_verified_at = saved.get("last_verified_at")
            verified_by = saved.get("verified_by")
            verification_error = saved.get("verification_error")
            masked_public_summary = saved.get("masked_public_summary")
            updated_at = saved.get("updated_at")
            provider_config_id = saved.get("id")
            provider_config_scope = saved.get("provider_config_scope") or PROVIDER_CONFIG_SCOPE_GROUP
            destination_type = saved.get("destination_type") or PAYMENT_DESTINATION_GROUP_CONFIG
            destination_ref = saved.get("destination_ref")

        else:

            is_enabled = False
            status = GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED
            secret_ref = None
            encrypted_config_json = None
            secret_status = SECRET_STATUS_NOT_CONFIGURED
            last_verified_at = None
            verified_by = None
            verification_error = None
            masked_public_summary = None
            updated_at = None
            provider_config_id = None
            provider_config_scope = PROVIDER_CONFIG_SCOPE_GROUP
            destination_type = PAYMENT_DESTINATION_GROUP_CONFIG
            destination_ref = None


        if provider in (
            PAYMENT_PROVIDER_PAYPAL,
            PAYMENT_PROVIDER_REVOLUT,
            PAYMENT_PROVIDER_CHANGENOW
        ):

            provider_missing_env = []

        else:

            provider_missing_env = provider_config.get("missing_env") or []


        if not global_enabled:

            effective_status = GROUP_PAYMENT_PROVIDER_STATUS_DISABLED
            effective_label = "deshabilitado globalmente"
            can_be_enabled = False

        elif is_enabled and status == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE:

            effective_status = GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
            effective_label = "activo para este grupo"
            can_be_enabled = True

        else:

            effective_status = status or GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED
            effective_label = GROUP_PAYMENT_PROVIDER_STATUS_LABELS.get(
                effective_status,
                effective_status
            )
            can_be_enabled = True


        statuses.append({
            "provider": provider,
            "label": provider_config.get("label"),
            "flag": provider_config.get("flag"),
            "global_enabled": global_enabled,
            "group_enabled": is_enabled is True,
            "status": effective_status,
            "status_label": effective_label,
            "provider_config_id": provider_config_id,
            "provider_config_scope": provider_config_scope,
            "destination_type": destination_type,
            "destination_ref": destination_ref,
            "has_secret_ref": bool(secret_ref),
            "has_encrypted_config": bool(encrypted_config_json),
            "secret_status": secret_status,
            "last_verified_at": last_verified_at,
            "verified_by": verified_by,
            "verification_error": verification_error,
            "masked_public_summary": masked_public_summary,
            "encryption_ready": has_payment_encryption_key(),
            "missing_env": provider_missing_env,
            "can_be_enabled": can_be_enabled,
            "updated_at": updated_at
        })


    return statuses


def build_group_payment_methods_text(group_id, group_name, telegram_group_id, owner_user_id=None):

    lines = [
        "💳 Métodos de pago del grupo",
        "",
        f"Comunidad: {group_name or f'Grupo {group_id}'}",
        f"ID interno: {group_id}",
        f"ID Telegram: {telegram_group_id or 'pendiente'}"
    ]


    if owner_user_id:

        lines.append(f"Owner: {owner_user_id}")


    lines.extend([
        "",
        "Aquí se prepara la configuración de métodos de pago propios de esta comunidad.",
        "Estos pagos usan payment_scope=group y destino owner/grupo cuando el proveedor esté activo.",
        "Las credenciales propias del owner se configurarán desde el bot, no desde Railway.",
        "PayPal y Revolut pueden crear checkout real si tienen credenciales cifradas, webhook secreto y estado activo. ChangeNOW puede crear pagos cripto controlados, siempre en revisión manual.",
        "Los métodos siempre respetan los flags globales de la plataforma.",
        f"Cifrado de credenciales: {'preparado' if has_payment_encryption_key() else 'pendiente de PAYMENT_CONFIG_ENCRYPTION_KEY'}.",
        ""
    ])


    for provider in list_group_payment_provider_statuses(group_id):

        lines.extend([
            provider.get("label") or provider.get("provider"),
            "Scope: group",
            f"Destino futuro: {provider.get('destination_type') or PAYMENT_DESTINATION_GROUP_CONFIG}",
            f"Estado global: {'activo' if provider.get('global_enabled') else 'deshabilitado'}",
            f"Estado del grupo: {provider.get('status_label')}",
            f"Credenciales owner: {provider.get('secret_status') or SECRET_STATUS_NOT_CONFIGURED}",
            f"Flag: {provider.get('flag')}",
            ""
        ])


    lines.extend([
        "Qué falta para activar pagos propios en próximas fases:",
        "- ChangeNOW queda en revisión manual; otros proveedores cripto siguen pendientes.",
        "- PayPal y Revolut owner/grupo conceden acceso solo tras webhook verificado.",
        "",
        "Stripe global sigue funcionando como hasta ahora."
    ])


    return "\n".join(lines)


def build_group_payment_provider_detail_text(group_id, group_name, provider_status):

    provider = provider_status.get("provider")
    label = provider_status.get("label") or provider
    encryption_text = "lista" if provider_status.get("encryption_ready") else "pendiente"
    global_text = "activo" if provider_status.get("global_enabled") else "deshabilitado"
    secret_summary = provider_status.get("masked_public_summary") or "sin credenciales guardadas"
    verification_error = provider_status.get("verification_error") or "-"

    lines = [
        f"{label}",
        "",
        f"Comunidad: {group_name or f'Grupo {group_id}'}",
        "Scope: group",
        "Destino futuro: cuenta/configuración del owner.",
        f"Estado global: {global_text}",
        f"Estado del grupo: {provider_status.get('status_label')}",
        f"Credenciales: {provider_status.get('secret_status') or SECRET_STATUS_NOT_CONFIGURED}",
        f"Cifrado: {encryption_text}",
        f"Resumen público: {secret_summary}",
        f"Último error: {verification_error}",
        "",
        "Railway solo guarda credenciales globales de plataforma. Las credenciales propias de owners/grupos se configurarán desde el bot y se guardarán cifradas.",
        "",
        "PayPal y Revolut de grupo crean checkout real solo si están activos y tienen credenciales cifradas completas. Otros proveedores siguen preparados como fase futura."
    ]


    if provider == PAYMENT_PROVIDER_PAYPAL:

        lines.extend([
            "",
            "Conectar PayPal pide estos datos dentro del bot:",
            "- client_id",
            "- client_secret",
            "- webhook_id opcional",
            "- modo sandbox/live",
            "",
            "Los secretos se guardan cifrados si PAYMENT_CONFIG_ENCRYPTION_KEY está configurada. Si incluye webhook_id, PayPal queda disponible para checkout real de grupo."
        ])


    if provider == PAYMENT_PROVIDER_REVOLUT:

        lines.extend([
            "",
            "Conectar Revolut pide estos datos dentro del bot:",
            "- REVOLUT_API_KEY del comercio/owner",
            "- REVOLUT_WEBHOOK_SECRET del comercio/owner",
            "- modo sandbox/live",
            "- REVOLUT_BASE_URL opcional",
            "",
            "Los secretos se guardan cifrados si PAYMENT_CONFIG_ENCRYPTION_KEY está configurada. Revolut queda disponible para checkout real de grupo cuando está activo."
        ])


    if provider == PAYMENT_PROVIDER_CHANGENOW:

        lines.extend([
            "",
            "¿Qué es ChangeNOW.io?",
            "Permite aceptar pagos en criptomonedas y convertirlos hacia una moneda/wallet destino.",
            "",
            "Cómo funciona en este bot:",
            "1. Configuras API key, wallet, moneda y red destino.",
            "2. El comprador elige pagar con cripto.",
            "3. Se registra una operación y se muestran instrucciones de pago.",
            "4. El pago queda en revisión manual.",
            "5. El acceso solo se activa cuando un superadmin lo confirma.",
            "",
            "Seguridad: ChangeNOW no concede acceso automático en esta fase porque falta confirmación pública suficiente sobre firma/verificación de callbacks.",
            "",
            "Fixed / Floating:",
            "- fixed intenta mantener importe/tasa fija durante una ventana limitada.",
            "- floating puede variar según mercado.",
            "Para vender accesos conviene fixed si ChangeNOW lo permite y está habilitado."
        ])


    return "\n".join(lines)


def disable_group_payment_provider_config(group_id, provider):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_payment_provider_configs
                SET is_enabled=FALSE,
                    status=%s,
                    secret_status=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE group_id=%s
                AND provider=%s

            """, (
                GROUP_PAYMENT_PROVIDER_STATUS_DISABLED,
                SECRET_STATUS_DISABLED,
                group_id,
                provider
            ))

        conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print("Error desactivando proveedor de pago de grupo:", e)

        return False


def clear_group_payment_provider_config(group_id, provider):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_payment_provider_configs
                SET is_enabled=FALSE,
                    status=%s,
                    encrypted_config_json=NULL,
                    secret_ref=NULL,
                    secret_status=%s,
                    last_verified_at=NULL,
                    verified_by=NULL,
                    verification_error=NULL,
                    masked_public_summary=NULL,
                    public_config_json='{}'::jsonb,
                    metadata_json='{}'::jsonb,
                    updated_at=CURRENT_TIMESTAMP
                WHERE group_id=%s
                AND provider=%s

            """, (
                GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED,
                SECRET_STATUS_NOT_CONFIGURED,
                group_id,
                provider
            ))

        conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print("Error borrando configuración de proveedor de grupo:", e)

        return False


def save_group_payment_provider_encrypted_config(
    owner_user_id,
    group_id,
    provider,
    encrypted_config_json,
    masked_public_summary,
    public_config_json=None,
    verified_by=None
):

    ensure_group_payment_provider_config(
        owner_user_id,
        group_id,
        provider,
        status=GROUP_PAYMENT_PROVIDER_STATUS_PENDING
    )


    safe_public_config = public_config_json or {}
    webhook_configured = safe_public_config.get("webhook_configured") is True
    manual_review_provider = (
        provider == PAYMENT_PROVIDER_CHANGENOW
        and safe_public_config.get("manual_review_required") is True
        and safe_public_config.get("checkout_enabled") is True
    )
    target_status = (
        GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
        if webhook_configured or manual_review_provider
        else GROUP_PAYMENT_PROVIDER_STATUS_PENDING
    )
    target_secret_status = (
        SECRET_STATUS_ACTIVE
        if target_status == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
        else SECRET_STATUS_PENDING
    )
    target_is_enabled = target_status == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE


    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_payment_provider_configs
                SET owner_user_id=%s,
                    is_enabled=%s,
                    status=%s,
                    provider_config_scope=%s,
                    destination_type=%s,
                    public_config_json=%s::jsonb,
                    encrypted_config_json=%s,
                    secret_ref=NULL,
                    secret_status=%s,
                    last_verified_at=NULL,
                    verified_by=%s,
                    verification_error=NULL,
                    masked_public_summary=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE group_id=%s
                AND provider=%s

            """, (
                owner_user_id,
                target_is_enabled,
                target_status,
                PROVIDER_CONFIG_SCOPE_GROUP,
                PAYMENT_DESTINATION_GROUP_CONFIG,
                json.dumps(safe_public_config),
                encrypted_config_json,
                target_secret_status,
                verified_by,
                masked_public_summary,
                group_id,
                provider
            ))

        conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print("Error guardando configuración cifrada de proveedor de grupo:", e)

        return False
