"""
La recuperación de ventas a medias, por fin visible.

Hay dos máquinas escribiendo a gente que estuvo a punto de pagar y no pagó:

  - `abandoned_checkout_service`: quien llegó a la pantalla de pago y la cerró
    (y, 24 h después, el segundo toque con cupón).
  - `interest_followup_service`: quien miró los planes y ni llegó a la pantalla.

Entre las dos son más de mil líneas escribiéndole a clientes de verdad, y su
resultado no se veía en NINGUNA pantalla: vivía en `log_event` —que nadie abre—
y en un `print` del servidor. Nadie podía responder a las dos únicas preguntas
que deciden si esto merece la pena o hay que apagarlo:

    ¿a cuánta gente le estamos escribiendo, y cuánto dinero vuelve?

Esto lo contesta. Y contesta antes una tercera que nadie se estaba haciendo:
si la máquina está ENCENDIDA, porque las dos se apagan con una variable de
entorno y apagadas no dan ni un aviso de que están apagadas.

Cómo se cuenta un rescate: a alguien se le escribe el día X; si paga esa
comunidad DESPUÉS del día X, cuenta. No es causalidad demostrada —puede que
hubiera pagado igual— pero es la única medida honesta que se puede hacer sin
inventarse nada, y por eso el texto dice «pagaron después», no «gracias a».
"""

from db import conn
from owner_revenue_service import formato_centimos


PAID_STATUSES = ("paid", "completed", "succeeded")

# Un mes: suficiente para que dé tiempo a pagar tras el aviso, y lo bastante
# corto para que la foto sea la de ahora y no la del año pasado.
VENTANA_DIAS = 30


