"""
Ofertas semanales que se encienden y se apagan solas.

Un catálogo con el mismo precio todo el año no da ninguna razón para comprar
HOY, y «hoy» es la única venta que existe. Esto pone cada semana un descuento de
verdad sobre los planes cortos, con cuenta atrás, y lo retira solo.

Lo que se vigila aquí es que una oferta no pueda romper el dinero: que no toque
el plan, que su precio de Stripe diga exactamente lo que se anuncia, que no baje
de lo que Stripe puede cobrar, que no se duplique por arrancar dos veces el
mismo lunes, y que caduque de verdad.
"""

from datetime import datetime, timedelta

import pytest

import weekly_offer_service as ofs


@pytest.fixture
def catalogo(clean_db, monkeypatch):
    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append({"name": name, "amount_major": amount_major,
                        "currency": currency})
        return (f"prod_{len(creados)}", f"price_oferta_{len(creados)}")

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (31, 'StarsVip', -1031, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(311, 31, 'Semana', 'price_s', 'price_s', 7, 10, 'EUR', TRUE), "
            "(312, 31, 'Mes', 'price_m', 'price_m', 30, 20, 'EUR', TRUE), "
            "(313, 31, 'Año', 'price_a', 'price_a', 360, 29, 'EUR', TRUE)"
        )

    return {"db": db, "creados": creados}


# =========================
# QUÉ SE OFERTA Y QUÉ NO
# =========================

def test_only_the_short_plans_are_offered(catalogo):
    """Un -60% sobre un plan anual regala once meses."""

    ofertables = [p["id"] for p in ofs.planes_ofertables()]

    assert 311 in ofertables
    assert 312 in ofertables
    assert 313 not in ofertables, "el anual no entra en las ofertas semanales"


def test_the_buckets_are_the_ones_people_understand():
    assert ofs.tramo_de_plan(7) == "semana"
    assert ofs.tramo_de_plan(30) == "mes"
    assert ofs.tramo_de_plan(31) == "mes"
    assert ofs.tramo_de_plan(2) is None, "dos días no es una suscripción"
    assert ofs.tramo_de_plan(365) is None
    assert ofs.tramo_de_plan(None) is None


# =========================
# EL DINERO DE LA OFERTA
# =========================

def test_the_stripe_price_says_exactly_what_is_advertised(catalogo):
    plan = [p for p in ofs.planes_ofertables() if p["id"] == 311][0]

    oferta, _detalle = ofs.crear_oferta(plan, percent=60)

    # plans.amount es una columna ENTERA: los planes se tarifan en euros
    # redondos, así que el importe rebajado cae siempre en céntimos limpios.
    assert oferta["amount"] == pytest.approx(4.00), "10 con -60% son 4,00"

    creado = catalogo["creados"][-1]

    assert creado["amount_major"] == pytest.approx(4.00), (
        "el precio de Stripe lleva el importe YA rebajado: lo que se enseña y "
        "lo que se cobra tienen que ser el mismo número"
    )
    assert "-60%" in creado["name"], (
        "y el descuento se lee también en la página de pago"
    )


def test_the_plan_itself_is_never_touched(catalogo):
    plan = [p for p in ofs.planes_ofertables() if p["id"] == 311][0]

    ofs.crear_oferta(plan, percent=60)

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT amount, stripe_price_id FROM plans WHERE id=311")
        importe, price_id = cur.fetchone()

    assert float(importe) == pytest.approx(10), (
        "si la oferta pisara el plan, al caducar no habría a dónde volver"
    )
    assert price_id == "price_s"


def test_an_offer_that_cannot_be_charged_is_not_created(catalogo):
    """Stripe no cobra menos de 0,50: ofrecerlo sería anunciar un error."""

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET amount=1 WHERE id=311")

    plan = [p for p in ofs.planes_ofertables() if p["id"] == 311][0]

    oferta, detalle = ofs.crear_oferta(plan, percent=60)

    assert oferta is None
    assert "mínimo que se puede cobrar" in detalle
    assert catalogo["creados"] == [], "ni se llama a Stripe"


def test_the_discount_is_bounded():
    assert ofs.descuento_de_tramo("semana") <= 70
    assert ofs.descuento_de_tramo("mes") >= 10


# =========================
# QUE SE ENCIENDA Y SE APAGUE SOLA
# =========================

