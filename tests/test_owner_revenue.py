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
# V2: COMPARATIVA, RENOVACIÓN Y CSV
# =========================

def test_month_comparison_uses_whole_months_not_rolling_windows(comunidad):
    db = comunidad

    with db.conn.cursor() as cur:
        # Mes actual y mes anterior COMPLETO, sin depender del día de hoy.
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, "
            "plan, payment_date) VALUES "
            "(1, 98, 3000, 'EUR', 'paid', 'Mensual', date_trunc('month', NOW()) + INTERVAL '1 hour'), "
            "(2, 98, 2000, 'EUR', 'paid', 'Mensual', date_trunc('month', NOW()) - INTERVAL '10 days')"
        )

    filas = ors.fetch_month_comparison(98)

    assert filas == [("EUR", 3000, 2000)]

    texto = ors.formato_comparativa(filas)

    assert "30.00 EUR" in texto
    assert "mes anterior: 20.00 EUR" in texto
    assert "+50%" in texto


def test_renewals_are_second_payments_of_the_same_person(comunidad):
    """La definición vale para todos los proveedores: renovar es volver a
    pagar donde ya pagaste."""

    pago(comunidad, 1, 1500, hace_dias=40)   # primera compra, vieja
    pago(comunidad, 1, 1500, hace_dias=5)    # renovación (2º pago) ✓
    pago(comunidad, 2, 1500, hace_dias=5)    # primera compra: NO es renovación

    r = ors.fetch_autorenew_summary(98)

    assert r["renovaciones_30d"] == 1


def test_subscribers_are_counted_by_their_anchors(comunidad):
    db = comunidad

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) "
            "VALUES (21, 98, NOW() + INTERVAL '20 days', TRUE, 'sub_21')"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (22, 98, NOW() + INTERVAL '20 days', TRUE)"
        )
        cur.execute(
            "INSERT INTO payment_transactions (provider, status, payment_scope, "
            "purchase_type, user_id, group_id, external_checkout_id) "
            "VALUES ('paypal', 'paid', 'platform', 'group_access', 22, 98, 'I-22')"
        )
        # Con ancla pero inactivo: no cuenta.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) "
            "VALUES (23, 98, NOW() - INTERVAL '1 day', FALSE, 'sub_23')"
        )

    r = ors.fetch_autorenew_summary(98)

    assert r["suscriptores"] == 2


def test_the_csv_is_for_a_spreadsheet_not_for_our_database(comunidad):
    pago(comunidad, 1, 1500, plan="Mensual; con punto y coma")

    csv = ors.build_payments_csv(98)
    lineas = csv.splitlines()

    assert lineas[0] == "fecha;usuario;importe;moneda;estado;plan"
    assert ";15.00;EUR;paid;" in lineas[1], (
        "importes en unidades mayores: el destinatario es una hoja de cálculo"
    )
    assert "punto y coma" in lineas[1]
    assert lineas[1].count(";") == 5, "el ';' del nombre del plan iba a romper la columna"


def test_the_screen_now_shows_autorenewal_and_comparison(comunidad):
    pago(comunidad, 1, 1500, hace_dias=1)

    texto = ors.build_owner_revenue_text(98, "VIP Ingresos")

    assert "🔁 Renovación automática" in texto
    assert "Suscriptores activos: 0" in texto
    assert "Renovaciones cobradas (30 días): 0" in texto


def test_the_csv_button_lives_in_the_revenue_screen_with_the_same_gates():
    source = open("owner_panel_callbacks.py", encoding="utf-8").read()

    assert '"owner_panel_revenue_csv"' in source
    assert "build_payments_csv" in source

    # El CSV comprueba los MISMOS permisos que la pantalla: es la misma
    # información en otro formato.
    pos = source.index('if data == "owner_panel_revenue_csv":')
    trozo = source[pos:pos + 800]

    assert "get_selected_group_for_permissions" in trozo
    assert "can_view_payments" in trozo


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


# =========================
# EL PANEL DE SUSCRIPTORES
# =========================
# La lista humana detrás de los números: quién tiene renovación, cuánto paga
# de verdad (su último cobro), y cuándo le toca.

