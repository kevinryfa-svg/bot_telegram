"""
La tienda de servicios extra: la única línea de ingresos recurrentes.

Estaba apagada por dos motivos que se sumaban, y ninguno daba error:

  - ensure_owner_addon_products_seeded() NO SE LLAMABA desde ningún sitio, así
    que la tabla estaba vacía y la pantalla decía «no hay servicios extra
    activos para mostrar», sin un botón.
  - y los productos se sembraban SIN stripe_price_id, que es justo lo que el
    checkout mete en line_items. Aunque la tienda se hubiera llenado, comprar
    habría sido imposible: price=None.

Un producto que no se puede comprar no factura, y esto es lo que paga el
servidor todos los meses.
"""

import pytest

import owner_addon_service as oas


@pytest.fixture
def tienda(clean_db, monkeypatch):
    """La tienda sembrada, con Stripe simulado y las llamadas a la vista."""

    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append({
            "name": name,
            "amount_major": amount_major,
            "currency": currency,
            "metadata": metadata or {},
            "recurring_interval_days": recurring_interval_days,
        })
        return (f"prod_{len(creados)}", f"price_{len(creados)}")

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    return {"db": clean_db, "creados": creados}


def test_the_store_was_empty_and_the_seed_fills_it(tienda):
    assert oas.fetch_owner_addon_products() == [], (
        "así estaba producción: la tienda vacía"
    )

    oas.ensure_owner_addon_products_seeded()

    productos = oas.fetch_owner_addon_products()
    codigos = sorted(p["code"] for p in productos)

    assert codigos == ["ad_promo", "backups", "bundle_ads_backups"]


def test_seeding_twice_does_not_duplicate(tienda):
    oas.ensure_owner_addon_products_seeded()
    oas.ensure_owner_addon_products_seeded()

    assert len(oas.fetch_owner_addon_products()) == 3, (
        "un redespliegue no puede duplicar el catálogo"
    )


def test_cents_are_not_charged_as_euros(tienda):
    """La trampa que habría cobrado 1.999 € al mes en vez de 19,99 €.

    monthly_price_cents son CÉNTIMOS; create_stripe_product_and_price espera
    unidades MAYORES. Es el mismo error de unidad que ya tuvo el panel de
    ingresos, y aquí no lo lee nadie: lo paga un cliente.
    """

    oas.ensure_owner_addon_products_seeded()

    producto = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "ad_promo"
    )

    assert producto["monthly_price_cents"] == 1999

    oas.ensure_owner_addon_stripe_price(producto)

    assert len(tienda["creados"]) == 1

    creado = tienda["creados"][0]

    assert creado["amount_major"] == pytest.approx(19.99), (
        f"se pidió un precio de {creado['amount_major']} en unidades mayores"
    )
    assert creado["amount_major"] < 100, (
        "cualquier cosa por encima de 100 aquí es un error de unidad"
    )


def test_the_price_is_monthly_because_the_screen_says_monthly(tienda):
    oas.ensure_owner_addon_products_seeded()

    producto = oas.fetch_owner_addon_products()[0]
    oas.ensure_owner_addon_stripe_price(producto)

    assert tienda["creados"][0]["recurring_interval_days"] == 30, (
        "la pantalla dice «/mes»: cobrar con otro periodo es un cargo que el "
        "cliente no reconoce"
    )
    assert tienda["creados"][0]["metadata"]["purpose"] == "owner_addon"


def test_the_price_is_created_once_and_then_reused(tienda):
    oas.ensure_owner_addon_products_seeded()

    producto = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "backups"
    )

    primero = oas.ensure_owner_addon_stripe_price(producto)

    # Se relee de la base: el precio tiene que haber quedado guardado.
    recargado = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "backups"
    )

    assert recargado["stripe_price_id"] == primero

    segundo = oas.ensure_owner_addon_stripe_price(recargado)

    assert segundo == primero
    assert len(tienda["creados"]) == 1, (
        "crear un precio nuevo en cada compra llenaría Stripe de precios "
        "duplicados del mismo servicio"
    )


def test_a_stripe_failure_leaves_the_store_readable(tienda, monkeypatch):
    """Si Stripe no contesta, la tienda se ve y el precio se crea después."""

    import stripe_catalog

    def explota(*args, **kwargs):
        raise RuntimeError("Stripe down")

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", explota
    )

    linea = oas.prepare_owner_addon_store()

    assert "3 disponibles" in linea
    assert "0 con precio" in linea, (
        "el arranque dice cuántos quedaron sin precio, en vez de callarse"
    )
    assert len(oas.fetch_owner_addon_products()) == 3


def test_the_startup_line_says_what_can_be_sold(tienda):
    linea = oas.prepare_owner_addon_store()

    assert "3 disponibles" in linea
    assert "9,99–24,99 EUR/mes" in linea, (
        "el rango de precios es lo que dice si la tienda está puesta de verdad"
    )
    assert "3 con precio de Stripe listo" in linea


def test_the_checkout_no_longer_goes_out_with_price_none(tienda, monkeypatch):
    """El fallo de fondo: line_items[0].price era None."""

    import callback_router as cr

    oas.ensure_owner_addon_products_seeded()

    producto = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "ad_promo"
    )

    assert not producto["stripe_price_id"], "se siembra sin precio"

    sesiones = []

    class FakeSession:
        @staticmethod
        def create(**kwargs):
            sesiones.append(kwargs)
            return {"id": "cs_1", "url": "https://stripe.test/x",
                    "customer": "cus_1"}

    monkeypatch.setattr(cr.stripe.checkout, "Session", FakeSession)

    cr.create_owner_addon_stripe_checkout_session(producto, 700, 700, 51)

    assert sesiones, "no se creó ninguna sesión"

    precio = sesiones[0]["line_items"][0]["price"]

    assert precio, "el checkout salía con price=None: nadie podía comprar"
    assert precio.startswith("price_")
    assert sesiones[0]["mode"] == "subscription"


def test_a_service_without_a_price_is_refused_instead_of_charged_wrong(tienda):
    """Sin importe no se inventa un cobro: se dice que no se puede cobrar."""

    import callback_router as cr

    oas.ensure_owner_addon_products_seeded()

    with tienda["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE owner_addon_products SET monthly_price_cents=0 "
            "WHERE code='backups'"
        )

    producto = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "backups"
    )

    assert oas.ensure_owner_addon_stripe_price(producto) is None

    with pytest.raises(ValueError):
        cr.create_owner_addon_stripe_checkout_session(producto, 700, 700, 51)


def test_the_startup_actually_calls_it(tienda):
    """El fallo original era exactamente este: escrito y nunca llamado."""

    fuente = open("main.py", encoding="utf-8").read()

    assert "prepare_owner_addon_store" in fuente

    pos = fuente.index("prepare_owner_addon_store")

    assert "try:" in fuente[pos - 400:pos], (
        "una llamada a Stripe en el arranque va envuelta o puede tumbar el bot"
    )
