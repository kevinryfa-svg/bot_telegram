"""
Publicar una comunidad, pagando: la puerta de entrada de un propietario.

Estaba roto en tres sitios seguidos y ninguno daba error:

  1. Los cuatro planes comerciales se siembran con amount NULL, así que la
     pantalla los enseñaba como «pendiente de precio».
  2. No había ninguna pantalla para ponerles precio.
  3. Y al pulsar uno, el bot contestaba «El pago automático comercial todavía
     está pendiente de conectar».

Con eso, la plataforma no podía cobrarle a un propietario ni queriendo: hacía
falta que una persona contestara una solicitud, acordara un importe por fuera y
activara el cupo a mano.

Lo que se vigila aquí es la cadena entera: precio → cobro → permiso. Y las dos
cosas que se pagan con dinero real: la unidad del importe (céntimos vs euros) y
que un plan sin precio no llegue nunca a un botón de pago.
"""

import pytest

import platform_plan_service as pps


@pytest.fixture
def planes(clean_db, monkeypatch):
    """Los cuatro planes sembrados como en producción: sin precio."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM commercial_plans WHERE product_type='shared_bot_space'")
        cur.execute(
            "INSERT INTO commercial_plans "
            "(id, product_type, name, duration_days, amount, stripe_price_id) "
            "VALUES "
            "(9001, 'shared_bot_space', '1 mes', 30, NULL, NULL), "
            "(9002, 'shared_bot_space', '1 año', 365, NULL, NULL)"
        )

    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append({
            "name": name,
            "amount_major": amount_major,
            "currency": currency,
            "metadata": metadata or {},
            "recurring_interval_days": recurring_interval_days,
        })
        return (f"prod_{len(creados)}", f"price_{len(creados)}")

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    return {"db": db, "creados": creados}


def test_nothing_is_for_sale_until_someone_sets_a_price(planes):
    """Así estaba producción: cuatro planes y ninguno cobrable."""

    assert pps.fetch_purchasable_platform_plans() == []
    assert pps.platform_plan_is_purchasable() is False

    linea = pps.describe_platform_plan_for_startup()

    assert "SIN PRECIO" in linea
    assert "solicitud" in linea, (
        "hay que decir qué pasa mientras tanto, no solo que falta un precio"
    )


def test_setting_a_price_puts_it_on_sale(planes):
    assert pps.set_platform_plan_amount(9001, 2900) is True

    planes_venta = pps.fetch_purchasable_platform_plans()

    assert len(planes_venta) == 1
    assert pps.format_plan_amount(planes_venta[0]) == "29,00 EUR"
    assert pps.describe_plan_period(planes_venta[0]) == "al mes"

    assert "29,00 EUR" in pps.describe_platform_plan_for_startup()


def test_the_amount_is_read_as_cents_not_euros(planes):
    """La trampa: commercial_plans.amount va en CÉNTIMOS.

    Y en el mismo producto, plans.amount va en unidades MAYORES. Las dos
    convenciones conviven, así que cada lado tiene que saber en cuál está.
    """

    pps.set_platform_plan_amount(9001, 2900)

    plan = pps.fetch_platform_plan(9001)

    assert plan["amount"] == 2900
    assert pps.format_plan_amount(plan) == "29,00 EUR", (
        "2900 céntimos son 29 euros, no 2.900"
    )

    pps.ensure_platform_plan_stripe_price(plan)

    creado = planes["creados"][0]

    assert creado["amount_major"] == pytest.approx(29.00), (
        f"se pidió a Stripe un precio de {creado['amount_major']}"
    )


def test_the_stripe_price_matches_the_plan_period(planes):
    pps.set_platform_plan_amount(9002, 19900)

    plan = pps.fetch_platform_plan(9002)
    pps.ensure_platform_plan_stripe_price(plan)

    creado = planes["creados"][0]

    assert creado["recurring_interval_days"] == 365, (
        "el plan de 1 año no puede cobrarse cada mes"
    )
    assert creado["metadata"]["purpose"] == "platform_plan"


def test_the_price_is_created_once_and_stored(planes):
    pps.set_platform_plan_amount(9001, 2900)

    plan = pps.fetch_platform_plan(9001)
    primero = pps.ensure_platform_plan_stripe_price(plan)

    recargado = pps.fetch_platform_plan(9001)

    assert recargado["stripe_price_id"] == primero

    pps.ensure_platform_plan_stripe_price(recargado)

    assert len(planes["creados"]) == 1, (
        "un precio nuevo por compra llenaría Stripe de precios duplicados"
    )


def test_changing_the_price_drops_the_old_stripe_price(planes):
    """Si no, se seguiría cobrando el precio viejo con el número nuevo delante."""

    pps.set_platform_plan_amount(9001, 2900)
    plan = pps.fetch_platform_plan(9001)
    pps.ensure_platform_plan_stripe_price(plan)

    assert pps.fetch_platform_plan(9001)["stripe_price_id"] == "price_1"

    pps.set_platform_plan_amount(9001, 3900)

    assert pps.fetch_platform_plan(9001)["stripe_price_id"] is None, (
        "el precio de Stripe del importe anterior no puede sobrevivir al cambio"
    )

    pps.ensure_platform_plan_stripe_price(pps.fetch_platform_plan(9001))

    assert planes["creados"][1]["amount_major"] == pytest.approx(39.00)


def test_a_plan_without_a_price_never_reaches_a_payment(planes):
    plan_sin_precio = {"id": 9001, "name": "1 mes", "duration_days": 30,
                       "amount": None, "currency": "EUR",
                       "stripe_price_id": None}

    assert pps.ensure_platform_plan_stripe_price(plan_sin_precio) is None

    with pytest.raises(ValueError):
        pps.create_platform_plan_checkout(700, plan_sin_precio)


def test_a_forged_callback_cannot_buy_a_disabled_plan(planes):
    """Un callback se reenvía: el plan se relee de la base, no del botón."""

    pps.set_platform_plan_amount(9001, 2900)

    with planes["db"].conn.cursor() as cur:
        cur.execute("UPDATE commercial_plans SET is_active=FALSE WHERE id=9001")

    assert pps.fetch_platform_plan(9001) is None


def test_paying_turns_into_permission(planes):
    """El único sitio donde esto vale algo: el pago da el cupo."""

    from group_registration_handler import can_creator_add_group
    from rbac_helpers import get_creator_group_quota

    assert get_creator_group_quota(7700) == 0 or not can_creator_add_group(7700)

    assert pps.activate_platform_plan(7700, stripe_subscription_id="sub_1") is True

    assert get_creator_group_quota(7700) >= 1
    assert can_creator_add_group(7700) is True, (
        "pagar y no poder publicar es cobrar sin entregar"
    )


def test_the_same_webhook_twice_does_not_double_the_quota(planes):
    from rbac_helpers import get_creator_group_quota

    pps.activate_platform_plan(7700, stripe_subscription_id="sub_1")
    primera = get_creator_group_quota(7700)

    pps.activate_platform_plan(7700, stripe_subscription_id="sub_1")

    assert get_creator_group_quota(7700) == primera, (
        "los webhooks se reintentan: el cupo no puede ir subiendo con cada uno"
    )


def test_stopping_the_payment_stops_new_communities_but_not_the_old_ones(planes):
    """Lo publicado y los accesos vendidos NO se tocan.

    Los pagaron sus compradores: apagarlos por una factura del propietario sería
    quitarle a un tercero algo que pagó.
    """

    from group_registration_handler import can_creator_add_group

    with planes["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (77, 'La suya', -1077, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7799, 77, NOW() + INTERVAL '30 days', TRUE)"
        )

    pps.activate_platform_plan(7700, stripe_subscription_id="sub_1")

    assert pps.deactivate_platform_plan(7700, reason="canceled") is True

    assert can_creator_add_group(7700) is False, "no puede publicar más"

    with planes["db"].conn.cursor() as cur:
        cur.execute("SELECT is_active FROM groups WHERE id=77")
        assert cur.fetchone()[0] is True, "su comunidad sigue viva"

        cur.execute(
            "SELECT subscription_active FROM users WHERE user_id=7799"
        )
        assert cur.fetchone()[0] is True, (
            "el acceso de quien le compró no se toca: lo pagó"
        )


def test_the_webhook_route_exists_and_activates(planes, monkeypatch):
    """La rama que faltaba: el pago llegaba y nadie lo convertía en permiso."""

    import stripe_handler as sh

    from rbac_helpers import get_creator_group_quota

    pps.set_platform_plan_amount(9001, 2900)

    monkeypatch.setattr(
        sh.stripe.Subscription, "retrieve",
        lambda sub_id: {"status": "trialing",
                        "current_period_end": 1800000000}
    )
    monkeypatch.setattr(sh, "send_telegram_message",
                        lambda *a, **k: True)

    hecho = sh.process_platform_plan_checkout_completed({
        "id": "cs_plan_1",
        "customer": "cus_1",
        "subscription": "sub_plan_1",
        "metadata": {
            "purpose": "platform_plan",
            "user_id": "7700",
            "commercial_plan_id": "9001",
        },
    })

    assert hecho is True
    assert get_creator_group_quota(7700) >= 1, (
        "durante la prueba tiene que poder publicar: si no, la prueba no prueba "
        "nada"
    )


def test_a_checkout_without_a_user_is_logged_not_swallowed(planes):
    import stripe_handler as sh

    assert sh.process_platform_plan_checkout_completed({
        "id": "cs_plan_2",
        "metadata": {"purpose": "platform_plan"},
    }) is False


def test_the_dead_end_message_is_gone():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "pago automático comercial todavía está pendiente de conectar" not in fuente
    assert "un administrador debe añadir el price_id" not in fuente.lower()

    # Y el super admin tiene dónde poner el precio.
    assert 'callback_data="admin_platform_plan_prices"' in fuente
    assert 'if data == "admin_platform_plan_prices":' in fuente

    entrada = open("admin_input_handler.py", encoding="utf-8").read()

    assert "setting_platform_plan_price_id" in entrada
    assert "EN EUROS" in entrada, (
        "pedir céntimos aquí publicaría un precio cien veces más bajo"
    )
