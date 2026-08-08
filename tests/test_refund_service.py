"""
Una devolución tiene que retirar el acceso.

Faltaba por completo. PAYMENT_STATUS_REFUNDED existía y los proveedores de
cripto detectaban el estado, pero ningún sitio quitaba el acceso, y el webhook de
Stripe no escuchaba charge.refunded ni charge.dispute.created. Alguien podía
pagar, entrar, pedir la devolución y quedarse dentro para siempre; con una
disputa de tarjeta, perdías el dinero y el acceso seguía dado.

Lo delicado de esto es que se ejecuta sobre gente que ya está dentro: expulsar a
quien no toca, o expulsar dos veces porque el proveedor reintenta el webhook, son
fallos peores que el que se está arreglando.
"""

import pytest

import refund_service as rs


# =========================
# CONFIGURACIÓN
# =========================

def test_the_two_reasons_are_distinguished():
    """
    Una devolución y una disputa de tarjeta se le cuentan distinto al cliente:
    una la ha pedido él, la otra la ha abierto su banco.
    """

    assert rs.REFUND_REASON_REFUND != rs.REFUND_REASON_DISPUTE

    devolucion = rs.build_refund_notice("VIP Fitness", rs.REFUND_REASON_REFUND)
    disputa = rs.build_refund_notice("VIP Fitness", rs.REFUND_REASON_DISPUTE)

    assert devolucion != disputa
    assert "VIP Fitness" in devolucion
    assert "VIP Fitness" in disputa


def test_the_notice_explains_and_offers_a_way_back():
    texto = rs.build_refund_notice("VIP Fitness", rs.REFUND_REASON_REFUND)

    assert "acceso" in texto.lower()
    assert "escríbenos" in texto.lower(), (
        "sin salida, quedarse fuera sin explicación acaba en soporte igual"
    )


def test_the_notice_is_translated():
    texto = rs.build_refund_notice(
        "VIP Fitness", rs.REFUND_REASON_REFUND, language="en"
    )

    assert "Refund processed" in texto
    assert "Devolución" not in texto


# =========================
# CONTRA BASE DE DATOS REAL
# =========================

@pytest.fixture
def cliente_dentro(clean_db, monkeypatch):
    """Alguien que pagó, tiene acceso activo y está en el grupo."""

    db = clean_db
    user_id, group_id = 9101, 91

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (%s, 'VIP Fitness', -1091, TRUE)",
            (group_id,),
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (%s, %s, NOW() + INTERVAL '30 days', TRUE)",
            (user_id, group_id),
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, stripe_payment_id, amount, "
            "currency, status) VALUES (%s, %s, 'pi_refund_test', 1500, 'EUR', 'paid')",
            (user_id, group_id),
        )

    expulsados = []
    avisos = []
    revocados = []

    monkeypatch.setattr(rs, "kick_chat_member",
                        lambda token, chat, uid: expulsados.append(uid))
    monkeypatch.setattr(rs, "revoke_and_delete_user_group_links",
                        lambda token, uid, chat: revocados.append(uid))
    monkeypatch.setattr(
        rs, "send_telegram_message",
        lambda token, chat, text, reply_markup=None: (
            avisos.append((chat, text)), {"ok": True}
        )[1],
    )
    monkeypatch.setattr(rs, "notify_super_admins", lambda *a, **k: 0)

    return {
        "db": db,
        "user_id": user_id,
        "group_id": group_id,
        "expulsados": expulsados,
        "avisos": avisos,
        "revocados": revocados,
    }


def acceso_activo(db, user_id, group_id):
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(subscription_active, FALSE) FROM users "
            "WHERE user_id=%s AND group_id=%s",
            (user_id, group_id),
        )
        row = cur.fetchone()

    return bool(row[0]) if row else None


def estado_pago(db, user_id):
    with db.conn.cursor() as cur:
        cur.execute("SELECT status FROM payments WHERE user_id=%s", (user_id,))
        row = cur.fetchone()

    return row[0] if row else None


