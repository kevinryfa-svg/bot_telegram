"""
La pantalla «Mis accesos»: la salida que se le ofrece a quien acaba de pagar.

Es el destino del botón «🔗 Pedir mi enlace» del mensaje de compra, así que la
gente llega aquí precisamente cuando algo ha ido mal. Tenía tres salidas sin un
solo botón, y la peor le decía al CLIENTE:

    «Asegúrate de que el bot es administrador del grupo y tiene permisos para
     invitar usuarios.»

Una instrucción interna, sobre un grupo que no es suyo, donde no puede tocar
nada. Y encima es justo el fallo que ya vigila el repaso de entrega: había una
persona esperando delante y nadie avisaba a quien podía arreglarlo.
"""

import ast

import pytest

import callback_router as cr


SOURCE = open(cr.__file__, encoding="utf-8").read()


# =========================
# NADA DE INSTRUCCIONES QUE EL CLIENTE NO PUEDE EJECUTAR
# =========================

def test_the_customer_is_not_told_to_fix_the_group_permissions():
    """
    El cliente no es administrador de la comunidad que ha comprado.

    Al PROPIETARIO sí se le puede pedir: él tiene el grupo. Así que no se
    prohíbe la frase, se acota a los sitios donde el destinatario puede actuar
    —hoy, solo el panel de enlace público del propietario—. La prueba encontró
    dos copias más que sí iban a clientes.
    """

    apariciones = [
        i for i in range(len(SOURCE))
        if SOURCE.startswith("Asegúrate de que el bot es administrador", i)
    ]

    assert len(apariciones) <= 1, (
        f"{len(apariciones)} sitios piden arreglar permisos; solo el aviso al "
        "propietario del enlace público puede hacerlo"
    )

    if apariciones:

        # Y ese único sitio tiene que ir acompañado del teclado del propietario.
        alrededor = SOURCE[apariciones[0]:apariciones[0] + 400]

        assert "build_owner_publicity_group_keyboard" in alrededor, (
            "la frase sigue en un mensaje que no va al propietario"
        )


def test_the_message_tells_them_what_actually_matters():
    from i18n_service import t

    texto = t("access.link_unavailable", "es", group="VIP Fitness")

    assert "VIP Fitness" in texto
    assert "no es cosa tuya" in texto.lower()
    assert "no has perdido" in texto.lower()
    # Y nada de pedirle que toque permisos.
    assert "administrador" not in texto.lower()


def test_the_message_is_translated():
    from i18n_service import t

    es = t("access.link_unavailable", "es", group="VIP")
    en = t("access.link_unavailable", "en", group="VIP")

    assert es != en
    assert "not on you" in en


# =========================
# NINGUNA SALIDA SIN BOTONES
# =========================

def test_no_exit_of_the_screen_leaves_the_customer_stuck():
    """
    Tres de las cuatro salidas no tenían teclado. En una pantalla a la que se
    llega porque algo falló, quedarse sin botones es quedarse sin salida.
    """

    tree = ast.parse(SOURCE)

    button = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "button"
    )

    rama = next(
        s for s in button.body
        if isinstance(s, ast.If)
        and any(
            isinstance(c, ast.Constant) and c.value == "mysub_"
            for c in ast.walk(s.test)
        )
    )

    sin_teclado = []

    for node in ast.walk(rama):

        if not isinstance(node, ast.Call):
            continue

        if getattr(node.func, "attr", None) not in ("reply_text", "send_message"):
            continue

        if any(k.arg == "reply_markup" for k in node.keywords):
            continue

        # reply_with_recover_navigation y report_access_link_unavailable ya ponen
        # teclado por dentro; lo que se busca son los reply_text pelados.
        sin_teclado.append(node.lineno)

    assert not sin_teclado, (
        f"salidas sin botones en «Mis accesos», líneas {sin_teclado}"
    )


# =========================
# LA PANTALLA, EJECUTADA
# =========================

@pytest.fixture
def comprador_dentro(clean_db, monkeypatch):
    """Alguien con acceso pagado y activo a una comunidad."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (71, 'VIP Fitness', -1071, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7101, 71, NOW() + INTERVAL '30 days', TRUE)"
        )

    return db


class FakeMessage:
    def __init__(self):
        self.chat_id = 7101
        self.enviados = []

    async def delete(self):
        return True

    async def reply_text(self, text=None, reply_markup=None, **kwargs):
        self.enviados.append((text, reply_markup))
        return True


class FakeQuery:
    def __init__(self):
        self.message = FakeMessage()
        self.from_user = type("U", (), {"id": 7101})()

    async def answer(self, *a, **k):
        return True


class FakeBot:
    id = 999

    def __init__(self):
        self.mensajes = []

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.mensajes.append((chat_id, text))

    async def get_chat_member(self, chat_id, user_id):
        raise RuntimeError("no se puede consultar en la prueba")


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()
        self.user_data = {}


def test_when_the_link_cannot_be_created_the_owner_is_told(comprador_dentro, monkeypatch):
    """
    Lo importante: hay una persona esperando delante, así que no basta con
    apuntarlo en un registro.
    """

    monkeypatch.setattr(cr, "create_telegram_invite_link", lambda *a, **k: None)
    monkeypatch.setattr(cr, "get_group_owner_user_id", lambda gid: 555)
    monkeypatch.setattr(cr, "revoke_telegram_invite_link", lambda *a, **k: True)

    query, context = FakeQuery(), FakeContext()

    import asyncio

    asyncio.run(
        cr.report_access_link_unavailable(
            context, query, 7101, 71, "VIP Fitness", -1071, "grupo"
        )
    )

    al_cliente = [t for t, _ in query.message.enviados]

    assert al_cliente, "el cliente no recibe nada"
    assert "no es cosa tuya" in al_cliente[0].lower()

    con_teclado = [m for _, m in query.message.enviados if m is not None]

    assert con_teclado, "el cliente se queda sin botones"

    al_propietario = [t for c, t in context.bot.mensajes if c == 555]

    assert al_propietario, "nadie avisa a quien puede arreglarlo"
    assert "no puede entrar" in al_propietario[0]
    assert "Invitar usuarios" in al_propietario[0], (
        "el aviso tiene que decir el permiso concreto, no solo que algo falla"
    )


def test_a_broken_telegram_does_not_break_the_screen(comprador_dentro, monkeypatch):
    """
    La reconsulta de entrega y el aviso al propietario son extras: si fallan, el
    cliente tiene que recibir su mensaje igual.
    """

    def owner_roto(gid):
        raise RuntimeError("base de datos caída")

    monkeypatch.setattr(cr, "get_group_owner_user_id", owner_roto)

    query, context = FakeQuery(), FakeContext()

    import asyncio

    asyncio.run(
        cr.report_access_link_unavailable(
            context, query, 7101, 71, "VIP Fitness", -1071, "grupo"
        )
    )

    assert query.message.enviados, "el cliente se quedó sin mensaje por un fallo interno"
