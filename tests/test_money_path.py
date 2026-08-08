"""
El camino del dinero: pago confirmado -> acceso concedido y enlace entregado.

Es el flujo más crítico del bot y no tenía ninguna prueba. En esta sesión
aparecieron dos fallos justo aquí:
  - payments no tenía la columna 'status' en producción, así que el INSERT
    rompía y, al estar justo antes del guardado del enlace, el cliente podía
    pagar y no recibir acceso.
  - un grupo convertido en supergrupo dejaba de poder crear enlaces.

Estos tests ejercitan el webhook real contra una base de datos real.
"""

import flask
import pytest


PAID_STATUSES = ("paid", "completed", "succeeded")


def make_event(user_id, group_id, session_id="cs_test_1", amount=1500, currency="eur"):
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "payment_intent": f"pi_{session_id}",
                "amount_total": amount,
                "currency": currency,
                "metadata": {
                    "telegram_id": str(user_id),
                    "group_id": str(group_id),
                },
            }
        },
    }


@pytest.fixture
def stripe_env(clean_db, monkeypatch):
    """Grupo con plan, y Stripe/Telegram simulados alrededor del webhook."""

    import stripe_handler as sh

    db = clean_db
    user_id, group_id, telegram_group_id = 5551, 1, -1001234567890

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (%s, %s, %s, TRUE)",
            (group_id, "VIP Fitness", telegram_group_id),
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) "
            "VALUES (%s, 'Mensual', 'price_x', 'price_x', 30, 15, 'EUR', TRUE)",
            (group_id,),
        )

    # Firma de Stripe: se valida en producción, aquí se sustituye el resultado.
    monkeypatch.setattr(
        sh.stripe.Webhook,
        "construct_event",
        staticmethod(lambda payload, sig, secret: flask.g.fake_event),
    )
    monkeypatch.setattr(
        sh.stripe.checkout.Session,
        "list_line_items",
        staticmethod(lambda session_id: {"data": [{"price": {"id": "price_x"}}]}),
    )

    # Nada de red: enlace de invitación y avisos simulados.
    monkeypatch.setattr(
        sh, "create_telegram_invite_link",
        lambda *a, **k: "https://t.me/joinchat/TEST"
    )
    monkeypatch.setattr(sh, "send_telegram_message", lambda *a, **k: None)
    monkeypatch.setattr(sh, "notify_super_admins", lambda *a, **k: None)

    return {
        "sh": sh,
        "db": db,
        "user_id": user_id,
        "group_id": group_id,
        "telegram_group_id": telegram_group_id,
    }


def run_webhook(sh, event):
    """Ejecuta el webhook real dentro de un contexto de petición Flask."""

    app = flask.Flask(__name__)

    with app.test_request_context("/webhook", method="POST", data=b"{}"):
        flask.g.fake_event = event
        return sh.stripe_webhook()


def test_paid_checkout_grants_access(stripe_env):
    env = stripe_env
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT expiration, subscription_active FROM users "
            "WHERE user_id=%s AND group_id=%s",
            (env["user_id"], env["group_id"]),
        )
        row = cur.fetchone()

    assert row is not None, "el pago no concedió acceso al usuario"
    expiration, active = row
    assert active is True
    assert expiration is not None, "un plan de 30 días debe fijar caducidad"


def test_paid_checkout_stores_the_invite_link(stripe_env):
    env = stripe_env
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT invite_link FROM invite_links WHERE user_id=%s AND group_id=%s",
            (env["user_id"], env["group_id"]),
        )
        row = cur.fetchone()

    # Este es el fallo que costaba dinero: acceso concedido y enlace perdido.
    assert row is not None, "el usuario pagó y no se guardó su enlace de acceso"
    assert row[0]


def test_paid_checkout_is_recorded_in_payments(stripe_env):
    env = stripe_env
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT status, amount, currency FROM payments "
            "WHERE user_id=%s AND group_id=%s",
            (env["user_id"], env["group_id"]),
        )
        row = cur.fetchone()

    assert row is not None, "el pago no quedó registrado"
    status, amount, currency = row
    assert str(status).lower() in PAID_STATUSES
    assert amount == 1500
    assert (currency or "").upper() == "EUR"


def test_paid_checkout_records_a_transaction(stripe_env):
    env = stripe_env
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM payment_transactions "
            "WHERE user_id=%s AND group_id=%s",
            (env["user_id"], env["group_id"]),
        )
        rows = cur.fetchall()

    assert rows, "no se registró la transacción del pago"
    assert any(str(r[0]).lower() in PAID_STATUSES for r in rows)