def test_a_refund_takes_the_access_away(cliente_dentro):
    env = cliente_dentro

    assert acceso_activo(env["db"], env["user_id"], env["group_id"]) is True

    resumen = rs.process_refund(external_payment_id="pi_refund_test")

    assert resumen["found"] is True
    assert resumen["access_revoked"] is True
    assert acceso_activo(env["db"], env["user_id"], env["group_id"]) is False


def test_a_refund_marks_the_payment_instead_of_deleting_history(cliente_dentro):
    env = cliente_dentro

    rs.process_refund(external_payment_id="pi_refund_test")

    assert estado_pago(env["db"], env["user_id"]) == "refunded"


def test_a_refund_kicks_them_and_revokes_their_links(cliente_dentro):
    """
    Los enlaces primero: expulsar sin revocarlos dejaría que volviese a entrar
    con uno que todavía valga.
    """

    env = cliente_dentro

    rs.process_refund(external_payment_id="pi_refund_test")

    assert env["user_id"] in env["expulsados"]
    assert env["user_id"] in env["revocados"]


def test_the_person_is_told_why_they_lost_access(cliente_dentro):
    env = cliente_dentro

    rs.process_refund(external_payment_id="pi_refund_test")

    al_cliente = [t for c, t in env["avisos"] if c == env["user_id"]]

    assert al_cliente, "se le retiró el acceso sin decirle nada"
    assert "Devolución" in al_cliente[0]


def test_processing_the_same_refund_twice_does_nothing_the_second_time(cliente_dentro):
    """
    Los proveedores reintentan los webhooks. Expulsar y avisar dos veces por la
    misma devolución sería peor que el fallo original.
    """

    env = cliente_dentro

    primero = rs.process_refund(external_payment_id="pi_refund_test")
    env["expulsados"].clear()
    env["avisos"].clear()

    segundo = rs.process_refund(external_payment_id="pi_refund_test")

    assert primero["access_revoked"] is True
    assert segundo["already_refunded"] is True
    assert env["expulsados"] == []
    assert env["avisos"] == []


def test_a_dispute_uses_its_own_message(cliente_dentro):
    env = cliente_dentro

    rs.process_refund(
        external_payment_id="pi_refund_test",
        reason=rs.REFUND_REASON_DISPUTE,
    )

    al_cliente = [t for c, t in env["avisos"] if c == env["user_id"]]

    assert al_cliente
    assert "suspendido" in al_cliente[0].lower()


def test_a_partial_refund_leaves_the_access_alone(cliente_dentro):
    """
    Cuando el aviso dice cuánto se devuelve pero no cuánto se cobró (el objeto
    reembolso de Stripe), la comparación se hace contra el pago guardado. Se han
    devuelto 5 de 15: sigue siendo suyo.
    """

    env = cliente_dentro

    resumen = rs.process_refund(
        external_payment_id="pi_refund_test",
        refunded_amount=500,
    )

    assert resumen["partial"] is True
    assert resumen["access_revoked"] is False
    assert acceso_activo(env["db"], env["user_id"], env["group_id"]) is True
    assert estado_pago(env["db"], env["user_id"]) == "paid"
    assert env["expulsados"] == []


def test_a_full_refund_announced_as_an_amount_does_take_the_access(cliente_dentro):
    """El mismo camino, pero devolviendo los 15 enteros."""

    env = cliente_dentro

    resumen = rs.process_refund(
        external_payment_id="pi_refund_test",
        refunded_amount=1500,
    )

    assert resumen["partial"] is False
    assert resumen["access_revoked"] is True
    assert acceso_activo(env["db"], env["user_id"], env["group_id"]) is False