def test_running_it_twice_the_same_week_creates_one_offer(catalogo):
    ofs.lanzar_ofertas_de_la_semana()
    ofs.lanzar_ofertas_de_la_semana()

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM plan_offers WHERE plan_id=311")
        assert cur.fetchone()[0] == 1, (
            "cada arranque del bot crearía otro precio en Stripe"
        )

    assert len(catalogo["creados"]) == 2, "una por plan corto, no más"


def test_an_expired_offer_stops_being_live(catalogo):
    plan = [p for p in ofs.planes_ofertables() if p["id"] == 311][0]

    ofs.crear_oferta(plan, percent=60)

    assert ofs.oferta_viva(311) is not None

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plan_offers SET ends_at = NOW() - INTERVAL '1 hour' "
            "WHERE plan_id=311"
        )

    assert ofs.oferta_viva(311) is None, "una oferta sin caducidad no es oferta"


def test_a_future_offer_is_not_live_yet(catalogo):
    plan = [p for p in ofs.planes_ofertables() if p["id"] == 311][0]

    ofs.crear_oferta(plan, percent=60)

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plan_offers SET starts_at = NOW() + INTERVAL '2 days' "
            "WHERE plan_id=311"
        )

    assert ofs.oferta_viva(311) is None


def test_an_offer_without_a_stripe_price_is_not_live(catalogo):
    """Sin precio no se puede cobrar: enseñarla sería el fallo de siempre."""

    plan = [p for p in ofs.planes_ofertables() if p["id"] == 311][0]

    ofs.crear_oferta(plan, percent=60)

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plan_offers SET stripe_price_id='' WHERE plan_id=311")

    assert ofs.oferta_viva(311) is None


def test_the_countdown_is_real(catalogo):
    plan = [p for p in ofs.planes_ofertables() if p["id"] == 311][0]

    ofs.crear_oferta(plan, percent=60, dias=7)

    oferta = ofs.oferta_viva(311)

    assert ofs.dias_que_quedan(oferta) in (6, 7)


def test_the_week_key_changes_with_the_week():
    lunes = datetime(2026, 8, 17)
    domingo = datetime(2026, 8, 23)
    lunes_siguiente = datetime(2026, 8, 24)

    assert ofs.clave_de_semana(lunes) == ofs.clave_de_semana(domingo)
    assert ofs.clave_de_semana(lunes) != ofs.clave_de_semana(lunes_siguiente)


def test_the_startup_line_says_what_it_did(catalogo):
    linea = ofs.describe_weekly_offers()

    assert "Ofertas de la semana" in linea
    assert "-60%" in linea or "-40%" in linea


# =========================
# QUE SE VEA, Y QUE SE PUEDA COMPRAR
# =========================
# Una oferta que no se anuncia no vende, y una que se anuncia y no se puede
# cobrar es peor que no tenerla. Las dos cosas se comprueban juntas porque
# juntas son la oferta.

def test_the_shop_window_shows_the_offer_price_and_the_countdown(catalogo,
                                                                 monkeypatch):
    import start_offer_service as sos

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE groups SET is_marketplace_visible=TRUE WHERE id=31"
        )

    plan = [p for p in ofs.planes_ofertables(31) if p["id"] == 311][0]
    ofs.crear_oferta(plan, percent=60, dias=7)

    ofertas = sos.fetch_sellable_communities(0, limit=5, solo_grupo=31)

    assert ofertas, "la comunidad tiene que seguir en el escaparate"

    oferta = ofertas[0]

    assert float(oferta["amount"]) == pytest.approx(4.00), (
        "el escaparate anuncia el precio con descuento"
    )
    assert oferta["price_id"] == "price_oferta_1", (
        "y el identificador con el que se va a cobrar es el de la oferta"
    )
    assert oferta["oferta_percent"] == 60

    frase = sos.frase_de_oferta(oferta)

    assert "-60%" in frase
    assert "antes" in frase
    assert "quedan" in frase or "ÚLTIMO DÍA" in frase, (
        "sin cuenta atrás no hay ninguna razón para comprar hoy"
    )

    assert "-60%" in sos.etiqueta_de_compra_directa(oferta)


