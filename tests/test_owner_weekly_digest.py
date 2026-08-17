"""
El resumen semanal del propietario: su negocio en un mensaje, sin pedirlo.

Las tres reglas: semanas de CALENDARIO (lunes-a-domingo contra
lunes-a-domingo, no ventanas móviles), UNA vez por semana (idempotente ante
redeploys), y solo comunidades vivas (a un grupo muerto no se le escribe).
"""

import asyncio

import pytest

import owner_weekly_digest_service as owd


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
def comunidades(clean_db):
    """
    Dos comunidades con dueño: la 83 viva (pagos y socios) y la 82 muerta
    (sin un solo pago ni socio activo). Solo la viva genera resumen.
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) VALUES "
            "(83, 'VIP Semana', -1083, TRUE), (82, 'Muerta', -1082, TRUE)"
        )
        cur.execute(
            "INSERT INTO admins (user_id, group_id, role, is_active) VALUES "
            "(701, 83, 'GROUP_OWNER', TRUE), (702, 82, 'GROUP_OWNER', TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, created_at) VALUES "
            # Alta de la semana pasada, activa.
            "(8301, 83, NOW() + INTERVAL '20 days', TRUE, date_trunc('week', NOW()) - INTERVAL '5 days'), "
            # Caducado la semana pasada sin volver.
            "(8302, 83, date_trunc('week', NOW()) - INTERVAL '2 days', FALSE, NOW() - INTERVAL '60 days')"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            # Semana pasada: 30 EUR en dos pagos; uno es renovación (segundo de 8301).
            "(8301, 83, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '40 days'), "
            "(8301, 83, 1500, 'EUR', 'paid', 'Mensual', date_trunc('week', NOW()) - INTERVAL '5 days'), "
            "(8303, 83, 1500, 'EUR', 'paid', 'Mensual', date_trunc('week', NOW()) - INTERVAL '3 days'), "
            # Semana anterior: 15 EUR.
            "(8304, 83, 1500, 'EUR', 'paid', 'Mensual', date_trunc('week', NOW()) - INTERVAL '10 days'), "
            # Esta semana (no cuenta: la semana aún no está completa).
            "(8305, 83, 9000, 'EUR', 'paid', 'Anual', NOW())"
        )

    return db


def test_only_living_communities_get_a_digest(comunidades):
    filas = owd.fetch_owned_active_groups()

    assert [(o, g) for o, g, _n in filas] == [(701, 83)], (
        "la comunidad muerta no genera resumen: el spam no es información"
    )


def test_the_numbers_are_calendar_weeks_not_rolling_windows(comunidades):
    numeros = owd.fetch_week_numbers(83)

    assert numeros["ingresos"] == [("EUR", 3000, 1500)], (
        "semana pasada completa (30) contra la anterior (15); el pago de ESTA "
        "semana no cuenta: la semana aún no está terminada"
    )
    assert numeros["pagos"] == 2
    assert numeros["renovaciones"] == 1, "el segundo pago de 8301 es renovación"
    assert numeros["altas"] == 1
    assert numeros["caducados"] == 1


def test_the_digest_reads_like_a_business_summary(comunidades):
    texto = owd.build_weekly_digest_text(83, "VIP Semana")

    assert "📬 Tu semana en VIP Semana" in texto
    assert "30.00 EUR (+100% vs anterior)" in texto
    assert "renovaciones: 1" in texto
    assert "Altas: 1" in texto
    assert "Caducados sin volver: 1" in texto
    assert "Entrega de accesos:" in texto


def test_mondays_job_sends_once_even_after_a_redeploy(comunidades):
    contexto = FakeContext()

    resumen = asyncio.run(owd.process_weekly_digests(contexto))

    assert resumen["sent"] == 1
    assert contexto.bot.enviados[0][0] == 701

    # El teclado lleva directo al panel de ingresos.
    teclado = contexto.bot.enviados[0][2]
    botones = [b for fila in teclado.inline_keyboard for b in fila]
    assert any(b.callback_data == "owner_panel_revenue" for b in botones)

    # El "redeploy" del mismo lunes: nada se duplica.
    contexto2 = FakeContext()
    resumen2 = asyncio.run(owd.process_weekly_digests(contexto2))

    assert resumen2["sent"] == 0
    assert not contexto2.bot.enviados


def test_a_blocked_owner_does_not_stop_the_rest(comunidades, monkeypatch):
    with comunidades.conn.cursor() as cur:
        # Revivir la 82 para tener dos destinatarios.
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (8201, 82, 1500, 'EUR', 'paid', 'Mensual')"
        )

    class BotConVetado(FakeBot):
        async def send_message(self, chat_id=None, text=None, reply_markup=None):
            if chat_id == 701:
                raise RuntimeError("Forbidden: bot was blocked by the user")
            return await super().send_message(chat_id, text, reply_markup)

    contexto = FakeContext()
    contexto.bot = BotConVetado()

    resumen = asyncio.run(owd.process_weekly_digests(contexto))

    assert resumen["failed"] == 1
    assert resumen["sent"] == 1, "el propietario que bloqueó no frena al resto"


def test_the_job_is_scheduled_on_mondays():
    source = open("main.py", encoding="utf-8").read()

    pos = source.index("def schedule_owner_weekly_digest")
    trozo = source[pos:pos + 900]

    assert "run_daily" in trozo
    assert "days=(1,)" in trozo, (
        "en PTB 22 los días van 0-6 domingo-sábado: el lunes es el 1"
    )
    assert "schedule_owner_weekly_digest(telegram_app)" in source
