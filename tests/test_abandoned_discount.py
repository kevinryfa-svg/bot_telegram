"""
El segundo toque de la recuperación de carrito: 24 h después, con dientes.

El primer recordatorio (2 h) es amable; este llega solo si aquel no
funcionó, y trae un cupón PERSONAL del 20%: un solo uso, caduca en 24 h,
acotado a los productos de la comunidad. Sin cupón posible (comunidad sin
planes de Stripe) no hay mensaje: un segundo aviso sin nada nuevo que
ofrecer es ruido.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

import abandoned_checkout_service as acs
import stripe_coupon_service as scs


class FakeBot:
    def __init__(self):
        self.enviados = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None):
        self.enviados.append((chat_id, text))
        return True


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()


@pytest.fixture
def carrito(clean_db, monkeypatch):
    """
    Tres intentos abandonados:
      501  con primer recordatorio hace 25 h  → candidato
      502  con primer recordatorio hace 1 h   → aún no (ventana)
      503  sin primer recordatorio            → aún no (orden de toques)
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (86, 'VIP Carrito', -1086, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, "
            "is_active, payment_provider, stripe_product_id, stripe_price_id) "
            "VALUES (86, 'Mensual', 15, 'EUR', 30, TRUE, 'stripe', 'prod_86', 'price_86')"
        )
        cur.execute(
            "INSERT INTO payment_transactions (id, provider, status, payment_scope, "
            "purchase_type, user_id, group_id, external_checkout_id, created_at) VALUES "
            "(501, 'stripe', 'pending', 'platform', 'group_access', 8601, 86, 'cs_501', NOW() - INTERVAL '2 days'), "
            "(502, 'stripe', 'pending', 'platform', 'group_access', 8602, 86, 'cs_502', NOW() - INTERVAL '3 hours'), "
            "(503, 'stripe', 'pending', 'platform', 'group_access', 8603, 86, 'cs_503', NOW() - INTERVAL '2 days')"
        )
        cur.execute(
            "INSERT INTO abandoned_checkout_reminders (transaction_id, user_id, group_id, sent_at) VALUES "
            "(501, 8601, 86, NOW() - INTERVAL '25 hours'), "
            "(502, 8602, 86, NOW() - INTERVAL '1 hour')"
        )

    creados = {"coupons": [], "promos": []}

    monkeypatch.setattr(
        scs.stripe.Coupon, "create",
        lambda **k: creados["coupons"].append(k) or {"id": "cup_r"}
    )
    monkeypatch.setattr(
        scs.stripe.PromotionCode, "create",
        lambda **k: creados["promos"].append(k) or {"id": "promo_r"}
    )

    return {"db": db, "creados": creados}


def test_only_the_cold_attempt_with_a_first_reminder_qualifies(carrito):
    filas = acs.fetch_discount_candidates()

    assert [f[0] for f in filas] == [501], (
        "502 está en ventana del primer toque y 503 aún no lo recibió"
    )


def test_the_personal_coupon_has_teeth(carrito):
    contexto = FakeContext()

    resumen = asyncio.run(acs.process_abandoned_discounts(contexto))

    assert resumen["sent"] == 1

    cupon = carrito["creados"]["coupons"][0]
    promo = carrito["creados"]["promos"][0]

    assert cupon["percent_off"] == 20
    assert cupon["applies_to"] == {"products": ["prod_86"]}, (
        "el cupón de recuperación también respeta el perímetro"
    )
    assert promo["code"] == "REGRESA501", "un código por intento, legible"
    assert promo["max_redemptions"] == 1, "personal: compartirlo no sirve"

    import time as time_mod

    ahora = int(time_mod.time())
    assert 0 < promo["expires_at"] - ahora <= 24 * 3600 + 60
    assert 0 < cupon["redeem_by"] - ahora <= 24 * 3600 + 60

    chat, texto = contexto.bot.enviados[0]
    assert chat == 8601
    assert "REGRESA501" in texto
    assert "20%" in texto
    assert "24 horas" in texto


def test_each_attempt_gets_the_discount_exactly_once(carrito):
    asyncio.run(acs.process_abandoned_discounts(FakeContext()))

    contexto = FakeContext()
    resumen = asyncio.run(acs.process_abandoned_discounts(contexto))

    assert resumen["sent"] == 0
    assert not contexto.bot.enviados


def test_without_stripe_plans_there_is_no_second_touch(carrito):
    with carrito["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_active=FALSE WHERE group_id=86")

    assert acs.fetch_discount_candidates() == []


def test_a_failed_coupon_neither_marks_nor_messages(carrito, monkeypatch):
    """Sin cupón no hay mensaje, y el intento queda libre para reintentarse."""

    def roto(**k):
        raise RuntimeError("stripe caído")

    monkeypatch.setattr(scs.stripe.Coupon, "create", roto)

    contexto = FakeContext()
    resumen = asyncio.run(acs.process_abandoned_discounts(contexto))

    assert resumen["sent"] == 0 and resumen["skipped"] == 1
    assert not contexto.bot.enviados

    # La siguiente pasada lo vuelve a intentar.
    assert [f[0] for f in acs.fetch_discount_candidates()] == [501]


def test_who_paid_after_the_reminder_is_left_alone(carrito):
    with carrito["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_transactions (provider, status, payment_scope, "
            "purchase_type, user_id, group_id, created_at) "
            "VALUES ('stripe', 'paid', 'platform', 'group_access', 8601, 86, NOW())"
        )

    assert acs.fetch_discount_candidates() == []


def test_the_second_touch_rides_the_same_scheduled_job():
    source = open("abandoned_checkout_service.py", encoding="utf-8").read()

    pos = source.index("async def process_abandoned_checkouts")
    assert "await process_abandoned_discounts(context)" in source[pos:], (
        "el segundo toque tiene que viajar en el job ya programado"
    )
