"""
El panel global de la plataforma, y el entierro de las tres mentiras.

La pantalla «Ingresos» del menú de negocio contaba devoluciones como
ingreso, mezclaba monedas bajo MAX(currency) y mostraba céntimos como si
fueran unidades. Estas pruebas fijan las tres reglas de dinero de la casa
sobre la vista global Y sobre la vista acotada de un admin de grupos.
"""

import pytest

import platform_revenue_service as prs


@pytest.fixture
def plataforma(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) VALUES "
            "(88, 'Alfa', -1088, TRUE), (89, 'Beta', -1089, TRUE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            # Cobros de este mes en dos monedas y dos comunidades.
            "(1, 88, 1500, 'EUR', 'paid', 'Mensual', date_trunc('month', NOW()) + INTERVAL '1 hour'), "
            "(2, 88, 2000, 'USD', 'paid', 'Mensual', date_trunc('month', NOW()) + INTERVAL '2 hours'), "
            "(3, 89, 9000, 'EUR', 'completed', 'Anual', date_trunc('month', NOW()) + INTERVAL '3 hours'), "
            # Mes anterior completo, para la comparativa.
            "(4, 88, 1000, 'EUR', 'paid', 'Mensual', date_trunc('month', NOW()) - INTERVAL '10 days'), "
            # Una devolución y un fallo: FUERA de los ingresos.
            "(5, 88, 5000, 'EUR', 'refunded', 'Mensual', NOW()), "
            "(6, 88, 5000, 'EUR', 'failed', 'Mensual', NOW())"
        )
        cur.execute(
            "INSERT INTO payment_transactions (provider, status, payment_scope, "
            "purchase_type, user_id, group_id, amount, currency) VALUES "
            "('stripe', 'paid', 'platform', 'group_access', 1, 88, 1500, 'EUR'), "
            "('paypal', 'paid', 'platform', 'group_access', 3, 89, 9000, 'EUR'), "
            "('paypal', 'pending', 'platform', 'group_access', 7, 89, 1500, 'EUR')"
        )

    return db


def test_refunds_and_failures_are_not_income(plataforma):
    ventanas = prs.fetch_platform_windows()

    historico = {c: t for c, t, _ in ventanas["historico"]}

    assert historico["EUR"] == 1500 + 9000 + 1000, (
        "refunded y failed no pueden sumar como ingresos"
    )


def test_currencies_never_mix(plataforma):
    ventanas = prs.fetch_platform_windows()

    monedas = {c for c, _, _ in ventanas["mes_actual"]}

    assert monedas == {"EUR", "USD"}, (
        "la pantalla vieja sumaba EUR+USD bajo MAX(currency)"
    )


def test_the_screen_shows_money_not_cents(plataforma):
    texto = prs.build_platform_revenue_text()

    assert "15.00 EUR" in texto or "105.00 EUR" in texto
    assert "1500 EUR" not in texto, (
        "céntimos mostrados como unidades: la mentira nº 3 de la pantalla vieja"
    )


def test_the_global_photo_has_comparison_providers_and_top(plataforma):
    texto = prs.build_platform_revenue_text()

    assert "vs mes anterior" in texto, "la comparativa con el mes anterior"
    assert "Por proveedor (30 días)" in texto
    assert "stripe" in texto and "paypal" in texto
    assert "Comunidades que más facturan" in texto
    assert "Beta" in texto, "la comunidad que más factura tiene que salir"
    assert "Con renovación automática" in texto


def test_pending_transactions_do_not_count_as_provider_income(plataforma):
    filas = prs.fetch_provider_split_30d()

    paypal = [(t, n) for p, c, t, n in filas if p == "paypal"]

    assert paypal == [(9000, 1)], (
        "una transacción pending no es dinero cobrado"
    )


def test_the_scoped_view_follows_the_same_money_rules(plataforma):
    texto = prs.build_scoped_income_text([88])

    # Histórico de Alfa: 15.00 de este mes + 10.00 del anterior.
    assert "Alfa: 25.00 EUR (2 pagos)" in texto
    assert "20.00 USD" in texto
    assert "Beta" not in texto, "un admin acotado no ve las comunidades ajenas"
    assert "50.00 EUR" not in texto and "refunded" not in texto


def test_the_router_delegates_instead_of_lying():
    source = open("callback_router.py", encoding="utf-8").read()

    pos = source.index('if data == "admin_income":')
    trozo = source[pos:pos + 1600]

    assert "build_platform_revenue_text" in trozo
    assert "build_scoped_income_text" in trozo
    assert "MAX(p.currency)" not in trozo, "la mezcla de monedas tiene que estar muerta"
