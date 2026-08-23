"""
Del escaparate al acceso, pasando por el cobro de verdad.

Cada venta con tarjeta empieza en la MISMA ruta: el bot hace una petición HTTP a
su propio servidor (/create-checkout-session) con el identificador de precio que
acaba de anunciar. Esa ruta no tenía ni una prueba: se comprobaba el escaparate
por un lado y el webhook por otro, y el punto donde se encuentran —que es donde
se decide si alguien puede pagar— no lo miraba nadie.

Ahí vivía el fallo que costaba las ventas: el escaparate resolvía el precio con
NULLIF y el cobro sin él, así que un plan con la columna a cadena vacía se
anunciaba con un identificador y se buscaba por otro. El comprador, ya decidido,
recibía «Plan inválido».

Esta prueba recorre la cadena entera con Stripe simulado: lo que el escaparate
anuncia, se puede cobrar; y lo que se cobra, concede el acceso con su caducidad.
"""

import json

import flask
import pytest

import checkout_routes
import start_offer_service as sos


@pytest.fixture
def tienda(clean_db, monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, preview_text) VALUES "
            "(91, 'StarsVip', -1091, TRUE, TRUE, 'Lo que hay dentro.')"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(991, 91, 'Acceso 360 días', 'price_1viejo', 'price_1nuevo', 360, "
            "29, 'EUR', TRUE)"
        )

    monkeypatch.setattr(
        checkout_routes, "is_stripe_payments_enabled", lambda: True
    )

    creadas = []

    class FakeSession:
        id = "cs_test_e2e"
        url = "https://checkout.stripe.test/pagar"

    def falsa_creacion(**kwargs):
        creadas.append(kwargs)
        return FakeSession()

    monkeypatch.setattr(
        checkout_routes.stripe.checkout.Session, "create",
        staticmethod(falsa_creacion)
    )

    app = flask.Flask(__name__)
    checkout_routes.register_checkout_routes(app)

    return {"db": db, "app": app, "creadas": creadas}


def cobrar(tienda, price_id, group_id=91, user_id=9101):
    cliente = tienda["app"].test_client()

    return cliente.post(
        "/create-checkout-session",
        data=json.dumps({
            "telegram_id": user_id,
            "plan": price_id,
            "group_id": group_id,
        }),
        content_type="application/json",
    )


def test_what_the_shop_window_advertises_can_actually_be_charged(tienda):
    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    assert ofertas, "el escaparate tiene que ofrecer esta comunidad"

    respuesta = cobrar(tienda, ofertas[0]["price_id"])

    assert respuesta.status_code == 200, (
        f"lo anunciado no se puede cobrar: {respuesta.get_json()}"
    )
    assert respuesta.get_json()["url"].startswith("https://")


def test_an_empty_price_column_does_not_break_the_checkout(tienda):
    """Cadena vacía, que no es NULL: el COALESCE viejo la daba por buena."""

    with tienda["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET stripe_price_id='' WHERE id=991")

    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    assert ofertas[0]["price_id"] == "price_1viejo", (
        "el escaparate cae en price_id cuando el de Stripe está vacío"
    )

    respuesta = cobrar(tienda, ofertas[0]["price_id"])

    assert respuesta.status_code == 200, (
        "el cobro tiene que resolver el precio igual que el escaparate"
    )


def test_the_payment_carries_the_plan_number(tienda):
    """Es la única referencia que sobrevive a un cambio de precio."""

    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    cobrar(tienda, ofertas[0]["price_id"])

    metadata = tienda["creadas"][0]["metadata"]

    assert metadata["plan_id"] == "991"
    assert metadata["group_id"] == "91"


def test_an_invented_price_is_refused(tienda):
    respuesta = cobrar(tienda, "price_que_no_existe")

    assert respuesta.status_code == 400
    assert "Plan inválido" in respuesta.get_json()["error"]


def test_a_plan_from_another_community_is_not_charged_here(tienda):
    """El grupo va en la petición: sin comprobarlo, el precio de una comunidad
    serviría para entrar en otra."""

    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    respuesta = cobrar(tienda, ofertas[0]["price_id"], group_id=92)

    assert respuesta.status_code == 400


def test_the_pending_transaction_is_recorded(tienda):
    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    cobrar(tienda, ofertas[0]["price_id"])

    with tienda["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT status, external_checkout_id FROM payment_transactions "
            "WHERE user_id=9101 AND group_id=91"
        )
        fila = cur.fetchone()

    assert fila is not None, (
        "sin la transacción pendiente no hay recuperación de carrito ni "
        "forma de saber cuánta gente empieza a pagar y no termina"
    )
    assert fila[1] == "cs_test_e2e"


# =========================
# LAS OFERTAS SEMANALES
# =========================
# Una oferta cambia el precio que se anuncia. Si el cobro no la conoce, el botón
# enseña 4,00 y la ruta contesta «Plan inválido» — el fallo de siempre, pero
# estrenado cada lunes.

