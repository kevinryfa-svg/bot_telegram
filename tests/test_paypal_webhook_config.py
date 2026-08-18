"""
La autoconfiguración del webhook de PayPal: el seguro que ya salvó a Stripe.

Un webhook sin BILLING.SUBSCRIPTION.CANCELLED pierde las bajas en silencio;
sin PAYMENT.SALE.COMPLETED pierde LOS COBROS. En Stripe esta misma
comprobación destapó en producción que faltaban 8 de 9 eventos.

Aquí los dobles de red son dicts planos A PROPÓSITO: la capa de PayPal es
HTTP directa (requests → JSON), así que los dicts son la forma real de
producción, no un doble permisivo.
"""

import pytest

import paypal_webhook_config_service as pwc
import payment_providers.paypal_provider as pp


class FakeResp:
    def __init__(self, data, code=200):
        self._d, self.status_code = data, code

    def json(self):
        return self._d


@pytest.fixture
def red(monkeypatch):
    """Un webhook de PayPal simulado con eventos configurables."""

    estado = {
        "eventos": [{"name": e} for e in pwc.REQUIRED_EVENTS],
        "patches": [],
        "fallar_patch": False,
    }

    def red_get(url, *a, **k):
        if "/v1/notifications/webhooks/" in url:
            return FakeResp({
                "id": url.rsplit("/", 1)[-1],
                "event_types": estado["eventos"],
            })
        raise AssertionError(f"GET inesperado a {url}")

    def red_patch(url, *a, **k):
        if estado["fallar_patch"]:
            return FakeResp({"name": "UNPROCESSABLE_ENTITY"}, code=422)
        estado["patches"].append((url, k.get("json")))
        return FakeResp({}, code=200)

    monkeypatch.setattr(pp.requests, "get", red_get)
    monkeypatch.setattr(pp.requests, "patch", red_patch)

    return estado


def test_when_everything_is_subscribed_nothing_is_touched(red):
    r = pwc.revisar_webhook("https://api.test", "tok", "WH-1", "prueba")

    assert r["estado"] == "ok"
    assert not red["patches"]


def test_missing_events_are_added_without_removing_foreign_ones(red):
    """La regla de oro, la misma que en Stripe: unión, nunca resta."""

    red["eventos"] = [
        {"name": "PAYMENT.SALE.COMPLETED"},
        {"name": "CUSTOMER.DISPUTE.CREATED"},   # del propietario, ajeno
    ]

    r = pwc.revisar_webhook("https://api.test", "tok", "WH-1", "prueba")

    assert r["estado"] == "arreglado"
    assert "BILLING.SUBSCRIPTION.CANCELLED" in r["faltaban"]

    url, cuerpo = red["patches"][0]
    assert url.endswith("/v1/notifications/webhooks/WH-1")

    nombres = [e["name"] for e in cuerpo[0]["value"]]

    for evento in pwc.REQUIRED_EVENTS:
        assert evento in nombres, f"falta {evento} en la suscripción final"

    assert "CUSTOMER.DISPUTE.CREATED" in nombres, (
        "el PATCH reemplaza la lista entera: quitar lo ajeno es des-suscribirlo"
    )


def test_a_wildcard_webhook_is_already_complete(red):
    red["eventos"] = [{"name": "*"}]

    r = pwc.revisar_webhook("https://api.test", "tok", "WH-1", "prueba")

    assert r["estado"] == "ok"
    assert not red["patches"]


def test_a_failed_fix_is_reported_not_silenced(red):
    red["eventos"] = [{"name": "PAYMENT.SALE.COMPLETED"}]
    red["fallar_patch"] = True

    r = pwc.revisar_webhook("https://api.test", "tok", "WH-1", "prueba")

    assert r["estado"] == "fallo_arreglando"
    assert r["faltaban"], "la lista de lo que falta es lo que permite arreglarlo a mano"


def test_an_unreadable_webhook_is_flagged(red, monkeypatch):
    monkeypatch.setattr(
        pp.requests, "get",
        lambda url, *a, **k: FakeResp({"name": "INVALID_RESOURCE_ID"}, code=404)
    )

    r = pwc.revisar_webhook("https://api.test", "tok", "WH-MAL", "prueba")

    assert r["estado"] == "ilegible"


