import reengagement_service as rs


def test_defaults_are_conservative():
    # Cada 3 días, con tope de mensajes y pausa entre envíos.
    assert rs.REENGAGEMENT_INTERVAL_DAYS == 3
    assert rs.REENGAGEMENT_MAX_MESSAGES >= 1
    assert rs.REENGAGEMENT_BATCH_SIZE >= 1
    assert rs.REENGAGEMENT_SEND_DELAY_SECONDS > 0


def test_message_singular_and_plural():
    # El recuento va en negrita Markdown: "*1 comunidad* disponible"
    one = rs.build_reengagement_text({"total": 1, "examples": []})
    assert "1 comunidad" in one
    assert "disponible en el bot" in one
    assert "comunidades" not in one.split("Cómo funciona")[0]

    many = rs.build_reengagement_text({"total": 7, "examples": []})
    assert "7 comunidades" in many
    assert "disponibles en el bot" in many


def test_message_without_communities_does_not_invent_numbers():
    text = rs.build_reengagement_text({"total": 0, "examples": []})
    assert "0 " not in text
    assert "comunidades privadas disponibles" in text


def test_message_lists_examples_and_marks_free():
    text = rs.build_reengagement_text({
        "total": 2,
        "examples": [("VIP Fitness", "Fitness", False), ("Gratis", "", True)],
    })
    assert "VIP Fitness (Fitness)" in text
    assert "· gratis" in text


def test_message_explains_how_it_works():
    text = rs.build_reengagement_text({"total": 3, "examples": []})
    for step in ("1️⃣", "2️⃣", "3️⃣"):
        assert step in text
    assert "Stripe" in text


def test_keyboard_has_explore_support_and_optout():
    rows = rs.build_reengagement_keyboard().inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]
    assert "start_explore_groups" in callbacks
    assert "public_support" in callbacks
    assert rs.CALLBACK_REENGAGEMENT_STOP in callbacks


def test_blocked_error_detection():
    assert rs.is_blocked_error("Forbidden: bot was blocked by the user") is True
    assert rs.is_blocked_error("Chat not found") is True
    assert rs.is_blocked_error("user is deactivated") is True
    assert rs.is_blocked_error("Timed out") is False
    assert rs.is_blocked_error(None) is False