def test_replayed_webhook_does_not_duplicate_access(stripe_env):
    """Stripe reintenta los webhooks: el mismo pago no debe duplicar acceso."""

    env = stripe_env
    event = make_event(env["user_id"], env["group_id"])

    run_webhook(env["sh"], event)
    run_webhook(env["sh"], event)

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE user_id=%s AND group_id=%s",
            (env["user_id"], env["group_id"]),
        )
        assert cur.fetchone()[0] == 1, "el acceso se duplicó al reintentar el webhook"

        cur.execute(
            "SELECT COUNT(*) FROM invite_links WHERE user_id=%s AND group_id=%s",
            (env["user_id"], env["group_id"]),
        )
        assert cur.fetchone()[0] == 1, "se acumularon enlaces de acceso"


def test_banned_user_does_not_get_access(stripe_env):
    env = stripe_env

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO banned_users (user_id, group_id) VALUES (%s, %s)",
            (env["user_id"], env["group_id"]),
        )

    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM invite_links WHERE user_id=%s",
            (env["user_id"],),
        )
        assert cur.fetchone()[0] == 0, "un usuario baneado recibió acceso"


# =========================
# PAGO COBRADO Y ENLACE FALLIDO
# =========================
# El peor estado posible para un cliente. Antes de esto, el webhook avisaba a los
# administradores y retornaba: al comprador no se le enviaba nada, y como el
# acceso se guarda DESPUÉS del enlace, se quedaba también sin acceso. Pagaba y
# recibía silencio, sin nada en «Mis accesos».

@pytest.fixture
def stripe_env_sin_enlace(stripe_env, monkeypatch):
    """Mismo entorno, pero la creación del enlace falla."""

    monkeypatch.setattr(
        stripe_env["sh"], "create_telegram_invite_link", lambda *a, **k: None
    )

    enviados = []

    def capturar(token, chat_id, text, reply_markup=None):
        enviados.append((chat_id, text, reply_markup))
        return {"ok": True}

    monkeypatch.setattr(stripe_env["sh"], "send_telegram_message", capturar)

    stripe_env["enviados"] = enviados

    return stripe_env


def test_a_failed_link_still_grants_the_access_that_was_paid_for(stripe_env_sin_enlace):
    """El pago es real y el derecho también; el enlace solo es la entrega."""

    env = stripe_env_sin_enlace
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT subscription_active FROM users WHERE user_id=%s AND group_id=%s",
            (env["user_id"], env["group_id"]),
        )
        row = cur.fetchone()

    assert row is not None, "pagó y se quedó sin acceso porque falló el enlace"
    assert row[0] is True


def test_a_failed_link_still_records_the_payment(stripe_env_sin_enlace):
    env = stripe_env_sin_enlace
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM payments WHERE user_id=%s AND group_id=%s",
            (env["user_id"], env["group_id"]),
        )
        row = cur.fetchone()

    assert row is not None, "el cobro no quedó registrado"
    assert str(row[0]).lower() in PAID_STATUSES


def test_a_failed_link_does_not_store_an_empty_link_row(stripe_env_sin_enlace):
    """Una fila activa sin enlace haría creer que ya se entregó el acceso."""

    env = stripe_env_sin_enlace
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM invite_links WHERE user_id=%s",
            (env["user_id"],),
        )
        assert cur.fetchone()[0] == 0


def test_the_buyer_is_told_instead_of_left_in_silence(stripe_env_sin_enlace):
    env = stripe_env_sin_enlace
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    al_comprador = [
        (text, markup)
        for chat_id, text, markup in env["enviados"]
        if chat_id == env["user_id"]
    ]

    assert al_comprador, "el comprador no recibió ningún mensaje"

    texto, markup = al_comprador[0]

    # Lo que necesita saber: que el pago está, que el acceso está, y qué hacer.
    assert "Pago confirmado" in texto
    assert "acceso" in texto.lower()
    assert "no has perdido el dinero" in texto.lower()

    callbacks = [
        boton["callback_data"]
        for fila in markup["inline_keyboard"]
        for boton in fila
    ]

    assert f"mysub_{env['telegram_group_id']}" in callbacks, (
        "sin botón para pedir el enlace, el cliente sigue bloqueado"
    )
    assert "public_support" in callbacks


def test_the_recovery_button_can_actually_deliver_the_link(stripe_env_sin_enlace):
    """
    El botón solo sirve si el acceso está guardado: «Mis accesos» genera un
    enlace nuevo a partir del acceso, y por eso se guarda aunque falle la
    entrega.
    """

    env = stripe_env_sin_enlace
    run_webhook(env["sh"], make_event(env["user_id"], env["group_id"]))

    with env["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM users WHERE user_id=%s AND group_id=%s "
            "AND COALESCE(subscription_active, FALSE)=TRUE "
            "AND (expiration IS NULL OR expiration > NOW())",
            (env["user_id"], env["group_id"]),
        )

        assert cur.fetchone() is not None, (
            "«Mis accesos» no encontraría nada y el botón no podría dar el enlace"
        )
