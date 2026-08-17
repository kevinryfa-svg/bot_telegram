"""
Quitar el último plan deja la tienda abierta y vacía.

Cuando se borraba el último plan activo de una comunidad, el código hacía
esto:

    if remaining_plans == 0:
        print("Grupo sin planes restantes:", group_id)

Es decir: el único que se enteraba era quien leyera los logs del servidor.
La comunidad seguía visible en el mercado, y quien entrara pulsaría
«Comprar acceso» para encontrarse con nada.

Las dos reglas: se avisa a quien acaba de hacerlo, en el momento; y el aviso
distingue si la comunidad está VISIBLE (hay gente que se va a topar con la
tienda vacía) o no (entonces no hay urgencia, solo un recordatorio).
"""

import pytest

import platform_health_service as phs


@pytest.fixture
def comunidad_visible(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible) VALUES (64, 'VIP Tienda', -1064, TRUE, TRUE)"
        )

    return db


def test_the_visible_community_without_plans_is_detectable(comunidad_visible):
    """Es la misma consulta que usa el panel de salud: una sola verdad."""

    assert [f[0] for f in phs.fetch_unsellable_but_visible()] == [64]

    with comunidad_visible.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) "
            "VALUES (64, 'Mensual', 'price_64', 'price_64', 30, 15, 'EUR', TRUE)"
        )

    assert phs.fetch_unsellable_but_visible() == [], (
        "con un plan usable la tienda ya no está vacía"
    )


def test_a_hidden_community_is_not_an_emergency(comunidad_visible):
    with comunidad_visible.conn.cursor() as cur:
        cur.execute(
            "UPDATE groups SET is_marketplace_visible=FALSE, "
            "is_main_menu_visible=FALSE WHERE id=64"
        )

    assert phs.fetch_unsellable_but_visible() == [], (
        "sin visibilidad nadie se topa con la tienda vacía"
    )


def test_the_warning_replaced_the_print_and_says_what_to_do():
    router = open("callback_router.py", encoding="utf-8").read()

    assert 'print(\n                        "Grupo sin planes restantes:",' not in router, (
        "el print solo avisaba a quien leyera los logs del servidor"
    )

    pos = router.index("if remaining_plans == 0:")
    trozo = router[pos:pos + 2500]

    # Se avisa, se registra, y se distingue visible de escondida.
    assert "Era el último plan activo" in trozo
    assert "group_left_without_plans" in trozo
    assert "fetch_unsellable_but_visible" in trozo, (
        "la visibilidad se comprueba con la misma consulta que el panel de "
        "salud, para que las dos pantallas no puedan contradecirse"
    )
    assert "pulsará «Comprar acceso» y no encontrará nada" in trozo
    assert "nadie se va a topar con la tienda vacía" in trozo

    # Y lleva al sitio donde se ve todo lo que falta para vender.
    assert 'callback_data="owner_panel_ready"' in trozo