def test_autofix_can_be_disabled(red, monkeypatch):
    monkeypatch.setattr(pwc, "AUTOFIX_ENABLED", False)

    red["eventos"] = [{"name": "PAYMENT.SALE.COMPLETED"}]

    r = pwc.revisar_webhook("https://api.test", "tok", "WH-1", "prueba")

    assert r["estado"] == "faltan_sin_arreglar"
    assert not red["patches"], "con el autofix apagado solo se avisa"


# =========================
# LA PASADA COMPLETA
# =========================

def test_the_sweep_covers_platform_and_every_configured_group(red, clean_db,
                                                              monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (92, 'VIP Config', -1092, TRUE)"
        )
        cur.execute(
            "INSERT INTO group_payment_provider_configs "
            "(owner_user_id, group_id, provider, is_enabled) "
            "VALUES (777, 92, 'paypal', TRUE)"
        )
        # Una desactivada NO se revisa.
        cur.execute(
            "INSERT INTO group_payment_provider_configs "
            "(owner_user_id, group_id, provider, is_enabled) "
            "VALUES (778, 92, 'revolut', TRUE)"
        )

    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-PLATAFORMA")
    monkeypatch.setattr(pp, "get_paypal_access_token", lambda: "tok")
    monkeypatch.setattr(pp, "get_paypal_base_url", lambda: "https://api.test")
    monkeypatch.setattr(pp, "get_group_paypal_credentials", lambda gid: {
        "client_id": "cid", "client_secret": "sec", "mode": "sandbox",
        "owner_user_id": 777, "webhook_id": f"WH-GRUPO-{gid}",
        "provider_config_id": 1,
    })
    monkeypatch.setattr(pp, "get_paypal_access_token_for_credentials",
                        lambda *a, **k: "tok")
    monkeypatch.setattr(pp, "get_paypal_base_url_for_mode",
                        lambda mode: "https://api.test")

    avisos = []
    monkeypatch.setattr(
        "notification_service.send_telegram_message",
        lambda token, chat, text, **k: avisos.append((chat, text))
    )

    red["eventos"] = [{"name": "PAYMENT.SALE.COMPLETED"}]

    resultados = pwc.verify_paypal_webhook_events(notify=True, token_bot="tok-bot")

    etiquetas = {r["etiqueta"] for r in resultados}
    assert etiquetas == {"plataforma", "grupo 92"}

    assert all(r["estado"] == "arreglado" for r in resultados)
    assert len(red["patches"]) == 2

    # El propietario del grupo se entera de lo que el bot arregló por él.
    assert any(c == 777 and "activado" in t for c, t in avisos)


def test_a_broken_group_does_not_stop_the_sweep(red, clean_db, monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (92, 'VIP Config', -1092, TRUE)"
        )
        cur.execute(
            "INSERT INTO group_payment_provider_configs "
            "(owner_user_id, group_id, provider, is_enabled) "
            "VALUES (777, 92, 'paypal', TRUE)"
        )

    monkeypatch.delenv("PAYPAL_WEBHOOK_ID", raising=False)

    def credenciales_rotas(gid):
        raise RuntimeError("configuración corrupta")

    monkeypatch.setattr(pp, "get_group_paypal_credentials", credenciales_rotas)

    resultados = pwc.verify_paypal_webhook_events(notify=False)

    assert resultados == [], "el grupo roto no puede tumbar la pasada"


# =========================
# PARIDAD CON EL PROCESADOR
# =========================

def test_every_event_the_processor_handles_is_in_the_required_list():
    """
    Si alguien enseña al procesador un evento nuevo y no lo añade aquí, el
    webhook de producción no lo recibirá nunca: verde en tests, mudo en real.
    """

    source = open("payment_providers/paypal_provider.py", encoding="utf-8").read()

    import re

    en_codigo = set(re.findall(
        r'"((?:PAYMENT|BILLING)\.[A-Z.]+)"', source
    ))

    faltan = sorted(en_codigo - set(pwc.REQUIRED_EVENTS))

    assert not faltan, (
        f"el procesador atiende {faltan} pero el webhook no los suscribe"
    )


# =========================
# EL WEBHOOK_ID CON LA FORMA EQUIVOCADA
# =========================
# El fallo que había en producción: la casilla del webhook_id guardaba un valor
# con forma de client_id. Solo se comprobaba que NO estuviera vacía. Con eso el
# cobro salía, PayPal lo aceptaba, y la verificación de la firma del webhook
# contestaba HTTP 400: dinero cobrado, acceso no entregado, y ninguna traza que
# lo dijera. Los dos extremos del arreglo son negarse a cobrar y decir cuál es
# el campo.

