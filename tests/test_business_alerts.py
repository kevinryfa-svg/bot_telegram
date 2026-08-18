"""
Alertas de negocio: el propietario se entera del problema HOY, no el lunes.

Las tres reglas: solo problemas REALES (umbral en todo; por debajo,
silencio), base mínima para hablar de porcentajes (pasar de 1 pago a 0 no
es una crisis), y una alerta por periodo (idempotente ante redeploys).
"""

import asyncio

import pytest

import business_alert_service as bas
from audit_log_service import log_event


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
    """Una comunidad viva (87) con dueño (707) y sin ruido previo en logs."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM audit_logs WHERE group_id IN (87, 86)")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (87, 'VIP Alertas', -1087, TRUE)"
        )
        cur.execute(
            "INSERT INTO admins (user_id, group_id, role, is_active) "
            "VALUES (707, 87, 'GROUP_OWNER', TRUE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (8701, 87, 1500, 'EUR', 'paid', 'Mensual')"
        )

    return db


def registrar_fallidos(n, group_id=87):
    for i in range(n):
        log_event(
            "group_subscription_payment_failed",
            category="payment", severity="warning", scope="group",
            group_id=group_id, actor_user_id=9000 + i,
            message="Cobro de renovación fallido; Stripe reintentará.",
        )


def registrar_bajas(n, group_id=87):
    for i in range(n):
        log_event(
            "group_subscription_autorenew_off",
            category="payment", severity="info", scope="group",
            group_id=group_id, actor_user_id=9100 + i,
            message="Renovación apagada.",
        )


def test_a_streak_of_failed_charges_alerts_today_not_monday(comunidad):
    registrar_fallidos(3)

    contexto = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto))

    assert resumen["sent"] == 1
    chat_id, texto, teclado = contexto.bot.enviados[0]

    assert chat_id == 707
    assert "🚨 3 cobros de renovación fallidos" in texto
    assert "VIP Alertas" in texto

    botones = [b for fila in teclado.inline_keyboard for b in fila]
    assert any(b.callback_data == "owner_panel_revenue" for b in botones)

    # El mismo día, el job vuelve a pasar: nada se duplica.
    contexto2 = FakeContext()
    resumen2 = asyncio.run(bas.process_business_alerts(contexto2))

    assert resumen2["sent"] == 0
    assert not contexto2.bot.enviados


def test_below_the_threshold_there_is_silence(comunidad):
    registrar_fallidos(2)
    registrar_bajas(2)

    contexto = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto))

    assert resumen["sent"] == 0, (
        "dos fallidos sueltos son tarjetas concretas, no una racha; una "
        "alerta que salta por ruido enseña al dueño a ignorarlas"
    )


def test_a_real_revenue_drop_alerts_with_the_numbers(comunidad):
    with comunidad.conn.cursor() as cur:
        # Semana de referencia: 3 pagos, 60 EUR. Últimos 7 días: 30 EUR
        # (15 de este insert + los 15 del pago de hoy del fixture).
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            "(8702, 87, 2000, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '10 days'), "
            "(8703, 87, 2000, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '9 days'), "
            "(8704, 87, 2000, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '8 days'), "
            "(8705, 87, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '2 days')"
        )

    assert bas.detect_revenue_drop(87) == (3000, 6000, 50, "EUR")

    contexto = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto))

    assert resumen["sent"] == 1
    texto = contexto.bot.enviados[0][1]

    assert "caen un 50%" in texto
    assert "30.00 EUR" in texto
    assert "60.00 EUR" in texto


def test_one_payment_to_zero_is_a_tuesday_not_a_crisis(comunidad):
    with comunidad.conn.cursor() as cur:
        # Solo 2 pagos en la semana de referencia: base insuficiente.
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            "(8702, 87, 2000, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '10 days'), "
            "(8703, 87, 2000, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '9 days')"
        )

    assert bas.detect_revenue_drop(87) is None, (
        "sin base mínima de pagos el porcentaje es ruido con signo"
    )


def test_a_cancellation_spike_alerts_and_stripe_and_paypal_count_together(comunidad):
    registrar_bajas(3)

    contexto = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto))

    assert resumen["sent"] == 1
    texto = contexto.bot.enviados[0][1]

    assert "🔻 3 personas han apagado su renovación" in texto

    # Y la fuente PayPal existe: el handler de cancelación registra el
    # MISMO evento que Stripe, para que el detector cuente ambos mundos.
    source = open("mysub_callbacks.py", encoding="utf-8").read()
    pos = source.index('data.startswith("mysub_pprenewoff_yes_")')
    trozo = source[pos:pos + 2000]

    assert '"group_subscription_autorenew_off"' in trozo


def test_the_kill_switch_and_the_schedule(comunidad, monkeypatch):
    registrar_fallidos(5)

    monkeypatch.setattr(bas, "ALERTS_ENABLED", False)

    contexto = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto))

    assert resumen["sent"] == 0
    assert not contexto.bot.enviados

    source = open("main.py", encoding="utf-8").read()
    assert "schedule_business_alerts_job(telegram_app)" in source

    pos = source.index("def schedule_business_alerts_job")
    trozo = source[pos:pos + 900]
    assert "run_repeating" in trozo


# =========================
# SOCIOS PAGANDO Y FUERA
# =========================
# Cuando alguien se queda fuera con el acceso vivo, el bot le manda un enlace.
# A quien nunca abrió el bot no se le puede escribir, y eso quedaba registrado
# donde nadie mira. Esa persona está pagando y sin poder entrar.

def registrar_fuera(n, group_id=87):
    for i in range(n):
        log_event(
            "member_return_offer_failed",
            category="access", severity="warning", scope="group",
            group_id=group_id, actor_user_id=9200 + i, target_user_id=9200 + i,
            message="Socio con acceso vivo fuera del grupo y sin poder avisarle.",
        )


def test_a_paying_member_locked_out_reaches_the_owner(comunidad):
    registrar_fuera(1)

    contexto = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto))

    assert resumen["sent"] == 1

    _chat, texto, _teclado = contexto.bot.enviados[0]

    assert "1 persona con acceso pagado" in texto
    assert "no hemos podido avisarles" in texto
    assert "veto puesto por error" in texto, (
        "el propietario es el único que puede arreglarlo: hay que decirle cómo"
    )


def test_the_wording_holds_up_in_plural(comunidad):
    registrar_fuera(3)

    contexto = FakeContext()
    asyncio.run(bas.process_business_alerts(contexto))

    texto = contexto.bot.enviados[0][1]

    assert "3 personas con acceso pagado" in texto
    assert "Están pagando" in texto


def test_the_same_week_does_not_repeat_it(comunidad):
    registrar_fuera(2)

    contexto = FakeContext()
    asyncio.run(bas.process_business_alerts(contexto))

    contexto2 = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto2))

    assert resumen["sent"] == 0, (
        "es una alerta semanal: repetirla cada seis horas la vuelve ruido"
    )


def test_one_person_counts_once_however_many_attempts(comunidad):
    """Varios intentos fallidos con la misma persona son una persona."""

    for _ in range(4):
        log_event(
            "member_return_offer_failed",
            category="access", severity="warning", scope="group",
            group_id=87, actor_user_id=9299, target_user_id=9299,
            message="Sin poder avisarle.",
        )

    assert bas.detect_paying_members_locked_out(87) == 1


# =========================
# EL PLAN QUE COBRA Y NO ENTREGA
# =========================
# En producción, la única comunidad vendible del sistema tenía un plan de
# 1.300.000 días: el cobro se niega a convertir eso en acceso, así que se
# cobraba y no se entregaba. Desde que el escaparate mira el mismo techo, ese
# plan ya no se ofrece — y su comunidad deja de vender del todo. Callarse eso
# sería cambiar un fallo ruidoso por uno silencioso.

def crear_plan(dias, group_id=87, price="price_x", amount=15):
    from db import conn as db_conn

    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) "
            "VALUES (%s, 'Plan', %s, %s, %s, %s, 'EUR', TRUE)",
            (group_id, price, price, dias, amount)
        )


def test_a_plan_the_charge_would_refuse_reaches_the_owner(comunidad):
    crear_plan(1300000)

    contexto = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto))

    assert resumen["sent"] == 1

    chat, texto, _teclado = contexto.bot.enviados[0]

    assert chat == 707, "va al propietario, que es quien puede corregirlo"
    assert "1300000 días" in texto, (
        "el número exacto: es lo que va a buscar en la pantalla de planes"
    )
    assert str(bas.MAX_PLAN_DURATION_DAYS) in texto, "y cuál es el máximo"
    assert "no está vendiendo" in texto, (
        "la consecuencia de hoy, que es dejar de vender, no la de ayer"
    )
    assert "o 0 si querías acceso permanente" in texto, (
        "el arreglo concreto: quien escribe 1.300.000 quería decir «siempre»"
    )


def test_a_healthy_plan_says_nothing(comunidad):
    crear_plan(30)

    contexto = FakeContext()
    resumen = asyncio.run(bas.process_business_alerts(contexto))

    assert resumen["sent"] == 0, "un catálogo sano no genera ruido"


def test_the_exact_ceiling_is_not_an_alert(comunidad):
    """El límite exacto se entrega, así que no hay nada que avisar."""

    crear_plan(bas.MAX_PLAN_DURATION_DAYS)

    assert bas.detect_undeliverable_plans(87) is None

    crear_plan(bas.MAX_PLAN_DURATION_DAYS + 1, price="price_y")

    assert bas.detect_undeliverable_plans(87) == (
        1, bas.MAX_PLAN_DURATION_DAYS + 1
    )


def test_an_inactive_broken_plan_is_not_worth_waking_anyone(comunidad):
    from db import conn as db_conn

    crear_plan(1300000)

    with db_conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_active=FALSE WHERE group_id=87")

    assert bas.detect_undeliverable_plans(87) is None, (
        "un plan apagado no se ofrece ni se cobra: avisar de él es ruido"
    )


def test_it_is_said_once_a_week_not_once_a_run(comunidad):
    crear_plan(1300000)

    primero = asyncio.run(bas.process_business_alerts(FakeContext()))
    segundo = asyncio.run(bas.process_business_alerts(FakeContext()))

    assert primero["sent"] == 1
    assert segundo["sent"] == 0, (
        "un redespliegue no puede convertir el aviso en spam"
    )
