"""
El embudo: cuánta gente mira, cuánta empieza a pagar y cuánta paga.

Ingresos dice cuánto entra y retención cuánto se queda. Faltaba la pregunta
que decide qué hacer mañana: si no vendo, ¿no viene nadie, espanta el precio,
o se rompe el pago? Tres problemas distintos con tres soluciones distintas.

Las dos reglas de honestidad: se cuentan PERSONAS distintas (quien abre la
ficha seis veces es un interesado, no seis) y sin base no hay porcentaje —
un porcentaje sobre cero no es un cero, es un "no se sabe".
"""

import pytest

import owner_funnel_service as ofs


def vista(db, user_id, group_id=62, hace_dias=0):
    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bot_user_events (user_id, event_type, event_key, group_id, created_at) "
            "VALUES (%s, 'community_viewed', %s, %s, NOW() - (%s || ' days')::interval)",
            (user_id, f"marketplace_group_{group_id}", group_id, hace_dias)
        )


@pytest.fixture
def comunidad(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM bot_user_events WHERE group_id=62")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (62, 'VIP Embudo', -1062, TRUE)"
        )

    return db


def test_the_same_person_looking_six_times_is_one_interested(comunidad):
    for _ in range(6):
        vista(comunidad, 6201)

    vista(comunidad, 6202)

    numeros = ofs.fetch_funnel(62)

    assert numeros["miran"] == 2, (
        "contar pulsaciones convertiría una buena conversión en un desastre "
        "aparente"
    )


def test_old_views_are_out_of_the_window(comunidad):
    vista(comunidad, 6201, hace_dias=2)
    vista(comunidad, 6202, hace_dias=90)

    assert ofs.fetch_funnel(62, days=30)["miran"] == 1


def test_the_three_steps_come_from_data_already_stored(comunidad):
    for uid in (6201, 6202, 6203, 6204):
        vista(comunidad, uid)

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_transactions (provider, status, purchase_type, "
            "user_id, group_id) VALUES "
            "('stripe', 'pending', 'group_access', 6201, 62), "
            "('stripe', 'paid', 'group_access', 6202, 62)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (6202, 62, 1500, 'EUR', 'paid', 'Mensual')"
        )

    numeros = ofs.fetch_funnel(62)

    assert numeros == {"miran": 4, "empiezan": 2, "pagan": 1}

    texto = ofs.build_owner_funnel_text(62, "VIP Embudo")

    assert "👀 Han mirado la comunidad: 4" in texto
    assert "💳 Han pedido el pago: 2" in texto
    assert "✅ Han pagado: 1" in texto
    assert "De mirar a intentarlo: 50%" in texto
    assert "De intentarlo a pagar: 50%" in texto
    assert "De mirar a pagar: 25%" in texto


def test_without_views_there_is_no_percentage_invented(comunidad):
    texto = ofs.build_owner_funnel_text(62, "VIP Embudo")

    assert "no hay conversión que calcular" in texto
    assert "No es un 0%" in texto
    assert ofs.porcentaje(0, 0) is None


def test_with_too_few_visitors_it_refuses_to_diagnose(comunidad):
    for uid in range(6201, 6206):
        vista(comunidad, uid)

    texto = ofs.build_owner_funnel_text(62, "VIP Embudo")

    assert "todavía no se puede diagnosticar nada" in texto, (
        "con cinco visitas cualquier diagnóstico es ruido"
    )


def test_nobody_finishing_the_payment_points_at_the_payment(comunidad):
    for uid in range(6201, 6216):
        vista(comunidad, uid)

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_transactions (provider, status, purchase_type, "
            "user_id, group_id) VALUES "
            "('stripe', 'pending', 'group_access', 6201, 62), "
            "('stripe', 'pending', 'group_access', 6202, 62)"
        )

    texto = ofs.build_owner_funnel_text(62, "VIP Embudo")

    assert "NADIE termina" in texto
    assert "no es el precio: es el pago" in texto.lower()


def test_people_leaving_before_trying_points_at_price_or_description(comunidad):
    for uid in range(6301, 6351):
        vista(comunidad, uid)

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_transactions (provider, status, purchase_type, "
            "user_id, group_id) VALUES ('stripe', 'paid', 'group_access', 6301, 62)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (6301, 62, 1500, 'EUR', 'paid', 'Mensual')"
        )

    texto = ofs.build_owner_funnel_text(62, "VIP Embudo")

    assert "se va antes de intentarlo" in texto
    assert "el precio" in texto


def test_a_healthy_funnel_says_what_to_do_next(comunidad):
    for uid in range(6401, 6421):
        vista(comunidad, uid)

    with comunidad.conn.cursor() as cur:
        for uid in range(6401, 6411):
            cur.execute(
                "INSERT INTO payment_transactions (provider, status, purchase_type, "
                "user_id, group_id) VALUES ('stripe', 'paid', 'group_access', %s, 62)",
                (uid,)
            )
            cur.execute(
                "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
                "VALUES (%s, 62, 1500, 'EUR', 'paid', 'Mensual')",
                (uid,)
            )

    texto = ofs.build_owner_funnel_text(62, "VIP Embudo")

    assert "El embudo está sano" in texto
    assert "más gente arriba" in texto


def test_the_panel_has_the_button_with_the_same_permissions():
    panel = open("owner_panel_callbacks.py", encoding="utf-8").read()

    assert 'callback_data="owner_panel_funnel"' in panel

    pos = panel.index('if data == "owner_panel_funnel":')
    trozo = panel[pos:pos + 900]

    for permiso in ("can_manage_plans", "can_manage_groups",
                    "can_view_payments", "can_manage_payments"):
        assert permiso in trozo
