"""
Alguien entra en StarsVip con el enlace del grupo y el bot no lo expulsa.

Dos agujeros, los dos de verdad:

  1. El control de entradas solo escuchaba el mensaje de servicio «X se ha
     unido», que NO dice con qué enlace se entró. Con un solo enlace de
     publicidad activo en la comunidad, la regla «si Telegram no informó el
     enlace, se deja entrar» dejaba entrar a CUALQUIERA, por cualquier enlace.
  2. La expulsión no miraba la respuesta de Telegram: sin permiso de expulsar,
     el bot apuntaba «expulsado» y la persona se quedaba dentro.
"""

import asyncio
from types import SimpleNamespace

import pytest

import user_join_handler as ujh


GRUPO = 1159
TG = -1001159

ENLACE_PUBLICIDAD = "https://t.me/+PUBLIcidad12345"
ENLACE_CUALQUIERA = "https://t.me/+OTROenlace99999"


class FakeBot:

    def __init__(self):
        self.id = 777000
        self.username = "TheStarVipBOT"
        self.enviados = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None, **k):
        self.enviados.append((chat_id, text))
        return True


def _persona(user_id):
    return SimpleNamespace(
        id=user_id, username=f"u{user_id}", first_name="Alguien", is_bot=False
    )


@pytest.fixture
def grupo(clean_db, monkeypatch):

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (%s, 'StarsVip', %s, TRUE)", (GRUPO, TG)
        )

    expulsados = []
    respuesta = {"ban": {"ok": True}}

    def falso_kick(token, chat_id, user_id):
        expulsados.append((chat_id, user_id))
        return {"ban": dict(respuesta["ban"]), "unban": {"ok": True}}

    monkeypatch.setattr(ujh, "kick_chat_member", falso_kick)

    async def sin_registro(*a, **k):
        return None

    monkeypatch.setattr(ujh, "send_guardian_event_log", sin_registro)

    ujh._ENTRADAS_RECIENTES.clear()

    contexto = SimpleNamespace(bot=FakeBot())

    return {
        "db": db, "expulsados": expulsados, "respuesta": respuesta,
        "contexto": contexto,
    }


def _con_publicidad(db, enlace=ENLACE_PUBLICIDAD):
    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO publicity_group_invite_links "
            "(group_id, telegram_group_id, invite_link, created_by, is_active) "
            "VALUES (%s, %s, %s, 1, TRUE)", (GRUPO, TG, enlace)
        )


def _entra(grupo, user_id, enlace=None, origen=ujh.ORIGEN_CHAT_MEMBER):
    asyncio.run(ujh.evaluar_entrada(
        grupo["contexto"], TG, _persona(user_id),
        invite_link_used=enlace, origen=origen, group_title="StarsVip",
    ))


def _expulsado(grupo, user_id):
    return (TG, user_id) in grupo["expulsados"]


# =========================
# 1. EL AGUJERO DE LA PUBLICIDAD
# =========================

def test_el_mensaje_de_servicio_ya_no_deja_entrar_a_cualquiera(grupo):
    """
    Antes: comunidad con publicidad + mensaje sin enlace → «se deja entrar».
    Ahora el mensaje de servicio no decide: lo decide chat_member.
    """

    _con_publicidad(grupo["db"])

    _entra(grupo, 5001, enlace=None, origen=ujh.ORIGEN_MENSAJE)

    assert not _expulsado(grupo, 5001)
    assert not ujh.ya_evaluada(TG, 5001), (
        "al no decidir, tiene que dejar la entrada libre para chat_member"
    )

    # …y cuando llega chat_member con un enlace que no es de publicidad:
    _entra(grupo, 5001, enlace=ENLACE_CUALQUIERA)

    assert _expulsado(grupo, 5001), "sin pagar y sin enlace de publicidad: fuera"


def test_quien_entra_por_el_enlace_de_publicidad_se_queda(grupo):
    _con_publicidad(grupo["db"])

    _entra(grupo, 5002, enlace=ENLACE_PUBLICIDAD)

    assert not _expulsado(grupo, 5002)


def test_el_enlace_de_publicidad_recortado_por_telegram_tambien_vale(grupo):
    """
    Telegram recorta los enlaces que no creó el bot: «https://t.me/+PUBLIc…».
    El dueño puede autorizar uno suyo como publicidad, así que hay que casarlo.
    """

    _con_publicidad(grupo["db"])

    _entra(grupo, 5003, enlace="https://t.me/+PUBLIcid…")

    assert not _expulsado(grupo, 5003)


def test_un_enlace_recortado_que_no_es_de_publicidad_no_vale(grupo):
    _con_publicidad(grupo["db"])

    _entra(grupo, 5004, enlace="https://t.me/+OTROen…")

    assert _expulsado(grupo, 5004)


def test_un_prefijo_demasiado_corto_no_casa_con_nada(grupo):
    _con_publicidad(grupo["db"])

    _entra(grupo, 5005, enlace="https://t.me/+P…")

    assert _expulsado(grupo, 5005)


def test_sin_enlace_por_chat_member_ya_no_se_da_por_bueno(grupo):
    """Añadido a mano, o un grupo público: se comprueba el acceso."""

    _con_publicidad(grupo["db"])

    _entra(grupo, 5006, enlace=None)

    assert _expulsado(grupo, 5006)


def test_quien_ha_pagado_entra_por_cualquier_enlace(grupo):
    _con_publicidad(grupo["db"])

    with grupo["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (5007, %s, NOW() + INTERVAL '20 days', TRUE)", (GRUPO,)
        )

    _entra(grupo, 5007, enlace=ENLACE_CUALQUIERA)

    assert not _expulsado(grupo, 5007)


