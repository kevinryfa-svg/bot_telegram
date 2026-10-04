"""
El embudo de ventas entero, etapa por etapa, en el registro del arranque.

Para decidir qué hacer cuando no se vende hay que saber DÓNDE se pierde la
gente, y la respuesta cambia todo:

  - si no llega nadie, el problema es de captación, y tocar el bot no sirve;
  - si llegan y no abren la comunidad, es la primera pantalla;
  - si abren los planes y no pulsan, es el precio o la oferta;
  - si pulsan y no llegan a Stripe, es una avería (como la de agosto-octubre);
  - si llegan a Stripe y no pagan, es la página de pago.

El panel tiene un embudo por comunidad de tres pasos. Este tiene seis, para
toda la plataforma, y sale en el registro del servidor: se puede leer sin abrir
Telegram y sin credenciales de la base de datos, que es exactamente lo que hace
falta cuando hay que diagnosticar desde fuera.

Se cuentan PERSONAS distintas, no pulsaciones. Y las etapas de pulsar se
cuentan por la clave del botón, porque eso es lo que guarda bot_user_events.
"""

from db import conn


PAGADO = ("paid", "completed", "succeeded")


ETAPAS = (
    ("llegan", "abren el bot (/start)"),
    ("ven", "ven una comunidad"),
    ("planes", "abren la lista de planes"),
    ("pulsan", "pulsan pagar"),
    ("stripe", "llegan a la página de pago"),
    ("pagan", "pagan"),
)


SQL_ETAPAS = {

    "llegan": """
        SELECT COUNT(DISTINCT user_id) FROM bot_user_events
        WHERE (event_type = 'start'
               OR (event_type = 'command' AND event_key LIKE '/start%%'))
          AND created_at >= NOW() - (%(dias)s || ' days')::interval
    """,

    "ven": """
        SELECT COUNT(DISTINCT user_id) FROM bot_user_events
        WHERE (event_type = 'community_viewed'
               OR (event_type = 'callback'
                   AND (event_key LIKE 'marketplace\\_group\\_%%'
                        OR event_key LIKE 'marketplace\\_preview\\_%%')))
          AND created_at >= NOW() - (%(dias)s || ' days')::interval
    """,

    "planes": """
        SELECT COUNT(DISTINCT user_id) FROM bot_user_events
        WHERE event_type = 'callback'
          AND event_key ~ '^group_[0-9]+$'
          AND created_at >= NOW() - (%(dias)s || ' days')::interval
    """,

    "pulsan": """
        SELECT COUNT(DISTINCT user_id) FROM bot_user_events
        WHERE event_type = 'callback'
          AND (event_key LIKE 'price\\_%%' OR event_key LIKE 'startbuy\\_%%')
          AND created_at >= NOW() - (%(dias)s || ' days')::interval
    """,

    "stripe": """
        SELECT COUNT(DISTINCT user_id) FROM payment_transactions
        WHERE COALESCE(purchase_type, 'group_access') = 'group_access'
          AND user_id IS NOT NULL
          AND created_at >= NOW() - (%(dias)s || ' days')::interval
    """,

    "pagan": """
        SELECT COUNT(DISTINCT user_id) FROM payments
        WHERE LOWER(COALESCE(status, '')) = ANY(%(pagado)s)
          AND payment_date >= NOW() - (%(dias)s || ' days')::interval
    """,
}


def fetch_embudo(dias=30):
    """{etapa: personas} o {etapa: None} donde no se pudo contar."""

    resultado = {}

    for clave, sql in SQL_ETAPAS.items():

        try:

            with conn.cursor() as cur:

                cur.execute(sql, {"dias": int(dias), "pagado": list(PAGADO)})

                resultado[clave] = int((cur.fetchone() or [0])[0] or 0)

        except Exception as e:

            conn.rollback()
            print(f"Embudo: no se pudo contar «{clave}»:", str(e)[:160])

            resultado[clave] = None

    return resultado


