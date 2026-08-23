"""
El embudo de TODO el bot, no el de una comunidad.

El embudo por comunidad ya existía y responde «¿por qué no vende esta?». Falta
la pregunta de arriba, la que decide en qué gastar el día siguiente:

    ¿no viene nadie, se caen al ver el precio, o el cobro los está perdiendo?

Son tres problemas con tres arreglos completamente distintos, y sin este número
se elige por corazonada. Los cuatro pasos salen de datos que ya se guardaban:

  LLEGAN     Personas distintas con cualquier evento registrado en el bot.

  MIRAN      Personas que abrieron la ficha de una comunidad
             (bot_user_events con community_viewed).

  EMPIEZAN   Personas con una transacción de pago creada: han llegado a la
             pantalla de Stripe con la tarjeta delante.

  PAGAN      Personas con un pago cobrado.

LA REGLA QUE LO HACE CREÍBLE: se cuentan PERSONAS distintas, no pulsaciones.
Alguien que abre seis veces la misma ficha no son seis interesados, y contarlo
así convierte una conversión decente en un desastre aparente (o al revés).

Y cuando el paso de arriba es cero no se calcula el porcentaje: un porcentaje
sobre cero no es un cero, es un «no se sabe», y decirlo así evita decisiones
tomadas sobre un número inventado.
"""

from db import conn


PAID_STATUSES = ("paid", "completed", "succeeded")


def fetch_platform_funnel(days=30):
    """{'llegan', 'miran', 'empiezan', 'pagan'} — personas distintas."""

    vacio = {"llegan": 0, "miran": 0, "empiezan": 0, "pagan": 0}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT
                    (SELECT COUNT(DISTINCT user_id)
                       FROM bot_user_events
                      WHERE user_id IS NOT NULL AND user_id > 0
                        AND created_at >= NOW() - (%(dias)s || ' days')::interval),

                    (SELECT COUNT(DISTINCT user_id)
                       FROM bot_user_events
                      WHERE event_type = 'community_viewed'
                        AND user_id IS NOT NULL AND user_id > 0
                        AND created_at >= NOW() - (%(dias)s || ' days')::interval),

                    (SELECT COUNT(DISTINCT user_id)
                       FROM payment_transactions
                      WHERE user_id IS NOT NULL
                        AND created_at >= NOW() - (%(dias)s || ' days')::interval),

                    (SELECT COUNT(DISTINCT user_id)
                       FROM payments
                      WHERE user_id IS NOT NULL
                        AND LOWER(COALESCE(status, '')) = ANY(%(pagados)s)
                        AND payment_date >= NOW() - (%(dias)s || ' days')::interval)

            """, {"dias": int(days), "pagados": list(PAID_STATUSES)})

            fila = cur.fetchone()

    except Exception as e:

        print("Embudo de plataforma: error leyendo los números:", str(e)[:200])

        return vacio

    if not fila:
        return vacio

    return {
        "llegan": int(fila[0] or 0),
        "miran": int(fila[1] or 0),
        "empiezan": int(fila[2] or 0),
        "pagan": int(fila[3] or 0),
    }


def porcentaje(parte, total):
    """«12%» o None cuando el de arriba es cero: eso no es un 0%, es un «no sé»."""

    if not total:
        return None

    return f"{round(100 * int(parte) / int(total))}%"


def _linea(etiqueta, valor, anterior=None):

    pct = porcentaje(valor, anterior) if anterior is not None else None

    return f"{etiqueta}: {valor}" + (f" ({pct} del paso anterior)" if pct else "")


def build_platform_funnel_text(days=30):
    """La pantalla. Dice dónde se cae la gente y qué significa cada caída."""

    numeros = fetch_platform_funnel(days)

    lineas = [
        f"📊 Embudo del bot — últimos {int(days)} días",
        "",
        _linea("👋 Llegan al bot", numeros["llegan"]),
        _linea("👀 Miran una comunidad", numeros["miran"], numeros["llegan"]),
        _linea("💳 Empiezan a pagar", numeros["empiezan"], numeros["miran"]),
        _linea("✅ Pagan", numeros["pagan"], numeros["empiezan"]),
        "",
    ]

    # El diagnóstico, que es para lo que existe la pantalla. Se dice UNA cosa:
    # la de más arriba que esté rota, porque arreglar la de abajo con la de
    # arriba rota no cambia nada.
    if not numeros["llegan"]:

        lineas.append(
            "Nadie ha entrado en el bot. No es un problema de precio ni de "
            "cobro: es que no llega gente. El material para repartir está en "
            "«📣 Traer compradores» de cada comunidad."
        )

    elif not numeros["miran"]:

        lineas.append(
            "Entra gente y nadie abre una comunidad. Lo que se ve al llegar no "
            "invita a mirar: revisa el escaparate y las descripciones."
        )

    elif not numeros["empiezan"]:

        lineas.append(
            "Miran y ninguno llega a pagar. Ahí decide el precio y lo que "
            "promete la ficha."
        )

    elif not numeros["pagan"]:

        lineas.append(
            "🚨 Llegan a la pantalla de pago y no paga NINGUNO. Eso ya no es el "
            "producto: es la pasarela. Mira «Cobro» en el arranque y qué nombre "
            "sale en la página de Stripe."
        )

    else:

        lineas.append(
            "El embudo entero tiene gente. Para vender más, lo que más rinde es "
            "ensanchar el paso con peor porcentaje."
        )

    return "\n".join(lineas)
