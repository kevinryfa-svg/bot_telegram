"""
Quinta tanda del comprador: el silencio y el idioma que no se podía cambiar.

Dos agujeros que llevaban desde el principio, los dos en el primer minuto de
alguien que abre el bot:

  1. Escribir al bot no daba NADA. Ni acuse, ni error, ni un botón.
  2. El idioma salía del móvil y no había una sola pantalla viva para
     cambiarlo — con portugués, francés e italiano al 6%.
"""

import asyncio

import pytest

import i18n_service as i18n
import language_menu_service as lang
import private_text_fallback_service as fallback


# =========================
# EL IDIOMA
# =========================

def test_the_coverage_is_counted_not_claimed():
    """
    Si mañana alguien traduce el resto, la etiqueta tiene que desaparecer sin
    que nadie edite un número a mano. Por eso se cuenta.
    """

    assert i18n.cobertura_de_idioma("es") == 100
    assert i18n.cobertura_de_idioma("en") == 100

    for codigo in ("pt", "fr", "it"):
        assert 0 < i18n.cobertura_de_idioma(codigo) < 100


def test_a_partial_language_says_so_in_its_own_name():
    assert i18n.nombre_de_idioma_con_aviso("en") == "English"

    etiqueta = i18n.nombre_de_idioma_con_aviso("it")

    assert etiqueta.startswith("Italiano (")
    assert etiqueta.endswith("%)")


def test_the_marker_is_a_number_and_not_a_spanish_word():
    """«(parcial)» sería español metido en el nombre de un idioma que no lo es."""

    for codigo in ("pt", "fr", "it"):
        assert "parcial" not in i18n.nombre_de_idioma_con_aviso(codigo)


def test_the_warning_that_explains_the_gap_exists_in_all_five():
    """Es la única frase que TIENE que estar traducida: es la que lo explica."""

    frases = i18n.TRANSLATIONS["language.partial_warning"]

    for codigo in i18n.list_supported_languages():
        assert frases.get(codigo), f"falta la de {codigo}"


def test_a_complete_language_gets_no_warning():
    assert i18n.aviso_de_idioma_parcial("es") is None
    assert i18n.aviso_de_idioma_parcial("en") is None


def test_the_warning_comes_in_the_language_you_just_chose():
    aviso = i18n.aviso_de_idioma_parcial("fr")

    assert aviso
    assert "traduit" in aviso, "en francés, que es lo que acaba de elegir"
    assert "%" in aviso


def test_the_menu_marks_the_language_you_have():
    teclado = lang.build_language_menu_keyboard("it")

    botones = [b for fila in teclado.inline_keyboard for b in fila]

    marcados = [b for b in botones if b.text.startswith("✅")]

    assert len(marcados) == 1
    assert "Italiano" in marcados[0].text


def test_the_menu_offers_the_five_and_never_traps_you():
    teclado = lang.build_language_menu_keyboard("es")

    botones = [b for fila in teclado.inline_keyboard for b in fila]

    idiomas = [
        b for b in botones
        if (b.callback_data or "").startswith(lang.CALLBACK_PREFIX)
    ]

    assert len(idiomas) == len(i18n.list_supported_languages())
    assert any(b.callback_data == "public_back_start" for b in botones), (
        "una pantalla de idioma sin salida deja tirado justo a quien no lee"
    )


def test_the_menu_explains_what_the_percentage_means():
    texto = lang.build_language_menu_text("es")

    assert "%" in texto
    assert "pago" in texto, (
        "lo que importa es que los mensajes del pago SÍ están traducidos"
    )


def test_only_a_real_language_is_accepted():
    assert lang.parse_language_callback("lang_set_pt") == "pt"
    assert lang.parse_language_callback("lang_set_klingon") is None
    assert lang.parse_language_callback("otra_cosa") is None


def test_choosing_a_language_saves_it_and_confirms_in_it(clean_db):
    idioma, confirmacion, aviso = lang.aplicar_idioma(88801, "it")

    assert idioma == "it"
    assert "Italiano" in confirmacion
    assert aviso and "tradotto" in aviso

    i18n.forget_cached_language(88801)

    assert i18n.load_user_language(88801) == "it"