def test_the_cheapest_plan_is_the_cheapest_after_the_discount(catalogo):
    """Con el mes rebajado por debajo de la semana, el escaparate cambia."""

    import start_offer_service as sos

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE groups SET is_marketplace_visible=TRUE WHERE id=31")
        # La semana a 9 de tarifa; el mes, a 20 con -60%, sale a 8,00.
        cur.execute("UPDATE plans SET amount=9 WHERE id=311")

    mes = [p for p in ofs.planes_ofertables(31) if p["id"] == 312][0]

    ofs.crear_oferta(mes, percent=60)

    oferta = sos.fetch_sellable_communities(0, limit=5, solo_grupo=31)[0]

    assert oferta["plan_id"] == 312, (
        "gana el que de verdad sale más barato AL PAGAR (8,00 el mes "
        "rebajado), no el de tarifa más baja (9 la semana)"
    )
    assert float(oferta["amount"]) == pytest.approx(8.00)


def test_a_community_with_an_offer_is_still_sellable_without_one(catalogo):
    """Sin oferta viva, todo sigue exactamente como estaba."""

    import start_offer_service as sos

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE groups SET is_marketplace_visible=TRUE WHERE id=31")

    oferta = sos.fetch_sellable_communities(0, limit=5, solo_grupo=31)[0]

    assert oferta["oferta_percent"] is None
    assert sos.frase_de_oferta(oferta) is None
    assert float(oferta["amount"]) == pytest.approx(10)


def test_the_launcher_runs_every_day_not_only_on_mondays():
    """Solo el lunes, cualquier cosa que salga mal deja la tienda a precio de
    tarifa hasta el lunes SIGUIENTE.

    El contenedor caído a las ocho, un plan dado de alta el miércoles, una
    comunidad nueva, o una oferta nacida fuera de ciclo que muere antes de
    tiempo. Con oferta viva el repaso diario no hace nada —se corta en la
    primera consulta y no toca Stripe—, así que corre gratis.
    """

    fuente = open("main.py", encoding="utf-8").read()

    assert "schedule_weekly_offers" in fuente

    bloque = fuente[fuente.index("def schedule_weekly_offers"):]
    bloque = bloque[:bloque.index('name="weekly_offers"')]

    assert "days=" not in bloque, (
        "restringirlo a un día de la semana es lo que abre el hueco"
    )

    assert fuente.count("describe_weekly_offers") >= 2, (
        "una vez en el arranque y otra en el job"
    )

    pos = fuente.index("describe_weekly_offers")

    assert "try:" in fuente[max(0, pos - 400):pos], (
        "preparar ofertas no puede impedir que el bot arranque"
    )


# =========================
# EL AÑO CON DESCUENTO, SOLO PARA QUIEN YA PROBÓ
# =========================
# Quien está a punto de perder su acceso de una semana es la persona más fácil
# de convertir en anual que existe. Pero si esa oferta fuese pública, el precio
# anual pasaría a ser la mitad para TODO el mundo, incluido quien iba a pagar el
# completo. Por eso lleva dueño.

def test_the_annual_offer_belongs_to_one_person(catalogo):
    oferta = ofs.asegurar_oferta_anual(7001, 31)

    assert oferta is not None
    assert oferta["user_id"] == 7001
    assert oferta["plan_id"] == 313, "el plan anual, no otro"
    assert oferta["amount"] == pytest.approx(14.50), "29 con -50%"


def test_the_annual_offer_never_reaches_the_shop_window(catalogo):
    import start_offer_service as sos

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE groups SET is_marketplace_visible=TRUE WHERE id=31")

    ofs.asegurar_oferta_anual(7001, 31)

    escaparate = sos.fetch_sellable_communities(0, limit=5, solo_grupo=31)[0]

    assert escaparate["oferta_percent"] is None, (
        "una oferta personal no puede bajarle el precio a todo el mundo"
    )


def test_only_the_owner_of_the_offer_can_use_it(catalogo, monkeypatch):
    """Un precio personal que sirva a cualquiera no es personal."""

    import flask
    import json as json_mod

    import checkout_routes

    monkeypatch.setattr(
        checkout_routes, "is_stripe_payments_enabled", lambda: True
    )

    class FakeSession:
        id = "cs_test_anual"
        url = "https://checkout.stripe.test/pagar"

    monkeypatch.setattr(
        checkout_routes.stripe.checkout.Session, "create",
        staticmethod(lambda **k: FakeSession())
    )

    oferta = ofs.asegurar_oferta_anual(7001, 31)

    app = flask.Flask(__name__)
    checkout_routes.register_checkout_routes(app)
    cliente = app.test_client()

    def cobrar(user_id):
        return cliente.post(
            "/create-checkout-session",
            data=json_mod.dumps({
                "telegram_id": user_id, "plan": oferta["stripe_price_id"],
                "group_id": 31,
            }),
            content_type="application/json",
        )

    assert cobrar(7001).status_code == 200, "su dueño sí puede pagarla"
    assert cobrar(7002).status_code == 400, (
        "otro no: si el precio rebajado sirviera para cualquiera, bastaría "
        "con reenviar el enlace"
    )


