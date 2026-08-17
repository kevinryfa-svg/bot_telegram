"""
Referidos: el socio contento trae a otro y los dos ganan días.

Las cuatro reglas que impiden que esto sea un agujero: solo gente NUEVA
(ni autorreferidos ni quien ya está dentro), PAGA luego cobra (un clic no
es una venta), UNA atribución por persona y comunidad (la primera manda),
y días DE VERDAD (contados desde hoy y con el cobro de Stripe empujado,
porque si no la semana regalada no sería gratis).
"""

import asyncio
from datetime import datetime, timedelta

import pytest

import referral_service as rs


@pytest.fixture
def comunidad(clean_db):
    """Grupo 91 con un socio dentro (9101) y un desconocido fuera (9199)."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (91, 'VIP Referidos', -1091, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (9101, 91, NOW() + INTERVAL '10 days', TRUE)"
        )

    return db


def test_the_link_carries_the_member_and_the_community(comunidad):
    enlace = rs.build_referral_link(9101, 91)

    assert enlace.endswith("?start=ref_91_9101")
    assert rs.parse_referral_payload("ref_91_9101") == (91, 9101)

    # Cargas rotas: ninguna puede reventar el /start de nadie.
    assert rs.parse_referral_payload("ref_91") is None
    assert rs.parse_referral_payload("ref_a_b") is None
    assert rs.parse_referral_payload("pagado_91") is None


def test_only_new_people_count(comunidad):
    # Autorreferido: no.
    assert rs.record_referral_click(9101, 9101, 91) is False

    # Invitar a alguien que ya está dentro: no trae a nadie nuevo.
    assert rs.record_referral_click(9101, 9101, 91) is False

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (9102, 91, NOW() + INTERVAL '5 days', TRUE)"
        )

    assert rs.record_referral_click(9101, 9102, 91) is False, (
        "quien ya tiene acceso no es un alta que nadie haya traído"
    )

    # Quien recomienda tiene que ser de la casa.
    assert rs.record_referral_click(9500, 9199, 91) is False, (
        "un enlace de alguien que no está dentro solo busca días gratis"
    )

    # Y el caso bueno sí.
    assert rs.record_referral_click(9101, 9199, 91) is True


def test_the_first_link_wins_forever(comunidad):
    assert rs.record_referral_click(9101, 9199, 91) is True

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (9103, 91, NOW() + INTERVAL '30 days', TRUE)"
        )

    assert rs.record_referral_click(9103, 9199, 91) is False, (
        "la atribución es del primer enlace: sin peleas por el último clic"
    )

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "SELECT referrer_user_id FROM referrals WHERE invited_user_id=9199"
        )
        assert cur.fetchone()[0] == 9101


def test_a_click_is_not_a_sale_but_a_payment_pays_both(comunidad, monkeypatch):
    rs.record_referral_click(9101, 9199, 91)

    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=9101")
        antes_referidor = cur.fetchone()[0]

    # Todavía nadie ha pagado: ni un día para nadie.
    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=9101")
        assert cur.fetchone()[0] == antes_referidor

    # El invitado paga: aparece su fila de acceso y se convierte el referido.
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (9199, 91, NOW() + INTERVAL '30 days', TRUE)"
        )

    resultado = rs.convert_referral(9199, 91)

    assert resultado["referrer_user_id"] == 9101
    assert resultado["days"] == rs.REFERRAL_DAYS

    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=9101")
        despues_referidor = cur.fetchone()[0]

    ganados = (despues_referidor - antes_referidor).days
    assert ganados == rs.REFERRAL_DAYS, (
        "el referidor cobra sus días sobre su fecha actual"
    )

    # El reintento del webhook del mismo pago no regala nada más.
    assert rs.convert_referral(9199, 91) is None

    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT expiration FROM users WHERE user_id=9101")
        assert cur.fetchone()[0] == despues_referidor


def test_expired_members_count_days_from_today_not_from_the_past(comunidad):
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET expiration = NOW() - INTERVAL '100 days' "
            "WHERE user_id=9101"
        )

    nueva = rs.credit_referral_days(9101, 91, days=7)

    assert nueva > datetime.now() + timedelta(days=6), (
        "sumar días a una fecha ya pasada sería regalar nada"
    )


def test_stripe_subscribers_get_their_charge_pushed(comunidad, monkeypatch):
    """Sin empujar el cobro, la semana regalada no sería gratis."""

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET stripe_subscription_id='sub_ref_1' "
            "WHERE user_id=9101"
        )

    llamadas = []

    monkeypatch.setattr(
        rs.stripe.Subscription, "modify",
        lambda sub_id, **kwargs: llamadas.append((sub_id, kwargs))
    )

    nueva = rs.credit_referral_days(9101, 91, days=7)

    assert len(llamadas) == 1
    sub_id, kwargs = llamadas[0]

    assert sub_id == "sub_ref_1"
    assert kwargs["trial_end"] == int(nueva.timestamp()), (
        "el próximo cobro se mueve a la nueva fecha de acceso"
    )
    assert kwargs["proration_behavior"] == "none"
    assert "items" not in kwargs and "price" not in kwargs, (
        "el precio heredado del socio es intocable"
    )


def test_a_stripe_failure_does_not_swallow_the_gift(comunidad, monkeypatch):
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET stripe_subscription_id='sub_ref_2' "
            "WHERE user_id=9101"
        )

    def explota(sub_id, **kwargs):
        raise RuntimeError("Stripe down")

    monkeypatch.setattr(rs.stripe.Subscription, "modify", explota)

    nueva = rs.credit_referral_days(9101, 91, days=7)

    assert nueva is not None, (
        "los días locales ya están dados: un fallo de Stripe no los borra"
    )


def test_the_member_screen_shows_link_and_score(comunidad):
    rs.record_referral_click(9101, 9199, 91)

    estadisticas = rs.fetch_referral_stats(9101, 91)
    assert estadisticas == {"invitados": 1, "convertidos": 0, "dias": 0}

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (9199, 91, NOW() + INTERVAL '30 days', TRUE)"
        )

    rs.convert_referral(9199, 91)

    estadisticas = rs.fetch_referral_stats(9101, 91)
    assert estadisticas["convertidos"] == 1
    assert estadisticas["dias"] == rs.REFERRAL_DAYS


def test_the_payment_path_converts_and_the_screen_has_the_button():
    """Los dos extremos del circuito: el gancho del pago y el botón."""

    pago = open("payment_access_service.py", encoding="utf-8").read()

    assert "convert_referral" in pago, (
        "sin el gancho en el pago, el referido nunca cobra"
    )
    assert "notify_referral_conversion" in pago

    pantalla = open("mysub_callbacks.py", encoding="utf-8").read()

    assert 'callback_data=f"mysub_invite_{telegram_group_id}"' in pantalla
    assert pantalla.index('data.startswith("mysub_invite_")') < pantalla.index(
        'data.startswith("mysub_pause_")'
    ), "las ramas específicas van antes que la genérica mysub_"

    arranque = open("start_handler.py", encoding="utf-8").read()

    assert 'carga.startswith("ref_")' in arranque
    assert "record_referral_click" in arranque


def test_the_kill_switch(comunidad, monkeypatch):
    monkeypatch.setattr(rs, "REFERRALS_ENABLED", False)

    assert rs.record_referral_click(9101, 9199, 91) is False
    assert rs.convert_referral(9199, 91) is None
