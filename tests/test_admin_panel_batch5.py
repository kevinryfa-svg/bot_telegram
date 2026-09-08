"""
Quinta tanda del panel: listas que mentían y dinero cobrado sin entregar.

Tres cosas:

  1. Los logs por categoría filtraban DESPUÉS del límite, así que una pantalla
     podía decir «sin actividad» con la tabla llena.
  2. Media docena de listas pintaban las primeras N y no lo decían.
  3. Las incidencias de cobro —gente que PAGÓ y no tiene acceso— solo se podían
     tocar desde el mensaje que las anunció. Perdido el mensaje, perdida la
     incidencia.
"""

import pytest

from admin_menu_catalog import nota_de_recorte
import audit_log_service as als
import incident_repair_service as irs


# =========================
# 1. EL FILTRO IBA DESPUÉS DEL LÍMITE
# =========================

@pytest.fixture
def muchos_eventos(clean_db):
    """
    60 eventos de pagos y 3 de usuarios, los de usuarios los más viejos.

    Con el filtro después del LIMIT 50, «Logs de usuarios» contestaba «sin
    actividad»: los tres estaban fuera de los últimos cincuenta.
    """

    db = clean_db

    with db.conn.cursor() as cur:

        for n in range(3):
            cur.execute(
                "INSERT INTO audit_logs (event_type, category, severity, message, "
                "created_at) VALUES ('entro', 'user', 'info', %s, "
                "NOW() - INTERVAL '10 days')",
                (f"usuario {n}",)
            )

        for n in range(60):
            cur.execute(
                "INSERT INTO audit_logs (event_type, category, severity, message, "
                "created_at) VALUES ('pago', 'payment', 'info', %s, NOW())",
                (f"pago {n}",)
            )

    return db


def test_a_category_screen_no_longer_says_nothing_when_there_is_something(muchos_eventos):
    filas = als.list_recent_events(limit=50, category="user")

    assert len(filas) == 3, (
        "los tres eventos de usuario estaban fuera de los últimos 50 de todo"
    )

    assert all(fila[2] == "user" for fila in filas)


def test_without_a_category_it_behaves_as_before(muchos_eventos):
    filas = als.list_recent_events(limit=50)

    assert len(filas) == 50
    assert filas[0][2] == "payment", "lo más reciente primero, como siempre"


def test_the_count_is_of_the_same_thing_the_list_shows(muchos_eventos):
    assert als.contar_eventos(category="user") == 3
    assert als.contar_eventos(category="payment") == 60
    assert als.contar_eventos() == 63


def test_a_count_that_fails_says_none_and_not_zero(monkeypatch):
    """Un cero inventado se lee como «no hay nada», que es lo contrario."""

    class Roto:
        def cursor(self):
            raise RuntimeError("sin base de datos")

    monkeypatch.setattr(als, "conn", Roto())

    assert als.contar_eventos() is None


def test_a_group_scope_and_a_category_work_together(muchos_eventos):
    with muchos_eventos.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (66, 'Log', -1066, TRUE)"
        )
        cur.execute(
            "INSERT INTO audit_logs (event_type, category, severity, message, "
            "group_id) VALUES ('entro', 'user', 'info', 'del grupo 66', 66)"
        )

    filas = als.list_recent_events(limit=50, group_ids=[66], category="user")

    assert len(filas) == 1
    assert filas[0][8] == "del grupo 66"


# =========================
# 2. «SE ENSEÑAN N DE M», UNA SOLA VEZ
# =========================

def test_the_note_appears_only_when_something_is_missing():
    assert nota_de_recorte(30, 50)
    assert nota_de_recorte(50, 50) == ""
    assert nota_de_recorte(51, 50) == ""


def test_the_note_says_both_numbers():
    linea = nota_de_recorte(30, 340)

    assert "30" in linea and "340" in linea


def test_the_note_can_carry_the_way_out():
    linea = nota_de_recorte(30, 50, "Filtra por categoría.")

    assert "Filtra por categoría." in linea


def test_an_unknown_total_is_said_and_not_invented():
    linea = nota_de_recorte(30, None)

    assert "30" in linea
    assert "no se ha podido contar" in linea.lower()


def test_the_note_never_explodes_on_rubbish():
    assert nota_de_recorte(None, None) == ""
    assert nota_de_recorte("x", 5) == ""
    assert nota_de_recorte(5, "x") == ""


