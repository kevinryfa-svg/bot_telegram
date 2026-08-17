"""
La ficha de un comprador, para poder atenderle sin abrir la base de datos.

El buscador contestaba esto:

    👤 Usuario 123456
    Grupo: VIP Fitness
    Expira: 2026-09-14 08:31:22.184000

Las preguntas que llegan a soporte son «pagué y no entro», «me habéis
cobrado dos veces», «cancelé y me seguís cobrando», y ninguna se responde
con una fecha en formato de base de datos.

Las dos reglas: solo datos propios (una pantalla de soporte que depende de
una API ajena falla justo cuando hay un cliente esperando) y el mismo
alcance que ya tenía el buscador — cambia lo que se enseña, no quién puede
verlo.
"""

import pytest

import support_lookup_service as sls


@pytest.fixture
def comprador(clean_db):
    """Alguien con dos comunidades: una pagando y otra caducada y vetada."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM payment_incidents WHERE user_id=6501")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) VALUES "
            "(65, 'VIP Bueno', -1065, TRUE), (66, 'VIP Malo', -1066, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) VALUES "
            "(6501, 65, NOW() + INTERVAL '15 days', TRUE, 'sub_65'), "
            "(6501, 66, NOW() - INTERVAL '20 days', FALSE, NULL)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan, payment_date) VALUES "
            "(6501, 65, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '45 days'), "
            "(6501, 65, 1500, 'EUR', 'paid', 'Mensual', NOW() - INTERVAL '15 days'), "
            "(6501, 66, 2000, 'EUR', 'refunded', 'Mensual', NOW() - INTERVAL '60 days')"
        )
        cur.execute(
            "INSERT INTO banned_users (user_id, group_id) VALUES (6501, 66)"
        )

    return db


def test_the_dossier_answers_the_questions_support_actually_gets(comprador):
    texto = sls.build_member_dossier(6501)

    assert "👤 Usuario 6501" in texto

    # Estado en formato humano, no un timestamp de base de datos.
    assert "Acceso activo hasta el" in texto
    assert ".000" not in texto and "00:00:00" not in texto

    # De quién es la renovación: es la pregunta de "cancelé y me cobráis".
    assert "Renovación automática: sí (Stripe)" in texto
    assert "Renovación automática: no" in texto

    # Lo que ha pagado: la pregunta de "me habéis cobrado dos veces".
    assert "Ha pagado 2 veces · 30.00 EUR en total" in texto

    # Y el veto, que explica por qué no entra.
    assert "⛔ VETADO en esta comunidad" in texto


def test_a_refund_is_not_a_payment(comprador):
    texto = sls.build_member_dossier(6501)

    # En la comunidad 66 su único movimiento fue una devolución.
    trozo = texto[texto.index("VIP Malo"):]

    assert "Sin pagos registrados" in trozo, (
        "una devolución no es dinero cobrado: contarla llevaría a soporte a "
        "buscar un pago que no existe"
    )


def test_open_incidents_are_shown_with_their_id(comprador):
    with comprador.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_incidents (incident_key, kind, user_id, group_id) "
            "VALUES ('sup1', 'plan_not_found', 6501, 65) RETURNING id"
        )
        incidencia_id = cur.fetchone()[0]

    texto = sls.build_member_dossier(6501)

    assert "incidencia(s) de cobro ABIERTA(S)" in texto
    assert f"#{incidencia_id}" in texto, (
        "el id hace falta: el aviso de incidencia ya trae botón para resolverla"
    )


def test_a_resolved_incident_is_not_a_problem_anymore(comprador):
    with comprador.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_incidents (incident_key, kind, user_id, group_id, resolved_at) "
            "VALUES ('sup2', 'plan_not_found', 6501, 65, NOW())"
        )

    texto = sls.build_member_dossier(6501)

    assert "ABIERTA" not in texto


def test_scope_is_respected(comprador):
    texto = sls.build_member_dossier(6501, group_ids=[65])

    assert "VIP Bueno" in texto
    assert "VIP Malo" not in texto, (
        "un administrador de una comunidad no ve la de otro"
    )


def test_an_unknown_user_gets_told_where_to_look_next(comprador):
    texto = sls.build_member_dossier(999999)

    assert "No tiene acceso registrado" in texto
    assert "incidencias" in texto, (
        "si dice que pagó, el sitio donde mirar es el cobro sin acceso"
    )


def test_permanent_access_is_not_a_missing_date(comprador):
    with comprador.conn.cursor() as cur:
        cur.execute("UPDATE users SET expiration=NULL WHERE user_id=6501 AND group_id=65")

    texto = sls.build_member_dossier(6501)

    assert "Acceso permanente (sin fecha de fin)" in texto


def test_the_search_screen_uses_the_dossier_and_keeps_its_scope():
    fuente = open("code_flow_handler.py", encoding="utf-8").read()

    pos = fuente.index('if context.user_data.get("search_user"):')
    trozo = fuente[pos:pos + 2000]

    assert "build_member_dossier" in trozo
    assert "can_view_users" in trozo and "can_manage_users" in trozo, (
        "el alcance no cambia: cambia lo que se enseña"
    )
    assert 'user_id.lstrip("-").isdigit()' in trozo, (
        "un texto que no es un id no puede reventar la consulta"
    )
