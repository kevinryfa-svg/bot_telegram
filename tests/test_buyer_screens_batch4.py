"""
Diez cosas más del camino del comprador.

El hilo de esta tanda: lo que pasa cuando el bot habla con la voz del sistema
en vez de con la del que compra. «Checkout PayPal creado», «webhook
verificado», «2026-10-08 15:22», el error del servidor reenviado tal cual. Y
la restricción de región, que aparecía cuando ya se había decidido comprar.
"""

import pytest


# =========================
# LA PANTALLA DE «PAGA AQUÍ», IGUAL PARA LOS CINCO
# =========================

def test_the_pay_screen_says_what_and_how_much(clean_db):
    import callback_router as cr

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (98, 'StarsVip', -1098, TRUE)"
        )

    texto = cr.build_pay_here_text(
        "Revolut", "https://pay/x", group_id=98, importe=3.6, moneda="EUR"
    )

    assert "StarsVip" in texto, "no decía QUÉ se estaba pagando"
    assert "3,60 EUR" in texto, "ni CUÁNTO"
    assert "https://pay/x" in texto
    assert "no se te cobra nada" in texto


def test_the_pay_screen_has_no_jargon():
    import callback_router as cr

    texto = cr.build_pay_here_text("PayPal", "https://pay/x")

    for jerga in ("webhook", "checkout", "Checkout"):
        assert jerga not in texto, jerga


def test_it_survives_without_community_or_price():
    import callback_router as cr

    texto = cr.build_pay_here_text("PayPal", "https://pay/x")

    assert "https://pay/x" in texto
    assert "Último paso" in texto


def test_revolut_no_longer_wipes_the_keyboard():
    fuente = open("callback_router.py", encoding="utf-8").read()

    pos = fuente.index('build_pay_here_text(\n                "Revolut"')
    trozo = fuente[pos:pos + 600]

    assert "build_payment_link_keyboard" in trozo
    assert "ReplyKeyboardRemove" not in trozo, (
        "quitaba el teclado y dejaba una URL pelada: si el enlace no abría, "
        "no había salida"
    )


def test_every_provider_error_says_nobody_charged_you():
    fuente = open("callback_router.py", encoding="utf-8").read()

    for prov in ("PayPal", "Revolut", "ChangeNOW", "Guardarian"):

        pos = fuente.index(f"No he podido abrir el pago con {prov}")
        trozo = fuente[pos:pos + 300]

        assert "No se te ha cobrado nada" in trozo, prov

    # Y el del servidor ya no se reenvía tal cual al comprador.
    assert 'text=response_data.get("error")' not in fuente


def test_the_card_disabled_error_says_it_too():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "Este método de pago aún no está disponible." not in fuente, (
        "era el único error de pago que no lo decía"
    )
    assert "El pago con tarjeta no está disponible ahora mismo" in fuente


# =========================
# UNA MARCA DE TIEMPO DE MÁQUINA
# =========================

def test_the_access_date_reads_like_a_date():
    from datetime import datetime

    import callback_router as cr

    escrito = cr.format_access_expiration(datetime(2026, 10, 8, 15, 22))

    assert escrito == "hasta el 08/10/2026", (
        "«2026-10-08 15:22» es una marca de tiempo, y se pegaba detrás de "
        "«Acceso:» como si fuera un código"
    )
    assert cr.format_access_expiration(None) == "permanente"


def test_the_existing_access_screen_uses_it():
    import callback_router as cr

    from datetime import datetime, timedelta

    texto = cr.build_existing_group_access_text({
        "group_name": "StarsVip",
        "has_active_access": True,
        "expires_at": datetime.now() + timedelta(days=5),
    })

    assert "Tu acceso vale hasta el" in texto
    assert "Acceso: 2" not in texto


# =========================
# PEDIR DEVOLUCIÓN, QUE NO SE PODÍA
# =========================

@pytest.fixture
def con_pago(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (99, 'StarsVip', -1099, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, subscription_active, expiration) "
            "VALUES (9901, 99, TRUE, NOW() + INTERVAL '20 days')"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, "
            "plan, stripe_payment_id) VALUES "
            "(9901, 99, 1500, 'EUR', 'paid', 'Mensual', 'pi_x')"
        )

    return db


def test_a_member_can_ask_for_a_refund(con_pago):
    from refund_request_service import describe_refundable

    devolvible = describe_refundable(9901, 99)

    assert devolvible is not None
    assert devolvible["plan"] == "Mensual"


def test_the_button_exists_in_the_access_screen():
    fuente = open("mysub_callbacks.py", encoding="utf-8").read()

    assert 't("mysub.btn_refund", language)' in fuente
    assert "mysubrefund_ask_" in fuente
    assert 'data.startswith("mysubrefund_")' in fuente


def test_asking_does_not_move_any_money():
    """La decisión sigue siendo de una persona."""

    fuente = open("mysub_callbacks.py", encoding="utf-8").read()

    pos = fuente.index('data.startswith("mysubrefund_")')
    trozo = fuente[pos:pos + 4000]

    assert "mark_refund_requested" in trozo, "se registra la petición"
    assert "refund_last_payment" not in trozo, (
        "pedirla no puede ejecutarla: eso lo decide el operador"
    )