def test_the_log_screen_uses_it_and_the_two_limits_have_names():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "MAXIMO_EVENTOS_DE_LOG = 50" in fuente
    assert "MAXIMO_EVENTOS_EN_PANTALLA_DE_LOG = 30" in fuente
    assert "rows[:MAXIMO_EVENTOS_EN_PANTALLA_DE_LOG]" in fuente
    assert "category=category_filter" in fuente, (
        "el filtro tiene que ir en la consulta, no después"
    )


def test_the_backup_screens_use_it_too():
    fuente = open("owner_backup_callbacks.py", encoding="utf-8").read()

    assert fuente.count("nota_de_recorte(") == 2
    assert "def contar_backup_errores" in fuente
    assert "def contar_backup_mensajes" in fuente


# =========================
# 3. DINERO COBRADO SIN ENTREGAR
# =========================

@pytest.fixture
def incidencias(clean_db):
    """
    Tres incidencias abiertas y una resuelta, en dos comunidades.

      #1  la más VIEJA: alguien lleva 5 días pagado y sin acceso
      #2  de ayer
      #3  vetado — a este no se le ofrece conceder acceso, se le devuelve
      #4  resuelta: no sale
    """

    db = clean_db

    with db.conn.cursor() as cur:

        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) VALUES "
            "(55, 'VIP Cobro', -1055, TRUE), (56, 'Otra', -1056, TRUE)"
        )

        cur.execute("""
            INSERT INTO payment_incidents
                (incident_key, kind, user_id, group_id, provider, detail,
                 created_at, resolved_at)
            VALUES
                ('k1', 'plan_not_found', 5501, 55, 'stripe', 'sin plan',
                 NOW() - INTERVAL '5 days', NULL),
                ('k2', 'storage_failed', 5502, 56, 'paypal', NULL,
                 NOW() - INTERVAL '1 day', NULL),
                ('k3', 'banned_buyer', 5503, 55, 'stripe', NULL,
                 NOW() - INTERVAL '2 hours', NULL),
                ('k4', 'plan_not_found', 5504, 55, 'stripe', NULL,
                 NOW() - INTERVAL '9 days', NOW())
        """)

    return db


def test_the_open_incidents_can_finally_be_listed(incidencias):
    filas = irs.listar_incidencias_abiertas()

    assert len(filas) == 3, "la resuelta no sale"

    assert {f[2] for f in filas} == {5501, 5502, 5503}


def test_the_oldest_comes_first_because_that_is_the_urgent_one(incidencias):
    """Al contrario que el resto del panel: aquí urge quien lleva más esperando."""

    filas = irs.listar_incidencias_abiertas()

    assert filas[0][2] == 5501


def test_the_screen_says_what_each_one_is(incidencias):
    texto = irs.build_open_incidents_text()

    assert "VIP Cobro" in texto
    assert "5501" in texto
    assert "PAGÓ" in texto, "hay que decir que el dinero ya está cobrado"
    assert "5504" not in texto, "la resuelta no se lista"


def test_the_age_is_in_words_and_not_a_database_timestamp(incidencias):
    texto = irs.build_open_incidents_text()

    assert "día(s)" in texto or " h" in texto
    assert "00:00:00" not in texto


def test_every_incident_gets_its_own_button(incidencias):
    """Era lo único que faltaba: llegar a ellas sin el mensaje original."""

    teclado = irs.build_open_incidents_keyboard()

    destinos = [
        b.callback_data
        for fila in teclado.inline_keyboard
        for b in fila
    ]

    assert any(d.startswith("incident_fix_") for d in destinos)
    assert any(d.startswith("incident_refund_") for d in destinos)


def test_a_banned_buyer_is_offered_the_refund_and_not_the_access(incidencias):
    """
    Conceder acceso a quien está vetado sería saltarse la decisión de alguien.
    La misma regla que en el aviso, con LA misma constante.
    """

    teclado = irs.build_open_incidents_keyboard()

    por_boton = {
        b.text: b.callback_data
        for fila in teclado.inline_keyboard
        for b in fila
    }

    vetado = [c for t, c in por_boton.items() if "5503" in t]

    assert vetado == ["incident_refund_3"] or vetado and vetado[0].startswith(
        "incident_refund_"
    )


