"""
La oferta de salvamento: el último intento antes de perder a un suscriptor.

Las dos reglas que la mantienen honesta, fijadas como pruebas:

  1. UNA VEZ por persona y acceso, registrada AL MOSTRARSE: un descuento que
     aparece cada vez que amagas con cancelar enseña a cancelar para
     conseguir rebajas.
  2. El cupón es DE UN CICLO y se aplica solo a la suscripción de quien lo
     aceptó — nada de descuentos eternos ni códigos tecleables.
"""

import pytest

import retention_offer_service as ros


@pytest.fixture
def suscriptor(clean_db, monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (84, 'VIP Salva', -1084, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) "
            "VALUES (8401, 84, NOW() + INTERVAL '20 days', TRUE, 'sub_84')"
        )

    llamadas = {"coupons": [], "modificaciones": []}

    monkeypatch.setattr(
        ros.stripe.Coupon, "create",
        lambda **k: llamadas["coupons"].append(k) or {"id": "cup_save"}
    )
    monkeypatch.setattr(
        ros.stripe.Subscription, "modify",
        lambda sid, **k: llamadas["modificaciones"].append((sid, k)) or {"id": sid}
    )

    return {"db": db, "llamadas": llamadas}


def test_the_offer_shows_exactly_once(suscriptor):
    assert ros.offer_already_made(8401, 84) is False

    assert ros.record_offer_shown(8401, 84, "sub_84") is True, "la primera vez se enseña"
    assert ros.record_offer_shown(8401, 84, "sub_84") is False, (
        "quien la vio y canceló igualmente no la vuelve a ver: si reapareciera, "
        "cancelar se convertiría en el truco para conseguir descuentos"
    )

    assert ros.offer_already_made(8401, 84) is True


def test_accepting_applies_a_one_cycle_coupon_to_their_subscription(suscriptor):
    ros.record_offer_shown(8401, 84, "sub_84")

    assert ros.apply_save_discount(8401, 84) is True

    cupon = suscriptor["llamadas"]["coupons"][0]

    assert cupon["percent_off"] == 30
    assert cupon["duration"] == "once", (
        "el descuento es del PRÓXIMO cobro: nada de rebajas eternas en un click"
    )
    assert "applies_to" not in cupon, (
        "sin perímetro a propósito: lo aplicamos nosotros, nadie lo teclea"
    )

    sid, cambios = suscriptor["llamadas"]["modificaciones"][0]

    assert sid == "sub_84"
    assert cambios == {"discounts": [{"coupon": "cup_save"}]}

    with suscriptor["db"].conn.cursor() as cur:
        cur.execute("SELECT accepted FROM retention_offers WHERE user_id=8401")
        assert cur.fetchone()[0] is True


def test_without_a_subscription_there_is_nothing_to_save(suscriptor):
    with suscriptor["db"].conn.cursor() as cur:
        cur.execute("UPDATE users SET stripe_subscription_id=NULL WHERE user_id=8401")

    assert ros.apply_save_discount(8401, 84) is False
    assert not suscriptor["llamadas"]["coupons"]


def test_a_stripe_failure_leaves_the_renewal_untouched(suscriptor, monkeypatch):
    def roto(**k):
        raise RuntimeError("stripe caído")

    monkeypatch.setattr(ros.stripe.Coupon, "create", roto)

    ros.record_offer_shown(8401, 84, "sub_84")

    assert ros.apply_save_discount(8401, 84) is False

    with suscriptor["db"].conn.cursor() as cur:
        cur.execute("SELECT accepted FROM retention_offers WHERE user_id=8401")
        assert cur.fetchone()[0] is False, "sin descuento aplicado no hay aceptación"


def test_the_percent_is_tunable(suscriptor, monkeypatch):
    monkeypatch.setattr(ros, "RETENTION_DISCOUNT_PERCENT", 50)

    ros.apply_save_discount(8401, 84)

    assert suscriptor["llamadas"]["coupons"][0]["percent_off"] == 50


def test_when_in_doubt_the_offer_is_not_repeated(suscriptor, monkeypatch):
    """Si la base falla al comprobar, mejor no ofertar dos veces que de más."""

    class ConnRota:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr(ros, "conn", ConnRota())

    assert ros.offer_already_made(8401, 84) is True


