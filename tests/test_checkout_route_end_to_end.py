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
