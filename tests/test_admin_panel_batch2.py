"""
Cinco cosas del panel que le costaban dinero o le mentían al que decide.

La peor: el resumen semanal se marcaba como enviado ANTES de enviarse, así que
un envío fallido le quitaba a ese propietario su resumen de esa semana para
siempre.
"""

import pytest


# =========================
# UNA SEMANA QUEMADA POR UN ENVÍO FALLIDO
# =========================
# Marcar antes de enviar es lo correcto contra los duplicados: si el contenedor
# se reinicia a mitad de la tanda, nadie recibe dos. Pero un envío FALLIDO
# quemaba la semana igual, y ese propietario se quedaba sin resumen —no hasta el
# lunes siguiente: para siempre, porque la clave de esa semana ya estaba puesta.

def test_a_failed_send_gives_the_week_back(clean_db):
    import owner_weekly_digest_service as owd

    semana = owd.semana_actual_clave()

    assert owd.mark_digest_sent(7001, 71, semana) is True
    assert owd.mark_digest_sent(7001, 71, semana) is False, (
        "la marca existe justo para que no se manden dos"
    )

    assert owd.liberar_marca_de_digest(7001, 71, semana) is True

    assert owd.mark_digest_sent(7001, 71, semana) is True, (
        "tras liberarla, la próxima ronda tiene que poder intentarlo"
    )


def test_only_a_retryable_failure_releases_it():
    """Si el propietario bloqueó el bot, reintentar cada semana es ruido."""

    fuente = open("owner_weekly_digest_service.py", encoding="utf-8").read()

    pos = fuente.index("no se pudo enviar a")
    trozo = fuente[pos:pos + 900]

    assert "is_unreachable_error" in trozo
    assert "liberar_marca_de_digest" in trozo
    assert "if not is_unreachable_error(e):" in trozo


def test_releasing_never_breaks_the_batch(monkeypatch):
    import owner_weekly_digest_service as owd

    class Revienta:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr(owd, "conn", Revienta())

    assert owd.liberar_marca_de_digest(7001, 71, "2026-W40") is False


# =========================
# EL PANEL AFIRMABA QUE DOS PROTECCIONES ESTABAN ACTIVAS
# =========================
# Dos líneas fijas escritas a pelo. Un propietario con Guardian APAGADO leía
# «activo» en la pantalla que existe justo para saber cómo está protegido.

def test_the_security_screen_reads_the_real_state(clean_db):
    import owner_panel_callbacks as opc

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (72, 'StarsVip', -1072, TRUE)"
        )

    texto = opc.build_owner_security_text(72)

    assert "Guardian: Desactivado" in texto, (
        "sin fila de ajustes, Guardian está apagado: es el valor por defecto"
    )
    assert "Bloqueo de enlaces: Desactivado" in texto


def test_a_group_with_guardian_on_says_so(clean_db):
    import owner_panel_callbacks as opc

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (72, 'StarsVip', -1072, TRUE)"
        )
        cur.execute(
            "INSERT INTO guardian_group_settings (group_id, is_enabled, "
            "anti_links_enabled, action_mode) VALUES (72, TRUE, TRUE, 'delete')"
        )

    texto = opc.build_owner_security_text(72)

    assert "Guardian: Activado" in texto
    assert "Bloqueo de enlaces: Activado (delete)" in texto


def test_the_screen_no_longer_asserts_anything_by_hand():
    fuente = open("owner_panel_callbacks.py", encoding="utf-8").read()

    assert "Anti-intrusos: activo con validación" not in fuente, (
        "eso era una afirmación fija, no un estado leído"
    )
    assert "Links no registrados: se bloquean" not in fuente


# =========================
# «PUEDE DAR ACCESO» SIN DECIR DE CUÁNDO
# =========================
# Lo escribe un trabajo que pasa cada 6 horas y en tandas: un ✅ puede tener
# horas. Sin la hora, la línea se lee como «lo acabo de comprobar».

def test_the_green_tick_says_when_it_was_checked(clean_db):
    import owner_readiness_service as ors

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (73, 'StarsVip', -1073, TRUE)"
        )
        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver, "
            "bot_status, checked_at) VALUES "
            "(73, TRUE, 'administrator', NOW() - INTERVAL '3 hours')"
        )

    ok, texto = ors.check_delivery(73)

    assert ok is True
    assert "comprobado hace 3 h" in texto


def test_the_age_is_written_the_way_people_read_it():
    from datetime import datetime, timedelta

    import owner_readiness_service as ors

    ahora = datetime.now()

    assert "20 min" in ors.antiguedad_de_la_comprobacion(
        ahora - timedelta(minutes=20)
    )
    assert "2 h" in ors.antiguedad_de_la_comprobacion(
        ahora - timedelta(hours=2)
    )
    assert "día" in ors.antiguedad_de_la_comprobacion(
        ahora - timedelta(days=2)
    )
    assert ors.antiguedad_de_la_comprobacion(None) == "", (
        "sin fecha, mejor no decir nada que inventarse una"
    )


# =========================
# EL DIAGNÓSTICO DE COBRO NO TENÍA BOTÓN EN NINGÚN SITIO
# =========================
# Solo corría en el arranque —un print que no lee nadie— y en el vigilante
# horario, que calla mientras el estado no cambie. Es el que caza «el precio no
# existe en Stripe» y «se anuncia un importe y Stripe cobraría otro».

def test_the_charge_diagnostic_has_a_button_now():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert 'callback_data="admin_sale_readiness"' in fuente, (
        "sin botón, solo se podía consultar reiniciando el bot"
    )
    assert 'if data == "admin_sale_readiness":' in fuente

    pos = fuente.index('if data == "admin_sale_readiness":')
    trozo = fuente[pos:pos + 1400]

    assert "describe_sale_readiness" in trozo
    assert "avisar=False" in trozo, (
        "se está mirando a propósito: no hace falta que además llegue un aviso"
    )
    assert "is_super_admin" in trozo


def test_the_warnings_reach_the_admin_too():
    """Si lo único roto era el nombre de la página de pago, nadie se enteraba."""

    fuente = open("sale_readiness_service.py", encoding="utf-8").read()

    assert '"\\n\\n".join(problemas + avisos)' in fuente, (
        "el aviso solo mandaba `problemas`"
    )
    assert "Se puede cobrar, pero hay algo que hace" in fuente, (
        "y con solo avisos no mandaba nada"
    )


def test_the_hourly_watch_does_not_become_spam():
    """El vigilante llama con avisar=False: el aviso nuevo es del arranque."""

    fuente = open("sale_readiness_service.py", encoding="utf-8").read()

    pos = fuente.index("def vigilar_cobro(")
    trozo = fuente[pos:pos + 700]

    assert "describe_sale_readiness(avisar=False)" in trozo
