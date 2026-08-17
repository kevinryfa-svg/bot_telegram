from datetime import datetime, timedelta

import pytest

import renewal_service as rs


def test_defaults_are_sane():
    assert rs.RENEWAL_EARLY_DAYS >= 1
    assert rs.RENEWAL_BATCH_SIZE >= 1
    assert rs.RENEWAL_SEND_DELAY_SECONDS >= 0


def test_amount_formatting():
    assert rs.format_amount(15, "EUR") == "15 EUR"
    assert rs.format_amount(9.5, "EUR") == "9,5 EUR"
    assert rs.format_amount(10, None) == "10 EUR"
    assert rs.format_amount(None, "EUR") is None
    assert rs.format_amount("x", "EUR") is None


def test_days_left_rounds_up():
    # Dos días exactos se calculan como 47,99 h; truncar diría "1 día".
    almost_two_days = datetime.now() + timedelta(days=2, seconds=-30)
    assert rs.format_days_left(almost_two_days) == "en 2 días"

    assert rs.format_days_left(datetime.now() + timedelta(days=3)) == "en 3 días"
    assert rs.format_days_left(datetime.now() + timedelta(hours=12)) == "en 12 horas"
    assert rs.format_days_left(datetime.now() + timedelta(hours=1, minutes=30)) == "en 2 horas"


def test_days_left_singular():
    assert rs.format_days_left(datetime.now() + timedelta(days=1)) == "en 1 día"


def test_days_left_under_an_hour():
    assert rs.format_days_left(datetime.now() + timedelta(minutes=20)) == "en menos de una hora"


def test_days_left_never_crashes_on_bad_input():
    assert rs.format_days_left(None) == "muy pronto"
    assert rs.format_days_left("no es una fecha") == "muy pronto"


def test_early_reminder_mentions_days_and_price():
    text = rs.build_renewal_text(
        "VIP Fitness",
        datetime.now() + timedelta(days=3),
        price=(15, "EUR"),
        stage=rs.RENEWAL_STAGE_EARLY,
    )
    assert "VIP Fitness" in text
    assert "en 3 días" in text
    assert "15 EUR" in text


def test_last_reminder_has_more_urgent_header():
    early = rs.build_renewal_text(
        "X", datetime.now() + timedelta(days=3), stage=rs.RENEWAL_STAGE_EARLY
    )
    last = rs.build_renewal_text(
        "X", datetime.now() + timedelta(hours=5), stage=rs.RENEWAL_STAGE_LAST
    )
    assert early != last
    assert "caduca pronto" in last


def test_expired_notice_explains_how_to_return():
    text = rs.build_renewal_text(
        "VIP Fitness", None, price=(15, "EUR"), stage=rs.RENEWAL_STAGE_EXPIRED
    )
    assert "ha caducado" in text
    assert "volver a entrar desde 15 EUR" in text
    assert "al instante" in text


def test_texts_work_without_a_known_price():
    for stage in (rs.RENEWAL_STAGE_EARLY, rs.RENEWAL_STAGE_LAST, rs.RENEWAL_STAGE_EXPIRED):
        text = rs.build_renewal_text(
            "X", datetime.now() + timedelta(days=2), price=None, stage=stage
        )
        assert text
        assert "None" not in text


def test_keyboard_offers_renewal_and_support():
    rows = rs.build_renewal_keyboard(7).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]
    assert "marketplace_group_7" in callbacks
    assert "mis_subs" in callbacks
    assert "public_support" in callbacks


def test_expired_keyboard_uses_return_wording():
    labels = [
        b.text
        for row in rs.build_renewal_keyboard(7, stage=rs.RENEWAL_STAGE_EXPIRED).inline_keyboard
        for b in row
    ]
    assert any("Volver a entrar" in label for label in labels)


def test_unreachable_user_detection():
    assert rs.is_unreachable_error("Forbidden: bot was blocked by the user") is True
    assert rs.is_unreachable_error("Chat not found") is True
    assert rs.is_unreachable_error("Timed out") is False
    assert rs.is_unreachable_error(None) is False


# =========================
# UN TOQUE: RENOVAR EL PLAN DE SIEMPRE
# =========================
# Renovar costaba tres toques (aviso → tarjeta → lista de planes → pagar).
# Cada pantalla intermedia es gente que se cae por el camino.

@pytest.fixture
def socio_con_historial(clean_db):
    """Alguien que compró el plan «Mensual» de la comunidad 77."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (77, 'VIP Toque', -1077, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, payment_provider, is_active) VALUES "
            "(77, 'Mensual', 'price_mensual_77', 'price_mensual_77', 30, 15, 'EUR', 'stripe', TRUE), "
            "(77, 'Anual', 'price_anual_77', 'price_anual_77', 365, 120, 'EUR', 'stripe', TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7701, 77, NOW() + INTERVAL '2 days', TRUE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) "
            "VALUES (7701, 77, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '28 days')"
        )

    return db


def test_the_reminder_leads_straight_to_the_plan_they_had(socio_con_historial):
    filas = rs.build_renewal_keyboard(77, user_id=7701).inline_keyboard

    primero = filas[0][0]

    assert primero.callback_data == "price_mensual_77", (
        "el callback es el mismo que pulsaría en la lista de planes"
    )
    assert "Mensual" in primero.text
    assert "15 EUR" in primero.text, (
        "el precio en el botón: nadie pulsa a ciegas para pagar"
    )

    # Y los botones de siempre siguen debajo: el menú no desaparece.
    resto = [b.callback_data for fila in filas[1:] for b in fila]
    assert "marketplace_group_77" in resto


def test_without_a_matching_active_plan_there_is_no_shortcut(socio_con_historial):
    """Mandar a alguien a un plan que no es el suyo es peor que el menú."""

    with socio_con_historial.conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_active=FALSE WHERE name='Mensual'")

    filas = rs.build_renewal_keyboard(77, user_id=7701).inline_keyboard

    assert filas[0][0].callback_data == "marketplace_group_77", (
        "sin plan activo que coincida, los botones de siempre"
    )


def test_a_stranger_gets_the_normal_keyboard(socio_con_historial):
    filas = rs.build_renewal_keyboard(77, user_id=999999).inline_keyboard

    assert filas[0][0].callback_data == "marketplace_group_77"


def test_each_provider_gets_its_own_callback():
    assert rs.same_plan_callback(77, 5, "price_x", "stripe") == "price_x"
    assert rs.same_plan_callback(77, 5, None, "paypal") == "paypal_group_plan_77_5"
    assert rs.same_plan_callback(77, 5, None, "revolut") == "revolut_group_plan_77_5"

    # Sin price_id, Stripe no tiene botón: mejor el menú que uno muerto.
    assert rs.same_plan_callback(77, 5, None, "stripe") is None
    assert rs.same_plan_callback(77, 5, "price_x", "inventado") is None


def test_the_expiry_notice_also_carries_the_shortcut(socio_con_historial):
    _texto, teclado = rs.build_expired_notice(77, "VIP Toque", user_id=7701)

    assert teclado.inline_keyboard[0][0].callback_data == "price_mensual_77", (
        "al caducar es cuando más intención de volver hay"
    )

    worker = open("expiration_worker.py", encoding="utf-8").read()
    assert "user_id=user_id" in worker[
        worker.index("build_expired_notice("):
        worker.index("build_expired_notice(") + 400
    ], "el trabajador de caducidades pasa quién es, o no hay atajo"
