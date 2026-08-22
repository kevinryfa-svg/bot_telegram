"""
La prueba gratuita por plan (solo suscripciones de Stripe).

La decisión de producto: tarjeta POR DELANTE. El cliente la pone al
suscribirse, prueba gratis y el primer cobro sale al terminar; si cancela
durante la prueba, cobro cero. Es lo que convierte más y lo que Stripe
modela nativamente (trial_period_days).

La trampa que estas pruebas vigilan: el alta del checkout concede la
duración ENTERA del plan, pero en una suscripción en prueba lo cubierto es
la prueba. Sin el recorte, un cliente de 7 días de prueba que cancela el
día 2 se quedaría 30 días dentro gratis.
"""

from datetime import datetime, timedelta

import pytest
import stripe

import group_subscription_service as gss


@pytest.fixture
def socio_en_prueba(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (87, 'VIP Trial', -1087, TRUE)"
        )
        # El alta acaba de conceder los 30 días del plan.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) "
            "VALUES (8701, 87, NOW() + INTERVAL '30 days', TRUE, 'sub_87')"
        )

    return db


def suscripcion(status="trialing", trial_end=None):
    fin = trial_end or int((datetime.now() + timedelta(days=7)).timestamp())
    return stripe.Subscription.construct_from(
        {"id": "sub_87", "status": status, "trial_end": fin,
         "current_period_end": fin},
        "sk_test",
    )


def expiracion(db):
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT expiration FROM users WHERE user_id=8701 AND group_id=87"
        )
        return cur.fetchone()[0]


def test_a_trialing_subscription_cuts_the_grant_to_the_trial_end(
        socio_en_prueba, monkeypatch):
    fin = int((datetime.now() + timedelta(days=7)).timestamp())

    monkeypatch.setattr(gss.stripe.Subscription, "retrieve",
                        lambda sid: suscripcion(trial_end=fin))

    assert gss.align_expiration_with_trial(8701, 87, "sub_87") is True

    e = expiracion(socio_en_prueba)

    assert abs((e - datetime.fromtimestamp(fin)).total_seconds()) < 2, (
        "lo cubierto es la PRUEBA, no la duración entera del plan"
    )


def test_a_paying_subscription_is_left_alone(socio_en_prueba, monkeypatch):
    monkeypatch.setattr(gss.stripe.Subscription, "retrieve",
                        lambda sid: suscripcion(status="active"))

    antes = expiracion(socio_en_prueba)

    assert gss.align_expiration_with_trial(8701, 87, "sub_87") is False
    assert expiracion(socio_en_prueba) == antes


def test_a_stripe_hiccup_never_blocks_the_grant(socio_en_prueba, monkeypatch):
    def roto(sid):
        raise RuntimeError("stripe caído")

    monkeypatch.setattr(gss.stripe.Subscription, "retrieve", roto)

    antes = expiracion(socio_en_prueba)

    assert gss.align_expiration_with_trial(8701, 87, "sub_87") is False
    assert expiracion(socio_en_prueba) == antes, (
        "en caso de duda se queda la concesión generosa, nunca se rompe el alta"
    )


# =========================
# EL CABLEADO
# =========================

def test_the_checkout_sends_the_trial_only_for_recurring_plans():
    source = open("checkout_routes.py", encoding="utf-8").read()

    # Con alias desde que el cobro resuelve también el precio de oferta.
    assert (
        "COALESCE(trial_days, 0)" in source
        or "COALESCE(p.trial_days, 0)" in source
    )

    pos = source.index('"trial_period_days"')
    contexto = source[max(0, pos - 600):pos]

    assert "if plan_es_recurrente:" in contexto, (
        "el trial fuera de una suscripción no existe para Stripe"
    )
    assert "plan_trial_days > 0" in source


def test_the_grant_path_aligns_with_the_trial():
    source = open("stripe_handler.py", encoding="utf-8").read()

    pos_attach = source.index("attach_subscription_to_member(\n                user_id")

    assert "align_expiration_with_trial(" in source[pos_attach:pos_attach + 900], (
        "sin el recorte, cancelar el día 2 de la prueba deja 30 días gratis"
    )


def test_the_wizard_asks_for_trial_only_after_saying_yes_to_renewal():
    source = open("admin_input_handler.py", encoding="utf-8").read()

    assert "¿DÍAS DE PRUEBA GRATIS?" in source
    assert "trial_days" in source

    # El paso 7 solo se alcanza desde el SÍ del paso 6.
    pos_si = source.index('context.user_data["new_plan"]["is_recurring"] = True')
    trozo = source[pos_si:pos_si + 400]

    assert '"add_plan_step"] = 7' in trozo
