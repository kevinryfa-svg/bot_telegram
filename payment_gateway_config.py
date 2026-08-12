import os

from decimal import Decimal, ROUND_HALF_UP


# =========================
# UNIDADES DE DINERO
# =========================
# plans.amount está en la unidad PRINCIPAL (15 = quince euros): el asistente
# pide "el PRECIO" y el propietario teclea 15, no 1500. Las tablas de pagos y
# transacciones, en cambio, van en la unidad MÍNIMA (céntimos), que es lo que
# asumen todas las capas que muestran importes (dividen entre 100) y lo que
# mandan los webhooks de Stripe y PayPal.
#
# Esta función es LA conversión entre ambas. Antes cada proveedor decidía por
# su cuenta y tres de los cuatro se equivocaban: PayPal guardaba euros y los
# comparaba contra los céntimos del webhook (rechazaba todos los pagos por
# "amount mismatch"), Revolut mandaba euros a una API que espera céntimos
# (cobraba 0,15 € por un plan de 15 €), y Guardarian/ChangeNOW guardaban euros
# que las pantallas luego dividían entre 100.

ZERO_DECIMAL_CURRENCIES = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"
}


def amount_to_minor_units(amount_major, currency):
    """
    15 EUR -> 1500; 15 JPY -> 15 (el yen no tiene decimales).

    Decimal y no float: 19.99 * 100 en float da 1998.9999..., y en dinero un
    céntimo perdido es una discusión con un cliente.
    """

    currency = (currency or "eur").strip().lower()

    value = Decimal(str(amount_major))

    if currency in ZERO_DECIMAL_CURRENCIES:

        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


PAYMENT_PROVIDER_STRIPE = "stripe"
PAYMENT_PROVIDER_PAYPAL = "paypal"
PAYMENT_PROVIDER_REVOLUT = "revolut"
PAYMENT_PROVIDER_CRYPTO = "crypto"
PAYMENT_PROVIDER_CHANGENOW = "changenow"
PAYMENT_PROVIDER_GUARDARIAN = "guardarian"

PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_CONFIRMING = "confirming"
PAYMENT_STATUS_MANUAL_REVIEW = "manual_review"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_EXPIRED = "expired"
PAYMENT_STATUS_CANCELLED = "cancelled"
PAYMENT_STATUS_REFUNDED = "refunded"

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
    PAYMENT_PROVIDER_CRYPTO: "ENABLE_CRYPTO_PAYMENTS",
    PAYMENT_PROVIDER_CHANGENOW: "ENABLE_CHANGENOW_PAYMENTS",
    PAYMENT_PROVIDER_GUARDARIAN: "ENABLE_GUARDARIAN_PAYMENTS"
}


PROVIDER_LABELS = {
    PAYMENT_PROVIDER_STRIPE: "💳 Tarjeta / Stripe",
    PAYMENT_PROVIDER_PAYPAL: "🅿️ PayPal",
    PAYMENT_PROVIDER_REVOLUT: "🏦 Revolut",
    PAYMENT_PROVIDER_CRYPTO: "₿ Cripto",
    PAYMENT_PROVIDER_CHANGENOW: "💱 ChangeNOW.io / Cripto",
    PAYMENT_PROVIDER_GUARDARIAN: "💳 Tarjeta EUR → USDT / Guardarian"
}


PROVIDER_REQUIRED_ENV = {
    PAYMENT_PROVIDER_STRIPE: [
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET"
    ],
    PAYMENT_PROVIDER_PAYPAL: [
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_WEBHOOK_ID",
        "PAYPAL_MODE"
    ],
    PAYMENT_PROVIDER_REVOLUT: [
        "REVOLUT_API_KEY",
        "REVOLUT_WEBHOOK_SECRET"
    ],
    PAYMENT_PROVIDER_CRYPTO: [
        "CRYPTO_PAYMENT_PROVIDER",
        "CRYPTO_PAYMENT_API_KEY",
        "CRYPTO_PAYMENT_WEBHOOK_SECRET"
    ],
    PAYMENT_PROVIDER_CHANGENOW: [
        "PAYMENT_CONFIG_ENCRYPTION_KEY"
    ],
    PAYMENT_PROVIDER_GUARDARIAN: [
        "PAYMENT_CONFIG_ENCRYPTION_KEY"
    ]
}


# Por defecto solo se ofrece lo que puede cobrar de verdad con la
# configuración actual (Stripe). ChangeNOW y Guardarian necesitan una API key
# por comunidad; mientras no esté puesta, ofrecerlos solo produce errores al
# intentar pagar. Se pueden reactivar con ENABLE_CHANGENOW_PAYMENTS=true /
# ENABLE_GUARDARIAN_PAYMENTS=true cuando haya credenciales.
PROVIDER_DEFAULT_ENABLED = {
    PAYMENT_PROVIDER_STRIPE: True,
    PAYMENT_PROVIDER_PAYPAL: False,
    PAYMENT_PROVIDER_REVOLUT: False,
    PAYMENT_PROVIDER_CRYPTO: False,
    PAYMENT_PROVIDER_CHANGENOW: False,
    PAYMENT_PROVIDER_GUARDARIAN: False
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
            PAYMENT_PROVIDER_CRYPTO,
            PAYMENT_PROVIDER_CHANGENOW,
            PAYMENT_PROVIDER_GUARDARIAN
        )
    ]
