"""
Stripe solo manda los eventos que están marcados en el endpoint.

Ese es el fallo silencioso más desagradable de todo el camino del pago: el código
puede atender charge.refunded perfectamente y no enterarse nunca de una
devolución porque el evento no está activado. No hay error, no hay traza, no hay
nada. Una función entera queda muerta sin que nada lo delate.

Lo delicado de arreglarlo automáticamente es que se está modificando la
configuración de una cuenta de cobro real: tocar el endpoint equivocado, o
quitarle un evento que alguien puso a mano, sería mucho peor que no hacer nada.
Casi todas las pruebas de aquí son sobre eso.
"""

import re

import pytest

import stripe_webhook_config_service as swc


# =========================
# QUE LAS DOS LISTAS NO SE SEPAREN
# =========================

def events_handled_in_the_code():
    """Los eventos que stripe_handler.py compara de verdad."""

    source = open("stripe_handler.py", encoding="utf-8").read()

    # Solo dentro del webhook: fuera hay cadenas que no son tipos de evento.
    webhook = source[source.index("def stripe_webhook"):]

    return {
        evento for evento in re.findall(r'"([a-z_]+(?:\.[a-z_]+)+)"', webhook)
        if evento.count(".") >= 1
        and not evento.endswith(".py")
        and evento.split(".")[0] in (
            "checkout", "customer", "invoice", "charge", "payment_intent"
        )
    }


def test_every_event_the_code_handles_is_requested_from_stripe():
    """
    Si se atiende un evento y no se pide, Stripe no lo manda nunca. Es
    exactamente el fallo que había con las devoluciones.
    """

    faltan = events_handled_in_the_code() - set(swc.REQUIRED_EVENTS)

    assert not faltan, (
        f"el código atiende estos eventos pero no se piden a Stripe: {sorted(faltan)}"
    )


def test_no_event_is_requested_without_anyone_handling_it():
    """
    Al revés también importa: pedir eventos que nadie atiende llena el endpoint
    de ruido y engorda la factura de llamadas sin motivo.
    """

    sobran = set(swc.REQUIRED_EVENTS) - events_handled_in_the_code()

    assert not sobran, (
        f"se piden estos eventos y nadie los atiende: {sorted(sobran)}"
    )


def test_the_refund_events_are_in_the_list():
    """El motivo de que este módulo exista."""

    for evento in (
        "charge.refunded",
        "charge.dispute.created",
        "charge.dispute.closed",
    ):
        assert evento in swc.REQUIRED_EVENTS


# =========================
# QUÉ FALTA
# =========================

def endpoint(url="https://bot.example.com/webhook", eventos=(), status="enabled",
             id_="we_1"):
    """
    Un endpoint como el que devuelve Stripe DE VERDAD.

    Esto empezó siendo un diccionario, y ese fue el fallo más caro de toda la
    serie: los recursos del SDK de Stripe NO son diccionarios —no tienen .get()—
    así que el código pasaba las pruebas y en producción reventaba con
    "AttributeError: get", sin llegar a comprobar nada. El doble era más
    permisivo que la realidad.

    Se construye con la clase real para que el doble no pueda volver a ser más
    tolerante que producción.
    """

    import stripe

    return stripe.WebhookEndpoint.construct_from(
        {
            "id": id_,
            "url": url,
            "enabled_events": list(eventos),
            "status": status,
        },
        key=None,
    )


def endpoint_dict(**kwargs):
    """
    La misma cosa como diccionario.

    Se mantiene porque el lector de campos tiene que servir para las dos formas:
    hay respuestas ya normalizadas por otras partes del bot.
    """

    e = endpoint(**kwargs)

    return {
        "id": e.id,
        "url": e.url,
        "enabled_events": list(e.enabled_events),
        "status": e.status,
    }


def test_the_double_is_not_more_permissive_than_production():
    """
    La prueba que faltaba. Si el doble tuviese .get(), este fichero volvería a dar
    verde con el código roto.
    """

    e = endpoint()

    assert not isinstance(e, dict), "el doble ha vuelto a ser un diccionario"

    with pytest.raises(AttributeError):
        e.get("url")


def test_fields_are_read_from_both_shapes():
    """El lector tiene que servir para el objeto de Stripe y para un dict."""

    for muestra in (endpoint(eventos=["invoice.paid"]),
                    endpoint_dict(eventos=["invoice.paid"])):

        assert swc.campo(muestra, "url") == "https://bot.example.com/webhook"
        assert swc.campo(muestra, "enabled_events") == ["invoice.paid"]
        assert swc.campo(muestra, "status") == "enabled"
        assert swc.campo(muestra, "id") == "we_1"
        assert swc.campo(muestra, "no_existe", "por_defecto") == "por_defecto"


def test_a_wildcard_endpoint_is_missing_nothing():
    """Con "*" Stripe manda todo: no hay nada que arreglar."""

    assert swc.missing_events(endpoint(eventos=["*"])) == []