def fetch_audiencia():
    """
    A cuánta gente se le puede vender ahora mismo, sin captar a nadie nuevo.

    Es la otra mitad de la pregunta: un embudo vacío con una audiencia de dos
    mil personas se arregla escribiendo; con una audiencia de veinte, no.
    """

    consultas = {

        "alguna_vez": """
            SELECT COUNT(DISTINCT user_id) FROM bot_user_events
            WHERE user_id IS NOT NULL
        """,

        "contactables": """
            SELECT COUNT(DISTINCT e.user_id) FROM bot_user_events e
            WHERE e.user_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM user_reengagement r
                  WHERE r.user_id = e.user_id
                    AND (COALESCE(r.opted_out, FALSE)
                         OR COALESCE(r.is_blocked, FALSE)))
        """,

        "socios_activos": """
            SELECT COUNT(DISTINCT user_id) FROM users
            WHERE COALESCE(subscription_active, FALSE) = TRUE
              AND (expiration IS NULL OR expiration > NOW())
        """,

        "caducan_7_dias": """
            SELECT COUNT(DISTINCT user_id) FROM users
            WHERE expiration > NOW()
              AND expiration <= NOW() + INTERVAL '7 days'
        """,

        "caducados_90_dias": """
            SELECT COUNT(DISTINCT u.user_id) FROM users u
            WHERE u.expiration <= NOW()
              AND u.expiration > NOW() - INTERVAL '90 days'
              AND NOT EXISTS (
                  SELECT 1 FROM users v
                  WHERE v.user_id = u.user_id AND v.expiration > NOW())
        """,

        "pagaron_alguna_vez": """
            SELECT COUNT(DISTINCT user_id) FROM payments
            WHERE LOWER(COALESCE(status, '')) = ANY(%(pagado)s)
        """,

        "ingresos_30_dias_centimos": """
            SELECT COALESCE(SUM(amount), 0) FROM payments
            WHERE LOWER(COALESCE(status, '')) = ANY(%(pagado)s)
              AND payment_date >= NOW() - INTERVAL '30 days'
        """,
    }

    resultado = {}

    for clave, sql in consultas.items():

        try:

            with conn.cursor() as cur:

                cur.execute(sql, {"pagado": list(PAGADO)})

                resultado[clave] = int((cur.fetchone() or [0])[0] or 0)

        except Exception as e:

            conn.rollback()
            print(f"Audiencia: no se pudo contar «{clave}»:", str(e)[:160])

            resultado[clave] = None

    return resultado


def _num(valor):

    return "?" if valor is None else str(valor)


def linea_de_embudo(dias):

    e = fetch_embudo(dias)

    return (
        f"Embudo {dias} días: "
        + " → ".join(f"{_num(e[c])} {texto}" for c, texto in ETAPAS)
    )


def donde_se_pierde(dias=30):
    """
    La etapa con la mayor caída, en palabras. None si no hay datos para decir.

    Solo se nombra una caída cuando la etapa de arriba tiene gente: «de 0 a 0»
    no es una caída, es que no hay nadie.
    """

    e = fetch_embudo(dias)

    peor = None

    for (a, texto_a), (b, texto_b) in zip(ETAPAS, ETAPAS[1:]):

        arriba, abajo = e.get(a), e.get(b)

        if not arriba or abajo is None:
            continue

        perdidos = arriba - abajo

        if perdidos <= 0:
            continue

        if peor is None or perdidos > peor[0]:
            peor = (perdidos, arriba, texto_a, texto_b)

    if not peor:
        return None

    perdidos, arriba, texto_a, texto_b = peor

    return (
        f"La mayor caída ({dias} días): {perdidos} de {arriba} se quedan entre "
        f"«{texto_a}» y «{texto_b}»."
    )


