"""
El cobro sale bien y el acceso no se puede conceder.

Dos formas de que pase, y en las dos el comprador se quedaba en silencio: solo
quedaba una línea en el registro de auditoría.

  - plan_not_found: se cobró por un plan que ya no existe. El reintento del
    webhook no lo arregla nunca.
  - storage_failed: falló el guardado. Aquí el reintento sí puede salvarlo.

Es peor que el caso del enlace, que ya estaba cubierto: allí el acceso quedaba
guardado y el botón «Pedir mi enlace» desbloqueaba al cliente solo. Aquí no hay
nada guardado, así que no puede hacer nada por su cuenta.

Lo delicado: los proveedores reintentan los webhooks. Avisar veinte veces a
alguien que acaba de pagar es peor que el fallo original.
"""

import pytest

import payment_incident_service as pis


# =========================
# TRANSITORIO O DEFINITIVO
# =========================

def test_a_missing_plan_needs_a_person():
    """Reintentar un cobro por un plan que no existe no lo arregla nunca."""

    assert pis.incident_is_permanent(pis.INCIDENT_PLAN_MISSING) is True


def test_a_storage_failure_may_fix_itself():
    """El reintento del proveedor es justo lo que salva este caso."""

    assert pis.incident_is_permanent(pis.INCIDENT_STORAGE_FAILED) is False


def test_the_two_cases_are_told_differently_to_the_buyer():
    """
    Decirle "espera unos minutos" cuando hace falta una persona es hacerle
    perder la tarde.
    """

    esperando = pis.build_buyer_incident_text(
        "VIP Fitness", pis.INCIDENT_STORAGE_FAILED
    )
    a_mano = pis.build_buyer_incident_text(
        "VIP Fitness", pis.INCIDENT_PLAN_MISSING
    )

    assert esperando != a_mano
    assert "minutos" in esperando
    assert "responsable" in a_mano


def test_the_buyer_is_told_the_money_is_not_lost():
    """Es lo único que de verdad le preocupa en ese momento."""

    for kind in (pis.INCIDENT_PLAN_MISSING, pis.INCIDENT_STORAGE_FAILED):

        texto = pis.build_buyer_incident_text("VIP Fitness", kind)

        assert "No has perdido el dinero" in texto
        assert "VIP Fitness" in texto


def test_the_buyer_message_is_translated():
    for kind in (pis.INCIDENT_PLAN_MISSING, pis.INCIDENT_STORAGE_FAILED):

        es = pis.build_buyer_incident_text("VIP", kind, language="es")
        en = pis.build_buyer_incident_text("VIP", kind, language="en")

        assert es != en
        assert "not lost your money" in en


def test_the_buyer_is_not_offered_a_link_they_cannot_get():
    """
    Aquí no hay acceso guardado, así que un botón de «pedir mi enlace» no
    tendría nada que darle: solo más frustración.
    """

    filas = pis.build_buyer_incident_keyboard().inline_keyboard
    callbacks = [b.callback_data for fila in filas for b in fila]

    assert callbacks == ["public_support"]


def test_the_staff_message_carries_the_identifiers():
    """Sin ellos hay que buscar el pago a mano."""

    texto = pis.build_staff_incident_text(
        "VIP Fitness",
        pis.INCIDENT_PLAN_MISSING,
        user_id=4242,
        group_id=51,
        provider="paypal",
        detail="plan_id=99",
        external_payment_id="PAY-XYZ",
    )

    assert "4242" in texto
    assert "51" in texto
    assert "paypal" in texto
    assert "PAY-XYZ" in texto
    assert "plan_id=99" in texto


def test_the_staff_message_says_whether_to_act_now():
    permanente = pis.build_staff_incident_text(
        "VIP", pis.INCIDENT_PLAN_MISSING, 1, 1
    )
    transitorio = pis.build_staff_incident_text(
        "VIP", pis.INCIDENT_STORAGE_FAILED, 1, 1
    )

    assert "intervenir" in permanente
    assert "reintentará" in transitorio


# =========================
# UNA SOLA VEZ
# =========================

@pytest.fixture
def entorno(clean_db, monkeypatch):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (51, 'VIP Fitness', -1051, TRUE)"
        )

    al_comprador = []
    al_equipo = []

    def enviar(token, chat, text, reply_markup=None):
        (al_comprador if chat == 4242 else al_equipo).append(text)
        return {"ok": True}

    monkeypatch.setattr(pis, "send_telegram_message", enviar)
    monkeypatch.setattr(pis, "notify_super_admins", lambda *a, **k: 1)
    monkeypatch.setattr(pis, "get_group_owner_user_id", lambda gid: 777)

    return {"db": db, "comprador": al_comprador, "equipo": al_equipo}


def reportar(**kwargs):
    base = dict(
        kind=pis.INCIDENT_STORAGE_FAILED,
        user_id=4242,
        group_id=51,
        provider="paypal",
        external_payment_id="PAY-RETRY",
    )
    base.update(kwargs)

    return pis.report_payment_incident(**base)


def test_the_buyer_is_told_once(entorno):
    resumen = reportar()

    assert resumen["recorded"] is True
    assert resumen["buyer_notified"] is True
    assert len(entorno["comprador"]) == 1


def test_a_retried_webhook_does_not_tell_them_again(entorno):
    """
    Los proveedores reintentan. Veinte avisos del mismo problema a quien acaba de
    pagar es peor que el problema.
    """

    reportar()
    entorno["comprador"].clear()
    entorno["equipo"].clear()

    segundo = reportar()

    assert segundo["recorded"] is False
    assert entorno["comprador"] == []
    assert entorno["equipo"] == []


