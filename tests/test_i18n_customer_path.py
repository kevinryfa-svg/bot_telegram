"""
Idioma del cliente.

Dos cosas estaban rotas o ausentes:
  - el idioma elegido vivía en un diccionario en memoria, así que cualquier
    reinicio devolvía a todo el mundo al español;
  - nadie miraba el idioma que Telegram ya envía en cada mensaje, así que un
    comprador inglés recibía todo en español desde el primer /start.

Se traduce el camino del cliente (renovación, caducidad, pago sin completar).
El panel de administración sigue en español a propósito.
"""

import abandoned_checkout_service as acs
import i18n_service as i18n
import renewal_service as rs


# =========================
# DETECCIÓN DEL IDIOMA DE TELEGRAM
# =========================

def test_telegram_language_codes_are_understood():
    assert i18n.language_from_telegram_code("en") == "en"
    assert i18n.language_from_telegram_code("en-US") == "en"
    assert i18n.language_from_telegram_code("pt-BR") == "pt"
    assert i18n.language_from_telegram_code("es-ES") == "es"


def test_unsupported_or_missing_codes_return_nothing():
    # None, no español: quien llama decide el respaldo.
    assert i18n.language_from_telegram_code("zh-CN") is None
    assert i18n.language_from_telegram_code("") is None
    assert i18n.language_from_telegram_code(None) is None


# =========================
# PREFERENCIA PERSISTIDA
# =========================

def test_the_chosen_language_survives_a_restart(db_module):
    user_id = 810001

    i18n.save_user_language(user_id, "en")

    # Vaciar la caché es lo que ocurre al reiniciar el proceso.
    i18n.forget_cached_language(user_id)

    assert i18n.load_user_language(user_id) == "en"


def test_an_explicit_choice_beats_what_telegram_says(db_module):
    """Quien elige español no debe volver a inglés porque su móvil esté en inglés."""

    user_id = 810002

    i18n.save_user_language(user_id, "es")
    i18n.forget_cached_language(user_id)

    assert i18n.load_user_language(user_id, telegram_language_code="en-US") == "es"


def test_telegram_language_is_used_on_first_contact(db_module):
    user_id = 810003

    i18n.forget_cached_language(user_id)

    with db_module.conn.cursor() as cur:
        cur.execute("DELETE FROM user_preferences WHERE user_id=%s", (user_id,))

    assert i18n.load_user_language(user_id, telegram_language_code="en-GB") == "en"

    # Y queda guardado, marcado como detectado y no como elección del usuario.
    with db_module.conn.cursor() as cur:
        cur.execute(
            "SELECT language, language_is_detected FROM user_preferences "
            "WHERE user_id=%s",
            (user_id,),
        )
        language, detected = cur.fetchone()

    assert language == "en"
    assert detected is True


def test_spanish_is_the_fallback_when_nothing_is_known(db_module):
    user_id = 810004

    i18n.forget_cached_language(user_id)

    with db_module.conn.cursor() as cur:
        cur.execute("DELETE FROM user_preferences WHERE user_id=%s", (user_id,))

    assert i18n.load_user_language(user_id) == "es"
    assert i18n.load_user_language(user_id, telegram_language_code="zh") == "es"


def test_reading_the_language_survives_a_broken_database(monkeypatch):
    """Un fallo de base de datos no debe impedir contestar al cliente."""

    class BrokenConn:
        def cursor(self):
            raise RuntimeError("base de datos caída")

    import db

    monkeypatch.setattr(db, "conn", BrokenConn())
    i18n.forget_cached_language(810005)

    assert i18n.load_user_language(810005) == "es"


# =========================
# TEXTOS TRADUCIDOS
# =========================

def test_renewal_notice_is_translated():
    spanish = rs.build_renewal_text("VIP Fitness", None, price=(15, "EUR"),
                                    stage=rs.RENEWAL_STAGE_EXPIRED)
    english = rs.build_renewal_text("VIP Fitness", None, price=(15, "EUR"),
                                    stage=rs.RENEWAL_STAGE_EXPIRED,
                                    language="en")

    assert "Tu acceso ha caducado" in spanish
    assert "Your access has expired" in english

    # El nombre y el precio no se traducen.
    assert "VIP Fitness" in english
    assert "15 EUR" in english


def test_renewal_buttons_are_translated():
    rows = rs.build_renewal_keyboard(4, language="en").inline_keyboard
    labels = [button.text for row in rows for button in row]

    assert any("Renew" in label for label in labels)
    assert any("question" in label for label in labels)

    # Los callbacks NO se traducen: traducirlos rompería los botones.
    callbacks = [button.callback_data for row in rows for button in row]
    assert "marketplace_group_4" in callbacks
    assert "public_support" in callbacks


def test_abandoned_notice_is_translated():
    english = acs.build_abandoned_text("VIP Fitness", price=(15, "EUR"),
                                       language="en")

    assert "was not completed" in english
    assert "VIP Fitness" in english
    assert "15 EUR" in english
    assert "🛟" in english


def test_abandoned_buttons_are_translated_but_keep_their_callbacks():
    rows = acs.build_abandoned_keyboard(7, language="en").inline_keyboard

    labels = [button.text for row in rows for button in row]
    callbacks = [button.callback_data for row in rows for button in row]

    assert any("Resume" in label for label in labels)
    assert "marketplace_group_7" in callbacks
    assert "public_support" in callbacks


def test_spanish_output_did_not_change():
    """Traducir no debe alterar lo que ya reciben los clientes españoles."""

    text = acs.build_abandoned_text("VIP Fitness", price=(15, "EUR"))

    assert "🛒 ¿Te quedaste a medias?" in text
    assert "Empezaste a entrar en VIP Fitness pero el pago no se completó." in text
    assert "Sigue disponible desde 15 EUR." in text


# =========================
# TIEMPO RESTANTE
# =========================

def test_time_left_is_translated():
    from datetime import datetime, timedelta

    in_three_days = datetime.now() + timedelta(days=3)

    assert "días" in rs.format_days_left(in_three_days)
    assert "days" in rs.format_days_left(in_three_days, language="en")


def test_one_day_is_not_pluralised_in_either_language():
    from datetime import datetime, timedelta

    tomorrow = datetime.now() + timedelta(days=1)

    assert rs.format_days_left(tomorrow) == "en 1 día"
    assert rs.format_days_left(tomorrow, language="en") == "in 1 day"


def test_broken_dates_do_not_crash_either_language():
    assert rs.format_days_left(None) == "muy pronto"
    assert rs.format_days_left(None, language="en") == "very soon"


# =========================
# EL CATÁLOGO
# =========================

def test_every_customer_string_has_an_english_version():
    missing = [
        key
        for key, translations in i18n.TRANSLATIONS.items()
        if not translations.get("en")
    ]

    assert not missing, f"sin traducir al inglés: {missing}"


def test_placeholders_match_between_languages():
    """
    Un marcador distinto entre idiomas deja el texto a medias en producción, y
    solo para los usuarios de ese idioma.
    """

    import re

    for key, translations in i18n.TRANSLATIONS.items():
        spanish = set(re.findall(r"\{(\w+)\}", translations.get("es", "")))

        for language, text in translations.items():
            if language == "es":
                continue

            assert set(re.findall(r"\{(\w+)\}", text)) == spanish, (
                f"{key} ({language}) no usa los mismos marcadores que el español"
            )


def test_an_unknown_key_returns_the_key_instead_of_crashing():
    assert i18n.t("no.existe", "en") == "no.existe"