def test_no_incidents_is_said_as_good_news(clean_db):
    texto = irs.build_open_incidents_text()

    assert "Ninguna abierta" in texto
    assert "nadie ha pagado sin recibir su acceso" in texto


def test_a_failure_to_read_never_shows_a_reassuring_zero(clean_db, monkeypatch):
    monkeypatch.setattr(irs, "contar_incidencias_abiertas", lambda: None)
    monkeypatch.setattr(irs, "listar_incidencias_abiertas", lambda limit=20: [])

    texto = irs.build_open_incidents_text()

    assert "No se ha podido comprobar" in texto
    assert "Ninguna abierta" not in texto, (
        "decir que no hay ninguna cuando no se sabe es la peor de las mentiras "
        "de esta pantalla"
    )


def test_the_panel_has_a_button_that_reaches_it():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert 'callback_data="admin_incidents"' in fuente
    assert 'if data == "admin_incidents":' in fuente


def test_the_eleven_exits_of_the_flow_are_no_longer_dead_ends():
    """
    El operador acababa de mover dinero de verdad y se quedaba sin un botón:
    ni ver si quedan más incidencias, ni volver al panel.
    """

    import re

    fuente = open("callback_router.py", encoding="utf-8").read()

    inicio = fuente.index('if data.startswith("incident_refund_go_"):')
    tramo = fuente[inicio:inicio + 20000]
    tramo = tramo[:tramo.index('if data == "admin_incidents"')] \
        if 'if data == "admin_incidents"' in tramo else tramo

    sin_botones = []

    for m in re.finditer(r'await query\.message\.reply_text\(', tramo):
        i = m.end() - 1
        profundidad = 0
        while i < len(tramo):
            if tramo[i] == "(":
                profundidad += 1
            elif tramo[i] == ")":
                profundidad -= 1
                if profundidad == 0:
                    break
            i += 1

        llamada = tramo[m.start():i + 1]

        if "reply_markup" not in llamada:
            sin_botones.append(llamada.replace("\n", " ")[:80])

    assert sin_botones == [], (
        "estas salidas siguen dejando al operador sin nada:\n  "
        + "\n  ".join(sin_botones)
    )


# =========================
# LA PUESTA A PUNTO, VISIBLE
# =========================

def test_an_armed_task_is_announced_with_the_alarm_it_deserves(monkeypatch):
    """Armada significa que se repite en CADA despliegue, y nadie lo veía."""

    monkeypatch.setenv("BOOTSTRAP_TASKS", "precio_comunidad")

    from bootstrap_panel_service import build_bootstrap_panel_text

    texto = build_bootstrap_panel_text()

    assert "ARMADA AHORA MISMO" in texto
    assert "precio_comunidad" in texto
    assert "CADA despliegue" in texto
    assert "quitar la variable" in texto, "hay que decir cómo desarmarla"


def test_nothing_armed_is_said_as_the_normal_state(monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_TASKS", raising=False)

    from bootstrap_panel_service import build_bootstrap_panel_text

    texto = build_bootstrap_panel_text()

    assert "No hay ninguna armada" in texto
    assert "ARMADA AHORA MISMO" not in texto


def test_the_last_run_is_remembered_and_shown(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_TASKS", "no_existe_esta_tarea")

    import bootstrap_tasks
    from bootstrap_panel_service import build_bootstrap_panel_text

    bootstrap_tasks.run_bootstrap_tasks()

    texto = build_bootstrap_panel_text()

    assert "no existe esa tarea" in texto, (
        "lo que contestó la última vez se lo llevaba el log del contenedor"
    )


def test_only_the_read_only_task_can_be_launched_from_the_panel():
    """Un botón que reescribe precios de producción a un toque no debe existir."""

    from bootstrap_panel_service import TAREAS_SOLO_DE_LECTURA

    assert TAREAS_SOLO_DE_LECTURA == ("listar_planes",)

    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "admin_bootstrap_list_plans" in fuente

    for peligrosa in ("precio_comunidad", "cobrar_por_stripe", "renombrar_plan",
                      "desactivar_plan", "crear_planes"):

        assert f'callback_data="admin_bootstrap_{peligrosa}"' not in fuente


def test_launching_a_task_and_running_them_all_share_one_definition():
    fuente = open("bootstrap_tasks.py", encoding="utf-8").read()

    assert "def ejecutar_una_tarea(" in fuente
    assert "lineas.append(ejecutar_una_tarea(nombre))" in fuente
