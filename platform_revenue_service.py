"""
Los ingresos de la PLATAFORMA entera, para el ojo del super admin.

La pantalla «Ingresos» del menú de negocio tenía tres mentiras de dinero:

  1. No filtraba el estado: las devoluciones contaban como ingreso.
  2. MAX(currency) mezclaba monedas: 15 EUR + 15 USD salían sumados bajo
     la etiqueta que tocara — el pecado exacto que el panel del propietario
     evita a propósito.
  3. Mostraba céntimos como si fueran unidades: "1500 EUR" por 15 euros.

Este servicio es la versión verdadera: por moneda siempre, solo pagos
cobrados, céntimos divididos al mostrarse. El super admin ve la foto global
(ventanas, proveedores, top de comunidades, suscriptores); un admin acotado
a sus grupos ve lo suyo con las mismas reglas.
"""

from db import conn
from owner_revenue_service import PAID_STATUSES, formato_importe


def fetch_platform_windows():
    """Ingresos por ventana temporal y moneda, de toda la plataforma."""

    resumen = {"mes_actual": [], "mes_anterior": [], "dias_30": [], "historico": []}

    ventanas = (
        ("mes_actual", "payment_date >= date_trunc('month', NOW())"),
        ("mes_anterior",
         "payment_date >= date_trunc('month', NOW()) - INTERVAL '1 month' "
         "AND payment_date < date_trunc('month', NOW())"),
        ("dias_30", "payment_date >= NOW() - INTERVAL '30 days'"),
        ("historico", "TRUE"),
    )

    try:

        with conn.cursor() as cur:

            for clave, condicion in ventanas:

                cur.execute(f"""

                    SELECT COALESCE(NULLIF(UPPER(currency), ''), 'EUR'),
                           COALESCE(SUM(amount), 0),
                           COUNT(*)
                    FROM payments
                    WHERE LOWER(COALESCE(status, '')) IN %s
                      AND {condicion}
                    GROUP BY 1
                    ORDER BY 2 DESC

                """, (PAID_STATUSES,))

                resumen[clave] = cur.fetchall() or []

    except Exception as e:

        print("Plataforma: error leyendo ventanas:", e)


    return resumen


def fetch_provider_split_30d():
    """
    Qué proveedor trae el dinero (30 días), desde payment_transactions, que
    es la única tabla que sabe el proveedor. [(provider, currency, total, n)]
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(provider, '¿?'),
                       COALESCE(NULLIF(UPPER(currency), ''), 'EUR'),
                       COALESCE(SUM(amount), 0),
                       COUNT(*)
                FROM payment_transactions
                WHERE status = 'paid'
                  AND purchase_type = 'group_access'
                  AND COALESCE(updated_at, created_at) >= NOW() - INTERVAL '30 days'
                GROUP BY 1, 2
                ORDER BY 3 DESC

            """)

            return cur.fetchall() or []

    except Exception as e:

        print("Plataforma: error leyendo proveedores:", e)

        return []


def fetch_top_groups_30d(limit=5):
    """Las comunidades que más facturan (30 días), por moneda."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(g.name, 'Comunidad ' || p.group_id),
                       COALESCE(NULLIF(UPPER(p.currency), ''), 'EUR'),
                       COALESCE(SUM(p.amount), 0),
                       COUNT(*)
                FROM payments p
                LEFT JOIN groups g ON g.id = p.group_id
                WHERE LOWER(COALESCE(p.status, '')) IN %s
                  AND p.payment_date >= NOW() - INTERVAL '30 days'
                GROUP BY 1, 2
                ORDER BY 3 DESC
                LIMIT %s

            """, (PAID_STATUSES, int(limit)))

            return cur.fetchall() or []

    except Exception as e:

        print("Plataforma: error leyendo el top de comunidades:", e)

        return []