def test_a_refund_for_an_unknown_payment_does_nothing(clean_db):
    """
    Nunca se debe expulsar a nadie por una devolución que no se puede asociar a
    un pago concreto.
    """

    resumen = rs.process_refund(external_payment_id="pi_que_no_existe")

    assert resumen["found"] is False
    assert resumen["access_revoked"] is False
    assert resumen["kicked"] is False


def test_it_also_finds_the_payment_through_the_transaction(clean_db, monkeypatch):
    """
    Los proveedores que no son Stripe registran en payment_transactions, no en
    payments.stripe_payment_id.
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (92, 'Otra', -1092, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (9102, 92, NOW() + INTERVAL '30 days', TRUE)"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status) "
            "VALUES (9102, 92, 1500, 'EUR', 'paid')"
        )
        cur.execute(
            "INSERT INTO payment_transactions (user_id, group_id, provider, status, "
            "external_payment_id, amount, currency) "
            "VALUES (9102, 92, 'paypal', 'paid', 'PAYPAL-XYZ', 1500, 'EUR')"
        )

    monkeypatch.setattr(rs, "kick_chat_member", lambda *a, **k: None)
    monkeypatch.setattr(rs, "revoke_and_delete_user_group_links", lambda *a, **k: None)
    monkeypatch.setattr(rs, "send_telegram_message", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(rs, "notify_super_admins", lambda *a, **k: 0)

    resumen = rs.process_refund(external_payment_id="PAYPAL-XYZ")

    assert resumen["found"] is True
    assert acceso_activo(db, 9102, 92) is False


def test_a_broken_database_does_not_crash_the_webhook(monkeypatch):
    """
    Un webhook que revienta hace que el proveedor reintente sin parar.
    """

    class BrokenConn:
        def cursor(self):
            raise RuntimeError("base de datos caída")

    monkeypatch.setattr(rs, "conn", BrokenConn())

    assert rs.find_payment_by_external_id("pi_x") is None
    assert rs.mark_payment_refunded(1, 1, "pi_x") is False
    assert rs.deactivate_access(1, 1) is False
    assert rs.process_refund(external_payment_id="pi_x")["found"] is False


# =========================
# LOS EVENTOS DE STRIPE
# =========================

def test_the_webhook_listens_to_refunds_and_disputes():
    """Estos eventos no se escuchaban en absoluto."""

    source = open("stripe_handler.py", encoding="utf-8").read()

    for evento in (
        "charge.refunded",
        "charge.dispute.created",
        "charge.dispute.closed",
    ):
        assert f'"{evento}"' in source, f"el webhook sigue sin escuchar {evento}"


def test_a_partial_refund_does_not_take_the_access_away():
    """
    Se ha devuelto parte del dinero, pero el acceso comprado sigue siendo suyo.
    """

    source = open("stripe_handler.py", encoding="utf-8").read()

    assert "amount_refunded" in source
    assert "refund_partial_ignored" in source


def test_a_failed_refund_does_not_take_the_access_away():
    """
    charge.refund.updated también salta cuando el reembolso falla o se cancela.
    Ahí no se ha devuelto dinero: quitar el acceso dejaría al cliente pagado y
    fuera, que es peor que el fallo original.
    """

    source = open("stripe_handler.py", encoding="utf-8").read()

    assert "refund_not_succeeded_ignored" in source
    assert '!= "succeeded"' in source


def test_a_won_dispute_leaves_the_access_alone():
    source = open("stripe_handler.py", encoding="utf-8").read()

    assert "dispute_won_no_action" in source


def test_the_crypto_providers_act_on_a_refund():
    """
    Detectaban el estado 'refunded' desde el principio, pero nadie retiraba el
    acceso.
    """

    for path in (
        "payment_providers/changenow_provider.py",
        "payment_providers/guardarian_provider.py",
    ):
        source = open(path, encoding="utf-8").read()

        assert "process_refund" in source, f"{path} sigue sin retirar el acceso"
        assert "PAYMENT_STATUS_REFUNDED" in source
