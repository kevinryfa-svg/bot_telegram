"""
Un plan a la venta sin precio de Stripe: se anuncia y no se puede cobrar.

Lo encontré en el log de producción. El diagnóstico de cobro decía:

    Cobro: listo (servidor de pago accesible, 0 precio(s) de Stripe verificado(s))

Cero, teniendo una comunidad a la venta. Un plan puede estar activo, con importe
y con duración —o sea, en el escaparate— y no tener identificador de precio de
Stripe. Entonces se anuncia, se pulsa, y el cobro no se puede ni empezar.

Ofrecer algo que no se puede comprar es la peor mentira que puede decir una
tienda, y encima no deja rastro: el comprador ve un error genérico y se va.
"""

import pytest

import plan_price_service as pps


@pytest.fixture
def catalogo(clean_db, monkeypatch):
    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append({
            "name": name,
            "amount_major": amount_major,
            "currency": currency,
            "recurring_interval_days": recurring_interval_days,
        })
        return (f"prod_{len(creados)}", f"price_creado_{len(creados)}")

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) VALUES "
            "(61, 'StarsVip', -1061, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active, is_recurring) VALUES "
            "(661, 61, 'VIP', NULL, NULL, 360, 7, 'EUR', TRUE, TRUE)"
        )

    return {"db": db, "creados": creados}


def test_a_plan_on_sale_without_a_price_gets_one(catalogo):
    reparados = pps.reparar_precios_de_planes()

    assert len(reparados) == 1

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT stripe_price_id, price_id FROM plans WHERE id=661")
        stripe_price_id, price_id = cur.fetchone()

    assert stripe_price_id == "price_creado_1"
    assert price_id == "price_creado_1", (
        "el callback de la lista de planes usa price_id: sin él, el botón de "
        "ese plan tampoco lleva a ningún sitio"
    )


def test_the_created_price_says_exactly_what_was_advertised(catalogo):
    pps.reparar_precios_de_planes()

    creado = catalogo["creados"][0]

    assert creado["amount_major"] == pytest.approx(7.0), (
        "se crea con el importe que YA se anuncia: nadie puede pagar algo "
        "distinto de lo que vio"
    )
    assert creado["recurring_interval_days"] == 360


def test_an_existing_price_is_never_replaced(catalogo):
    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plans SET stripe_price_id='price_del_dueno' WHERE id=661"
        )

    assert pps.reparar_precios_de_planes() == []
    assert catalogo["creados"] == [], (
        "reemplazar a ciegas un precio existente cambiaría lo que se cobra sin "
        "que lo haya decidido nadie"
    )


def test_running_it_twice_creates_one_price(catalogo):
    pps.reparar_precios_de_planes()
    pps.reparar_precios_de_planes()

    assert len(catalogo["creados"]) == 1, (
        "el arranque se repite: no puede ir creando precios en cada despliegue"
    )


def test_an_undeliverable_plan_is_not_given_a_price(catalogo):
    """No se prepara para cobrar lo que el acceso va a rechazar."""

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET duration_days=1300000 WHERE id=661")

    assert pps.reparar_precios_de_planes() == []


def test_another_provider_is_left_alone(catalogo):
    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET payment_provider='paypal' WHERE id=661")

    assert pps.reparar_precios_de_planes() == []
    assert catalogo["creados"] == [], (
        "el identificador de precio de PayPal lo emite PayPal"
    )


def test_a_stripe_failure_does_not_leave_a_half_written_plan(catalogo,
                                                             monkeypatch):
    import stripe_catalog

    def explota(*args, **kwargs):
        raise RuntimeError("Stripe down")

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", explota
    )

    assert pps.reparar_precios_de_planes() == []

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT stripe_price_id FROM plans WHERE id=661")
        assert cur.fetchone()[0] is None


def test_the_startup_line_only_speaks_when_something_was_broken(catalogo):
    assert pps.describe_price_repairs() is not None

    # Ya reparado: silencio.
    assert pps.describe_price_repairs() is None


def test_the_line_names_the_community_and_the_amount(catalogo):
    linea = pps.describe_price_repairs()

    assert "StarsVip" in linea
    assert "7.00 EUR" in linea
    assert "no se podían cobrar" in linea


def test_the_startup_runs_it_wrapped():
    fuente = open("main.py", encoding="utf-8").read()

    assert "describe_price_repairs" in fuente

    pos = fuente.index("describe_price_repairs")

    assert "try:" in fuente[pos - 400:pos]
