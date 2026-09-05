"""
El recorrido antes de pagar: descubrir, comparar y decidir.

Recorriendo las pantallas como un comprador de verdad (ni admin, ni dueño, ni
con acceso) aparecieron tres cosas:

  - el precio no se veía hasta dos toques después. En la lista de comunidades y
    en la ficha solo se leía "💎 Premium", así que no se podían comparar sin
    entrar en cada una y pulsar "Comprar acceso".
  - la pantalla de planes abría con tres líneas sobre familias de métodos de
    pago, que el cliente no ha preguntado, y los planes quedaban debajo, sin
    decir cuánto duraba cada uno.
  - si la pasarela fallaba, el mensaje era "❌ Error creando pago", sin decir lo
    único que importa en ese momento: que no te han cobrado.
"""

import pytest

import callback_router as cr


# =========================
# EL PRECIO, DONDE SE DECIDE
# =========================

def test_the_price_is_shown_with_the_badge():
    group = {
        "is_free_group": False,
        "marketplace_badge": "💎 Premium",
        "entry_amount": 15,
        "entry_currency": "eur",
        "entry_duration_days": 30,
        "plan_count": 2,
    }

    assert cr.format_marketplace_kind(group) == "💎 Premium · 💰 desde 15 EUR · 30 días"


def test_a_single_plan_is_not_advertised_as_from():
    """«desde 15 EUR» con un único plan sería engañoso."""

    group = {
        "is_free_group": False,
        "entry_amount": 15,
        "entry_currency": "EUR",
        "entry_duration_days": 30,
        "plan_count": 1,
    }

    texto = cr.format_marketplace_kind(group)

    assert "desde" not in texto
    assert "15 EUR" in texto


def test_free_communities_do_not_show_a_price():
    group = {"is_free_group": True, "entry_amount": 15, "plan_count": 1}

    assert cr.format_marketplace_kind(group) == "🔓 Gratis"


def test_a_community_without_plans_keeps_its_badge():
    group = {"is_free_group": False, "marketplace_badge": "💎 Premium"}

    assert cr.format_marketplace_kind(group) == "💎 Premium"
    assert cr.format_marketplace_price(group) is None


def test_a_broken_price_does_not_break_the_card():
    group = {
        "is_free_group": False,
        "entry_amount": "no es un número",
        "entry_currency": None,
        "entry_duration_days": "raro",
        "plan_count": "raro",
    }

    texto = cr.format_marketplace_kind(group)

    assert texto
    assert "None" not in texto


def test_the_marketplace_query_brings_the_price_along():
    """
    Va en la propia consulta para que la lista no haga una consulta por
    comunidad solo para poder decir el precio.
    """

    select = cr.get_marketplace_group_select()

    assert "entry_amount" in select
    assert "entry_currency" in select
    assert "entry_duration_days" in select
    assert "plan_count" in select


def test_the_row_mapping_matches_the_query():
    """
    Si los campos y las columnas se desalinean, cada comunidad muestra el dato
    de otra columna y nadie se da cuenta hasta verlo en pantalla.
    """

    import re

    select = cr.get_marketplace_group_select()

    # Cuántos campos espera el diccionario.
    source = open(cr.__file__, encoding="utf-8").read()
    bloque = re.search(
        r"def row_to_marketplace_group.*?return dict\(zip\(fields, row\)\)",
        source,
        re.DOTALL,
    ).group(0)
    campos = re.findall(r'^\s+"(\w+)",?$', bloque, re.MULTILINE)

    for esperado in ("entry_amount", "entry_currency", "entry_duration_days",
                     "plan_count"):
        assert esperado in campos, f"falta {esperado} en row_to_marketplace_group"

    # Y que el último campo del diccionario sea también la última columna de la
    # consulta. Se comprueba sin escribir el nombre a mano: fijarlo obligaba a
    # tocar este test cada vez que se añade una columna, que es justo lo que no
    # debe pasar — lo que importa es que sigan alineados.
    ultimo = campos[-1]

    assert f"AS {ultimo}" in select or f"g.{ultimo}" in select, (
        f"el último campo del diccionario ({ultimo}) no está en la consulta"
    )

    posiciones = [
        (select.rfind(f"AS {campo}"), campo)
        for campo in campos
        if f"AS {campo}" in select
    ]

    assert posiciones == sorted(posiciones), (
        "el orden de los campos no coincide con el de las columnas: cada "
        f"comunidad mostraría el dato de otra columna. Orden en la consulta: "
        f"{[c for _, c in sorted(posiciones)]}"
    )


