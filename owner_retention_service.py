"""
Retención: cuánto duran los clientes de una comunidad y cuántos se van.

El panel de ingresos cuenta lo que ENTRA. Esta pantalla cuenta lo que se
queda, que es lo que decide si el negocio crece o solo hace ruido: un
propietario puede vender veinte accesos al mes y no crecer nada si veinte
se van cada mes.

Cuatro números, con la aritmética a la vista para que nadie tenga que
creerse un porcentaje sin saber de dónde sale:

  BAJAS DEL MES     Cuántos accesos caducaron sin volver a pagar en los
                    últimos 30 días, sobre los que había activos al empezar
                    el periodo. Ese cociente es la tasa de bajas.

  VIDA MEDIA        Los días que aguanta de media un cliente que YA se fue
                    (del primer pago a su última caducidad). Solo se cuentan
                    los que terminaron: incluir a los activos —que aún están
                    sumando días— hunde la media y miente a la baja.

  VALOR POR CLIENTE Lo que ha pagado de media cada cliente a lo largo de su
                    vida. Con la vida media al lado, es lo que dice cuánto
                    se puede gastar en traer uno nuevo.

  RENOVACIONES      Qué porcentaje de los clientes ha pagado más de una vez.
                    Un negocio de suscripción donde casi nadie llega al
                    segundo pago no es un negocio de suscripción.

Los importes de `payments` van en céntimos y solo cuentan los estados
cobrados: una devolución no es un ingreso ni una vida más larga.
"""

from db import conn
from owner_revenue_service import PAID_STATUSES, formato_importe


def fetch_churn_numbers(group_id):
    """{'activos', 'bajas_30', 'tasa'} — las bajas del último mes.

    La tasa se calcula sobre la base de partida (activos ahora + los que se
    fueron), que es la población que PODÍA irse. Sin base, no hay tasa: se
    devuelve None en vez de un 0% que parecería una buena noticia.
    """

    vacio = {"activos": 0, "bajas_30": 0, "tasa": None}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT
                    COUNT(*) FILTER (
                        WHERE expiration IS NULL OR expiration > NOW()
                    ),
                    COUNT(*) FILTER (
                        WHERE expiration IS NOT NULL
                          AND expiration <= NOW()
                          AND expiration >= NOW() - INTERVAL '30 days'
                    )
                FROM users
                WHERE group_id = %s

            """, (group_id,))

            activos, bajas = cur.fetchone() or (0, 0)

        activos = int(activos or 0)
        bajas = int(bajas or 0)
        base = activos + bajas

        return {
            "activos": activos,
            "bajas_30": bajas,
            "tasa": (bajas * 100 // base) if base else None,
        }

    except Exception as e:

        print("Retención: error contando bajas:", e)

        return vacio


def fetch_lifetime_numbers(group_id):
    """{'vida_dias', 'clientes_cerrados', 'valor', 'currency'}.

    La vida media se mide SOLO sobre clientes que ya terminaron: el que
    sigue dentro no ha terminado de durar, y meterlo en la media la hunde.
    """

    vacio = {"vida_dias": None, "clientes_cerrados": 0,
             "valor": None, "currency": "EUR"}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                WITH vidas AS (
                    SELECT u.user_id,
                           MIN(p.payment_date) AS primero,
                           u.expiration AS fin
                    FROM users u
                    JOIN payments p
                      ON p.user_id = u.user_id
                     AND p.group_id = u.group_id
                     AND LOWER(COALESCE(p.status, '')) IN %s
                    WHERE u.group_id = %s
                      AND u.expiration IS NOT NULL
                      AND u.expiration <= NOW()
                    GROUP BY u.user_id, u.expiration
                )
                SELECT COUNT(*),
                       AVG(GREATEST(EXTRACT(EPOCH FROM (fin - primero)) / 86400, 0))
                FROM vidas

            """, (PAID_STATUSES, group_id))

            cerrados, vida = cur.fetchone() or (0, None)

            cur.execute("""

                SELECT COALESCE(NULLIF(UPPER(currency), ''), 'EUR'),
                       SUM(amount),
                       COUNT(DISTINCT user_id)
                FROM payments
                WHERE group_id = %s
                  AND LOWER(COALESCE(status, '')) IN %s
                GROUP BY 1
                ORDER BY 2 DESC
                LIMIT 1

            """, (group_id, PAID_STATUSES))

            fila = cur.fetchone()

        valor = None
        currency = "EUR"

        if fila and fila[2]:

            currency = fila[0]
            valor = int(fila[1] or 0) // int(fila[2])

        return {
            "vida_dias": int(vida) if vida is not None else None,
            "clientes_cerrados": int(cerrados or 0),
            "valor": valor,
            "currency": currency,
        }

    except Exception as e:

        print("Retención: error midiendo la vida del cliente:", e)

        return vacio


