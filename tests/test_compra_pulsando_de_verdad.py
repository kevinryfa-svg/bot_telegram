"""
Del mensaje que recibe el comprador hasta la página de Stripe, pulsando.

Diagnóstico de la caída de ventas: el bot escribió a ~200 personas en un mes,
con descuentos del 60%, y no llegó a crearse NI UN pago. El servidor de cobro
funciona (lo prueba test_checkout_route_end_to_end) y el escaparate anuncia bien.
Lo que nadie había ejecutado entero es el clic: este archivo lo hace.
"""

import flask
import pytest

import checkout_routes
from tests.comprador_simulado import (
    Comprador,
    botones_de,
    conectar_cobro_real,
    textos_de,
)


GRUPO = 1159
TG = -1001159


@pytest.fixture
def tienda_como_produccion(clean_db, monkeypatch):
    """StarsVip tal y como está en producción hoy."""

    db = clean_db

    with db.conn.cursor() as cur:

        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, preview_text) VALUES "
            "(%s, 'StarsVip', %s, TRUE, TRUE, 'Contenido exclusivo.')",
            (GRUPO, TG)
        )

        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active, payment_provider) VALUES "
            # Como en producción: el anual tiene DOS identificadores distintos
            # (price_id=price_1U6fHr…, stripe_price_id=price_1U6fP8…).
            "(24, %s, 'Acceso 360 días', 'price_24_viejo', 'price_24', 360, 29, 'EUR', TRUE, 'stripe'), "
            "(26, %s, 'Acceso 7 días', 'price_26', 'price_26', 7, 9, 'EUR', TRUE, 'stripe'), "
            "(27, %s, 'Acceso 30 días', 'price_27', 'price_27', 30, 15, 'EUR', TRUE, 'stripe')",
            (GRUPO, GRUPO, GRUPO)
        )

    monkeypatch.setattr(checkout_routes, "is_stripe_payments_enabled", lambda: True)

    sesiones = []

    class Sesion:
        id = "cs_prueba"
        url = "https://checkout.stripe.com/c/pay/cs_prueba"

    def crear(**kwargs):
        sesiones.append(kwargs)
        return Sesion()

    monkeypatch.setattr(
        checkout_routes.stripe.checkout.Session, "create", staticmethod(crear)
    )

    import stripe_catalog

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price",
        lambda name, amount_major, currency, metadata=None,
        recurring_interval_days=None: ("prod_of", f"price_oferta_{amount_major}")
    )

    import weekly_offer_service as ofs

    for plan in ofs.planes_ofertables(GRUPO):
        if plan["id"] == 26:
            ofs.crear_oferta(plan, percent=60)
        if plan["id"] == 27:
            ofs.crear_oferta(plan, percent=40)

    app = flask.Flask(__name__)
    checkout_routes.register_checkout_routes(app)

    conectar_cobro_real(monkeypatch, app)

    return {"db": db, "sesiones": sesiones}


def _recorrer(comprador, primeros, profundidad=4):
    """
    Pulsa en anchura todo lo que lleve hacia pagar. Devuelve (traza, urls).

    Se salta lo que aleja de la compra: soporte, dejar de recibir, volver.
    """

    alejan = ("public_support", "reengagement_stop", "public_back_start",
              "admin_", "public_monetize", "ai_", "lang_", "mis_subs")

    pendientes = [(c, 0) for c in primeros]
    vistos = set()
    traza = []
    urls = []

    while pendientes:

        data, nivel = pendientes.pop(0)

        if data in vistos or nivel > profundidad:
            continue

        vistos.add(data)

        llamadas, error = comprador.pulsar(data)

        textos = [textos_de(l) for l in llamadas if textos_de(l)]

        traza.append({
            "pulsado": data, "nivel": nivel, "error": error,
            "textos": textos,
        })

        for llamada in llamadas:

            for b in botones_de(llamada):

                if getattr(b, "url", None):
                    urls.append((data, b.text, b.url))

                cb = getattr(b, "callback_data", None)

                if cb and not cb.startswith(alejan):
                    pendientes.append((cb, nivel + 1))

    return traza, urls


