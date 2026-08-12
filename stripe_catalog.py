import stripe


# =========================
# STRIPE CATALOG — CREACIÓN DE PRODUCTO/PRECIO VÍA API
# =========================
# Permite que el bot cree el Producto y el Precio en Stripe automáticamente
# (sin pasar por el panel de Stripe) usando la clave de plataforma ya
# configurada en main.py (stripe.api_key).


from payment_gateway_config import amount_to_minor_units


def to_stripe_unit_amount(amount_major, currency):
    """
    Delegado en la conversión compartida de payment_gateway_config: antes cada
    proveedor tenía la suya y tres de cuatro se equivocaban de unidad.
    """

    return amount_to_minor_units(amount_major, currency)


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
