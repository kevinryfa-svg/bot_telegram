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
import pathlib

import pytest

import callback_router as cr
import mysub_callbacks as mc


# La pantalla vive en mysub_callbacks desde la fase 7 del troceo, y las frases
# vigiladas pueden estar en cualquier tramo: se escanea la unión del router y
# todos los módulos extraídos, no un solo fichero.
_RAIZ = pathlib.Path(cr.__file__).parent
SOURCE = "\n".join(
    p.read_text(encoding="utf-8")
    for p in [_RAIZ / "callback_router.py", *sorted(_RAIZ.glob("*_callbacks.py"))]
)


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

    tree = ast.parse(open(mc.__file__, encoding="utf-8").read())

    rama = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "handle_mysub_callbacks"
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

    monkeypatch.setattr(mc, "create_telegram_invite_link", lambda *a, **k: None)
    monkeypatch.setattr(mc, "get_group_owner_user_id", lambda gid: 555)

    query, context = FakeQuery(), FakeContext()

    import asyncio

    asyncio.run(
        mc.report_access_link_unavailable(
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

    monkeypatch.setattr(mc, "get_group_owner_user_id", owner_roto)

    query, context = FakeQuery(), FakeContext()

    import asyncio

    asyncio.run(
        mc.report_access_link_unavailable(
            context, query, 7101, 71, "VIP Fitness", -1071, "grupo"
        )
    )

    assert query.message.enviados, "el cliente se quedó sin mensaje por un fallo interno"


# =========================
# EL CAMINO DEL COMPRADOR, EN SU IDIOMA
# =========================
# La pantalla estaba en español fijo aunque el sistema i18n existía: un
# comprador inglés que no entiende el aviso es un comprador que no renueva.

def test_the_screen_speaks_the_buyers_language():
    from i18n_service import t

    es = t("mysub.screen", "es", group="VIP", intro="", remaining="3d 0h 1m",
           renewal="", validity="24 horas", link="https://t.me/+x")
    en = t("mysub.screen", "en", group="VIP", intro="", remaining="3d 0h 1m",
           renewal="", validity="24 hours", link="https://t.me/+x")

    assert es != en
    assert "Tiempo restante" in es
    assert "Time left" in en


def test_every_mysub_key_exists_in_both_languages():
    from i18n_service import TRANSLATIONS

    claves = [k for k in TRANSLATIONS if k.startswith("mysub.")]

    assert len(claves) >= 18, "faltan claves del camino del comprador"

    for clave in claves:

        assert TRANSLATIONS[clave].get("es"), f"{clave} sin español"
        assert TRANSLATIONS[clave].get("en"), f"{clave} sin inglés"
        assert TRANSLATIONS[clave]["es"] != TRANSLATIONS[clave]["en"], (
            f"{clave}: el inglés es una copia del español"
        )


def test_no_hardcoded_buyer_spanish_remains_in_the_screen():
    """Las frases largas del comprador ya no viven como literales."""

    source = open(mc.__file__, encoding="utf-8").read()

    for frase in (
        "Tiempo restante:",
        "Enviarme otro enlace",
        "No encuentro esa comunidad",
        "¿Desactivar la renovación",
        "no se te volverá a cobrar",
    ):
        assert frase not in source, (
            f"'{frase}' sigue como literal en vez de clave i18n"
        )


def test_the_time_formatter_translates_only_its_two_words():
    from datetime import datetime, timedelta
    from formatters import format_tiempo_restante

    assert format_tiempo_restante(None) == "♾️ Permanente"
    assert format_tiempo_restante(None, language="en") == "♾️ Permanent"

    pasado = datetime.now() - timedelta(days=1)
    assert format_tiempo_restante(pasado) == "Expirado"
    assert format_tiempo_restante(pasado, language="en") == "Expired"

    futuro = datetime.now() + timedelta(days=2, hours=3, minutes=10)
    assert format_tiempo_restante(futuro) == format_tiempo_restante(
        futuro, language="en"
    ), "el '2d 3h 10m' es neutro: no cambia de idioma"


# =========================
# «MIS PAGOS»: EL HISTORIAL DEL COMPRADOR
# =========================
# Un cargo que se reconoce no se disputa: el comprador ve sus cobros en el
# bot, con fechas e importes en dinero de verdad.

def test_the_receipts_screen_shows_real_money(comprador_dentro):
    import asyncio

    with comprador_dentro.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            "(7101, 71, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '40 days'), "
            "(7101, 71, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '10 days'), "
            "(7101, 71, 1500, 'EUR', 'refunded', 'Mensual', NOW() - INTERVAL '5 days')"
        )

    query, context = FakeQuery(), FakeContext()

    asyncio.run(mc.handle_mysub_callbacks(
        None, context, query, 7101, "mysub_receipts_-1071"
    ))

    texto, teclado = query.message.enviados[0]

    assert "Tus pagos de VIP Fitness" in texto
    assert texto.count("15.00 EUR") == 3, "importes en dinero, no en céntimos"
    assert "↩️" in texto, "la devolución se distingue del cobro"
    assert "escríbenos antes que a tu banco" in texto

    botones = [b for fila in teclado.inline_keyboard for b in fila]
    assert any(b.callback_data == "mysub_-1071" for b in botones)


def test_an_empty_history_explains_itself(comprador_dentro):
    import asyncio

    query, context = FakeQuery(), FakeContext()

    asyncio.run(mc.handle_mysub_callbacks(
        None, context, query, 7101, "mysub_receipts_-1071"
    ))

    texto, _ = query.message.enviados[0]
    assert "Todavía no hay pagos registrados" in texto


def test_the_receipts_button_lives_in_the_access_screen():
    source = open(mc.__file__, encoding="utf-8").read()

    assert 't("mysub.btn_receipts", language)' in source
    assert source.index('data.startswith("mysub_receipts_")') < \
        source.index('if data.startswith("mysub_"):'), (
        "la rama del historial caería en la genérica"
    )


def test_renewal_receipts_carry_the_amount():
    """El recibo de renovación dice CUÁNTO: un cargo reconocible no se disputa."""

    from i18n_service import t

    es = t("renewal.renewed_priced", "es", group="VIP", until="01/01/2027",
           price="15.00 EUR")

    assert "🧾 Cobro: 15.00 EUR" in es

    source = open("group_subscription_service.py", encoding="utf-8").read()
    assert "renewal.renewed_priced" in source


# =========================
# LA PANTALLA DE INVITAR (referidos)
# =========================

def test_the_invite_screen_hands_over_the_personal_link(comprador_dentro):
    """El enlace personal, el premio y el marcador, en una sola pantalla."""

    import asyncio

    import referral_service as rs

    query, context = FakeQuery(), FakeContext()

    asyncio.run(mc.handle_mysub_callbacks(
        None, context, query, 7101, "mysub_invite_-1071"
    ))

    texto, teclado = query.message.enviados[0]

    assert "Invita a VIP Fitness" in texto
    assert f"?start=ref_71_7101" in texto, (
        "el enlace lleva la comunidad y el socio: sin eso no hay atribución"
    )
    assert f"{rs.REFERRAL_DAYS} días" in texto
    assert "Invitados: 0 · han pagado: 0 · días ganados: 0" in texto

    botones = [b for fila in teclado.inline_keyboard for b in fila]
    assert any(b.callback_data == "mysub_-1071" for b in botones)


def test_the_invite_screen_survives_a_bogus_reference(comprador_dentro):
    """Una referencia que no existe no puede dejar a nadie en un callejón."""

    import asyncio

    query, context = FakeQuery(), FakeContext()

    asyncio.run(mc.handle_mysub_callbacks(
        None, context, query, 7101, "mysub_invite_-9999999"
    ))

    assert query.message.enviados, "siempre se responde algo"