def test_un_comprador_nuevo_llega_a_stripe_desde_el_reenganche(tienda_como_produccion):

    from reengagement_service import build_reengagement_keyboard
    import start_offer_service as sos

    ofertas = sos.fetch_sellable_communities(5001, limit=5)

    print("\nOFERTAS:", [(o.get("group_name") or o.get("nombre"), o.get("amount"), o["planes"],
                           sos.callback_de_oferta(o)) for o in ofertas])

    teclado = build_reengagement_keyboard(user_id=5001, ofertas=ofertas)

    primeros = [
        b.callback_data for fila in teclado.inline_keyboard for b in fila
        if b.callback_data
    ]

    print("BOTONES DEL MENSAJE:", primeros)

    comprador = Comprador(5001)

    traza, urls = _recorrer(comprador, primeros)

    for paso in traza:
        print(f"\n[{paso['nivel']}] PULSA {paso['pulsado']}"
              + (f"  ❌ {paso['error']}" if paso["error"] else ""))
        for t in paso["textos"][:3]:
            print("     →", t.replace("\n", " | ")[:220])

    print("\nURLS:", urls)
    print("SESIONES STRIPE:", len(tienda_como_produccion["sesiones"]))

    assert tienda_como_produccion["sesiones"], (
        "ningún camino desde el mensaje de reenganche llega a crear el pago"
    )
    assert any("checkout.stripe.com" in u for _, _, u in urls), (
        "se creó el pago pero el enlace no le llegó al comprador"
    )


# =========================
# CADA PLAN, CON SU PROPIO COMPRADOR
# =========================

def _botones_de_pago(llamadas):
    return [
        b for l in llamadas for b in botones_de(l)
        if (b.text or "").startswith("💳 Tarjeta")
    ]


@pytest.mark.parametrize("plan_id, comprador_id", [
    (26, 6026),   # 7 días, oferta -60% → 3,60 EUR
    (27, 6027),   # 30 días, oferta -40% → 9 EUR
    (24, 6024),   # 360 días, sin oferta, con price_id ≠ stripe_price_id
])
def test_cada_plan_de_la_lista_se_puede_pagar(tienda_como_produccion, plan_id,
                                              comprador_id):
    """
    LA AVERÍA DE LAS VENTAS. Los tres botones de la lista de planes contestaban
    «⚠️ Este plan no está configurado para Stripe»: el clic buscaba el precio en
    una columna donde no estaba.
    """

    comprador = Comprador(comprador_id)

    llamadas, error = comprador.pulsar(f"group_{GRUPO}")

    assert error is None, error

    botones = _botones_de_pago(llamadas)

    assert len(botones) == 3, "la lista tiene que ofrecer los tres planes"

    import weekly_offer_service as ofs
    from db import conn

    # Qué botón es el de este plan: el que lleva su precio vigente.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT " + ofs.sql_precio_vigente("p", "comprador")
            + " FROM plans p WHERE p.id = %(id)s",
            {"id": plan_id, "comprador": comprador_id}
        )
        precio = cur.fetchone()[0]

    boton = [b for b in botones if b.callback_data == precio]

    assert boton, f"no hay botón con el precio vigente del plan {plan_id}"

    llamadas, error = comprador.pulsar(precio)

    assert error is None, error

    textos = " ".join(textos_de(l) for l in llamadas)

    assert "no está configurado para Stripe" not in textos, (
        f"el plan {plan_id} sigue sin poder pagarse: {textos[:200]}"
    )

    urls = [
        b.url for l in llamadas for b in botones_de(l)
        if getattr(b, "url", None)
    ]

    assert any("checkout.stripe.com" in u for u in urls) or \
        "checkout.stripe.com" in textos, (
            f"el plan {plan_id} no llegó a la página de Stripe: {textos[:300]}"
        )


