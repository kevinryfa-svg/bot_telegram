"""
La salud de TODAS las comunidades en una pantalla, para la plataforma.

Cada avería avisa a su propietario, y ahí está el problema: depende de que
ese propietario lea, entienda y actúe. Una comunidad con el bot degradado
lleva semanas sin vender y nadie de la plataforma lo sabe.

Las tres reglas: ordenado por lo que cuesta dinero, con el id delante para
poder actuar, y silencio cuando no hay nada roto — una pantalla de salud que
siempre enseña algo enseña a ignorarla.
"""

import pytest

import platform_health_service as phs


@pytest.fixture
def plataforma(clean_db):
    """Cuatro comunidades, cada una con su avería (y una sana)."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM group_delivery_health WHERE group_id IN (71,72,73,74,75)")
        cur.execute("DELETE FROM payment_incidents WHERE group_id IN (71,72,73,74,75)")
        cur.execute("DELETE FROM audit_logs WHERE group_id IN (71,72,73,74,75)")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, is_free_group) VALUES "
            "(71, 'Sin entrega', -1071, TRUE, TRUE, FALSE), "
            "(72, 'Con incidencias', -1072, TRUE, TRUE, FALSE), "
            "(73, 'Sin planes', -1073, TRUE, TRUE, FALSE), "
            "(74, 'Cobros fallando', -1074, TRUE, TRUE, FALSE), "
            "(75, 'Sana', -1075, TRUE, TRUE, FALSE)"
        )

        # Todas menos la 73 tienen plan usable.
        for gid in (71, 72, 74, 75):
            cur.execute(
                "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
                "duration_days, amount, currency, is_active) "
                "VALUES (%s, 'Mensual', %s, %s, 30, 15, 'EUR', TRUE)",
                (gid, f"price_{gid}", f"price_{gid}")
            )

        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver, bot_status, "
            "broken_since) VALUES "
            "(71, FALSE, 'member', NOW() - INTERVAL '9 days'), "
            "(75, TRUE, 'administrator', NULL)"
        )
        cur.execute(
            "INSERT INTO payment_incidents (incident_key, kind, user_id, group_id, created_at) VALUES "
            "('p1', 'plan_not_found', 7201, 72, NOW() - INTERVAL '4 days'), "
            "('p2', 'storage_failed', 7202, 72, NOW() - INTERVAL '1 days'), "
            "('p3', 'plan_not_found', 7501, 75, NOW() - INTERVAL '2 days')"
        )
        cur.execute(
            "UPDATE payment_incidents SET resolved_at = NOW() WHERE incident_key='p3'"
        )

    from audit_log_service import log_event

    for i in range(3):
        log_event(
            "group_subscription_payment_failed",
            category="payment", severity="warning", scope="group",
            group_id=74, actor_user_id=7400 + i,
            message="Cobro fallido.",
        )

    return db


def test_a_community_that_cannot_deliver_is_the_first_thing_shown(plataforma):
    filas = phs.fetch_broken_delivery()

    assert [(f[0], f[2], f[3]) for f in filas] == [(71, 9, 'member')]

    texto = phs.build_platform_health_text()

    assert texto.index("No pueden entregar") < texto.index("Cobros sin acceso"), (
        "lo primero es lo que más cuesta: la comunidad que cobra y no entrega"
    )
    assert "Sin entrega (id 71) — 9 días" in texto


def test_resolved_incidents_do_not_count(plataforma):
    filas = phs.fetch_open_incidents()

    assert [(f[0], f[2]) for f in filas] == [(72, 2)], (
        "la comunidad 75 tiene su incidencia resuelta: ya no está roto"
    )

    texto = phs.build_platform_health_text()
    assert "Con incidencias (id 72) — 2 abiertas, la más vieja hace 4 días" in texto


def test_being_in_the_market_without_a_plan_is_a_broken_shop(plataforma):
    filas = phs.fetch_unsellable_but_visible()

    assert [f[0] for f in filas] == [73]

    texto = phs.build_platform_health_text()
    assert "Sin planes (id 73)" in texto


def test_a_free_community_needs_no_plan(plataforma):
    with plataforma.conn.cursor() as cur:
        cur.execute("UPDATE groups SET is_free_group=TRUE WHERE id=73")

    assert phs.fetch_unsellable_but_visible() == [], (
        "una comunidad gratuita sin planes no está rota: es gratuita"
    )


def test_the_failed_charge_streak_uses_the_same_threshold_as_the_alerts(plataforma):
    filas = phs.fetch_failed_charge_streaks()

    assert [(f[0], f[2]) for f in filas] == [(74, 3)]

    texto = phs.build_platform_health_text()
    assert "Cobros fallando (id 74) — 3 fallidos" in texto


def test_a_deleted_community_is_not_listed(plataforma):
    """Los registros sobreviven al borrado: listar lo que ya no existe es
    ruido que nadie puede arreglar."""

    with plataforma.conn.cursor() as cur:
        cur.execute("UPDATE groups SET is_active=FALSE WHERE id=74")

    assert phs.fetch_failed_charge_streaks() == []


def test_the_cap_says_how_many_it_is_hiding(plataforma, monkeypatch):
    monkeypatch.setattr(phs, "HEALTH_LIST_LIMIT", 1)

    with plataforma.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible) VALUES "
            "(76, 'Sin planes 2', -1076, TRUE, TRUE), "
            "(77, 'Sin planes 3', -1077, TRUE, TRUE)"
        )

    texto = phs.build_platform_health_text()

    assert "…y 2 más" in texto, (
        "un tope que no se dice se lee como 'esto es todo'"
    )


def test_when_nothing_is_broken_it_says_so_in_one_line(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute("DELETE FROM payment_incidents")
        # audit_logs no se vacía entre pruebas y sobrevive al borrado de la
        # comunidad: se limpia lo que dejó la prueba anterior.
        cur.execute(
            "DELETE FROM audit_logs "
            "WHERE event_type='group_subscription_payment_failed'"
        )
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible) VALUES (78, 'Sola y sana', -1078, TRUE, FALSE)"
        )

    texto = phs.build_platform_health_text()

    assert "✅ Nada roto" in texto
    assert "No pueden entregar" not in texto, (
        "una pantalla de salud que siempre enseña algo enseña a ignorarla"
    )


def test_the_panel_is_platform_only():
    router = open("callback_router.py", encoding="utf-8").read()

    assert 'callback_data="admin_health"' in router

    pos = router.index('if data == "admin_health":')
    trozo = router[pos:pos + 700]

    assert "is_super_admin(user_id)" in trozo, (
        "es la foto de comunidades de OTROS propietarios: solo plataforma"
    )
    assert "build_platform_health_text" in trozo


# =========================
# EL COSTE DE TENER EL PORTAL SIN ACTIVAR
# =========================
# Sin el portal de facturación de Stripe, el aviso de cobro fallido sale
# igual (eso nunca se degrada al silencio) pero SIN el botón que arregla el
# problema en un toque. Ese coste no se veía en ninguna parte.

def registrar_aviso_fallido(group_id, user_id, portal_ok):
    from audit_log_service import log_event

    log_event(
        "group_subscription_payment_failed",
        category="payment", severity="warning", scope="group",
        group_id=group_id, actor_user_id=user_id, target_user_id=user_id,
        message="Cobro de renovación fallido; Stripe reintentará.",
        metadata={"portal_ok": portal_ok, "invoice_id": f"in_{user_id}"},
    )


def test_the_notices_without_a_card_button_are_counted(plataforma):
    registrar_aviso_fallido(75, 7501, False)
    registrar_aviso_fallido(75, 7502, False)
    registrar_aviso_fallido(75, 7503, True)

    sin_portal, total = phs.count_failed_notices_without_portal()

    assert (sin_portal, total) == (2, 3)

    texto = phs.build_platform_health_text()

    assert "Portal de facturación sin activar (2 de 3 avisos)" in texto
    assert "SIN botón para cambiar la tarjeta" in texto
    assert "se activa una vez" in texto.lower()


def test_old_notices_without_the_flag_are_not_counted(plataforma):
    """Los avisos anteriores a medir esto no llevan la marca: no se inventan."""

    from audit_log_service import log_event

    log_event(
        "group_subscription_payment_failed",
        category="payment", severity="warning", scope="group",
        group_id=75, actor_user_id=7599, target_user_id=7599,
        message="Cobro fallido antiguo.",
        metadata={"invoice_id": "in_viejo"},
    )

    assert phs.count_failed_notices_without_portal() == (0, 0), (
        "sin la marca no se sabe si hubo botón: contarlo como fallo sería "
        "inventarse un problema"
    )


def test_with_the_portal_active_the_section_disappears(plataforma):
    registrar_aviso_fallido(75, 7504, True)
    registrar_aviso_fallido(75, 7505, True)

    texto = phs.build_platform_health_text()

    assert "Portal de facturación sin activar" not in texto


def test_the_failure_notice_records_whether_it_had_a_button():
    """El registro tiene que ir DESPUÉS de saber si había portal."""

    fuente = open("group_subscription_service.py", encoding="utf-8").read()

    pos = fuente.index("def process_group_subscription_invoice_failed")
    trozo = fuente[pos:pos + 3000]

    assert '"portal_ok": bool(url_portal)' in trozo
    assert trozo.index("url_portal = crear_url_portal_pago") < \
        trozo.index('"group_subscription_payment_failed"'), (
        "si el registro va antes, el dato del botón no se puede anotar"
    )