def _cuenta_de_una_tabla(tabla, dias):
    """
    (escritos, recuperados, importe_en_centimos, moneda) de una tabla de avisos.

    `moneda` es None cuando hay más de una: sumar monedas distintas bajo una
    sola etiqueta es la mentira de dinero que ya se corrigió en la pantalla de
    ingresos, y no se repite aquí.

    Devuelve None si la consulta falla (tabla que aún no existe, por ejemplo):
    el que llama tiene que poder decir «no se ha podido comprobar» en vez de
    enseñar un cero que parece un dato.
    """

    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT COUNT(*)::int,
                       COUNT(pago.amount)::int,
                       COALESCE(SUM(pago.amount), 0)::bigint,
                       MIN(pago.currency),
                       COUNT(DISTINCT pago.currency)::int
                FROM {tabla} a
                LEFT JOIN LATERAL (
                    SELECT p.amount, p.currency
                    FROM payments p
                    WHERE p.user_id = a.user_id
                      AND p.group_id = a.group_id
                      AND LOWER(COALESCE(p.status, '')) = ANY(%(pagado)s)
                      AND p.payment_date >= a.sent_at
                    ORDER BY p.payment_date ASC
                    LIMIT 1
                ) pago ON TRUE
                WHERE a.sent_at >= NOW() - (%(dias)s || ' days')::interval

            """, {"pagado": list(PAID_STATUSES), "dias": int(dias)})

            fila = cur.fetchone()

    except Exception as e:

        print("Informe de recuperación: no se pudo contar", tabla, ":", str(e)[:200])
        return None

    if not fila:
        return (0, 0, 0, None)

    escritos, recuperados, importe, moneda, monedas = fila

    return (
        int(escritos or 0),
        int(recuperados or 0),
        int(importe or 0),
        moneda if int(monedas or 0) == 1 else None
    )


def _linea_de_resultado(cuenta):
    """El resultado de un canal en una línea, o el aviso de que no se sabe."""

    if cuenta is None:
        return "   No se ha podido comprobar."

    escritos, recuperados, importe, moneda = cuenta

    if not escritos:
        return f"   No se ha escrito a nadie en {VENTANA_DIAS} días."

    linea = f"   {escritos} escritos · {recuperados} pagaron después"

    if recuperados and importe:

        if moneda:
            linea += f" · {formato_centimos(importe, moneda)}"
        else:
            linea += " · (varias monedas)"

    return linea


def _esperando_carritos():
    """Cuántos intentos a medias hay ahora mismo listos para el aviso."""

    try:

        from abandoned_checkout_service import fetch_abandoned_checkouts

        return len(fetch_abandoned_checkouts(limit=1000))

    except Exception as e:

        print("Informe de recuperación: no se pudo mirar la cola:", str(e)[:200])
        return None


def _esperando_interesados():

    try:

        from interest_followup_service import count_interest_candidates

        return count_interest_candidates()

    except Exception as e:

        print("Informe de recuperación: no se pudo mirar los interesados:", str(e)[:200])
        return None


def _estado(encendido):

    return "encendido" if encendido else "APAGADO"


def _esperando(cuantos, encendido):
    """La cola de un canal, diciendo la verdad cuando no se va a vaciar."""

    if cuantos is None:
        return "   Esperando: no se ha podido comprobar."

    if not cuantos:
        return "   Esperando: nadie."

    if not encendido:
        return f"   Esperando: {cuantos} — y no se les va a escribir, está apagado."

    return f"   Esperando ahora: {cuantos}."


def build_recovery_report_text(dias=None):
    """La pantalla entera. Nunca lanza."""

    try:
        return _montar(dias)

    except Exception as e:

        print("Informe de recuperación: no se pudo montar:", str(e)[:300])

        return (
            "🛒 Recuperación de ventas a medias\n\n"
            f"No se ha podido montar el informe: {str(e)[:200]}"
        )


def _montar(dias=None):

    dias = int(dias or VENTANA_DIAS)

    try:
        from abandoned_checkout_service import ABANDONED_ENABLED
    except Exception:
        ABANDONED_ENABLED = False

    try:
        from interest_followup_service import INTEREST_ENABLED
    except Exception:
        INTEREST_ENABLED = False

    carritos = _cuenta_de_una_tabla("abandoned_checkout_reminders", dias)
    cupones = _cuenta_de_una_tabla("abandoned_discount_reminders", dias)
    interes = _cuenta_de_una_tabla("interest_followups", dias)

    lineas = [
        "🛒 Recuperación de ventas a medias",
        f"(últimos {dias} días)",
        "",
        f"Carritos abandonados — {_estado(ABANDONED_ENABLED)}",
        _linea_de_resultado(carritos),
        _esperando(_esperando_carritos(), ABANDONED_ENABLED),
        "",
        f"Segundo toque con cupón — {_estado(ABANDONED_ENABLED)}",
        _linea_de_resultado(cupones),
        "",
        f"Interesados que no llegaron a pagar — {_estado(INTEREST_ENABLED)}",
        _linea_de_resultado(interes),
        _esperando(_esperando_interesados(), INTEREST_ENABLED),
    ]

    # El dinero recuperado, junto, porque es la cifra por la que existe todo
    # esto y buscarla sumando tres líneas a mano es como no enseñarla.
    recuperado = [c for c in (carritos, cupones, interes) if c and c[1] and c[2]]

    monedas = {c[3] for c in recuperado}

    if recuperado and len(monedas) == 1 and None not in monedas:

        total = sum(c[2] for c in recuperado)
        personas = sum(c[1] for c in recuperado)

        lineas += [
            "",
            f"💰 En total: {personas} persona(s) y "
            f"{formato_centimos(total, monedas.pop())} que se habían perdido."
        ]

    if not (ABANDONED_ENABLED and INTEREST_ENABLED):

        lineas += [
            "",
            "⚠️ Lo apagado no avisa de que está apagado: se enciende en el "
            "servidor con ABANDONED_ENABLED / INTEREST_FOLLOWUP_ENABLED."
        ]

    lineas += [
        "",
        "«Pagaron después» es eso literalmente: se les escribió y luego "
        "compraron. No prueba que fuera por el mensaje."
    ]

    return "\n".join(lineas)
