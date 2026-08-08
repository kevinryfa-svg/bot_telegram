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

def plan_row(plan_id, name, amount, currency, duration, provider="stripe"):
    return (plan_id, name, f"price_{plan_id}", amount, currency, provider, duration)


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
