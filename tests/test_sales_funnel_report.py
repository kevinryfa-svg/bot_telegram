"""El embudo de seis etapas que sale en el registro del arranque."""

import pytest

import sales_funnel_report_service as sfr


@pytest.fixture
def embudo(clean_db):
    """
    10 llegan, 6 ven la comunidad, 4 abren planes, 2 pulsan pagar,
    1 llega a Stripe, 1 paga. Y uno que pulsa seis veces cuenta UNA.
    """

    db = clean_db

    with db.conn.cursor() as cur:

        ev = ("INSERT INTO bot_user_events (user_id, event_type, event_key) "
              "VALUES (%s, %s, %s)")

        for uid in range(9001, 9011):
            cur.execute(ev, (uid, "start", "/start"))

        for uid in range(9001, 9007):
            cur.execute(ev, (uid, "community_viewed", None))

        for uid in range(9001, 9005):
            cur.execute(ev, (uid, "callback", "group_1159"))

        for _ in range(6):
            cur.execute(ev, (9001, "callback", "price_abc"))

        cur.execute(ev, (9002, "callback", "startbuy_1159_26"))

        # Botones que NO son abrir planes: group_admin_panel, group_plans_help.
        cur.execute(ev, (9009, "callback", "group_plans_help"))

        cur.execute(
            "INSERT INTO payment_transactions (provider, status, user_id, "
            "group_id) VALUES ('stripe', 'pending', 9001, 1159)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status) "
            "VALUES (9001, 1159, 360, 'EUR', 'paid')"
        )

    return db


def test_each_stage_counts_distinct_people(embudo):
    e = sfr.fetch_embudo(30)

    assert e == {
        "llegan": 10, "ven": 6, "planes": 4,
        "pulsan": 2, "stripe": 1, "pagan": 1,
    }


def test_a_help_button_is_not_opening_the_plans(embudo):
    """«group_plans_help» empieza por group_ pero no es la lista de planes."""

    assert sfr.fetch_embudo(30)["planes"] == 4


def test_the_biggest_drop_is_named(embudo):
    caida = sfr.donde_se_pierde(30)

    assert "4 de 10" in caida
    assert "abren el bot" in caida and "ven una comunidad" in caida


def test_the_startup_lines_include_the_audience_and_the_money(embudo):
    lineas = sfr.describe_para_el_arranque()

    texto = "\n".join(lineas)

    assert "Embudo 30 días: 10 abren el bot" in texto
    assert "1 pagan" in texto
    assert "Ingresos 30 días: 3.60 EUR" in texto


def test_a_failing_count_says_question_mark_not_zero(clean_db, monkeypatch):
    monkeypatch.setitem(sfr.SQL_ETAPAS, "pagan", "SELECT * FROM tabla_que_no_existe")

    e = sfr.fetch_embudo(30)

    assert e["pagan"] is None
    assert "? pagan" in sfr.linea_de_embudo(30)


def test_the_card_report_says_what_is_missing(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, preview_text) VALUES "
            "(1159, 'StarsVip', -1001159, TRUE, TRUE, 'Contenido exclusivo.')"
        )

    linea = sfr.describe_fichas()[0]

    assert "NO se vende" in linea, "sin planes, no hay nada que comprar"

    assert "«Contenido exclusivo.»" in linea, "una descripción corta se cita"
    assert "SIN foto" in linea
    assert "SIN vídeo" in linea
    assert "sin categoría" in linea


def test_a_complete_card_says_so(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, preview_text, preview_image_file_id, "
            "preview_video_file_id, category) VALUES "
            "(1160, 'Otra', -1001160, TRUE, TRUE, %s, 'AgACfoto', 'BAACvideo', 'vip')",
            ("x" * 200,)
        )

    linea = sfr.describe_fichas()[0]

    assert "200 caracteres" in linea
    assert "con foto" in linea and "con vídeo" in linea


def test_a_card_visible_through_public_visibility_is_reported(clean_db):
    """
    En producción StarsVip se ve por public_visibility y no por
    is_marketplace_visible: el informe la dejaba fuera.
    """

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, public_visibility, preview_text) VALUES "
            "(1161, 'StarsVip', -1001161, TRUE, FALSE, 'both', 'Algo')"
        )

    assert any("StarsVip" in l for l in sfr.describe_fichas())



def test_the_card_that_is_sold_is_reported_even_if_not_in_the_catalog(clean_db):
    """StarsVip se vende desde /start con visibilidad start_home."""

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, public_visibility, preview_text) VALUES "
            "(1159, 'StarsVip', -1001159, TRUE, FALSE, 'start_home', 'Algo')"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(24, 1159, 'Anual', 'p24', 'p24', 360, 29, 'EUR', TRUE)"
        )

    lineas = sfr.describe_fichas()

    assert any("StarsVip" in l and "SE VENDE" in l for l in lineas), lineas


def test_the_relaunch_audience_excludes_payers_members_and_the_no(clean_db, monkeypatch):
    import reengagement_service as rs

    monkeypatch.setattr(rs, "ADMIN_ID", 1)

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (70, 'G', -1070, TRUE)"
        )
        ev = "INSERT INTO bot_user_events (user_id, event_type) VALUES (%s, 'start')"
        for uid in (7001, 7002, 7003, 7004, 7005):
            cur.execute(ev, (uid,))
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status) "
            "VALUES (7002, 70, 900, 'EUR', 'paid')"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7003, 70, NOW() + INTERVAL '9 days', TRUE)"
        )
        cur.execute(
            "INSERT INTO user_reengagement (user_id, opted_out) VALUES (7004, TRUE)"
        )
        cur.execute(
            "INSERT INTO user_reengagement (user_id, is_blocked) VALUES (7005, TRUE)"
        )

    assert rs.contar_audiencia_de_relanzamiento() == 1, "solo 7001"
