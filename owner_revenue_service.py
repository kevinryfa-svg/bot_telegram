"""
Los ingresos de una comunidad, para el ojo de su propietario.

El panel mostraba usuarios, planes, códigos, admins y backup — todo menos el
dinero. El propietario de una comunidad de pago no tenía forma de ver cuánto
factura, cuántos clientes ha ganado o perdido, ni qué plan vende, sin ir a
mirar el panel de Stripe (que además solo cubre uno de los cinco métodos).

Los datos salen de `payments`, que es donde escriben TODOS los caminos de
cobro: el webhook de Stripe y el camino compartido de PayPal, Revolut,
ChangeNOW y Guardarian. Los importes están en céntimos.

La misma pantalla junta "qué está roto ahora mismo": la salud de entrega, las
incidencias de pago abiertas y las devoluciones. Cada una de esas cosas avisa
por su lado cuando ocurre, pero los avisos se borran o se silencian; esta
pantalla es el sitio al que mirar cuando algo no cuadra.
"""

from db import conn
from group_delivery_health_service import describe_group_delivery


# Estados que cuentan como dinero cobrado. Las devoluciones quedan fuera de los
# ingresos y se enseñan como su propia línea.
PAID_STATUSES = ("paid", "completed")


def formato_importe(cents, currency):
    """1500 -> '15.00 EUR'. Los importes de payments van en céntimos."""

    try:

        return f"{int(cents) / 100:.2f} {(currency or 'EUR').upper()}"

    except Exception:

        return f"{cents} {(currency or 'EUR').upper()}"


def fetch_revenue_summary(group_id):
    """
    Ingresos por ventana temporal, separados por moneda.

    Por moneda y no sumados: mezclar 15 EUR con 15 USD en un total daría un
    número que no existe. Devuelve listas de (currency, total_cents, pagos).
    """

    resumen = {"mes_actual": [], "dias_30": [], "historico": []}

    ventanas = (
        ("mes_actual", "payment_date >= date_trunc('month', NOW())"),
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
                    WHERE group_id = %s
                      AND LOWER(COALESCE(status, '')) IN %s
                      AND {condicion}
                    GROUP BY 1
                    ORDER BY 2 DESC

                """, (group_id, PAID_STATUSES))

                resumen[clave] = cur.fetchall() or []

    except Exception as e:

        print("Ingresos: error leyendo pagos:", e)


    return resumen


def fetch_customer_summary(group_id):
    """Altas, activos y caducados que no han vuelto."""

    datos = {"activos": 0, "altas_30": 0, "caducados_30": 0}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT
                    COUNT(*) FILTER (
                        WHERE COALESCE(subscription_active, FALSE) = TRUE
                          AND (expiration IS NULL OR expiration > NOW())
                    ),
                    COUNT(*) FILTER (
                        WHERE created_at >= NOW() - INTERVAL '30 days'
                    ),
                    COUNT(*) FILTER (
                        WHERE expiration >= NOW() - INTERVAL '30 days'
                          AND expiration < NOW()
                          AND COALESCE(subscription_active, FALSE) = FALSE
                    )
                FROM users
                WHERE group_id = %s

            """, (group_id,))

            fila = cur.fetchone()

            if fila:

                datos["activos"], datos["altas_30"], datos["caducados_30"] = fila

    except Exception as e:

        print("Ingresos: error leyendo clientes:", e)


    return datos


def fetch_top_plan(group_id):
    """El plan que más vende, por número de pagos. (nombre, ventas) o None."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(NULLIF(plan, ''), 'Sin nombre'),
                       COUNT(*)
                FROM payments
                WHERE group_id = %s
                  AND LOWER(COALESCE(status, '')) IN %s
                GROUP BY 1
                ORDER BY 2 DESC
                LIMIT 1

            """, (group_id, PAID_STATUSES))

            return cur.fetchone()

    except Exception as e:

        print("Ingresos: error leyendo el plan más vendido:", e)

        return None


def fetch_problem_snapshot(group_id):
    """
    Lo que está roto o pendiente ahora mismo.

    Las devoluciones no tienen fecha propia (se marca el estado sobre el pago),
    así que se enseña el total histórico: mentir con "últimos 30 días" usando
    la fecha del PAGO contaría mal.
    """

    datos = {"incidencias_abiertas": 0, "devoluciones": 0}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM payment_incidents
                WHERE group_id = %s
                  AND resolved_at IS NULL

            """, (group_id,))

            datos["incidencias_abiertas"] = (cur.fetchone() or [0])[0]

            cur.execute("""

                SELECT COUNT(*)
                FROM payments
                WHERE group_id = %s
                  AND LOWER(COALESCE(status, '')) = 'refunded'

            """, (group_id,))

            datos["devoluciones"] = (cur.fetchone() or [0])[0]

    except Exception as e:

        print("Ingresos: error leyendo problemas:", e)


    return datos


def formato_ventana(filas):
    """Una ventana de ingresos como texto: '15.00 EUR (3 pagos)'."""

    if not filas:

        return "0.00 EUR (0 pagos)"


    partes = []

    for currency, total, pagos in filas:

        etiqueta = "pago" if pagos == 1 else "pagos"
        partes.append(f"{formato_importe(total, currency)} ({pagos} {etiqueta})")


    return " · ".join(partes)


def build_owner_revenue_text(group_id, group_name):
    """
    La pantalla entera. En español a propósito: es panel de administración, como
    el resto del panel del propietario.
    """

    ingresos = fetch_revenue_summary(group_id)
    clientes = fetch_customer_summary(group_id)
    top = fetch_top_plan(group_id)
    problemas = fetch_problem_snapshot(group_id)

    lineas = [
        f"💰 Ingresos de {group_name}",
        "",
        f"Este mes: {formato_ventana(ingresos['mes_actual'])}",
        f"Últimos 30 días: {formato_ventana(ingresos['dias_30'])}",
        f"Total histórico: {formato_ventana(ingresos['historico'])}",
        "",
        "👥 Clientes",
        f"Activos ahora: {clientes['activos']}",
        f"Altas (30 días): {clientes['altas_30']}",
        f"Caducados sin volver (30 días): {clientes['caducados_30']}",
    ]


    if top:

        nombre, ventas = top
        etiqueta = "venta" if ventas == 1 else "ventas"
        lineas.extend(["", f"🏆 Plan más vendido: {nombre} ({ventas} {etiqueta})"])


    lineas.extend([
        "",
        "🩺 Ahora mismo",
        f"Entrega de accesos: {describe_group_delivery(group_id)}",
        f"Incidencias de pago abiertas: {problemas['incidencias_abiertas']}",
        f"Devoluciones (histórico): {problemas['devoluciones']}",
    ])


    if problemas["incidencias_abiertas"]:

        lineas.extend([
            "",
            "⚠️ Hay cobros sin acceso concedido pendientes de resolver: revisa "
            "los avisos o escribe a soporte."
        ])


    return "\n".join(lineas)
