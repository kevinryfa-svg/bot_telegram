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


def test_the_startup_and_the_monday_job_both_launch_them():
    """Solo con el job del lunes, una semana estrenada por un despliegue del
    martes se quedaría sin oferta hasta siete días después."""

    fuente = open("main.py", encoding="utf-8").read()

    assert "schedule_weekly_offers" in fuente
    assert "days=(1,)" in fuente
    assert fuente.count("describe_weekly_offers") >= 2, (
        "una vez en el arranque y otra en el job del lunes"
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