@pytest.fixture
def con_oferta(tienda, monkeypatch):
    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append({"name": name, "amount_major": amount_major})
        return ("prod_of", "price_de_oferta")

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    with tienda["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET duration_days=7, amount=10 WHERE id=991")

    import weekly_offer_service as ofs

    plan = [p for p in ofs.planes_ofertables(91) if p["id"] == 991][0]
    oferta, _detalle = ofs.crear_oferta(plan, percent=60)

    return {**tienda, "oferta": oferta}


def test_the_offer_price_is_the_one_charged(con_oferta):
    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    assert ofertas[0]["price_id"] == "price_de_oferta", (
        "el escaparate anuncia el precio de oferta"
    )
    assert float(ofertas[0]["amount"]) == pytest.approx(4.00)
    assert ofertas[0]["oferta_percent"] == 60

    respuesta = cobrar(con_oferta, ofertas[0]["price_id"])

    assert respuesta.status_code == 200, (
        f"lo anunciado en oferta no se puede cobrar: {respuesta.get_json()}"
    )

    creada = con_oferta["creadas"][-1]

    assert creada["line_items"][0]["price"] == "price_de_oferta"
    assert creada["metadata"]["offer_percent"] == "60"


def test_the_normal_price_still_works_while_the_offer_lives(con_oferta):
    """La oferta añade un camino, no cierra el de siempre."""

    respuesta = cobrar(con_oferta, "price_1nuevo")

    assert respuesta.status_code == 200


def test_an_offer_that_ended_says_so_instead_of_plan_invalido(con_oferta):
    with con_oferta["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plan_offers SET ends_at = NOW() - INTERVAL '1 minute'"
        )

    respuesta = cobrar(con_oferta, "price_de_oferta")

    assert respuesta.status_code == 400
    assert "oferta ya ha terminado" in respuesta.get_json()["error"], (
        "«Plan inválido» suena a error del bot; y cobrarle el precio normal "
        "sin avisar sería cobrar más de lo que decía el botón"
    )


def test_an_old_button_never_charges_more_than_the_offer(con_oferta):
    """Un botón de hace tres días lleva el precio de tarifa. Con la oferta
    viva, se cobra la oferta: al revés sería cobrar más de lo anunciado."""

    respuesta = cobrar(con_oferta, "price_1nuevo")

    assert respuesta.status_code == 200

    creada = con_oferta["creadas"][-1]

    assert creada["line_items"][0]["price"] == "price_de_oferta", (
        "el identificador viejo entra, pero cobra el precio de hoy"
    )


def test_the_payment_page_says_what_is_being_bought(tienda):
    """La cabecera de esa pantalla la pone Stripe con el nombre fiscal de la
    cuenta —en esta, «TIENDA INFORMATICA»—. Quien llega desde un bot de
    comunidades de Telegram y lee eso cree que se ha equivocado de enlace."""

    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    cobrar(tienda, ofertas[0]["price_id"])

    mensaje = tienda["creadas"][-1]["custom_text"]["submit"]["message"]

    assert "StarsVip" in mensaje, "a qué comunidad entra"
    assert "enlace de entrada" in mensaje, "y qué pasa justo después de pagar"

    for promesa in ("exclusivo", "diario", "mejor", "garantizado"):
        assert promesa not in mensaje.lower(), (
            "aquí no se promete nada sobre el contenido: este código no lo "
            "conoce"
        )


def test_the_trust_line_survives_a_nameless_community(tienda):
    with tienda["db"].conn.cursor() as cur:
        cur.execute("UPDATE groups SET name='' WHERE id=91")

    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    respuesta = cobrar(tienda, ofertas[0]["price_id"])

    assert respuesta.status_code == 200, (
        "un nombre vacío no puede tumbar un cobro"
    )


def test_the_payment_page_is_in_the_buyers_language(tienda, monkeypatch):
    """Quien lee una pantalla de pago en un idioma que no es el suyo desconfía
    justo en el segundo en el que hay que confiar."""

    import i18n_service

    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    monkeypatch.setattr(i18n_service, "load_user_language", lambda uid: "en")

    cobrar(tienda, ofertas[0]["price_id"])

    assert tienda["creadas"][-1]["locale"] == "en"

    # Un idioma que Stripe no conoce no puede tumbar la venta. Con OTRO
    # comprador: el mismo no puede volver a pagar lo que ya está pagando.
    monkeypatch.setattr(i18n_service, "load_user_language", lambda uid: "eu")

    respuesta = cobrar(tienda, ofertas[0]["price_id"], user_id=9102)

    assert respuesta.status_code == 200
    assert tienda["creadas"][-1]["locale"] == "auto"


def test_the_charge_carries_a_readable_concept(tienda):
    """«TIENDA INFORMATICA» a secas no le dice nada a nadie tres semanas
    después, y así nacen las reclamaciones de «yo no he comprado esto»."""

    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=91)

    cobrar(tienda, ofertas[0]["price_id"])

    descripcion = tienda["creadas"][-1]["payment_intent_data"]["description"]

    assert "StarsVip" in descripcion
