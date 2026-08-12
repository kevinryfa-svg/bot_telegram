"""
PayPal y Revolut de punta a punta, con el código real.

El creador REAL guarda la transacción y el webhook REAL la procesa; solo se le
miente a la red (las APIs de PayPal/Revolut, la verificación de firma) y a la
configuración de credenciales. Nunca a la lógica.

Existen porque los dos caminos estuvieron rotos de formas que ninguna prueba
veía: PayPal rechazaba todos los pagos por "amount mismatch" (guardaba euros y
comparaba contra céntimos) y Revolut cobraba el 1% del precio (mandaba euros a
una API que espera céntimos). Los dobles anteriores pasaban los importes ya
convertidos a mano, así que todo salía verde sobre código que no podía
funcionar. Aquí el punto de partida es el precio que teclea el propietario.
"""

import pytest

import payment_access_service as pas
import payment_providers.paypal_provider as pp
import payment_providers.revolut_provider as rv


PRECIO_EUROS = 15


class FakeResp:
    def __init__(self, data, code=201):
        self._d, self.status_code = data, code

    def json(self):
        return self._d

    def raise_for_status(self):
        return None


@pytest.fixture
def entorno(clean_db, monkeypatch):
    """
    Una comunidad con un plan de 15 EUR, y los stubs de red/credenciales.

    Los stubs de red capturan lo que se les manda: comprobar el payload que
    saldría hacia el proveedor es la mitad del valor de estas pruebas.
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (97, 'VIP E2E', -1097, TRUE, FALSE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, "
            "is_active, payment_provider, paypal_plan_id) "
            "VALUES (97, 'Mensual', %s, 'EUR', 30, TRUE, 'paypal', 'P-PLAN97') "
            "RETURNING id",
            (PRECIO_EUROS,),
        )
        plan_paypal = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, "
            "is_active, payment_provider) "
            "VALUES (97, 'Mensual', %s, 'EUR', 30, TRUE, 'revolut') RETURNING id",
            (PRECIO_EUROS,),
        )
        plan_revolut = cur.fetchone()[0]

    avisos = []
    a_paypal = []
    a_revolut = []

    def enviar(token, chat, text, reply_markup=None):
        avisos.append((chat, text))
        return {"ok": True}

    monkeypatch.setattr(pas, "send_telegram_message", enviar)
    monkeypatch.setattr(pas, "notify_super_admins", lambda *a, **k: 1)
    monkeypatch.setattr(pas, "create_telegram_invite_link",
                        lambda *a, **k: "https://t.me/+e2e")
    monkeypatch.setattr(pas, "log_user_event_by_ids", lambda *a, **k: None)

    for mod in (pp, rv):
        monkeypatch.setattr(mod, "get_payment_provider_config",
                            lambda provider: {"enabled": True})

    monkeypatch.setattr(pp, "get_group_paypal_credentials", lambda gid: {
        "client_id": "cid", "client_secret": "sec", "mode": "sandbox",
        "owner_user_id": 777, "provider_config_id": 1,
    })
    monkeypatch.setattr(pp, "get_paypal_access_token_for_credentials",
                        lambda *a, **k: "token")
    monkeypatch.setattr(pp, "verify_paypal_webhook",
                        lambda headers, body, transaction=None: True)

    # Un único stub para los dos proveedores: pp.requests y rv.requests son el
    # MISMO módulo, así que parchearlo dos veces hace que el último parche
    # reciba las llamadas del otro. La primera versión de esta fixture cayó ahí.
    def red_falsa(url, *a, **k):
        if "billing/subscriptions" in url:
            a_paypal.append(k.get("json") or {})
            return FakeResp({
                "id": "I-SUB97",
                "links": [{"rel": "approve", "href": "https://pp.example/ok"}],
            })
        if "/api/orders" in url:
            a_revolut.append(k.get("json") or {})
            return FakeResp({"id": "REV-97", "checkout_url": "https://rv.example/ok"})
        raise AssertionError(f"POST inesperado a {url}")

    monkeypatch.setattr(pp.requests, "post", red_falsa)

    monkeypatch.setattr(rv, "get_group_revolut_credentials", lambda gid: {
        "api_key": "key", "mode": "sandbox",
        "owner_user_id": 777, "provider_config_id": 1,
    })
    monkeypatch.setattr(rv, "verify_revolut_webhook",
                        lambda headers, raw_body, transaction=None: True)

    return {
        "db": db, "plan_paypal": plan_paypal, "plan_revolut": plan_revolut,
        "avisos": avisos,
        "a_paypal": a_paypal, "a_revolut": a_revolut,
    }


def acceso(db, user_id):
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(subscription_active, FALSE), expiration "
            "FROM users WHERE user_id=%s AND group_id=97", (user_id,)
        )
        row = cur.fetchone()
    return (bool(row[0]), row[1]) if row else (False, None)


def tx_amount(db, user_id):
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT amount FROM payment_transactions WHERE user_id=%s", (user_id,)
        )
        row = cur.fetchone()
    return row[0] if row else None


def evento_paypal(total="15.00"):
    return {
        "id": "WH-97",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "id": "SALE-97",
            "state": "completed",
            "billing_agreement_id": "I-SUB97",
            "amount": {"total": total, "currency": "EUR"},
        },
    }


def evento_revolut(amount=1500):
    return {
        "event": "ORDER_COMPLETED",
        "order_id": "REV-97",
        "data": {
            "id": "REV-97", "amount": amount, "currency": "EUR",
            "merchant_order_data": {"reference": None},
        },
    }


# =========================
# PAYPAL
# =========================

def test_paypal_full_cycle_from_the_price_the_owner_typed(entorno):
    """
    Crear pedido → webhook con "15.00" → acceso concedido y mensaje correcto.
    Antes de la corrección de unidades este ciclo era IMPOSIBLE: la validación
    rechazaba el webhook siempre.
    """

    pp.create_group_paypal_order(9701, 97, entorno["plan_paypal"])

    assert tx_amount(entorno["db"], 9701) == 1500, (
        "la transacción no guarda céntimos: la validación del webhook fallará"
    )

    r = pp.process_paypal_webhook(evento_paypal(), {})

    assert r.get("status_code") == 200

    activo, _ = acceso(entorno["db"], 9701)
    assert activo is True

    al_comprador = [t for c, t in entorno["avisos"] if c == 9701]
    assert al_comprador and "15.00 EUR" in al_comprador[0]


def test_paypal_retry_does_not_extend_access_or_repeat_the_message(entorno):
    """PayPal reenvía los webhooks: la segunda vez no puede regalar días."""

    pp.create_group_paypal_order(9701, 97, entorno["plan_paypal"])
    pp.process_paypal_webhook(evento_paypal(), {})

    _, expira = acceso(entorno["db"], 9701)
    entorno["avisos"].clear()

    r = pp.process_paypal_webhook(evento_paypal(), {})

    assert "Already processed" in (r.get("message") or "")

    _, expira2 = acceso(entorno["db"], 9701)
    assert expira2 == expira, "el reintento extendió el acceso otra vez"
    assert not [t for c, t in entorno["avisos"] if c == 9701]


def test_paypal_rejects_a_webhook_with_the_wrong_amount(entorno):
    """La validación que antes rechazaba todo ahora solo rechaza lo falso."""

    pp.create_group_paypal_order(9701, 97, entorno["plan_paypal"])

    r = pp.process_paypal_webhook(evento_paypal(total="1.00"), {})

    assert r.get("status_code") == 400
    assert "mismatch" in (r.get("message") or "").lower()

    activo, _ = acceso(entorno["db"], 9701)
    assert activo is False


# =========================
# REVOLUT
# =========================

def test_revolut_charges_the_real_price_not_one_percent(entorno):
    """
    Lo que se le manda a la API de Revolut, capturado del payload real. Antes
    iban 15 (euros) a una API que espera céntimos: el pedido salía por 0,15 €.
    """

    rv.create_group_revolut_order(9702, 97, entorno["plan_revolut"])

    assert entorno["a_revolut"], "no se llamó a la API de Revolut"
    assert entorno["a_revolut"][0].get("amount") == 1500, (
        f"a Revolut se le pidió {entorno['a_revolut'][0].get('amount')}: "
        "el cliente pagaría otra cosa que el precio del plan"
    )
    assert tx_amount(entorno["db"], 9702) == 1500


def test_revolut_full_cycle_grants_access_and_says_the_right_amount(entorno):
    rv.create_group_revolut_order(9702, 97, entorno["plan_revolut"])

    r = rv.process_revolut_webhook(evento_revolut(), {}, "{}")

    assert r.get("status_code") == 200

    activo, _ = acceso(entorno["db"], 9702)
    assert activo is True

    al_comprador = [t for c, t in entorno["avisos"] if c == 9702]
    assert al_comprador and "15.00 EUR" in al_comprador[0]


def test_revolut_rejects_a_forged_amount_before_payment(entorno):
    """
    La ventana real de fraude: un webhook falsificado que intenta marcar como
    pagado un pedido pendiente por menos dinero.
    """

    rv.create_group_revolut_order(9702, 97, entorno["plan_revolut"])

    r = rv.process_revolut_webhook(evento_revolut(amount=100), {}, "{}")

    assert r.get("status_code") == 400
    assert "mismatch" in (r.get("message") or "").lower()

    activo, _ = acceso(entorno["db"], 9702)
    assert activo is False


def test_revolut_retry_is_neutralized(entorno):
    rv.create_group_revolut_order(9702, 97, entorno["plan_revolut"])
    rv.process_revolut_webhook(evento_revolut(), {}, "{}")

    _, expira = acceso(entorno["db"], 9702)
    entorno["avisos"].clear()

    # Reintento legítimo y también un intento con importe falso ya pagado:
    # los dos deben quedar en "ya procesado" sin tocar nada.
    for ev in (evento_revolut(), evento_revolut(amount=100)):
        r = rv.process_revolut_webhook(ev, {}, "{}")
        assert "Already processed" in (r.get("message") or "")

    _, expira2 = acceso(entorno["db"], 9702)
    assert expira2 == expira
    assert not [t for c, t in entorno["avisos"] if c == 9702]
