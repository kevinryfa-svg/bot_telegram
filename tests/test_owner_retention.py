"""
Retención: cuánto duran los clientes y cuántos se van.

Las tres reglas de honestidad de esta pantalla: la vida media se mide solo
sobre clientes que YA terminaron (meter a los activos la hunde y miente a
la baja), sin base no hay porcentaje (un 0% inventado parecería una buena
noticia), y las devoluciones no cuentan ni como ingreso ni como vida.
"""

import pytest

import owner_retention_service as ors


@pytest.fixture
def comunidad(clean_db):
    """
    Grupo 93 con historia: dos activos, dos que se fueron este mes, uno que
    se fue hace mucho, y una devolución que no puede contar.
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (93, 'VIP Retención', -1093, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) VALUES "
            # Activos.
            "(9301, 93, NOW() + INTERVAL '20 days', TRUE), "
            "(9302, 93, NOW() + INTERVAL '5 days', TRUE), "
            # Bajas del mes: uno duró 60 días, otro 30.
            "(9303, 93, NOW() - INTERVAL '3 days', FALSE), "
            "(9304, 93, NOW() - INTERVAL '10 days', FALSE), "
            # Baja antigua (fuera de los 30 días).
            "(9305, 93, NOW() - INTERVAL '200 days', FALSE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            # 9301 repite: dos pagos.
            "(9301, 93, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '50 days'), "
            "(9301, 93, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '20 days'), "
            "(9302, 93, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '25 days'), "
            # 9303 empezó hace 63 días y caducó hace 3 → 60 días de vida.
            "(9303, 93, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '63 days'), "
            # 9304 empezó hace 40 y caducó hace 10 → 30 días de vida.
            "(9304, 93, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '40 days'), "
            # 9305 tiene una devolución: no es un cliente pagado.
            "(9305, 93, 1500, 'EUR', 'refunded', 'Mensual', NOW() - INTERVAL '230 days')"
        )

    return db


def test_the_churn_rate_is_measured_against_who_could_leave(comunidad):
    numeros = ors.fetch_churn_numbers(93)

    assert numeros["activos"] == 2
    assert numeros["bajas_30"] == 2, "la baja de hace 200 días no es de este mes"
    assert numeros["tasa"] == 50, "2 de 4: los activos más los que se fueron"


def test_average_life_only_counts_customers_who_finished(comunidad):
    numeros = ors.fetch_lifetime_numbers(93)

    assert numeros["clientes_cerrados"] == 2, (
        "9305 solo tiene una devolución: no fue cliente pagado"
    )
    assert 44 <= numeros["vida_dias"] <= 46, (
        "media de 60 y 30 días; incluir a los activos la hundiría"
    )


def test_the_value_per_customer_is_the_ceiling_for_acquisition(comunidad):
    numeros = ors.fetch_lifetime_numbers(93)

    # 5 pagos cobrados (9301 pagó dos veces) = 75.00 EUR entre 4 clientes
    # distintos → 18.75 de media por cliente.
    assert numeros["valor"] == 1875
    assert numeros["currency"] == "EUR"


def test_the_second_payment_is_what_makes_it_a_subscription(comunidad):
    numeros = ors.fetch_repeat_numbers(93)

    assert numeros["clientes"] == 4, "la devolución no crea un cliente"
    assert numeros["repiten"] == 1
    assert numeros["porcentaje"] == 25


def test_the_screen_shows_the_arithmetic_not_just_the_percentage(comunidad):
    texto = ors.build_owner_retention_text(93, "VIP Retención")

    assert "🔄 Retención de VIP Retención" in texto
    assert "Tasa de bajas: 50% (2 de 4)" in texto
    assert "días" in texto
    assert "18.75 EUR" in texto
    assert "techo de lo que tiene sentido gastar" in texto
    assert "Han pagado más de una vez: 1 de 4 (25%)" in texto
    assert "Menos de un tercio llega al segundo pago" not in texto, (
        "el diagnóstico duro solo con base suficiente (5 clientes o más)"
    )


def test_an_empty_community_says_so_instead_of_inventing_a_zero(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (94, 'VIP Vacía', -1094, TRUE)"
        )

    texto = ors.build_owner_retention_text(94, "VIP Vacía")

    assert "todavía sin datos" in texto
    assert "Todavía no se ha ido nadie" in texto
    assert "Todavía no hay pagos que contar" in texto
    assert "0%" not in texto, (
        "un 0% inventado parecería una buena noticia"
    )


def test_the_panel_has_the_button_and_the_same_permissions():
    panel = open("owner_panel_callbacks.py", encoding="utf-8").read()

    assert 'callback_data="owner_panel_retention"' in panel
    assert 'if data == "owner_panel_retention":' in panel

    pos = panel.index('if data == "owner_panel_retention":')
    trozo = panel[pos:pos + 900]

    for permiso in ("can_manage_plans", "can_manage_groups",
                    "can_view_payments", "can_manage_payments"):
        assert permiso in trozo, (
            "la retención se calcula con los mismos pagos: mismos permisos"
        )


# =========================
# EL COSTE DE LOS REFERIDOS
# =========================
# El programa de referidos regala días de acceso: coste de adquisición real,
# pagado en producto. El propietario lo estaba pagando sin verlo en ninguna
# pantalla, y un coste invisible es un coste que nadie decide.

def test_the_referral_cost_counts_both_sides(comunidad):
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO referrals (referrer_user_id, invited_user_id, group_id, "
            "status, days_awarded) VALUES "
            "(9301, 9401, 93, 'converted', 7), "
            "(9301, 9402, 93, 'converted', 7), "
            "(9301, 9403, 93, 'pending', 0)"
        )

    numeros = ors.fetch_referral_cost(93)

    assert numeros["invitados"] == 3
    assert numeros["convertidos"] == 2
    assert numeros["dias"] == 28, (
        "cada referido convertido cuesta el doble: cobran los dos lados"
    )


def test_the_screen_frames_it_as_acquisition_cost(comunidad):
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO referrals (referrer_user_id, invited_user_id, group_id, "
            "status, days_awarded) VALUES (9301, 9401, 93, 'converted', 7)"
        )

    texto = ors.build_owner_retention_text(93, "VIP Retención")

    assert "🎁 Referidos" in texto
    assert "Invitados: 1 · han pagado: 1" in texto
    assert "Días de acceso regalados: 14" in texto
    assert "coste de adquisición pagado en producto" in texto, (
        "el número solo sirve si se puede comparar con lo que paga un cliente"
    )


def test_a_community_without_referrals_gets_no_empty_section(comunidad):
    texto = ors.build_owner_retention_text(93, "VIP Retención")

    assert "🎁 Referidos" not in texto, (
        "una sección que dice '0 invitados' en toda comunidad que no usa el "
        "programa es ruido"
    )
