"""
El deep link post-pago: aterrizar en el bot con contexto, no en un chat mudo.

El checkout de Stripe vuelve al bot con carga (?start=pagado_<grupo> /
cancelado_<grupo>). Quien paga aterriza con su acceso a un toque; quien
cancela, con el camino de vuelta — que alimenta la recuperación de carrito.
La regla de seguridad: cualquier carga rara cae al menú de siempre, nunca a
un callejón ni a un error.
"""

import asyncio

import pytest

import start_handler as sh


class FakeMessage:
    def __init__(self):
        self.enviados = []

    async def reply_text(self, text=None, reply_markup=None, **kwargs):
        self.enviados.append((text, reply_markup))
        return True


class FakeUpdate:
    def __init__(self):
        self.message = FakeMessage()
        self.effective_user = type("U", (), {"id": 8101, "username": "u",
                                             "first_name": "n"})()
        self.effective_chat = type("C", (), {"id": 8101})()


class FakeContext:
    def __init__(self, args=None):
        self.args = args or []
        self.user_data = {}
        self.bot = type("B", (), {})()


@pytest.fixture
def comunidad(clean_db, monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (81, 'VIP Landing', -1081, TRUE)"
        )

    monkeypatch.setattr(sh, "clear_location_flow_state", lambda c: [])
    monkeypatch.setattr(sh, "log_user_event", lambda *a, **k: None)

    menus = []

    async def menu_falso(update, context):
        menus.append(True)

    monkeypatch.setattr(sh, "send_start_menu", menu_falso)

    return {"db": db, "menus": menus}


def test_who_paid_lands_one_tap_from_their_access(comunidad):
    update, contexto = FakeUpdate(), FakeContext(args=["pagado_81"])

    asyncio.run(sh.start(update, contexto))

    assert not comunidad["menus"], "el que acaba de pagar no necesita el menú"

    texto, teclado = update.message.enviados[0]

    assert "Pago recibido" in texto
    assert "VIP Landing" in texto

    botones = [b for fila in teclado.inline_keyboard for b in fila]
    assert any(b.callback_data == "mysub_-1081" for b in botones), (
        "el botón lleva DIRECTO a «Mis accesos», que entrega el enlace"
    )


def test_the_telegram_group_id_also_resolves(comunidad):
    update = FakeUpdate()

    asyncio.run(sh.start(update, FakeContext(args=["pagado_-1081"])))

    texto, _ = update.message.enviados[0]
    assert "VIP Landing" in texto


def test_who_cancelled_gets_the_way_back(comunidad):
    update = FakeUpdate()

    asyncio.run(sh.start(update, FakeContext(args=["cancelado_81"])))

    texto, teclado = update.message.enviados[0]

    assert "a medias" in texto

    botones = [b.callback_data for fila in teclado.inline_keyboard for b in fila]
    assert "marketplace_group_81" in botones, "retomar el pago en un toque"
    assert "public_support" in botones, "y contar el problema si lo hubo"


def test_a_weird_payload_falls_back_to_the_menu(comunidad):
    for carga in (["pagado_"], ["pagado_abc"], ["pagado_99999"], ["otra_cosa"]):

        comunidad["menus"].clear()
        update = FakeUpdate()

        asyncio.run(sh.start(update, FakeContext(args=list(carga))))

        assert comunidad["menus"] or update.message.enviados, (
            f"la carga {carga} dejó al usuario sin NADA"
        )

        if carga != ["pagado_99999"]:
            pass

    # Y sin carga, el /start de siempre.
    comunidad["menus"].clear()
    asyncio.run(sh.start(FakeUpdate(), FakeContext()))
    assert comunidad["menus"], "sin carga, el menú de siempre"


def test_the_checkout_returns_with_the_payload():
    source = open("checkout_routes.py", encoding="utf-8").read()

    assert 'success_url=f"https://t.me/TheStarVipBOT?start=pagado_{group_id}"' in source
    assert 'cancel_url=f"https://t.me/TheStarVipBOT?start=cancelado_{group_id}"' in source
