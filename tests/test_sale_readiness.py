"""
¿Puede el bot cobrar AHORA MISMO? La pregunta que nadie hacía.

Simulando el camino de un comprador con los datos de producción me encontré con
que el bot no habla con Stripe para crear el enlace de pago: hace una petición
HTTP A SU PROPIO SERVIDOR (SERVER_URL/create-checkout-session). Si esa dirección
está vacía, apunta a un dominio viejo o el servidor no contesta, TODAS las
compras mueren con «No he podido abrir la pasarela de pago» y lo único que queda
es una línea en los logs.

Y encima la dirección que se ve en el log de arranque sale de
RAILWAY_PUBLIC_DOMAIN, no de SERVER_URL: ver un dominio correcto ahí NO prueba
que el de cobrar lo sea.

El segundo punto ciego es el precio: un price_id borrado, o creado en la cuenta
de test en vez de la de producción, revienta el checkout con el comprador ya
decidido.

Los dos fallan en silencio y los dos se parecen desde fuera a «la gente no
compra».
"""

import pytest

import sale_readiness_service as srs


class FakeResp:
    def __init__(self, code):
        self.status_code = code


def test_without_server_url_nothing_can_be_charged(monkeypatch):
    monkeypatch.delenv("SERVER_URL", raising=False)

    ok, detalle = srs.check_checkout_endpoint()

    assert ok is False
    assert "SERVER_URL" in detalle
    assert "ninguna compra puede terminar" in detalle, (
        "hay que decir la consecuencia, no solo que falta una variable"
    )


def test_the_expected_answer_is_the_400_of_an_impossible_plan(monkeypatch):
    """La sonda no crea nada en Stripe: pide un plan que no existe."""

    llamadas = []

    def falso_post(url, **kwargs):
        llamadas.append((url, kwargs.get("json")))
        return FakeResp(400)

    monkeypatch.setenv("SERVER_URL", "https://ejemplo.test")
    monkeypatch.setattr(srs.requests, "post", falso_post)

    ok, detalle = srs.check_checkout_endpoint()

    assert ok is True
    assert "responde correctamente" in detalle

    url, payload = llamadas[0]

    assert url == "https://ejemplo.test/create-checkout-session"
    assert payload["plan"] == srs.PROBE_PLAN, (
        "la sonda tiene que usar un plan imposible: con uno real crearía "
        "sesiones de pago de mentira en Stripe"
    )


def test_a_404_says_that_the_address_is_not_this_bot(monkeypatch):
    monkeypatch.setenv("SERVER_URL", "https://dominio-viejo.test")
    monkeypatch.setattr(srs.requests, "post", lambda url, **k: FakeResp(404))

    ok, detalle = srs.check_checkout_endpoint()

    assert ok is False
    assert "no es la de este bot" in detalle
    assert "SERVER_URL" in detalle


def test_stripe_disabled_is_reported_as_what_it_is(monkeypatch):
    monkeypatch.setenv("SERVER_URL", "https://ejemplo.test")
    monkeypatch.setattr(srs.requests, "post", lambda url, **k: FakeResp(503))

    ok, detalle = srs.check_checkout_endpoint()

    assert ok is False
    assert "Stripe está deshabilitado" in detalle


def test_an_unreachable_server_is_a_broken_checkout(monkeypatch):
    def explota(url, **kwargs):
        raise OSError("Name or service not known")

    monkeypatch.setenv("SERVER_URL", "https://no-existe.test")
    monkeypatch.setattr(srs.requests, "post", explota)

    ok, detalle = srs.check_checkout_endpoint()

    assert ok is False
    assert "No he podido abrir la pasarela de pago" in detalle, (
        "hay que enseñar el mensaje EXACTO que ve el comprador, para poder "
        "atar el síntoma con la causa"
    )


# =========================
# EL PRECIO QUE NO EXISTE
# =========================

OFERTA = {
    "group_id": 51,
    "nombre": "StarsVip",
    "provider": "stripe",
    "price_id": "price_borrado",
}


