"""
«¿Puede vender mi comunidad?»: la respuesta, con lo que falta.

Una comunidad puede estar publicada y no vender nada por un detalle
invisible: el bot sin permiso de invitar, ningún plan usable, ningún cobro
disponible. El propietario nuevo no sabe que esas condiciones existen: monta
la comunidad, no le compra nadie, y se va.

Las dos reglas de honestidad: cada línea sale de la MISMA fuente que
gobierna esa condición al comprar (si aquí dijera "listo" y el checkout
dijera que no, la pantalla sería una mentira), y no hay medallas ni
porcentajes — lo que hace falta es la lista de lo que falta.
"""

import pytest

import owner_readiness_service as ors


@pytest.fixture
def comunidad(clean_db):
    """Comunidad 87 recién creada: sin nada configurado."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM group_delivery_health WHERE group_id=87")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, is_main_menu_visible) "
            "VALUES (87, 'VIP Nueva', -1087, TRUE, FALSE, FALSE)"
        )

    return db


def preparar_todo(db):
    """Deja la comunidad 87 lista para vender."""

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver, bot_status) "
            "VALUES (87, TRUE, 'administrator') "
            "ON CONFLICT (group_id) DO UPDATE SET can_deliver=TRUE"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) "
            "VALUES (87, 'Mensual', 'price_m87', 'price_m87', 30, 15, 'EUR', TRUE)"
        )
        cur.execute(
            "UPDATE groups SET is_marketplace_visible=TRUE WHERE id=87"
        )


def test_a_brand_new_community_is_told_exactly_what_is_missing(comunidad):
    texto = ors.build_readiness_text(87, "VIP Nueva")

    assert "🚦 ¿Puede vender VIP Nueva?" in texto
    assert "Faltan" in texto

    # Cada condición aparece con su estado y su qué-hacer.
    assert "❌ Entrega de accesos" in texto
    assert "❌ Planes de venta" in texto
    assert "❌ Visibilidad" in texto
    assert "no puede encontrarla" in texto


def test_the_delivery_check_says_how_to_fix_it(comunidad):
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver, bot_status, detail) "
            "VALUES (87, FALSE, 'member', 'sin permiso de invitar')"
        )

    ok, texto = ors.check_delivery(87)

    assert ok is False
    assert "administrador" in texto
    assert "invitar" in texto
    assert "sin eso no se puede entregar lo que se cobre" in texto


def test_a_plan_without_duration_counts_as_no_plan(comunidad):
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) "
            "VALUES (87, 'Roto', 'price_r87', 'price_r87', NULL, 15, 'EUR', TRUE)"
        )

    ok, texto = ors.check_plans(87)

    assert ok is False, (
        "un plan sin duración aparece y no se puede conceder: es peor que "
        "ninguno"
    )
    # La frase cambió al aparecer una segunda forma de no ser vendible (una
    # duración que el cobro se niega a entregar): «precio y duración» ya no
    # cubría las dos, y el panel dice ahora lo que de verdad importa.
    assert "que se pueda entregar" in texto


def test_a_broken_plan_next_to_a_good_one_is_flagged_without_blocking(comunidad):
    preparar_todo(comunidad)

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) "
            "VALUES (87, 'Roto', 'price_r87', 'price_r87', 0, 15, 'EUR', TRUE)"
        )

    ok, texto = ors.check_plans(87)

    assert ok is True
    assert "1 plan activo" in texto
    assert "no se pueden entregar" in texto


def test_the_payment_check_asks_the_same_code_the_checkout_asks(comunidad, monkeypatch):
    import payment_service

    monkeypatch.setattr(payment_service, "is_stripe_payments_enabled",
                        lambda: False)
    monkeypatch.setattr(payment_service, "is_paypal_group_checkout_available",
                        lambda group_id: False)
    monkeypatch.setattr(payment_service, "is_revolut_group_checkout_available",
                        lambda group_id: False)
    monkeypatch.setattr(payment_service, "is_changenow_group_checkout_available",
                        lambda group_id: False)
    monkeypatch.setattr(payment_service, "is_guardarian_group_checkout_available",
                        lambda group_id: False)

    ok, texto = ors.check_payment_methods(87)

    assert ok is False
    assert "Ningún método de cobro" in texto

    monkeypatch.setattr(payment_service, "is_stripe_payments_enabled",
                        lambda: True)

    ok, texto = ors.check_payment_methods(87)

    assert ok is True
    assert "Stripe" in texto


def test_a_deactivated_community_is_shown_to_nobody(comunidad):
    with comunidad.conn.cursor() as cur:
        cur.execute("UPDATE groups SET is_active=FALSE WHERE id=87")

    ok, texto = ors.check_visibility(87)

    assert ok is False
    assert "desactivada" in texto


def test_when_everything_is_ready_it_says_where_to_look_next(comunidad):
    preparar_todo(comunidad)

    filas = ors.collect_readiness(87)
    fallos = [titulo for ok, titulo, _d in filas if not ok]

    assert fallos in ([], ["Métodos de cobro"]), (
        "sin claves de Stripe en el entorno de pruebas, el cobro puede no "
        "estar disponible; el resto tiene que estar listo"
    )

    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT can_deliver FROM group_delivery_health WHERE group_id=87")
        assert cur.fetchone()[0] is True


def test_the_panel_has_the_button_with_the_same_permissions():
    panel = open("owner_panel_callbacks.py", encoding="utf-8").read()

    assert 'callback_data="owner_panel_ready"' in panel
    assert 'if data == "owner_panel_ready":' in panel

    pos = panel.index('if data == "owner_panel_ready":')
    trozo = panel[pos:pos + 900]

    for permiso in ("can_manage_plans", "can_manage_groups",
                    "can_view_payments", "can_manage_payments"):
        assert permiso in trozo
