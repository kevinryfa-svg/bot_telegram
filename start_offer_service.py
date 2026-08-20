"""
Que /start venda, en vez de dar la bienvenida.

Los datos de producción dijeron el problema sin margen de duda: 297 personas
han pasado por el bot y ninguna ha pagado. Y la primera pantalla que veían
decía «Bienvenido… selecciona una opción», con un botón por comunidad que
ponía «➡️ Ver comunidad — X». Sin precio, sin qué es, sin por qué entrar. El
precio no aparecía hasta el TERCER toque, y hasta el enlace de pago había
cuatro.

Una tienda que no pone el precio en el escaparate no vende: filtra a la gente
por paciencia, no por interés.

Lo que hace este módulo:

  EL PRECIO EN EL BOTÓN   Cada comunidad se ofrece con su precio real mínimo
                          y su periodo: «VIP Fitness — 15.00 EUR/mes». Quien
                          sigue después de ver el precio está cualificado;
                          quien no, se va sin gastar cuatro pantallas.

  UNA SOLA COMUNIDAD,     Si solo hay una cosa que vender, un menú es un
  UNA SOLA OFERTA         estorbo: se enseña la oferta directamente, con su
                          descripción y su precio, y el botón de comprar.

  UN TOQUE HASTA PAGAR    Con un único plan, el botón lleva DIRECTO al
                          enlace de pago con el mismo callback que usaría la
                          lista de planes. Con varios, a elegir plan. Nunca
                          a una tarjeta intermedia que no añade nada.

  NO SE OFRECE LO QUE     Una comunidad sin plan usable, o cuya entrega está
  NO SE PUEDE ENTREGAR    confirmada como rota, no se enseña como compra. El
                          bot ya se niega a cobrar en ese estado: ofrecerlo
                          sería prometer en falso y cobrar la frustración.
                          Con la entrega SIN COMPROBAR sí se ofrece, que es
                          lo que hace el resto del sistema ante la duda.

  A QUIEN YA ESTÁ         Al socio con acceso vivo no se le vende otra vez:
  DENTRO, SU ACCESO       su botón lleva a «Mis accesos».
"""

import os

from db import conn
from payment_access_service import MAX_PLAN_DURATION_DAYS


# Cuántas ofertas caben en la primera pantalla. Más que esto no es catálogo,
# es un muro: nadie elige entre quince cosas que no conoce.
MAX_OFERTAS = 6


def formato_periodo(duration_days):
    """'/mes', '/año', '/30 días' — lo que el comprador espera leer.

    El 0 no es «sin periodo»: en plans significa acceso permanente, y así lo
    entrega el cobro (expiration = None). Decir «7 EUR» a secas donde el
    comprador espera un periodo es la diferencia entre parecer una cuota y ser
    lo que es: un pago único.
    """

    dias = int(duration_days or 0)

    if dias == 0:
        return " para siempre"

    if dias in (28, 29, 30, 31):
        return "/mes"

    if dias in (365, 366):
        return "/año"

    if dias in (7,):
        return "/semana"

    if dias in (90, 91, 92):
        return "/trimestre"

    if dias < 0:
        return ""

    return f"/{dias} días"


# Alias de moneda que se ven en los datos reales y no son códigos ISO. Solo
# están los INEQUÍVOCOS: «€» y «EURO» no pueden ser otra cosa que EUR. «$» no
# está a propósito, porque son al menos cinco monedas distintas, y adivinar cuál
# es adivinar el precio.
ALIAS_DE_MONEDA = {
    "EURO": "EUR",
    "EUROS": "EUR",
    "€": "EUR",
}


def normaliza_moneda_para_mostrar(currency):
    """El código como se le ENSEÑA al comprador. No toca el dato guardado.

    En producción el plan vendible tenía la moneda escrita «EURO», y el botón
    decía «7 EURO/360 días». No rompía el cobro —el price_id de Stripe lleva su
    propia moneda—, pero un precio con la moneda mal escrita es lo último que
    quiere leer alguien antes de dar su tarjeta.

    Normalizar aquí y no en la base de datos es deliberado: reescribir el campo
    de moneda de un plan es cambiar un dato de dinero por una suposición mía. Lo
    que se arregla es cómo se lee; que el dato esté bien se le pide a su dueño,
    y el panel «¿Puedo vender?» se lo dice.
    """

    moneda = str(currency or "EUR").strip().upper()

    return ALIAS_DE_MONEDA.get(moneda, moneda)