def test_it_reports_exactly_what_is_missing():
    e = endpoint(eventos=["checkout.session.completed", "invoice.paid"])

    faltan = swc.missing_events(e)

    assert "charge.refunded" in faltan
    assert "checkout.session.completed" not in faltan


def test_a_fully_configured_endpoint_is_left_alone():
    assert swc.missing_events(endpoint(eventos=swc.REQUIRED_EVENTS)) == []


def test_no_endpoint_means_everything_is_missing():
    assert swc.missing_events(None) == list(swc.REQUIRED_EVENTS)


# =========================
# CUÁL ES NUESTRO ENDPOINT
# =========================

def test_it_matches_our_endpoint_by_exact_url():
    nuestro = endpoint(url="https://bot.example.com/webhook", id_="we_nuestro")
    ajeno = endpoint(url="https://otra-cosa.example.com/webhook", id_="we_ajeno")

    encontrado = swc.find_our_endpoint(
        [ajeno, nuestro], "https://bot.example.com/webhook"
    )

    assert encontrado["id"] == "we_nuestro"


def test_it_refuses_to_guess_between_two_candidates():
    """
    Si el dominio ha cambiado y hay más de un candidato, no se elige: modificar
    el endpoint de otro servicio es peor que no arreglar nada.
    """

    a = endpoint(url="https://uno.example.com/webhook", id_="we_a")
    b = endpoint(url="https://dos.example.com/webhook", id_="we_b")

    assert swc.find_our_endpoint([a, b], "https://bot.example.com/webhook") is None


def test_it_accepts_a_single_candidate_when_the_domain_changed():
    """
    Un solo endpoint acabado en la ruta del bot: el dominio de Railway cambia al
    recrear el servicio, y ahí sí se puede afirmar cuál es.
    """

    solo = endpoint(url="https://dominio-nuevo.example.com/webhook", id_="we_solo")

    encontrado = swc.find_our_endpoint([solo], "https://viejo.example.com/webhook")

    assert encontrado["id"] == "we_solo"


def test_disabled_endpoints_are_not_picked_by_fallback():
    apagado = endpoint(url="https://x.example.com/webhook", status="disabled")

    assert swc.find_our_endpoint([apagado], "https://bot.example.com/webhook") is None


def test_an_empty_account_matches_nothing():
    assert swc.find_our_endpoint([], "https://bot.example.com/webhook") is None
    assert swc.find_our_endpoint(None, "https://bot.example.com/webhook") is None


# =========================
# AL ARREGLARLO, NO ROMPER NADA
# =========================

class FakeWebhookEndpoint:
    """Sustituye a stripe.WebhookEndpoint y apunta lo que se le pide."""

    def __init__(self, endpoints, fail=False):
        self._endpoints = endpoints
        self._fail = fail
        self.modified = []

    def list(self, limit=None):
        endpoints = self._endpoints

        if self._fail:
            raise RuntimeError("Stripe no contesta")

        class Page:
            @staticmethod
            def auto_paging_iter():
                return iter(endpoints)

        return Page()

    def modify(self, endpoint_id, enabled_events=None):
        if self._fail:
            raise RuntimeError("Stripe no contesta")

        self.modified.append((endpoint_id, list(enabled_events or [])))
        return {"id": endpoint_id, "enabled_events": list(enabled_events or [])}


@pytest.fixture
def stripe_falso(clean_db, monkeypatch):
    """
    Deja stripe con clave y un WebhookEndpoint que se puede dictar.

    Depende de clean_db porque el servicio escribe en el registro de auditoría:
    sin base de datos real, log_event se queda reintentando la conexión.
    """

    monkeypatch.setattr(swc.stripe, "api_key", "sk_test_falsa", raising=False)
    monkeypatch.setenv("SERVER_URL", "https://bot.example.com")
    monkeypatch.setattr(swc, "notify_super_admins", lambda *a, **k: 1)

    def instalar(endpoints, fail=False):
        fake = FakeWebhookEndpoint(endpoints, fail=fail)
        monkeypatch.setattr(swc.stripe, "WebhookEndpoint", fake, raising=False)
        return fake

    return instalar


def test_fixing_it_never_removes_an_event_somebody_else_added(stripe_falso):
    """
    Puede haber eventos puestos a mano para otra cosa. Se añaden los que faltan y
    se conserva todo lo demás.
    """

    ajeno = "radar.early_fraud_warning.created"
    fake = stripe_falso([endpoint(eventos=["invoice.paid", ajeno])])

    resumen = swc.verify_stripe_webhook_events(notify=False)

    assert resumen["fixed"] is True
    assert fake.modified, "no se llamó a Stripe para arreglarlo"

    _, final = fake.modified[0]

    assert ajeno in final, "se ha quitado un evento que no era nuestro"
    assert "invoice.paid" in final
    for evento in swc.REQUIRED_EVENTS:
        assert evento in final


