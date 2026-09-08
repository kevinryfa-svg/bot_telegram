"""
Cinco cosas del panel, y una que me pilló a mí escribiéndolas.

La primera es la mejor: la auditoría de botones NO PODÍA detectar un botón
muerto. Buscaba la cadena del callback en el código, y ese código incluye las
definiciones de los teclados, así que todo botón encontraba su propia
definición y la pantalla salía ✅ por construcción. Peor que no tenerla,
porque se le cree.
"""

import pytest


# =========================
# UNA AUDITORÍA QUE NO PODÍA FALLAR
# =========================

def test_the_audit_can_now_tell_a_dead_button():
    import admin_button_audit as aba

    fuente = aba.load_callback_router_source()

    assert aba.callback_has_handler("esto_no_existe_en_ningun_sitio", fuente) is False

    # Y sigue reconociendo los que sí se atienden, de las tres formas.
    assert aba.callback_has_handler("admin_back_main", fuente) is True


def test_it_reads_the_three_dispatch_forms():
    import admin_button_audit as aba

    fuente = '''
        if data == "uno":
            pass
        if data in ("dos", "tres"):
            pass
        if data.startswith("cuatro_"):
            pass
    '''

    exactos, prefijos = aba._formas_de_despacho(fuente)

    assert exactos == {"uno", "dos", "tres"}
    assert prefijos == {"cuatro_"}

    assert aba.callback_has_handler("dos", fuente) is True
    assert aba.callback_has_handler("cuatro_99", fuente) is True
    assert aba.callback_has_handler("cinco", fuente) is False


def test_a_keyboard_definition_is_not_a_handler():
    """Era exactamente el fallo: el botón encontraba su propia definición."""

    import admin_button_audit as aba

    solo_definicion = 'InlineKeyboardButton("X", callback_data="boton_huerfano")'

    assert aba.callback_has_handler("boton_huerfano", solo_definicion) is False


# =========================
# UN MENÚ SEÑUELO
# =========================

def test_the_decoy_public_menu_is_gone():
    import commercial_catalog as cc

    assert not hasattr(cc, "PUBLIC_MENU_BUTTONS"), (
        "nadie la usaba y dos de sus botones no estaban enrutados: quien "
        "viniera a «cambiar los botones del menú» editaba código muerto"
    )
    assert not hasattr(cc, "get_public_menu_buttons")
    assert not hasattr(cc, "CALLBACK_EXPLORE_COMMUNITIES")


def test_nothing_referenced_it():
    import pathlib

    for ruta in sorted(pathlib.Path(".").glob("*.py")):

        texto = ruta.read_text(encoding="utf-8")

        # commercial_catalog.py conserva la mención en el comentario que
        # explica por qué se borró: eso es documentación, no código.
        if ruta.name == "commercial_catalog.py":

            assert "PUBLIC_MENU_BUTTONS = [" not in texto
            continue

        assert "PUBLIC_MENU_BUTTONS" not in texto, ruta.name
        assert "public_explore_communities" not in texto, ruta.name


# =========================
# UN 30 QUE PARECÍA UN TOTAL
# =========================
# La lista se topa a 30 para que quepa en un mensaje, y el pie decía
# «Suscriptores listados: 30». Peor: la previsión de cobros de los próximos 7
# días se calculaba con esas 30 filas.

@pytest.fixture
def con_socios(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (97, 'StarsVip', -1097, TRUE)"
        )

        for i in range(35):
            cur.execute(
                "INSERT INTO users (user_id, group_id, subscription_active, "
                "expiration, stripe_subscription_id) VALUES "
                "(%s, 97, TRUE, NOW() + (%s || ' days')::interval, %s)",
                (97000 + i, i + 1, f"sub_{i}"),
            )
            cur.execute(
                "INSERT INTO payments (user_id, group_id, amount, currency, "
                "status, plan) VALUES (%s, 97, 1500, 'EUR', 'paid', 'Mensual')",
                (97000 + i,),
            )

    return db


def test_the_total_is_counted_not_measured(con_socios):
    import owner_revenue_service as ors

    total, proximos, totales = ors.resumen_de_suscriptores(97)

    assert total == 35, "la lista está topada a 30; el total no"

    assert len(ors.fetch_subscriber_rows(97)) == 30, (
        "y la lista sigue topada a propósito: son dos preguntas distintas"
    )


def test_the_forecast_covers_everyone_not_just_the_listed(con_socios):
    import owner_revenue_service as ors

    _total, proximos, totales = ors.resumen_de_suscriptores(97, dias=7)

    assert proximos == 7, "los que cobran dentro de 7 días, de los 35"
    assert totales.get("EUR") == 7 * 1500, "en céntimos, y por moneda"


def test_the_footer_says_it_is_showing_a_slice(con_socios):
    import owner_revenue_service as ors

    texto = ors.build_owner_subscribers_text(97, "StarsVip")

    assert "35 en total" in texto
    assert "se listan los 30" in texto, (
        "un 30 a secas se lee como el total"
    )


def test_a_number_that_could_not_be_read_is_not_a_zero(monkeypatch):
    import owner_revenue_service as ors

    class Revienta:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr(ors, "conn", Revienta())

    total, proximos, totales = ors.resumen_de_suscriptores(97)

    assert total is None and proximos is None and totales == {}


# =========================
# DOS FUNCIONES CON EL MISMO NOMBRE Y UNIDADES CONTRARIAS
# =========================
# `formato_importe` de la tienda espera unidades MAYORES; el de ingresos
# esperaba CÉNTIMOS. Escribiendo esta tanda me colé y metí una división de
# más. El nombre lo dice ahora.

def test_the_cents_formatter_says_so_in_its_name():
    import owner_revenue_service as ors

    assert not hasattr(ors, "formato_importe"), (
        "el mismo nombre con la unidad contraria es de donde salen los errores "
        "de dinero por cien"
    )

    assert ors.formato_centimos(1500, "EUR") == "15.00 EUR"
    assert ors.formato_centimos(360, "EUR") == "3.60 EUR"


def test_the_report_keeps_its_fixed_decimals():
    """En una columna de importes, «15.00» y «3.60» se comparan de un vistazo."""

    import owner_revenue_service as ors

    assert ors.formato_centimos(1500, "EUR").endswith(".00 EUR")


# =========================
# RECHAZAR UN PAGO DE CRIPTO, A UN TOQUE
# =========================

def test_rejecting_a_crypto_payment_asks_first():
    fuente = open("admin_changenow_callbacks.py", encoding="utf-8").read()

    assert 'data.startswith("admin_changenow_reject_ask_")' in fuente

    # El botón de la lista lleva a la confirmación, no al rechazo.
    pos = fuente.index("❌ Rechazar #")
    assert "admin_changenow_reject_ask_" in fuente[pos:pos + 200]

    # Y la rama específica va ANTES de la genérica, o quedaría tapada.
    assert fuente.index('data.startswith("admin_changenow_reject_ask_")') < \
        fuente.index('data.startswith("admin_changenow_reject_"):')


def test_the_rejection_leaves_a_record():
    fuente = open("admin_changenow_callbacks.py", encoding="utf-8").read()

    pos = fuente.index('data.startswith("admin_changenow_reject_"):')
    trozo = fuente[pos:pos + 800]

    assert "log_event" in trozo
    assert "changenow_payment_rejected" in trozo


def test_a_failed_grant_says_why():
    fuente = open("admin_changenow_callbacks.py", encoding="utf-8").read()

    assert "Motivo: {result.get('reason')" in fuente, (
        "la razón se guardaba en metadata_json y solo se leía con SQL"
    )
