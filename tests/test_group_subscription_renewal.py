"""
Renovación automática del acceso (Stripe), contra el código real.

Las tres decisiones de producto, fijadas como pruebas:

  1. REINTENTOS: un cobro fallido NO toca el acceso — el periodo pagado sigue
     corriendo y Stripe reintenta. Solo revoca customer.subscription.deleted.
  2. CANCELAR: cancel_at_period_end — el periodo ya pagado nunca se corta, y
     el único Subscription.modify permitido en el repo es ese interruptor.
  3. PRECIOS: quien está suscrito conserva su precio; nada en el repo puede
     tocar una suscripción existente al editar un plan.

Los eventos se construyen con stripe.Event.construct_from, que es lo que
devuelve stripe.Webhook.construct_event en producción: si el servicio pidiera
algo que un evento real no tiene, aquí reventaría igual. La lección de la
sesión: los dobles nunca más permisivos que producción.
"""

from datetime import datetime, timedelta

import pytest
import stripe

import group_subscription_service as gss


def evento(tipo, objeto, previous=None):
    data = {"object": objeto}
    if previous is not None:
        data["previous_attributes"] = previous
    return stripe.Event.construct_from(
        {"id": "evt_95", "type": tipo, "data": data}, "sk_test"
    )


def factura(billing_reason="subscription_cycle", invoice_id="in_95",
            amount_paid=1500, period_end=None, subscription="sub_95"):
    fin = period_end or int((datetime.now() + timedelta(days=30)).timestamp())
    return {
        "id": invoice_id,
        "subscription": subscription,
        "billing_reason": billing_reason,
        "amount_paid": amount_paid,
        "currency": "eur",
        "attempt_count": 1,
        "lines": {"data": [{"period": {"end": fin}}]},
    }


def suscripcion_obj(sub_id="sub_95", cancel_at_period_end=False, period_end=None):
    fin = period_end or int((datetime.now() + timedelta(days=12)).timestamp())
    return {
        "id": sub_id,
        "cancel_at_period_end": cancel_at_period_end,
        "current_period_end": fin,
    }


