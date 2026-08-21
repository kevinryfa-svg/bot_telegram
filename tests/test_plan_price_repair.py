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


# =========================
# LA MONEDA QUE STRIPE RECHAZA
# =========================
# En producción la moneda del plan estaba escrita «EURO». Stripe contesta
# «Invalid currency: euro» y no crea el precio, así que el plan no se puede poner
# a cobrar por mucho que todo lo demás esté bien.

def test_an_unmistakable_alias_is_translated_for_stripe(catalogo):
    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET currency='EURO' WHERE id=661")

    pps.reparar_precios_de_planes()

    assert catalogo["creados"][0]["currency"] == "EUR", (
        "«EURO» es el mismo euro escrito de otra forma, y Stripe no lo acepta"
    )


def test_a_currency_nobody_can_read_is_refused_not_guessed(catalogo):
    """Cobrar en una moneda que nadie ha elegido es peor que no cobrar."""

    import pytest as _pytest

    with _pytest.raises(ValueError):
        pps.moneda_valida_para_stripe("dólares")

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET currency='ZZZZ' WHERE id=661")

    assert pps.reparar_precios_de_planes() == []
    assert catalogo["creados"] == []


def test_changing_the_price_canonicalises_the_stored_currency(catalogo):
    """Dejarla mal convierte cada futuro cambio de precio en el mismo fallo."""

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET currency='EURO' WHERE id=661")

    ok, _detalle = pps.set_group_plan_price(661, 29)

    assert ok is True

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT currency, amount FROM plans WHERE id=661")
        moneda, importe = cur.fetchone()

    assert moneda == "EUR"
    assert float(importe) == 29.0


# =========================
# LO QUE NO PUEDE SER UN PRECIO
# =========================
# En producción, dentro del stripe_price_id de un plan activo había una
# respuesta de soporte entera. Eso no es «un precio que quizá ya no existe»: es
# algo que no ha cobrado nunca ni puede cobrar. Tratarlo como un precio válido
# —y no tocarlo por prudencia— deja el plan anunciándose y sin poder cobrar.

def test_a_price_id_that_cannot_be_one_is_replaced(catalogo):
    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plans SET stripe_price_id=%s, price_id=%s WHERE id=661",
            ("Hola lorrrdd, gracias por tu mensaje.",) * 2
        )

    reparados = pps.reparar_precios_de_planes()

    assert len(reparados) == 1

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT stripe_price_id, price_id FROM plans WHERE id=661")
        stripe_price_id, price_id = cur.fetchone()

    assert stripe_price_id == "price_creado_1"
    assert price_id == "price_creado_1", (
        "el identificador imposible estaba en los dos campos: dejar uno "
        "apuntando a él mantiene el cobro roto"
    )


def test_a_real_price_is_still_never_replaced(catalogo):
    """La regla de siempre: un precio de verdad no se toca aquí."""

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plans SET stripe_price_id='price_1Real', "
            "price_id='price_1Real' WHERE id=661"
        )

    assert pps.reparar_precios_de_planes() == []

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT stripe_price_id FROM plans WHERE id=661")
        assert cur.fetchone()[0] == "price_1Real"

    assert catalogo["creados"] == [], (
        "reemplazarlo cambiaría lo que se cobra sin que nadie lo haya decidido"
    )


def test_the_startup_line_says_it_was_not_a_price(catalogo):
    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plans SET stripe_price_id='Hola, buenas tardes' WHERE id=661"
        )

    linea = pps.describe_price_repairs()

    assert "no era un precio" in linea, (
        "un plan que nunca tuvo precio y uno con basura dentro se arreglan "
        "igual, pero se buscan en sitios distintos"
    )


def test_an_orphan_plan_is_explained_not_shrugged_at(catalogo):
    """El motivo honesto delató un hueco real: el plan sin comunidad.

    La consulta de vendibles hace JOIN con groups, así que un plan cuya
    comunidad ya no existe desaparece de ella sin dejar rastro. En producción
    salió con el motivo «ninguna razón conocida lo explica», que es justo lo que
    ese texto existe para provocar: buscar en vez de inventarse una causa.
    """

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(662, 999999, 'Huérfano', 'price_x', 'price_x', 30, 5, 'EUR', TRUE)"
        )

    diagnostico = pps.diagnostico_de_plan(662)

    assert diagnostico["vendible"] is False
    assert "huérfano" in diagnostico["motivo"]
    assert "999999" in diagnostico["motivo"]
