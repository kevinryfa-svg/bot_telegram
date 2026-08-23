"""
El pulso diario: el negocio entero en seis líneas, sin abrir nada.

El aviso de cada pago ya existía, y el resumen semanal por comunidad también.
Falta lo de en medio: saber cada mañana si esto está vendiendo, sin tener que
entrar a mirar. Un negocio del que solo te enteras cuando ya ha pasado un mes es
un negocio que se descubre tarde.

Seis líneas y ni una más, porque un resumen que hay que leer despacio no se lee:

  DINERO       Lo cobrado ayer y en los últimos siete días, con el número de
               pagos. En euros, desde céntimos, que es como lo guarda la tabla.

  TIENDA       Cuántas comunidades se pueden comprar ahora mismo.

  COBRO        Si el cobro funciona. Es lo único que, roto, hace inútil todo lo
               demás.

  EMBUDO       Cuántos llegan y cuántos pagan. La caída dice qué arreglar.

Nada de esto se calcula aquí: cada línea viene del servicio que ya responde esa
pregunta. Un resumen que hace sus propias cuentas acaba diciendo un número
distinto del que dice la pantalla de al lado.
"""

import os

from db import conn


PAID_STATUSES = ("paid", "completed", "succeeded")

PULSO_ACTIVO = os.environ.get(
    "DAILY_PULSE_ENABLED", "true"
).strip().lower() not in ("0", "false", "no", "off")


def dinero_reciente():
    """{'ayer': (importe, pagos), 'semana': (importe, pagos)} en unidades mayores."""

    vacio = {"ayer": (0.0, 0), "semana": (0.0, 0)}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT
                    COALESCE(SUM(amount) FILTER (
                        WHERE payment_date >= CURRENT_DATE - INTERVAL '1 day'
                          AND payment_date < CURRENT_DATE
                    ), 0),
                    COUNT(*) FILTER (
                        WHERE payment_date >= CURRENT_DATE - INTERVAL '1 day'
                          AND payment_date < CURRENT_DATE
                    ),
                    COALESCE(SUM(amount) FILTER (
                        WHERE payment_date >= NOW() - INTERVAL '7 days'
                    ), 0),
                    COUNT(*) FILTER (
                        WHERE payment_date >= NOW() - INTERVAL '7 days'
                    )
                FROM payments
                WHERE LOWER(COALESCE(status, '')) = ANY(%s)

            """, (list(PAID_STATUSES),))

            fila = cur.fetchone()

    except Exception as e:

        print("Pulso diario: error leyendo el dinero:", str(e)[:200])

        return vacio

    if not fila:
        return vacio

    # payments.amount va en CÉNTIMOS (al revés que plans.amount, que va en
    # unidades mayores). Las dos convenciones conviven en este producto y
    # confundirlas es cómo se enseña un ingreso cien veces mayor.
    return {
        "ayer": (float(fila[0] or 0) / 100.0, int(fila[1] or 0)),
        "semana": (float(fila[2] or 0) / 100.0, int(fila[3] or 0)),
    }


def build_daily_pulse_text():
    """Las seis líneas. Nunca lanza: es un aviso, no una operación."""

    from start_offer_service import formato_importe

    dinero = dinero_reciente()

    ayer_importe, ayer_pagos = dinero["ayer"]
    semana_importe, semana_pagos = dinero["semana"]

    lineas = [
        "📈 Pulso del bot",
        "",
        f"💰 Ayer: {formato_importe(ayer_importe, 'EUR')} "
        f"({ayer_pagos} pago{'s' if ayer_pagos != 1 else ''})",
        f"💰 7 días: {formato_importe(semana_importe, 'EUR')} "
        f"({semana_pagos} pago{'s' if semana_pagos != 1 else ''})",
    ]

    try:

        from start_offer_service import fetch_sellable_communities

        vendibles = len(fetch_sellable_communities(0, limit=50))

        lineas.append(
            f"🏪 A la venta: {vendibles} comunidad(es)"
        )

    except Exception as e:

        print("Pulso diario: sin escaparate:", str(e)[:160])

    try:

        from sale_readiness_service import _ultimo_estado_del_cobro

        roto = _ultimo_estado_del_cobro.get("roto")

        if roto is True:
            lineas.append("🚨 Cobro: ROTO — nadie puede pagar ahora mismo")

        elif roto is False:
            lineas.append("✅ Cobro: funcionando")

    except Exception:

        pass

    try:

        from platform_funnel_service import fetch_platform_funnel, porcentaje

        embudo = fetch_platform_funnel(days=7)

        conversion = porcentaje(embudo["pagan"], embudo["llegan"])

        lineas.append(
            f"👥 7 días: {embudo['llegan']} llegan · {embudo['miran']} miran · "
            f"{embudo['empiezan']} empiezan · {embudo['pagan']} pagan"
            + (f" ({conversion})" if conversion else "")
        )

    except Exception as e:

        print("Pulso diario: sin embudo:", str(e)[:160])

    if not ayer_pagos and not semana_pagos:

        lineas.extend([
            "",
            "Siete días sin una venta. Lo que más rinde ahora es repartir el "
            "enlace donde ya te lea alguien: «📣 Traer compradores».",
        ])

    return "\n".join(lineas)


def enviar_pulso_diario():
    """Manda el pulso al admin. True si se envió."""

    if not PULSO_ACTIVO:
        return False

    try:

        from bot_config import ADMIN_ID, TOKEN
        from notification_service import send_telegram_message

        if not (ADMIN_ID and TOKEN):
            return False

        send_telegram_message(TOKEN, int(ADMIN_ID), build_daily_pulse_text())

        return True

    except Exception as e:

        print("Pulso diario: no se pudo enviar:", str(e)[:200])

        return False