# =========================
# DURACIÓN DE LOS PLANES
# =========================

def test_durations_are_said_the_way_people_say_them():
    assert cr.format_plan_duration_short(30) == "1 mes"
    assert cr.format_plan_duration_short(90) == "3 meses"
    assert cr.format_plan_duration_short(365) == "1 año"
    assert cr.format_plan_duration_short(730) == "2 años"
    assert cr.format_plan_duration_short(1) == "1 día"
    assert cr.format_plan_duration_short(45) == "45 días"


def test_permanent_access_is_not_shown_as_zero_days():
    assert cr.format_plan_duration_short(0) == "para siempre"
    assert cr.format_plan_duration_short(None) == "para siempre"


def test_a_broken_duration_is_ignored_instead_of_crashing():
    assert cr.format_plan_duration_short("no es un número") is None


# =========================
# LA PANTALLA DE PLANES
# =========================

def plan_row(plan_id, name, amount, currency, duration, provider="stripe",
             amount_tarifa=None, oferta_percent=None):
    """La fila tal y como la lee la pantalla de compra.

    Lleva dos campos más desde que hay ofertas: el importe de TARIFA y el
    porcentaje, para poder decir «3,60 EUR 🔥 -60% (antes 9 EUR)». El importe
    de la posición 4 es el VIGENTE, que es el que se cobra.
    """

    return (
        plan_id, name, f"price_{plan_id}", amount, currency, provider, duration,
        amount_tarifa if amount_tarifa is not None else amount,
        oferta_percent,
    )


def test_the_plans_are_readable_before_touching_a_button():
    resumen = cr.format_plans_summary([
        plan_row(1, "Mensual", 15, "eur", 30),
        plan_row(2, "Anual", 120, "eur", 365),
    ])

    assert "• Mensual — 15 EUR · 1 mes" in resumen
    assert "• Anual — 120 EUR · 1 año" in resumen


def test_a_plan_with_several_payment_methods_is_listed_once():
    """
    En los botones un mismo plan aparece una vez por método de pago; en el texto
    repetirlo solo confundiría.
    """

    resumen = cr.format_plans_summary([
        plan_row(1, "Mensual", 15, "eur", 30, "stripe"),
        plan_row(1, "Mensual", 15, "eur", 30, "paypal"),
        plan_row(1, "Mensual", 15, "eur", 30, "revolut"),
    ])

    assert resumen.count("Mensual") == 1


def test_the_summary_survives_empty_or_broken_rows():
    assert cr.format_plans_summary([]) == "• Acceso a la comunidad"
    assert cr.format_plans_summary(None) == "• Acceso a la comunidad"
    assert cr.format_plans_summary([("solo", "dos")]) == "• Acceso a la comunidad"


def test_a_plan_without_price_still_appears():
    resumen = cr.format_plans_summary([plan_row(1, "Invitación", None, None, 30)])

    assert "Invitación" in resumen
    assert "None" not in resumen


# =========================
# CUANDO EL PAGO NO SE PUEDE ABRIR
# =========================

def test_the_failure_message_says_nobody_was_charged():
    """Es lo único que le importa saber a alguien en ese momento."""

    assert "no se te ha cobrado nada" in cr.PAYMENT_FAILED_TEXT.lower()


def test_the_failure_message_does_not_leak_the_technical_error():
    texto = cr.PAYMENT_FAILED_TEXT

    for fuga in ("Traceback", "stripe.error", "psycopg2", "{", "}"):
        assert fuga not in texto


def test_every_payment_method_uses_the_same_clear_failure_message():
    source = open(cr.__file__, encoding="utf-8").read()

    for viejo in (
        'text="❌ Error creando pago"',
        'text="❌ Error creando pago PayPal"',
        'text="❌ Error creando pago Revolut"',
        'text="❌ Error creando pago ChangeNOW"',
        'text="❌ Error creando pago Guardarian"',
    ):
        assert viejo not in source, f"quedó el mensaje escueto: {viejo}"

    # Los cinco métodos más la definición.
    assert source.count("PAYMENT_FAILED_TEXT") >= 6