def formato_precio(amount, currency, duration_days):
    """'15.00 EUR/mes'. amount de plans va en unidades mayores, no céntimos."""

    try:

        importe = f"{float(amount):.2f}".rstrip("0").rstrip(".")

    except (TypeError, ValueError):

        return None

    moneda = normaliza_moneda_para_mostrar(currency)

    return f"{importe} {moneda}{formato_periodo(duration_days)}"


def fetch_sellable_communities(user_id, limit=MAX_OFERTAS, solo_grupo=None,
                               exigir_visibilidad=True):
    """Las comunidades que se pueden ofrecer AHORA, con su mejor precio.

    Devuelve una lista de diccionarios con lo que hace falta para vender:
    id, telegram_group_id, nombre, descripción, precio mínimo (con su plan
    para el atajo de un toque), cuántos planes hay y si esa persona ya tiene
    acceso.

    El orden es por precio de entrada: la puerta más baja primero, porque es
    la que convierte a un desconocido.

    Con `solo_grupo` se pregunta por UNA comunidad concreta: es el caso del
    enlace directo de un anuncio, donde no hay escaparate que ordenar.

    Y ahí `exigir_visibilidad=False` tiene sentido: los filtros de visibilidad
    deciden qué se EXPONE en el escaparate, no a quién se le permite comprar
    lo que ha venido a comprar. Quien llega con el enlace del anuncio del
    propietario ya ha sido invitado por él. Lo que NO se relaja es nada de lo
    que hace falta para entregar: comunidad activa, plan usable, no gratuita y
    la entrega sin descartar.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT g.id,
                       g.telegram_group_id,
                       COALESCE(NULLIF(g.name, ''), 'la comunidad'),
                       -- El texto descriptivo de una comunidad vive en
                       -- preview_text: groups NO tiene columna description, y
                       -- pedirla reventaba la consulta entera (con ella, /start
                       -- se habría quedado sin ofertas en silencio).
                       COALESCE(NULLIF(g.preview_text, ''), ''),
                       barato.plan_id,
                       barato.amount,
                       barato.currency,
                       barato.duration_days,
                       barato.price_id,
                       barato.provider,
                       cuantos.total,
                       (
                           SELECT COUNT(*)
                           FROM users u2
                           WHERE u2.group_id = g.id
                             AND (
                                 u2.expiration IS NULL
                                 OR u2.expiration > NOW()
                             )
                       ) AS miembros,
                       EXISTS (
                           SELECT 1 FROM users u
                           WHERE u.user_id = %(uid)s
                             AND u.group_id = g.id
                             AND (u.expiration IS NULL OR u.expiration > NOW())
                       ) AS ya_dentro
                FROM groups g
                LEFT JOIN LATERAL (
                    SELECT p.id AS plan_id,
                           p.amount,
                           COALESCE(NULLIF(p.currency, ''), 'EUR') AS currency,
                           p.duration_days,
                           COALESCE(NULLIF(p.stripe_price_id, ''), p.price_id) AS price_id,
                           COALESCE(NULLIF(p.payment_provider, ''), 'stripe') AS provider
                    FROM plans p
                    WHERE p.group_id = g.id
                      AND COALESCE(p.is_active, TRUE) = TRUE
                      AND p.amount IS NOT NULL AND p.amount > 0
                      AND p.duration_days IS NOT NULL
                      AND p.duration_days > 0
                      -- El techo es el mismo que usa la concesión de acceso:
                      -- por encima, el cobro se NIEGA a convertir el pago en
                      -- acceso, así que ofrecerlo es cobrar sin entregar. En
                      -- producción la ÚNICA comunidad vendible tenía un plan
                      -- de 1.300.000 días.
                      --
                      -- El 0 (acceso permanente para la concesión) se queda
                      -- fuera a propósito: ningún asistente del bot puede
                      -- crear un plan con 0 —todos exigen entre 1 y el
                      -- techo—, así que un 0 en la tabla no es una decisión,
                      -- es un dato anómalo. Venderlo como acceso permanente
                      -- regalaría acceso de por vida al precio de un mes, y
                      -- eso no se puede deshacer; no venderlo solo deja un
                      -- plan sin usar, y el panel del propietario lo señala.
                      AND p.duration_days <= %(max_dias)s
                    ORDER BY p.amount ASC, p.id ASC
                    LIMIT 1
                ) barato ON TRUE
                LEFT JOIN LATERAL (
                    SELECT COUNT(*) AS total
                    FROM plans p
                    WHERE p.group_id = g.id
                      AND COALESCE(p.is_active, TRUE) = TRUE
                      AND p.amount IS NOT NULL AND p.amount > 0
                      AND p.duration_days IS NOT NULL
                      AND p.duration_days > 0
                      AND p.duration_days <= %(max_dias)s
                ) cuantos ON TRUE
                LEFT JOIN group_delivery_health h ON h.group_id = g.id
                WHERE COALESCE(g.is_active, TRUE) = TRUE
                  AND g.telegram_group_id IS NOT NULL
                  AND g.telegram_group_id <> 0
                  AND COALESCE(g.is_free_group, FALSE) = FALSE
                  AND COALESCE(g.is_free, FALSE) = FALSE
                  AND (%(solo_grupo)s IS NULL OR g.id = %(solo_grupo)s)
                  AND (
                      %(sin_visibilidad)s
                      OR COALESCE(g.is_marketplace_visible, FALSE) = TRUE
                      OR COALESCE(g.is_main_menu_visible, FALSE) = TRUE
                      OR COALESCE(g.public_visibility, 'start_home')
                         IN ('start_home', 'explore_only', 'both')
                  )
                  AND barato.plan_id IS NOT NULL
                  -- Entrega roja CONFIRMADA fuera; sin comprobar, dentro:
                  -- ante la duda se deja vender, como el resto del sistema.
                  AND COALESCE(h.can_deliver, TRUE) = TRUE
                ORDER BY barato.amount ASC, g.id ASC
                LIMIT %(limite)s

            """, {
                "uid": user_id,
                "limite": int(limit),
                "max_dias": MAX_PLAN_DURATION_DAYS,
                "solo_grupo": int(solo_grupo) if solo_grupo else None,
                "sin_visibilidad": not exigir_visibilidad,
            })

            filas = cur.fetchall() or []

    except Exception as e:

        print("Oferta de inicio: error leyendo comunidades vendibles:", e)

        return []


    ofertas = []

    for fila in filas:

        (group_id, telegram_group_id, nombre, descripcion, plan_id, amount,
         currency, duration_days, price_id, provider, planes, miembros,
         ya_dentro) = fila

        ofertas.append({
            "group_id": group_id,
            "telegram_group_id": telegram_group_id,
            "nombre": nombre,
            "descripcion": (descripcion or "").strip(),
            "plan_id": plan_id,
            "precio": formato_precio(amount, currency, duration_days),
            "price_id": price_id,
            "provider": provider,
            "planes": int(planes or 0),
            "miembros": int(miembros or 0),
            "ya_dentro": bool(ya_dentro),
        })

    return ofertas


