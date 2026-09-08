"""
Cuarta tanda del panel: lo que trabajaba a oscuras y lo que no llevaba a nada.

Cuatro cosas distintas, un mismo defecto de fondo — el panel no contaba lo que
estaba pasando:

  1. Dos recuperadores escribiéndole a clientes de verdad sin una sola pantalla
     donde ver a cuántos y con qué resultado (ni si estaban encendidos).
  2. Un creador de planes que contestaba «los euros son números» a «9.99».
  3. Una lista de eventos que enseñaba 30 de 50 y cortaba el último a mitad de
     palabra sin decirlo.
  4. Dos entradas de menú duplicadas y una tercera inalcanzable.
"""

import pytest

import recovery_report_service as rr


# =========================
# 1. LA RECUPERACIÓN, VISIBLE
# =========================

@pytest.fixture
def recuperacion(clean_db, monkeypatch):
    """
    A tres personas se les escribió hace 5 días. Dos pagaron DESPUÉS.

      7701  carrito abandonado  → pagó 20 EUR después   (rescate)
      7702  carrito abandonado  → no pagó
      7703  interesado          → pagó 15 EUR después   (rescate)
      7704  interesado          → pagó ANTES de que se le escribiera
    """

    db = clean_db

    with db.conn.cursor() as cur:

        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (77, 'Recupera', -1077, TRUE)"
        )

        cur.execute(
            "INSERT INTO abandoned_checkout_reminders "
            "(transaction_id, user_id, group_id, sent_at) VALUES "
            "(7001, 7701, 77, NOW() - INTERVAL '5 days'), "
            "(7002, 7702, 77, NOW() - INTERVAL '5 days')"
        )

        cur.execute(
            "INSERT INTO interest_followups (user_id, group_id, sent_at) VALUES "
            "(7703, 77, NOW() - INTERVAL '5 days'), "
            "(7704, 77, NOW() - INTERVAL '5 days')"
        )

        cur.execute(
            "INSERT INTO payments "
            "(user_id, group_id, amount, currency, status, payment_date) VALUES "
            "(7701, 77, 2000, 'EUR', 'paid', NOW() - INTERVAL '4 days'), "
            "(7703, 77, 1500, 'EUR', 'paid', NOW() - INTERVAL '1 day'), "
            "(7704, 77, 9900, 'EUR', 'paid', NOW() - INTERVAL '20 days')"
        )

    monkeypatch.setattr("abandoned_checkout_service.ABANDONED_ENABLED", True)
    monkeypatch.setattr("interest_followup_service.INTEREST_ENABLED", True)

    return db


def test_the_screen_says_how_many_were_written_and_who_paid_after(recuperacion):
    texto = rr.build_recovery_report_text()

    assert "2 escritos · 1 pagaron después" in texto, (
        "de los dos carritos escritos, uno pagó después"
    )
    assert texto.count("2 escritos · 1 pagaron después") == 2, (
        "las dos máquinas —carritos e interesados— tienen la misma cuenta"
    )


def test_a_payment_from_before_the_message_is_not_a_rescue(recuperacion):
    """7704 pagó VEINTE días antes de que se le escribiera. No cuenta."""

    texto = rr.build_recovery_report_text()

    assert "99" not in texto, (
        "sumar un pago anterior al aviso sería inventarse el resultado"
    )


def test_the_money_recovered_is_shown_together(recuperacion):
    texto = rr.build_recovery_report_text()

    # 2000 + 1500 céntimos, en el formato de informe.
    assert "35.00 EUR" in texto
    assert "2 persona(s)" in texto


def test_the_screen_does_not_claim_the_message_caused_the_sale(recuperacion):
    texto = rr.build_recovery_report_text()

    assert "No prueba que fuera por el mensaje" in texto, (
        "«pagaron después» es una correlación y hay que decirlo"
    )


def test_a_machine_that_is_off_says_so_and_says_who_is_waiting(recuperacion, monkeypatch):
    """Apagado, el recuperador no avisa de que está apagado. La pantalla sí."""

    monkeypatch.setattr("abandoned_checkout_service.ABANDONED_ENABLED", False)
    monkeypatch.setattr(
        rr, "_esperando_carritos", lambda: 72
    )

    texto = rr.build_recovery_report_text()

    assert "APAGADO" in texto
    assert "72 — y no se les va a escribir, está apagado" in texto
    assert "ABANDONED_ENABLED" in texto, "hay que decir cómo se enciende"


def test_when_everything_is_on_there_is_no_alarm(recuperacion):
    texto = rr.build_recovery_report_text()

    assert "APAGADO" not in texto
    assert "encendido" in texto


def test_two_currencies_are_never_added_together(recuperacion):
    """La mentira de dinero que ya se corrigió en Ingresos no vuelve aquí."""

    with recuperacion.conn.cursor() as cur:
        cur.execute(
            "UPDATE payments SET currency='USD' WHERE user_id=7703"
        )

    texto = rr.build_recovery_report_text()

    assert "35.00" not in texto, "20 EUR y 15 USD no son 35 de nada"


def test_a_broken_count_says_so_instead_of_showing_a_zero(clean_db, monkeypatch):
    monkeypatch.setattr(
        rr, "_cuenta_de_una_tabla", lambda tabla, dias: None
    )

    texto = rr.build_recovery_report_text()

    assert "No se ha podido comprobar" in texto
    assert "0 escritos" not in texto, (
        "un cero inventado es peor que decir que no se sabe"
    )


def test_the_report_never_explodes(clean_db, monkeypatch):
    monkeypatch.setattr(
        rr, "_esperando_carritos", lambda: 1 / 0
    )

    # _esperando_carritos ya atrapa lo suyo; esto comprueba que la pantalla
    # entera se puede pedir sin miedo.
    try:
        texto = rr.build_recovery_report_text()
    except ZeroDivisionError:
        pytest.fail("la pantalla del panel no puede reventar")

    assert "Recuperación de ventas a medias" in texto


