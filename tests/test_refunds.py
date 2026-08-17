"""
PEDIR una devolución desde el bot, cuando no hay otra salida.

Reparto de papeles: refund_service procesa la devolución que YA ocurrió (el
webhook: marca el pago, retira el acceso, expulsa y avisa). Este módulo solo
se la PIDE a Stripe. Lo de después lo hace el webhook, que ya sabe hacerlo.

El aviso de "ha pagado alguien con el acceso vetado" terminaba diciendo «hay
que devolverle el pago», y devolverlo significaba entrar al panel de Stripe a
buscar el cobro entre todos, con el cliente esperando y con la posibilidad de
devolver el equivocado.

Las reglas que hacen que un botón de devolver dinero no dé miedo: lo pulsa
una PERSONA tras una confirmación con el importe exacto, se devuelve el
ÚLTIMO cobrado, no se puede pedir dos veces, este módulo no toca ni el pago
ni el acceso (los toca el webhook, o se los saltaría por idempotencia), y si
el cobro no se puede pedir por API se dice en vez de fingir que se hizo.
"""

import pytest
import stripe

import refund_request_service as rs


@pytest.fixture
def comprador(clean_db):
    """Alguien con dos pagos: uno viejo y el último, que es el devolvible."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (63, 'VIP Devolución', -1063, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (6301, 63, NOW() + INTERVAL '20 days', TRUE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, stripe_payment_id, amount, "
            "currency, status, plan, payment_date) VALUES "
            "(6301, 63, 'stripe:pi_viejo', 1000, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '60 days'), "
            "(6301, 63, 'stripe:pi_ultimo', 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '1 days')"
        )

    return db


def test_the_target_is_resolved_from_what_we_actually_store():
    assert rs.resolve_refund_target("stripe:pi_123") == {"payment_intent": "pi_123"}
    assert rs.resolve_refund_target("pi_123") == {"payment_intent": "pi_123"}
    assert rs.resolve_refund_target("stripe:ch_123") == {"charge": "ch_123"}

    # Otros proveedores y referencias raras: no se finge que se puede.
    assert rs.resolve_refund_target("paypal:ABC123") is None
    assert rs.resolve_refund_target("stripe:algo_raro") is None
    assert rs.resolve_refund_target(None) is None


def test_a_renewal_invoice_is_resolved_through_stripe(monkeypatch):
    """Una factura no se devuelve: hay que sacarle el cobro."""

    monkeypatch.setattr(
        rs.stripe.Invoice, "retrieve",
        lambda ref: stripe.Invoice.construct_from(
            {"id": ref, "payment_intent": "pi_de_factura"}, "sk_test"
        )
    )

    assert rs.resolve_refund_target("in_123") == {"payment_intent": "pi_de_factura"}


def test_the_confirmation_screen_knows_the_exact_amount(comprador):
    devolvible = rs.describe_refundable(6301, 63)

    assert devolvible["importe"] == "15.00 EUR", (
        "el último cobrado, no el viejo de 10.00"
    )
    assert devolvible["puede_api"] is True


def test_the_request_is_asked_once_and_never_twice(comprador, monkeypatch):
    llamadas = []

    monkeypatch.setattr(rs.stripe.Refund, "create",
                        lambda **k: llamadas.append(k) or {"id": "re_1"})

    resultado = rs.refund_last_payment(6301, 63, actor_user_id=7000)

    assert resultado["ok"] is True
    assert resultado["importe"] == "15.00 EUR"
    assert llamadas == [{"payment_intent": "pi_ultimo"}]

    # Dos personas pulsando el mismo botón: solo una pide la devolución.
    segundo = rs.refund_last_payment(6301, 63, actor_user_id=7001)

    assert (segundo["ok"], segundo["reason"]) == (False, "already")
    assert len(llamadas) == 1


def test_the_payment_is_left_for_the_webhook_to_mark(comprador, monkeypatch):
    """Marcarlo aquí haría que el webhook se lo saltara por idempotencia, y
    entonces nadie retiraría el acceso ni avisaría al comprador."""

    monkeypatch.setattr(rs.stripe.Refund, "create", lambda **k: {"id": "re_1"})

    rs.refund_last_payment(6301, 63, actor_user_id=7000)

    with comprador.conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM payments WHERE stripe_payment_id='stripe:pi_ultimo'"
        )
        assert cur.fetchone()[0] == "paid", (
            "el pago lo marca el webhook de la devolución, no este módulo"
        )

    fuente = open("refund_request_service.py", encoding="utf-8").read()

    assert "SET status" not in fuente and "'refunded'" not in fuente, (
        "este módulo no toca el estado del pago ni el acceso"
    )


def test_asking_for_the_refund_does_not_touch_the_access(comprador, monkeypatch):
    """El acceso lo retira el webhook cuando Stripe confirma, no la petición."""

    monkeypatch.setattr(rs.stripe.Refund, "create", lambda **k: {"id": "re_1"})

    with comprador.conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=6301")
        antes = cur.fetchone()[0]

    rs.refund_last_payment(6301, 63, actor_user_id=7000)

    with comprador.conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=6301")
        assert cur.fetchone()[0] == antes


def test_a_stripe_failure_can_be_retried(comprador, monkeypatch):
    def explota(**kwargs):
        raise RuntimeError("card_error")

    monkeypatch.setattr(rs.stripe.Refund, "create", explota)

    resultado = rs.refund_last_payment(6301, 63, actor_user_id=7000)

    assert resultado["ok"] is False
    assert resultado["reason"] == "stripe_error"

    with comprador.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM refund_requests")
        assert cur.fetchone()[0] == 0, (
            "si Stripe rechaza, la marca se borra: si no, el cobro quedaría "
            "imposible de devolver para siempre"
        )

    # Y con Stripe funcionando, el reintento sí pasa.
    monkeypatch.setattr(rs.stripe.Refund, "create", lambda **k: {"id": "re_2"})

    assert rs.refund_last_payment(6301, 63, actor_user_id=7000)["ok"] is True


def test_without_a_paid_payment_there_is_nothing_to_refund(comprador):
    with comprador.conn.cursor() as cur:
        cur.execute("UPDATE payments SET status='refunded' WHERE user_id=6301")

    resultado = rs.refund_last_payment(6301, 63, actor_user_id=7000)

    assert (resultado["ok"], resultado["reason"]) == (False, "no_payment")


def test_a_non_api_payment_is_reported_not_faked(comprador):
    with comprador.conn.cursor() as cur:
        cur.execute(
            "UPDATE payments SET stripe_payment_id='paypal:ABC' "
            "WHERE stripe_payment_id='stripe:pi_ultimo'"
        )

    devolvible = rs.describe_refundable(6301, 63)
    assert devolvible["puede_api"] is False

    resultado = rs.refund_last_payment(6301, 63, actor_user_id=7000)
    assert resultado["reason"] == "unsupported"

    with comprador.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM refund_requests")
        assert cur.fetchone()[0] == 0, (
            "no se registra una petición que no se ha hecho"
        )


def test_the_banned_buyer_notice_offers_refund_instead_of_access():
    import payment_incident_service as pis

    teclado = pis.build_staff_incident_keyboard(
        55, kind=pis.INCIDENT_BANNED_BUYER
    )
    callbacks = [b["callback_data"]
                 for fila in teclado["inline_keyboard"] for b in fila]

    assert callbacks == ["incident_refund_55"], (
        "conceder acceso a quien está vetado sería saltarse la decisión de "
        "alguien"
    )

    otro = pis.build_staff_incident_keyboard(56, kind="plan_not_found")
    callbacks = [b["callback_data"]
                 for fila in otro["inline_keyboard"] for b in fila]

    assert callbacks == ["incident_fix_56", "incident_refund_56"]


def test_the_refund_needs_two_taps_and_the_right_person():
    router = open("callback_router.py", encoding="utf-8").read()

    # El "go" antes que su prefijo padre, o la confirmación no se alcanzaría.
    assert router.index('data.startswith("incident_refund_go_")') < \
        router.index('data.startswith("incident_refund_")')

    for rama in ('data.startswith("incident_refund_go_")',
                 'data.startswith("incident_refund_")'):

        pos = router.index(rama)
        trozo = router[pos:pos + 2500]

        assert "is_super_admin(user_id)" in trozo
        assert "get_group_owner_user_id(group_id) == user_id" in trozo


    pos = router.index('data.startswith("incident_refund_")')
    trozo = router[pos:pos + 3000]

    assert "¿Devolver" in trozo, "la confirmación dice el importe exacto"
    assert "el acceso se " in trozo and "retira solo" in trozo, (
        "hay que decir la verdad: el webhook retirará el acceso"
    )
