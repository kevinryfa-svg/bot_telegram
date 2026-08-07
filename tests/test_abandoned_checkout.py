import abandoned_checkout_service as acs


def test_defaults_are_sane():
    # Ni tan pronto que moleste, ni tan tarde que ya no sirva.
    assert acs.ABANDONED_AFTER_HOURS >= 1
    assert acs.ABANDONED_MAX_AGE_DAYS >= 1
    assert acs.ABANDONED_BATCH_SIZE >= 1
    assert acs.ABANDONED_SEND_DELAY_SECONDS >= 0


def test_paid_statuses_cover_the_usual_wording():
    for status in ("paid", "completed", "succeeded"):
        assert status in acs.PAID_STATUSES


def test_message_names_the_community_and_price():
    text = acs.build_abandoned_text("VIP Fitness", price=(15, "EUR"))
    assert "VIP Fitness" in text
    assert "15 EUR" in text
    assert "no se completó" in text


def test_message_works_without_price():
    text = acs.build_abandoned_text("VIP Fitness", price=None)
    assert "VIP Fitness" in text
    assert "None" not in text


def test_message_offers_help_without_blaming_the_user():
    text = acs.build_abandoned_text("X", price=(9, "EUR"))
    assert "🛟" in text
    assert "al instante" in text


def test_keyboard_lets_them_resume_or_ask():
    rows = acs.build_abandoned_keyboard(4).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]
    assert "marketplace_group_4" in callbacks
    assert "public_support" in callbacks


def test_keyboard_has_no_dead_buttons():
    rows = acs.build_abandoned_keyboard(4).inline_keyboard
    for row in rows:
        for button in row:
            assert button.callback_data
            assert button.text