def test_subscribers_are_listed_by_next_charge_with_their_real_price(comunidad):
    db = comunidad

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, username, expiration, "
            "subscription_active, stripe_subscription_id) VALUES "
            "(31, 98, 'ana', NOW() + INTERVAL '3 days', TRUE, 'sub_31'), "
            "(32, 98, NULL, NOW() + INTERVAL '20 days', TRUE, NULL)"
        )
        cur.execute(
            "INSERT INTO payment_transactions (provider, status, payment_scope, "
            "purchase_type, user_id, group_id, external_checkout_id) "
            "VALUES ('paypal', 'paid', 'platform', 'group_access', 32, 98, 'I-32')"
        )
        # El precio REAL de ana: su último cobro fue con precio antiguo (10).
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            "(31, 98, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '60 days'), "
            "(31, 98, 1000, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '2 days')"
        )
        # Sin renovación: no aparece.
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (33, 98, NOW() + INTERVAL '10 days', TRUE)"
        )

    filas = ors.fetch_subscriber_rows(98)

    assert [f[0] for f in filas] == [31, 32], (
        "por próximo cobro, y el 33 (sin renovación) fuera"
    )
    assert filas[0][4] == 1000, "el precio es su ÚLTIMO cobro, no el primero"

    texto = ors.build_owner_subscribers_text(98, "VIP Ingresos")

    assert "@ana — 10.00 EUR" in texto
    assert "id 32" in texto, "sin username se identifica por id"
    assert "paypal" in texto
    assert "Cobros en los próximos 7 días: 1" in texto
    assert "10.00 EUR" in texto


def test_an_empty_subscriber_list_explains_itself(comunidad):
    texto = ors.build_owner_subscribers_text(98, "VIP Ingresos")

    assert "Nadie tiene renovación automática todavía" in texto


def test_the_subscribers_button_lives_in_the_revenue_panel():
    source = open("owner_panel_callbacks.py", encoding="utf-8").read()

    assert '"owner_panel_subscribers"' in source

    pos = source.index('if data == "owner_panel_subscribers":')
    trozo = source[pos:pos + 700]

    assert "can_view_payments" in trozo, (
        "la lista de quién paga ES información de pagos: mismos permisos"
    )


# =========================
# EXPORTAR SOCIOS (la gente, no las transacciones)
# =========================

def test_the_members_csv_covers_active_expired_and_permanent(comunidad):
    """El CSV de pagos son transacciones; este es la gente."""

    db = comunidad

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "username, stripe_subscription_id) VALUES "
            "(6001, 98, NOW() + INTERVAL '10 days', TRUE, 'activa', 'sub_98'), "
            "(6002, 98, NOW() - INTERVAL '10 days', FALSE, 'caducado', NULL), "
            "(6003, 98, NULL, TRUE, 'permanente', NULL) "
            "ON CONFLICT (user_id, group_id) DO NOTHING"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            "(6001, 98, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '40 days'), "
            "(6001, 98, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '10 days'), "
            "(6002, 98, 2000, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '80 days')"
        )

    csv = ors.build_members_csv(98)
    lineas = csv.split("\n")

    assert lineas[0].startswith("usuario;username;estado;acceso_hasta;renovacion")

    filas = {l.split(";")[0]: l.split(";") for l in lineas[1:]}

    assert filas["6001"][2] == "activo"
    assert filas["6001"][4] == "stripe", "la renovación real, no la de lista"
    assert filas["6001"][5] == "2", "dos pagos"
    assert filas["6001"][6] == "30.00", (
        "el total en unidades mayores: el destinatario es una hoja de cálculo"
    )

    assert filas["6002"][2] == "caducado"
    assert filas["6002"][4] == "no"
    assert filas["6002"][6] == "20.00"

    assert filas["6003"][2] == "permanente"
    assert filas["6003"][3] == "", "sin fecha de fin, la columna va vacía"
    assert filas["6003"][5] == "0", "nunca pagó: cero pagos, no una fila falsa"


def test_the_members_csv_button_shares_the_payment_permissions():
    panel = open("owner_panel_callbacks.py", encoding="utf-8").read()

    assert 'callback_data="owner_panel_members_csv"' in panel

    pos = panel.index('if data == "owner_panel_members_csv":')
    trozo = panel[pos:pos + 900]

    for permiso in ("can_manage_plans", "can_manage_groups",
                    "can_view_payments", "can_manage_payments"):
        assert permiso in trozo