def test_two_different_payments_are_two_different_incidents(entorno):
    reportar(external_payment_id="PAY-1")
    reportar(external_payment_id="PAY-2")

    assert len(entorno["comprador"]) == 2


def test_the_same_payment_failing_two_ways_is_reported_twice(entorno):
    """
    El tipo forma parte de la identidad: un guardado que falla y luego un plan
    que desaparece son dos problemas distintos del mismo pago.
    """

    reportar(kind=pis.INCIDENT_STORAGE_FAILED)
    reportar(kind=pis.INCIDENT_PLAN_MISSING)

    assert len(entorno["comprador"]) == 2


def test_the_people_who_can_fix_it_are_told(entorno):
    reportar(kind=pis.INCIDENT_PLAN_MISSING)

    assert entorno["equipo"], "nadie que pueda arreglarlo se ha enterado"
    assert "intervenir" in entorno["equipo"][0]


def test_without_a_payment_id_it_still_does_not_spam(entorno):
    """
    Algunos proveedores no dan identificador. La combinación de persona,
    comunidad y tipo evita al menos la repetición inmediata.
    """

    reportar(external_payment_id=None, transaction_id=None)
    entorno["comprador"].clear()
    reportar(external_payment_id=None, transaction_id=None)

    assert entorno["comprador"] == []


def test_a_broken_database_does_not_notify_and_does_not_crash(monkeypatch):
    """
    Sin poder registrar no se puede garantizar que no se repita el aviso, así
    que no se avisa. Y sobre todo: no se lanza, porque esto corre dentro de un
    webhook de cobro.
    """

    class BrokenConn:
        def cursor(self):
            raise RuntimeError("base de datos caída")

    enviados = []

    monkeypatch.setattr(pis, "conn", BrokenConn())
    monkeypatch.setattr(
        pis, "send_telegram_message",
        lambda *a, **k: enviados.append(1) or {"ok": True}
    )

    resumen = pis.report_payment_incident(
        pis.INCIDENT_STORAGE_FAILED, 1, 1, provider="stripe"
    )

    assert resumen["recorded"] is False
    assert enviados == []


def test_a_later_success_closes_the_incident(entorno):
    """
    En storage_failed el reintento del proveedor suele arreglarlo. Dejar la
    incidencia abierta haría perseguir un problema que ya no existe.
    """

    reportar()

    cerradas = pis.resolve_incidents_for(4242, 51)

    assert cerradas == 1

    with entorno["db"].conn.cursor() as cur:
        cur.execute(
            "SELECT resolved_at FROM payment_incidents WHERE user_id=4242"
        )
        assert cur.fetchone()[0] is not None


# =========================
# EL CAMINO DE PAGO DE VERDAD
# =========================

def test_a_payment_for_a_deleted_plan_tells_the_buyer(clean_db, monkeypatch):
    """
    Se ejecuta grant_group_access_after_payment de verdad, que es lo que llaman
    los cinco proveedores.
    """

    import payment_access_service as pas

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (52, 'VIP Borrado', -1052, TRUE)"
        )

    avisos = []

    monkeypatch.setattr(
        pis, "send_telegram_message",
        lambda token, chat, text, reply_markup=None: (
            avisos.append((chat, text)), {"ok": True}
        )[1],
    )
    monkeypatch.setattr(pis, "notify_super_admins", lambda *a, **k: 1)
    monkeypatch.setattr(pis, "get_group_owner_user_id", lambda gid: None)

    resultado = pas.grant_group_access_after_payment(
        "paypal",
        5252,
        52,
        plan_id=999999,            # un plan que no existe
        external_payment_id="PAY-BORRADO",
        amount=1500,
        currency="EUR",
    )

    assert resultado["ok"] is False
    assert resultado["reason"] == "plan_not_found"

    al_comprador = [t for c, t in avisos if c == 5252]

    assert al_comprador, "pagó y no se le dijo nada"
    assert "No has perdido el dinero" in al_comprador[0]


def test_the_five_providers_all_go_through_the_same_grant(clean_db):
    """
    El aviso vive dentro de grant_group_access_after_payment justamente para que
    valga para los cinco. Si alguno dejara de pasar por ahí, se quedaría sin él.
    """

    import re

    for path in (
        "payment_providers/paypal_provider.py",
        "payment_providers/revolut_provider.py",
        "payment_providers/guardarian_provider.py",
    ):
        source = open(path, encoding="utf-8").read()

        assert "grant_group_access_after_payment" in source, (
            f"{path} concede acceso por su cuenta: se quedaría sin el aviso"
        )

    # ChangeNOW es distinto a propósito: un pago confirmado se deja en revisión
    # manual y nunca concede acceso solo, así que no pasa por aquí. Se comprueba
    # ese diseño, para que si alguien lo cambia a concesión automática sin usar
    # la función compartida, salte.
    changenow = open(
        "payment_providers/changenow_provider.py", encoding="utf-8"
    ).read()

    assert "grant_group_access_after_payment" not in changenow
    assert "PAYMENT_STATUS_MANUAL_REVIEW" in changenow, (
        "ChangeNOW ya no manda los pagos a revisión manual: si ahora concede "
        "acceso, tiene que hacerlo por grant_group_access_after_payment"
    )

    # Stripe tiene su propio camino, así que su fallo se cubre aparte.
    stripe_source = open("stripe_handler.py", encoding="utf-8").read()

    assert re.search(r"build_buyer_message", stripe_source)
