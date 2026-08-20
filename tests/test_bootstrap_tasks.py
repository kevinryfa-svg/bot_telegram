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
            # El nombre se guarda porque es lo que se lee en la página de pago:
            # un doble que no lo mira no puede vigilar lo que ve el comprador.
            "name": name,
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


def test_the_group_can_be_named_instead_of_the_plan(plan_de_comunidad,
                                                    monkeypatch):
    """Los ids de plan no se pueden consultar desde fuera; el del grupo sí."""

    monkeypatch.setenv("BOOTSTRAP_PLAN_PRICE", "g41:29")

    resultado = bt.tarea_precio_comunidad()

    assert "grupo 41 → plan #881" in resultado
    assert "7.00 → 29.00 EUR" in resultado


def test_a_tie_between_plans_is_refused_instead_of_drawn(plan_de_comunidad,
                                                         monkeypatch):
    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active, is_recurring) VALUES "
            "(882, 41, 'Otro', 'price_v2', 'price_v2', 30, 7, 'EUR', TRUE, TRUE)"
        )

    monkeypatch.setenv("BOOTSTRAP_PLAN_PRICE", "g41:29")

    resultado = bt.tarea_precio_comunidad()

    assert "no se elige por sorteo" in resultado
    assert "#881" in resultado and "#882" in resultado, (
        "los enumera para poder elegir a mano"
    )
    assert plan_de_comunidad["creados"] == []


def test_an_undeliverable_plan_is_never_the_chosen_one(plan_de_comunidad,
                                                       monkeypatch):
    """El plan de 1.300.000 días no se puede entregar: no es candidato."""

    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active, is_recurring) VALUES "
            "(883, 41, 'Eterno', 'price_e', 'price_e', 1300000, 1, 'EUR', TRUE, TRUE)"
        )

    monkeypatch.setenv("BOOTSTRAP_PLAN_PRICE", "g41:29")

    resultado = bt.tarea_precio_comunidad()

    assert "plan #881" in resultado, "el entregable, no el más barato a secas"


# =========================
# PASAR UN PLAN A COBRAR POR STRIPE
# =========================
# En producción, lo ÚNICO a la venta cobraba por PayPal, y ese PayPal tiene el
# webhook_id inválido: el bot se niega a cobrar, con razón, porque el pago no se
# podría confirmar y el acceso no se entregaría. Con eso, la conversión no podía
# ser otra cosa que cero.

@pytest.fixture
def plan_de_paypal(plan_de_comunidad):
    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute(
            "UPDATE plans SET payment_provider='paypal', stripe_price_id=NULL, "
            "price_id='P-PAYPAL-1' WHERE id=881"
        )

    return plan_de_comunidad


def test_a_paypal_plan_is_switched_and_gets_a_stripe_price(plan_de_paypal,
                                                            monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PLAN_PROVIDER", "g41")

    resultado = bt.tarea_cobrar_por_stripe()

    assert "paypal → stripe" in resultado

    with plan_de_paypal["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT payment_provider, stripe_price_id, price_id, amount "
            "FROM plans WHERE id=881"
        )
        proveedor, stripe_price_id, price_id, importe = cur.fetchone()

    assert proveedor == "stripe"
    assert stripe_price_id == "price_nuevo_1"
    assert price_id == "price_nuevo_1", (
        "el identificador de PayPal ya no vale para nada aquí"
    )
    assert float(importe) == 7.0, "el importe anunciado no se toca"

    creado = plan_de_paypal["creados"][0]

    assert creado["amount_major"] == pytest.approx(7.0), (
        "se cobra lo que ya se anunciaba: nadie paga algo distinto de lo que vio"
    )


def test_a_working_provider_is_left_alone(plan_de_comunidad, monkeypatch):
    """Cambiar un cobro que funciona es mover el dinero de sitio sin pedirlo."""

    monkeypatch.setenv("BOOTSTRAP_PLAN_PROVIDER", "g41")

    resultado = bt.tarea_cobrar_por_stripe()

    assert "ya cobra por Stripe" in resultado
    assert plan_de_comunidad["creados"] == []


def test_the_provider_and_the_price_are_written_together(plan_de_paypal,
                                                          monkeypatch):
    """Si Stripe falla, el plan NO se queda a medias."""

    import stripe_catalog

    monkeypatch.setenv("BOOTSTRAP_PLAN_PROVIDER", "g41")
    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Stripe down"))
    )

    resultado = bt.tarea_cobrar_por_stripe()

    assert "Stripe no aceptó" in resultado

    with plan_de_paypal["db"].conn.cursor() as cur:
        cur.execute("SELECT payment_provider FROM plans WHERE id=881")

        assert cur.fetchone()[0] == "paypal", (
            "dejar el proveedor cambiado sin precio válido es cambiar un cobro "
            "roto por otro"
        )