def test_it_only_touches_our_own_endpoint(stripe_falso):
    nuestro = endpoint(url="https://bot.example.com/webhook", id_="we_nuestro")
    ajeno = endpoint(url="https://otro-servicio.example.com/webhook", id_="we_ajeno")

    fake = stripe_falso([ajeno, nuestro])

    swc.verify_stripe_webhook_events(notify=False)

    tocados = [eid for eid, _ in fake.modified]

    assert tocados == ["we_nuestro"]


def test_a_correct_configuration_is_not_touched_at_all(stripe_falso):
    fake = stripe_falso([endpoint(eventos=swc.REQUIRED_EVENTS)])

    resumen = swc.verify_stripe_webhook_events(notify=False)

    assert resumen["missing"] == []
    assert resumen["fixed"] is False
    assert fake.modified == []


def test_it_can_be_left_as_warn_only(stripe_falso, monkeypatch):
    """
    Quien no quiera que el bot toque su cuenta de Stripe puede apagarlo y seguir
    recibiendo el aviso.
    """

    monkeypatch.setenv("STRIPE_WEBHOOK_AUTOFIX", "0")
    fake = stripe_falso([endpoint(eventos=["invoice.paid"])])

    resumen = swc.verify_stripe_webhook_events(notify=False)

    assert resumen["missing"], "tiene que seguir detectando lo que falta"
    assert resumen["fixed"] is False
    assert fake.modified == [], "estaba desactivado y ha modificado la cuenta"


def test_autofix_is_on_by_default(monkeypatch):
    """Un aviso que nadie lee deja el agujero abierto igual."""

    monkeypatch.delenv("STRIPE_WEBHOOK_AUTOFIX", raising=False)

    assert swc.autofix_enabled() is True


@pytest.mark.parametrize("valor", ["0", "false", "no", "off", "OFF"])
def test_autofix_can_be_switched_off_in_several_ways(monkeypatch, valor):
    monkeypatch.setenv("STRIPE_WEBHOOK_AUTOFIX", valor)

    assert swc.autofix_enabled() is False


# =========================
# CUANDO ALGO VA MAL
# =========================

def test_without_a_stripe_key_it_does_nothing(monkeypatch):
    monkeypatch.setattr(swc.stripe, "api_key", None, raising=False)

    resumen = swc.verify_stripe_webhook_events(notify=False)

    assert resumen["checked"] is False
    assert resumen["fixed"] is False


def test_a_stripe_outage_does_not_crash_the_startup(stripe_falso):
    """
    Esto corre al arrancar. Si revienta, el bot no arranca por algo que no es
    imprescindible para funcionar.
    """

    stripe_falso([endpoint()], fail=True)

    resumen = swc.verify_stripe_webhook_events(notify=False)

    assert resumen["checked"] is False


def test_a_failure_while_fixing_is_reported_as_not_fixed(stripe_falso, monkeypatch):
    fake = stripe_falso([endpoint(eventos=["invoice.paid"])])

    def modify_roto(endpoint_id, enabled_events=None):
        raise RuntimeError("permiso insuficiente en la clave")

    monkeypatch.setattr(fake, "modify", modify_roto)

    resumen = swc.verify_stripe_webhook_events(notify=False)

    assert resumen["missing"]
    assert resumen["fixed"] is False


def test_a_missing_endpoint_is_reported_as_critical(stripe_falso):
    """Sin endpoint no llega nada: ni un pago completado."""

    stripe_falso([])

    resumen = swc.verify_stripe_webhook_events(notify=False)

    assert resumen["checked"] is True
    assert resumen["endpoint_found"] is False


def test_the_notice_names_the_missing_events():
    texto = swc.build_missing_events_notice(
        "https://bot.example.com/webhook",
        ["charge.refunded", "charge.dispute.created"],
        arreglado=False,
    )

    assert "charge.refunded" in texto
    assert "charge.dispute.created" in texto
    assert "Webhooks" in texto, "sin decir dónde arreglarlo, el aviso no sirve"


def test_the_notice_reads_differently_once_it_is_fixed():
    faltaban = ["charge.refunded"]

    aviso = swc.build_missing_events_notice("u", faltaban, arreglado=False)
    arreglado = swc.build_missing_events_notice("u", faltaban, arreglado=True)

    assert aviso != arreglado
    assert "corregido" in arreglado.lower()


# =========================
# LA URL QUE SE ESPERA
# =========================

def test_the_expected_url_is_built_from_server_url(monkeypatch):
    monkeypatch.setenv("SERVER_URL", "https://bot.example.com/")

    assert swc.expected_webhook_url() == "https://bot.example.com/webhook"


def test_without_server_url_there_is_no_expectation(monkeypatch):
    """No se inventa una URL: se dice que no se sabe."""

    monkeypatch.delenv("SERVER_URL", raising=False)

    assert swc.expected_webhook_url() is None


def test_the_path_matches_where_the_webhook_is_actually_published():
    """
    Si alguien mueve la ruta en main.py, esta comprobación buscaría un endpoint
    que no existe y avisaría de un problema falso.
    """

    source = open("main.py", encoding="utf-8").read()

    assert f'app.route("{swc.WEBHOOK_PATH}", methods=["POST"])(stripe_webhook)' in source