def test_se_cobra_el_precio_de_la_oferta_y_no_el_de_tarifa(tienda_como_produccion):
    """Pulsar el 3,60 € tiene que crear un cobro de 3,60 €, no de 9."""

    comprador = Comprador(6100)

    llamadas, _ = comprador.pulsar(f"group_{GRUPO}")

    oferta = [
        b for b in _botones_de_pago(llamadas) if "-60%" in (b.text or "")
    ]

    assert oferta, "el botón tiene que enseñar el descuento"

    comprador.pulsar(oferta[0].callback_data)

    sesiones = tienda_como_produccion["sesiones"]

    assert sesiones, "no se creó el cobro"

    precio_cobrado = sesiones[-1]["line_items"][0]["price"]

    assert precio_cobrado == oferta[0].callback_data, (
        "se cobra el precio del botón que se pulsó: el de la oferta"
    )


def test_un_boton_de_oferta_caducada_lo_dice_y_no_suena_a_averia(tienda_como_produccion):

    comprador = Comprador(6200)

    llamadas, _ = comprador.pulsar(f"group_{GRUPO}")

    oferta = [
        b for b in _botones_de_pago(llamadas) if "-60%" in (b.text or "")
    ][0]

    from db import conn

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE plan_offers SET ends_at = NOW() - INTERVAL '1 minute' "
            "WHERE stripe_price_id = %s",
            (oferta.callback_data,)
        )

    llamadas, error = comprador.pulsar(oferta.callback_data)

    textos = " ".join(textos_de(l) for l in llamadas)

    assert "ya ha terminado" in textos
    assert "No se te ha cobrado nada" in textos
    assert "no está configurado" not in textos


def test_si_vuelve_a_fallar_queda_rastro(tienda_como_produccion, capsys):
    """
    Este rechazo era INVISIBLE: no llegaba al servidor de cobro, así que no
    salía en ningún registro. Un mes de «nadie compra» sin una sola pista.
    """

    comprador = Comprador(6300)

    comprador.pulsar(f"group_{GRUPO}")
    capsys.readouterr()

    comprador.pulsar("price_que_no_existe_en_ningun_sitio")

    salida = capsys.readouterr().out

    assert "Venta rechazada" in salida
    assert "plan_no_encontrado_al_pulsar" in salida


# =========================
# TODAS LAS PUERTAS QUE LLEVAN A PAGAR
# =========================
# El bot no vende desde un sitio: escribe a la gente desde media docena de
# mensajes, y cada uno lleva su botón por su propio camino. La avería de arriba
# estaba en UNO. Aquí se pasa por todos, con un comprador nuevo cada vez.

def _llega_a_stripe(comprador, primeros, profundidad=4):
    """(llegó, camino, último_texto). Para en cuanto ve el enlace de Stripe."""

    alejan = ("public_support", "reengagement_stop", "public_back_start",
              "admin_", "public_monetize", "ai_", "lang_", "mis_subs",
              "favorite_", "unfavorite_", "marketplace_filter",
              "group_user_promo", "user_support", "support_help",
              "group_plans_help", "interest_stop", "abandoned_stop")

    pendientes = [(c, 0, [c]) for c in primeros]
    vistos = set()
    ultimo = ""

    while pendientes:

        data, nivel, camino = pendientes.pop(0)

        if data in vistos or nivel > profundidad:
            continue

        vistos.add(data)

        llamadas, error = comprador.pulsar(data)

        if error:
            return False, camino, f"EXCEPCIÓN: {error}"

        textos = " ".join(textos_de(l) for l in llamadas)
        ultimo = textos[:300]

        urls = [b.url for l in llamadas for b in botones_de(l)
                if getattr(b, "url", None)]

        if "checkout.stripe.com" in textos or any(
            "checkout.stripe.com" in u for u in urls
        ):
            return True, camino, ultimo

        for l in llamadas:
            for b in botones_de(l):
                cb = getattr(b, "callback_data", None)
                if cb and not cb.startswith(alejan):
                    pendientes.append((cb, nivel + 1, camino + [cb]))

    return False, camino, ultimo


