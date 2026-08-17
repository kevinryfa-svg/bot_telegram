"""
Stripe Tax: el IVA calculado por Stripe, no a ojo por el propietario.

Vender accesos a una comunidad a compradores de media Europa significa
tantos tipos de IVA como países. Stripe Tax lo calcula en el checkout, lo
declara en sus informes y admite el NIF-IVA del comprador de empresa
(inversión del sujeto pasivo). Esto lo enciende.

DORMIDO POR DEFECTO, y por un motivo serio: automatic_tax exige una
activación previa en el panel de Stripe (origen del negocio y países
registrados). Encenderlo aquí sin haberlo hecho allí hace que
Session.create falle — es decir, tumbaría TODOS los cobros. Así que
mientras STRIPE_TAX_ENABLED no esté a true, esto devuelve {} y el checkout
es el de siempre, byte a byte.

El comportamiento fiscal del precio (STRIPE_TAX_BEHAVIOR) sí se marca
siempre en los precios NUEVOS: es un requisito de automatic_tax y no
cambia lo que paga nadie mientras Tax esté apagado. Por defecto
"inclusive": el precio anunciado es el que se paga, que es lo que espera
quien compra un grupo de Telegram. Los precios ya creados siguen intactos.
"""

import os


TAX_ENABLED = os.environ.get(
    "STRIPE_TAX_ENABLED", "false"
).strip().lower() in ("1", "true", "yes", "on")

TAX_BEHAVIOR = (
    os.environ.get("STRIPE_TAX_BEHAVIOR", "inclusive").strip().lower()
)

# Recoger el NIF-IVA del comprador de empresa: en la UE, con un NIF válido
# de otro país, la operación va sin IVA (inversión del sujeto pasivo). Se
# puede apagar para no meter un campo extra en el checkout.
TAX_ID_COLLECTION = os.environ.get(
    "STRIPE_TAX_ID_COLLECTION", "true"
).strip().lower() not in ("0", "false", "no", "off")


def tax_price_kwargs():
    """Lo que hay que añadir al crear un precio para que Tax pueda usarlo.

    Un precio sin tax_behavior hace fallar automatic_tax con "price has no
    tax_behavior" el día que el propietario lo encienda. Marcarlo desde el
    principio es gratis: sin Tax, Stripe lo ignora.
    """

    if TAX_BEHAVIOR not in ("inclusive", "exclusive"):
        return {}

    return {"tax_behavior": TAX_BEHAVIOR}


def tax_checkout_kwargs():
    """Lo que hay que añadir al checkout para que Stripe calcule el impuesto.

    {} cuando Tax está apagado: el checkout de siempre, sin un campo nuevo
    ni un céntimo de diferencia.
    """

    if not TAX_ENABLED:
        return {}

    extra = {
        "automatic_tax": {"enabled": True},

        # Sin dirección no hay tipo que aplicar: es el dato con el que
        # Stripe decide el IVA. Checkout la guarda en el cliente que crea,
        # así que las renovaciones siguen calculando bien.
        "billing_address_collection": "required",
    }

    if TAX_ID_COLLECTION:

        extra["tax_id_collection"] = {"enabled": True}

    return extra


def tax_status_line():
    """Una línea para el panel del propietario. Sin promesas falsas."""

    if not TAX_ENABLED:

        return (
            "🧾 IVA automático: apagado.\n"
            "Se activa en el panel de Stripe (Tax → registros de países) y "
            "luego con STRIPE_TAX_ENABLED=true. Hasta entonces cobras como "
            "hasta ahora."
        )

    return (
        f"🧾 IVA automático: activo ({TAX_BEHAVIOR}).\n"
        + ("Se pide el NIF-IVA a quien compra como empresa."
           if TAX_ID_COLLECTION else
           "No se pide NIF-IVA en el checkout.")
    )
