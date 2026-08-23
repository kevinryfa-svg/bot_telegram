"""
La puerta del asistente de planes: lo que el cobro no puede usar, no entra.

El paso que pide el identificador del precio guardaba CUALQUIER cosa. En
producción, dentro del stripe_price_id de un plan activo había una respuesta de
soporte entera:

    «Hola lorrrdd, Gracias por tu mensaje. Hemos recibido tu solicitud de
    revisión manual de ubicación…»

Ese plan se anuncia con su precio y su botón, y el cobro muere en el último
paso, con el comprador ya decidido. Desde fuera se ve igual que «la gente no
compra».

Y había una segunda puerta al mismo sitio: el paso dice por escrito «escribe
*auto* y el bot creará el precio», pero al EDITAR un plan no existía ningún
auto — se guardaba la palabra literal como identificador. Seguir la instrucción
de la pantalla dejaba el plan roto.

Lo mismo con la moneda: se guardaba lo que se escribiera. En producción hay
planes con «EURO», «€», «$» y «1».
"""

import asyncio

import pytest

import admin_input_handler as aih


class FakeMessage:
    def __init__(self, texto):
        self.text = texto
        self.enviados = []

    async def reply_text(self, text=None, reply_markup=None, **kwargs):
        self.enviados.append(text)
        return True


class FakeUpdate:
    def __init__(self, texto):
        self.message = FakeMessage(texto)
        self.effective_user = type("U", (), {"id": 9001, "username": "admin",
                                             "first_name": "A"})()
        self.effective_chat = type("C", (), {"id": 9001})()


class FakeContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}
        self.bot = type("B", (), {})()


def escribir(texto, user_data):
    """Le escribe al asistente y devuelve (respuestas, estado)."""

    update = FakeUpdate(texto)
    contexto = FakeContext(user_data)

    asyncio.run(aih.receive_admin_inputs(update, contexto))

    return update.message.enviados, contexto.user_data


def editando_en_el_paso_del_precio(provider="stripe"):
    return {
        "editing_plan": True,
        "editing_plan_id": 7,
        "edit_plan_step": 2,
        "edit_plan_provider": provider,
        "selected_group_admin": 41,
    }


# =========================
# EL IDENTIFICADOR DEL PRECIO
# =========================

def test_a_support_reply_is_not_a_price_id():
    """El caso literal de producción."""

    respuestas, estado = escribir(
        "Hola lorrrdd,\n\nGracias por tu mensaje. Hemos recibido tu solicitud "
        "de revisión manual de ubicación y hemos aprobado temporalmente tu "
        "acceso.",
        editando_en_el_paso_del_precio(),
    )

    assert estado.get("edit_plan_stripe_price_id") is None, (
        "guardarlo deja el plan anunciándose y sin poder cobrar"
    )
    assert estado["edit_plan_step"] == 2, "el asistente no avanza con eso"
    assert "price_1" in respuestas[0], "y dice qué forma tiene lo que pide"


def test_the_word_auto_is_honoured_when_editing_not_stored_as_a_price():
    """La pantalla lo ofrece por escrito; al editar no existía."""

    respuestas, estado = escribir("auto", editando_en_el_paso_del_precio())

    assert estado.get("edit_plan_stripe_autocreate") is True
    assert estado.get("edit_plan_stripe_price_id") is None, (
        "se guardaba la palabra «auto» como identificador de precio"
    )
    assert estado["edit_plan_step"] == 3, "y el asistente sigue"
    assert "duración" in respuestas[0]


def test_a_real_price_id_goes_through():
    _respuestas, estado = escribir(
        "price_1U6fP8BbMxuRndhhRudyEFLt", editando_en_el_paso_del_precio()
    )

    assert estado["edit_plan_stripe_price_id"] == "price_1U6fP8BbMxuRndhhRudyEFLt"
    assert estado["edit_plan_step"] == 3
    assert estado.get("edit_plan_stripe_autocreate") is False


def test_a_paypal_secret_is_not_a_paypal_plan_id():
    """También literal: en producción hay un plan con un token de 80 letras."""

    respuestas, estado = escribir(
        "AeNhl8tdGot0KU8f5ksYm_7sNx7rw7SwX4jC7G84SqXuiFnjarTkaPhOHIDAO2xUgWofv6E",
        editando_en_el_paso_del_precio(provider="paypal"),
    )

    assert estado.get("edit_plan_paypal_plan_id") is None
    assert estado["edit_plan_step"] == 2
    assert "P-" in respuestas[0]


def test_a_real_paypal_plan_id_goes_through():
    _respuestas, estado = escribir(
        "P-5ML4271244454362W", editando_en_el_paso_del_precio(provider="paypal")
    )

    assert estado["edit_plan_paypal_plan_id"] == "P-5ML4271244454362W"
    assert estado["edit_plan_step"] == 3


def test_another_provider_takes_a_reference_but_not_a_paragraph():
    respuestas, estado = escribir(
        "esto es una frase entera", editando_en_el_paso_del_precio(provider="revolut")
    )

    assert estado["edit_plan_step"] == 2
    assert "sin espacios" in respuestas[0]

    _respuestas, estado = escribir(
        "mensual_vip", editando_en_el_paso_del_precio(provider="revolut")
    )

    assert estado["edit_plan_step"] == 3


