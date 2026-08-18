"""
La tienda de servicios extra: la única línea de ingresos recurrentes.

Estaba apagada por dos motivos que se sumaban, y ninguno daba error:

  - ensure_owner_addon_products_seeded() NO SE LLAMABA desde ningún sitio, así
    que la tabla estaba vacía y la pantalla decía «no hay servicios extra
    activos para mostrar», sin un botón.
  - y los productos se sembraban SIN stripe_price_id, que es justo lo que el
    checkout mete en line_items. Aunque la tienda se hubiera llenado, comprar
    habría sido imposible: price=None.

Un producto que no se puede comprar no factura, y esto es lo que paga el
servidor todos los meses.
"""

import pytest

import owner_addon_service as oas


@pytest.fixture
def tienda(clean_db, monkeypatch):
    """La tienda sembrada, con Stripe simulado y las llamadas a la vista."""

    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append({
            "name": name,
            "amount_major": amount_major,
            "currency": currency,
            "metadata": metadata or {},
            "recurring_interval_days": recurring_interval_days,
        })
        return (f"prod_{len(creados)}", f"price_{len(creados)}")

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    return {"db": clean_db, "creados": creados}


def test_the_store_was_empty_and_the_seed_fills_it(tienda):
    assert oas.fetch_owner_addon_products() == [], (
        "así estaba producción: la tienda vacía"
    )

    oas.ensure_owner_addon_products_seeded()

    productos = oas.fetch_owner_addon_products()
    codigos = sorted(p["code"] for p in productos)

    assert codigos == ["ad_promo", "backups", "bundle_ads_backups"]


def test_seeding_twice_does_not_duplicate(tienda):
    oas.ensure_owner_addon_products_seeded()
    oas.ensure_owner_addon_products_seeded()

    assert len(oas.fetch_owner_addon_products()) == 3, (
        "un redespliegue no puede duplicar el catálogo"
    )


def test_cents_are_not_charged_as_euros(tienda):
    """La trampa que habría cobrado 1.999 € al mes en vez de 19,99 €.

    monthly_price_cents son CÉNTIMOS; create_stripe_product_and_price espera
    unidades MAYORES. Es el mismo error de unidad que ya tuvo el panel de
    ingresos, y aquí no lo lee nadie: lo paga un cliente.
    """

    oas.ensure_owner_addon_products_seeded()

    producto = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "ad_promo"
    )

    assert producto["monthly_price_cents"] == 1999

    oas.ensure_owner_addon_stripe_price(producto)

    assert len(tienda["creados"]) == 1

    creado = tienda["creados"][0]

    assert creado["amount_major"] == pytest.approx(19.99), (
        f"se pidió un precio de {creado['amount_major']} en unidades mayores"
    )
    assert creado["amount_major"] < 100, (
        "cualquier cosa por encima de 100 aquí es un error de unidad"
    )


def test_the_price_is_monthly_because_the_screen_says_monthly(tienda):
    oas.ensure_owner_addon_products_seeded()

    producto = oas.fetch_owner_addon_products()[0]
    oas.ensure_owner_addon_stripe_price(producto)

    assert tienda["creados"][0]["recurring_interval_days"] == 30, (
        "la pantalla dice «/mes»: cobrar con otro periodo es un cargo que el "
        "cliente no reconoce"
    )
    assert tienda["creados"][0]["metadata"]["purpose"] == "owner_addon"


def test_the_price_is_created_once_and_then_reused(tienda):
    oas.ensure_owner_addon_products_seeded()

    producto = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "backups"
    )

    primero = oas.ensure_owner_addon_stripe_price(producto)

    # Se relee de la base: el precio tiene que haber quedado guardado.
    recargado = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "backups"
    )

    assert recargado["stripe_price_id"] == primero

    segundo = oas.ensure_owner_addon_stripe_price(recargado)

    assert segundo == primero
    assert len(tienda["creados"]) == 1, (
        "crear un precio nuevo en cada compra llenaría Stripe de precios "
        "duplicados del mismo servicio"
    )


def test_a_stripe_failure_leaves_the_store_readable(tienda, monkeypatch):
    """Si Stripe no contesta, la tienda se ve y el precio se crea después."""

    import stripe_catalog

    def explota(*args, **kwargs):
        raise RuntimeError("Stripe down")

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", explota
    )

    linea = oas.prepare_owner_addon_store()

    assert "3 disponibles" in linea
    assert "0 con precio" in linea, (
        "el arranque dice cuántos quedaron sin precio, en vez de callarse"
    )
    assert len(oas.fetch_owner_addon_products()) == 3


