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

from db import conn


# Cuántas ofertas caben en la primera pantalla. Más que esto no es catálogo,
# es un muro: nadie elige entre quince cosas que no conoce.
MAX_OFERTAS = 6


def formato_periodo(duration_days):
    """'/mes', '/año', '/30 días' — lo que el comprador espera leer."""

    dias = int(duration_days or 0)

    if dias in (28, 29, 30, 31):
        return "/mes"

    if dias in (365, 366):
        return "/año"

    if dias in (7,):
        return "/semana"

    if dias in (90, 91, 92):
        return "/trimestre"

    if dias <= 0:
        return ""

    return f"/{dias} días"


def formato_precio(amount, currency, duration_days):
    """'15.00 EUR/mes'. amount de plans va en unidades mayores, no céntimos."""

    try:

        importe = f"{float(amount):.2f}".rstrip("0").rstrip(".")

    except (TypeError, ValueError):

        return None

    moneda = (currency or "EUR").upper()

    return f"{importe} {moneda}{formato_periodo(duration_days)}"


def fetch_sellable_communities(user_id, limit=MAX_OFERTAS):
    """Las comunidades que se pueden ofrecer AHORA, con su mejor precio.

    Devuelve una lista de diccionarios con lo que hace falta para vender:
    id, telegram_group_id, nombre, descripción, precio mínimo (con su plan
    para el atajo de un toque), cuántos planes hay y si esa persona ya tiene
    acceso.

    El orden es por precio de entrada: la puerta más baja primero, porque es
    la que convierte a un desconocido.
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
                      AND p.duration_days IS NOT NULL AND p.duration_days > 0
                    ORDER BY p.amount ASC, p.id ASC
                    LIMIT 1
                ) barato ON TRUE
                LEFT JOIN LATERAL (
                    SELECT COUNT(*) AS total
                    FROM plans p
                    WHERE p.group_id = g.id
                      AND COALESCE(p.is_active, TRUE) = TRUE
                      AND p.amount IS NOT NULL AND p.amount > 0
                      AND p.duration_days IS NOT NULL AND p.duration_days > 0
                ) cuantos ON TRUE
                LEFT JOIN group_delivery_health h ON h.group_id = g.id
                WHERE COALESCE(g.is_active, TRUE) = TRUE
                  AND g.telegram_group_id IS NOT NULL
                  AND g.telegram_group_id <> 0
                  AND COALESCE(g.is_free_group, FALSE) = FALSE
                  AND COALESCE(g.is_free, FALSE) = FALSE
                  AND (
                      COALESCE(g.is_marketplace_visible, FALSE) = TRUE
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

            """, {"uid": user_id, "limite": int(limit)})

            filas = cur.fetchall() or []

    except Exception as e:

        print("Oferta de inicio: error leyendo comunidades vendibles:", e)

        return []


    ofertas = []

    for fila in filas:

        (group_id, telegram_group_id, nombre, descripcion, plan_id, amount,
         currency, duration_days, price_id, provider, planes, ya_dentro) = fila

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


def build_single_offer_text(oferta):
    """La oferta cuando solo hay una cosa que vender: sin menú de por medio."""

    lineas = [f"🔓 {oferta['nombre']}"]

    if oferta["descripcion"]:

        # La descripción la escribe el propietario: se recorta, no se adorna.
        lineas.extend(["", oferta["descripcion"][:400]])

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
