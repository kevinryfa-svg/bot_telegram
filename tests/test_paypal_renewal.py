"""
La renovación automática de PayPal, de punta a punta con el código real.

Los planes de grupo de PayPal siempre fueron suscripciones: cada ciclo llega
un PAYMENT.SALE.COMPLETED nuevo y el webhook real vuelve a conceder. Lo que
faltaba era el resto de la vida de la suscripción: que el comprador se entere
cuando se cancela, se suspende o falla un cobro, y que pueda apagarla desde el
bot sin bucear en PayPal.

Paridad de decisiones con Stripe, con UNA diferencia que manda en los textos:
en PayPal la cancelación es DEFINITIVA (no se puede reactivar), así que el
interruptor pide confirmación y nada promete reactivación.

Mismo método que test_provider_webhooks_e2e: creador y webhook REALES, solo se
le miente a la red y a las credenciales, y el punto de partida es el precio
que teclea el propietario.
"""

from datetime import datetime

import pytest

import payment_access_service as pas
import payment_providers.paypal_provider as pp
import paypal_subscription_controls as ppc


PRECIO_EUROS = 15


class FakeResp:
    def __init__(self, data, code=200):
        self._d, self.status_code = data, code

    def json(self):
        return self._d

    def raise_for_status(self):
        return None


@pytest.fixture
def entorno(clean_db, monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (94, 'VIP PayPal Renov', -1094, TRUE, FALSE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, "
            "is_active, payment_provider, paypal_plan_id) "
            "VALUES (94, 'Mensual', %s, 'EUR', 30, TRUE, 'paypal', 'P-PLAN94') "
            "RETURNING id",
            (PRECIO_EUROS,),
        )
        plan_id = cur.fetchone()[0]

    avisos = []
    cancelaciones = []
    estado_paypal = {"status": "ACTIVE"}

    def enviar(token, chat, text, reply_markup=None):
        avisos.append((chat, text))
        return {"ok": True}

    # El grant real avisa por payment_access_service; los avisos de ciclo de
    # vida, por notification_service (import diferido dentro de la función).
    monkeypatch.setattr(pas, "send_telegram_message", enviar)
    monkeypatch.setattr("notification_service.send_telegram_message", enviar)
    monkeypatch.setattr(pas, "notify_super_admins", lambda *a, **k: 1)
    monkeypatch.setattr(pas, "create_telegram_invite_link",
                        lambda *a, **k: "https://t.me/+renov94")
    monkeypatch.setattr(pas, "log_user_event_by_ids", lambda *a, **k: None)

    monkeypatch.setattr(pp, "get_payment_provider_config",
                        lambda provider: {"enabled": True})
    monkeypatch.setattr(pp, "get_group_paypal_credentials", lambda gid: {
        "client_id": "cid", "client_secret": "sec", "mode": "sandbox",
        "owner_user_id": 777, "provider_config_id": 1,
    })
    monkeypatch.setattr(pp, "get_paypal_access_token_for_credentials",
                        lambda *a, **k: "token")
    monkeypatch.setattr(pp, "verify_paypal_webhook",
                        lambda headers, body, transaction=None: True)

    def red_post(url, *a, **k):
        if "billing/subscriptions" in url and url.endswith("/cancel"):
            cancelaciones.append(url)
            estado_paypal["status"] = "CANCELLED"
            return FakeResp({}, code=204)
        if "billing/subscriptions" in url:
            return FakeResp({
                "id": "I-SUB94",
                "links": [{"rel": "approve", "href": "https://pp.example/ok"}],
            }, code=201)
        raise AssertionError(f"POST inesperado a {url}")

    def red_get(url, *a, **k):
        if "billing/subscriptions/I-SUB94" in url:
            return FakeResp({"id": "I-SUB94", "status": estado_paypal["status"]})
        raise AssertionError(f"GET inesperado a {url}")

    monkeypatch.setattr(pp.requests, "post", red_post)
    monkeypatch.setattr(pp.requests, "get", red_get)

    return {
        "db": db, "plan": plan_id, "avisos": avisos,
        "cancelaciones": cancelaciones, "estado_paypal": estado_paypal,
    }


def acceso(db, user_id=9401):
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(subscription_active, FALSE), expiration "
            "FROM users WHERE user_id=%s AND group_id=94", (user_id,)
        )
        row = cur.fetchone()
    return (bool(row[0]), row[1]) if row else (False, None)