def test_the_annual_offer_is_only_for_short_plan_buyers(catalogo):
    """A quien ya pagó un año no se le regala otro más barato."""

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, "
            "status, plan, payment_date) VALUES "
            "(7003, 31, 2900, 'EUR', 'paid', 'Año', NOW())"
        )

    assert ofs.tiene_plan_corto(7003, 31) is False

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, "
            "status, plan, payment_date) VALUES "
            "(7004, 31, 400, 'EUR', 'paid', 'Semana', NOW())"
        )

    assert ofs.tiene_plan_corto(7004, 31) is True


def test_without_an_annual_plan_nothing_is_promised(catalogo):
    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_active=FALSE WHERE id=313")

    assert ofs.asegurar_oferta_anual(7001, 31) is None


def test_asking_twice_does_not_create_two_offers(catalogo):
    primera = ofs.asegurar_oferta_anual(7001, 31)
    segunda = ofs.asegurar_oferta_anual(7001, 31)

    assert primera["id"] == segunda["id"]

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM plan_offers WHERE user_id=7001")
        assert cur.fetchone()[0] == 1


def test_the_renewal_notice_carries_the_annual_offer(catalogo):
    """Es el momento: le quedan horas de acceso y ya sabe lo que hay dentro."""

    import renewal_service as rs

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, "
            "status, plan, payment_date) VALUES "
            "(7005, 31, 400, 'EUR', 'paid', 'Semana', NOW())"
        )

    teclado = rs.build_renewal_keyboard(31, user_id=7005)

    etiquetas = [b.text for fila in teclado.inline_keyboard for b in fila]

    assert any("-50%" in e for e in etiquetas), (
        "sin el botón, la oferta anual no existe para quien tiene que verla"
    )
    assert any("14,50" in e for e in etiquetas), "con su precio"


def test_someone_who_never_paid_gets_the_normal_notice(catalogo):
    import renewal_service as rs

    teclado = rs.build_renewal_keyboard(31, user_id=7009)

    etiquetas = [b.text for fila in teclado.inline_keyboard for b in fila]

    assert not any("-50%" in e for e in etiquetas)


def test_money_is_written_the_way_it_is_read():
    """«3.6 EUR» no es un precio en ningún sitio donde se hable español, y se
    lee justo antes de pagar."""

    from start_offer_service import formato_importe, formato_precio

    assert formato_importe(3.6, "EUR") == "3,60 EUR"
    assert formato_importe(9.0, "EUR") == "9 EUR"
    assert formato_importe(14.5, "EUR") == "14,50 EUR"
    assert formato_precio(3.6, "EUR", 7) == "3,60 EUR/semana"

    # Y una sola definición: el botón de la oferta anual usa la misma.
    assert "14,50 EUR" in ofs.frase_oferta_anual(
        {"amount": 14.5, "percent": 50, "currency": "EUR"}
    )