def test_a_price_stripe_denies_is_reported(monkeypatch):
    import stripe

    def no_existe(price_id):
        raise Exception("No such price: 'price_borrado'")

    monkeypatch.setattr(stripe.Price, "retrieve", no_existe)

    rotos, comprobados = srs.check_stripe_prices([OFERTA])

    assert comprobados == 1
    assert len(rotos) == 1
    assert rotos[0]["nombre"] == "StarsVip"


def test_a_network_glitch_does_not_condemn_a_good_price(monkeypatch):
    """Apagar la tienda por un timeout es peor que el fallo que se busca."""

    import stripe

    def timeout(price_id):
        raise Exception("Request timed out")

    monkeypatch.setattr(stripe.Price, "retrieve", timeout)

    rotos, comprobados = srs.check_stripe_prices([OFERTA])

    assert comprobados == 1
    assert rotos == [], (
        "solo la negativa explícita de Stripe cuenta como precio inexistente"
    )


def test_a_good_price_is_silence(monkeypatch):
    import stripe

    monkeypatch.setattr(stripe.Price, "retrieve", lambda price_id: {"id": price_id})

    rotos, comprobados = srs.check_stripe_prices([OFERTA])

    assert (rotos, comprobados) == ([], 1)


def test_providers_that_are_not_stripe_are_not_asked_to_stripe(monkeypatch):
    """A Stripe no se le pregunta por un plan de PayPal..."""

    import stripe

    def no_deberia_llamarse(price_id):
        raise AssertionError("no se pregunta a Stripe por un plan de PayPal")

    monkeypatch.setattr(stripe.Price, "retrieve", no_deberia_llamarse)

    _rotos, comprobados = srs.check_stripe_prices([
        {**OFERTA, "provider": "paypal"}
    ])

    assert comprobados == 0, "no cuenta como precio de Stripe comprobado"


def test_but_the_other_provider_is_checked_instead_of_ignored(monkeypatch):
    """...pero SÍ se comprueba el suyo, que era el agujero.

    Una comunidad puede estar en el escaparate con su precio y su botón y cobrar
    por un método apagado o mal configurado. Desde fuera se ve exactamente igual
    que una que vende bien, y el diagnóstico solo sabía de Stripe: se callaba
    justo el caso que impide vender.
    """

    monkeypatch.delenv("ENABLE_PAYPAL_PAYMENTS", raising=False)
    monkeypatch.setenv("ENABLE_PAYPAL_PAYMENTS", "0")

    rotos, _c = srs.check_stripe_prices([{**OFERTA, "provider": "paypal"}])

    assert len(rotos) == 1
    assert "DESHABILITADO" in rotos[0]["detalle"]
    assert "no puede pagar" in rotos[0]["detalle"]


def test_a_paypal_offer_with_broken_credentials_is_reported(monkeypatch):
    monkeypatch.setenv("ENABLE_PAYPAL_PAYMENTS", "1")

    import payment_providers.paypal_provider as pp

    def credenciales_malas(group_id):
        raise ValueError("El webhook_id de PayPal no puede ser un webhook_id.")

    monkeypatch.setattr(pp, "get_group_paypal_credentials", credenciales_malas)

    rotos, _c = srs.check_stripe_prices([{**OFERTA, "provider": "paypal"}])

    assert len(rotos) == 1
    assert "su configuración no sirve" in rotos[0]["detalle"]
    assert "webhook_id" in rotos[0]["detalle"]


def test_a_stripe_offer_without_a_price_id_is_reported(monkeypatch):
    """El caso de producción: en el escaparate y sin con qué cobrar."""

    rotos, _c = srs.check_stripe_prices([{**OFERTA, "price_id": None}])

    assert len(rotos) == 1
    assert "no tiene identificador de precio" in rotos[0]["detalle"]
    assert "no se puede ni empezar" in rotos[0]["detalle"]


# =========================
# LA LÍNEA DEL ARRANQUE
# =========================

def test_when_everything_works_it_says_so(monkeypatch):
    monkeypatch.setenv("SERVER_URL", "https://ejemplo.test")
    monkeypatch.setattr(srs.requests, "post", lambda url, **k: FakeResp(400))
    monkeypatch.setattr(srs, "check_stripe_prices", lambda ofertas=None: ([], 2))

    linea = srs.describe_sale_readiness(avisar=False)

    assert linea.startswith("Cobro: listo")
    assert "2 precio(s)" in linea


