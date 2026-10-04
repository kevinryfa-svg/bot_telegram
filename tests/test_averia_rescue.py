"""
El rescate de quienes pulsaron «pagar» durante la avería del cobro.

Es un mensaje a clientes de verdad, en nombre del negocio, pidiendo perdón. Lo
que no puede fallar aquí no es que salga: es a QUIÉN NO le sale. Quien ya pagó,
quien tiene acceso, quien está vetado, quien pidió que no le escribieran, quien
bloqueó el bot, y quien ya lo recibió.
"""

import asyncio

import pytest

import averia_rescue_service as ars


@pytest.fixture
def averia(clean_db, monkeypatch):
    """
    Siete personas pulsaron «💳 Tarjeta» durante la avería:

      8001  nadie le ha vuelto a escribir             → SÍ
      8002  pagó después                              → no
      8003  tiene acceso vivo                         → no
      8004  vetado                                    → no
      8005  pidió no recibir avisos                   → no
      8006  bloqueó el bot                            → no
      8007  pulsó el botón de una OFERTA              → SÍ

    Y dos que no cuentan:
      8008  pulsó DESPUÉS del arreglo (ya funcionaba) → no
      8009  pulsó otra cosa, no un botón de pago      → no
    """

    monkeypatch.setattr(ars, "AVERIA_DESDE", "2026-08-15")
    monkeypatch.setattr(ars, "AVERIA_HASTA", "2026-10-04 08:50")
    monkeypatch.setattr(ars, "RESCATE_PAUSA_SEGUNDOS", 0)

    db = clean_db

    with db.conn.cursor() as cur:

        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible) VALUES (81, 'StarsVip', -1081, TRUE, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(811, 81, 'Acceso 7 días', 'price_811', 'price_811', 7, 9, 'EUR', TRUE)"
        )
        cur.execute(
            "INSERT INTO plan_offers (plan_id, stripe_price_id, amount, percent, "
            "starts_at, ends_at) VALUES (811, 'price_oferta_811', 3.60, 60, "
            "'2026-09-20', '2026-09-27')"
        )

        pulsa = (
            "INSERT INTO bot_user_events (user_id, event_type, event_key, "
            "created_at) VALUES (%s, 'callback', %s, %s)"
        )

        for uid in (8001, 8002, 8003, 8004, 8005, 8006):
            cur.execute(pulsa, (uid, "price_811", "2026-09-20 12:00"))

        cur.execute(pulsa, (8007, "price_oferta_811", "2026-09-22 12:00"))
        cur.execute(pulsa, (8008, "price_811", "2026-10-04 12:00"))
        cur.execute(pulsa, (8009, "group_81", "2026-09-20 12:00"))

        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, "
            "payment_date) VALUES (8002, 81, 900, 'EUR', 'paid', '2026-09-25')"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (8003, 81, NOW() + INTERVAL '20 days', TRUE)"
        )
        cur.execute("INSERT INTO banned_users (user_id, group_id) VALUES (8004, 81)")
        cur.execute(
            "INSERT INTO user_reengagement (user_id, opted_out) VALUES (8005, TRUE)"
        )
        cur.execute(
            "INSERT INTO user_reengagement (user_id, is_blocked) VALUES (8006, TRUE)"
        )

    return db


def _ids():
    return {fila[0] for fila in ars.fetch_afectados()}


def test_only_the_people_who_got_the_error_and_still_want_in(averia):
    assert _ids() == {8001, 8007}


def test_an_offer_button_is_traced_back_to_its_community(averia):
    """El 8007 pulsó el precio de una OFERTA, que no está en la tabla de planes."""

    fila = [f for f in ars.fetch_afectados() if f[0] == 8007][0]

    assert fila[1] == 81
    assert fila[2] == "StarsVip"


def test_whoever_paid_afterwards_is_left_alone(averia):
    assert 8002 not in _ids()


def test_banned_opted_out_and_blocked_are_respected(averia):
    assert not {8004, 8005, 8006} & _ids()


def test_clicks_after_the_fix_are_not_apologised_for(averia):
    assert 8008 not in _ids()


class FakeBot:
    def __init__(self, falla_para=()):
        self.enviados = []
        self.falla_para = set(falla_para)

    async def send_message(self, chat_id=None, text=None, reply_markup=None):
        if chat_id in self.falla_para:
            raise Exception("Forbidden: bot was blocked by the user")
        self.enviados.append((chat_id, text, reply_markup))


def test_the_message_tells_the_truth_and_goes_straight_to_paying(averia):
    bot = FakeBot()

    asyncio.run(ars.enviar_rescate(bot))

    textos = {c: t for c, t, _ in bot.enviados}

    assert set(textos) == {8001, 8007}

    texto = textos[8001]

    assert "fallo nuestro" in texto
    assert "No se te cobró nada" in texto
    assert "StarsVip" in texto

    teclado = [m for c, _, m in bot.enviados if c == 8001][0]

    destinos = [b.callback_data for f in teclado.inline_keyboard for b in f]

    assert "group_81" in destinos, "directo a la lista de planes, ya arreglada"
    assert "reengagement_stop" in destinos, "y siempre la forma de pedir que no"


def test_nobody_ever_gets_it_twice(averia):
    """Una disculpa repetida es peor que ninguna."""

    bot = FakeBot()

    asyncio.run(ars.enviar_rescate(bot))
    asyncio.run(ars.enviar_rescate(bot))

    assert len(bot.enviados) == 2
    assert _ids() == set()


def test_who_blocked_the_bot_is_marked_and_not_retried(averia):
    bot = FakeBot(falla_para={8001})

    resumen = asyncio.run(ars.enviar_rescate(bot))

    assert resumen["bloqueados"] == 1
    assert resumen["enviados"] == 1

    with averia.conn.cursor() as cur:
        cur.execute(
            "SELECT is_blocked FROM user_reengagement WHERE user_id = 8001"
        )
        assert cur.fetchone()[0] is True


def test_the_preview_says_how_many_and_shows_the_message(averia):
    texto = ars.build_preview_text()

    assert "2 persona(s)" in texto
    assert "fallo nuestro" in texto, "el operador ve lo que va a salir"
    assert "UN mensaje, una sola vez" in texto


def test_the_send_button_only_exists_when_there_is_someone(averia):
    teclado = ars.build_preview_keyboard()

    destinos = [b.callback_data for f in teclado.inline_keyboard for b in f]

    assert "admin_averia_rescue_send" in destinos

    asyncio.run(ars.enviar_rescate(FakeBot()))

    teclado = ars.build_preview_keyboard()

    destinos = [b.callback_data for f in teclado.inline_keyboard for b in f]

    assert "admin_averia_rescue_send" not in destinos


def test_the_startup_line_says_how_many_are_waiting(averia):
    assert "2 persona(s)" in ars.describe_para_el_arranque()