def callback_de_compra(oferta):
    """El callback que menos toques necesita para pagar ESA oferta.

    Con un solo plan se salta la lista y va al enlace de pago con el mismo
    callback que usaría la lista (la regla vive en renewal_service: un solo
    sitio decide cómo se paga cada proveedor). Con varios planes, a elegir.
    """

    if oferta["planes"] == 1:

        proveedor = (oferta["provider"] or "stripe").strip().lower()

        if proveedor == "stripe" and oferta["price_id"]:

            # NO se usa el price_id a secas, que es lo que pulsa la lista de
            # planes: esa rama del router saca el grupo de
            # user_data["selected_group"], y en /start eso no existe todavía —
            # el botón habría muerto con «esta opción ya no está disponible».
            # Este callback lleva el grupo y el plan dentro.
            return f"startbuy_{oferta['group_id']}_{oferta['plan_id']}"

        if proveedor in ("paypal", "revolut", "changenow", "guardarian"):

            # Estos ya llevan su grupo en el callback y lo fijan ellos.
            return f"{proveedor}_group_plan_{oferta['group_id']}_{oferta['plan_id']}"

    return f"group_{oferta['group_id']}"


def etiqueta_de_oferta(oferta):
    """El texto del botón. Con precio, siempre."""

    if oferta["ya_dentro"]:
        return f"🎟 Tu acceso — {oferta['nombre']}"

    if oferta["precio"]:
        return f"💳 {oferta['nombre']} — {oferta['precio']}"

    return f"➡️ {oferta['nombre']}"


