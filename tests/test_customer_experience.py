"""
Lo que ve el cliente: enlace de acceso y mensaje de compra.

Dos problemas reales encontrados leyendo las pantallas de verdad:

  - los enlaces de acceso caducaban en 180 segundos. Quien pagaba y no abría el
    mensaje en tres minutos se quedaba fuera de algo que había comprado, y en
    esa pantalla no había ningún botón para pedir otro enlace.
  - el mensaje que recibe alguien justo después de pagar era una sola línea con
    el enlace pelado: ni confirmación del cobro, ni qué había comprado, ni
    cuánto duraba, ni a quién preguntar si algo fallaba.
"""

from datetime import datetime, timedelta

import invite_link_service as ils
import stripe_handler as sh


# =========================
# CUÁNTO DURA EL ENLACE
# =========================

def test_the_link_lasts_long_enough_to_actually_be_used():
    """Tres minutos dejaban fuera a clientes que ya habían pagado."""

    assert ils.ACCESS_LINK_EXPIRE_SECONDS >= 3600, (
        "un enlace de menos de una hora vuelve a dejar tirado a quien paga"
    )


def test_the_link_never_outlives_the_access_it_gives():
    """Un acceso de dos horas no puede dar un enlace válido dos días."""

    in_two_hours = datetime.now() + timedelta(hours=2)

    seconds = ils.access_link_expire_seconds(in_two_hours)

    assert seconds <= 2 * 3600 + 60
    assert seconds > 3600


def test_permanent_access_gets_the_full_window():
    seconds = ils.access_link_expire_seconds(None)

    assert seconds >= 3600
    assert seconds <= ils.ACCESS_LINK_EXPIRE_SECONDS


def test_an_already_expired_access_still_gets_a_usable_minute():
    """
    Un enlace ya caducado al nacer haría que el cliente viese un error en vez
    de su acceso.
    """

    yesterday = datetime.now() - timedelta(days=1)

    assert ils.access_link_expire_seconds(yesterday) >= 60


def test_a_broken_expiration_does_not_crash_the_purchase():
    assert ils.access_link_expire_seconds("no es una fecha") >= 60


def test_the_default_of_the_link_helper_is_not_three_minutes_again():
    """
    Hoy todas las llamadas pasan su propio valor; esto evita que una llamada
    futura que se olvide del parámetro reviva los 180 segundos.
    """

    import inspect

    default = inspect.signature(
        ils.create_telegram_invite_link
    ).parameters["expire_seconds"].default

    assert default == ils.ACCESS_LINK_EXPIRE_SECONDS


# =========================
# CÓMO SE LE CUENTA AL CLIENTE
# =========================

def test_validity_is_said_in_the_customers_language():
    assert ils.format_access_link_validity(86400, "es") == "24 horas"
    assert ils.format_access_link_validity(86400, "en") == "24 hours"


def test_validity_avoids_awkward_singulars():
    assert ils.format_access_link_validity(3600, "es") == "1 hora"
    assert ils.format_access_link_validity(3600, "en") == "1 hour"
    assert ils.format_access_link_validity(30, "es") == "1 minuto"
    assert ils.format_access_link_validity(600, "es") == "10 minutos"


def test_validity_never_says_zero():
    for seconds in (0, 1, 59, None):
        text = ils.format_access_link_validity(seconds, "es")
        assert "0 " not in text, f"{seconds} -> {text}"


# =========================
# EL MENSAJE DE COMPRA CONFIRMADA
# =========================

def purchase_text(language="es", expiration=None, plan_name="Mensual",
                  amount_total=1500):
    return sh.build_purchase_confirmation_text(
        group_name="VIP Fitness",
        plan_name=plan_name,
        amount_total=amount_total,
        currency="eur",
        expiration=expiration,
        expire_seconds=86400,
        link="https://t.me/+AbCdEf",
        language=language,
    )


