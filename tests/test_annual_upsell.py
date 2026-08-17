"""
El upsell al plan anual: al que ya demostró quedarse, más valor.

Las reglas: 3+ pagos (dos renovaciones demostradas), plan anual REAL de su
comunidad en su misma moneda, ahorro VERDADERO frente a 12 meses de su
precio actual (ofrecer un "ahorro" inventado quema la confianza), y una
sola vez para siempre. Y la salvaguarda que este upsell exigía: comprar el
anual teniendo el mensual apaga la suscripción vieja — sin cobros dobles.
"""

import asyncio

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
def comunidad(clean_db):
    """
    8001: 3 pagos de 15 EUR → candidato (anual 120 EUR ahorra un 33%).
    8002: solo 2 pagos → aún no.
    8003: 3 pagos pero sin renovación automática → no.
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (80, 'VIP Upsell', -1080, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, "
            "is_active, payment_provider, is_recurring) VALUES "
            "(80, 'Anual', 120, 'EUR', 365, TRUE, 'stripe', TRUE), "
            "(80, 'Mensual', 15, 'EUR', 30, TRUE, 'stripe', TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) VALUES "
            "(8001, 80, NOW() + INTERVAL '20 days', TRUE, 'sub_8001'), "
            "(8002, 80, NOW() + INTERVAL '20 days', TRUE, 'sub_8002')"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (8003, 80, NOW() + INTERVAL '20 days', TRUE)"
        )

        for user_id, pagos in ((8001, 3), (8002, 2), (8003, 3)):
            for i in range(pagos):
                cur.execute(
                    "INSERT INTO payments (user_id, group_id, amount, currency, "
                    "status, plan, payment_date) "
                    "VALUES (%s, 80, 1500, 'EUR', 'paid', 'Mensual', "
                    "NOW() - (%s || ' days')::interval)",
                    (user_id, 30 * i),
                )

    return db


def test_only_proven_subscribers_with_real_savings_qualify(comunidad):
    filas = rs.fetch_annual_upsell_candidates()

    assert [f[0] for f in filas] == [8001], (
        "8002 aún no renovó dos veces y 8003 no tiene renovación automática"
    )


def test_a_fake_saving_kills_the_offer(comunidad):
    """Anual a 200 EUR contra 15x12=180: no hay ahorro, no hay oferta."""

    with comunidad.conn.cursor() as cur:
        cur.execute("UPDATE plans SET amount=200 WHERE name='Anual'")

    assert rs.fetch_annual_upsell_candidates() == []


def test_without_an_annual_plan_there_is_silence(comunidad):
    with comunidad.conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_active=FALSE WHERE name='Anual'")

    assert rs.fetch_annual_upsell_candidates() == []


def test_the_offer_says_the_saving_and_shows_once(comunidad):
    contexto = FakeContext()

    resumen = asyncio.run(rs.send_annual_upsell_stage(contexto))

    assert resumen["sent"] == 1

    chat, texto, teclado = contexto.bot.enviados[0]

    assert chat == 8001
    assert "120.00 EUR" in texto
    assert "33%" in texto, "el ahorro real: (180-120)/180"
    assert "se apaga sola" in texto, (
        "hay que decirle que no habrá cobros dobles: es la objeción número 1"
    )

    botones = [b for fila in teclado.inline_keyboard for b in fila]
    assert any(b.callback_data == "marketplace_group_80" for b in botones)

    # Para siempre: ni en la siguiente pasada ni nunca.
    resumen2 = asyncio.run(rs.send_annual_upsell_stage(FakeContext()))
    assert resumen2["sent"] == 0


def test_buying_annual_turns_off_the_monthly_subscription(comunidad, monkeypatch):
    """La salvaguarda del doble cobro: el ancla apaga la suscripción vieja."""

    import group_subscription_service as gss

    apagadas = []
    monkeypatch.setattr(gss.stripe.Subscription, "modify",
                        lambda sid, **k: apagadas.append((sid, k)) or {"id": sid})

    gss.attach_subscription_to_member(8001, 80, "sub_anual_nueva", "cus_1")

    assert apagadas == [("sub_8001", {"cancel_at_period_end": True})], (
        "sin esto, la mensual y la anual cobrarían a la vez para siempre"
    )

    # Y anclar la MISMA suscripción (reintento de webhook) no apaga nada.
    apagadas.clear()
    gss.attach_subscription_to_member(8001, 80, "sub_anual_nueva", "cus_1")
    assert not apagadas


def test_the_upsell_rides_the_renewal_job():
    source = open("renewal_service.py", encoding="utf-8").read()

    pos = source.index("async def process_renewal_reminders")
    assert "send_annual_upsell_stage(context)" in source[pos:pos + 1500]