def test_the_startup_line_says_what_can_be_sold(tienda):
    linea = oas.prepare_owner_addon_store()

    assert "3 disponibles" in linea
    assert "9,99–24,99 EUR/mes" in linea, (
        "el rango de precios es lo que dice si la tienda está puesta de verdad"
    )
    assert "3 con precio de Stripe listo" in linea


def test_the_checkout_no_longer_goes_out_with_price_none(tienda, monkeypatch):
    """El fallo de fondo: line_items[0].price era None."""

    import callback_router as cr

    oas.ensure_owner_addon_products_seeded()

    producto = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "ad_promo"
    )

    assert not producto["stripe_price_id"], "se siembra sin precio"

    sesiones = []

    class FakeSession:
        @staticmethod
        def create(**kwargs):
            sesiones.append(kwargs)
            return {"id": "cs_1", "url": "https://stripe.test/x",
                    "customer": "cus_1"}

    monkeypatch.setattr(cr.stripe.checkout, "Session", FakeSession)

    cr.create_owner_addon_stripe_checkout_session(producto, 700, 700, 51)

    assert sesiones, "no se creó ninguna sesión"

    precio = sesiones[0]["line_items"][0]["price"]

    assert precio, "el checkout salía con price=None: nadie podía comprar"
    assert precio.startswith("price_")
    assert sesiones[0]["mode"] == "subscription"


def test_a_service_without_a_price_is_refused_instead_of_charged_wrong(tienda):
    """Sin importe no se inventa un cobro: se dice que no se puede cobrar."""

    import callback_router as cr

    oas.ensure_owner_addon_products_seeded()

    with tienda["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE owner_addon_products SET monthly_price_cents=0 "
            "WHERE code='backups'"
        )

    producto = next(
        p for p in oas.fetch_owner_addon_products() if p["code"] == "backups"
    )

    assert oas.ensure_owner_addon_stripe_price(producto) is None

    with pytest.raises(ValueError):
        cr.create_owner_addon_stripe_checkout_session(producto, 700, 700, 51)


def test_the_startup_actually_calls_it(tienda):
    """El fallo original era exactamente este: escrito y nunca llamado."""

    fuente = open("main.py", encoding="utf-8").read()

    assert "prepare_owner_addon_store" in fuente

    pos = fuente.index("prepare_owner_addon_store")

    assert "try:" in fuente[pos - 400:pos], (
        "una llamada a Stripe en el arranque va envuelta o puede tumbar el bot"
    )


# =========================
# QUE ALGUIEN SE ENTERE DE QUE EXISTE
# =========================
# Una tienda con existencias y sin nadie que le diga el precio a un propietario
# vende lo mismo que una vacía. El sitio donde un propietario SÍ lee es su
# resumen semanal. Y lo que convierte una oferta en una insistencia es
# repetirla: se paga con que dejen de leer el resumen entero.

@pytest.fixture
def comunidad_con_dueno(tienda):
    """Comunidad 71 vendible, con dueño 771 y la tienda sembrada."""

    db = tienda["db"]

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM group_delivery_health WHERE group_id=71")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, preview_text) VALUES "
            "(71, 'VIP Pádel', -1071, TRUE, TRUE, 'Partidos y clases.')"
        )
        cur.execute(
            "INSERT INTO admins (user_id, group_id, role, is_active) "
            "VALUES (771, 71, 'GROUP_OWNER', TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(71, 'Mensual', 'price_71m', 'price_71m', 30, 20, 'EUR', TRUE)"
        )
        # Un socio activo: el resumen semanal solo se manda de comunidades
        # VIVAS, y eso está bien — a un grupo muerto no se le resume nada.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7101, 71, NOW() + INTERVAL '20 days', TRUE)"
        )

    oas.ensure_owner_addon_products_seeded()

    return tienda


def test_a_community_with_no_new_members_gets_the_offer_with_its_price(
    comunidad_con_dueno
):
    sugerencia = oas.fetch_addon_suggestion(71, 771, 0)

    assert sugerencia is not None
    assert sugerencia["code"] == "ad_promo"
    assert oas.format_addon_monthly_price(sugerencia) == "19,99 EUR/mes"


def test_a_community_that_is_growing_is_left_alone(comunidad_con_dueno):
    assert oas.fetch_addon_suggestion(71, 771, 25) is None, (
        "a quien le entran 25 personas por semana no hay que venderle "
        "publicidad: es ruido"
    )


