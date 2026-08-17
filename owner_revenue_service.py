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


def fetch_month_comparison(group_id):
    """
    Este mes contra el anterior, por moneda: [(currency, actual, anterior)].
    El mes anterior COMPLETO, no "hace 30 días": comparar un mes a medias con
    una ventana móvil da porcentajes que no significan nada.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(NULLIF(UPPER(currency), ''), 'EUR'),
                       COALESCE(SUM(amount) FILTER (
                           WHERE payment_date >= date_trunc('month', NOW())
                       ), 0),
                       COALESCE(SUM(amount) FILTER (
                           WHERE payment_date >= date_trunc('month', NOW()) - INTERVAL '1 month'
                             AND payment_date < date_trunc('month', NOW())
                       ), 0)
                FROM payments
                WHERE group_id = %s
                  AND LOWER(COALESCE(status, '')) IN %s
                  AND payment_date >= date_trunc('month', NOW()) - INTERVAL '1 month'
                GROUP BY 1
                ORDER BY 2 DESC

            """, (group_id, PAID_STATUSES))

            return cur.fetchall() or []

    except Exception as e:

        print("Ingresos: error comparando meses:", e)

        return []


def fetch_autorenew_summary(group_id):
    """
    La renovación automática en números: cuántos socios tienen una suscripción
    viva anclada, y cuántas renovaciones se han cobrado en 30 días. Una
    renovación es el pago de alguien que YA había pagado antes en la misma
    comunidad — la definición vale para todos los proveedores.
    """

    datos = {"suscriptores": 0, "renovaciones_30d": 0}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM users u
                WHERE u.group_id = %s
                  AND COALESCE(u.subscription_active, FALSE) = TRUE
                  AND (
                      u.stripe_subscription_id IS NOT NULL
                      OR EXISTS (
                          SELECT 1 FROM payment_transactions pt
                          WHERE pt.provider = 'paypal'
                            AND pt.user_id = u.user_id
                            AND pt.group_id = u.group_id
                            AND pt.purchase_type = 'group_access'
                            AND pt.status = 'paid'
                            AND pt.external_checkout_id IS NOT NULL
                      )
                  )

            """, (group_id,))

            datos["suscriptores"] = (cur.fetchone() or [0])[0]

            cur.execute("""

                SELECT COUNT(*)
                FROM payments p
                WHERE p.group_id = %s
                  AND LOWER(COALESCE(p.status, '')) IN %s
                  AND p.payment_date >= NOW() - INTERVAL '30 days'
                  AND EXISTS (
                      SELECT 1 FROM payments antes
                      WHERE antes.user_id = p.user_id
                        AND antes.group_id = p.group_id
                        AND antes.id < p.id
                        AND LOWER(COALESCE(antes.status, '')) IN %s
                  )

            """, (group_id, PAID_STATUSES, PAID_STATUSES))

            datos["renovaciones_30d"] = (cur.fetchone() or [0])[0]

    except Exception as e:

        print("Ingresos: error leyendo la renovación automática:", e)


    return datos


def formato_comparativa(filas):
    """'45.00 EUR (mes anterior: 30.00 EUR, +50%)' — por moneda."""

    if not filas:

        return None


    partes = []

    for currency, actual, anterior in filas:

        trozo = formato_importe(actual, currency)

        if anterior:

            delta = (int(actual) - int(anterior)) * 100 // int(anterior)
            signo = "+" if delta >= 0 else ""
            trozo += (f" (mes anterior: {formato_importe(anterior, currency)}, "
                      f"{signo}{delta}%)")

        partes.append(trozo)


    return " · ".join(partes)


def build_payments_csv(group_id):
    """
    Todos los pagos de la comunidad como CSV, con los importes en unidades
    mayores (15.00, no 1500): el destinatario es una hoja de cálculo, no
    nuestra base. Separador ';' y BOM: lo que Excel en español abre bien.
    """

    lineas = ["fecha;usuario;importe;moneda;estado;plan"]

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT payment_date, user_id, amount, currency, status, plan
                FROM payments
                WHERE group_id = %s
                ORDER BY payment_date DESC NULLS LAST, id DESC

            """, (group_id,))

            for fecha, user_id, amount, currency, status, plan in cur.fetchall():

                try:
                    fecha_txt = fecha.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    fecha_txt = ""

                try:
                    importe = f"{int(amount) / 100:.2f}"
                except Exception:
                    importe = ""

                plan_txt = (plan or "").replace(";", ",").replace("\n", " ")

                lineas.append(
                    f"{fecha_txt};{user_id};{importe};"
                    f"{(currency or 'EUR').upper()};{status or ''};{plan_txt}"
                )

    except Exception as e:

        print("Ingresos: error exportando pagos:", e)


    return "\n".join(lineas)


