import os


PAYMENT_PROVIDER_STRIPE = "stripe"
PAYMENT_PROVIDER_PAYPAL = "paypal"
PAYMENT_PROVIDER_REVOLUT = "revolut"
PAYMENT_PROVIDER_CRYPTO = "crypto"

PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_EXPIRED = "expired"
PAYMENT_STATUS_CANCELLED = "cancelled"

PAYMENT_SCOPE_PLATFORM = "platform"
PAYMENT_SCOPE_GROUP = "group"

PROVIDER_CONFIG_SCOPE_PLATFORM = "platform"
PROVIDER_CONFIG_SCOPE_GROUP = "group"

PAYMENT_DESTINATION_PLATFORM_ACCOUNT = "platform_account"
PAYMENT_DESTINATION_OWNER_ACCOUNT = "owner_account"
PAYMENT_DESTINATION_GROUP_CONFIG = "group_config"

PURCHASE_TYPE_GROUP_ACCESS = "group_access"
PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION = "commercial_subscription"
PURCHASE_TYPE_PLATFORM_PRODUCT = "platform_product"
PURCHASE_TYPE_OWNER_UPGRADE = "owner_upgrade"


PROVIDER_ENV_FLAGS = {
    PAYMENT_PROVIDER_STRIPE: "ENABLE_STRIPE_PAYMENTS",
    PAYMENT_PROVIDER_PAYPAL: "ENABLE_PAYPAL_PAYMENTS",
    PAYMENT_PROVIDER_REVOLUT: "ENABLE_REVOLUT_PAYMENTS",
    PAYMENT_PROVIDER_CRYPTO: "ENABLE_CRYPTO_PAYMENTS"
}


PROVIDER_LABELS = {
    PAYMENT_PROVIDER_STRIPE: "💳 Tarjeta / Stripe",
    PAYMENT_PROVIDER_PAYPAL: "🅿️ PayPal",
    PAYMENT_PROVIDER_REVOLUT: "🏦 Revolut",
    PAYMENT_PROVIDER_CRYPTO: "₿ Cripto"
}


PROVIDER_REQUIRED_ENV = {
    PAYMENT_PROVIDER_STRIPE: [
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET"
    ],
    PAYMENT_PROVIDER_PAYPAL: [
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_WEBHOOK_ID"
    ],
    PAYMENT_PROVIDER_REVOLUT: [
        "REVOLUT_API_KEY",
        "REVOLUT_WEBHOOK_SECRET"
    ],
    PAYMENT_PROVIDER_CRYPTO: [
        "CRYPTO_PAYMENT_PROVIDER",
        "CRYPTO_PAYMENT_API_KEY",
        "CRYPTO_PAYMENT_WEBHOOK_SECRET"
    ]
}


PROVIDER_DEFAULT_ENABLED = {
    PAYMENT_PROVIDER_STRIPE: True,
    PAYMENT_PROVIDER_PAYPAL: False,
    PAYMENT_PROVIDER_REVOLUT: False,
    PAYMENT_PROVIDER_CRYPTO: False
}


def parse_env_bool(value, default=False):

    if value is None:

        return default


    return str(value).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
        "enabled"
    )


def is_payment_provider_enabled(provider):

    env_name = PROVIDER_ENV_FLAGS.get(provider)


    if not env_name:

        return False


    return parse_env_bool(
        os.environ.get(env_name),
        PROVIDER_DEFAULT_ENABLED.get(provider, False)
    )


def get_payment_provider_config(provider):

    required_env = PROVIDER_REQUIRED_ENV.get(provider, [])
    configured_env = [
        env_name
        for env_name in required_env
        if os.environ.get(env_name)
    ]


    return {
        "provider": provider,
        "label": PROVIDER_LABELS.get(provider, provider),
        "enabled": is_payment_provider_enabled(provider),
        "flag": PROVIDER_ENV_FLAGS.get(provider),
        "required_env": required_env,
        "configured_env_count": len(configured_env),
        "missing_env": [
            env_name
            for env_name in required_env
            if not os.environ.get(env_name)
        ]
    }


def list_payment_provider_configs():

    return [
        get_payment_provider_config(provider)
        for provider in (
            PAYMENT_PROVIDER_STRIPE,
            PAYMENT_PROVIDER_PAYPAL,
            PAYMENT_PROVIDER_REVOLUT,
            PAYMENT_PROVIDER_CRYPTO
        )
    ]