def test_sin_publicidad_el_mensaje_de_servicio_sigue_expulsando(grupo):
    """En una comunidad sin publicidad nada cambia: el enlace no decide."""

    _entra(grupo, 5008, enlace=None, origen=ujh.ORIGEN_MENSAJE)

    assert _expulsado(grupo, 5008)


def test_la_misma_entrada_por_las_dos_vias_se_decide_una_vez(grupo):
    _entra(grupo, 5009, enlace=None, origen=ujh.ORIGEN_MENSAJE)
    _entra(grupo, 5009, enlace=ENLACE_CUALQUIERA)

    assert grupo["expulsados"].count((TG, 5009)) == 1
    avisos = [t for c, t in grupo["contexto"].bot.enviados if "5009" in (t or "")]
    assert len(avisos) <= 1, "un solo aviso al admin por persona"


# =========================
# 2. LA EXPULSIÓN QUE NO SE COMPROBABA
# =========================

def test_si_telegram_no_deja_expulsar_se_avisa_al_admin(grupo):
    grupo["respuesta"]["ban"] = {
        "ok": False,
        "description": "Bad Request: not enough rights to restrict/unrestrict chat member",
    }

    _entra(grupo, 5010, enlace=ENLACE_CUALQUIERA)

    avisos = [t for _c, t in grupo["contexto"].bot.enviados if t and "NO he podido expulsarlo" in t]

    assert avisos, "antes ponía «expulsado» y la persona se quedaba dentro"
    assert "permiso de expulsar" in avisos[0]
    assert "5010" in avisos[0]


def test_la_respuesta_de_telegram_se_lee_bien():
    assert ujh.expulsion_fallida({"ban": {"ok": True}}) is None
    assert "rights" in ujh.expulsion_fallida(
        {"ban": {"ok": False, "description": "not enough rights"}}
    )
    assert ujh.expulsion_fallida({"ban": None}) == "no se pudo hablar con Telegram"
    assert ujh.expulsion_fallida(None) == "no se pudo hablar con Telegram"


# =========================
# 3. LA VÍA chat_member
# =========================

def _miembro(estado, is_member=None):
    return SimpleNamespace(status=estado, is_member=is_member, user=_persona(1))


def test_que_cuenta_como_entrar():
    entra = lambda antes, ahora: ujh.es_una_entrada(
        SimpleNamespace(old_chat_member=antes, new_chat_member=ahora)
    )

    assert entra(_miembro("left"), _miembro("member"))
    assert entra(_miembro("kicked"), _miembro("member"))
    assert entra(_miembro("left"), _miembro("restricted", is_member=True))

    assert not entra(_miembro("member"), _miembro("administrator")), "ascenso"
    assert not entra(_miembro("member"), _miembro("left")), "salida"
    assert not entra(_miembro("left"), _miembro("administrator")), (
        "a quien el dueño mete como administrador no se le expulsa"
    )
    assert not entra(_miembro("left"), _miembro("restricted", is_member=False))


def test_el_manejador_pasa_el_enlace_real(grupo, monkeypatch):
    vistos = []

    async def falso(context, tg, member, invite_link_used=None, origen=None,
                    group_title=None):
        vistos.append((tg, member.id, invite_link_used, origen))

    monkeypatch.setattr(ujh, "evaluar_entrada", falso)

    actualizacion = SimpleNamespace(
        chat_member=SimpleNamespace(
            chat=SimpleNamespace(id=TG, type="supergroup", title="StarsVip"),
            old_chat_member=_miembro("left"),
            new_chat_member=SimpleNamespace(
                status="member", is_member=True, user=_persona(5011)
            ),
            invite_link=SimpleNamespace(invite_link=ENLACE_CUALQUIERA),
        )
    )

    asyncio.run(ujh.detect_user_join_chat_member(actualizacion, grupo["contexto"]))

    assert vistos == [(TG, 5011, ENLACE_CUALQUIERA, ujh.ORIGEN_CHAT_MEMBER)]


def test_los_canales_no_cambian(grupo, monkeypatch):
    vistos = []

    async def falso(*a, **k):
        vistos.append(1)

    monkeypatch.setattr(ujh, "evaluar_entrada", falso)

    actualizacion = SimpleNamespace(
        chat_member=SimpleNamespace(
            chat=SimpleNamespace(id=TG, type="channel", title="Canal"),
            old_chat_member=_miembro("left"),
            new_chat_member=SimpleNamespace(
                status="member", is_member=True, user=_persona(5012)
            ),
            invite_link=None,
        )
    )

    asyncio.run(ujh.detect_user_join_chat_member(actualizacion, grupo["contexto"]))

    assert vistos == []


def test_el_bot_pide_chat_member_a_telegram_y_lo_escucha():
    """Sin pedirlo, Telegram no manda chat_member y el arreglo no recibe nada."""

    fuente = open("main.py", encoding="utf-8").read()

    assert "run_polling(allowed_updates=actualizaciones_que_se_piden())" in fuente
    assert "detect_user_join_chat_member" in fuente
    assert "ChatMemberHandler.CHAT_MEMBER" in fuente

    from telegram import Update

    import main

    pedidas = main.actualizaciones_que_se_piden()

    assert Update.CHAT_MEMBER in pedidas
    assert Update.MESSAGE in pedidas and Update.CALLBACK_QUERY in pedidas
    assert Update.MY_CHAT_MEMBER in pedidas