def test_the_recovery_keyboard_offers_support():
    rows = cr.build_group_recovery_keyboard(4).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]

    assert "public_support" in callbacks
    assert "marketplace_group_4" in callbacks


def test_the_recovery_keyboard_can_offer_a_retry():
    rows = cr.build_group_recovery_keyboard(
        4, retry_callback="stripe_group_plan_4_1"
    ).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]

    assert "stripe_group_plan_4_1" in callbacks


# =========================
# EL ENLACE DE PAGO
# =========================

def test_the_payment_link_keeps_a_way_back_and_support():
    """
    Antes el enlace se enviaba con ReplyKeyboardRemove y sin botones: quien
    dudaba o no conseguía abrirlo se quedaba sin salida.
    """

    rows = cr.build_payment_link_keyboard(4).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]

    assert "marketplace_group_4" in callbacks
    assert "public_support" in callbacks


def test_the_payment_link_keyboard_works_without_a_group():
    rows = cr.build_payment_link_keyboard(None).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]

    assert "public_support" in callbacks
    assert all(c for c in callbacks), "botón sin callback"


def test_the_payment_message_explains_what_happens_next():
    source = open(cr.__file__, encoding="utf-8").read()

    assert "Último paso: el pago" in source
    assert "recibes aquí mismo tu enlace de entrada" in source
    # Y que quien cierre la página sepa que no se le cobra.
    assert "Si cierras la página sin pagar" in source


# =========================
# ERRORES DE BASE DE DATOS EN PANTALLA
# =========================

def test_the_backup_button_no_longer_shows_a_database_error():
    """
    Un propietario que pulsaba "crear backup" leía el error de PostgreSQL,
    incluido el contenido de la fila que falló.
    """

    import owner_backup_callbacks as obc

    source = open(obc.__file__, encoding="utf-8").read()

    assert 'f"❌ No he podido crear el backup: {str(e)[:300]}"' not in source
    assert "No he podido identificar al propietario" in source, (
        "falta la comprobación previa: sin dueño, el INSERT rompía"
    )


# =========================
# DE QUÉ COMUNIDAD ES ESTA PANTALLA
# =========================
# La pantalla de compra ponía «💳 Elige tu acceso» y una lista de precios, sin
# nombrar la comunidad ni una vez. Quien llega desde un mensaje, desde un enlace
# compartido o después de mirar dos o tres comunidades, se encuentra unos
# precios sueltos y no sabe qué está comprando. Y con una oferta viva era peor:
# el escaparate prometía 3,60 y esta lista enseñaba 9.

def test_the_summary_shows_the_offer_price_and_what_it_cost_before():
    resumen = cr.format_plans_summary([
        plan_row(1, "Acceso 7 días", 3.60, "eur", 7,
                 amount_tarifa=9, oferta_percent=60),
    ])

    assert "3,60 EUR" in resumen, "el precio que se va a cobrar"
    assert "-60%" in resumen
    assert "antes 9 EUR" in resumen, (
        "sin el punto de referencia, un descuento es solo un precio"
    )


def test_without_an_offer_the_summary_is_the_one_of_always():
    resumen = cr.format_plans_summary([
        plan_row(1, "Mensual", 15, "eur", 30),
    ])

    assert "• Mensual — 15 EUR · 1 mes" in resumen
    assert "🔥" not in resumen


def test_the_purchase_screen_is_titled_with_the_community(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (55, 'StarsVip', -1055, TRUE)"
        )

    assert cr._nombre_de_comunidad(55) == "StarsVip"

    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "— elige tu acceso" in fuente, (
        "el nombre de la comunidad encabeza la pantalla donde se paga"
    )


def test_a_nameless_community_does_not_break_the_screen(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (56, '', -1056, TRUE)"
        )

    assert cr._nombre_de_comunidad(56) is None, (
        "quedarse sin título es un texto más pobre; quedarse sin la pantalla "
        "de compra es una venta perdida"
    )
    assert cr._nombre_de_comunidad(999999) is None


