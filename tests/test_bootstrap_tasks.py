"""
Tareas de puesta a punto: arreglar DATOS de producción sin credenciales.

Hay cosas que no se arreglan con código: una comunidad sin descripción, un plan
sin precio. Las credenciales de la base no salen del servidor, y las pantallas
que tocan esos datos exigen a una persona con Telegram delante.

Estas tareas son la tercera vía, y lo que se vigila aquí es que se porten:
no pisan nada escrito por una persona, se pueden ejecutar mil veces, y el texto
que ponen no promete NADA que el bot no cumpla.
"""

import pytest

import bootstrap_tasks as bt


@pytest.fixture
def entorno(clean_db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_TASKS", "")

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "preview_text) VALUES "
            "(41, 'StarsVip', -1041, TRUE, NULL), "
            "(42, 'Con texto', -1042, TRUE, 'Aquí explico de verdad qué hay dentro.')"
        )
        cur.execute("DELETE FROM commercial_plans")
        cur.execute(
            "INSERT INTO commercial_plans (id, product_type, name, duration_days, "
            "amount) VALUES "
            "(701, 'shared_bot_space', '1 mes', 30, NULL), "
            "(702, 'shared_bot_space', '1 año', 365, NULL), "
            "(703, 'shared_bot_space', 'Raro', 47, NULL)"
        )

    return db


# =========================
# NADA SE EJECUTA SIN PEDIRLO
# =========================

def test_without_the_variable_nothing_runs(entorno):
    assert bt.tareas_pedidas() == []
    assert bt.run_bootstrap_tasks() == []

    with entorno.conn.cursor() as cur:
        cur.execute("SELECT preview_text FROM groups WHERE id=41")
        assert cur.fetchone()[0] is None, "el estado normal es no tocar nada"


def test_an_unknown_task_says_so_instead_of_failing_silently(entorno, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_TASKS", "no_existe_esta")

    lineas = bt.run_bootstrap_tasks()

    assert len(lineas) == 1
    assert "no existe esa tarea" in lineas[0]
    assert "descripcion_minima" in lineas[0], "y dice cuáles hay"


# =========================
# LA DESCRIPCIÓN DE RELLENO
# =========================

def test_it_only_fills_the_empty_ones(entorno):
    resultado = bt.tarea_descripcion_minima()

    assert "1 comunidad(es)" in resultado
    assert "StarsVip" in resultado

    with entorno.conn.cursor() as cur:
        cur.execute("SELECT preview_text FROM groups WHERE id=42")

        assert cur.fetchone()[0] == "Aquí explico de verdad qué hay dentro.", (
            "un arreglo automático que sobrescribe lo que escribió una persona "
            "no es un arreglo"
        )


def test_the_filler_promises_nothing_the_bot_cannot_keep(entorno):
    """Yo no sé qué hay dentro de la comunidad de nadie."""

    texto = bt.descripcion_minima("StarsVip")

    # Ni una palabra sobre el contenido: inventarlo sería ponerle al comprador
    # una promesa que no ha hecho nadie.
    for inventado in ("señales", "directos", "exclusivo", "diario", "vídeos",
                      "análisis", "cada semana", "contenido premium"):
        assert inventado.lower() not in texto.lower(), inventado

    # Y lo que dice, lo cumple el bot.
    assert "se confirma el pago" in texto
    assert "cancelar la renovación" in texto


def test_running_it_twice_changes_nothing(entorno):
    primera = bt.tarea_descripcion_minima()
    segunda = bt.tarea_descripcion_minima()

    assert "1 comunidad(es)" in primera
    assert "nada que hacer" in segunda, (
        "el arranque se repite en cada despliegue: no puede ir reescribiendo"
    )


def test_the_panel_still_demands_a_real_description(entorno):
    """El relleno no puede silenciar el aviso que hace falta."""

    import owner_readiness_service as ors

    bt.tarea_descripcion_minima()

    ok, texto = ors.check_pitch(41)

    assert ok is False, (
        "con el texto de relleno, la comunidad sigue sin decir qué hay dentro"
    )
    assert "texto de relleno" in texto
    assert "Vista previa" in texto


def test_a_real_description_passes_the_panel(entorno):
    import owner_readiness_service as ors

    ok, _texto = ors.check_pitch(42)

    assert ok is True


# =========================
# EL PRECIO DE PUBLICAR
# =========================

def test_it_prices_the_known_durations(entorno):
    resultado = bt.tarea_precio_publicacion()

    assert "2 plan(es)" in resultado

    with entorno.conn.cursor() as cur:
        cur.execute("SELECT amount FROM commercial_plans WHERE id=701")
        assert cur.fetchone()[0] == 1999, "19,99 al mes"

        cur.execute("SELECT amount FROM commercial_plans WHERE id=702")
        assert cur.fetchone()[0] == 17999, "179,99 al año"


def test_an_unknown_duration_is_not_priced_by_guessing(entorno):
    bt.tarea_precio_publicacion()

    with entorno.conn.cursor() as cur:
        cur.execute("SELECT amount FROM commercial_plans WHERE id=703")

        assert cur.fetchone()[0] is None, (
            "un precio a ojo en un plan de verdad se lo come un cliente"
        )


def test_it_never_touches_a_plan_that_already_has_a_price(entorno):
    with entorno.conn.cursor() as cur:
        cur.execute("UPDATE commercial_plans SET amount=4900 WHERE id=701")

    bt.tarea_precio_publicacion()

    with entorno.conn.cursor() as cur:
        cur.execute("SELECT amount FROM commercial_plans WHERE id=701")

        assert cur.fetchone()[0] == 4900, "el precio que puso una persona manda"


def test_after_pricing_the_plan_can_actually_be_bought(entorno):
    """El objetivo de la tarea no es el número: es que se pueda pagar."""

    import platform_plan_service as pps

    assert pps.platform_plan_is_purchasable() is False

    bt.tarea_precio_publicacion()

    assert pps.platform_plan_is_purchasable() is True

    planes = pps.fetch_purchasable_platform_plans()

    assert pps.format_plan_amount(planes[0]) == "19,99 EUR"


def test_running_the_price_task_twice_changes_nothing(entorno):
    bt.tarea_precio_publicacion()
    segunda = bt.tarea_precio_publicacion()

    assert "nada que hacer" in segunda


def test_the_startup_runs_them_wrapped():
    fuente = open("main.py", encoding="utf-8").read()

    assert "run_bootstrap_tasks" in fuente

    pos = fuente.index("run_bootstrap_tasks")

    assert "try:" in fuente[pos - 400:pos], (
        "una tarea de datos no puede impedir que el bot arranque"
    )


# =========================
# CAMBIAR EL PRECIO DE UNA COMUNIDAD
# =========================
# El importe vive en DOS sitios: plans.amount (lo que se ENSEÑA) y el precio de
# Stripe (lo que se COBRA). El asistente del panel deja cambiar el primero y pide
# el segundo a mano, sin comprobar que coincidan: así se puede anunciar 29 y
# cobrar 7, o al revés, y no enterarse hasta mirar un extracto.

@pytest.fixture
def plan_de_comunidad(entorno, monkeypatch):
    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append({
            "amount_major": amount_major,
            "currency": currency,
            "recurring_interval_days": recurring_interval_days,
        })
        return (f"prod_{len(creados)}", f"price_nuevo_{len(creados)}")

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    with entorno.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active, is_recurring) VALUES "
            "(881, 41, 'VIP', 'price_viejo', 'price_viejo', 360, 7, 'EUR', TRUE, TRUE)"
        )

    return {"db": entorno, "creados": creados}


