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


def test_a_price_id_that_cannot_be_one_is_named_out_loud(monkeypatch):
    """Lo que había de verdad dentro de este campo en producción."""

    llamadas = []

    import stripe

    monkeypatch.setattr(
        stripe.Price, "retrieve",
        lambda pid, *a, **k: llamadas.append(pid) or {"unit_amount": 2900}
    )

    rotos, comprobados = srs.check_stripe_prices([{
        **OFERTA,
        "price_id": "Hola lorrrdd, gracias por tu mensaje.",
    }])

    assert len(rotos) == 1
    assert "no puede serlo" in rotos[0]["detalle"]
    assert "Hola lorrrdd" in rotos[0]["detalle"], (
        "con sus propias palabras: si no, el aviso manda a buscar en Stripe un "
        "precio borrado que nunca existió"
    )
    assert llamadas == [], "no hace falta preguntárselo a Stripe"
    assert comprobados == 0


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


# =========================
# VIGILARLO, NO SOLO MIRARLO AL ARRANCAR
# =========================
# Esto solo corría al arrancar. Con despliegues de vez en cuando, es enterarse
# días después — y así es exactamente como este bot estuvo meses sin poder
# cobrar: nadie lo miró.

def test_it_only_speaks_when_the_state_changes(monkeypatch):
    avisos = []

    monkeypatch.setattr(srs, "_ultimo_estado_del_cobro", {"roto": None})
    monkeypatch.setattr(
        srs, "describe_sale_readiness",
        lambda avisar=True: "🚨 COBRO ROTO — el servidor no contesta"
    )

    import notification_service

    monkeypatch.setattr(
        notification_service, "send_telegram_message",
        lambda token, chat, texto, *a, **k: avisos.append(texto)
    )
    monkeypatch.setenv("ADMIN_ID", "1")

    roto, _linea = srs.vigilar_cobro(avisar=False)

    assert roto is True

    # Segunda pasada con el mismo estado: ni una palabra más.
    antes = len(avisos)

    srs.vigilar_cobro(avisar=False)

    assert len(avisos) == antes, (
        "un aviso cada hora es ruido que se ignora, y así pasa desapercibido "
        "el que importa"
    )


def test_a_recovery_is_only_announced_after_a_break(monkeypatch):
    monkeypatch.setattr(srs, "_ultimo_estado_del_cobro", {"roto": None})
    monkeypatch.setattr(
        srs, "describe_sale_readiness", lambda avisar=True: "Cobro: listo."
    )

    roto, _ = srs.vigilar_cobro(avisar=False)

    assert roto is False


def test_the_watchdog_never_takes_down_what_it_watches(monkeypatch):
    def revienta(avisar=True):
        raise RuntimeError("stripe no contesta")

    monkeypatch.setattr(srs, "describe_sale_readiness", revienta)

    assert srs.vigilar_cobro(avisar=False) == (None, None)


def test_the_watch_is_scheduled_every_hour():
    fuente = open("main.py", encoding="utf-8").read()

    assert "schedule_sale_readiness_watch" in fuente
    assert "vigilar_cobro" in fuente

    pos = fuente.index("sale_readiness_watch_job,")

    assert "interval=3600" in fuente[pos:pos + 200]


# =========================
# EL NOMBRE QUE SE LEE CON LA TARJETA EN LA MANO
# =========================
# La página de pago de producción decía «TIENDA INFORMATICA» a gente que iba a
# pagar por entrar a una comunidad de Telegram. El cobro funcionaba: lo que
# fallaba era que el comprador leía el nombre de otro negocio en el único
# segundo en el que puede arrepentirse. Eso no da error, no sale en ningún log y
# desde dentro del bot no lo ve nadie.

def _cuenta(publico=None, extracto=None, marca=None):

    return {
        "business_profile": {"name": publico},
        "settings": {
            "payments": {"statement_descriptor": extracto},
            "dashboard": {"display_name": marca},
        },
    }


def test_the_buyer_reads_the_statement_descriptor_when_there_is_no_public_name():
    """Es la cadena de reservas de Stripe, y es de donde salió el problema."""

    assert srs.nombre_que_vera_el_comprador(
        _cuenta(publico=None, extracto="TIENDA INFORMATICA")
    ) == "TIENDA INFORMATICA"

    assert srs.nombre_que_vera_el_comprador(
        _cuenta(publico="TheStarVip", extracto="TIENDA INFORMATICA")
    ) == "TheStarVip", "el nombre público manda sobre el del extracto"


def test_a_name_from_another_business_is_reported(monkeypatch):
    monkeypatch.setattr(srs, "_leer_cuenta_de_stripe", lambda: _cuenta(
        extracto="TIENDA INFORMATICA", marca="thestarvip.online"
    ))

    ok, detalle = srs.check_nombre_de_la_pagina_de_pago()

    assert ok is False
    assert "TIENDA INFORMATICA" in detalle
    assert "thestarvip.online" in detalle
    assert "se va" in detalle, (
        "el aviso tiene que decir qué se pierde, no solo qué está distinto"
    )