def callback_de_oferta(oferta):
    """Dónde lleva el botón: a su acceso si ya está dentro, o a pagar."""

    if oferta["ya_dentro"]:
        return f"mysub_{oferta['telegram_group_id']}"

    return callback_de_compra(oferta)


# A partir de cuántos socios la cifra ayuda a vender. Por debajo, decirla es
# peor que callarla: «1 persona dentro» es un argumento en contra. Es la misma
# disciplina que la de los porcentajes sin base (regla 7).
MIN_MIEMBROS_PARA_ENSENAR = int(
    os.environ.get("MIN_MIEMBROS_PARA_ENSENAR", "5")
)


def frase_de_miembros(oferta):
    """«👥 23 personas dentro ahora mismo». None si el número no ayuda.

    Sale de contar accesos vivos de verdad, no de un número inventado ni
    redondeado: si alguien lo comprueba, tiene que cuadrar.
    """

    miembros = int((oferta or {}).get("miembros") or 0)

    if miembros < MIN_MIEMBROS_PARA_ENSENAR:
        return None

    return f"👥 {miembros} personas dentro ahora mismo."


def build_single_offer_text(oferta):
    """La oferta cuando solo hay una cosa que vender: sin menú de por medio."""

    lineas = [f"🔓 {oferta['nombre']}"]

    if oferta["descripcion"]:

        # La descripción la escribe el propietario: se recorta, no se adorna.
        lineas.extend(["", oferta["descripcion"][:400]])

    social = frase_de_miembros(oferta)

    if social:

        # Delante del precio a propósito: lo que convence a un desconocido es
        # que ahí dentro hay gente, y eso se lee ANTES de mirar cuánto cuesta.
        lineas.extend(["", social])

    if oferta["precio"]:

        lineas.extend(["", f"Precio: {oferta['precio']}"])

    lineas.extend([
        "",
        "El acceso es automático: en cuanto se confirma el pago recibes aquí "
        "mismo tu enlace de entrada, sin esperar a que nadie te lo mande a "
        "mano.",
    ])

    return "\n".join(lineas)


def build_offer_intro(ofertas):
    """La cabecera cuando hay varias: lo que se vende y desde cuánto."""

    comprables = [o for o in ofertas if not o["ya_dentro"] and o["precio"]]

    if not comprables:
        return None

    cuantas = len(comprables)

    if cuantas == 1:
        return "🔓 Acceso disponible ahora mismo:"

    return (
        f"🔓 {cuantas} comunidades con acceso inmediato. El precio está en "
        "cada botón; el acceso llega solo en cuanto se confirma el pago:"
    )


def fetch_offer_for_group(group_id, user_id):
    """La oferta de UNA comunidad, la del enlace de un anuncio. None si no hay.

    None significa siempre lo mismo: esa comunidad no se puede vender ahora
    mismo (no existe, está apagada, es gratuita, no tiene plan usable o la
    entrega está descartada). Quien llame cae al menú de siempre — un enlace
    de un anuncio no puede acabar en un callejón, porque el clic ya está
    pagado.
    """

    try:

        group_id = int(group_id)

    except (TypeError, ValueError):

        return None

    ofertas = fetch_sellable_communities(
        user_id, limit=1, solo_grupo=group_id, exigir_visibilidad=False
    )

    return ofertas[0] if ofertas else None


