"""
La primera pantalla: menos opciones y ningún callejón sin salida.

Alguien que llega sin nada veía siete botones a la vez, y tres de ellos no le
servían:

  - "🎟 Mis accesos / recuperar" prometía recuperar algo y llevaba a "No tienes
    suscripciones activas";
  - "💬 Ayuda sobre este menú" solo activaba el modo de texto libre y dejaba al
    usuario sin ningún botón, mientras al lado había "🤖 Ayuda inteligente", que
    lleva a un panel que resuelve justo las dudas que frenan una compra;
  - "🔎 Explorar comunidades" podía llevar a "Todavía no hay comunidades
    publicadas" cuando las comunidades solo estaban visibles en el inicio.

Y "🚀 Publicar mi comunidad", que va dirigido a quien quiere vender, se colaba
entre las acciones del comprador.
"""

import re


SOURCE = open("start_handler.py", encoding="utf-8").read()


# =========================
# LO QUE YA NO SE OFRECE EN VANO
# =========================

def test_accesses_are_only_offered_to_someone_who_has_some():
    """
    El botón prometía "recuperar" y llevaba a "No tienes suscripciones
    activas": un toque perdido en la pantalla donde hay que decidir si comprar.
    """

    assert "🎟 Mis accesos / recuperar" not in SOURCE

    bloque = re.search(
        r"if has_subscriptions:.*?\]\)\n", SOURCE, re.DOTALL
    ).group(0)

    assert "mis_subs" in bloque
    assert "else:" not in bloque, (
        "sigue habiendo una rama que muestra el botón sin tener accesos"
    )


def test_there_is_only_one_ai_help_button_on_the_first_screen(clean_db):
    """
    Había dos, y el que se ha quitado dejaba al usuario sin ningún botón.

    Se comprueba sobre el teclado que se construye de verdad, no leyendo el
    código: la primera versión de este test miraba el texto del fichero y le
    engañaba un comentario que menciona el botón retirado.
    """

    etiquetas = build_start_keyboard_for(
        clean_db, 880007, communities=[(881, True, True)]
    )

    con_ia = [e for e in etiquetas if "🤖" in e]

    assert len(con_ia) == 1, f"hay {len(con_ia)} entradas de ayuda con IA: {con_ia}"
    assert not any("Ayuda sobre este menú" in e for e in etiquetas)


def test_the_remaining_help_button_is_the_useful_one():
    """
    ai_buyer_panel resuelve "Pagué y no tengo link" y "Cómo puedo pagar", que es
    lo que frena una compra. El modo de texto libre sigue dentro de ese panel,
    en "✍️ Preguntar a la IA", así que no se ha perdido nada.
    """

    assert 'callback_data="ai_buyer_panel"' in SOURCE

    router = open("callback_router.py", encoding="utf-8").read()

    assert 'callback_data="ai_ask_buyer"' in router, (
        "el modo de texto libre ya no es accesible desde el panel de ayuda"
    )


def test_explore_is_only_offered_when_there_is_something_new_to_explore():
    """
    Si explorar mostraría lo mismo que los botones directos, o nada en absoluto,
    el botón solo gasta un toque o lleva a un mensaje vacío.
    """

    assert "hay_algo_mas" in SOURCE
    assert "ya_visibles" in SOURCE

    bloque = re.search(
        r"if hay_algo_mas:.*?start_explore_groups", SOURCE, re.DOTALL
    )

    assert bloque, "«Explorar comunidades» ya no está condicionado"


# =========================
# EL ORDEN
# =========================

def test_the_seller_button_comes_after_the_buyer_actions(clean_db):
    """
    "Publicar mi comunidad" va dirigido a otro público. En medio de las acciones
    del comprador, competía con la compra.

    Se mira el orden real de los botones. La primera versión de este test
    comparaba posiciones en el fichero y comparaba con la línea del import.
    """

    etiquetas = build_start_keyboard_for(
        clean_db, 880008, communities=[(881, True, True)]
    )

    def posicion(fragmento):
        for indice, etiqueta in enumerate(etiquetas):
            if fragmento in etiqueta:
                return indice
        return None

    vender = posicion("Publicar mi comunidad")
    # El botón de la comunidad puede llamarse «Ver comunidad — X» (cuando no
    # hay precio que ofrecer) o «💳 X — 15 EUR/mes» (la oferta). Es el mismo
    # botón, así que se busca por el NOMBRE de la comunidad, no por la
    # etiqueta: fijar la etiqueta convertía este test en un freno para
    # mejorar el escaparate, que es justo lo contrario de lo que vigila.
    comunidad = posicion("Comunidad 881")
    soporte = posicion("Soporte")

    assert vender is not None
    assert comunidad is not None and comunidad < vender, (
        f"la comunidad debe ir antes que vender: {etiquetas}"
    )
    assert soporte is not None and soporte < vender, (
        f"el soporte al comprador debe ir antes que vender: {etiquetas}"
    )