def test_the_panel_has_a_button_that_reaches_it():
    """Una pantalla sin botón es una pantalla que no existe."""

    fuente = open("callback_router.py", encoding="utf-8").read()

    assert 'callback_data="admin_recovery"' in fuente
    assert 'if data == "admin_recovery":' in fuente


# =========================
# 2. UN PLAN DE 9,99
# =========================

def test_a_price_with_cents_gets_a_true_answer_not_a_lie(clean_db, monkeypatch):
    """«9.99 no es un número» era mentira, y dejaba sin saber qué fallaba."""

    import bootstrap_tasks

    monkeypatch.setenv("BOOTSTRAP_PLAN_NEW", "g1:30:9.99:Mensual")

    salida = bootstrap_tasks.tarea_crear_planes()

    assert "no es un precio" not in salida
    assert "son números" not in salida
    assert "céntimos" in salida, "hay que decir cuál es el problema de verdad"
    assert "9 o 10" in salida, "y cuál es la salida"


def test_a_comma_in_the_price_is_explained_instead_of_confusing(clean_db, monkeypatch):
    """
    En España el precio se escribe con coma — y aquí la coma separa PLANES, así
    que «9,99» parte la entrada en dos y salían dos quejas de sintaxis sin una
    pista de por qué. Ahora el error dice cuál es la regla.
    """

    import bootstrap_tasks

    monkeypatch.setenv("BOOTSTRAP_PLAN_NEW", "g1:30:9,99:Mensual")

    salida = bootstrap_tasks.tarea_crear_planes()

    assert "el precio se escribe con punto: 9.99, no 9,99" in salida


def test_something_that_is_not_a_price_is_still_rejected(clean_db, monkeypatch):
    import bootstrap_tasks

    monkeypatch.setenv("BOOTSTRAP_PLAN_NEW", "g1:30:gratis:Mensual")

    salida = bootstrap_tasks.tarea_crear_planes()

    assert "no es un precio" in salida


# =========================
# 3. CUÁNTOS DE CUÁNTOS
# =========================

def _evento(n, mensaje="algo"):
    return (n, "2026-01-01", "tipo", "warning", 1, 1, -100, mensaje, False)


def test_the_event_list_says_how_many_of_how_many():
    from admin_beta_callbacks import format_beta_monitor_events_text

    texto = format_beta_monitor_events_text("T", [_evento(n) for n in range(50)])

    assert "Se enseñan 30 de 50" in texto


def test_nothing_is_hidden_when_everything_fits():
    from admin_beta_callbacks import format_beta_monitor_events_text

    texto = format_beta_monitor_events_text("T", [_evento(n) for n in range(5)])

    assert "Se enseñan" not in texto, "no hay nota que dar si están todos"


def test_an_event_is_never_cut_in_half():
    """El corte a 3900 caracteres partía el último evento a mitad de palabra."""

    from admin_beta_callbacks import format_beta_monitor_events_text

    largo = "x" * 600

    texto = format_beta_monitor_events_text(
        "T", [_evento(n, largo) for n in range(30)]
    )

    assert texto.count(largo) * 600 > 0
    # Todo evento pintado está pintado ENTERO: tantas fechas como detalles.
    assert texto.count("Detalle:") == texto.count("Fecha:")
    assert "no cabían más" in texto


def test_the_screen_still_fits_in_a_telegram_message():
    from admin_beta_callbacks import format_beta_monitor_events_text

    texto = format_beta_monitor_events_text(
        "T", [_evento(n, "y" * 600) for n in range(30)]
    )

    assert len(texto) <= 4096


# =========================
# 4. MENÚS QUE NO LLEVABAN A NINGUNA PARTE
# =========================

def test_the_security_summary_goes_through_the_real_screen():
    """
    Era una copia letra por letra que NO guardaba la comunidad elegida: el
    siguiente botón del panel podía acabar operando sobre otra.
    """

    fuente = open("owner_panel_callbacks.py", encoding="utf-8").read()

    assert fuente.count('if data == "owner_panel_security_info":') == 1
    assert 'data = "owner_panel_security"' in fuente

    # Y el atajo sigue existiendo: los mensajes ya enviados lo llevan.
    router = open("callback_router.py", encoding="utf-8").read()
    assert 'callback_data="owner_panel_security_info"' in router


def test_the_unreachable_info_screen_is_gone():
    """Ningún teclado lo pintaba, y otra rama lo atrapaba antes que la suya."""

    import subprocess

    salida = subprocess.run(
        ["grep", "-rn", "owner_panel_access_type_info", "--include=*.py", "."],
        capture_output=True, text=True
    ).stdout

    vivas = [
        l for l in salida.splitlines()
        if l.strip() and "#" not in l.split(":", 2)[-1].split("owner_panel")[0]
    ]

    assert not [l for l in vivas if "callback_data" in l or "if data" in l], (
        "no puede quedar despacho ni botón de un callback muerto"
    )


def test_the_help_table_that_led_nowhere_is_gone():
    import admin_menu_catalog

    assert not hasattr(admin_menu_catalog, "ADMIN_HELP_CONTEXT_BY_CALLBACK")
    assert not hasattr(admin_menu_catalog, "get_help_context_for_admin_callback")


def test_the_help_that_does_exist_still_works():
    """Borrar la tabla muerta no puede tocar la ayuda de verdad."""

    from callback_router import build_admin_context_help_text

    texto = build_admin_context_help_text("global_panel")

    assert "todavía no está configurada" not in texto