def parse_group_payload(carga):
    """'group_51' -> 51. None si la carga no es un enlace de comunidad.

    Se valida aquí y no en el sitio de uso porque esta carga viene de fuera:
    la escribe quien quiera en la barra de direcciones de Telegram.
    """

    if not carga or not carga.startswith("group_"):
        return None

    resto = carga[len("group_"):]

    if not resto.isdigit():
        return None

    try:

        valor = int(resto)

    except (TypeError, ValueError):

        return None

    return valor if valor > 0 else None


def etiqueta_de_compra_directa(oferta):
    """El botón de la pantalla de UNA oferta: el nombre ya está en el texto.

    Repetir ahí el nombre de la comunidad gasta el ancho del botón en algo que
    la persona acaba de leer dos líneas más arriba. Lo que sí va, siempre, es
    el precio: un botón de pago sin precio es una trampa.
    """

    if oferta["precio"]:
        return f"💳 Entrar ahora — {oferta['precio']}"

    return "💳 Entrar ahora"


def describe_shop_window():
    """Una línea con el estado del escaparate, para el arranque.

    Es el dato de negocio más importante del sistema y el único que no se
    puede leer en ninguna pantalla: si no hay ninguna comunidad vendible,
    /start no tiene nada que vender y da igual lo bien redactado que esté.
    Un bot que arranca sin escaparate no lo dice por ningún sitio, y ese
    silencio es el que deja pasar meses sin una sola venta.

    Se pregunta con user_id=0 a propósito: nadie tiene acceso con ese id, así
    que lo que sale es el escaparate tal y como lo ve un desconocido.
    """

    try:

        ofertas = fetch_sellable_communities(0, limit=100)

    except Exception as e:

        return f"Escaparate: no se pudo comprobar ({str(e)[:120]})."

    # Un escaparate vacío puede estar vacío por falta de comunidades o porque
    # las que hay tienen planes que el cobro se niega a entregar. Son dos
    # problemas distintos con arreglos distintos, así que se distinguen: si no,
    # el arreglo del segundo se busca en el sitio del primero.
    imposibles = contar_planes_no_entregables()

    aviso = ""

    if imposibles:

        aviso = (
            f" Además hay {imposibles} plan(es) activo(s) con una duración de "
            f"más de {MAX_PLAN_DURATION_DAYS} días: no se ofrecen porque el "
            "cobro no los puede convertir en acceso. Se corrigen poniendo los "
            "días reales, o 0 para acceso permanente."
        )


    if not ofertas:

        return (
            "Escaparate: 0 comunidades vendibles — /start no tiene nada que "
            "vender. Hace falta al menos una comunidad activa, no gratuita, "
            "con un plan activo con importe y una duración entregable, y la "
            "entrega sin descartar." + aviso
        )

    precios = [o["precio"] for o in ofertas if o["precio"]]

    return (
        f"Escaparate: {len(ofertas)} comunidad(es) vendible(s)"
        + (f", la más barata a {precios[0]}." if precios else ".")
        + aviso
    )


def contar_planes_no_entregables():
    """Planes activos cuya duración el cobro se niega a convertir en acceso.

    Son el peor estado posible de un catálogo: se pueden enseñar, se pueden
    cobrar, y el acceso no sale. Desde este cambio no se enseñan, y este
    contador es lo que evita que dejar de enseñarlos los haga invisibles
    también para quien tiene que corregirlos.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM plans
                WHERE COALESCE(is_active, TRUE) = TRUE
                  AND duration_days IS NOT NULL
                  AND duration_days > %s

            """, (MAX_PLAN_DURATION_DAYS,))

            fila = cur.fetchone()

            return int(fila[0] or 0) if fila else 0

    except Exception as e:

        print("Escaparate: error contando planes no entregables:", e)

        return 0
