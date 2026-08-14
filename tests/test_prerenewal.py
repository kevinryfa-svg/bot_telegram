"""
El aviso pre-cobro de las suscripciones, y el fin del aviso equivocado.

Con la renovación automática, "tu acceso caduca, renueva" es MENTIRA para un
suscriptor: se le va a cobrar solo. El aviso correcto es el contrario —cuánto,
cuándo y dónde cancelar— y es el que reduce disputas y chargebacks.

Dos mitades, las dos aquí:
  1. El aviso nuevo llega solo a quien tiene renovación VIVA (se pregunta a la
     fuente), una sola vez por cobro, con su precio real y el botón al
     interruptor.
  2. Los avisos viejos EXCLUYEN a los suscriptores — y vuelven a incluirlos
     cuando la suscripción muere, porque entonces la caducidad vuelve a ser
     verdad.
"""

import asyncio
from datetime import datetime

import pytest

import renewal_service as rs


class FakeBot:
    def __init__(self):
        self.enviados = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None):
        self.enviados.append((chat_id, text, reply_markup))
        return True


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()


@pytest.fixture
def comunidad(clean_db, monkeypatch):
    """
    Cuatro socios de una comunidad con renovación en juego:

      9301  suscriptor Stripe, cobro en 2 días      → aviso pre-cobro
      9302  pago único, caduca en 2 días            → aviso clásico de renovar
      9303  suscriptor PayPal, cobro en 2 días      → aviso pre-cobro
      9304  suscriptor Stripe, cobro en 10 días     → fuera de ventana
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (93, 'VIP Aviso', -1093, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) VALUES "
            "(9301, 93, NOW() + INTERVAL '2 days', TRUE, 'sub_93'), "
            "(9302, 93, NOW() + INTERVAL '2 days', TRUE, NULL), "
            "(9304, 93, NOW() + INTERVAL '10 days', TRUE, 'sub_94x')"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (9303, 93, NOW() + INTERVAL '2 days', TRUE)"
        )
        cur.execute(
            "INSERT INTO payment_transactions (provider, status, payment_scope, "
            "purchase_type, user_id, group_id, external_checkout_id) "
            "VALUES ('paypal', 'paid', 'platform', 'group_access', 9303, 93, 'I-SUB93')"
        )
        # El precio real que paga 9301: su último cobro, no el precio de lista.
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (9301, 93, 1500, 'EUR', 'paid', 'Mensual')"
        )

    # El estado vivo de las renovaciones, controlable por cada prueba.
    estados = {
        "stripe": {"cancel_at_period_end": False},
        "paypal": {"activa": True, "cancelada": False},
    }

    def estado_stripe(user_id, group_id):
        if user_id in (9301, 9304):
            return dict(estados["stripe"])
        return None

    def estado_paypal(user_id, group_id):
        if user_id == 9303:
            return dict(estados["paypal"])
        return None

    monkeypatch.setattr(
        "group_subscription_service.fetch_renewal_state", estado_stripe
    )
    monkeypatch.setattr(
        "paypal_subscription_controls.fetch_paypal_renewal_state", estado_paypal
    )

    return {"db": db, "estados": estados}


# =========================
# LOS CANDIDATOS
# =========================

def test_only_subscribers_inside_the_window_are_candidates(comunidad):
    filas = rs.fetch_upcoming_autorenewals()

    quienes = {u for u, *_ in filas}

    assert quienes == {9301, 9303}, (
        "9302 no es suscriptor y 9304 está fuera de la ventana"
    )


def test_the_old_reminders_no_longer_lie_to_subscribers(comunidad):
    """El aviso clásico de renovar excluye a quien se le cobra solo."""

    filas = rs.fetch_accesses_expiring(rs.RENEWAL_STAGE_EARLY)

    quienes = {u for u, *_ in filas}

    assert 9302 in quienes, "al de pago único hay que seguir avisándole"
    assert 9301 not in quienes and 9303 not in quienes, (
        "a un suscriptor no se le puede pedir que renueve a mano"
    )


def test_when_the_subscription_dies_the_old_reminders_come_back(comunidad):
    """La exclusión sigue a la vida real: sin ancla, vuelve el aviso clásico."""

    db = comunidad["db"]

    with db.conn.cursor() as cur:
        # La muerte de la suscripción Stripe limpia el ancla…
        cur.execute(
            "UPDATE users SET stripe_subscription_id=NULL WHERE user_id=9301"
        )
        # …y la cancelación PayPal saca a la transacción de 'paid'.
        cur.execute(
            "UPDATE payment_transactions SET status='cancelled' WHERE user_id=9303"
        )

    quienes = {u for u, *_ in rs.fetch_accesses_expiring(rs.RENEWAL_STAGE_EARLY)}

    assert {9301, 9302, 9303} <= quienes


# =========================
# EL ENVÍO
# =========================

def test_the_notice_says_price_date_and_offers_the_switch(comunidad):
    contexto = FakeContext()

    resumen = asyncio.run(rs.send_prerenewal_stage(contexto))

    assert resumen["sent"] == 2

    por_usuario = {c: (t, m) for c, t, m in contexto.bot.enviados}

    texto, teclado = por_usuario[9301]

    assert "se renovará el" in texto
    assert "15.00 EUR" in texto, "el precio es el SUYO: su último cobro"

    with comunidad["db"].conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=9301 AND group_id=93")
        expira = cur.fetchone()[0]

    assert expira.strftime("%d/%m/%Y") in texto

    botones = [b for fila in teclado.inline_keyboard for b in fila]
    assert any(b.callback_data == "mysub_-1093" for b in botones), (
        "el aviso tiene que llevar directo al interruptor"
    )

    # 9303 no tiene pagos registrados: el aviso sale igual, sin importe.
    texto_pp, _ = por_usuario[9303]
    assert "se renovará el" in texto_pp


def test_each_charge_is_announced_exactly_once(comunidad):
    contexto = FakeContext()

    asyncio.run(rs.send_prerenewal_stage(contexto))
    contexto.bot.enviados.clear()

    resumen = asyncio.run(rs.send_prerenewal_stage(contexto))

    assert resumen["sent"] == 0
    assert not contexto.bot.enviados


def test_who_already_cancelled_is_not_told_about_a_charge(comunidad):
    """Avisar de un cobro que no va a salir sería mentir en sentido contrario."""

    comunidad["estados"]["stripe"]["cancel_at_period_end"] = True
    comunidad["estados"]["paypal"]["activa"] = False

    contexto = FakeContext()

    resumen = asyncio.run(rs.send_prerenewal_stage(contexto))

    assert resumen["sent"] == 0
    assert resumen["skipped"] == 2


def test_a_cancelled_skip_does_not_burn_the_notice(comunidad):
    """Si reactiva antes de la fecha, el aviso tiene que salir entonces."""

    comunidad["estados"]["stripe"]["cancel_at_period_end"] = True
    comunidad["estados"]["paypal"]["activa"] = False

    asyncio.run(rs.send_prerenewal_stage(FakeContext()))

    comunidad["estados"]["stripe"]["cancel_at_period_end"] = False
    comunidad["estados"]["paypal"]["activa"] = True

    contexto = FakeContext()
    resumen = asyncio.run(rs.send_prerenewal_stage(contexto))

    assert resumen["sent"] == 2


def test_the_job_runs_prerenewal_first(comunidad, monkeypatch):
    """El pre-cobro es el único aviso con fecha límite dura: va el primero."""

    orden = []

    async def falso_pre(context):
        orden.append("prerenewal")
        return {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    async def falso_stage(context, stage):
        orden.append(stage)
        return {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    monkeypatch.setattr(rs, "send_prerenewal_stage", falso_pre)
    monkeypatch.setattr(rs, "send_renewal_stage", falso_stage)

    asyncio.run(rs.process_renewal_reminders(FakeContext()))

    assert orden[0] == "prerenewal"