def describe_fichas():
    """
    Qué ve un comprador en la ficha de cada comunidad a la venta.

    En producción el 88% de quien ve la ficha de StarsVip se va sin abrir los
    planes. Lo que la ficha enseña —descripción, foto, vídeo de muestra— lo
    pone el dueño desde el panel, y desde fuera no había forma de saber si
    estaba puesto. Una línea por comunidad visible.
    """

    from reengagement_service import VISIBLE_GROUP_CONDITIONS

    lineas = []

    # Una ficha visible en la que no se puede comprar nada es un desvío: quien
    # explora la abre, no encuentra cómo entrar y se va.
    try:

        from start_offer_service import fetch_sellable_communities

        vendibles = {
            o.get("group_id") for o in
            (fetch_sellable_communities(0, limit=100) or [])
        }

    except Exception:

        vendibles = set()

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT g.id, COALESCE(g.name, '?'),
                       COALESCE(g.preview_text, ''),
                       COALESCE(NULLIF(g.preview_image_file_id, ''),
                                NULLIF(g.preview_file_id, '')) IS NOT NULL,
                       NULLIF(g.preview_video_file_id, '') IS NOT NULL,
                       (SELECT COUNT(*) FROM group_preview_videos v
                         WHERE v.group_id = g.id AND v.is_active = TRUE),
                       COALESCE(NULLIF(g.category, ''), 'sin categoría')
                FROM groups g
                -- La MISMA definición de «visible» que usa el catálogo: una
                -- comunidad se ve por is_marketplace_visible O por
                -- public_visibility, y mirar solo la primera dejaba fuera
                -- justo a StarsVip.
                -- Y las que se venden aunque no estén en el catálogo: son las
                -- fichas que de verdad abre un comprador desde /start.
                WHERE (""" + VISIBLE_GROUP_CONDITIONS + """)
                   OR g.id = ANY(%(vendibles)s)
                ORDER BY g.id

            """, {"vendibles": list(vendibles) or [0]})

            filas = cur.fetchall() or []

    except Exception as e:

        conn.rollback()
        return [f"Fichas: no se pudieron leer ({str(e)[:160]})"]


    for gid, nombre, texto, foto, video, videos_dinamicos, categoria in filas:

        texto = (texto or "").strip()

        if not texto:
            descripcion = "SIN descripción"
        elif len(texto) < 60:
            descripcion = f"descripción de {len(texto)} caracteres: «{texto}»"
        else:
            descripcion = f"descripción de {len(texto)} caracteres"

        lineas.append(
            f"Ficha «{nombre}» (#{gid}, {'SE VENDE' if gid in vendibles else 'NO se vende'}): {descripcion} · "
            + ("con foto" if foto else "SIN foto") + " · "
            + ("con vídeo" if (video or videos_dinamicos) else "SIN vídeo")
            + f" · categoría {categoria}."
        )

    return lineas


def describe_para_el_arranque():
    """Las líneas del embudo para el registro. Nunca lanza."""

    lineas = []

    try:

        for dias in (7, 30, 90):
            lineas.append(linea_de_embudo(dias))

        caida = donde_se_pierde(30)

        if caida:
            lineas.append(caida)

        lineas.extend(describe_fichas())

        a = fetch_audiencia()

        euros = (
            "?" if a.get("ingresos_30_dias_centimos") is None
            else f"{a['ingresos_30_dias_centimos'] / 100:.2f} EUR"
        )

        lineas.append(
            "Audiencia: "
            f"{_num(a.get('alguna_vez'))} han usado el bot alguna vez, "
            f"{_num(a.get('contactables'))} se les puede escribir, "
            f"{_num(a.get('socios_activos'))} socios activos, "
            f"{_num(a.get('caducan_7_dias'))} caducan en 7 días, "
            f"{_num(a.get('caducados_90_dias'))} caducaron en 90 días sin "
            f"renovar, {_num(a.get('pagaron_alguna_vez'))} han pagado alguna "
            f"vez. Ingresos 30 días: {euros}."
        )

    except Exception as e:

        lineas.append(f"Embudo: no se pudo calcular ({str(e)[:200]})")

    return lineas