def test_support_stays_reachable_from_the_first_screen():
    assert "CALLBACK_SUPPORT" in SOURCE


# =========================
# CONTRA BASE DE DATOS REAL
# =========================

def build_start_keyboard_for(db_module, user_id, *, communities):
    """
    Monta el estado y devuelve las etiquetas de los botones del inicio.

    Se usa el propio start() con un update simulado: comprobar el teclado
    leyendo el código no diría si de verdad aparece o no.
    """

    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    with db_module.conn.cursor() as cur:

        cur.execute("DELETE FROM plans WHERE group_id IN (881, 882)")
        cur.execute("DELETE FROM groups WHERE id IN (881, 882)")

        for group_id, en_inicio, en_explorar in communities:

            cur.execute(
                "INSERT INTO groups (id, name, telegram_group_id, is_active, "
                "is_main_menu_visible, is_marketplace_visible, public_visibility, "
                "is_free, is_free_group) "
                "VALUES (%s, %s, %s, TRUE, %s, %s, %s, FALSE, FALSE)",
                (
                    group_id,
                    f"Comunidad {group_id}",
                    -1000 - group_id,
                    en_inicio,
                    en_explorar,
                    "both" if (en_inicio and en_explorar)
                    else ("start_home" if en_inicio else "explore_only"),
                ),
            )
            cur.execute(
                "INSERT INTO plans (group_id, name, price_id, duration_days, "
                "amount, currency, is_active) "
                "VALUES (%s,'Mensual','p',30,15,'EUR',TRUE)",
                (group_id,),
            )

    import start_handler

    etiquetas = []

    async def send_message(chat_id=None, text=None, reply_markup=None, **kwargs):
        if reply_markup is not None:
            for row in reply_markup.inline_keyboard:
                for button in row:
                    etiquetas.append(button.text)
        return MagicMock(message_id=1)

    user = MagicMock(id=user_id, username="u", first_name="U", is_bot=False,
                     language_code="es")
    chat = MagicMock(id=user_id, type="private")
    message = MagicMock(chat_id=user_id, chat=chat, from_user=user)
    message.reply_text = AsyncMock()
    message.delete = AsyncMock()

    update = MagicMock(message=message, effective_user=user, effective_chat=chat,
                       callback_query=None, effective_message=message)

    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock(side_effect=send_message)
    context.user_data = {}
    context.chat_data = {}
    context.bot_data = {}

    asyncio.run(start_handler.start(update, context))

    return etiquetas


def test_explore_disappears_when_it_would_show_nothing_new(clean_db):
    """Una comunidad visible en los dos sitios: explorar no añade nada."""

    etiquetas = build_start_keyboard_for(
        clean_db, 880001, communities=[(881, True, True)]
    )

    assert any("Comunidad 881" in e for e in etiquetas), (
        f"la comunidad tiene que estar, con precio o sin él: {etiquetas}"
    )
    assert not any("Explorar comunidades" in e for e in etiquetas)


def test_explore_appears_when_there_is_something_only_there(clean_db):
    etiquetas = build_start_keyboard_for(
        clean_db, 880002, communities=[(881, True, False), (882, False, True)]
    )

    assert any("Explorar comunidades" in e for e in etiquetas)


def test_someone_without_access_is_not_offered_their_accesses(clean_db):
    etiquetas = build_start_keyboard_for(
        clean_db, 880003, communities=[(881, True, True)]
    )

    assert not any("Mis accesos" in e for e in etiquetas)


def test_someone_with_access_is_offered_their_accesses(clean_db):
    etiquetas_previas = build_start_keyboard_for(
        clean_db, 880004, communities=[(881, True, True)]
    )

    assert not any("Mis accesos" in e for e in etiquetas_previas)

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (880004, 881, NOW() + INTERVAL '30 days', TRUE)"
        )

    etiquetas = build_start_keyboard_for(
        clean_db, 880004, communities=[(881, True, True)]
    )

    assert any("Mis accesos" in e for e in etiquetas)


def test_the_first_screen_stays_short(clean_db):
    """
    Siete opciones a la vez en la primera pantalla no ayudan a decidir. Este
    tope evita que vuelva a crecer sin darse cuenta.
    """

    etiquetas = build_start_keyboard_for(
        clean_db, 880005, communities=[(881, True, True)]
    )

    assert len(etiquetas) <= 5, f"la primera pantalla tiene {len(etiquetas)} botones: {etiquetas}"


def test_no_button_on_the_first_screen_is_empty(clean_db):
    etiquetas = build_start_keyboard_for(
        clean_db, 880006, communities=[(881, True, True)]
    )

    assert etiquetas
    for etiqueta in etiquetas:
        assert etiqueta.strip()