def test_the_purchase_message_confirms_the_payment():
    """
    Lo primero que necesita saber quien acaba de pagar es que el cobro ha ido
    bien. Antes el mensaje no lo decía en ninguna parte.
    """

    text = purchase_text()

    assert "Pago confirmado" in text


def test_the_purchase_message_says_what_was_bought_and_for_how_much():
    text = purchase_text()

    assert "VIP Fitness" in text
    assert "Mensual" in text
    assert "15.00 EUR" in text


def test_the_purchase_message_says_until_when():
    text = purchase_text(expiration=datetime(2026, 9, 7))

    assert "07/09/2026" in text


def test_permanent_access_is_not_shown_as_a_date():
    text = purchase_text(expiration=None)

    assert "no caduca" in text
    assert "None" not in text


def test_the_purchase_message_includes_the_link_and_its_validity():
    text = purchase_text()

    assert "https://t.me/+AbCdEf" in text
    assert "24 horas" in text
    assert "una vez" in text, "no se avisa de que el enlace es de un solo uso"


def test_the_purchase_message_says_what_to_do_if_the_link_fails():
    """El caso doloroso: he pagado y no puedo entrar."""

    text = purchase_text()

    assert "Mis accesos" in text


def test_the_purchase_message_is_translated():
    text = purchase_text(language="en")

    assert "Payment confirmed" in text
    assert "Community: VIP Fitness" in text
    assert "24 hours" in text
    assert "horas" not in text, "quedó texto en español en el mensaje inglés"


def test_the_purchase_message_survives_missing_data():
    text = purchase_text(plan_name=None, amount_total=None)

    assert "Pago confirmado" in text
    assert "None" not in text


def test_the_purchase_message_fits_in_a_telegram_message():
    assert len(purchase_text()) < 4096


# =========================
# LOS BOTONES DEL MENSAJE DE COMPRA
# =========================

def test_the_purchase_message_offers_a_way_out():
    rows = sh.build_purchase_confirmation_keyboard(-1001234567890).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]

    # Pedir otro enlace y hablar con soporte, sin salir del mensaje del pago.
    assert "mysub_-1001234567890" in callbacks
    assert "public_support" in callbacks


def test_the_purchase_buttons_are_translated_but_keep_their_callbacks():
    rows = sh.build_purchase_confirmation_keyboard(
        -1001234567890, language="en"
    ).inline_keyboard

    labels = [b.text for row in rows for b in row]
    callbacks = [b.callback_data for row in rows for b in row]

    assert any("accesses" in label for label in labels)
    assert any("support" in label.lower() for label in labels)
    assert "mysub_-1001234567890" in callbacks


def test_no_purchase_button_is_dead():
    rows = sh.build_purchase_confirmation_keyboard(-1).inline_keyboard

    for row in rows:
        for button in row:
            assert button.text
            assert button.callback_data


# =========================
# LA PANTALLA DEL ENLACE
# =========================

def test_the_access_screen_lets_them_ask_for_another_link():
    """
    Antes, si el enlace caducaba, había que volver atrás y entrar otra vez en la
    comunidad. Dos toques de más justo cuando alguien no puede entrar.
    """

    router = open(
        __import__("callback_router").__file__, encoding="utf-8"
    ).read()

    assert "🔄 Enviarme otro enlace" in router


def test_the_access_screen_no_longer_hardcodes_three_minutes():
    router = open(
        __import__("callback_router").__file__, encoding="utf-8"
    ).read()

    assert "expirará en 3 minutos" not in router, (
        "vuelve a anunciarse una caducidad fija que ya no es la real"
    )


# =========================
# LA LISTA DE ACCESOS
# =========================

def test_the_access_list_shows_the_remaining_time(clean_db):
    """
    Antes solo decía "Tus suscripciones activas:" y había que abrir cada
    comunidad para saber cuánto quedaba en cada una.
    """

    router = open(
        __import__("callback_router").__file__, encoding="utf-8"
    ).read()

    assert "es_permanente" in router
    assert "quedan {format_tiempo_restante(caduca)}" in router
