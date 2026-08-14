"""
Cupones de descuento en el checkout de Stripe.

La regla que más importa aquí es el PERÍMETRO: el checkout de los grupos usa
la cuenta de Stripe de la plataforma, así que un cupón sin acotar valdría en
TODAS las comunidades. Cada cupón nace con applies_to limitado a los
productos de SU comunidad, y sin planes de Stripe no se crea ninguno.
"""

import pytest

import stripe_coupon_service as scs


@pytest.fixture
def comunidad(clean_db, monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (91, 'VIP Cupones', -1091, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, "
            "is_active, payment_provider, stripe_product_id, stripe_price_id) "
            "VALUES (91, 'Mensual', 15, 'EUR', 30, TRUE, 'stripe', 'prod_91', 'price_91')"
        )
        # Un plan de otro proveedor no entra en el perímetro.
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, "
            "is_active, payment_provider) "
            "VALUES (91, 'Mensual PP', 15, 'EUR', 30, TRUE, 'paypal')"
        )

    creados = {"coupons": [], "promos": [], "modificados": []}

    monkeypatch.setattr(
        scs.stripe.Coupon, "create",
        lambda **k: creados["coupons"].append(k) or {"id": "cup_1"}
    )
    monkeypatch.setattr(
        scs.stripe.PromotionCode, "create",
        lambda **k: creados["promos"].append(k) or {"id": "promo_1"}
    )
    monkeypatch.setattr(
        scs.stripe.PromotionCode, "modify",
        lambda pid, **k: creados["modificados"].append((pid, k)) or {"id": pid}
    )

    return {"db": db, "creados": creados}


def test_the_coupon_is_fenced_to_the_groups_own_products(comunidad):
    r = scs.create_group_coupon(91, "verano 20", 20, created_by=777)

    assert r["ok"] is True
    assert r["code"] == "VERANO20", "el código se normaliza a mayúsculas sin espacios"

    cupon = comunidad["creados"]["coupons"][0]

    assert cupon["applies_to"] == {"products": ["prod_91"]}, (
        "sin el perímetro, el cupón valdría en las comunidades de otros"
    )
    assert cupon["percent_off"] == 20
    assert cupon["duration"] == "once", (
        "en suscripciones el descuento es del PRIMER ciclo, no para siempre"
    )

    promo = comunidad["creados"]["promos"][0]
    assert promo["code"] == "VERANO20"


def test_without_stripe_plans_there_is_no_coupon(comunidad):
    with comunidad["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_active=FALSE WHERE stripe_product_id='prod_91'")

    r = scs.create_group_coupon(91, "SINPLAN", 20)

    assert r["ok"] is False and r["error"] == "sin_planes_stripe"
    assert not comunidad["creados"]["coupons"], "no puede llegar a Stripe"


def test_bad_codes_and_bad_percentages_never_reach_stripe(comunidad):
    assert scs.create_group_coupon(91, "ab", 20)["error"] == "codigo_invalido"
    assert scs.create_group_coupon(91, "CÓDIGO CON Ñ", 20)["error"] == "codigo_invalido"
    assert scs.create_group_coupon(91, "VALIDO", 0)["error"] == "porcentaje_invalido"
    assert scs.create_group_coupon(91, "VALIDO", 101)["error"] == "porcentaje_invalido"
    assert scs.create_group_coupon(91, "VALIDO", "veinte")["error"] == "porcentaje_invalido"

    assert not comunidad["creados"]["coupons"]


def test_a_live_code_cannot_be_duplicated(comunidad):
    scs.create_group_coupon(91, "UNICO", 10)

    r = scs.create_group_coupon(91, "UNICO", 25)

    assert r["ok"] is False and r["error"] == "codigo_repetido"
    assert len(comunidad["creados"]["coupons"]) == 1


def test_deactivating_kills_the_code_but_not_inflight_checkouts(comunidad):
    r = scs.create_group_coupon(91, "ADIOS", 10)

    listado = scs.list_group_coupons(91)
    assert len(listado) == 1

    ok = scs.deactivate_group_coupon(91, listado[0][0], actor_user_id=777)

    assert ok is True

    pid, cambios = comunidad["creados"]["modificados"][0]
    assert pid == "promo_1" and cambios == {"active": False}, (
        "se apaga el PromotionCode (nadie más lo teclea); el Coupon no se "
        "borra para que los checkouts en vuelo terminen bien"
    )

    assert scs.list_group_coupons(91) == []

    # Y el código queda libre para reutilizarse.
    r2 = scs.create_group_coupon(91, "ADIOS", 15)
    assert r2["ok"] is True


def test_the_screen_reads_like_an_owner_tool(comunidad):
    scs.create_group_coupon(91, "VERANO20", 20)

    texto = scs.build_coupons_text(91, "VIP Cupones")

    assert "VERANO20 — 20%" in texto
    assert "primer cobro" in texto

    vacio = scs.build_coupons_text(90, "Otra")
    assert "No hay cupones activos" in vacio


# =========================
# EL CABLEADO
# =========================

def test_the_checkout_lets_buyers_type_codes():
    source = open("checkout_routes.py", encoding="utf-8").read()

    assert "allow_promotion_codes=True" in source, (
        "sin esto, el campo de código no aparece en el checkout"
    )


def test_the_panel_wires_are_gated_to_the_owner():
    source = open("owner_panel_callbacks.py", encoding="utf-8").read()

    # La trampa de prefijos de siempre: el "off" antes que la pantalla.
    assert source.index('data.startswith("owner_stripe_coupon_off_")') < \
        source.index('data == "owner_stripe_coupons"')

    # Las tres ramas comprueban propietario o super admin.
    for ancla in ('data.startswith("owner_stripe_coupon_off_")',
                  'data == "owner_stripe_coupon_new"',
                  'data == "owner_stripe_coupons"'):

        pos = source.index(ancla)
        trozo = source[pos:pos + 700]

        assert "is_super_admin(user_id) or get_group_owner_user_id" in trozo, (
            f"la rama {ancla} no comprueba al propietario"
        )


def test_the_wizard_normalizes_and_reports_errors():
    source = open("admin_input_handler.py", encoding="utf-8").read()

    assert 'context.user_data.get("creating_stripe_coupon")' in source
    assert "normalizar_codigo" in source
    assert "sin_planes_stripe" in source, (
        "el error más probable necesita su mensaje claro"
    )
