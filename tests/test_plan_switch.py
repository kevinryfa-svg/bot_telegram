"""
Cambiar de plan: el único caso en que un socio con acceso paga otra vez.

El bloqueo de "ya tienes acceso" existe para evitar el doble cobro
ACCIDENTAL, y hace bien. Pero convertía en callejón el caso legítimo: al
suscriptor mensual se le ofrecía el plan anual y al pulsar aterrizaba en
«ya tienes acceso a esta comunidad».

Lo que hace seguro el cambio no es un permiso nuevo: es la salvaguarda que
ya existe en attach_subscription_to_member, que apaga la suscripción
anterior al anclar la nueva. Las tres reglas que se prueban aquí: misma
comunidad, Stripe o nada (en PayPal quedarían dos cobrando), y validación
CONTRA LA BASE DE DATOS — un callback se escribe a mano, la consulta no.
"""

import asyncio

import pytest

import plan_switch_service as pss


@pytest.fixture
def socio(clean_db):
    """Suscriptor mensual de la comunidad 78, que también tiene plan anual."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) VALUES "
            "(78, 'VIP Cambio', -1078, TRUE), (79, 'Otra', -1079, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, payment_provider, is_active) VALUES "
            "(78, 'Mensual', 'price_m78', 'price_m78', 30, 15, 'EUR', 'stripe', TRUE), "
            "(78, 'Anual', 'price_a78', 'price_a78', 365, 120, 'EUR', 'stripe', TRUE), "
            "(78, 'Viejo', 'price_v78', 'price_v78', 30, 10, 'EUR', 'stripe', FALSE), "
            "(79, 'Ajeno', 'price_x79', 'price_x79', 30, 15, 'EUR', 'stripe', TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (7801, 78, NOW() + INTERVAL '12 days', TRUE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (7801, 78, 1500, 'EUR', 'paid', 'Mensual')"
        )

    return db


def test_only_the_other_active_plans_of_the_same_community(socio):
    opciones = pss.fetch_switch_options(7801, 78)

    nombres = [o[1] for o in opciones]

    assert nombres == ["Anual"], (
        "ni el plan que ya tiene, ni uno inactivo, ni el de otra comunidad"
    )


def test_the_switch_is_allowed_for_a_member_with_active_access(socio):
    assert pss.switch_is_allowed(7801, 78) == (True, None)

    # Y con un plan destino concreto, si es de esa comunidad.
    plan_anual = pss.fetch_switch_options(7801, 78)[0][0]
    assert pss.switch_is_allowed(7801, 78, plan_id=plan_anual) == (True, None)


def test_a_plan_from_another_community_is_never_a_switch(socio):
    with socio.conn.cursor() as cur:
        cur.execute("SELECT id FROM plans WHERE group_id=79")
        ajeno = cur.fetchone()[0]

    assert pss.switch_is_allowed(7801, 78, plan_id=ajeno) == (False, "bad_plan"), (
        "un callback se escribe a mano; la consulta es la que manda"
    )

    with socio.conn.cursor() as cur:
        cur.execute("SELECT id FROM plans WHERE name='Viejo'")
        inactivo = cur.fetchone()[0]

    assert pss.switch_is_allowed(7801, 78, plan_id=inactivo) == (False, "bad_plan")


def test_a_stranger_cannot_switch(socio):
    assert pss.switch_is_allowed(999999, 78) == (False, "no_access")


def test_an_expired_member_buys_normally_instead(socio):
    with socio.conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET expiration = NOW() - INTERVAL '2 days' "
            "WHERE user_id=7801"
        )

    assert pss.switch_is_allowed(7801, 78) == (False, "no_access")


def test_paypal_members_are_told_the_order_instead_of_being_charged_twice(socio):
    with socio.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_transactions "
            "(provider, status, user_id, group_id, external_checkout_id) "
            "VALUES ('paypal', 'completed', 7801, 78, 'I-PAYPAL78')"
        )

    permitido, motivo = pss.switch_is_allowed(7801, 78)

    assert (permitido, motivo) == (False, "paypal"), (
        "la salvaguarda que apaga la anterior es de Stripe: en PayPal "
        "quedarían dos suscripciones cobrando"
    )

    from i18n_service import t

    texto = t("mysub.switch_paypal", "es", group="VIP Cambio")
    assert "primero apaga la renovación" in texto
    assert "después elige el plan nuevo" in texto


def test_the_screen_says_what_happens_before_anyone_taps(socio):
    opciones = pss.fetch_switch_options(7801, 78)

    texto = pss.build_switch_text("VIP Cambio", opciones, current_plan="Mensual")

    assert "🔀 Cambiar de plan en VIP Cambio" in texto
    assert "Tu plan ahora: Mensual" in texto
    assert "se apaga sola" in texto
    assert "no se te cobra dos veces" in texto
    assert "• Anual — 120 EUR / 1 año" in texto


def test_the_guard_only_yields_to_a_declared_switch():
    """El bloqueo sigue en pie para una recompra normal."""

    router = open("callback_router.py", encoding="utf-8").read()

    pos = router.index("async def create_checkout_for_user")
    trozo = router[pos:pos + 1200]

    assert "if not plan_switch and should_block_new_group_purchase" in trozo, (
        "sin plan_switch, el bloqueo de doble cobro sigue intacto"
    )
    assert '"plan_switch": bool(plan_switch)' in router, (
        "el servidor tiene que enterarse de que es un cambio declarado"
    )

    # Y el servidor no se cree la petición: la vuelve a validar.
    checkout = open("checkout_routes.py", encoding="utf-8").read()

    assert 'data.get("plan_switch")' in checkout
    assert "switch_is_allowed" in checkout
    assert "if not cambio_de_plan and should_block_new_group_purchase" in checkout


def test_the_router_validates_the_callback_before_taking_money():
    router = open("callback_router.py", encoding="utf-8").read()

    pos = router.index('data.startswith("switchplan_")')
    trozo = router[pos:pos + 3000]

    assert "switch_is_allowed" in trozo
    assert "plan_is_switchable_target" in trozo
    assert "plan_switch=True" in trozo
    assert "plan_switch_rejected" in trozo, "un rechazo tiene que quedar escrito"

    # La rama va antes que la tarjeta de la comunidad, que es donde acababa
    # el upsell antes de existir este camino.
    assert router.index('data.startswith("switchplan_")') < \
        router.index('data.startswith("marketplace_group_")')


def test_the_annual_upsell_no_longer_walks_into_a_dead_end():
    renovacion = open("renewal_service.py", encoding="utf-8").read()

    pos = renovacion.index("renewal.upsell_annual_button")
    trozo = renovacion[pos - 400:pos + 200]

    assert "mysub_switch_" in trozo, (
        "el que ya tiene acceso aterrizaba en «ya tienes acceso»"
    )
    assert "marketplace_group_" not in trozo


def test_the_button_lives_in_the_access_screen():
    pantalla = open("mysub_callbacks.py", encoding="utf-8").read()

    assert 'callback_data=f"mysub_switch_{telegram_group_id}"' in pantalla
    assert pantalla.index('data.startswith("mysub_switch_")') < \
        pantalla.index('if data.startswith("mysub_"):'), (
        "la rama del cambio caería en la genérica"
    )
