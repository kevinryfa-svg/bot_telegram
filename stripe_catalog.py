import stripe


# =========================
# STRIPE CATALOG — CREACIÓN DE PRODUCTO/PRECIO VÍA API
# =========================
# Permite que el bot cree el Producto y el Precio en Stripe automáticamente
# (sin pasar por el panel de Stripe) usando la clave de plataforma ya
# configurada en main.py (stripe.api_key).


# Monedas "de cero decimales" en Stripe: el importe NO se multiplica por 100.
_ZERO_DECIMAL_CURRENCIES = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"
}


def to_stripe_unit_amount(amount_major, currency):
    """
    Convierte un importe en la unidad principal (p.ej. 10 EUR) a la unidad
    mínima que espera Stripe (p.ej. 1000 céntimos). Respeta las monedas de
    cero decimales.
    """

    currency = (currency or "eur").strip().lower()

    value = float(amount_major)

    if currency in _ZERO_DECIMAL_CURRENCIES:

        return int(round(value))

    return int(round(value * 100))


def create_stripe_product_and_price(name, amount_major, currency, metadata=None):
    """
    Crea un Producto y un Precio (pago único) en Stripe vía API.

    Devuelve una tupla (product_id, price_id). Propaga la excepción de Stripe
    si la creación falla, para que quien llame decida cómo avisar.
    """

    currency = (currency or "EUR").strip().lower()
    safe_metadata = {
        str(k): str(v)
        for k, v in (metadata or {}).items()
        if v is not None
    }

    product = stripe.Product.create(
        name=(name or "Plan"),
        metadata=safe_metadata
    )

    price = stripe.Price.create(
        product=product["id"],
        unit_amount=to_stripe_unit_amount(amount_major, currency),
        currency=currency,
        metadata=safe_metadata
    )

    return product["id"], price["id"]
