"""
Cinco agujeros del panel, encontrados leyéndolo como lo lee quien lo usa para
decidir.

El peor no es el que revienta: es el que MIENTE. Una pantalla que dice «nada
roto» cuando la consulta ha fallado, y otra que multiplica los ingresos por
cien, valen menos que no tenerlas — porque se les cree.
"""

import pytest


# =========================
# LOS INGRESOS, MULTIPLICADOS POR CIEN
# =========================
# payments.amount está en céntimos. La pantalla de últimos pagos lo pintaba en
# crudo, así que una venta de 3,60 € se leía «Importe: 360 EUR». Es la pantalla
# que se abre para echar un ojo a las ventas recientes.

def test_the_last_payments_screen_no_longer_multiplies_by_a_hundred():
    fuente = open("admin_view_callbacks.py", encoding="utf-8").read()

    pos = fuente.index('"💳 Últimos pagos')
    trozo = fuente[pos:pos + 1600]

    assert "formato_importe" in trozo, (
        "los céntimos de la base no son el precio que se lee"
    )
    assert "{amount or '-'} {currency or ''}" not in trozo


def test_the_cents_are_turned_into_the_price_the_shop_shows():
    from start_offer_service import formato_importe

    assert formato_importe(360 / 100.0, "EUR") == "3,60 EUR"
    assert formato_importe(1500 / 100.0, "EUR") == "15 EUR"


# =========================
# «NADA ROTO» CUANDO NO SE HA PODIDO COMPROBAR
# =========================
# Cada consulta devolvía lista vacía también al fallar, y la pantalla remataba
# con «✅ Nada roto». Un error de base de datos se leía IGUAL que una plataforma
# sana, en la única pantalla que existe para decir qué está roto.

def test_a_failed_query_is_not_an_empty_one(monkeypatch):
    import platform_health_service as phs

    class Revienta:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr(phs, "conn", Revienta())

    assert phs.fetch_broken_delivery() is None
    assert phs.fetch_open_incidents() is None
    assert phs.fetch_unsellable_but_visible() is None
    assert phs.fetch_failed_charge_streaks() is None
    assert phs.count_failed_notices_without_portal() is None


def test_the_screen_says_it_could_not_check(monkeypatch):
    import platform_health_service as phs

    class Revienta:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr(phs, "conn", Revienta())

    texto = phs.build_platform_health_text()

    assert "No se ha podido comprobar" in texto
    assert "Nada roto" not in texto, (
        "es exactamente la mentira que hacía inútil esta pantalla"
    )


def test_with_everything_answered_it_still_says_all_clear(clean_db):
    import platform_health_service as phs

    texto = phs.build_platform_health_text()

    assert "Nada roto" in texto
    assert "No se ha podido comprobar" not in texto


def test_a_partial_failure_only_speaks_for_what_it_checked(monkeypatch,
                                                           clean_db):
    import platform_health_service as phs

    monkeypatch.setattr(phs, "fetch_open_incidents", lambda: None)

    texto = phs.build_platform_health_text()

    assert "cobros sin acceso" in texto
    assert "de lo que sí se ha podido comprobar" in texto.lower()


# =========================
# LA REVOCACIÓN MASIVA, A UN SOLO TOQUE
# =========================
# Revoca TODOS los enlaces de TODA la plataforma —sin filtro ni alcance— y
# estaba a un toque, justo encima de «Volver». Un dedo torcido dejaba sin
# entrada a todos los socios que pagan.

def test_the_mass_revoke_asks_first():
    fuente = open("callback_router.py", encoding="utf-8").read()

    pos = fuente.index('if data == "admin_revoke_links":')
    fin = fuente.index('if data == "admin_revoke_links_yes":', pos)
    trozo = fuente[pos:fin]

    assert "admin_revoke_links_yes" in trozo, "tiene que haber un paso de más"
    assert "contar_enlaces_activos" in trozo, (
        "«vas a revocar todos» no da idea de nada; «vas a revocar 412» sí"
    )
    assert "SELECT invite_link" not in trozo, (
        "la confirmación no puede revocar nada por sí misma"
    )
    assert "revoke_link(" not in trozo


def test_the_revoke_leaves_a_record():
    fuente = open("callback_router.py", encoding="utf-8").read()

    pos = fuente.index('if data == "admin_revoke_links_yes":')
    trozo = fuente[pos:pos + 900]

    assert "log_event" in trozo, (
        "sin registro no se sabe quién dejó fuera a todos los socios"
    )


def test_a_half_done_revoke_does_not_read_as_complete():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "no se pudieron revocar y siguen" in fuente, (
        "se contaban solo los que salían bien, así que los que quedaban vivos "
        "seguían dando entrada sin que nadie lo supiera"
    )


def test_counting_links_never_breaks_the_screen(monkeypatch):
    import callback_router as cr

    class Revienta:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr(cr, "conn", Revienta())

    assert cr.contar_enlaces_activos() == 0


# =========================
# CIFRAS TOPADAS PRESENTADAS COMO TOTALES
# =========================
# El resumen contaba `len()` de listas con LIMIT 10 y LIMIT 20. Con 40
# propietarios esperando, decía «pendientes: 10» y el operador se lo creía.

def test_the_owner_summary_counts_instead_of_measuring(clean_db):
    import admin_commercial_callbacks as acc

    with clean_db.conn.cursor() as cur:
        for i in range(14):
            cur.execute(
                "INSERT INTO commercial_requests (user_id, status, request_type) "
                "VALUES (%s, 'pending', 'shared_bot_space')",
                (90000 + i,),
            )

    assert acc.contar_solicitudes(["pending"]) == 14, (
        "la lista está topada a 10; el total no"
    )
    assert len(acc.fetch_pending_commercial_requests()) == 10, (
        "y la lista sigue topada a propósito: son dos preguntas distintas"
    )


def test_a_number_that_could_not_be_read_is_not_a_zero(monkeypatch):
    import admin_commercial_callbacks as acc

    class Revienta:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr(acc, "conn", Revienta())

    assert acc.contar_solicitudes(["pending"]) is None
    assert acc.numero_o_interrogacion(None) == "?"
    assert acc.numero_o_interrogacion(0) == "0", (
        "cero de verdad y «no se sabe» no se pueden leer igual"
    )


# =========================
# PANTALLAS SIN SALIDA
# =========================

def test_the_operator_screens_have_a_way_out():
    from admin_menu_catalog import build_admin_screen_keyboard

    teclado = build_admin_screen_keyboard("admin_health")

    callbacks = [b.callback_data for f in teclado.inline_keyboard for b in f]

    assert "admin_health" in callbacks, "recargar es lo que hace falta ahí"
    assert "admin_back_main" in callbacks


def test_a_screen_without_a_refresh_still_has_a_back():
    from admin_menu_catalog import build_admin_screen_keyboard

    teclado = build_admin_screen_keyboard()

    callbacks = [b.callback_data for f in teclado.inline_keyboard for b in f]

    assert callbacks == ["admin_back_main"]


def test_health_and_income_are_no_longer_dead_ends():
    fuente = open("callback_router.py", encoding="utf-8").read()

    for callback in ("admin_health", "admin_income"):

        pos = fuente.index(f'if data == "{callback}":')
        trozo = fuente[pos:pos + 2600]

        assert "build_admin_screen_keyboard" in trozo, callback