def test_the_request_is_idempotent(con_pago):
    from refund_request_service import describe_refundable, mark_refund_requested

    devolvible = describe_refundable(9901, 99)

    assert mark_refund_requested(devolvible["payment_id"], 9901) is True
    assert mark_refund_requested(devolvible["payment_id"], 9901) is False, (
        "pulsar dos veces no puede abrir dos peticiones"
    )


def test_a_failed_notice_does_not_lose_the_request(monkeypatch):
    """La petición ya está registrada cuando se avisa."""

    import mysub_callbacks as ms

    import notification_service

    def revienta(*a, **k):
        raise RuntimeError("telegram caído")

    monkeypatch.setattr(notification_service, "send_telegram_message", revienta)

    assert ms.avisar_al_operador_de_la_devolucion(
        9901, 99, "StarsVip", {"plan": "Mensual", "importe": "15.00 EUR",
                               "payment_id": 1, "puede_api": True}
    ) is False


# =========================
# LA CABECERA Y LOS BOTONES, LA MISMA CUENTA
# =========================
# La cabecera salía de fetch_offer_snapshot y los botones de
# fetch_sellable_communities, y las dos filtran cosas distintas: se leía «Hay 4
# comunidades disponibles, desde 3 EUR» encima de UN botón de 15 EUR.

def test_the_headline_counts_what_the_buttons_show():
    import start_handler as sh

    vendibles = [
        {"ya_dentro": False, "amount": 15, "currency": "EUR"},
        {"ya_dentro": False, "amount": 9, "currency": "EUR"},
        {"ya_dentro": True, "amount": 3, "currency": "EUR"},
    ]

    texto = sh.build_public_start_message(vendibles=vendibles)

    assert "Hay 2 comunidades" in texto, "el que ya está dentro no cuenta"
    assert "9" in texto, "y el «desde» es el más barato de los que se enseñan"
    assert "desde 3" not in texto


def test_with_nothing_to_sell_it_falls_back():
    import start_handler as sh

    texto = sh.build_public_start_message(vendibles=[])

    assert texto == sh.PUBLIC_START_TEXT_ES


def test_the_call_site_passes_the_same_list():
    fuente = open("start_handler.py", encoding="utf-8").read()

    assert "build_public_start_message(vendibles=ofertas)" in fuente


# =========================
# LA REGIÓN, DICHA ANTES DE DECIDIR
# =========================

def test_the_card_says_the_region_upfront(clean_db):
    import callback_router as cr

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "location_gate_enabled, allowed_region, allowed_region_type) "
            "VALUES (100, 'SoloES', -1100, TRUE, TRUE, 'ES', 'country')"
        )

    lineas = cr.linea_de_region_restringida(100)

    assert lineas and "Solo desde" in lineas[0], (
        "la restricción aparecía DESPUÉS de elegir plan, con la compra ya "
        "decidida"
    )


def test_a_community_without_the_gate_says_nothing(clean_db):
    import callback_router as cr

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (101, 'Abierta', -1101, TRUE)"
        )

    assert cr.linea_de_region_restringida(101) == []
    assert cr.linea_de_region_restringida(None) == []


def test_the_gate_screen_says_nobody_charged_you():
    fuente = open("callback_router.py", encoding="utf-8").read()

    pos = fuente.index("Esta comunidad solo admite a gente de una zona")
    trozo = fuente[pos:pos + 900]

    assert "No se te ha cobrado nada" in trozo
    assert "/start" in trozo, "y cómo salir si no quiere compartirla"


# =========================
# ESPAÑOL DURO DENTRO DE UN FLUJO TRADUCIDO
# =========================

def test_the_switch_screen_speaks_the_buyers_language():
    from plan_switch_service import build_switch_text

    opciones = [(1, "Anual", 120, "EUR", 365, "price_a", "stripe")]

    texto_en = build_switch_text("StarsVip", opciones, current_plan="Mensual",
                                 language="en")

    assert "Change plan" in texto_en
    assert "Cambiar de plan" not in texto_en
    assert "Your current plan" in texto_en
    assert "Available plans" in texto_en


def test_spanish_still_reads_the_same():
    from plan_switch_service import build_switch_text

    opciones = [(1, "Anual", 120, "EUR", 365, "price_a", "stripe")]

    texto = build_switch_text("StarsVip", opciones, current_plan="Mensual")

    assert "🔀 Cambiar de plan en StarsVip" in texto
    assert "Tu plan ahora: Mensual" in texto


# =========================
# DOS ETIQUETAS PARA EL MISMO SITIO
# =========================

def test_one_label_for_one_destination():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert '"💳 Ver acceso"' not in fuente
    assert '"💳 Comprar acceso"' not in fuente, (
        "dos etiquetas distintas para el mismo destino en pantallas contiguas"
    )
    assert fuente.count('"💳 Ver planes y precios"') >= 4, (
        "y la etiqueta dice lo que se va a ver"
    )