def test_a_broken_checkout_shouts_and_reaches_the_admin(monkeypatch):
    avisos = []

    monkeypatch.delenv("SERVER_URL", raising=False)
    monkeypatch.setattr(srs, "check_stripe_prices", lambda ofertas=None: ([], 0))
    monkeypatch.setattr(srs, "log_event",
                        lambda *a, **k: avisos.append(("log", k)))

    import notification_service

    monkeypatch.setattr(
        notification_service, "send_telegram_message",
        lambda token, chat_id, texto, **k: avisos.append(("aviso", texto))
    )

    linea = srs.describe_sale_readiness(avisar=True)

    assert "COBRO ROTO" in linea

    severidades = [k.get("severity") for tipo, k in avisos if tipo == "log"]

    assert "critical" in severidades, "no poder cobrar no es un warning"


def test_the_startup_calls_it_wrapped():
    fuente = open("main.py", encoding="utf-8").read()

    assert "describe_sale_readiness" in fuente

    pos = fuente.index("describe_sale_readiness")

    assert "try:" in fuente[pos - 400:pos], (
        "una petición de red en el arranque va envuelta o puede tumbar el bot"
    )


# =========================
# ANUNCIAR UN PRECIO Y COBRAR OTRO
# =========================
# El importe vive en dos sitios: plans.amount (lo que se enseña) y el precio de
# Stripe (lo que se cobra). El asistente del panel deja cambiar uno y pide el
# otro a mano. Nada comprobaba que coincidieran.

def _oferta(amount, currency="EUR"):
    return {
        "group_id": 51,
        "nombre": "StarsVip",
        "provider": "stripe",
        "price_id": "price_x",
        "amount": amount,
        "currency": currency,
    }


def test_a_price_that_charges_something_else_is_caught(monkeypatch):
    import stripe

    # Se anuncian 29 EUR y el precio de Stripe dice 7 EUR.
    monkeypatch.setattr(
        stripe.Price, "retrieve",
        lambda price_id: {"id": price_id, "unit_amount": 700}
    )

    rotos, comprobados = srs.check_stripe_prices([_oferta(29)])

    assert comprobados == 1
    assert len(rotos) == 1
    assert rotos[0]["descuadre"] is True
    assert "29.00 EUR" in rotos[0]["detalle"]
    assert "7.00 EUR" in rotos[0]["detalle"]


def test_matching_amounts_are_silence(monkeypatch):
    import stripe

    monkeypatch.setattr(
        stripe.Price, "retrieve",
        lambda price_id: {"id": price_id, "unit_amount": 2900}
    )

    assert srs.check_stripe_prices([_oferta(29)]) == ([], 1)


def test_the_comparison_is_done_in_cents_not_units(monkeypatch):
    """El error clásico: comparar 29 con 2900 y ver un descuadre inventado."""

    import stripe

    monkeypatch.setattr(
        stripe.Price, "retrieve",
        lambda price_id: {"id": price_id, "unit_amount": 2900}
    )

    rotos, _c = srs.check_stripe_prices([_oferta(29.00)])

    assert rotos == [], "29 EUR y 2900 céntimos son lo mismo"


def test_the_alert_says_it_ends_in_a_refund(monkeypatch):
    avisos = []

    monkeypatch.setenv("SERVER_URL", "https://ejemplo.test")
    monkeypatch.setattr(srs.requests, "post", lambda url, **k: FakeResp(400))
    monkeypatch.setattr(
        srs, "check_stripe_prices",
        lambda ofertas=None: ([{
            "group_id": 51, "nombre": "StarsVip", "price_id": "price_x",
            "detalle": "se anuncia 29.00 EUR y Stripe cobraría 7.00 EUR",
            "descuadre": True,
        }], 1)
    )
    monkeypatch.setattr(srs, "log_event", lambda *a, **k: avisos.append(k))

    linea = srs.describe_sale_readiness(avisar=False)

    assert "COBRO ROTO" in linea
    assert "anuncia un precio y Stripe cobraría otro" in linea
    assert "devolución garantizada" in linea