def test_the_live_router_is_the_one_that_dispatches_it():
    """
    La pantalla vieja vivía en help_handler.py, un módulo sin un solo handler
    registrado, y su callback está en la lista de legacy que contesta «esta
    opción ya no está disponible».
    """

    router = open("callback_router.py", encoding="utf-8").read()

    assert 'if data == LANG_CALLBACK_MENU:' in router
    assert 'if data.startswith(LANG_CALLBACK_PREFIX):' in router

    inicio = open("start_handler.py", encoding="utf-8").read()

    assert "CALLBACK_LANGUAGE_MENU" in inicio, (
        "y hay un botón en /start, que es donde lo ve todo el mundo"
    )


def test_there_is_only_one_definition_of_the_language_screen():
    """`/idioma` y el botón de /start abren la MISMA pantalla."""

    ayuda = open("help_handler.py", encoding="utf-8").read()

    assert "build_language_menu_text" in ayuda
    assert 'startswith("set_language_")' not in ayuda, (
        "el despachador viejo no puede seguir compitiendo"
    )
    assert 'callback_data=f"set_language_' not in ayuda, (
        "ni pintar botones que el router vivo contesta con «ya no disponible»"
    )


def test_the_slash_command_finally_exists():
    principal = open("main.py", encoding="utf-8").read()

    assert 'CommandHandler("idioma", idioma_command)' in principal


def test_the_slash_menu_only_advertises_public_commands():
    """Anunciar /admin a todo el mundo es enseñar dónde está la puerta."""

    from bot_commands_service import comandos_publicos

    nombres = [c for c, _ in comandos_publicos()]

    assert "start" in nombres
    assert "idioma" in nombres

    for prohibido in ("admin", "codigos", "usuarios", "debugdb", "fixdb"):
        assert prohibido not in nombres

    for _, descripcion in comandos_publicos():
        assert descripcion, "un comando sin descripción no se entiende"


# =========================
# EL SILENCIO
# =========================

class FakeChat:
    def __init__(self, tipo="private"):
        self.type = tipo
        self.id = 5


class FakeMessage:
    def __init__(self, texto, tipo="private"):
        self.text = texto
        self.chat = FakeChat(tipo)
        self.respuestas = []

    async def reply_text(self, text=None, reply_markup=None):
        self.respuestas.append((text, reply_markup))
        return True


class FakeUser:
    def __init__(self, user_id=99001, language_code="es"):
        self.id = user_id
        self.language_code = language_code


class FakeUpdate:
    def __init__(self, texto, tipo="private", user_id=99001, language_code="es"):
        self.message = FakeMessage(texto, tipo)
        self.effective_user = FakeUser(user_id, language_code)


class FakeContext:
    def __init__(self):
        self.user_data = {}


def test_writing_to_the_bot_is_no_longer_answered_with_silence(clean_db):
    actualizacion = FakeUpdate("hola")

    contesto = asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    )

    assert contesto is True

    texto, teclado = actualizacion.message.respuestas[0]

    assert texto
    assert teclado is not None, "contestar sin una salida es medio contestar"


def test_the_answer_offers_the_things_that_actually_lead_somewhere(clean_db):
    actualizacion = FakeUpdate("no puedo pagar")

    asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    )

    _texto, teclado = actualizacion.message.respuestas[0]

    destinos = {
        b.callback_data
        for fila in teclado.inline_keyboard
        for b in fila
    }

    assert "start_explore_groups" in destinos
    assert "public_support" in destinos
    assert "ai_buyer_panel" in destinos
    assert "public_back_start" in destinos


def test_my_access_is_not_offered_to_someone_who_has_none(clean_db):
    """El botón que promete y contesta «no tienes ninguno» es un toque perdido."""

    actualizacion = FakeUpdate("hola", user_id=99002)

    asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    )

    _texto, teclado = actualizacion.message.respuestas[0]

    destinos = {
        b.callback_data
        for fila in teclado.inline_keyboard
        for b in fila
    }

    assert "mis_subs" not in destinos


