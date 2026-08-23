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


# =========================
# EL RESCATE DE LOS ANTIGUOS
# =========================
# En producción hay 72 intentos de pago a medias a los que NUNCA se les
# escribió: son anteriores a que existiera este recuperador, así que cayeron
# fuera de la ventana de siete días. Es la mayor intención de compra que existe
# en esa base de datos —gente que llegó a la pantalla de Stripe con la tarjeta
# fuera— y encima abandonaron cuando el cobro estaba roto.

def test_the_rescue_window_is_closed_by_default():
    assert acs.ABANDONED_RESCUE_DAYS == 0
    assert acs.ventana_de_dias() == acs.ABANDONED_MAX_AGE_DAYS, (
        "el estado normal es no perseguir intentos antiguos"
    )


def test_opening_the_rescue_widens_the_window(monkeypatch):
    monkeypatch.setattr(acs, "ABANDONED_RESCUE_DAYS", 200)

    assert acs.ventana_de_dias() == 200


def test_an_old_attempt_is_told_the_truth(monkeypatch):
    """Mandarle el recordatorio normal meses después suena a que el bot acaba
    de despertarse. Y hay algo mejor que decir: entonces el cobro estaba roto."""

    from datetime import datetime, timedelta

    monkeypatch.setattr(acs, "ABANDONED_RESCUE_DAYS", 200)

    viejo = datetime.now() - timedelta(days=90)
    reciente = datetime.now() - timedelta(hours=3)

    assert acs.es_rescate(viejo) is True
    assert acs.es_rescate(reciente) is False
    assert acs.es_rescate(None) is False

    texto = acs.build_rescue_text("StarsVip", price=(3.6, "EUR"))

    assert "StarsVip" in texto
    assert "estaba roto" in texto, "por qué no llegó a pagar"
    assert "No fue cosa tuya" in texto
    assert "3,60 EUR" in texto, "y cuánto cuesta ahora"


def test_the_rescue_text_survives_without_a_price(monkeypatch):
    monkeypatch.setattr(acs, "ABANDONED_RESCUE_DAYS", 200)

    texto = acs.build_rescue_text("StarsVip", price=None)

    assert "None" not in texto


def test_nobody_is_chased_when_the_shop_cannot_sell(monkeypatch):
    """Perseguir un carrito para mandar a la gente otra vez al mismo error es
    como se gana un bloqueo."""

    import asyncio

    import reengagement_service as rs

    monkeypatch.setattr(rs, "merece_la_pena_escribir", lambda: (False, "roto"))
    monkeypatch.setattr(acs, "ABANDONED_ENABLED", True)

    def no_deberia(*a, **k):
        raise AssertionError("ni se miran los carritos si no se puede vender")

    monkeypatch.setattr(acs, "fetch_abandoned_checkouts", no_deberia)

    class FakeContext:
        bot = None

    resumen = asyncio.run(acs.process_abandoned_checkouts(FakeContext()))

    assert resumen["sent"] == 0
