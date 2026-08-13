"""
El panel de ingresos del propietario.

El panel enseñaba usuarios, planes, códigos, admins y backup — todo menos el
dinero. Los datos salen de `payments`, donde escriben TODOS los caminos de
cobro, en céntimos.

Lo delicado: no inventar números. Monedas separadas (15 EUR + 15 USD no son
30 de nada), devoluciones fuera de los ingresos, y "histórico" cuando no hay
fecha fiable en vez de un "últimos 30 días" falso.
"""

import pytest

import owner_revenue_service as ors


# =========================
# FORMATO
# =========================

def test_amounts_are_cents_and_read_as_money():
    assert ors.formato_importe(1500, "EUR") == "15.00 EUR"
    assert ors.formato_importe(999, "usd") == "9.99 USD"


def test_an_empty_window_reads_as_zero_not_as_crash():
    assert ors.formato_ventana([]) == "0.00 EUR (0 pagos)"


def test_currencies_are_never_added_together():
    """15 EUR + 15 USD no son 30 de nada."""

    texto = ors.formato_ventana([("EUR", 1500, 2), ("USD", 1500, 1)])

    assert "15.00 EUR (2 pagos)" in texto
    assert "15.00 USD (1 pago)" in texto


# =========================
# CONTRA BASE DE DATOS REAL
# =========================

@pytest.fixture
def comunidad(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (98, 'VIP Ingresos', -1098, TRUE)"
        )

    return db


def pago(db, user_id, cents, status="paid", plan="Mensual", currency="EUR",
         hace_dias=0, group_id=98):
    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, "
            "plan, payment_date) "
            f"VALUES (%s, %s, %s, %s, %s, %s, NOW() - INTERVAL '{int(hace_dias)} days')",
            (user_id, group_id, cents, currency, status, plan),
        )


def test_revenue_is_split_by_window(comunidad):
    pago(comunidad, 1, 1500, hace_dias=1)      # este mes y 30 días
    pago(comunidad, 2, 2000, hace_dias=45)     # solo histórico

    r = ors.fetch_revenue_summary(98)

    historico = {c: (t, n) for c, t, n in r["historico"]}
    dias30 = {c: (t, n) for c, t, n in r["dias_30"]}

    assert historico["EUR"] == (3500, 2)
    assert dias30["EUR"] == (1500, 1)


def test_refunds_do_not_count_as_revenue(comunidad):
    """Una devolución no es un ingreso: es lo contrario."""

    pago(comunidad, 1, 1500)
    pago(comunidad, 2, 1500, status="refunded")

    r = ors.fetch_revenue_summary(98)
    historico = {c: (t, n) for c, t, n in r["historico"]}

    assert historico["EUR"] == (1500, 1)

    problemas = ors.fetch_problem_snapshot(98)

    assert problemas["devoluciones"] == 1


def test_other_groups_money_does_not_leak_in(comunidad):
    """El propietario ve SU comunidad, no la plataforma entera."""

    db = comunidad

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (99, 'Otra', -1099, TRUE)"
        )

    pago(db, 1, 1500, group_id=98)
    pago(db, 2, 99999, group_id=99)

    r = ors.fetch_revenue_summary(98)
    historico = {c: (t, n) for c, t, n in r["historico"]}

    assert historico["EUR"] == (1500, 1)


def test_currencies_are_reported_separately_from_the_db_too(comunidad):
    pago(comunidad, 1, 1500, currency="EUR")
    pago(comunidad, 2, 1500, currency="USD")

    r = ors.fetch_revenue_summary(98)

    monedas = {c for c, _, _ in r["historico"]}

    assert monedas == {"EUR", "USD"}


def test_customers_active_new_and_churned(comunidad):
    db = comunidad

    with db.conn.cursor() as cur:
        # Activo.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, created_at) "
            "VALUES (11, 98, NOW() + INTERVAL '20 days', TRUE, NOW() - INTERVAL '5 days')"
        )
        # Caducado hace 10 días, sin volver.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, created_at) "
            "VALUES (12, 98, NOW() - INTERVAL '10 days', FALSE, NOW() - INTERVAL '60 days')"
        )
        # Caducado hace medio año: fuera de la ventana de 30 días.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, created_at) "
            "VALUES (13, 98, NOW() - INTERVAL '180 days', FALSE, NOW() - INTERVAL '200 days')"
        )

    c = ors.fetch_customer_summary(98)

    assert c["activos"] == 1
    assert c["altas_30"] == 1
    assert c["caducados_30"] == 1