def _puertas():
    """Cada mensaje que el bot manda a un comprador, con sus botones."""

    import abandoned_checkout_service as acs
    import interest_followup_service as ifs
    import renewal_service as rs
    import weekly_offer_service as ofs

    def cbs(teclado):
        return [b.callback_data for fila in teclado.inline_keyboard
                for b in fila if b.callback_data]

    puertas = {
        "carrito abandonado": lambda: cbs(acs.build_abandoned_keyboard(GRUPO)),
        "interesado que no compró": lambda: cbs(ifs.build_interest_keyboard(GRUPO)),
        "socio que se fue (winback)": lambda: cbs(rs.build_winback_keyboard(GRUPO)),
    }

    for plan_id in (26, 27):

        def ultimo_dia(plan_id=plan_id):
            return cbs(ofs._teclado_de_ultimo_dia({
                "group_id": GRUPO, "plan_id": plan_id,
                "amount": 3.6, "currency": "EUR",
            }))

        puertas[f"último día de oferta (plan {plan_id})"] = ultimo_dia

    return puertas


@pytest.mark.parametrize("puerta", list(_puertas().keys()))
def test_cada_mensaje_del_bot_lleva_hasta_el_pago(tienda_como_produccion, puerta):

    primeros = _puertas()[puerta]()

    assert primeros, f"«{puerta}» no tiene botones"

    comprador = Comprador(7000 + abs(hash(puerta)) % 900)

    llego, camino, ultimo = _llega_a_stripe(comprador, primeros)

    assert llego, (
        f"desde «{puerta}» no se llega a pagar.\n"
        f"  camino: {' → '.join(camino)}\n"
        f"  último que vio: {ultimo}"
    )


# =========================
# LA ALARMA QUE HABRÍA CAZADO ESTO EL PRIMER DÍA
# =========================

def test_la_comprobacion_horaria_mira_los_botones_de_la_lista(tienda_como_produccion):
    from sale_readiness_service import check_botones_de_la_lista

    rotos, comprobados = check_botones_de_la_lista()

    assert comprobados == 3, "los tres planes a la venta"
    assert rotos == [], rotos


def test_si_un_boton_no_lleva_a_su_plan_salta_la_alarma(tienda_como_produccion, monkeypatch):
    """
    Se rompe la regla a propósito, como estaba antes: el clic buscando solo
    por price_id. La comprobación tiene que decirlo.
    """

    import weekly_offer_service as ofs

    monkeypatch.setattr(
        ofs, "sql_plan_cobra_este_precio",
        lambda alias="p", param_precio="plan", param_persona=None:
            f"({alias}.price_id = %({param_precio})s)"
    )

    from sale_readiness_service import check_botones_de_la_lista

    rotos, comprobados = check_botones_de_la_lista()

    assert len(rotos) == 3, "los tres estaban rotos así en producción"
    assert all("no se encuentra ningún plan" in r["detalle"] for r in rotos)


def test_el_clic_del_bot_usa_la_regla_compartida():
    """
    Que nadie vuelva a escribir su propia búsqueda del plan en el clic: era
    una copia, y la copia se quedó atrás seis semanas.
    """

    fuente = open("callback_router.py", encoding="utf-8").read()

    inicio = fuente.index("LA AVERÍA QUE SE COMÍA LAS VENTAS")
    tramo = fuente[inicio:inicio + 4000]

    assert "sql_plan_cobra_este_precio(" in tramo
    assert "WHERE price_id=%s" not in tramo

    cobro = open("checkout_routes.py", encoding="utf-8").read()

    assert "sql_plan_cobra_este_precio(" in cobro, (
        "y el servidor de cobro, la MISMA"
    )


def test_la_limpieza_de_precios_lee_objetos_reales_del_sdk():
    """
    Los dobles eran diccionarios, así que las pruebas pasaban; en producción
    el SDK nuevo contestaba «'get' is a dict method, but a Price is not a dict»
    y la limpieza no funcionó ni un día.
    """

    import stripe

    from plan_price_service import _campo

    precio = stripe.Price.construct_from({
        "id": "price_x", "type": "one_time", "unit_amount": 900,
        "metadata": {"purpose": "group_access", "plan_id": "26"},
    }, "sk_test")

    assert _campo(precio, "id") == "price_x"
    assert _campo(precio, "unit_amount") == 900
    assert _campo(_campo(precio, "metadata"), "plan_id") == "26"
    assert _campo(precio, "no_existe", "x") == "x"
    assert _campo({"id": "d"}, "id") == "d"
