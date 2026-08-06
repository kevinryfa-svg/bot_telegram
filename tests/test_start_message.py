import start_handler as sh
from commercial_catalog import PUBLIC_START_TEXT_ES


def patch_offer(monkeypatch, offer):
    monkeypatch.setattr(sh, "fetch_offer_snapshot", lambda limit=3: offer)


def test_shows_catalog_size_and_entry_price(monkeypatch):
    patch_offer(monkeypatch, {
        "total": 3,
        "free_total": 0,
        "cheapest_amount": 9,
        "cheapest_currency": "EUR",
        "examples": [],
    })
    text = sh.build_public_start_message()
    assert "3 comunidades privadas disponibles" in text
    assert "desde 9 EUR" in text


def test_singular_wording(monkeypatch):
    patch_offer(monkeypatch, {
        "total": 1,
        "free_total": 0,
        "cheapest_amount": None,
        "cheapest_currency": None,
        "examples": [],
    })
    text = sh.build_public_start_message()
    assert "1 comunidad privada disponible." in text


def test_free_communities_are_mentioned_with_agreement(monkeypatch):
    patch_offer(monkeypatch, {
        "total": 4, "free_total": 1,
        "cheapest_amount": 5, "cheapest_currency": "EUR", "examples": [],
    })
    assert "1 de ellas es de acceso gratuito." in sh.build_public_start_message()

    patch_offer(monkeypatch, {
        "total": 4, "free_total": 2,
        "cheapest_amount": 5, "cheapest_currency": "EUR", "examples": [],
    })
    assert "2 de ellas son de acceso gratuito." in sh.build_public_start_message()


def test_no_free_communities_says_nothing_about_free(monkeypatch):
    patch_offer(monkeypatch, {
        "total": 2, "free_total": 0,
        "cheapest_amount": 5, "cheapest_currency": "EUR", "examples": [],
    })
    assert "gratuito" not in sh.build_public_start_message()


def test_explains_how_it_works_and_trust_points(monkeypatch):
    patch_offer(monkeypatch, {
        "total": 2, "free_total": 0,
        "cheapest_amount": 5, "cheapest_currency": "EUR", "examples": [],
    })
    text = sh.build_public_start_message()
    for step in ("1️⃣", "2️⃣", "3️⃣"):
        assert step in text
    assert "un solo uso" in text
    assert text.rstrip().endswith("Selecciona una opción:")


def test_falls_back_to_original_text_without_catalog(monkeypatch):
    patch_offer(monkeypatch, {
        "total": 0, "free_total": 0,
        "cheapest_amount": None, "cheapest_currency": None, "examples": [],
    })
    assert sh.build_public_start_message() == PUBLIC_START_TEXT_ES


def test_falls_back_when_catalog_lookup_fails(monkeypatch):
    def boom(limit=3):
        raise RuntimeError("db caída")

    monkeypatch.setattr(sh, "fetch_offer_snapshot", boom)
    assert sh.build_public_start_message() == PUBLIC_START_TEXT_ES


def test_never_shows_markdown_markers(monkeypatch):
    # La pantalla de inicio se envía sin parse_mode: un asterisco se vería tal cual.
    patch_offer(monkeypatch, {
        "total": 3, "free_total": 1,
        "cheapest_amount": 9, "cheapest_currency": "EUR", "examples": [],
    })
    text = sh.build_public_start_message()
    assert "*" not in text
    assert "_" not in text
