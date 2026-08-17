"""
Resolver un cobro sin acceso en un toque, desde el propio aviso.

El aviso de incidencia llevaba todos los identificadores y ninguna forma de
actuar: arreglarlo significaba entrar a la base de datos o inventarse un
código promocional, mientras el comprador esperaba con el dinero pagado.

Las cuatro reglas que se prueban: lo hace una PERSONA con permiso (y el
permiso se comprueba al pulsar, porque un callback se reenvía), no se
escribe un pago nuevo (duplicarlo falsearía los ingresos), una incidencia
resuelta no se resuelve dos veces, y al conceder SIEMPRE se entrega el
enlace — conceder sin avisar deja al cliente esperando igual que antes.
"""

import asyncio

import pytest

import incident_repair_service as irs


class FakeBot:
    def __init__(self):
        self.mensajes = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None):
        self.mensajes.append((chat_id, text, reply_markup))
        return True


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()


@pytest.fixture
def incidencia(clean_db, monkeypatch):
    """Un cobro sin acceso en la comunidad 99, con planes activos."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM payment_incidents WHERE group_id=99")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (99, 'VIP Arreglo', -1099, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(99, 'Mensual', 'price_m99', 'price_m99', 30, 15, 'EUR', TRUE), "
            "(99, 'Anual', 'price_a99', 'price_a99', 365, 120, 'EUR', TRUE), "
            "(99, 'Roto', 'price_r99', 'price_r99', NULL, 10, 'EUR', TRUE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (9901, 99, 1500, 'EUR', 'paid', 'Mensual')"
        )
        cur.execute(
            "INSERT INTO payment_incidents "
            "(incident_key, kind, user_id, group_id, provider) "
            "VALUES ('k99', 'plan_not_found', 9901, 99, 'stripe') RETURNING id"
        )
        incident_id = cur.fetchone()[0]

    monkeypatch.setattr(
        irs, "create_telegram_invite_link",
        lambda token, tgid, **k: "https://t.me/+arreglado"
    )

    return {"db": db, "incident_id": incident_id}


def test_only_the_durations_the_owner_actually_sells(incidencia):
    duraciones = [int(d) for d, _n in irs.fetch_repair_durations(99)]

    assert duraciones == [30, 365], (
        "un plan sin duración válida no es una duración que conceder"
    )


def test_the_repair_grants_access_and_delivers_the_link(incidencia):
    contexto = FakeContext()

    resultado = asyncio.run(irs.repair_incident(
        contexto, incidencia["incident_id"], actor_user_id=7000,
        duration_days=30
    ))

    assert resultado["ok"] is True
    assert resultado["user_id"] == 9901
    assert resultado["link_sent"] is True

    chat, texto, teclado = contexto.bot.mensajes[0]

    assert chat == 9901
    assert "tu acceso a VIP Arreglo está activo" in texto
    assert teclado.inline_keyboard[0][0].url == "https://t.me/+arreglado"

    with incidencia["db"].conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=9901 AND group_id=99")
        assert cur.fetchone()[0] is not None


def test_the_repair_never_writes_a_second_payment(incidencia):
    contexto = FakeContext()

    asyncio.run(irs.repair_incident(
        contexto, incidencia["incident_id"], actor_user_id=7000,
        duration_days=30
    ))

    with incidencia["db"].conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM payments WHERE user_id=9901")
        assert cur.fetchone()[0] == 1, (
            "duplicar el pago falsearía los ingresos del propietario"
        )


def test_a_resolved_incident_cannot_be_resolved_twice(incidencia):
    contexto = FakeContext()

    primero = asyncio.run(irs.repair_incident(
        contexto, incidencia["incident_id"], actor_user_id=7000,
        duration_days=30
    ))
    segundo = asyncio.run(irs.repair_incident(
        contexto, incidencia["incident_id"], actor_user_id=7000,
        duration_days=365
    ))

    assert primero["ok"] is True
    assert segundo["ok"] is False
    assert segundo["reason"] == "not_open", (
        "el segundo toque no puede regalar otro año"
    )


def test_granting_never_shortens_an_existing_access(incidencia):
    with incidencia["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (9901, 99, NOW() + INTERVAL '300 days', TRUE)"
        )

    contexto = FakeContext()

    asyncio.run(irs.repair_incident(
        contexto, incidencia["incident_id"], actor_user_id=7000,
        duration_days=30
    ))

    with incidencia["db"].conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=9901")
        from datetime import datetime, timedelta
        assert cur.fetchone()[0] > datetime.now() + timedelta(days=200), (
            "conceder 30 días no puede recortar un acceso más largo"
        )


def test_a_buyer_who_never_opened_the_bot_still_gets_the_access(incidencia):
    class BotVetado(FakeBot):
        async def send_message(self, chat_id=None, text=None, reply_markup=None):
            raise RuntimeError("Forbidden: bot can't initiate conversation")

    contexto = FakeContext()
    contexto.bot = BotVetado()

    resultado = asyncio.run(irs.repair_incident(
        contexto, incidencia["incident_id"], actor_user_id=7000,
        duration_days=30
    ))

    assert resultado["ok"] is True
    assert resultado["link_sent"] is False

    with incidencia["db"].conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=9901")
        assert cur.fetchone()[0] is not None, (
            "el acceso se concede igual: el fallo es del aviso, no del arreglo"
        )
        cur.execute(
            "SELECT resolved_at FROM payment_incidents WHERE id=%s",
            (incidencia["incident_id"],)
        )
        assert cur.fetchone()[0] is not None


def test_the_notice_now_carries_the_button():
    import payment_incident_service as pis

    teclado = pis.build_staff_incident_keyboard(77)

    boton = teclado["inline_keyboard"][0][0]
    assert boton["callback_data"] == "incident_fix_77"
    assert "Conceder" in boton["text"]

    # Sin id (reintento del webhook) no hay botón que pintar.
    assert pis.build_staff_incident_keyboard(None) is None


def test_the_permission_is_checked_when_the_button_is_pressed():
    router = open("callback_router.py", encoding="utf-8").read()

    for rama in ('data.startswith("incident_fix_go_")',
                 'data.startswith("incident_fix_")'):

        pos = router.index(rama)
        trozo = router[pos:pos + 2500]

        assert "is_super_admin(user_id)" in trozo
        assert "get_group_owner_user_id(group_id) == user_id" in trozo, (
            f"{rama} tiene que comprobar el permiso al pulsar: un callback "
            "se puede reenviar"
        )

    # El "go" va antes que su prefijo padre, o caería en la pantalla.
    assert router.index('data.startswith("incident_fix_go_")') < \
        router.index('data.startswith("incident_fix_")')
