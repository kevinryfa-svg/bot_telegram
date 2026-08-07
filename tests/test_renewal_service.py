from datetime import datetime, timedelta

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