def pagos(db, user_id=9401):
    with db.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM payments WHERE user_id=%s", (user_id,))
        return cur.fetchone()[0]


def venta(sale_id="SALE-1", total="15.00"):
    return {
        "id": f"WH-{sale_id}",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "id": sale_id,
            "state": "completed",
            "billing_agreement_id": "I-SUB94",
            "amount": {"total": total, "currency": "EUR"},
        },
    }


def ciclo_de_vida(tipo, status="CANCELLED"):
    return {
        "id": f"WH-{tipo}",
        "event_type": tipo,
        "resource": {"id": "I-SUB94", "status": status},
    }


# =========================
# LA RENOVACIÓN QUE YA EXISTÍA, AHORA FIJADA
# =========================

def test_a_second_cycle_sale_extends_access_again(entorno):
    """
    El corazón de la renovación PayPal: cada ciclo llega una VENTA NUEVA
    (sale_id distinto, misma suscripción) y tiene que volver a conceder — la
    idempotencia es por venta, no por suscripción.
    """

    pp.create_group_paypal_order(9401, 94, entorno["plan"])

    r1 = pp.process_paypal_webhook(venta("SALE-1"), {})
    assert r1.get("status_code") == 200

    activo, expira_1 = acceso(entorno["db"])
    assert activo is True
    assert pagos(entorno["db"]) == 1

    entorno["avisos"].clear()

    r2 = pp.process_paypal_webhook(venta("SALE-2"), {})

    assert r2.get("status_code") == 200
    assert "Already processed" not in (r2.get("message") or ""), (
        "la renovación se confundió con un reintento: el ciclo 2 no concede"
    )

    activo, expira_2 = acceso(entorno["db"])
    assert activo is True
    assert expira_2 >= expira_1, "el ciclo 2 tiene que extender el acceso"
    assert pagos(entorno["db"]) == 2, "cada ciclo cobrado es un pago registrado"

    al_comprador = [t for c, t in entorno["avisos"] if c == 9401]
    assert al_comprador, "el comprador tiene que enterarse de la renovación"


def test_a_replayed_sale_still_does_not_double_grant(entorno):
    """Y el reintento del MISMO sale sigue neutralizado, como siempre."""

    pp.create_group_paypal_order(9401, 94, entorno["plan"])
    pp.process_paypal_webhook(venta("SALE-1"), {})

    _, expira = acceso(entorno["db"])

    r = pp.process_paypal_webhook(venta("SALE-1"), {})
    assert "Already processed" in (r.get("message") or "")

    _, expira_2 = acceso(entorno["db"])
    assert expira_2 == expira
    assert pagos(entorno["db"]) == 1


def test_a_forged_amount_on_a_renewal_cycle_is_rejected(entorno):
    """La validación de importes protege también los ciclos siguientes."""

    pp.create_group_paypal_order(9401, 94, entorno["plan"])
    pp.process_paypal_webhook(venta("SALE-1"), {})

    r = pp.process_paypal_webhook(venta("SALE-2", total="1.00"), {})

    assert r.get("status_code") == 400
    assert "mismatch" in (r.get("message") or "").lower()
    assert pagos(entorno["db"]) == 1


# =========================
# EL CICLO DE VIDA AVISA AL COMPRADOR
# =========================

@pytest.fixture
def suscrito(entorno):
    pp.create_group_paypal_order(9401, 94, entorno["plan"])
    pp.process_paypal_webhook(venta("SALE-1"), {})
    entorno["avisos"].clear()
    return entorno


