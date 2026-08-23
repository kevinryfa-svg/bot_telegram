"""
El pulso diario: el negocio entero en seis líneas.

El aviso de cada pago ya existía y el resumen semanal por comunidad también.
Faltaba lo de en medio: saber cada mañana si esto vende, sin entrar a mirar. Un
negocio del que solo te enteras cuando ha pasado un mes se descubre tarde.
"""

import pytest

import daily_pulse_service as dps


@pytest.fixture
def con_ventas(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (81, 'StarsVip', -1081, TRUE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, "
            "status, plan, payment_date) VALUES "
            # Ayer: dos pagos de 3,60 (en CÉNTIMOS).
            "(8101, 81, 360, 'EUR', 'paid', 'Semana', "
            " CURRENT_DATE - INTERVAL '6 hours'), "
            "(8102, 81, 360, 'EUR', 'paid', 'Semana', "
            " CURRENT_DATE - INTERVAL '10 hours'), "
            # Hace tres días: uno de 29.
            "(8103, 81, 2900, 'EUR', 'paid', 'Año', NOW() - INTERVAL '3 days'), "
            # Y uno que no se cobró: no cuenta.
            "(8104, 81, 900, 'EUR', 'failed', 'Mes', NOW() - INTERVAL '1 day')"
        )

    return db


def test_the_money_is_read_in_euros_not_cents(con_ventas):
    """payments.amount va en CÉNTIMOS, al revés que plans.amount."""

    dinero = dps.dinero_reciente()

    assert dinero["ayer"] == (7.2, 2), "dos de 3,60 son 7,20 euros"
    assert dinero["semana"][0] == pytest.approx(36.2)
    assert dinero["semana"][1] == 3, "el fallido no cuenta"


def test_the_pulse_says_the_money_first(con_ventas):
    texto = dps.build_daily_pulse_text()

    assert "7,20 EUR" in texto
    assert "2 pagos" in texto
    assert "36,20 EUR" in texto


def test_a_week_without_sales_says_what_to_do(clean_db):
    texto = dps.build_daily_pulse_text()

    assert "Siete días sin una venta" in texto
    assert "Traer compradores" in texto


def test_a_broken_checkout_is_the_headline(con_ventas, monkeypatch):
    import sale_readiness_service as srs

    monkeypatch.setattr(srs, "_ultimo_estado_del_cobro", {"roto": True})

    assert "Cobro: ROTO" in dps.build_daily_pulse_text()


def test_it_never_explodes(monkeypatch):
    """Es un aviso, no una operación: un fallo no puede tumbar el job."""

    monkeypatch.setattr(dps, "dinero_reciente", lambda: {
        "ayer": (0.0, 0), "semana": (0.0, 0)
    })

    assert "Pulso del bot" in dps.build_daily_pulse_text()


def test_it_is_scheduled_daily():
    fuente = open("main.py", encoding="utf-8").read()

    assert "schedule_daily_pulse" in fuente
    assert "enviar_pulso_diario" in fuente