# =========================
# LA MONEDA
# =========================

def test_a_currency_that_is_not_a_currency_is_refused():
    estado_inicial = {
        "editing_plan": True,
        "editing_plan_id": 7,
        "edit_plan_step": 5,
        "edit_plan_provider": "stripe",
        "selected_group_admin": 41,
        "edit_plan_name": "VIP",
        "edit_plan_price": "price_x",
        "edit_plan_stripe_price_id": "price_x",
        "edit_plan_duration": 30,
        "edit_plan_amount": 15,
    }

    respuestas, estado = escribir("euros de los de siempre", estado_inicial)

    assert estado["edit_plan_step"] == 5, "no se guarda el plan con esa moneda"
    assert "tres letras" in respuestas[0]


def test_a_currency_alias_is_stored_canonical(clean_db):
    """«EURO» es lo que había en producción, y Stripe lo rechaza."""

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (41, 'StarsVip', -1041, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(7, 41, 'VIP', 'price_x', 'price_x', 30, 15, 'EUR', TRUE)"
        )

    estado_inicial = {
        "editing_plan": True,
        "editing_plan_id": 7,
        "edit_plan_step": 5,
        "edit_plan_provider": "stripe",
        "selected_group_admin": 41,
        "edit_plan_name": "VIP",
        "edit_plan_price": "price_x",
        "edit_plan_stripe_price_id": "price_x",
        "edit_plan_provider_price_id": "price_x",
        "edit_plan_duration": 30,
        "edit_plan_amount": 15,
    }

    escribir("EURO", estado_inicial)

    with clean_db.conn.cursor() as cur:
        cur.execute("SELECT currency FROM plans WHERE id=7")
        assert cur.fetchone()[0] == "EUR"


def test_choosing_auto_really_creates_the_price_at_the_end(clean_db, monkeypatch):
    """«auto» no es una promesa: al terminar tiene que existir el precio."""

    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append({"name": name, "amount_major": amount_major,
                        "currency": currency})
        return ("prod_1", "price_creado_1")

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (41, 'StarsVip', -1041, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(7, 41, 'Viejo', 'price_viejo', 'price_viejo', 30, 15, 'EUR', TRUE)"
        )

    estado = {
        "editing_plan": True,
        "editing_plan_id": 7,
        "edit_plan_step": 2,
        "edit_plan_provider": "stripe",
        "selected_group_admin": 41,
        "edit_plan_name": "Acceso 30 días",
    }

    escribir("auto", estado)
    escribir("30", estado)
    escribir("29", estado)
    respuestas, _estado = escribir("EUR", estado)

    with clean_db.conn.cursor() as cur:
        cur.execute("SELECT name, amount, stripe_price_id FROM plans WHERE id=7")
        nombre, importe, price_id = cur.fetchone()

    assert nombre == "Acceso 30 días"
    assert float(importe) == 29.0
    assert price_id == "price_creado_1", (
        "sin esto, «auto» dejaba el plan sin precio y sin poder cobrar"
    )
    assert creados[-1]["name"].endswith("Acceso 30 días"), (
        "y con el nombre nuevo, que es lo que se lee en la página de pago"
    )
    assert creados[-1]["name"].startswith("StarsVip · "), (
        "la página de pago tiene que decir a QUÉ comunidad se accede"
    )
    assert creados[-1]["amount_major"] == pytest.approx(29.0)
    assert any("Precio de Stripe" in (r or "") for r in respuestas)


# =========================
# EL PRECIO DE LO QUE VENDE LA PLATAFORMA
# =========================
# La pantalla que decide cuánto cobra la plataforma por publicar una comunidad
# leía una variable que no existía en ese momento: se asigna más abajo, dentro
# de OTRAS ramas del mismo manejador que aquí no se recorren. Escribir el precio
# reventaba con NameError y el administrador se quedaba mirando una pantalla que
# no contestaba.

def test_setting_the_publishing_price_answers_instead_of_exploding(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute("DELETE FROM commercial_plans")
        cur.execute(
            "INSERT INTO commercial_plans (id, product_type, name, "
            "duration_days, amount, is_active) VALUES "
            "(901, 'shared_bot_space', '1 mes', 30, NULL, TRUE)"
        )

    respuestas, _estado = escribir(
        "29", {"setting_platform_plan_price_id": 901}
    )

    assert respuestas, "sin respuesta, el administrador no sabe si se guardó"
    assert "Precio guardado" in respuestas[0]

    with clean_db.conn.cursor() as cur:
        cur.execute("SELECT amount FROM commercial_plans WHERE id=901")
        assert cur.fetchone()[0] == 2900, (
            "se teclean EUROS y commercial_plans guarda CÉNTIMOS"
        )


def test_a_price_that_is_not_a_number_is_explained(clean_db):
    respuestas, _estado = escribir(
        "veintinueve", {"setting_platform_plan_price_id": 901}
    )

    assert "no es un número" in respuestas[0]