def test_the_card_price_matches_the_shop_window(clean_db, monkeypatch):
    """Dos precios para lo mismo en dos pantallas seguidas es lo que hace que
    alguien cierre el bot."""

    import start_offer_service as sos

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible) VALUES (57, 'StarsVip', -1057, TRUE, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(571, 57, 'Acceso 7 días', 'p_s', 'p_s', 7, 9, 'EUR', TRUE)"
        )
        cur.execute(
            "INSERT INTO plan_offers (plan_id, group_id, percent, amount, "
            "base_amount, currency, stripe_price_id, starts_at, ends_at, "
            "week_key) VALUES (571, 57, 60, 3.60, 9, 'EUR', 'p_of', NOW(), "
            "NOW() + INTERVAL '3 days', 'w')"
        )

    ficha = cr.fetch_marketplace_group(57)
    escaparate = sos.fetch_sellable_communities(0, limit=5, solo_grupo=57)[0]

    assert float(ficha["entry_amount"]) == pytest.approx(3.60)
    assert float(escaparate["amount"]) == pytest.approx(3.60)

    # Y escrito igual en las dos: «3,60 EUR», no «3.6».
    assert "3,60 EUR" in cr.format_marketplace_price(ficha)
    assert "3,60 EUR" in escaparate["precio"]


# =========================
# CUANDO EL BOT SE NIEGA A COBRAR, QUE SE SEPA
# =========================
# «Me comentan que intentan pagar y no pueden». El escaparate anunciaba bien, el
# servidor de cobro respondía, Stripe funcionaba y en los registros no había ni
# una línea: el bot corta la compra ANTES de pedirle nada a Stripe —ya tienes
# acceso, la comunidad no puede entregar, el cobro está apagado— y ninguno de
# los tres cortes escribía nada. Desde fuera, «no compra nadie» y «no puede
# comprar nadie» se ven exactamente igual.

def test_a_refused_sale_leaves_a_trace(capsys, monkeypatch):
    eventos = []

    monkeypatch.setattr(cr, "log_event", lambda *a, **k: eventos.append((a, k)))

    cr.registrar_venta_rechazada(707, 31, "ya_tiene_acceso", "active_until")

    salida = capsys.readouterr().out

    assert "707" in salida and "31" in salida, (
        "por pantalla, que es lo que se lee sin credenciales de base de datos"
    )
    assert "ya_tiene_acceso" in salida

    assert eventos, "y en el historial, que es lo que aguanta"

    _args, kwargs = eventos[0]

    assert kwargs["metadata"]["motivo"] == "ya_tiene_acceso"
    assert kwargs["severity"] == "warning"


def test_recording_the_refusal_can_never_become_another_failure(capsys,
                                                                monkeypatch):
    def revienta(*a, **k):
        raise RuntimeError("historial caído")

    monkeypatch.setattr(cr, "log_event", revienta)

    cr.registrar_venta_rechazada(707, 31, "no_puede_entregar")

    assert "707" in capsys.readouterr().out


def test_every_branch_that_refuses_for_existing_access_is_covered():
    """Son veinte ramas; el aviso compartido es el único sitio donde ponerlo.

    Tarjeta, PayPal, Revolut, acceso gratis, cambio de plan: todas llaman a
    send_existing_group_access_notice. Registrarlo en cada sitio de llamada
    habría dejado muda la que se olvidara.
    """

    fuente = open("callback_router.py", encoding="utf-8").read()

    pos = fuente.index("async def send_existing_group_access_notice")
    trozo = fuente[pos:pos + 1600]

    assert "registrar_venta_rechazada" in trozo

    ramas = fuente.count("should_block_new_group_purchase(access_state)")

    assert ramas >= 15, (
        "si alguien deja de pasar por el aviso compartido, esto se entera"
    )


def test_the_two_reasons_nobody_can_buy_are_recorded_too():
    """«Ya tienes acceso» es de UNA persona; estas dos son de todo el mundo."""

    fuente = open("callback_router.py", encoding="utf-8").read()

    pos = fuente.index("async def create_checkout_for_user")
    trozo = fuente[pos:pos + 3000]

    assert 'registrar_venta_rechazada' in trozo
    assert '"stripe_apagado"' in trozo

    pos2 = fuente.index("async def group_delivery_blocks_purchase")
    trozo2 = fuente[pos2:pos2 + 3000]

    assert '"no_puede_entregar"' in trozo2
