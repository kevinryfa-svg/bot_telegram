"""
Que /start venda, en vez de dar la bienvenida.

Los datos de producción dijeron el problema sin margen: 297 personas han
pasado por el bot y ninguna ha pagado. Y el escaparate era un botón por
comunidad que decía «➡️ Ver comunidad — X»: sin precio, sin qué es, y con el
enlace de pago a CUATRO toques.

Una tienda que no pone el precio en el escaparate no vende: filtra por
paciencia, no por interés.

Las cuatro reglas que se prueban aquí:

  EL PRECIO EN EL BOTÓN   Siempre, y el real (el mínimo de sus planes).
  UN TOQUE HASTA PAGAR    Con un solo plan, el botón ES el enlace de pago.
  NO SE OFRECE LO QUE     Sin plan usable o con la entrega confirmada roja,
  NO SE PUEDE ENTREGAR    no se vende. Sin comprobar SÍ: ante la duda, se
                          deja vender, como el resto del sistema.
  A QUIEN ESTÁ DENTRO,    Su botón lleva a «Mis accesos», no a pagar otra vez.
  SU ACCESO
"""

import pytest

import start_offer_service as sos


@pytest.fixture
def catalogo(clean_db):
    """Una comunidad vendible (51) y tres que no deberían ofrecerse."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM group_delivery_health WHERE group_id IN (51,52,53,54)")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, preview_text) VALUES "
            "(51, 'VIP Fitness', -1051, TRUE, TRUE, 'Entrenos y dieta cada semana.'), "
            "(52, 'Sin planes', -1052, TRUE, TRUE, 'Nada configurado.'), "
            "(53, 'Entrega rota', -1053, TRUE, TRUE, 'El bot no puede invitar.'), "
            "(54, 'Gratis', -1054, TRUE, TRUE, 'Comunidad gratuita.')"
        )
        cur.execute("UPDATE groups SET is_free_group=TRUE WHERE id=54")
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(51, 'Mensual', 'price_51m', 'price_51m', 30, 15, 'EUR', TRUE), "
            "(53, 'Mensual', 'price_53m', 'price_53m', 30, 20, 'EUR', TRUE), "
            "(54, 'Mensual', 'price_54m', 'price_54m', 30, 5, 'EUR', TRUE)"
        )
        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver, bot_status) "
            "VALUES (53, FALSE, 'member')"
        )

    return db


def test_the_price_is_in_the_button(catalogo):
    ofertas = sos.fetch_sellable_communities(7001)

    assert [o["group_id"] for o in ofertas] == [51], (
        "sin plan usable, con entrega roja o gratuita: no son una venta"
    )

    etiqueta = sos.etiqueta_de_oferta(ofertas[0])

    assert "VIP Fitness" in etiqueta
    assert "15 EUR/mes" in etiqueta, (
        "el precio real y su periodo, en el propio botón"
    )


def test_one_plan_means_one_tap_to_the_payment_link(catalogo):
    oferta = sos.fetch_sellable_communities(7001)[0]

    assert sos.callback_de_oferta(oferta) == "startbuy_51_" + str(oferta["plan_id"]), (
        "con un solo plan el botón va directo a pagar, y lleva el grupo "
        "dentro: el price_id a secas habría muerto porque su rama del router "
        "lee un selected_group que en /start todavía no existe"
    )


def test_several_plans_go_to_choose_not_to_a_card(catalogo):
    with catalogo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) "
            "VALUES (51, 'Anual', 'price_51a', 'price_51a', 365, 120, 'EUR', TRUE)"
        )

    oferta = sos.fetch_sellable_communities(7001)[0]

    assert oferta["planes"] == 2
    assert sos.callback_de_oferta(oferta) == "group_51", (
        "con varios planes hay que elegir, pero se salta la tarjeta intermedia"
    )
    assert "15 EUR/mes" in sos.etiqueta_de_oferta(oferta), (
        "el precio del botón es el de entrada, el más bajo"
    )


def test_unchecked_delivery_still_sells(catalogo):
    """Ante la duda se deja vender: es lo que hace el resto del sistema."""

    with catalogo.conn.cursor() as cur:
        cur.execute("DELETE FROM group_delivery_health WHERE group_id=53")

    ofertas = sos.fetch_sellable_communities(7001)

    assert 53 in [o["group_id"] for o in ofertas]


def test_a_member_already_inside_is_not_sold_again(catalogo):
    with catalogo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7001, 51, NOW() + INTERVAL '10 days', TRUE)"
        )

    oferta = sos.fetch_sellable_communities(7001)[0]

    assert oferta["ya_dentro"] is True
    assert sos.etiqueta_de_oferta(oferta).startswith("🎟 Tu acceso")
    assert sos.callback_de_oferta(oferta) == "mysub_-1051", (
        "el que ya pagó va a su acceso, no a pagar otra vez"
    )


def test_the_cheapest_door_goes_first(catalogo):
    with catalogo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible) VALUES (55, 'Barata', -1055, TRUE, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) "
            "VALUES (55, 'Mensual', 'price_55m', 'price_55m', 30, 5, 'EUR', TRUE)"
        )

    ofertas = sos.fetch_sellable_communities(7001)

    assert [o["group_id"] for o in ofertas] == [55, 51], (
        "la puerta más baja primero: es la que convierte a un desconocido"
    )


def test_the_single_offer_reads_like_an_offer(catalogo):
    oferta = sos.fetch_sellable_communities(7001)[0]
    texto = sos.build_single_offer_text(oferta)

    assert "🔓 VIP Fitness" in texto
    assert "Entrenos y dieta cada semana." in texto
    assert "Precio: 15 EUR/mes" in texto
    assert "El acceso es automático" in texto, (
        "la objeción número uno de un desconocido es si recibirá algo"
    )


def test_the_periods_read_like_people_speak():
    assert sos.formato_precio(15, "EUR", 30) == "15 EUR/mes"
    assert sos.formato_precio(120, "eur", 365) == "120 EUR/año"
    assert sos.formato_precio(9.5, "USD", 7) == "9.5 USD/semana"
    assert sos.formato_precio(30, "EUR", 45) == "30 EUR/45 días"

    # Sin precio no se inventa nada.
    assert sos.formato_precio(None, "EUR", 30) is None


def test_start_uses_the_offer_and_never_loses_its_exits():
    fuente = open("start_handler.py", encoding="utf-8").read()

    assert "fetch_sellable_communities" in fuente
    assert "etiqueta_de_oferta" in fuente
    assert "build_single_offer_text" in fuente

    pos = fuente.index("fetch_sellable_communities")
    trozo = fuente[pos - 600:pos + 2500]

    assert "except Exception" in trozo, (
        "si la oferta falla, la primera pantalla del bot no puede quedarse "
        "sin botones"
    )
    assert "marketplace_group_" in trozo, (
        "la comunidad que no se puede ofrecer con precio sigue estando"
    )


def test_the_one_tap_button_really_reaches_the_checkout(catalogo, monkeypatch):
    """La prueba que faltaba: pulsar el botón de verdad, en el router real.

    Antes esto se comprobaba mirando la cadena del callback, y así no se veía
    el fallo de verdad: el price_id a secas necesita un selected_group que en
    /start no existe, así que el botón contestaba «esta opción ya no está
    disponible» en vez de cobrar.
    """

    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    import callback_router as cr

    oferta = sos.fetch_sellable_communities(7001)[0]
    callback = sos.callback_de_oferta(oferta)

    llamadas = []

    async def falso_checkout(context, chat_id, user_id, group_id, price_id,
                             plan_switch=False):
        llamadas.append((chat_id, user_id, group_id, price_id))

    monkeypatch.setattr(cr, "create_checkout_for_user", falso_checkout)

    mensaje = MagicMock()
    mensaje.chat_id = 7001
    mensaje.chat = MagicMock(id=7001, type="private")
    mensaje.reply_text = AsyncMock()
    mensaje.delete = AsyncMock()

    usuario = MagicMock(id=7001, username="cliente", first_name="Cliente",
                        full_name="Cliente", is_bot=False)

    query = MagicMock()
    query.data = callback
    query.from_user = usuario
    query.message = mensaje
    query.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_user = usuario
    update.effective_chat = mensaje.chat
    update.message = None
    update.effective_message = mensaje

    context = MagicMock()
    context.bot = AsyncMock()
    context.user_data = {}
    context.chat_data = {}
    context.bot_data = {}
    context.args = []

    asyncio.run(cr.button(update, context))

    assert llamadas, (
        f"el botón {callback} no llegó al cobro: "
        f"contestó {mensaje.reply_text.call_args}"
    )

    _chat, _uid, group_id, price_id = llamadas[0]

    assert group_id == 51
    assert price_id == "price_51m"
    assert context.user_data.get("selected_group") == 51, (
        "el grupo tiene que quedar fijado, que es justo lo que faltaba"
    )


def test_a_forged_one_tap_button_cannot_charge_for_another_community(catalogo):
    """Un callback se escribe a mano: el plan tiene que ser de ESA comunidad."""

    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    import callback_router as cr

    with catalogo.conn.cursor() as cur:
        cur.execute("SELECT id FROM plans WHERE group_id=53")
        plan_ajeno = cur.fetchone()[0]

    mensaje = MagicMock()
    mensaje.chat_id = 7001
    mensaje.chat = MagicMock(id=7001, type="private")
    mensaje.reply_text = AsyncMock()
    mensaje.delete = AsyncMock()

    usuario = MagicMock(id=7001, username="cliente", first_name="Cliente",
                        full_name="Cliente", is_bot=False)

    query = MagicMock()
    query.data = f"startbuy_51_{plan_ajeno}"
    query.from_user = usuario
    query.message = mensaje
    query.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_user = usuario
    update.effective_chat = mensaje.chat
    update.message = None
    update.effective_message = mensaje

    context = MagicMock()
    context.bot = AsyncMock()
    context.user_data = {}
    context.chat_data = {}
    context.bot_data = {}
    context.args = []

    asyncio.run(cr.button(update, context))

    dicho = " ".join(str(c) for c in mensaje.reply_text.call_args_list)

    assert "ya no está disponible" in dicho
    assert context.user_data.get("selected_group") is None, (
        "un plan de otra comunidad no puede fijar grupo ni cobrar"
    )


# =========================
# EL AVISO DE REENGANCHE TAMBIÉN VENDE
# =========================
# El texto del aviso ya decía «desde 15 EUR» y su botón llevaba a un LISTADO:
# después de leer el precio quedaban tres toques más hasta pagar. Los 297
# candidatos de producción habían recibido hasta seis de esos avisos.

def test_the_follow_up_carries_the_priced_offer(catalogo):
    import reengagement_service as res

    teclado = res.build_reengagement_keyboard(user_id=7001)
    botones = [(b.text, b.callback_data)
               for fila in teclado.inline_keyboard for b in fila]

    etiquetas = [t for t, _c in botones]
    callbacks = [c for _t, c in botones]

    assert any("15 EUR/mes" in t for t in etiquetas), (
        "el precio va en el botón, no solo en el texto"
    )
    assert any(c.startswith("startbuy_") for c in callbacks), (
        "el botón lleva a pagar, no a un listado"
    )
    assert "start_explore_groups" not in callbacks, (
        "con oferta real, el listado genérico sobra"
    )


def test_the_opt_out_button_survives_every_variant(catalogo):
    import reengagement_service as res

    for user_id in (7001, None):

        teclado = res.build_reengagement_keyboard(user_id=user_id)
        callbacks = [b.callback_data
                     for fila in teclado.inline_keyboard for b in fila]

        assert res.CALLBACK_REENGAGEMENT_STOP in callbacks, (
            "quitar el «no quiero más avisos» para hacer sitio a otra oferta "
            "es cómo se gana un bloqueo"
        )
        assert "public_support" in callbacks


def test_without_anything_to_sell_the_follow_up_keeps_its_exit(clean_db):
    import reengagement_service as res

    teclado = res.build_reengagement_keyboard(user_id=999999)
    callbacks = [b.callback_data
                 for fila in teclado.inline_keyboard for b in fila]

    assert "start_explore_groups" in callbacks, (
        "un aviso sin salida sería peor que el listado"
    )


def test_the_follow_up_never_offers_what_the_person_already_has(catalogo):
    import reengagement_service as res

    with catalogo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7002, 51, NOW() + INTERVAL '10 days', TRUE)"
        )

    teclado = res.build_reengagement_keyboard(user_id=7002)
    callbacks = [b.callback_data
                 for fila in teclado.inline_keyboard for b in fila]

    assert not any(c.startswith("startbuy_51_") for c in callbacks), (
        "ofrecerle comprar lo que ya tiene es el aviso que hace desconfiar "
        "del bot entero"
    )


def test_the_batch_builds_one_keyboard_per_person(catalogo, monkeypatch):
    """El fallo que tuve al escribirlo: el teclado se montaba FUERA del bucle.

    Allí user_id no existe todavía, y un teclado compartido por toda la tanda
    le ofrecería a alguien comprar lo que ya tiene.
    """

    import asyncio

    import reengagement_service as res

    with catalogo.conn.cursor() as cur:
        # 7002 ya está dentro de la 51; 7003 no está en ninguna.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7002, 51, NOW() + INTERVAL '10 days', TRUE)"
        )

    # La suite tiene el reenganche apagado a propósito (nadie quiere que una
    # prueba escriba a nadie): aquí se enciende solo para este caso.
    monkeypatch.setattr(res, "REENGAGEMENT_ENABLED", True)
    monkeypatch.setattr(
        res, "fetch_reengagement_targets",
        lambda limit=None: [(7002, 0), (7003, 0)]
    )
    monkeypatch.setattr(res, "REENGAGEMENT_SEND_DELAY_SECONDS", 0)

    enviados = []

    class FakeBot:
        async def send_message(self, chat_id=None, text=None, reply_markup=None,
                               **kwargs):
            enviados.append((chat_id, reply_markup))
            return True

    class FakeContext:
        def __init__(self):
            self.bot = FakeBot()

    resumen = asyncio.run(res.process_reengagement_batch(FakeContext()))

    assert resumen["sent"] == 2

    por_usuario = {chat: [b.callback_data
                          for fila in markup.inline_keyboard for b in fila]
                   for chat, markup in enviados}

    assert not any(c.startswith("startbuy_51_") for c in por_usuario[7002]), (
        "al que ya está dentro de la 51 no se le ofrece comprarla"
    )
    assert any(c.startswith("startbuy_51_") for c in por_usuario[7003]), (
        "al que no está dentro sí, y con su botón de compra"
    )


def test_the_closing_line_matches_what_is_under_it(catalogo, monkeypatch):
    """Debajo hay botones de compra: el texto no puede cerrar mandándole a mirar.

    «Mira lo que hay disponible 👇» encima de tres botones que ya dicen el
    precio le pide que empiece de nuevo la búsqueda que ya has hecho tú por
    él. Y al revés: cuando no hay nada que ofrecerle y el botón vuelve a ser
    el catálogo, esa frase es la correcta y tiene que volver.
    """

    import asyncio

    import reengagement_service as res

    with catalogo.conn.cursor() as cur:
        # 7002 está dentro de la única comunidad vendible: para él no queda
        # oferta ninguna. 7003 está fuera de todo.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7002, 51, NOW() + INTERVAL '10 days', TRUE)"
        )

    monkeypatch.setattr(res, "REENGAGEMENT_ENABLED", True)
    monkeypatch.setattr(
        res, "fetch_reengagement_targets",
        lambda limit=None: [(7002, 0), (7003, 0)]
    )
    monkeypatch.setattr(res, "REENGAGEMENT_SEND_DELAY_SECONDS", 0)

    textos = {}

    class FakeBot:
        async def send_message(self, chat_id=None, text=None, **kwargs):
            textos[chat_id] = text
            return True

    class FakeContext:
        def __init__(self):
            self.bot = FakeBot()

    asyncio.run(res.process_reengagement_batch(FakeContext()))

    assert "Elige la tuya" in textos[7003]
    assert "Mira lo que hay disponible" not in textos[7003]

    assert "Mira lo que hay disponible" in textos[7002], (
        "sin oferta el botón es el catálogo, y la frase de siempre encaja"
    )
    assert "Elige la tuya" not in textos[7002], (
        "no se le dice «elige la tuya» a quien no tiene ninguna debajo"
    )


def test_the_same_variant_does_not_reuse_the_wrong_text(catalogo, monkeypatch):
    """Los textos se cachean por variante para no reconstruirlos por persona.

    Si la clave del caché fuera solo la variante, el primero de la tanda
    decidiría el cierre de todos los demás: el que tiene oferta recibiría la
    frase del catálogo, o el que no la tiene recibiría «elige la tuya» sobre
    un botón que no es ninguna. Los dos de esta prueba comparten variante 0.
    """

    import reengagement_service as res

    con = res.build_reengagement_text(variant=0, con_ofertas=True)
    sin = res.build_reengagement_text(variant=0, con_ofertas=False)

    assert con != sin
    assert "Elige la tuya" in con and "Elige la tuya" not in sin


# =========================
# EL ENLACE DEL ANUNCIO LLEVA A LA COMUNIDAD DEL ANUNCIO
# =========================
# El bot publica anuncios que terminan en «👉 https://t.me/BOT?start=group_51»
# (build_ad_promo_bot_link, callback_router). Y /start NO tenía ninguna rama
# para esa carga: quien pulsaba el anuncio de una comunidad concreta aterrizaba
# en la bienvenida genérica y tenía que volver a buscarla él. El clic de un
# anuncio ya está pagado; perderlo en la puerta es lo más caro que hace el bot.


def _start_con_carga(carga, user_id=7001):
    """Ejecuta el /start real con la carga del enlace y devuelve lo que dijo."""

    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    import start_handler as sh

    mensaje = MagicMock()
    mensaje.chat_id = user_id
    mensaje.chat = MagicMock(id=user_id, type="private", title=None)
    mensaje.reply_text = AsyncMock()

    usuario = MagicMock(id=user_id, username="cliente", first_name="Cliente",
                        full_name="Cliente", is_bot=False, language_code="es")

    update = MagicMock()
    update.message = mensaje
    update.effective_message = mensaje
    update.effective_user = usuario
    update.effective_chat = mensaje.chat
    update.callback_query = None

    context = MagicMock()
    context.bot = AsyncMock()
    context.bot.username = "TheStarVipBOT"
    context.user_data = {}
    context.chat_data = {}
    context.bot_data = {}
    context.args = [carga] if carga else []

    asyncio.run(sh.start(update, context))

    textos, teclados = [], []

    # Se miran los DOS canales de salida a propósito: las pantallas de deep
    # link contestan con reply_text y el menú de siempre sale por
    # send_clean_message -> bot.send_message. Mirar solo uno haría pasar por
    # «callejón sin salida» justo el camino de vuelta que sí existe.
    llamadas = list(mensaje.reply_text.call_args_list)
    llamadas += list(context.bot.send_message.call_args_list)

    for llamada in llamadas:

        if llamada.args:
            textos.append(str(llamada.args[0]))
        elif llamada.kwargs.get("text"):
            textos.append(str(llamada.kwargs["text"]))

        markup = llamada.kwargs.get("reply_markup")

        if markup is not None and hasattr(markup, "inline_keyboard"):
            teclados.extend(
                (b.text, b.callback_data)
                for fila in markup.inline_keyboard for b in fila
            )

    return " ".join(textos), teclados


def test_the_ad_link_lands_on_the_advertised_community(catalogo):
    texto, botones = _start_con_carga("group_51")

    assert "VIP Fitness" in texto
    assert "15 EUR/mes" in texto, (
        "el precio se dice en la pantalla a la que lleva el anuncio"
    )
    assert "Entrenos y dieta cada semana." in texto, (
        "lo que el propietario cuenta de su comunidad es su argumento de venta"
    )

    etiquetas = [t for t, _c in botones]
    callbacks = [c for _t, c in botones]

    assert any(c.startswith("startbuy_51_") for c in callbacks), (
        "con un solo plan, el botón del anuncio ES el enlace de pago"
    )
    assert any("15 EUR/mes" in t for t in etiquetas), (
        "y el precio también va en el botón"
    )
    assert "public_support" in callbacks, (
        "la duda que frena la compra tiene que tener salida aquí también"
    )


def test_the_link_and_the_handler_agree_on_the_payload():
    """El fallo era exactamente este: el bot generaba una carga que no leía."""

    import callback_router as cr

    enlace = cr.build_ad_promo_bot_link(
        {"paid_group_id": 51}, bot_username="TheStarVipBOT"
    )

    assert enlace.endswith("?start=group_51")

    carga = enlace.split("?start=", 1)[1]

    assert sos.parse_group_payload(carga) == 51, (
        "la carga que escribe el anuncio tiene que ser la que /start entiende"
    )
    assert 'carga.startswith("group_")' in open(
        "start_handler.py", encoding="utf-8"
    ).read()


def test_an_ad_can_sell_a_community_that_is_not_in_the_shop_window(catalogo):
    """La visibilidad decide qué se EXPONE, no quién puede comprar.

    El propietario que paga un anuncio de su comunidad ya ha decidido
    invitar a esa gente; que su comunidad no salga en el escaparate no puede
    dejar sin comprar a quien llega con el enlace que él mismo reparte.
    """

    with catalogo.conn.cursor() as cur:
        cur.execute(
            "UPDATE groups SET is_marketplace_visible=FALSE, "
            "is_main_menu_visible=FALSE, public_visibility='hidden' WHERE id=51"
        )

    assert sos.fetch_sellable_communities(7001) == [], (
        "fuera del escaparate no se ofrece sola"
    )

    oferta = sos.fetch_offer_for_group(51, 7001)

    assert oferta is not None and oferta["precio"] == "15 EUR/mes", (
        "pero con su enlace directo sí se vende"
    )


def test_what_cannot_be_delivered_is_not_sold_even_through_its_own_link(catalogo):
    """La entrega descartada no se relaja: el bot ya se niega a cobrar así."""

    assert sos.fetch_offer_for_group(53, 7001) is None, (
        "entrega confirmada roja: ni por enlace directo"
    )
    assert sos.fetch_offer_for_group(52, 7001) is None, "sin plan usable"
    assert sos.fetch_offer_for_group(54, 7001) is None, "gratuita"


def test_a_member_arriving_from_the_ad_gets_their_access_not_a_second_bill(catalogo):
    with catalogo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7001, 51, NOW() + INTERVAL '10 days', TRUE)"
        )

    texto, botones = _start_con_carga("group_51")

    callbacks = [c for _t, c in botones]

    assert "Ya tienes acceso" in texto
    assert "mysub_-1051" in callbacks
    assert not any(c.startswith("startbuy_") for c in callbacks), (
        "al socio no se le vuelve a cobrar lo que ya tiene"
    )


def test_a_broken_link_is_never_a_dead_end(catalogo):
    """La carga la escribe cualquiera en la barra de direcciones de Telegram."""

    for basura in ("group_", "group_abc", "group_0", "group_-5",
                   "group_99999999", "group_51_extra"):

        assert sos.parse_group_payload(basura) != 51

        texto, botones = _start_con_carga(basura)

        assert texto or botones, (
            f"la carga «{basura}» dejó al usuario sin nada en pantalla"
        )

        # Sí puede aparecer un botón de compra: es el escaparate normal de
        # /start, que ofrece el catálogo con su precio. Lo que no puede
        # aparecer es la pantalla DEDICADA de una comunidad, porque la carga
        # no señala ninguna. Su botón («Entrar ahora») solo existe ahí.
        assert not any(
            "Entrar ahora" in t for t, _c in botones
        ), f"la carga «{basura}» montó una oferta que nadie ha pedido"
