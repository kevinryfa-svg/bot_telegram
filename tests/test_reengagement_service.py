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


# =========================
# EL RELANZAMIENTO: UN AVISO MÁS, Y UNO SOLO
# =========================
# Las 297 personas que gastaron el tope de avisos lo gastaron cuando esto NO
# PODÍA COBRAR: el único plan a la venta se pagaba por un método deshabilitado,
# sin identificador de precio y con la moneda escrita como Stripe no acepta. Su
# «no» fue a una tienda rota. Eso justifica UN aviso más — y las tres
# condiciones que lo impiden convertirse en spam.

def test_without_the_key_there_is_no_relaunch(monkeypatch):
    monkeypatch.setattr(rs, "REENGAGEMENT_RELAUNCH_KEY", "")
    monkeypatch.setattr(rs, "hay_algo_que_vender", lambda: True)

    assert rs.relanzamiento_activo() is False, (
        "el estado normal es no relanzar nada"
    )


def test_with_nothing_to_sell_there_is_no_relaunch(monkeypatch):
    """«Ya funciona» con el escaparate vacío es el último mensaje que abre."""

    monkeypatch.setattr(rs, "REENGAGEMENT_RELAUNCH_KEY", "tienda-arreglada")
    monkeypatch.setattr(rs, "hay_algo_que_vender", lambda: False)

    assert rs.relanzamiento_activo() is False


def test_a_shop_window_error_does_not_announce_anything(monkeypatch):
    def revienta(*a, **k):
        raise RuntimeError("la base no contesta")

    import start_offer_service

    monkeypatch.setattr(
        start_offer_service, "fetch_sellable_communities", revienta
    )

    assert rs.hay_algo_que_vender() is False, (
        "ante la duda no se escribe: un error de lectura no es una tienda llena"
    )


def test_the_relaunch_message_starts_by_admitting_it_was_broken():
    texto = rs.build_relaunch_text(offer(total=1, cheapest_amount=29,
                                         cheapest_currency="EUR"))

    assert "no funcionaba" in texto or "estaba roto" in texto, (
        "es lo único que justifica un séptimo mensaje: que algo cambió"
    )
    assert "No quiero más avisos" in texto, (
        "y la salida, dicha en el propio texto"
    )


def test_the_relaunch_message_is_not_the_same_old_one():
    normal = rs.build_reengagement_text(offer(total=1), variant=0)
    relanzamiento = rs.build_reengagement_text(offer(total=1), relanzamiento=True)

    assert relanzamiento != normal


def _persona_que_gasto_el_tope(db, user_id=5501, relaunch_key=None):
    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bot_user_events (user_id, event_type) VALUES (%s, %s)",
            (user_id, "start")
        )
        cur.execute(
            "INSERT INTO user_reengagement (user_id, sent_count, last_sent_at, "
            "relaunch_key) VALUES (%s, %s, NOW() - INTERVAL '60 days', %s)",
            (user_id, rs.REENGAGEMENT_MAX_MESSAGES, relaunch_key)
        )


def test_the_relaunch_reaches_someone_who_had_run_out_of_notices(clean_db,
                                                                 monkeypatch):
    _persona_que_gasto_el_tope(clean_db)

    monkeypatch.setattr(rs, "REENGAGEMENT_RELAUNCH_KEY", "tienda-arreglada")
    monkeypatch.setattr(rs, "hay_algo_que_vender", lambda: True)

    assert 5501 in [u for u, _ in rs.fetch_reengagement_targets()]


def test_nobody_gets_the_same_relaunch_twice(clean_db, monkeypatch):
    """Con la clave anotada ya no vuelve a entrar: es una excepción, no un
    grifo abierto."""

    _persona_que_gasto_el_tope(clean_db, relaunch_key="tienda-arreglada")

    monkeypatch.setattr(rs, "REENGAGEMENT_RELAUNCH_KEY", "tienda-arreglada")
    monkeypatch.setattr(rs, "hay_algo_que_vender", lambda: True)

    assert 5501 not in [u for u, _ in rs.fetch_reengagement_targets()]


def test_the_cap_still_holds_when_there_is_no_relaunch(clean_db, monkeypatch):
    _persona_que_gasto_el_tope(clean_db)

    monkeypatch.setattr(rs, "REENGAGEMENT_RELAUNCH_KEY", "")

    assert 5501 not in [u for u, _ in rs.fetch_reengagement_targets()]


def test_someone_who_said_no_is_never_relaunched(clean_db, monkeypatch):
    """El «no» de una persona vale más que cualquier relanzamiento."""

    _persona_que_gasto_el_tope(clean_db)

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "UPDATE user_reengagement SET opted_out=TRUE WHERE user_id=5501"
        )

    monkeypatch.setattr(rs, "REENGAGEMENT_RELAUNCH_KEY", "tienda-arreglada")
    monkeypatch.setattr(rs, "hay_algo_que_vender", lambda: True)

    assert 5501 not in [u for u, _ in rs.fetch_reengagement_targets()]

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "UPDATE user_reengagement SET opted_out=FALSE, is_blocked=TRUE "
            "WHERE user_id=5501"
        )

    assert 5501 not in [u for u, _ in rs.fetch_reengagement_targets()], (
        "quien bloqueó el bot tampoco: escribirle es pedir una denuncia"
    )


def test_marking_the_relaunch_is_what_closes_the_door(clean_db):
    _persona_que_gasto_el_tope(clean_db)

    rs.mark_reengagement_sent(5501, relaunch_key="tienda-arreglada")

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "SELECT relaunch_key, sent_count FROM user_reengagement "
            "WHERE user_id=5501"
        )
        clave, enviados = cur.fetchone()

    assert clave == "tienda-arreglada"
    assert enviados == rs.REENGAGEMENT_MAX_MESSAGES + 1


def test_a_normal_send_does_not_erase_a_relaunch_already_noted(clean_db):
    _persona_que_gasto_el_tope(clean_db, relaunch_key="tienda-arreglada")

    rs.mark_reengagement_sent(5501)

    with clean_db.conn.cursor() as cur:
        cur.execute("SELECT relaunch_key FROM user_reengagement WHERE user_id=5501")
        assert cur.fetchone()[0] == "tienda-arreglada", (
            "borrarla dejaría a esa persona lista para recibir otra vez el "
            "mismo relanzamiento"
        )