def test_cancellation_tells_the_buyer_and_keeps_the_paid_period(suscrito):
    _, expira_antes = acceso(suscrito["db"])

    r = pp.process_paypal_webhook(
        ciclo_de_vida("BILLING.SUBSCRIPTION.CANCELLED"), {}
    )

    assert r.get("status_code") == 200

    activo, expira = acceso(suscrito["db"])
    assert activo is True, "cancelar NO revoca el periodo ya pagado"
    assert expira == expira_antes

    al_comprador = [t for c, t in suscrito["avisos"] if c == 9401]
    assert al_comprador
    assert "no se te volverá a cobrar" in al_comprador[0].lower()
    assert "definitiva" in al_comprador[0].lower(), (
        "en PayPal no hay reactivación: el texto no puede callárselo"
    )
    assert expira.strftime("%d/%m/%Y") in al_comprador[0], (
        "hay que decir hasta cuándo llega el acceso pagado"
    )


def test_a_failed_charge_warns_without_touching_access(suscrito):
    _, expira_antes = acceso(suscrito["db"])

    pp.process_paypal_webhook(
        ciclo_de_vida("BILLING.SUBSCRIPTION.PAYMENT.FAILED", status="ACTIVE"), {}
    )

    activo, expira = acceso(suscrito["db"])
    assert activo is True and expira == expira_antes

    al_comprador = [t for c, t in suscrito["avisos"] if c == 9401]
    assert al_comprador and "sigue activo" in al_comprador[0]


def test_suspension_warns_in_pause_terms(suscrito):
    pp.process_paypal_webhook(
        ciclo_de_vida("BILLING.SUBSCRIPTION.SUSPENDED", status="SUSPENDED"), {}
    )

    al_comprador = [t for c, t in suscrito["avisos"] if c == 9401]
    assert al_comprador and "pausa" in al_comprador[0].lower()


def test_expiry_says_goodbye_with_the_door_open(suscrito):
    pp.process_paypal_webhook(
        ciclo_de_vida("BILLING.SUBSCRIPTION.EXPIRED", status="EXPIRED"), {}
    )

    al_comprador = [t for c, t in suscrito["avisos"] if c == 9401]
    assert al_comprador and "terminado" in al_comprador[0].lower()


# =========================
# EL INTERRUPTOR DEL COMPRADOR
# =========================

def test_the_state_is_read_from_paypal_by_the_member_anchor(suscrito):
    estado = ppc.fetch_paypal_renewal_state(9401, 94)

    assert estado is not None
    assert estado["subscription_id"] == "I-SUB94"
    assert estado["activa"] is True


def test_cancelling_from_the_bot_calls_paypal_and_reads_back_cancelled(suscrito):
    ok = ppc.cancel_paypal_renewal(9401, 94)

    assert ok is True
    assert suscrito["cancelaciones"], "no se llamó al endpoint de cancelación"
    assert suscrito["cancelaciones"][0].endswith(
        "/v1/billing/subscriptions/I-SUB94/cancel"
    )

    estado = ppc.fetch_paypal_renewal_state(9401, 94)
    assert estado["cancelada"] is True and estado["activa"] is False


def test_someone_without_a_paypal_subscription_has_no_switch(entorno):
    assert ppc.fetch_paypal_renewal_state(9401, 94) is None
    assert ppc.cancel_paypal_renewal(9401, 94) is False


# =========================
# LA PANTALLA
# =========================

def test_the_screen_branches_dodge_the_prefix_traps():
    source = open("mysub_callbacks.py", encoding="utf-8").read()

    # El "yes" antes que su prefijo padre, y ambos antes que la rama genérica.
    assert source.index('data.startswith("mysub_pprenewoff_yes_")') < \
        source.index('data.startswith("mysub_pprenewoff_")')
    assert source.index("mysub_pprenewoff_yes_") < \
        source.index('data.startswith("mysub_")')

    # La confirmación avisa de que en PayPal no hay vuelta atrás. El texto
    # vive en i18n (el comprador lo ve en su idioma): se fija la clave y que
    # la rama la use.
    from i18n_service import t

    assert "definitiva" in t("mysub.pp_confirm", "es")
    assert "final" in t("mysub.pp_confirm", "en")

    pos = source.index('data.startswith("mysub_pprenewoff_")')
    assert 't("mysub.pp_confirm"' in source[pos:pos + 1200]
