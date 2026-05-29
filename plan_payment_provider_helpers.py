PLAN_PAYMENT_PROVIDER_STRIPE = "stripe"
PLAN_PAYMENT_PROVIDER_PAYPAL = "paypal"
PLAN_PAYMENT_PROVIDER_REVOLUT = "revolut"
PLAN_PAYMENT_PROVIDER_CHANGENOW = "changenow"
PLAN_PAYMENT_PROVIDER_GUARDARIAN = "guardarian"


PLAN_PAYMENT_PROVIDER_LABELS = {
    PLAN_PAYMENT_PROVIDER_STRIPE: "💳 Stripe",
    PLAN_PAYMENT_PROVIDER_PAYPAL: "🅿️ PayPal",
    PLAN_PAYMENT_PROVIDER_REVOLUT: "🏦 Revolut",
    PLAN_PAYMENT_PROVIDER_CHANGENOW: "💱 ChangeNOW",
    PLAN_PAYMENT_PROVIDER_GUARDARIAN: "💳 Guardarian"
}


def normalize_plan_payment_provider(provider):

    provider = (provider or PLAN_PAYMENT_PROVIDER_STRIPE).strip().lower()

    if provider in PLAN_PAYMENT_PROVIDER_LABELS:

        return provider

    return PLAN_PAYMENT_PROVIDER_STRIPE


def format_plan_payment_provider(provider):

    return PLAN_PAYMENT_PROVIDER_LABELS.get(
        normalize_plan_payment_provider(provider),
        "💳 Stripe"
    )


def get_plan_provider_id_prompt(provider, editing=False):

    provider = normalize_plan_payment_provider(provider)
    prefix = "nuevo " if editing else ""

    if provider == PLAN_PAYMENT_PROVIDER_PAYPAL:

        return (
            "Paso 2️⃣\n\n"
            f"Envía el {prefix}PayPal Plan ID, por ejemplo P-..."
        )

    if provider == PLAN_PAYMENT_PROVIDER_STRIPE:

        return (
            "Paso 2️⃣\n\n"
            f"Envía el {prefix}Stripe Price ID, por ejemplo price_..."
        )

    return (
        "Paso 2️⃣\n\n"
        f"Envía una referencia interna para este plan de {format_plan_payment_provider(provider)}.\n"
        "Ejemplo: mensual_vip"
    )
