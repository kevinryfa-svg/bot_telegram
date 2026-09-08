"""
Cinco cosas que el bot no le decía a quien ya había pagado o estaba pagando.

Las tres primeras son la misma familia: el bot sabía la fecha, sabía el importe
y sabía que era una suscripción, y no decía ninguna de las tres. De ahí salen
las reclamaciones al banco: no de un cobro mal hecho, sino de un cobro que
nadie había avisado.
"""

import pytest


# =========================
# UNA CUENTA ATRÁS NO ES UNA FECHA
# =========================
# «364d 23h 15m» no se puede apuntar en un calendario ni comprobar contra el
# extracto, y era el ÚNICO dato que tenía un socio sobre cuándo se le acaba.

def test_the_access_screen_shows_a_real_date():
    fuente = open("mysub_callbacks.py", encoding="utf-8").read()

    pos = fuente.index("format_tiempo_restante(")
    trozo = fuente[pos:pos + 800]

    assert "📅 Hasta el" in trozo
    assert "%d/%m/%Y" in trozo


# =========================
# «SE RENUEVA SOLA AL FINAL DE CADA PERIODO»
# =========================
# Ni cuándo ni cuánto. Es justo lo que se busca en esa pantalla cuando llega el
# cargo al banco y no se reconoce.

@pytest.fixture
def socio(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (96, 'StarsVip', -1096, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active, is_recurring) VALUES "
            "(961, 96, 'Mensual', 'price_m96', 'price_m96', 30, 15, 'EUR', TRUE, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, subscription_active, expiration) "
            "VALUES (9601, 96, TRUE, NOW() + INTERVAL '10 days')"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (9601, 96, 1500, 'EUR', 'paid', 'Mensual')"
        )

    return db


def test_the_renewal_line_says_when_and_how_much(socio):
    from datetime import datetime, timedelta

    import mysub_callbacks as ms

    caduca = datetime.now() + timedelta(days=10)

    linea = ms.linea_de_renovacion_activa(9601, 96, caduca, "es")

    assert caduca.strftime("%d/%m/%Y") in linea
    assert "15 EUR" in linea
    assert "se te cobrar" in linea


def test_without_a_price_it_still_says_the_date(socio, monkeypatch):
    from datetime import datetime, timedelta

    import mysub_callbacks as ms
    import renewal_service as rs

    monkeypatch.setattr(rs, "precio_de_renovacion", lambda u, g: None)

    caduca = datetime.now() + timedelta(days=10)

    linea = ms.linea_de_renovacion_activa(9601, 96, caduca, "es")

    assert caduca.strftime("%d/%m/%Y") in linea
    assert "Se renueva sola el" in linea


def test_without_a_date_it_falls_back_to_the_old_sentence(socio):
    import mysub_callbacks as ms

    from i18n_service import t

    assert ms.linea_de_renovacion_activa(9601, 96, None, "es") == t(
        "mysub.renewal_active", "es"
    ), "nunca una fecha inventada"


# =========================
# LA CONFIRMACIÓN NO DECÍA QUE SE VOLVERÍA A COBRAR
# =========================
# Con una suscripción decía «Tu acceso dura hasta el 8/10» y nada más: quien lo
# leía entendía que pagaba una vez.

def test_a_subscription_says_it_will_charge_again():
    from datetime import datetime, timedelta

    import purchase_message_service as pms

    texto = pms.build_purchase_confirmation_text(
        group_name="StarsVip",
        plan_name="Mensual",
        amount_total=1500,
        currency="EUR",
        expiration=datetime.now() + timedelta(days=30),
        expire_seconds=86400,
        link="https://t.me/+x",
        es_recurrente=True,
    )

    assert "Es una suscripción" in texto
    assert "se te vuelve a cobrar" in texto
    assert "Mis accesos" in texto, "y cómo apagarlo"


def test_a_one_off_purchase_says_nothing_about_renewing():
    from datetime import datetime, timedelta

    import purchase_message_service as pms

    texto = pms.build_purchase_confirmation_text(
        group_name="StarsVip",
        plan_name="Semana",
        amount_total=360,
        currency="EUR",
        expiration=datetime.now() + timedelta(days=7),
        expire_seconds=86400,
        link="https://t.me/+x",
    )

    assert "suscripción" not in texto, (
        "avisar de una renovación que no existe asusta igual que no avisar"
    )


def test_the_receipt_writes_money_like_the_shop():
    """Séptimo formateador a mano, y en el mensaje más importante del bot."""

    from purchase_message_service import format_purchase_amount

    assert format_purchase_amount(360, "EUR") == "3,60 EUR"
    assert format_purchase_amount(1500, "EUR") == "15 EUR"


def test_the_grant_knows_whether_the_plan_recurs():
    fuente = open("payment_access_service.py", encoding="utf-8").read()

    assert '"is_recurring": bool(row[9])' in fuente
    assert "es_recurrente=bool(plan.get(\"is_recurring\"))" in fuente


# =========================
# UNA PROMESA QUE EL BOT NO CUMPLE
# =========================
# El mensaje de pago decía «puedes volver a intentarlo cuando quieras», y el bot
# bloquea una compra nueva mientras el intento anterior siga pendiente —dos
# horas— para no cobrar dos veces con los métodos que confirman tarde.

def test_the_checkout_no_longer_promises_a_free_retry():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "volver a intentarlo cuando quieras" not in fuente, (
        "la contradicción caía justo en el momento de pagar"
    )
    assert "vuelve a " in fuente and "«Mis accesos»." in fuente


def test_the_blocked_screen_says_how_long():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "PENDING_PAYMENT_STALE_AFTER" in fuente, (
        "el plazo se lee de donde vive, no se escribe otra vez"
    )
    assert "se libera solo en" in fuente
    # La frase solo puede quedar en el comentario que explica por qué se
    # quitó, nunca en un mensaje que se le manda a alguien.
    pos = fuente.index("Hay un intento de pago pendiente")
    mensaje = fuente[pos:pos + 900]

    assert "crear un nuevo intento desde Ver planes" not in mensaje, (
        "eso era justo lo que el bloqueo no permitía"
    )
    assert "NO pagues otra vez" in mensaje


# =========================
# PRECIOS SIN FORMA DE PAGARLOS
# =========================
# El texto listaba TODOS los planes activos y el bucle de botones se salta los
# que no tienen precio de Stripe o cuyo proveedor está apagado.

def test_the_summary_is_built_from_the_payable_plans():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "format_plans_summary(planes_con_boton)" in fuente
    assert "+ f\"{format_plans_summary(plans)}" not in fuente, (
        "esa era la lista sin filtrar"
    )

    assert fuente.count("planes_con_boton.append(plan)") == 5, (
        "los cinco proveedores tienen que apuntar su plan"
    )


def test_with_nothing_payable_the_screen_says_so():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "if not planes_con_boton:" in fuente
    assert "los accesos están sin activar ahora" in fuente
    assert "plans_screen_without_payable_plan" in fuente, (
        "y queda escrito: es un fallo del dueño que nadie veía"
    )