CLIENT_ID_DE_VERDAD = (
    "AeA1QIZXlYRHqCv1cE-3Xy9pQ_kM7bNvB2wTqLsRfGhJkLmNoPqRsTuVwXyZ1234567890abcd"
)


def test_a_real_webhook_id_is_accepted():
    """Lo primero que hay que probar es que NO se rechaza lo bueno.

    Un filtro que deja a un propietario sin poder cobrar hace más daño que el
    fallo que evita, así que se aceptan las formas que PayPal usa y también el
    guion, que no puedo afirmar que no use nunca.
    """

    for bueno in ("0EH40505U7160970P", "1JE4291016473214C",
                  "5ML55555XX555555L", "WH-1", "WH_TEST_1"):

        assert pp.parece_webhook_id_de_paypal(bueno) is True, bueno


def test_what_cannot_be_a_webhook_id_is_rejected():
    for malo in (CLIENT_ID_DE_VERDAD,
                 "https://api.paypal.com/v1/notifications/webhooks/X",
                 "WH-1 WH-2", "correo@ejemplo.com", "", "   ", None):

        assert pp.parece_webhook_id_de_paypal(malo) is False, repr(malo)


def test_the_check_names_the_field_instead_of_blaming_the_credentials(red):
    """«No se ha podido leer la configuración» manda a revisar TODO.

    El problema es un campo y se sabe cuál: decirlo es la diferencia entre un
    arreglo de un minuto y una tarde revisando credenciales que están bien.
    """

    r = pwc.revisar_webhook(
        "https://api.test", "tok", CLIENT_ID_DE_VERDAD, "prueba"
    )

    assert r["estado"] == "forma_invalida"
    assert not red["patches"], (
        "con un webhook_id imposible no se gasta ni una llamada a PayPal"
    )


def test_the_owner_is_told_it_would_charge_without_delivering(red, monkeypatch):
    avisos = []

    monkeypatch.setattr(
        pwc, "log_event", lambda *a, **k: avisos.append(("log", a, k))
    )

    import notification_service

    monkeypatch.setattr(
        notification_service, "send_telegram_message",
        lambda token, chat_id, texto, **k: avisos.append(("aviso", texto))
    )

    pwc.notificar_resultado(
        {"etiqueta": "grupo 7", "estado": "forma_invalida", "faltaban": []},
        owner_user_id=99, token_bot="T"
    )

    textos = [t for tipo, t in ((a[0], a[1]) for a in avisos) if tipo == "aviso"]

    assert textos, "el propietario tiene que enterarse"
    assert "no se entregaría" in textos[0], (
        "hay que decir la consecuencia en dinero, no solo que hay un error"
    )
    assert "Webhooks" in textos[0], "y dónde está el valor correcto"

    severidades = [
        k.get("severity") for tipo, a, k in
        ((x[0], x[1], x[2]) for x in avisos if x[0] == "log")
    ]

    assert "critical" in severidades, (
        "cobrar sin entregar no es un warning"
    )


def test_the_charge_is_refused_before_taking_the_money():
    """El extremo que de verdad protege el dinero: no cobrar."""

    fuente = open("payment_providers/paypal_provider.py", encoding="utf-8").read()

    pos = fuente.index("parece_webhook_id_de_paypal(credentials.get")
    trozo = fuente[pos:pos + 1500]

    assert "PaymentProviderUnavailable" in trozo, (
        "sin excepción aquí, el cobro sigue adelante y el acceso no llega"
    )
    assert "no se cobra" in trozo


def test_the_wizard_refuses_to_save_it():
    """Y el sitio donde se comete el error es la casilla del asistente."""

    fuente = open("owner_payment_callbacks.py", encoding="utf-8").read()

    assert "parece_webhook_id_de_paypal" in fuente

    pos = fuente.index("if payload.get(\"webhook_id\") and not parece_webhook_id_de_paypal")

    # Se busca el cifrado que viene DESPUÉS de la comprobación: el fichero
    # guarda también Stripe y Revolut, y su encrypt_provider_config aparece
    # antes en el texto sin tener nada que ver con esto.
    assert pos < fuente.index("encrypt_provider_config", pos), (
        "la comprobación va ANTES de guardar: guardarlo y avisar después deja "
        "el valor malo dentro"
    )

    trozo = fuente[pos:pos + 1800]

    assert "0EH40505U7160970P" in trozo, "hay que enseñarle un ejemplo bueno"
    assert "Webhooks" in trozo, "y dónde encontrarlo"
