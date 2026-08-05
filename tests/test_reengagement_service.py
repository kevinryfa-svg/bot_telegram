import reengagement_service as rs


def offer(**kwargs):
    base = {
        "total": 0,
        "free_total": 0,
        "cheapest_amount": None,
        "cheapest_currency": None,
        "examples": [],
    }
    base.update(kwargs)
    return base


def test_defaults_are_conservative():
    # Cada 3 días, con tope de mensajes y pausa entre envíos.
    assert rs.REENGAGEMENT_INTERVAL_DAYS == 3
    assert rs.REENGAGEMENT_MAX_MESSAGES >= 1
    assert rs.REENGAGEMENT_BATCH_SIZE >= 1
    assert rs.REENGAGEMENT_SEND_DELAY_SECONDS > 0


def test_format_price_trims_decimals_and_uses_comma():
    assert rs.format_price(9, "EUR") == "9 EUR"
    assert rs.format_price(9.5, "EUR") == "9,5 EUR"
    assert rs.format_price(15.00, "USD") == "15 USD"
    assert rs.format_price(None, "EUR") is None
    assert rs.format_price("no-numero", "EUR") is None


def test_format_price_defaults_currency():
    assert rs.format_price(10, None) == "10 EUR"


def test_catalog_line_singular_and_plural():
    assert "1 comunidad" in rs.describe_catalog(offer(total=1))
    assert "disponible." in rs.describe_catalog(offer(total=1))
    assert "7 comunidades" in rs.describe_catalog(offer(total=7))
    assert "disponibles." in rs.describe_catalog(offer(total=7))


def test_catalog_line_includes_entry_price_when_known():
    line = rs.describe_catalog(
        offer(total=3, cheapest_amount=9, cheapest_currency="EUR")
    )
    assert "desde *9 EUR*" in line


def test_catalog_line_without_communities_invents_nothing():
    line = rs.describe_catalog(offer(total=0))
    assert "0 " not in line
    assert "comunidades privadas disponibles" in line


def test_examples_show_price_or_free():
    lines = rs.describe_examples(offer(examples=[
        ("VIP Fitness", "Fitness", False, 15, "EUR"),
        ("Cripto Free", "Cripto", True, None, None),
    ]))
    assert "• VIP Fitness (Fitness) — 15 EUR" in lines
    assert "• Cripto Free (Cripto) — gratis" in lines


def test_examples_tolerate_short_rows():
    # No debe romper si la fila no trae precio.
    lines = rs.describe_examples(offer(examples=[("Solo nombre",)]))
    assert lines == ["• Solo nombre"]


def test_four_distinct_variants_rotate():
    data = offer(total=3, free_total=1, cheapest_amount=9, cheapest_currency="EUR")
    texts = [rs.build_reengagement_text(data, v) for v in range(4)]
    assert len(set(texts)) == 4, "las cuatro variantes deben ser distintas"
    # La rotación es modular: el 5º aviso reutiliza la 1ª variante.
    assert rs.build_reengagement_text(data, 4) == texts[0]
    assert rs.build_reengagement_text(data, 9) == texts[1]


def test_first_variant_explains_how_it_works():
    text = rs.build_reengagement_text(offer(total=2), 0)
    for step in ("1️⃣", "2️⃣", "3️⃣"):
        assert step in text
    assert "Stripe" in text


def test_second_variant_leads_with_price():
    text = rs.build_reengagement_text(
        offer(total=2, cheapest_amount=9, cheapest_currency="EUR"), 1
    )
    assert "9 EUR" in text


def test_third_variant_mentions_free_access_only_when_real():
    with_free = rs.build_reengagement_text(offer(total=2, free_total=1), 2)
    assert "gratuito" in with_free

    without_free = rs.build_reengagement_text(offer(total=2, free_total=0), 2)
    assert "gratuito" not in without_free


def test_last_variant_is_short_and_mentions_opt_out():
    text = rs.build_reengagement_text(offer(total=2), 3)
    assert len(text) < len(rs.build_reengagement_text(offer(total=2), 0))
    assert "desactivar estos avisos" in text


def test_every_variant_ends_with_call_to_action():
    for v in range(4):
        assert rs.build_reengagement_text(offer(total=2), v).rstrip().endswith("👇")


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