def test_and_it_is_offered_to_someone_who_does(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (99, 'Con acceso', -1099, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (99003, 99, NOW() + INTERVAL '30 days', TRUE)"
        )

    actualizacion = FakeUpdate("hola", user_id=99003)

    asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    )

    _texto, teclado = actualizacion.message.respuestas[0]

    destinos = {
        b.callback_data
        for fila in teclado.inline_keyboard
        for b in fila
    }

    assert "mis_subs" in destinos


def test_the_answer_comes_in_the_language_of_whoever_wrote(clean_db):
    i18n.save_user_language(99004, "en")

    actualizacion = FakeUpdate("hello", user_id=99004)

    asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    )

    texto, _ = actualizacion.message.respuestas[0]

    assert "I didn't catch that" in texto


def test_a_pasted_code_is_recognised_and_placed(clean_db):
    """Un código pegado en el vacío era el silencio más caro de todos."""

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (98, 'VIP Codigo', -1098, TRUE)"
        )
        cur.execute("""
            INSERT INTO group_user_promo_codes
                (group_id, telegram_group_id, owner_user_id, code,
                 duration_days, is_permanent, max_uses, used_count, is_active)
            VALUES (98, -1098, 1, 'CODIGOBUENO123', 30, FALSE, 5, 0, TRUE)
        """)

    actualizacion = FakeUpdate("CODIGOBUENO123", user_id=99005)

    asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    )

    texto, teclado = actualizacion.message.respuestas[0]

    assert "VIP Codigo" in texto, "hay que decir de qué comunidad es"

    destinos = {
        b.callback_data
        for fila in teclado.inline_keyboard
        for b in fila
    }

    assert "group_user_promo_redeem_start_98" in destinos


def test_a_code_that_does_not_exist_gets_the_normal_answer(clean_db):
    actualizacion = FakeUpdate("NOEXISTEESTECODIGO", user_id=99006)

    asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    )

    texto, _ = actualizacion.message.respuestas[0]

    assert "No he entendido eso" in texto


def test_a_sentence_is_never_looked_up_as_a_code():
    """No se va a la base de datos por cada «hola, buenas tardes»."""

    assert fallback.parece_un_codigo("CODIGO123") is True
    assert fallback.parece_un_codigo("hola buenas tardes") is False
    assert fallback.parece_un_codigo("no") is False
    assert fallback.parece_un_codigo("x" * 40) is False
    assert fallback.parece_un_codigo("") is False


def test_the_bot_stays_quiet_in_a_group(clean_db):
    """Contestar a todo en un grupo es convertirse en el bot que hay que echar."""

    actualizacion = FakeUpdate("hola", tipo="supergroup")

    contesto = asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    )

    assert contesto is False
    assert not actualizacion.message.respuestas


def test_an_open_admin_wizard_still_gets_its_turn():
    """
    El respaldo no puede pisar a un asistente abierto: quien está creando un
    grupo espera que el bot lea el nombre que acaba de escribir.
    """

    from code_flow_handler import hay_asistente_abierto

    contexto = FakeContext()

    assert hay_asistente_abierto(contexto) is False

    for clave in ("delete_code", "search_user", "kick_user",
                  "ban_user", "unban_user", "creating_group"):

        contexto.user_data = {clave: True}

        assert hay_asistente_abierto(contexto) is True, clave


def test_every_state_that_the_wizard_reads_is_in_the_list():
    """
    Si mañana se añade un asistente y no se apunta aquí, el respaldo contestaría
    encima de él. Se comprueba contra el propio archivo.
    """

    import re

    from code_flow_handler import ESTADOS_DE_ESTE_ASISTENTE

    fuente = open("code_flow_handler.py", encoding="utf-8").read()

    leidos = set(re.findall(
        r'if context\.user_data\.get\("([a-z_]+)"\)', fuente
    ))

    assert leidos <= set(ESTADOS_DE_ESTE_ASISTENTE), (
        f"sin apuntar: {leidos - set(ESTADOS_DE_ESTE_ASISTENTE)}"
    )


def test_the_fallback_never_explodes(clean_db, monkeypatch):
    monkeypatch.setattr(
        fallback, "build_fallback_text", lambda language=None: 1 / 0
    )

    actualizacion = FakeUpdate("hola", user_id=99007)

    assert asyncio.run(
        fallback.responder_al_texto_suelto(actualizacion, FakeContext())
    ) is False