def test_the_same_business_written_two_ways_is_not_an_alarm(monkeypatch):
    monkeypatch.setattr(srs, "_leer_cuenta_de_stripe", lambda: _cuenta(
        publico="TheStarVip", marca="thestarvip.online"
    ))

    ok, _ = srs.check_nombre_de_la_pagina_de_pago()

    assert ok is True, (
        "«TheStarVip» y «thestarvip.online» son el mismo negocio; un aviso "
        "que salta con esto se ignora y se lleva por delante al de verdad"
    )


def test_a_network_failure_is_not_a_wrong_name(monkeypatch):

    def revienta():
        raise RuntimeError("timeout")

    monkeypatch.setattr(srs, "_leer_cuenta_de_stripe", revienta)

    ok, _ = srs.check_nombre_de_la_pagina_de_pago()

    assert ok is True, "sin poder preguntar no se acusa a nadie"


def test_without_credentials_it_stays_quiet(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")

    ok, _ = srs.check_nombre_de_la_pagina_de_pago()

    assert ok is True


def test_the_wrong_name_is_a_warning_and_not_a_broken_checkout(monkeypatch):
    """Se cobra perfectamente: decir «COBRO ROTO» mandaría a mirar donde no es."""

    monkeypatch.setenv("SERVER_URL", "https://ejemplo.test")
    monkeypatch.setattr(srs.requests, "post", lambda url, **k: FakeResp(400))
    monkeypatch.setattr(srs, "check_stripe_prices", lambda ofertas=None: ([], 2))
    monkeypatch.setattr(
        srs, "check_nombre_de_la_pagina_de_pago",
        lambda: (False, "la página de pago dice «TIENDA INFORMATICA»")
    )

    linea = srs.describe_sale_readiness(avisar=False)

    assert linea.startswith("Cobro: listo")
    assert "COBRO ROTO" not in linea
    assert "TIENDA INFORMATICA" in linea, (
        "y aun así tiene que salir: es dinero que se pierde en silencio"
    )


def test_asking_stripe_has_a_deadline(monkeypatch):
    """Esto corre en el ARRANQUE. Sin plazo, el bot se queda parado esperando.

    La librería de Stripe espera hasta 80 segundos por defecto, y son 80
    segundos de bot sin atender a nadie por una comprobación que solo mira un
    nombre. Por eso se pregunta a mano.
    """

    llamadas = []

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_de_mentira")

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    def falso_get(url, **kwargs):
        llamadas.append(kwargs)
        return Resp()

    monkeypatch.setattr(srs.requests, "get", falso_get)

    srs._leer_cuenta_de_stripe()

    assert llamadas, "tiene que preguntar"
    assert llamadas[0].get("timeout"), (
        "una petición sin plazo en el arranque puede dejar el bot colgado"
    )


# =========================
# UN NOMBRE DISTINTO NO SIEMPRE ES UN DESCUIDO
# =========================
# Quien vende acceso a una comunidad privada puede querer A PROPÓSITO que en el
# extracto del banco de su comprador salga algo neutro. Eso es una decisión
# suya, no una avería. Sin poder decirlo, este aviso saltaría cada hora para
# siempre por algo elegido — y un aviso que se sabe que hay que ignorar es el
# que hace que se ignoren todos.

def test_a_chosen_name_is_not_an_alarm(monkeypatch):
    monkeypatch.setenv("NOMBRE_DE_PAGO_ESPERADO", "TIENDA INFORMATICA")
    monkeypatch.setattr(srs, "_leer_cuenta_de_stripe", lambda: _cuenta(
        extracto="TIENDA INFORMATICA", marca="thestarvip.online"
    ))

    ok, detalle = srs.check_nombre_de_la_pagina_de_pago()

    assert ok is True, (
        "el dueño ha dicho que quiere ese nombre; repetírselo cada hora es "
        "enseñarle a ignorar los avisos"
    )
    assert "TIENDA INFORMATICA" in detalle


def test_with_a_chosen_name_the_account_name_stops_mattering(monkeypatch):
    """La decisión ya está tomada: la referencia es lo que se pidió."""

    monkeypatch.setenv("NOMBRE_DE_PAGO_ESPERADO", "TIENDA INFORMATICA")
    monkeypatch.setattr(srs, "_leer_cuenta_de_stripe", lambda: _cuenta(
        extracto="TIENDA INFORMATICA", marca="cualquier-otra-cosa.com"
    ))

    ok, _ = srs.check_nombre_de_la_pagina_de_pago()

    assert ok is True


def test_someone_changing_it_behind_your_back_is_still_reported(monkeypatch):
    """Justo por eso vale la pena declararlo: se vigila que siga estando."""

    monkeypatch.setenv("NOMBRE_DE_PAGO_ESPERADO", "TIENDA INFORMATICA")
    monkeypatch.setattr(srs, "_leer_cuenta_de_stripe", lambda: _cuenta(
        extracto="OTRA COSA", marca="thestarvip.online"
    ))

    ok, detalle = srs.check_nombre_de_la_pagina_de_pago()

    assert ok is False
    assert "OTRA COSA" in detalle
    assert "TIENDA INFORMATICA" in detalle
    assert "cambiado" in detalle


def test_without_the_variable_nothing_changes(monkeypatch):
    monkeypatch.delenv("NOMBRE_DE_PAGO_ESPERADO", raising=False)
    monkeypatch.setattr(srs, "_leer_cuenta_de_stripe", lambda: _cuenta(
        extracto="TIENDA INFORMATICA", marca="thestarvip.online"
    ))

    ok, _ = srs.check_nombre_de_la_pagina_de_pago()

    assert ok is False, "sin declarar nada, sigue siendo un descuadre"


def test_it_is_read_on_every_check(monkeypatch):
    """Cambiarlo en el servidor tiene que valer sin reiniciar el bot."""

    monkeypatch.setattr(srs, "_leer_cuenta_de_stripe", lambda: _cuenta(
        extracto="TIENDA INFORMATICA", marca="thestarvip.online"
    ))

    monkeypatch.delenv("NOMBRE_DE_PAGO_ESPERADO", raising=False)

    assert srs.check_nombre_de_la_pagina_de_pago()[0] is False

    monkeypatch.setenv("NOMBRE_DE_PAGO_ESPERADO", "TIENDA INFORMATICA")

    assert srs.check_nombre_de_la_pagina_de_pago()[0] is True


# =========================
# TRES PLANES A LA VENTA, UN PRECIO COMPROBADO
# =========================
# El log de producción decía «Cobro: listo (1 precio(s) de Stripe verificado(s))»
# con TRES planes vendibles: 9, 15 y 29 €. El diagnóstico miraba el escaparate, y
# el escaparate enseña UNA entrada por comunidad, la más barata. Un precio roto
# en los otros dos solo se descubre con el comprador ya decidido — justo el
# fallo para el que existe este fichero.

@pytest.fixture
def tres_planes(clean_db, monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible) VALUES (91, 'StarsVip', -1091, TRUE, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(911, 91, 'Acceso 7 días',   'price_a', 'price_a', 7,   9, 'EUR', TRUE), "
            "(912, 91, 'Acceso 30 días',  'price_b', 'price_b', 30, 15, 'EUR', TRUE), "
            "(913, 91, 'Acceso 360 días', 'price_c', 'price_c', 360, 29, 'EUR', TRUE)"
        )

    return db


def test_every_price_a_buyer_can_reach_is_checked(tres_planes):
    cobrables = srs.todo_lo_que_se_puede_cobrar()

    ids = {o.get("price_id") for o in cobrables}

    assert {"price_a", "price_b", "price_c"} <= ids, (
        "el de 15 y el de 29 también se pagan; nadie los miraba"
    )


def test_the_same_price_is_not_checked_twice(tres_planes):
    cobrables = srs.todo_lo_que_se_puede_cobrar()

    ids = [o.get("price_id") for o in cobrables]

    assert len(ids) == len(set(ids)), (
        "el escaparate y la lista de planes se solapan en el más barato"
    )


def test_a_broken_price_on_the_expensive_plan_is_reported(tres_planes,
                                                          monkeypatch):
    import stripe

    class NoExiste(Exception):
        pass

    def falso_retrieve(price_id, **kwargs):

        if price_id == "price_c":
            raise stripe.error.InvalidRequestError(
                f"No such price: '{price_id}'", None
            )

        return {"unit_amount": 900 if price_id == "price_a" else 1500}

    monkeypatch.setattr(stripe.Price, "retrieve", staticmethod(falso_retrieve))

    rotos, comprobados = srs.check_stripe_prices()

    assert comprobados >= 2
    assert any(r.get("price_id") == "price_c" for r in rotos), (
        "el plan de 29 estaba roto y el diagnóstico decía «listo»"
    )


def test_the_alert_says_which_plan_is_broken(tres_planes):
    cobrables = srs.todo_lo_que_se_puede_cobrar()

    extras = [o for o in cobrables if o.get("price_id") in ("price_b", "price_c")]

    assert extras

    for extra in extras:
        assert "StarsVip" in extra["nombre"]
        assert "Acceso" in extra["nombre"], (
            "«StarsVip» a secas no dice CUÁL de los tres está roto"
        )


def test_each_price_is_matched_against_its_own_amount(tres_planes, monkeypatch):
    """El de 29 comparado contra los 9 del escaparate sería un falso positivo."""

    import stripe

    monkeypatch.setattr(
        stripe.Price, "retrieve",
        staticmethod(lambda price_id, **k: {
            "unit_amount": {"price_a": 900, "price_b": 1500, "price_c": 2900}[price_id]
        })
    )

    rotos, _comprobados = srs.check_stripe_prices()

    assert rotos == [], "los tres cuadran con SU importe"