# =========================
# EL CABLEADO EN LA PANTALLA
# =========================

def test_the_flow_dodges_its_own_prefix_traps():
    source = open("mysub_callbacks.py", encoding="utf-8").read()

    # saveoffer_yes y stoprenew_go ANTES que stoprenew_yes y stoprenew_:
    # "mysub_stoprenew_go_" empieza por "mysub_stoprenew_".
    pos_save = source.index('data.startswith("mysub_saveoffer_yes_")')
    pos_go = source.index('data.startswith("mysub_stoprenew_go_")')
    pos_yes = source.index('data.startswith("mysub_stoprenew_yes_")')
    pos_base = source.index('data.startswith("mysub_stoprenew_"):')

    assert pos_save < pos_go < pos_yes
    assert pos_go < pos_base, (
        "mysub_stoprenew_go_ caería en la rama genérica mysub_stoprenew_"
    )


def test_the_offer_gates_are_in_the_screen():
    source = open("mysub_callbacks.py", encoding="utf-8").read()

    pos = source.index("record_offer_shown(user_id, grupo_oferta[0], sub_id)")
    contexto = source[max(0, pos - 1600):pos]

    assert "RETENTION_OFFER_ENABLED" in contexto
    assert "stripe_subscription_id IS NOT NULL" in contexto, (
        "sin suscripción de Stripe no hay nada que salvar: PayPal sigue igual"
    )


# =========================
# LA TERCERA VÍA: PAUSAR
# =========================
# Entre pagar y cancelar hay una pausa de un mes con vuelta automática: el
# que se va por saturación o dinero corto no se pierde.

def test_pausing_voids_a_month_and_resumes_alone(suscriptor, monkeypatch):
    import group_subscription_service as gss

    llamadas = []
    monkeypatch.setattr(gss.stripe.Subscription, "modify",
                        lambda sid, **k: llamadas.append((sid, k)) or {"id": sid})

    assert gss.pause_renewal(8401, 84) is True

    sid, cambios = llamadas[0]
    assert sid == "sub_84"
    assert cambios["pause_collection"]["behavior"] == "void", (
        "void: la factura de la pausa se ANULA, no se acumula como deuda"
    )

    import time as time_mod
    reanuda = cambios["pause_collection"]["resumes_at"]
    assert 0 < reanuda - int(time_mod.time()) <= 30 * 86400 + 60, (
        "la vuelta es automática: pausa sin fecha de vuelta es cancelación"
    )


def test_resuming_clears_the_pause(suscriptor, monkeypatch):
    import group_subscription_service as gss

    llamadas = []
    monkeypatch.setattr(gss.stripe.Subscription, "modify",
                        lambda sid, **k: llamadas.append((sid, k)) or {"id": sid})

    assert gss.resume_renewal(8401, 84) is True
    assert llamadas[0] == ("sub_84", {"pause_collection": ""}), (
        "la cadena vacía es como Stripe borra la pausa"
    )


def test_a_paused_subscriber_gets_no_charge_notice(suscriptor, monkeypatch):
    """El aviso pre-cobro a un pausado sería mentira: su factura se anula."""

    import renewal_service as rs

    monkeypatch.setattr(
        "group_subscription_service.fetch_renewal_state",
        lambda u, g: {"cancel_at_period_end": False, "paused": True}
    )

    assert rs.renewal_is_really_active(8401, 84) is False


def test_the_pause_lives_in_both_cancel_screens_and_dodges_traps():
    source = open("mysub_callbacks.py", encoding="utf-8").read()

    assert source.count('t("mysub.pause_btn", language)') >= 3, (
        "la pausa tiene que ofrecerse en la oferta de salvamento Y en las "
        "dos confirmaciones de cancelación"
    )

    # mysub_pause_ y mysub_resume_ antes que la rama genérica mysub_.
    assert source.index('data.startswith("mysub_pause_")') < \
        source.index('if data.startswith("mysub_"):')
    assert source.index('data.startswith("mysub_resume_")') < \
        source.index('if data.startswith("mysub_"):')

    # Y la pantalla enseña el estado en pausa con su botón de reanudar.
    assert 'renovacion.get("paused")' in source
    assert "mysub_resume_" in source