def fetch_subscriber_rows(group_id, limit=30):
    """
    Los socios con renovación automática, ordenados por próximo cobro. La
    expiración ES la fecha del próximo cobro: cada ciclo la mueve.

    [(user_id, username, expiration, provider, ultimo_importe, currency)]
    El importe es el ÚLTIMO cobro de cada socio: su precio real, no el de
    lista — quien se suscribió antes de una subida conserva el suyo.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT u.user_id,
                       u.username,
                       u.expiration,
                       CASE WHEN u.stripe_subscription_id IS NOT NULL
                            THEN 'stripe' ELSE 'paypal' END,
                       ultimo.amount,
                       ultimo.currency
                FROM users u
                LEFT JOIN LATERAL (
                    SELECT p.amount, p.currency
                    FROM payments p
                    WHERE p.user_id = u.user_id
                      AND p.group_id = u.group_id
                      AND LOWER(COALESCE(p.status, '')) IN %s
                    ORDER BY p.payment_date DESC NULLS LAST, p.id DESC
                    LIMIT 1
                ) ultimo ON TRUE
                WHERE u.group_id = %s
                  AND COALESCE(u.subscription_active, FALSE) = TRUE
                  AND (
                      u.stripe_subscription_id IS NOT NULL
                      OR EXISTS (
                          SELECT 1 FROM payment_transactions pt
                          WHERE pt.provider = 'paypal'
                            AND pt.user_id = u.user_id
                            AND pt.group_id = u.group_id
                            AND pt.purchase_type = 'group_access'
                            AND pt.status = 'paid'
                            AND pt.external_checkout_id IS NOT NULL
                      )
                  )
                ORDER BY u.expiration ASC NULLS LAST
                LIMIT %s

            """, (PAID_STATUSES, group_id, int(limit)))

            return cur.fetchall() or []

    except Exception as e:

        print("Suscriptores: error listando:", e)

        return []


def build_owner_subscribers_text(group_id, group_name):
    """La lista humana detrás del panel de ingresos."""

    filas = fetch_subscriber_rows(group_id)

    lineas = [
        f"👥 Suscriptores de {group_name}",
        "",
    ]

    if not filas:

        lineas.append(
            "Nadie tiene renovación automática todavía. Los planes de "
            "suscripción de Stripe y PayPal aparecen aquí en cuanto alguien "
            "se suscribe."
        )

        return "\n".join(lineas)


    proximos_7d = 0
    total_7d = {}

    for user_id, username, expiration, provider, importe, currency in filas:

        try:
            fecha = expiration.strftime("%d/%m")
        except Exception:
            fecha = "—"

        quien = f"@{username}" if username else f"id {user_id}"
        precio = formato_importe(importe, currency) if importe else "—"

        lineas.append(f"• {quien} — {precio} · próximo cobro {fecha} · {provider}")

        try:

            from datetime import datetime, timedelta

            if expiration and expiration <= datetime.now() + timedelta(days=7):

                proximos_7d += 1

                if importe:

                    clave = (currency or "EUR").upper()
                    total_7d[clave] = total_7d.get(clave, 0) + int(importe)

        except Exception:

            pass


    lineas.append("")
    lineas.append(f"Suscriptores listados: {len(filas)}")

    if proximos_7d:

        importes = " · ".join(
            formato_importe(total, cur_) for cur_, total in total_7d.items()
        )

        lineas.append(
            f"📅 Cobros en los próximos 7 días: {proximos_7d}"
            + (f" (≈ {importes})" if importes else "")
        )


    lineas.extend([
        "",
        "El importe es el último cobro de cada socio (su precio real). Si "
        "alguien canceló, desaparece de aquí cuando su periodo termina.",
    ])

    return "\n".join(lineas)


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
    comparativa = formato_comparativa(fetch_month_comparison(group_id))
    renovacion = fetch_autorenew_summary(group_id)

    linea_mes = f"Este mes: {formato_ventana(ingresos['mes_actual'])}"

    if comparativa:

        linea_mes = f"Este mes: {comparativa}"


    lineas = [
        f"💰 Ingresos de {group_name}",
        "",
        linea_mes,
        f"Últimos 30 días: {formato_ventana(ingresos['dias_30'])}",
        f"Total histórico: {formato_ventana(ingresos['historico'])}",
        "",
        "👥 Clientes",
        f"Activos ahora: {clientes['activos']}",
        f"Altas (30 días): {clientes['altas_30']}",
        f"Caducados sin volver (30 días): {clientes['caducados_30']}",
        "",
        "🔁 Renovación automática",
        f"Suscriptores activos: {renovacion['suscriptores']}",
        f"Renovaciones cobradas (30 días): {renovacion['renovaciones_30d']}",
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
