"""
Stripe Tax: el IVA lo calcula Stripe, no el propietario a ojo.

La regla que manda sobre todas: DORMIDO POR DEFECTO. automatic_tax exige
una activación previa en el panel de Stripe; encenderlo en el código sin
haberlo hecho allí hace fallar Session.create, o sea, tumba TODOS los
cobros. Mientras el interruptor está apagado, el checkout tiene que ser el
de siempre byte a byte.
"""

import importlib

import pytest

import stripe_tax_service as tax


def recargar(monkeypatch, **env):
    """Reimporta el módulo con otro entorno: las constantes se leen al importar."""

    for clave, valor in env.items():
        monkeypatch.setenv(clave, valor)

    return importlib.reload(tax)


@pytest.fixture(autouse=True)
def restaurar_modulo():
    yield
    importlib.reload(tax)


def test_asleep_by_default_the_checkout_is_untouched():
    assert tax.TAX_ENABLED is False, (
        "encendido por defecto tumbaría los cobros de cualquiera que no lo "
        "haya activado antes en el panel de Stripe"
    )
    assert tax.tax_checkout_kwargs() == {}, (
        "apagado, el checkout no puede cambiar ni en un campo"
    )


def test_when_switched_on_stripe_calculates_the_tax(monkeypatch):
    t = recargar(monkeypatch, STRIPE_TAX_ENABLED="true")

    extra = t.tax_checkout_kwargs()

    assert extra["automatic_tax"] == {"enabled": True}
    assert extra["billing_address_collection"] == "required", (
        "sin dirección no hay tipo de IVA que aplicar"
    )
    assert extra["tax_id_collection"] == {"enabled": True}, (
        "el comprador de empresa con NIF-IVA válido va sin IVA (inversión "
        "del sujeto pasivo): sin el campo, se le cobra de más"
    )


def test_the_vat_number_field_can_be_turned_off(monkeypatch):
    t = recargar(monkeypatch, STRIPE_TAX_ENABLED="true",
                 STRIPE_TAX_ID_COLLECTION="false")

    extra = t.tax_checkout_kwargs()

    assert "tax_id_collection" not in extra
    assert extra["automatic_tax"] == {"enabled": True}


def test_new_prices_are_marked_even_with_tax_off():
    """Un precio sin tax_behavior rompe el checkout el día del encendido."""

    assert tax.tax_price_kwargs() == {"tax_behavior": "inclusive"}, (
        "inclusive por defecto: el precio anunciado es el que se paga"
    )


def test_an_invalid_behavior_marks_nothing(monkeypatch):
    t = recargar(monkeypatch, STRIPE_TAX_BEHAVIOR="lo_que_sea")

    assert t.tax_price_kwargs() == {}, (
        "mejor no marcar nada que mandarle a Stripe un valor que rechaza"
    )


def test_the_catalog_marks_the_price(monkeypatch):
    import stripe_catalog as sc

    capturas = {}

    monkeypatch.setattr(sc.stripe.Product, "create",
                        lambda **k: {"id": "prod_tax"})
    monkeypatch.setattr(sc.stripe.Price, "create",
                        lambda **k: capturas.update(k) or {"id": "price_tax"})

    sc.create_stripe_product_and_price("Mensual", 15, "EUR")

    assert capturas["tax_behavior"] == "inclusive"
    assert capturas["unit_amount"] == 1500, (
        "marcar el comportamiento fiscal no cambia el importe de nadie"
    )


def test_the_access_checkout_asks_for_the_tax_and_the_addons_do_not():
    """
    El IVA automático se aplica donde los precios los creamos nosotros. Los
    extras del propietario usan precios del panel de Stripe, que pueden no
    tener tax_behavior: activarlo ahí le rompería su propia compra.
    """

    checkout = open("checkout_routes.py", encoding="utf-8").read()

    assert "tax_checkout_kwargs()" in checkout
    assert checkout.index("session_kwargs.update(tax_checkout_kwargs())") < \
        checkout.index("stripe.checkout.Session.create(**session_kwargs)"), (
        "el IVA tiene que estar en los kwargs antes de crear la sesión"
    )

    router = open("callback_router.py", encoding="utf-8").read()
    pos = router.index("def create_owner_addon_stripe_checkout_session")
    trozo = router[pos:pos + 1600]

    # Se busca la LLAMADA, no la palabra: el comentario de ahí explica justo
    # por qué los extras se quedan fuera.
    assert "tax_checkout_kwargs()" not in trozo
    assert "automatic_tax=" not in trozo and '"automatic_tax"' not in trozo


def test_the_owner_is_told_the_truth_about_the_state(monkeypatch):
    apagado = tax.tax_status_line()

    assert "apagado" in apagado
    assert "STRIPE_TAX_ENABLED" in apagado, (
        "el propietario tiene que saber qué falta para encenderlo"
    )
    assert "cobras como hasta ahora" in apagado

    t = recargar(monkeypatch, STRIPE_TAX_ENABLED="true")
    encendido = t.tax_status_line()

    assert "activo (inclusive)" in encendido
    assert "NIF-IVA" in encendido

    panel = open("owner_panel_callbacks.py", encoding="utf-8").read()
    assert "tax_status_line()" in panel, (
        "el estado del IVA vive junto al del cobro: es la otra mitad de "
        "cómo entra el dinero"
    )
