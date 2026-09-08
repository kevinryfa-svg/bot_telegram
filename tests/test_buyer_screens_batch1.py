"""
Cinco agujeros del camino del comprador, encontrados leyendo las pantallas
como las lee alguien que va a pagar.

Los dos primeros cuestan dinero de verdad: uno deja entrar a quien la
comunidad ha decidido no admitir, y el otro cobra por un acceso que el bot no
puede conceder. Los otros tres son de los que no revientan nada y hacen que
alguien se lo piense: dos precios distintos en el mismo mensaje, dinero escrito
como no se escribe, y dos botones iguales.
"""

import pytest


# =========================
# LA VÍA RÁPIDA SE SALTABA LA PUERTA DE REGIÓN
# =========================
# Todos los caminos al cobro piden la ubicación cuando la comunidad la exige
# —PayPal, Revolut, ChangeNOW, Guardarian y el de precio de Stripe— y el de
# `startbuy_` no. Y ese es el más usado: el botón de un toque de /start, el
# enlace de un anuncio (?start=group_N) y los dos botones del aviso de
# renovación. O sea, se colaban justo los compradores más decididos.

def test_the_fast_lane_asks_for_the_region_like_everyone_else():
    fuente = open("callback_router.py", encoding="utf-8").read()

    pos = fuente.index('if data.startswith("startbuy_"):')
    trozo = fuente[pos:pos + 4000]

    assert "group_requires_location_gate" in trozo, (
        "la vía de más intención de compra era la única sin puerta de región"
    )

    # Y la pide ANTES de crear el cobro, no después.
    assert trozo.index("group_requires_location_gate") < \
        trozo.index("create_checkout_for_user"), (
        "pedirla después del cobro es cobrar primero y preguntar luego"
    )


def test_every_path_to_paying_has_the_gate():
    """Si alguien añade un camino nuevo al cobro, esto se entera."""

    fuente = open("callback_router.py", encoding="utf-8").read()

    puertas = fuente.count("group_requires_location_gate(group_id)")

    assert puertas >= 6, (
        f"solo {puertas} caminos comprueban la región; había 5 y falta el de "
        "la vía rápida"
    )


# =========================
# SE VENDÍA UN ACCESO QUE NO SE PUEDE CONCEDER
# =========================
# La concesión rechaza una duración fuera de rango —lanza «Duración de plan
# fuera de rango»— y el escaparate ya lo filtraba. La lista de planes no: se
# enseñaba el plan con su botón de pagar, el comprador pagaba y el acceso no se
# le podía dar. En producción hay uno de 1.300.000 días.

def test_the_plan_list_only_shows_what_can_be_delivered():
    fuente = open("callback_router.py", encoding="utf-8").read()

    pos = fuente.index('"grupo": group_id,\n                    "comprador": user_id,')
    trozo = fuente[max(0, pos - 2500):pos]

    assert "max_dias" in trozo
    assert "p.duration_days <= %(max_dias)s" in trozo
    assert "p.duration_days >= 1" in trozo, (
        "un plan de 0 días también revienta la concesión"
    )


def test_the_ceiling_is_the_one_the_grant_uses():
    """Dos techos distintos volverían a abrir el mismo agujero."""

    import callback_router as cr
    from payment_access_service import MAX_PLAN_DURATION_DAYS

    assert cr.MAX_PLAN_DURATION_DAYS == MAX_PLAN_DURATION_DAYS


# =========================
# DOS PRECIOS EN EL MISMO MENSAJE
# =========================
# El aviso de renovación decía el precio del plan más BARATO de la comunidad,
# mientras el botón de un toque justo debajo lleva el plan que compró esa
# persona. Un socio anual leía «Renovar cuesta 15 EUR» encima de un botón que
# decía 120 EUR.

@pytest.fixture
def socio_anual(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (94, 'StarsVip', -1094, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(941, 94, 'Semana', 'price_s94', 'price_s94', 7, 9, 'EUR', TRUE), "
            "(942, 94, 'Anual', 'price_a94', 'price_a94', 360, 120, 'EUR', TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, subscription_active, expiration) "
            "VALUES (9401, 94, TRUE, NOW() + INTERVAL '3 days')"
        )
        cur.execute(
            "INSERT INTO payments (user_id, group_id, amount, currency, status, plan) "
            "VALUES (9401, 94, 12000, 'EUR', 'paid', 'Anual')"
        )

    return db


def test_the_notice_quotes_the_plan_the_button_charges(socio_anual):
    import renewal_service as rs

    precio = rs.precio_de_renovacion(9401, 94)

    assert precio == "120 EUR", (
        "el suyo, no los 9 EUR de la semana que es el plan más barato"
    )


def test_whoever_kept_an_old_price_keeps_reading_it(socio_anual):
    """Quien se suscribió antes de una subida conserva su precio."""

    import renewal_service as rs

    with socio_anual.conn.cursor() as cur:
        # Su plan se renombra: ya no empareja, así que manda su último cobro.
        cur.execute("UPDATE plans SET name='Anual 2027' WHERE id=942")
        cur.execute("UPDATE payments SET amount=9900 WHERE user_id=9401")

    assert rs.precio_de_renovacion(9401, 94) == "99 EUR"


def test_a_stranger_falls_back_to_the_entry_price(socio_anual):
    import renewal_service as rs

    assert rs.precio_de_renovacion(9999, 94) == "9 EUR"


def test_the_notice_never_shows_the_database_dot(socio_anual):
    """«15.00 EUR» es como lo guarda la base, no como se lee un precio."""

    import renewal_service as rs

    with socio_anual.conn.cursor() as cur:
        cur.execute("UPDATE plans SET name='Otro' WHERE id=942")
        cur.execute("UPDATE payments SET amount=360 WHERE user_id=9401")

    assert rs.precio_de_renovacion(9401, 94) == "3,60 EUR"


# =========================
# DINERO ESCRITO A MANO EN EL ÚLTIMO BOTÓN
# =========================

def test_nobody_writes_the_money_by_hand_in_a_button():
    """Con una oferta con céntimos, «3.6 EURO» justo antes de pagar."""

    import pathlib
    import re

    patron = re.compile(r"\{amount\}\s*\{currency\}")

    culpables = []

    for nombre in ("renewal_service.py", "plan_switch_service.py",
                   "mysub_callbacks.py"):

        for numero, linea in enumerate(
            pathlib.Path(nombre).read_text(encoding="utf-8").splitlines(),
            start=1,
        ):

            if patron.search(linea):
                culpables.append(f"{nombre}:{numero}")

    assert culpables == [], (
        "usa formato_importe(): " + ", ".join(culpables)
    )


# =========================
# DOS BOTONES IGUALES
# =========================

def test_the_expired_screen_has_one_button_not_two():
    import callback_router as cr

    teclado = cr.build_existing_group_access_keyboard(
        94, {"subscription_status": "expired"}
    )

    callbacks = [b.callback_data for f in teclado.inline_keyboard for b in f]

    assert callbacks.count("group_94") == 1, (
        "había dos etiquetas distintas para el MISMO destino: se pulsa una, "
        "y quien cree haberse equivocado pulsa la otra y le sale lo mismo"
    )

    etiquetas = [b.text for f in teclado.inline_keyboard for b in f]

    assert any("precios" in e for e in etiquetas), (
        "y ninguna decía que ahí se ven los precios"
    )