def fetch_platform_customers():
    """Los números de socios de toda la plataforma."""

    datos = {"activos": 0, "altas_mes": 0, "suscriptores": 0}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT
                    COUNT(*) FILTER (
                        WHERE COALESCE(subscription_active, FALSE) = TRUE
                          AND (expiration IS NULL OR expiration > NOW())
                    ),
                    COUNT(*) FILTER (
                        WHERE created_at >= date_trunc('month', NOW())
                    ),
                    COUNT(*) FILTER (
                        WHERE COALESCE(subscription_active, FALSE) = TRUE
                          AND (
                              stripe_subscription_id IS NOT NULL
                              OR EXISTS (
                                  SELECT 1 FROM payment_transactions pt
                                  WHERE pt.provider = 'paypal'
                                    AND pt.user_id = users.user_id
                                    AND pt.group_id = users.group_id
                                    AND pt.purchase_type = 'group_access'
                                    AND pt.status = 'paid'
                                    AND pt.external_checkout_id IS NOT NULL
                              )
                          )
                    )
                FROM users

            """)

            fila = cur.fetchone()

            if fila:

                datos["activos"], datos["altas_mes"], datos["suscriptores"] = fila

    except Exception as e:

        print("Plataforma: error leyendo socios:", e)


    return datos


def formato_filas(filas):
    """[(currency, total, n)] -> '15.00 EUR (1 pago)' — por moneda, siempre."""

    if not filas:

        return "0.00 EUR (0 pagos)"


    partes = []

    for currency, total, pagos in filas:

        etiqueta = "pago" if pagos == 1 else "pagos"
        partes.append(f"{formato_importe(total, currency)} ({pagos} {etiqueta})")


    return " · ".join(partes)


def build_platform_revenue_text():
    """La foto global que no existía en ningún sitio."""

    ventanas = fetch_platform_windows()
    proveedores = fetch_provider_split_30d()
    top = fetch_top_groups_30d()
    socios = fetch_platform_customers()

    anterior = {c: t for c, t, _n in ventanas["mes_anterior"]}

    linea_mes = formato_filas(ventanas["mes_actual"])

    comparado = []

    for currency, total, _n in ventanas["mes_actual"]:

        previo = anterior.get(currency)

        if previo:

            delta = (int(total) - int(previo)) * 100 // int(previo)
            signo = "+" if delta >= 0 else ""
            comparado.append(f"{currency} {signo}{delta}% vs mes anterior")


    lineas = [
        "💰 Ingresos de la plataforma",
        "",
        f"Este mes: {linea_mes}",
    ]

    if comparado:

        lineas.append(f"    ({' · '.join(comparado)})")


    lineas.extend([
        f"Últimos 30 días: {formato_filas(ventanas['dias_30'])}",
        f"Total histórico: {formato_filas(ventanas['historico'])}",
    ])


    if proveedores:

        lineas.extend(["", "🏦 Por proveedor (30 días)"])

        for provider, currency, total, n in proveedores:

            lineas.append(
                f"• {provider}: {formato_importe(total, currency)} ({n})"
            )


    if top:

        lineas.extend(["", "🏆 Comunidades que más facturan (30 días)"])

        for nombre, currency, total, n in top:

            lineas.append(
                f"• {nombre}: {formato_importe(total, currency)} ({n})"
            )


    lineas.extend([
        "",
        "👥 Socios en toda la plataforma",
        f"Activos ahora: {socios['activos']}",
        f"Altas este mes: {socios['altas_mes']}",
        f"Con renovación automática: {socios['suscriptores']}",
    ])


    return "\n".join(lineas)


def build_scoped_income_text(group_ids):
    """
    La vista de un admin acotado a sus grupos: lo suyo, con las MISMAS reglas
    de dinero (solo cobrado, por moneda, céntimos divididos).
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(g.name, 'Comunidad ' || p.group_id),
                       COALESCE(NULLIF(UPPER(p.currency), ''), 'EUR'),
                       COALESCE(SUM(p.amount), 0),
                       COUNT(*)
                FROM payments p
                LEFT JOIN groups g ON g.id = p.group_id
                WHERE p.group_id = ANY(%s)
                  AND LOWER(COALESCE(p.status, '')) IN %s
                GROUP BY 1, 2
                ORDER BY 1 ASC, 3 DESC

            """, (list(group_ids), PAID_STATUSES))

            filas = cur.fetchall() or []

    except Exception as e:

        print("Plataforma: error leyendo ingresos acotados:", e)

        filas = []


    if not filas:

        return "💰 No hay ingresos registrados en tus comunidades."


    lineas = ["💰 Ingresos por comunidad", ""]

    for nombre, currency, total, n in filas:

        etiqueta = "pago" if n == 1 else "pagos"
        lineas.append(f"• {nombre}: {formato_importe(total, currency)} ({n} {etiqueta})")


    return "\n".join(lineas)
