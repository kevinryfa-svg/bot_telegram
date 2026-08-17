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
