"""
El embudo: cuánta gente mira, cuánta empieza a pagar y cuánta paga.

El panel de ingresos dice cuánto entra y el de retención cuánto se queda, y
con los dos sigue faltando la pregunta que decide qué hacer mañana: si no
vendo, ¿es que no viene nadie, es que el precio espanta, o es que el pago se
rompe? Son tres problemas distintos con tres soluciones distintas, y el
propietario no tenía forma de distinguirlos.

Los tres números salen de datos que ya se guardaban:

  MIRAN      bot_user_events con community_viewed — la pulsación en la ficha
             de la comunidad quedó registrada desde el día que se añadió ese
             registro para saber quién se interesó y no compró.

  EMPIEZAN   payment_transactions de acceso a esa comunidad: una fila nace
             cuando alguien pide el enlace de pago.

  PAGAN      payments cobrados, personas distintas.

Y la regla que hace la pantalla creíble: se cuentan PERSONAS distintas, no
pulsaciones. Alguien que abre la ficha seis veces no son seis interesados, y
contarlo así convertiría una buena conversión en un desastre aparente.

Cuando falta el dato de arriba (nadie registrado mirando) no se calcula
ninguna conversión: un porcentaje sobre cero no es un cero, es un "no se
sabe", y decirlo así es lo que evita que alguien tome una decisión con un
número inventado.
"""

from db import conn


def fetch_funnel(group_id, days=30):
    """{'miran', 'empiezan', 'pagan'} — personas distintas en la ventana."""

    vacio = {"miran": 0, "empiezan": 0, "pagan": 0}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(DISTINCT user_id)
                FROM bot_user_events
                WHERE group_id = %s
                  AND event_type = 'community_viewed'
                  AND created_at >= NOW() - (%s || ' days')::interval

            """, (group_id, int(days)))

            miran = (cur.fetchone() or [0])[0]

            cur.execute("""

                SELECT COUNT(DISTINCT user_id)
                FROM payment_transactions
                WHERE group_id = %s
                  AND COALESCE(purchase_type, 'group_access') = 'group_access'
                  AND user_id IS NOT NULL
                  AND created_at >= NOW() - (%s || ' days')::interval

            """, (group_id, int(days)))

            empiezan = (cur.fetchone() or [0])[0]

            cur.execute("""

                SELECT COUNT(DISTINCT user_id)
                FROM payments
                WHERE group_id = %s
                  AND LOWER(COALESCE(status, '')) IN ('paid', 'completed')
                  AND payment_date >= NOW() - (%s || ' days')::interval

            """, (group_id, int(days)))

            pagan = (cur.fetchone() or [0])[0]

        return {
            "miran": int(miran or 0),
            "empiezan": int(empiezan or 0),
            "pagan": int(pagan or 0),
        }

    except Exception as e:

        print("Embudo: error contando el embudo:", e)

        return vacio


def porcentaje(parte, total):
    """None cuando no hay base: un porcentaje sobre cero no es un cero."""

    if not total:
        return None

    return int(int(parte) * 100 // int(total))


def diagnostico(numeros):
    """La frase que dice dónde está el problema. None si no se puede saber.

    El orden importa: primero se descarta la falta de gente, porque con dos
    visitas no se puede diagnosticar nada más.
    """

    miran = numeros["miran"]
    empiezan = numeros["empiezan"]
    pagan = numeros["pagan"]

    if miran < 10:

        return (
            "Con tan poca gente mirando todavía no se puede diagnosticar "
            "nada: lo único que mueve la aguja ahora es que te vean más."
        )

    if empiezan and pagan == 0:

        return (
            "Hay gente que llega a pagar y NADIE termina. Eso no es el "
            "precio: es el pago. Mira el semáforo «¿Puedo vender?» y prueba "
            "una compra tú mismo."
        )

    interes = porcentaje(empiezan, miran)

    if interes is not None and interes < 10:

        return (
            f"Solo {interes}% de quien mira llega a pedir el pago. La gente "
            "entra y se va antes de intentarlo: eso suele ser el precio, la "
            "descripción o la falta de preview."
        )

    cierre = porcentaje(pagan, empiezan)

    if cierre is not None and cierre < 50:

        return (
            f"Llegan al pago pero solo cierra {cierre}%. Revisa que el método "
            "de cobro funcione y que el precio del checkout sea el que "
            "esperaban."
        )

    return (
        "El embudo está sano: la mayoría de quien lo intenta termina "
        "pagando. Para crecer, más gente arriba."
    )


def build_owner_funnel_text(group_id, group_name, days=30):
    """La pantalla. En español, como el resto del panel del propietario."""

    numeros = fetch_funnel(group_id, days=days)

    lineas = [
        f"🔻 Embudo de {group_name} (últimos {days} días)",
        "",
        f"👀 Han mirado la comunidad: {numeros['miran']}",
        f"💳 Han pedido el pago: {numeros['empiezan']}",
        f"✅ Han pagado: {numeros['pagan']}",
        "",
    ]

    interes = porcentaje(numeros["empiezan"], numeros["miran"])
    cierre = porcentaje(numeros["pagan"], numeros["empiezan"])
    total = porcentaje(numeros["pagan"], numeros["miran"])

    if interes is None:

        lineas.append(
            "Sin nadie registrado mirando, no hay conversión que calcular. "
            "No es un 0%: es que todavía no hay dato."
        )

    else:

        lineas.append(f"De mirar a intentarlo: {interes}%")

        if cierre is not None:

            lineas.append(f"De intentarlo a pagar: {cierre}%")

        if total is not None:

            lineas.append(f"De mirar a pagar: {total}%")


    lineas.extend(["", diagnostico(numeros)])

    lineas.extend([
        "",
        "Se cuentan personas distintas, no pulsaciones: quien abre la ficha "
        "seis veces es un interesado, no seis."
    ])

    return "\n".join(lineas)
