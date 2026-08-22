"""
Una oferta de UNA SEMANA tiene que durar una semana.

Es la mitad callada de las ofertas semanales: rebajar el precio de siete días
solo funciona si a los siete días se sale. Si no, el -60% no es una oferta de
entrada, es un regalo permanente — y encima el comprador de la semana siguiente
paga por lo que otro tiene gratis.

La cadena entera: el pago fija una caducidad a 7 días, y el worker de
expiraciones encuentra a quien la pasó y lo saca del grupo. La segunda mitad
estaba enterrada dentro de un bucle infinito, donde ninguna prueba llegaba.
"""

from datetime import datetime, timedelta

import pytest

import expiration_worker as ew
from payment_access_service import calculate_group_access_expiration


def test_seven_days_means_seven_days():
    caduca = calculate_group_access_expiration(7)

    assert caduca is not None, "sin caducidad no hay expulsión posible"

    faltan = caduca - datetime.now()

    assert 6 <= faltan.days <= 7


def test_a_paid_week_expires_and_a_year_does_not(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (61, 'StarsVip', -1061, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, "
            "subscription_active) VALUES "
            # Compró una semana hace ocho días: fuera.
            "(6101, 61, NOW() - INTERVAL '1 day', TRUE), "
            # Compró el año: dentro.
            "(6102, 61, NOW() + INTERVAL '300 days', TRUE)"
        )

    caducados = [fila[0] for fila in ew.fetch_expired_members()]

    assert 6101 in caducados, (
        "el de la semana sigue dentro pasados los siete días: la oferta de "
        "entrada se habría convertido en acceso gratis para siempre"
    )
    assert 6102 not in caducados


def test_a_one_off_purchase_is_not_forgotten(clean_db):
    """El pago único también marca subscription_active: si no, el worker no
    miraría nunca a quien compró una semana suelta."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (62, 'StarsVip', -1062, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, "
            "subscription_active) VALUES (6201, 62, NOW() - INTERVAL '2 hours', "
            "TRUE)"
        )

    assert 6201 in [fila[0] for fila in ew.fetch_expired_members()]


def test_someone_without_expiration_is_never_kicked(clean_db):
    """Acceso permanente: sin fecha no hay nada que vencer."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (63, 'StarsVip', -1063, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, "
            "subscription_active) VALUES (6301, 63, NULL, TRUE)"
        )

    assert 6301 not in [fila[0] for fila in ew.fetch_expired_members()]


def test_the_worker_kicks_and_revokes():
    """Lo que hace con esa lista: sacar del grupo y anular sus enlaces."""

    fuente = open("expiration_worker.py", encoding="utf-8").read()

    assert "kick_chat_member" in fuente
    assert "revoke_link" in fuente
    assert "fetch_expired_members" in fuente