@pytest.fixture
def suscriptor(clean_db, monkeypatch):
    """Un socio con acceso activo anclado a la suscripción sub_95."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (95, 'VIP Renovación', -1095, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) "
            "VALUES (9501, 95, NOW() + INTERVAL '3 days', TRUE, 'sub_95')"
        )

    avisos = []
    monkeypatch.setattr(gss, "send_telegram_message",
                        lambda token, chat, text, **k: avisos.append((chat, text)))

    return {"db": db, "avisos": avisos}


def estado(db):
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT expiration, COALESCE(subscription_active, FALSE), "
            "stripe_subscription_id FROM users WHERE user_id=9501 AND group_id=95"
        )
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM payments WHERE user_id=9501")
        pagos = cur.fetchone()[0]
    return {"expiration": row[0], "activo": row[1],
            "sub_id": row[2], "pagos": pagos}


# =========================
# RENOVACIÓN COBRADA
# =========================

def test_renewal_extends_access_records_payment_and_tells_the_buyer(suscriptor):
    fin = int((datetime.now() + timedelta(days=33)).timestamp())

    r = gss.process_group_subscription_lifecycle_event(
        evento("invoice.paid", factura(period_end=fin))
    )

    assert r is True

    e = estado(suscriptor["db"])

    assert abs((e["expiration"] - datetime.fromtimestamp(fin)).total_seconds()) < 2, (
        "la expiración no se movió al fin del periodo pagado"
    )
    assert e["pagos"] == 1, "la renovación no quedó en payments"

    with suscriptor["db"].conn.cursor() as cur:
        cur.execute("SELECT amount, status FROM payments WHERE user_id=9501")
        amount, status = cur.fetchone()

    assert amount == 1500, "payments guarda céntimos"
    assert status == "paid"

    al_comprador = [t for c, t in suscriptor["avisos"] if c == 9501]
    assert al_comprador and "renovada" in al_comprador[0].lower()


def test_the_first_invoice_does_not_double_grant(suscriptor):
    """El alta la hace checkout.session.completed: la primera factura calla."""

    antes = estado(suscriptor["db"])

    r = gss.process_group_subscription_lifecycle_event(
        evento("invoice.paid", factura(billing_reason="subscription_create"))
    )

    assert r is True, "la primera factura ES nuestra: solo que no extiende"

    despues = estado(suscriptor["db"])

    assert despues["expiration"] == antes["expiration"]
    assert despues["pagos"] == 0
    assert not suscriptor["avisos"], "no puede haber doble mensaje de alta"


def test_a_retried_invoice_neither_extends_twice_nor_repeats_the_message(suscriptor):
    """Stripe reenvía webhooks: la misma factura, una sola vez."""

    gss.process_group_subscription_lifecycle_event(
        evento("invoice.paid", factura())
    )

    e1 = estado(suscriptor["db"])
    suscriptor["avisos"].clear()

    gss.process_group_subscription_lifecycle_event(
        evento("invoice.paid", factura())
    )

    e2 = estado(suscriptor["db"])

    assert e2["pagos"] == 1
    assert e2["expiration"] == e1["expiration"]
    assert not suscriptor["avisos"]


# =========================
# DECISIÓN 1: EL COBRO FALLIDO NO TOCA EL ACCESO
# =========================

def test_a_failed_charge_keeps_access_and_warns_the_buyer(suscriptor):
    antes = estado(suscriptor["db"])

    r = gss.process_group_subscription_lifecycle_event(
        evento("invoice.payment_failed", factura(invoice_id="in_fail"))
    )

    assert r is True

    despues = estado(suscriptor["db"])

    assert despues["expiration"] == antes["expiration"], (
        "un fallo de cobro NO puede recortar el periodo ya pagado"
    )
    assert despues["activo"] is True

    al_comprador = [t for c, t in suscriptor["avisos"] if c == 9501]
    assert al_comprador
    assert "sigue activo" in al_comprador[0]
    assert "tarjeta" in al_comprador[0].lower()


def test_the_failure_notice_carries_the_update_card_button(suscriptor, monkeypatch):
    """
    "Revisa tu tarjeta" sin un sitio donde hacerlo es un callejón. El aviso
    lleva el portal de facturación de Stripe en un botón, creado con el
    customer de la propia factura.
    """

    capturas = []

    def portal(**kwargs):
        capturas.append(kwargs)
        return stripe.billing_portal.Session.construct_from(
            {"id": "bps_1", "url": "https://billing.stripe.com/p/sesion_1"},
            "sk_test",
        )

    monkeypatch.setattr(gss.stripe.billing_portal.Session, "create", portal)

    teclados = []
    monkeypatch.setattr(
        gss, "send_telegram_message",
        lambda token, chat, text, reply_markup=None:
            teclados.append((chat, text, reply_markup))
    )

    factura_fallida = factura(invoice_id="in_fail_btn")
    factura_fallida["customer"] = "cus_95"

    gss.process_group_subscription_lifecycle_event(
        evento("invoice.payment_failed", factura_fallida)
    )

    assert capturas and capturas[0]["customer"] == "cus_95"

    chat, texto, teclado = teclados[0]
    assert chat == 9501
    assert teclado is not None, "el aviso salió sin el botón de la tarjeta"

    boton = teclado["inline_keyboard"][0][0]
    assert boton["url"] == "https://billing.stripe.com/p/sesion_1"
    assert "tarjeta" in boton["text"].lower()


def test_without_portal_the_notice_still_goes_out(suscriptor, monkeypatch):
    """El portal hay que activarlo una vez en Stripe: hasta entonces, el
    aviso de siempre. La degradación nunca es el silencio."""

    def portal_roto(**kwargs):
        raise RuntimeError("billing portal no configurado")

    monkeypatch.setattr(gss.stripe.billing_portal.Session, "create", portal_roto)

    teclados = []
    monkeypatch.setattr(
        gss, "send_telegram_message",
        lambda token, chat, text, reply_markup=None:
            teclados.append((chat, text, reply_markup))
    )

    gss.process_group_subscription_lifecycle_event(
        evento("invoice.payment_failed", factura(invoice_id="in_fail_np"))
    )

    assert teclados, "sin portal también hay que avisar"
    assert teclados[0][2] is None


# =========================
# DECISIÓN 2: CANCELAR = HASTA EL FIN DEL PERIODO
# =========================

def test_cancelling_notifies_the_date_and_keeps_access(suscriptor):
    antes = estado(suscriptor["db"])
    fin = int((datetime.now() + timedelta(days=12)).timestamp())

    r = gss.process_group_subscription_lifecycle_event(
        evento(
            "customer.subscription.updated",
            suscripcion_obj(cancel_at_period_end=True, period_end=fin),
            previous={"cancel_at_period_end": False},
        )
    )

    assert r is True

    despues = estado(suscriptor["db"])
    assert despues["expiration"] == antes["expiration"]
    assert despues["activo"] is True

    al_comprador = [t for c, t in suscriptor["avisos"] if c == 9501]
    assert al_comprador
    assert "desactivada" in al_comprador[0].lower()
    assert datetime.fromtimestamp(fin).strftime("%d/%m/%Y") in al_comprador[0], (
        "al cancelar hay que decir HASTA CUÁNDO llega el acceso pagado"
    )


def test_reactivating_notifies_too(suscriptor):
    gss.process_group_subscription_lifecycle_event(
        evento(
            "customer.subscription.updated",
            suscripcion_obj(cancel_at_period_end=False),
            previous={"cancel_at_period_end": True},
        )
    )

    al_comprador = [t for c, t in suscriptor["avisos"] if c == 9501]
    assert al_comprador and "reactivada" in al_comprador[0].lower()


def test_an_unrelated_update_stays_silent(suscriptor):
    """Los cambios internos de Stripe no generan conversación."""

    r = gss.process_group_subscription_lifecycle_event(
        evento(
            "customer.subscription.updated",
            suscripcion_obj(),
            previous={"status": "active"},
        )
    )

    assert r is True
    assert not suscriptor["avisos"]


# =========================
# LA MUERTE DE LA SUSCRIPCIÓN
# =========================

def test_deletion_closes_access_and_frees_the_anchor(suscriptor):
    r = gss.process_group_subscription_lifecycle_event(
        evento("customer.subscription.deleted", suscripcion_obj())
    )

    assert r is True

    e = estado(suscriptor["db"])

    assert e["expiration"] <= datetime.now(), "el acceso tenía que cerrarse"
    assert e["sub_id"] is None, (
        "el ancla tiene que liberarse para poder volver a suscribirse"
    )

    al_comprador = [t for c, t in suscriptor["avisos"] if c == 9501]
    assert al_comprador and "terminado" in al_comprador[0].lower()


def test_a_foreign_subscription_is_not_ours(suscriptor):
    """Sin ancla no es nuestro: será un extra del propietario u otra cosa."""

    antes = estado(suscriptor["db"])

    r = gss.process_group_subscription_lifecycle_event(
        evento("invoice.paid", factura(subscription="sub_ajena"))
    )

    assert r is False

    despues = estado(suscriptor["db"])
    assert despues == antes
    assert not suscriptor["avisos"]


# =========================
# EL ANCLA
# =========================

def test_checkout_attaches_the_subscription_anchor(suscriptor):
    db = suscriptor["db"]

    with db.conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET stripe_subscription_id=NULL WHERE user_id=9501"
        )

    assert gss.attach_subscription_to_member(9501, 95, "sub_nueva", "cus_1")

    assert estado(db)["sub_id"] == "sub_nueva"

    socio = gss.fetch_member_by_subscription("sub_nueva")
    assert socio and socio["user_id"] == 9501 and socio["group_id"] == 95


def test_the_webhook_wires_are_connected():
    """El handler ancla en checkout.completed y despacha el ciclo de vida."""

    source = open("stripe_handler.py", encoding="utf-8").read()

    assert "attach_subscription_to_member(" in source
    assert "process_group_subscription_lifecycle_event(event)" in source

    # El anclaje ocurre en la rama de checkout completado, tras guardar acceso.
    pos_grant = source.index("resolve_incidents_for(user_id, group_id)")
    assert "attach_subscription_to_member(" in source[pos_grant:pos_grant + 900]


# =========================
# LA FRONTERA DEL SDK
# =========================
# En stripe 15.x los recursos NO son diccionarios: no tienen .get(). El
# webhook usa .get() 105 veces, así que sin frontera el PRIMER evento real
# habría reventado el cobro — el mismo fallo que ya tumbó en producción la
# autoconfiguración del webhook ("AttributeError: get").

def test_stripe_objects_really_lack_dot_get():
    """El candado del hecho: si un futuro SDK lo cambia, esto lo dirá."""

    objeto = stripe.Event.construct_from(
        {"id": "evt_x", "type": "x", "data": {"object": {"id": "in_x"}}}, "sk"
    )["data"]["object"]

    with pytest.raises(Exception):
        objeto.get("id")


def test_the_webhook_verifies_the_signature_and_then_works_on_plain_json():
    source = open("stripe_handler.py", encoding="utf-8").read()

    pos_verify = source.index("stripe.Webhook.construct_event")
    pos_plain = source.index("event = json.loads(payload)")

    assert pos_verify < pos_plain, (
        "el JSON crudo solo puede usarse DESPUÉS de verificar la firma"
    )

    # Y los recursos que sí vienen del SDK (Subscription.retrieve) pasan por
    # la conversión antes de tocarse con .get().
    assert source.count(
        "recurso_plano(\n            stripe.Subscription.retrieve"
    ) == 3, "algún Subscription.retrieve quedó sin convertir"


def test_the_dispatcher_survives_sdk_objects_too(suscriptor):
    """
    La frontera entrega dicts, pero si algún día llega un StripeObject, el
    despacho lo convierte en vez de perder el evento en silencio. (Todas las
    demás pruebas de este fichero ya usan objetos del SDK a propósito.)
    """

    fin = int((datetime.now() + timedelta(days=40)).timestamp())

    r = gss.process_group_subscription_lifecycle_event(
        evento("invoice.paid", factura(invoice_id="in_sdk", period_end=fin))
    )

    assert r is True
    assert estado(suscriptor["db"])["pagos"] == 1


# =========================
# EL CATÁLOGO Y EL CHECKOUT
# =========================

def test_interval_mapping_reads_like_a_bank_statement():
    assert gss.stripe_recurring_interval(30) == ("month", 1)
    assert gss.stripe_recurring_interval(31) == ("month", 1)
    assert gss.stripe_recurring_interval(7) == ("week", 1)
    assert gss.stripe_recurring_interval(90) == ("month", 3)
    assert gss.stripe_recurring_interval(180) == ("month", 6)
    assert gss.stripe_recurring_interval(365) == ("year", 1)
    assert gss.stripe_recurring_interval(15) == ("day", 15)


def test_the_catalog_creates_a_recurring_price_only_when_asked(monkeypatch):
    import stripe_catalog as sc

    capturas = []

    monkeypatch.setattr(sc.stripe.Product, "create",
                        lambda **k: {"id": "prod_1"})
    monkeypatch.setattr(sc.stripe.Price, "create",
                        lambda **k: capturas.append(k) or {"id": "price_1"})

    sc.create_stripe_product_and_price("Mensual", 15, "EUR")

    assert "recurring" not in capturas[0], "sin pedirlo, el precio es de pago único"

    sc.create_stripe_product_and_price("Mensual", 15, "EUR",
                                       recurring_interval_days=30)

    assert capturas[1]["recurring"] == {"interval": "month", "interval_count": 1}
    assert capturas[1]["unit_amount"] == 1500, "céntimos, como siempre"


def test_the_checkout_route_switches_to_subscription_mode():
    source = open("checkout_routes.py", encoding="utf-8").read()

    assert "COALESCE(is_recurring, FALSE)" in source, (
        "el checkout no lee si el plan es recurrente"
    )
    assert 'mode="subscription" if plan_es_recurrente else "payment"' in source
    assert '"subscription_data"' in source, (
        "sin subscription_data la suscripción no lleva metadata"
    )


# =========================
# DECISIÓN 3: PRECIOS ANTIGUOS INTOCABLES
# =========================

def test_nothing_in_the_repo_can_touch_an_existing_subscriptions_price():
    """
    El precio de quien ya está suscrito se conserva porque NADA en el código
    modifica suscripciones existentes, salvo el interruptor de renovación
    (cancel_at_period_end). Si alguien añade un Subscription.modify que toque
    items o precios, esta prueba lo para.
    """

    import glob

    sitios = []

    for path in glob.glob("*.py") + glob.glob("payment_providers/*.py"):

        # Los extras del propietario quedan fuera de la regla: ahí el dueño
        # cambia SU PROPIA suscripción de nivel (con prorrateo), a propósito.
        # La regla protege a los SUSCRIPTORES de acceso a comunidades.
        if path.startswith("owner_addon"):
            continue

        source = open(path, encoding="utf-8").read()

        idx = 0
        while True:
            idx = source.find("Subscription.modify", idx)
            if idx == -1:
                break
            sitios.append((path, source[idx:idx + 220]))
            idx += 1

    assert sitios, "el interruptor de renovación tiene que existir"

    for path, trozo in sitios:

        # Cuatro usos legítimos: el interruptor (cancel_at_period_end), la
        # oferta de salvamento (discounts=, que solo puede MEJORAR el
        # precio), la pausa (pause_collection, que suspende cobros sin
        # tocarlo) y los días de regalo de un referido (trial_end, que
        # RETRASA el cargo — es lo que convierte unos días regalados en
        # días de verdad gratis).
        assert ("cancel_at_period_end" in trozo or "discounts=" in trozo
                or "pause_collection" in trozo or "trial_end" in trozo), (
            f"{path} modifica una suscripción para algo que no es el "
            "interruptor de renovación ni un descuento: eso puede tocar el "
            "precio de un suscriptor existente"
        )
        assert "items" not in trozo and "price" not in trozo, (
            f"{path} toca items/price de una suscripción existente: los "
            "precios de los ya suscritos son intocables"
        )


# =========================
# LA PANTALLA DEL COMPRADOR
# =========================

def test_the_screen_offerss_the_switch_and_the_wizard_asks():
    mysub = open("mysub_callbacks.py", encoding="utf-8").read()

    assert "mysub_stoprenew_yes_" in mysub
    assert "mysub_stoprenew_" in mysub
    assert "mysub_renewon_" in mysub

    # El "yes" se comprueba ANTES que su prefijo padre: la trampa de siempre.
    assert mysub.index('data.startswith("mysub_stoprenew_yes_")') < \
        mysub.index('data.startswith("mysub_stoprenew_")')

    # Y ambas antes que la rama genérica, que espera un número tras mysub_.
    assert mysub.index("mysub_stoprenew_yes_") < mysub.index('data.startswith("mysub_")')

    wizard = open("admin_input_handler.py", encoding="utf-8").read()

    assert "RENOVACIÓN AUTOMÁTICA" in wizard, "el paso 6 del asistente no existe"
    assert "is_recurring" in wizard


def test_the_renewal_switch_flips_only_cancel_at_period_end(suscriptor, monkeypatch):
    llamadas = []

    monkeypatch.setattr(
        gss.stripe.Subscription, "modify",
        lambda sub_id, **k: llamadas.append((sub_id, k)) or {"id": sub_id}
    )

    assert gss.set_renewal_enabled(9501, 95, False) is True
    assert llamadas[-1] == ("sub_95", {"cancel_at_period_end": True})

    assert gss.set_renewal_enabled(9501, 95, True) is True
    assert llamadas[-1] == ("sub_95", {"cancel_at_period_end": False})


def test_the_switch_without_subscription_says_no(suscriptor):
    with suscriptor["db"].conn.cursor() as cur:
        cur.execute("UPDATE users SET stripe_subscription_id=NULL WHERE user_id=9501")

    assert gss.set_renewal_enabled(9501, 95, False) is False
