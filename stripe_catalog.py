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


def create_stripe_product_and_price(name, amount_major, currency, metadata=None,
                                    recurring_interval_days=None):
    """
    Crea un Producto y un Precio en Stripe vía API.

    Sin recurring_interval_days es un precio de pago único (lo de siempre).
    Con él, el precio es RECURRENTE: Stripe cobrará solo cada periodo y el plan
    se convierte en renovación automática. La duración en días se traduce al
    intervalo que el comprador espera ver en su extracto (30 días → mensual).

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

    price_kwargs = dict(
        product=product["id"],
        unit_amount=to_stripe_unit_amount(amount_major, currency),
        currency=currency,
        metadata=safe_metadata
    )

    # Marca fiscal del precio (inclusive por defecto): sin ella, el día que
    # el propietario encienda Stripe Tax el checkout fallaría con "price has
    # no tax_behavior". Con Tax apagado, Stripe la ignora: nadie paga un
    # céntimo distinto por esto.
    from stripe_tax_service import tax_price_kwargs

    price_kwargs.update(tax_price_kwargs())

    if recurring_interval_days:

        from group_subscription_service import stripe_recurring_interval

        interval, interval_count = stripe_recurring_interval(recurring_interval_days)
        price_kwargs["recurring"] = {
            "interval": interval,
            "interval_count": interval_count
        }

    price = stripe.Price.create(**price_kwargs)

    return product["id"], price["id"]