def test_an_index_that_changed_shape_really_gets_replaced(db_module):
    """El fallo que solo apareció en producción.

    La primera versión del índice de ofertas era (plan_id, week_key), sin la
    persona. Al añadirla, «CREATE UNIQUE INDEX IF NOT EXISTS» con el MISMO
    nombre no hace nada —solo mira el nombre—, así que la base se quedó con la
    definición vieja y el ON CONFLICT de tres columnas falló con «no unique or
    exclusion constraint matching». Resultado: ni una oferta creada, y el error
    solo visible en el log del arranque.

    Aquí se reproduce ese estado exacto y se comprueba que el arranque lo
    corrige.
    """

    with db_module.conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS plan_offers")
        cur.execute("""
            CREATE TABLE plan_offers (
                id SERIAL PRIMARY KEY, plan_id INTEGER, group_id INTEGER,
                percent INTEGER, amount NUMERIC(12, 2),
                base_amount NUMERIC(12, 2), currency TEXT DEFAULT 'EUR',
                stripe_price_id TEXT, starts_at TIMESTAMP, ends_at TIMESTAMP,
                week_key TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute(
            "CREATE UNIQUE INDEX idx_plan_offers_semana "
            "ON plan_offers (plan_id, week_key)"
        )

    db_module.create_tables()

    with db_module.conn.cursor() as cur:
        cur.execute("""
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'plan_offers'
              AND indexname = 'idx_plan_offers_semana_persona'
        """)
        fila = cur.fetchone()

        cur.execute("""
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'plan_offers'
              AND indexname = 'idx_plan_offers_semana'
        """)
        viejo = cur.fetchone()

    assert fila is not None, "el índice nuevo no llegó a crearse"
    assert "user_id" in fila[0], "y tiene que incluir a la persona"
    assert viejo is None, "el viejo se queda y vuelve a haber dos reglas"


# =========================
# LA CUENTA ATRÁS, UNA SOLA
# =========================
# La dicen tres pantallas —el bot, la web y los avisos— y tres relojes distintos
# acaban dando tres cuentas distintas de la misma oferta.

def test_the_countdown_rounds_up_instead_of_eating_a_day():
    from datetime import datetime, timedelta

    ahora = datetime(2026, 8, 22, 12, 0)

    # Restar dos fechas y quedarse con .days trunca: a una oferta que termina
    # dentro de 2 días y 23 horas le quedan 3 para cualquiera que lo lea.
    assert ofs.frase_cuenta_atras(
        ahora + timedelta(days=2, hours=23), ahora
    ) == "quedan 3 días"

    assert ofs.frase_cuenta_atras(
        ahora + timedelta(days=1, hours=1), ahora
    ) == "quedan 2 días"

    assert ofs.frase_cuenta_atras(ahora + timedelta(hours=20), ahora) == "ÚLTIMO DÍA"
    assert ofs.frase_cuenta_atras(ahora + timedelta(minutes=5), ahora) == "ÚLTIMO DÍA"
    assert ofs.frase_cuenta_atras(None) is None


def test_the_three_screens_say_the_same_thing():
    """Bot, web y avisos: la misma frase para la misma oferta."""

    from datetime import datetime, timedelta

    import public_catalog_page as pcp
    import reengagement_service as rs
    import start_offer_service as sos

    termina = datetime.now() + timedelta(days=2, hours=23)

    oferta = {
        "oferta_percent": 60, "oferta_antes": "9 EUR", "oferta_termina": termina,
        "precio": "3,60 EUR/semana", "nombre": "StarsVip",
    }

    en_el_bot = sos.frase_de_oferta(oferta)
    en_la_web = pcp._insignia_de_oferta(oferta)
    en_el_aviso = rs.cabecera_de_oferta(
        {"offer_percent": 60, "offer_ends_at": termina}
    )

    for texto in (en_el_bot, en_la_web, en_el_aviso):
        assert "-60%" in texto
        assert "quedan 3 días" in texto


def test_every_message_quotes_the_price_the_shop_charges(catalogo):
    """El carrito abandonado, el aviso al interesado y el de renovación pasan
    todos por el mismo lector de precio. Decir 9 EUR mientras la tienda vende a
    3,60 pierde la venta y queda mal a la vez."""

    import renewal_service as rs

    antes = rs.fetch_group_entry_price(31)

    assert float(antes[0]) == pytest.approx(10), "la semana, a tarifa"

    plan = [p for p in ofs.planes_ofertables(31) if p["id"] == 311][0]

    ofs.crear_oferta(plan, percent=60)

    despues = rs.fetch_group_entry_price(31)

    assert float(despues[0]) == pytest.approx(4.00), (
        "con la oferta viva, el precio que se escribe es el de la oferta"
    )


# =========================
# EL AVISO DE ÚLTIMO DÍA
# =========================
# Una cuenta atrás solo vende si alguien la ve terminar. Pero de 306 personas,
# 176 ya habían bloqueado este bot: el empujón va a quien se lo ha ganado —miró
# esa comunidad y no compró— y una sola vez por oferta.

@pytest.fixture
def con_interesados(catalogo):
    db = catalogo["db"]

    plan = [p for p in ofs.planes_ofertables(31) if p["id"] == 311][0]
    oferta, _ = ofs.crear_oferta(plan, percent=60, dias=7)

    with db.conn.cursor() as cur:
        # Termina dentro de 5 horas: hoy es el último día.
        cur.execute(
            "UPDATE plan_offers SET ends_at = NOW() + INTERVAL '5 hours' "
            "WHERE id = %s", (oferta["id"],)
        )
        cur.execute(
            "INSERT INTO bot_user_events (user_id, event_type, group_id) VALUES "
            "(9001, 'community_viewed', 31), "   # miró y no compró
            "(9002, 'community_viewed', 31), "   # ya está dentro
            "(9003, 'community_viewed', 31), "   # se dio de baja
            "(9004, 'community_viewed', 99)"     # miró OTRA comunidad
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, "
            "subscription_active) VALUES (9002, 31, NOW() + INTERVAL '9 days', TRUE)"
        )
        cur.execute(
            "INSERT INTO user_reengagement (user_id, opted_out) VALUES (9003, TRUE)"
        )

    return {**catalogo, "oferta": ofs.oferta_viva(311)}


def test_only_the_offers_about_to_end_are_picked(con_interesados):
    terminan = [o["id"] for o in ofs.ofertas_que_terminan()]

    assert con_interesados["oferta"]["id"] in terminan

    with con_interesados["db"].conn.cursor() as cur:
        cur.execute("UPDATE plan_offers SET ends_at = NOW() + INTERVAL '4 days'")

    assert ofs.ofertas_que_terminan() == [], (
        "avisar cuatro días antes no es un último día"
    )


def test_it_goes_to_whoever_looked_and_did_not_buy(con_interesados):
    interesados = ofs.interesados_sin_comprar(con_interesados["oferta"])

    assert 9001 in interesados
    assert 9002 not in interesados, "ya está dentro"
    assert 9003 not in interesados, "dijo que no quería avisos"
    assert 9004 not in interesados, "miró otra comunidad"


def test_nobody_gets_the_same_last_call_twice(con_interesados):
    oferta = con_interesados["oferta"]

    assert ofs.marcar_ultimo_dia(oferta["id"], 9001, 31) is True
    assert ofs.marcar_ultimo_dia(oferta["id"], 9001, 31) is False, (
        "el job corre cada día y el contenedor reinicia"
    )

    assert 9001 not in ofs.interesados_sin_comprar(oferta)


def test_the_text_says_the_only_thing_that_matters_today(con_interesados):
    texto = ofs.texto_de_ultimo_dia({
        "percent": 60, "amount": 4, "currency": "EUR",
        "group_name": "StarsVip", "group_id": 31, "plan_id": 311,
    })

    assert "último día" in texto.lower()
    assert "-60%" in texto
    assert "4 EUR" in texto
    assert "precio de siempre" in texto


def test_the_button_goes_straight_to_paying(con_interesados):
    teclado = ofs._teclado_de_ultimo_dia({
        "percent": 60, "amount": 4, "currency": "EUR",
        "group_name": "StarsVip", "group_id": 31, "plan_id": 311,
    })

    callbacks = [b.callback_data for fila in teclado.inline_keyboard for b in fila]

    assert "startbuy_31_311" in callbacks, (
        "un aviso de último día que lleva a un menú pierde el último día"
    )


def test_no_last_calls_when_the_shop_cannot_sell(con_interesados, monkeypatch):
    import asyncio

    import reengagement_service as rs

    monkeypatch.setattr(rs, "merece_la_pena_escribir", lambda: (False, "roto"))

    class FakeContext:
        bot = None

    resumen = asyncio.run(ofs.process_offer_last_calls(FakeContext()))

    assert resumen["enviados"] == 0


# =========================
# EL PRECIO QUE SE DICE ES EL PRECIO QUE SE COBRA
# =========================
# Estas dos son la misma avería vista por dos sitios: un sitio que enseña un
# precio y otro que cobra otro. Da igual quién enseñe el número —un botón, una
# página o la IA contestando «¿cuánto cuesta?»—: si no coincide con el cobro,
# el que compra se siente engañado y no vuelve.

def test_the_ai_quotes_the_price_the_shop_is_charging(catalogo):
    """Quien le pregunta el precio a un bot se cree lo que le contesta."""

    import ai_context_builder as ctx

    plan = [p for p in ofs.planes_ofertables(31) if p["id"] == 311][0]
    ofs.crear_oferta(plan, percent=60, dias=7)

    contexto = ctx.build_public_marketplace_context(7001)

    assert "desde 4 EUR" in contexto, (
        "la semana está a 10 de tarifa y a 4 con la oferta viva; la IA tiene "
        "que decir el 4, que es lo que dice el botón"
    )
    assert "desde 10 EUR" not in contexto


def test_the_ai_writes_the_cents_the_way_the_shop_writes_them(catalogo):
    """«3.6 EUR» no es un precio en ningún sitio donde se hable español."""

    import ai_context_builder as ctx

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET amount=9 WHERE id=311")

    plan = [p for p in ofs.planes_ofertables(31) if p["id"] == 311][0]
    ofs.crear_oferta(plan, percent=60, dias=7)

    contexto = ctx.build_public_marketplace_context(7002)

    assert "desde 3,60 EUR" in contexto
    assert "3.60" not in contexto and "3.6 " not in contexto


def test_an_offer_stops_applying_if_the_plan_leaves_stripe(catalogo):
    """El precio de una oferta es un precio de Stripe y de nadie más.

    Si el plan se pasara a PayPal con la oferta viva, el escaparate seguiría
    anunciando el importe rebajado y el cobro se haría por el de tarifa: cobrar
    más de lo anunciado es lo único que este bot no se puede permitir.
    """

    import ai_context_builder as ctx
    import start_offer_service as sos

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("UPDATE groups SET is_marketplace_visible=TRUE WHERE id=31")
        cur.execute("DELETE FROM plans WHERE id IN (312, 313)")

    plan = [p for p in ofs.planes_ofertables(31) if p["id"] == 311][0]
    ofs.crear_oferta(plan, percent=60, dias=7)

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plans SET payment_provider='paypal' WHERE id=311"
        )

    oferta = ofs.oferta_viva(311)

    assert oferta, "la fila de la oferta sigue ahí, no se borra sola"

    escaparate = sos.fetch_sellable_communities(0, limit=5, solo_grupo=31)

    if escaparate:
        assert escaparate[0]["oferta_percent"] is None, (
            "un plan que ya no cobra por Stripe no puede anunciar un precio "
            "de Stripe"
        )
        assert float(escaparate[0]["amount"]) == pytest.approx(10), (
            "vuelve a valer lo que dice la tarifa"
        )

    assert "desde 10 EUR" in ctx.build_public_marketplace_context(7003)


# =========================
# ENTRE UNA OFERTA Y LA SIGUIENTE NO PUEDE HABER UN HUECO
# =========================
# Duraban SIETE DÍAS contados desde que se creaban, y eso solo cuadra si nacen
# un lunes a las ocho. La de producción nació un sábado por la tarde: moría el
# sábado siguiente y la próxima no salía hasta el lunes. 39 horas con la tienda
# a precio de tarifa y sin ninguna razón para comprar hoy — y volvía a pasar
# cada vez que una oferta naciera fuera del lunes.

def test_an_offer_dies_exactly_when_the_next_one_is_born():
    from datetime import datetime, timedelta

    sabado = datetime(2026, 8, 22, 16, 49)

    assert sabado.weekday() == 5, "la de producción nació un sábado"

    fin = ofs.fin_de_ciclo(sabado)

    assert fin.weekday() == 0, "muere un lunes"
    assert fin.hour == ofs.LANZAMIENTO_HORA
    assert fin == datetime(2026, 8, 24, 8, 0), (
        "el lunes SIGUIENTE, no el de dentro de siete días"
    )

    # Y con los siete días de antes había 39 horas de tienda a precio normal.
    viejo_final = sabado + timedelta(days=7)

    assert viejo_final > fin


def test_the_monday_launch_lasts_the_whole_week():
    from datetime import datetime

    lunes = datetime(2026, 8, 24, 8, 0)

    assert ofs.fin_de_ciclo(lunes) == datetime(2026, 8, 31, 8, 0)


def test_an_early_monday_does_not_get_a_one_hour_offer():
    """Si muriera a las ocho, el job de las ocho no podría crear otra —misma
    clave de semana— y la tienda se quedaría SIN oferta toda la semana."""

    from datetime import datetime

    casi = datetime(2026, 8, 24, 7, 59)

    assert ofs.fin_de_ciclo(casi) == datetime(2026, 8, 31, 8, 0)


def test_every_day_of_the_week_ends_on_the_same_monday():
    from datetime import datetime, timedelta

    lunes = datetime(2026, 8, 24, 8, 0)

    # De ese lunes a las ocho hasta el domingo a las once de la noche: toda la
    # semana ISO. La hora siguiente ya es otro lunes y otra oferta.
    horas_de_la_semana = 24 * 6 + 16

    finales = {
        ofs.fin_de_ciclo(lunes + timedelta(hours=h))
        for h in range(0, horas_de_la_semana)
    }

    assert finales == {datetime(2026, 8, 31, 8, 0)}, (
        "toda la semana comparte la misma oferta y el mismo final"
    )


def test_the_offer_it_creates_ends_on_the_cycle(catalogo):
    from datetime import datetime

    sabado = datetime(2026, 8, 22, 16, 49)

    plan = [p for p in ofs.planes_ofertables(31) if p["id"] == 311][0]

    oferta, _detalle = ofs.crear_oferta(plan, momento=sabado)

    assert oferta
    assert oferta["ends_at"].replace(tzinfo=None) == ofs.fin_de_ciclo(sabado)


def test_a_personal_offer_still_follows_whoever_asks(catalogo):
    """La oferta anual es de UNA PERSONA: no sigue el calendario del escaparate."""

    from datetime import datetime, timedelta

    sabado = datetime(2026, 8, 22, 16, 49)

    anual = [p for p in ofs.planes_ofertables(31)] + [{
        "id": 313, "group_id": 31, "group_name": "StarsVip", "name": "Año",
        "amount": 29, "currency": "EUR", "duration_days": 360,
        "is_recurring": False,
    }]

    oferta, _detalle = ofs.crear_oferta(
        anual[-1], percent=50, dias=7, user_id=7777, momento=sabado,
        permitir_cualquier_duracion=True,
    )

    assert oferta
    assert oferta["ends_at"].replace(tzinfo=None) == sabado + timedelta(days=7)


def test_the_job_and_the_expiry_read_the_same_hour():
    """Si estos dos números se separan, vuelve el hueco."""

    fuente = open("main.py", encoding="utf-8").read()

    assert "from weekly_offer_service import LANZAMIENTO_HORA" in fuente

    bloque = fuente[fuente.index("def schedule_weekly_offers"):]
    bloque = bloque[:bloque.index('name="weekly_offers"')]

    assert "hour=LANZAMIENTO_HORA" in bloque
    assert "hour=8" not in bloque, (
        "la hora escrita a mano en main.py es justo lo que se separa"
    )


def test_a_daily_run_with_a_live_offer_creates_nothing(catalogo):
    """El repaso diario tiene que ser gratis mientras haya oferta."""

    ofs.lanzar_ofertas_de_la_semana()

    tras_la_primera = len(catalogo["creados"])

    assert tras_la_primera == 2, "una por plan corto"

    for _dia in range(5):
        ofs.lanzar_ofertas_de_la_semana()

    assert len(catalogo["creados"]) == tras_la_primera, (
        "ni un precio más en Stripe mientras la oferta siga viva"
    )


def test_a_dead_offer_does_not_leak_a_price_every_day(catalogo):
    """La fila no entra —clave única por semana— pero el precio se crea ANTES.

    Sin comprobarlo, cada repaso diario dejaría un precio nuevo en la cuenta de
    Stripe para tirarlo acto seguido.
    """

    ofs.lanzar_ofertas_de_la_semana()

    tras_la_primera = len(catalogo["creados"])

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plan_offers SET ends_at = NOW() - INTERVAL '1 hour'"
        )

    assert ofs.oferta_viva(311) is None, "muerta, pero su semana sigue ocupada"

    for _dia in range(5):
        ofs.lanzar_ofertas_de_la_semana()

    assert len(catalogo["creados"]) == tras_la_primera, (
        "cinco precios de Stripe tirados a la basura en cinco días"
    )

    with catalogo["db"].conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM plan_offers WHERE plan_id=311")

        assert cur.fetchone()[0] == 1


def test_the_daily_run_refills_a_gap(catalogo):
    """Una oferta de la semana pasada que ya murió no espera al lunes.

    Es el caso de producción: nacida fuera de ciclo, con los siete días viejos,
    muriendo en mitad de la semana siguiente a la suya.
    """

    plan = [p for p in ofs.planes_ofertables(31) if p["id"] == 311][0]

    ofs.crear_oferta(plan, dias=7)

    with catalogo["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plan_offers SET week_key='2000-W01', "
            "ends_at = NOW() - INTERVAL '1 hour' WHERE plan_id=311"
        )

    antes = len(catalogo["creados"])

    assert ofs.oferta_viva(311) is None

    ofs.lanzar_ofertas_de_la_semana()

    assert len(catalogo["creados"]) > antes, (
        "sin repaso diario, la tienda estaría a precio de tarifa hasta el lunes"
    )

    viva = ofs.oferta_viva(311)

    assert viva, "y vuelve a haber algo que enseñar hoy"
    assert viva["ends_at"].replace(tzinfo=None) == ofs.fin_de_ciclo()