def test_nothing_is_offered_to_someone_who_already_pays_for_it(
    comunidad_con_dueno
):
    with comunidad_con_dueno["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO owner_addon_subscriptions "
            "(owner_user_id, group_id, addon_code, status) "
            "VALUES (771, 71, 'ad_promo', 'active')"
        )

    assert oas.fetch_addon_suggestion(71, 771, 0) is None


def test_the_bundle_counts_as_having_it(comunidad_con_dueno):
    """Quien paga el pack de 24,99 ya tiene la publicidad dentro."""

    with comunidad_con_dueno["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO owner_addon_subscriptions "
            "(owner_user_id, group_id, addon_code, status) "
            "VALUES (771, 71, 'bundle_ads_backups', 'active')"
        )

    assert oas.fetch_addon_suggestion(71, 771, 0) is None, (
        "cobrarle por separado lo que ya tiene en el pack sería venderle dos "
        "veces lo mismo"
    )


def test_promotion_is_not_sold_for_a_community_that_cannot_be_bought(
    comunidad_con_dueno
):
    """Traer tráfico a una puerta cerrada no es un servicio, es un gasto."""

    with comunidad_con_dueno["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_active=FALSE WHERE group_id=71")

    assert oas.fetch_addon_suggestion(71, 771, 0) is None


def test_it_is_offered_once_a_month_not_every_week(comunidad_con_dueno):
    primera = oas.fetch_addon_suggestion(71, 771, 0, period_key="2026-08")
    segunda = oas.fetch_addon_suggestion(71, 771, 0, period_key="2026-08")

    assert primera is not None
    assert segunda is None, (
        "la misma oferta cada semana deja de ser una oferta"
    )

    # Al mes siguiente vuelve a tocar.
    assert oas.fetch_addon_suggestion(71, 771, 0, period_key="2026-09")


def test_the_digest_carries_the_offer_in_the_text_and_in_a_button(
    comunidad_con_dueno
):
    import owner_weekly_digest_service as owd

    sugerencia = oas.fetch_addon_suggestion(71, 771, 0)

    texto = owd.build_weekly_digest_text(71, "VIP Pádel", sugerencia=sugerencia)
    teclado = owd.build_digest_keyboard(sugerencia=sugerencia)

    assert "19,99 EUR/mes" in texto, (
        "una sugerencia sin precio obliga a entrar para saber cuánto cuesta: "
        "eso es un anzuelo, no una oferta"
    )
    assert "Se cancela cuando quieras" in texto

    callbacks = [b.callback_data
                 for fila in teclado.inline_keyboard for b in fila]

    assert "owner_panel_revenue" in callbacks, "el resumen no pierde lo suyo"
    assert "owner_addons_menu" in callbacks


def test_without_a_suggestion_the_digest_is_exactly_what_it_was(
    comunidad_con_dueno
):
    import owner_weekly_digest_service as owd

    texto = owd.build_weekly_digest_text(71, "VIP Pádel")
    teclado = owd.build_digest_keyboard()

    assert "19,99" not in texto
    assert "publica tu comunidad" not in texto
    assert len(teclado.inline_keyboard) == 1


def test_the_batch_asks_for_the_suggestion_only_once(comunidad_con_dueno,
                                                     monkeypatch):
    """Pedirla dos veces gastaría la marca y descuadraría texto y botón.

    Es el mismo fallo que ya tuve con el teclado del reenganche: la segunda
    llamada vuelve vacía, así que el texto ofrecería un servicio que el teclado
    no tiene, o al revés.
    """

    import asyncio

    import owner_weekly_digest_service as owd

    monkeypatch.setattr(owd, "DIGEST_ENABLED", True)
    monkeypatch.setattr(owd, "DIGEST_SEND_DELAY_SECONDS", 0)

    enviados = []

    class FakeBot:
        async def send_message(self, chat_id=None, text=None,
                               reply_markup=None, **kwargs):
            enviados.append((chat_id, text, reply_markup))
            return True

    class FakeContext:
        def __init__(self):
            self.bot = FakeBot()

    resumen = asyncio.run(owd.process_weekly_digests(FakeContext()))

    assert resumen["sent"] == 1

    _chat, texto, markup = enviados[0]

    callbacks = [b.callback_data
                 for fila in markup.inline_keyboard for b in fila]

    tiene_texto = "19,99 EUR/mes" in texto
    tiene_boton = "owner_addons_menu" in callbacks

    assert tiene_texto == tiene_boton, (
        "el texto y el botón tienen que decir lo mismo: uno sin el otro es el "
        "síntoma de haber pedido la sugerencia dos veces"
    )
    assert tiene_texto, "con 0 altas y sin el servicio, toca ofrecerlo"