def test_without_the_variable_it_does_nothing(plan_de_paypal, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_PLAN_PROVIDER", raising=False)

    assert "falta BOOTSTRAP_PLAN_PROVIDER" in bt.tarea_cobrar_por_stripe()
    assert plan_de_paypal["creados"] == []


def test_after_switching_the_community_can_actually_be_charged(plan_de_paypal,
                                                                monkeypatch):
    """El objetivo no es el proveedor: es que exista una venta posible."""

    import sale_readiness_service as srs

    monkeypatch.setenv("BOOTSTRAP_PLAN_PROVIDER", "g41")

    bt.tarea_cobrar_por_stripe()

    import start_offer_service as sos

    oferta = [o for o in sos.fetch_sellable_communities(0) if o["group_id"] == 41]

    assert oferta, "sigue en el escaparate"
    assert oferta[0]["provider"] == "stripe"
    assert oferta[0]["price_id"] == "price_nuevo_1"

    import stripe

    monkeypatch.setattr(
        stripe.Price, "retrieve",
        lambda price_id: {"id": price_id, "unit_amount": 700}
    )

    rotos, comprobados = srs.check_stripe_prices(oferta)

    assert (rotos, comprobados) == ([], 1), (
        "y ahora el diagnóstico lo da por cobrable"
    )


# =========================
# EL NOMBRE QUE SE LEE AL PAGAR
# =========================
# El nombre del plan viaja al producto de Stripe: es lo que se lee en la página
# de pago, con la tarjeta ya en la mano. En producción se llamaba «PERMANENTE
# PAYPAL» — ni permanente (360 días) ni PayPal (ya no).

def test_renaming_also_forces_a_price_with_the_new_name(plan_de_comunidad,
                                                        monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PLAN_NAME", "881=Acceso 360 días")

    resultado = bt.tarea_renombrar_plan()

    assert "«Acceso 360 días»" in resultado

    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute("SELECT name, stripe_price_id FROM plans WHERE id=881")
        nombre, price_id = cur.fetchone()

    assert nombre == "Acceso 360 días"
    assert price_id is None, (
        "sin borrarlo, el nombre cambiaría en el bot y la página de pago "
        "seguiría diciendo el viejo"
    )

    # Y la reparación de arranque, que corre justo después, lo recrea bien.
    import plan_price_service as pps

    pps.reparar_precios_de_planes()

    assert plan_de_comunidad["creados"][-1]["name"] == "Acceso 360 días"


def test_an_empty_name_is_refused(plan_de_comunidad, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PLAN_NAME", "881=   ")

    assert "no es un nombre" in bt.tarea_renombrar_plan()

    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute("SELECT name FROM plans WHERE id=881")
        assert cur.fetchone()[0] == "VIP"


def test_a_name_with_colons_survives(plan_de_comunidad, monkeypatch):
    """Por eso el separador es «=» y no «:»."""

    monkeypatch.setenv("BOOTSTRAP_PLAN_NAME", "881=VIP: acceso 12 meses")

    bt.tarea_renombrar_plan()

    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute("SELECT name FROM plans WHERE id=881")
        assert cur.fetchone()[0] == "VIP: acceso 12 meses"


def test_without_the_variable_nothing_is_renamed(plan_de_comunidad, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_PLAN_NAME", raising=False)

    assert "falta BOOTSTRAP_PLAN_NAME" in bt.tarea_renombrar_plan()


def test_renaming_what_cannot_be_sold_does_not_erase_its_price(
    plan_de_comunidad, monkeypatch
):
    """El caso real: se renombró y la página de pago siguió igual.

    En producción se renombró un plan, el arranque dijo «se le creará precio
    nuevo» y no se creó ninguno: el plan no estaba entre los vendibles, así que
    la reparación pasó de largo. Borrarle el identificador lo habría dejado
    apoyado en el precio viejo —con el nombre viejo— y encima con el log
    prometiendo lo contrario.
    """

    with plan_de_comunidad["db"].conn.cursor() as cur:
        # Más días de los que el cobro puede convertir en acceso: fuera del
        # escaparate y fuera de la reparación.
        cur.execute("UPDATE plans SET duration_days=4000 WHERE id=881")

    monkeypatch.setenv("BOOTSTRAP_PLAN_NAME", "881=Acceso 360 días")

    resultado = bt.tarea_renombrar_plan()

    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute("SELECT name, stripe_price_id FROM plans WHERE id=881")
        nombre, price_id = cur.fetchone()

    assert nombre == "Acceso 360 días", "el nombre sí se cambia"
    assert price_id == "price_viejo", (
        "quitarle el precio a un plan al que nadie va a crearle otro solo "
        "empeora lo que ya estaba"
    )
    assert "seguirá diciendo el nombre viejo" in resultado
    assert "4000" in resultado, "y por qué, para no volver a buscar a ciegas"


# =========================
# MIRAR SIN TOCAR
# =========================
# La tarea que faltaba: todas las demás cambian datos y hay que creerse la línea
# del arranque. Cuando el resultado no es el esperado, sin esto no hay forma de
# averiguar por qué desde fuera del servidor.

def test_the_listing_says_why_a_plan_is_not_being_sold(plan_de_comunidad,
                                                       monkeypatch):
    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute("UPDATE plans SET payment_provider='paypal' WHERE id=881")

    monkeypatch.setenv("BOOTSTRAP_PLAN_LIST", "881")

    resultado = bt.tarea_listar_planes()

    assert "#881" in resultado
    assert "NO SE VENDE" in resultado
    assert "paypal" in resultado


def test_the_listing_shows_a_sellable_plan_as_sellable(plan_de_comunidad,
                                                       monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PLAN_LIST", "g41")

    resultado = bt.tarea_listar_planes()

    assert "#881" in resultado
    assert "SE VENDE" in resultado
    assert "NO SE VENDE" not in resultado
    assert "price_viejo" in resultado, (
        "sin el identificador entero no se puede comparar con lo que hay en "
        "Stripe, que es para lo que sirve mirar"
    )


def test_the_listing_changes_nothing(plan_de_comunidad, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PLAN_LIST", "todos")

    bt.tarea_listar_planes()

    with plan_de_comunidad["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT name, amount, stripe_price_id, payment_provider "
            "FROM plans WHERE id=881"
        )
        assert cur.fetchone() == ("VIP", 7, "price_viejo", "stripe")

    assert plan_de_comunidad["creados"] == [], (
        "mirar no crea precios en Stripe"
    )


def test_a_plan_that_does_not_exist_is_said_plainly(plan_de_comunidad,
                                                    monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PLAN_LIST", "999999")

    assert "no existe" in bt.tarea_listar_planes()


def test_without_the_variable_nothing_is_listed(plan_de_comunidad, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_PLAN_LIST", raising=False)

    assert "falta BOOTSTRAP_PLAN_LIST" in bt.tarea_listar_planes()