def fetch_repeat_numbers(group_id):
    """{'clientes', 'repiten', 'porcentaje'} — quién llega al segundo pago."""

    vacio = {"clientes": 0, "repiten": 0, "porcentaje": None}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                WITH pagos_por_cliente AS (
                    SELECT user_id, COUNT(*) AS veces
                    FROM payments
                    WHERE group_id = %s
                      AND LOWER(COALESCE(status, '')) IN %s
                    GROUP BY user_id
                )
                SELECT COUNT(*), COUNT(*) FILTER (WHERE veces > 1)
                FROM pagos_por_cliente

            """, (group_id, PAID_STATUSES))

            clientes, repiten = cur.fetchone() or (0, 0)

        clientes = int(clientes or 0)
        repiten = int(repiten or 0)

        return {
            "clientes": clientes,
            "repiten": repiten,
            "porcentaje": (repiten * 100 // clientes) if clientes else None,
        }

    except Exception as e:

        print("Retención: error contando repetidores:", e)

        return vacio


def fetch_referral_cost(group_id):
    """{'invitados', 'convertidos', 'dias'} — lo que cuestan los referidos.

    El programa de referidos regala días de acceso: es coste de adquisición
    real, pagado en producto en vez de en dinero. El propietario lo estaba
    pagando sin poder verlo en ninguna pantalla, y un coste invisible es un
    coste que nadie decide.

    Los días se cuentan por los dos lados: el que invita y el invitado cobran
    lo mismo, así que el coste de un referido convertido es el doble de lo que
    dice days_awarded en su fila.
    """

    vacio = {"invitados": 0, "convertidos": 0, "dias": 0}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE status = 'converted'),
                       COALESCE(SUM(days_awarded) FILTER (
                           WHERE status = 'converted'
                       ), 0) * 2
                FROM referrals
                WHERE group_id = %s

            """, (group_id,))

            fila = cur.fetchone() or (0, 0, 0)

        return {
            "invitados": int(fila[0] or 0),
            "convertidos": int(fila[1] or 0),
            "dias": int(fila[2] or 0),
        }

    except Exception as e:

        print("Retención: error leyendo el coste de los referidos:", e)

        return vacio


def build_owner_retention_text(group_id, group_name):
    """La pantalla. En español, como el resto del panel del propietario."""

    bajas = fetch_churn_numbers(group_id)
    vida = fetch_lifetime_numbers(group_id)
    repite = fetch_repeat_numbers(group_id)
    referidos = fetch_referral_cost(group_id)

    lineas = [
        f"🔄 Retención de {group_name}",
        "",
        "📉 Bajas (últimos 30 días)",
        f"Activos ahora: {bajas['activos']}",
        f"Se han ido: {bajas['bajas_30']}",
    ]

    if bajas["tasa"] is None:

        lineas.append(
            "Tasa de bajas: todavía sin datos (hace falta al menos un "
            "cliente para poder medirla)."
        )

    else:

        lineas.append(
            f"Tasa de bajas: {bajas['tasa']}% "
            f"({bajas['bajas_30']} de {bajas['activos'] + bajas['bajas_30']})"
        )


    lineas.extend(["", "⏳ Vida del cliente"])

    if vida["vida_dias"] is None:

        lineas.append(
            "Todavía no se ha ido nadie: la vida media se mide sobre "
            "clientes que ya terminaron, para no mentir a la baja."
        )

    else:

        lineas.append(
            f"Duración media: {vida['vida_dias']} días "
            f"({vida['clientes_cerrados']} clientes ya terminados)"
        )


    if vida["valor"] is not None:

        lineas.append(
            "Ha pagado de media cada cliente: "
            f"{formato_importe(vida['valor'], vida['currency'])}"
        )
        lineas.append(
            "Es el techo de lo que tiene sentido gastar en traer uno nuevo."
        )


    lineas.extend(["", "🔁 Segundo pago"])

    if repite["porcentaje"] is None:

        lineas.append("Todavía no hay pagos que contar.")

    else:

        lineas.append(
            f"Han pagado más de una vez: {repite['repiten']} de "
            f"{repite['clientes']} ({repite['porcentaje']}%)"
        )

        if repite["clientes"] >= 5 and repite["porcentaje"] < 30:

            lineas.append(
                "Menos de un tercio llega al segundo pago: casi todo el "
                "ingreso viene de altas nuevas, no de la comunidad."
            )


    # Los referidos solo se cuentan si ha habido alguno: una sección que dice
    # "0 invitados" en toda comunidad que no usa el programa es ruido.
    if referidos["invitados"]:

        lineas.extend(["", "🎁 Referidos"])

        lineas.append(
            f"Invitados: {referidos['invitados']} · "
            f"han pagado: {referidos['convertidos']}"
        )

        if referidos["dias"]:

            lineas.append(
                f"Días de acceso regalados: {referidos['dias']} "
                "(contando los dos lados de cada referido)"
            )
            lineas.append(
                "Es coste de adquisición pagado en producto: compáralo con lo "
                "que ha pagado de media un cliente."
            )


    return "\n".join(lineas)