def test_changing_the_price_also_changes_what_stripe_charges(plan_de_comunidad,
                                                             monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PLAN_PRICE", "881:29")

    resultado = bt.tarea_precio_comunidad()

    assert "7.00 → 29.00 EUR" in resultado

    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute("SELECT amount, stripe_price_id FROM plans WHERE id=881")
        amount, price_id = cur.fetchone()

    assert float(amount) == 29.0, "lo que se enseña"
    assert price_id == "price_nuevo_1", "y lo que se cobra, cambiados JUNTOS"

    creado = plan_de_comunidad["creados"][0]

    assert creado["amount_major"] == pytest.approx(29.0), (
        "plans.amount va en unidades MAYORES: pasar céntimos cobraría 100 veces "
        "de más"
    )
    assert creado["recurring_interval_days"] == 360, (
        "el plan es recurrente: convertirlo en pago único cambia lo que el "
        "comprador cree que compra"
    )


def test_a_one_off_plan_does_not_become_a_subscription(plan_de_comunidad,
                                                       monkeypatch):
    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_recurring=FALSE WHERE id=881")

    monkeypatch.setenv("BOOTSTRAP_PLAN_PRICE", "881:29")

    bt.tarea_precio_comunidad()

    assert plan_de_comunidad["creados"][0]["recurring_interval_days"] is None


def test_the_same_price_twice_does_not_create_another_stripe_price(
    plan_de_comunidad, monkeypatch
):
    monkeypatch.setenv("BOOTSTRAP_PLAN_PRICE", "881:29")

    bt.tarea_precio_comunidad()
    segunda = bt.tarea_precio_comunidad()

    assert "ya está a 29.00" in segunda
    assert len(plan_de_comunidad["creados"]) == 1, (
        "un precio nuevo en cada arranque llenaría Stripe de duplicados"
    )


def test_without_the_variable_it_touches_nothing(plan_de_comunidad, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_PLAN_PRICE", raising=False)

    resultado = bt.tarea_precio_comunidad()

    assert "falta BOOTSTRAP_PLAN_PRICE" in resultado
    assert plan_de_comunidad["creados"] == []


def test_a_plan_from_another_provider_is_refused(plan_de_comunidad, monkeypatch):
    """Su identificador de precio lo emite el proveedor, no nosotros."""

    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET payment_provider='paypal' WHERE id=881")

    monkeypatch.setenv("BOOTSTRAP_PLAN_PRICE", "881:29")

    resultado = bt.tarea_precio_comunidad()

    assert "paypal" in resultado
    assert plan_de_comunidad["creados"] == [], (
        "cambiar solo el importe dejaría descuadrado lo que se cobra"
    )


def test_garbage_in_the_variable_is_reported_not_guessed(plan_de_comunidad,
                                                         monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PLAN_PRICE", "881,esto:no,:")

    resultado = bt.tarea_precio_comunidad()

    assert "no tiene la forma" in resultado or "no son números" in resultado
    assert plan_de_comunidad["creados"] == []