def test_the_top_plan_is_by_sales_count(comunidad):
    pago(comunidad, 1, 1500, plan="Mensual")
    pago(comunidad, 2, 1500, plan="Mensual")
    pago(comunidad, 3, 9000, plan="Anual")

    nombre, ventas = ors.fetch_top_plan(98)

    # Por número de ventas, no por importe: el anual factura más en un pago,
    # pero lo que el propietario pregunta es qué compra la gente.
    assert nombre == "Mensual"
    assert ventas == 2


def test_open_incidents_show_up(comunidad):
    db = comunidad

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_incidents (incident_key, kind, user_id, group_id) "
            "VALUES ('k1', 'storage_failed', 1, 98)"
        )
        cur.execute(
            "INSERT INTO payment_incidents (incident_key, kind, user_id, group_id, resolved_at) "
            "VALUES ('k2', 'storage_failed', 2, 98, NOW())"
        )

    p = ors.fetch_problem_snapshot(98)

    assert p["incidencias_abiertas"] == 1, "las resueltas no cuentan"


# =========================
# LA PANTALLA ENTERA
# =========================

def test_the_screen_reads_like_money_and_warns_on_open_incidents(comunidad):
    db = comunidad

    pago(db, 1, 1500, hace_dias=1)

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_incidents (incident_key, kind, user_id, group_id) "
            "VALUES ('k3', 'plan_not_found', 1, 98)"
        )

    texto = ors.build_owner_revenue_text(98, "VIP Ingresos")

    assert "💰 Ingresos de VIP Ingresos" in texto
    assert "15.00 EUR (1 pago)" in texto
    assert "Incidencias de pago abiertas: 1" in texto
    assert "cobros sin acceso" in texto, (
        "con incidencias abiertas, la pantalla tiene que pedir acción"
    )
    # Y la salud de entrega está integrada, no en otra pantalla.
    assert "Entrega de accesos:" in texto


def test_a_brand_new_community_renders_zeros_not_errors(comunidad):
    texto = ors.build_owner_revenue_text(98, "VIP Ingresos")

    assert "0.00 EUR (0 pagos)" in texto
    assert "Activos ahora: 0" in texto


def test_a_broken_database_degrades_instead_of_crashing(monkeypatch):
    """El panel del propietario no puede reventar por un hipo de la base."""

    class BrokenConn:
        def cursor(self):
            raise RuntimeError("base de datos caída")

    monkeypatch.setattr(ors, "conn", BrokenConn())

    texto = ors.build_owner_revenue_text(98, "VIP")

    assert "💰 Ingresos de VIP" in texto
    assert "0.00 EUR" in texto


# =========================
# EL BOTÓN Y LA RAMA
# =========================

def test_the_panel_has_the_button_and_the_router_the_branch():
    import callback_router as cr

    source = open(cr.__file__, encoding="utf-8").read()

    assert '"owner_panel_revenue"' in source
    assert "build_owner_revenue_text" in source

    # El botón vive dentro del mismo bloque de permisos que "Planes y pagos":
    # quien puede ver los pagos puede ver los ingresos, y nadie más.
    import ast as ast_mod

    tree = ast_mod.parse(source)

    creador = next(
        n for n in ast_mod.walk(tree)
        if isinstance(n, ast_mod.FunctionDef)
        and n.name == "build_group_settings_keyboard"
    )

    # Localizar el if cuyo bloque añade owner_panel_payments y comprobar que
    # también añade owner_panel_revenue.
    for n in ast_mod.walk(creador):

        if not isinstance(n, ast_mod.If):
            continue

        literales = {
            c.value for c in ast_mod.walk(n)
            if isinstance(c, ast_mod.Constant) and isinstance(c.value, str)
        }

        if "owner_panel_payments" in literales:

            assert "owner_panel_revenue" in literales, (
                "el botón de ingresos no está bajo los permisos de pagos"
            )

            return

    pytest.fail("no se encontró el bloque de permisos de pagos en el teclado")
