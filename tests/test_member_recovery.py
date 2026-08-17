"""
El socio que paga y se queda fuera: devolverle la entrada, en el momento.

Guardian ya detectaba la salida y se lo contaba al propietario. Al que se
queda fuera no se le decía nada — y si su acceso sigue pagado, acaba de
perder lo que está pagando: una devolución esperando a pasar.

Las tres reglas: solo con acceso VIVO (perseguir a un excliente con enlaces
es ganarse un bloqueo), una vez por episodio con enfriamiento, y sin juzgar
el motivo (no se puede saber si salió queriendo o si lo sacaron).
"""

import asyncio

import pytest

import member_recovery_service as mrs


class FakeBot:
    id = 999

    def __init__(self):
        self.mensajes = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None):
        self.mensajes.append((chat_id, text, reply_markup))
        return True


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()


@pytest.fixture
def comunidad(clean_db, monkeypatch):
    """Grupo 98 con un socio pagando (9801) y uno caducado (9802)."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (98, 'VIP Vuelta', -1098, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) VALUES "
            "(9801, 98, NOW() + INTERVAL '20 days', TRUE), "
            "(9802, 98, NOW() - INTERVAL '5 days', FALSE)"
        )

    monkeypatch.setattr(
        mrs, "create_telegram_invite_link",
        lambda token, tgid, **k: "https://t.me/+enlaceNuevo"
    )

    return db


def test_a_paying_member_who_drops_out_gets_a_fresh_link(comunidad):
    contexto = FakeContext()

    enviado = asyncio.run(mrs.offer_return_link(contexto, 9801, 98))

    assert enviado is True

    chat, texto, teclado = contexto.bot.mensajes[0]

    assert chat == 9801
    assert "VIP Vuelta" in texto
    assert "tu acceso sigue activo hasta" in texto
    assert "un solo uso" in texto

    boton = teclado.inline_keyboard[0][0]
    assert boton.url == "https://t.me/+enlaceNuevo"


def test_an_expired_member_is_left_in_peace(comunidad):
    contexto = FakeContext()

    enviado = asyncio.run(mrs.offer_return_link(contexto, 9802, 98))

    assert enviado is False
    assert not contexto.bot.mensajes, (
        "perseguir a un excliente con enlaces es ganarse un bloqueo"
    )


def test_someone_who_hops_in_and_out_is_not_messaged_every_time(comunidad):
    contexto = FakeContext()

    assert asyncio.run(mrs.offer_return_link(contexto, 9801, 98)) is True
    assert asyncio.run(mrs.offer_return_link(contexto, 9801, 98)) is False

    assert len(contexto.bot.mensajes) == 1


def test_after_the_cooldown_the_offer_comes_back(comunidad):
    contexto = FakeContext()

    asyncio.run(mrs.offer_return_link(contexto, 9801, 98))

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "UPDATE member_return_offers SET sent_at = NOW() - INTERVAL '30 days' "
            "WHERE user_id=9801"
        )

    assert asyncio.run(mrs.offer_return_link(contexto, 9801, 98)) is True, (
        "un episodio nuevo semanas después sí merece su enlace"
    )


def test_without_a_link_there_is_no_silence(comunidad, monkeypatch):
    """Si Telegram no da enlace, el mensaje sale igual: el socio tiene que
    saber que su acceso sigue vivo."""

    monkeypatch.setattr(
        mrs, "create_telegram_invite_link",
        lambda token, tgid, **k: None
    )

    contexto = FakeContext()

    assert asyncio.run(mrs.offer_return_link(contexto, 9801, 98)) is True

    _chat, texto, teclado = contexto.bot.mensajes[0]

    assert teclado is None
    assert "sigue activo" in texto


def test_a_member_who_never_opened_the_bot_is_written_down(comunidad):
    """No se le puede escribir, pero el propietario tiene que poder verlo."""

    class BotVetado(FakeBot):
        async def send_message(self, chat_id=None, text=None, reply_markup=None):
            raise RuntimeError("Forbidden: bot can't initiate conversation")

    contexto = FakeContext()
    contexto.bot = BotVetado()

    # audit_logs es global y no se vacía entre pruebas: se parte de cero para
    # este evento concreto en vez de contar lo que dejó otra.
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "DELETE FROM audit_logs "
            "WHERE event_type='member_return_offer_failed' AND target_user_id=9801"
        )

    assert asyncio.run(mrs.offer_return_link(contexto, 9801, 98)) is False

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM audit_logs "
            "WHERE event_type='member_return_offer_failed' AND target_user_id=9801"
        )
        assert cur.fetchone()[0] == 1


def test_the_kill_switch(comunidad, monkeypatch):
    monkeypatch.setattr(mrs, "RETURN_OFFER_ENABLED", False)

    contexto = FakeContext()

    assert asyncio.run(mrs.offer_return_link(contexto, 9801, 98)) is False
    assert not contexto.bot.mensajes


def test_guardian_hooks_it_where_the_departure_is_detected():
    guardian = open("guardian_service.py", encoding="utf-8").read()

    pos = guardian.index("async def process_guardian_left_chat_member")
    trozo = guardian[pos:pos + 4000]

    assert "offer_return_link" in trozo, (
        "el momento de devolverle la entrada es cuando se detecta la salida"
    )
    assert "guardian_left_return_offer_error" in trozo, (
        "va en su propio try: no puede tumbar la detección de Guardian"
    )
