"""
Alertas de negocio: el propietario se entera del problema HOY, no el lunes.

El resumen semanal cuenta la semana cuando ya pasó. Estas alertas cubren lo
que no puede esperar a un resumen: una racha de cobros fallidos (tarjetas
caducadas o la cuenta de Stripe rota), una caída fuerte de ingresos, o un
pico de gente apagando su renovación. Un mensaje inmediato con el dato
concreto vale más que cualquier panel que hay que ir a mirar.

Las reglas:

  SOLO PROBLEMAS REALES    Cada alerta tiene umbral (3 cobros fallidos en
                           24 h, −50% de ingresos, 3 renovaciones apagadas
                           en 7 días). Por debajo, silencio: una alerta que
                           salta por ruido enseña al dueño a ignorarlas.

  BASE MÍNIMA              La caída de ingresos exige al menos 3 pagos en
                           la semana de referencia: pasar de 1 pago a 0 no
                           es una crisis, es un martes.

  UNA VEZ POR PERIODO      Racha de fallidos: una alerta por día. Caída de
                           ingresos y pico de bajas: una por semana ISO.
                           Registrado ANTES de enviar (clave única): un
                           redeploy no duplica.
"""

import asyncio
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from audit_log_service import log_event
from db import conn
from payment_access_service import MAX_PLAN_DURATION_DAYS
from owner_revenue_service import PAID_STATUSES, formato_importe
from owner_weekly_digest_service import fetch_owned_active_groups


ALERTS_ENABLED = os.environ.get(
    "BUSINESS_ALERTS_ENABLED", "true"
).strip().lower() not in ("0", "false", "no", "off")

FAILED_CHARGES_THRESHOLD = int(
    os.environ.get("BUSINESS_ALERT_FAILED_CHARGES", "3")
)

REVENUE_DROP_PERCENT = int(
    os.environ.get("BUSINESS_ALERT_REVENUE_DROP", "50")
)

REVENUE_MIN_BASE_PAYMENTS = int(
    os.environ.get("BUSINESS_ALERT_REVENUE_MIN_PAYMENTS", "3")
)

CANCELLATIONS_THRESHOLD = int(
    os.environ.get("BUSINESS_ALERT_CANCELLATIONS", "3")
)

ALERT_SEND_DELAY_SECONDS = float(
    os.environ.get("BUSINESS_ALERT_DELAY", "0.5")
)


def clave_dia():
    """'2026-08-17': la caducidad natural de una alerta diaria."""

    try:

        with conn.cursor() as cur:

            cur.execute("SELECT to_char(NOW(), 'YYYY-MM-DD')")

            return cur.fetchone()[0]

    except Exception:

        return "?"


def clave_semana():
    """'2026-33': semana ISO, la misma clave que usa el resumen semanal."""

    try:

        with conn.cursor() as cur:

            cur.execute("SELECT to_char(NOW(), 'IYYY-IW')")

            return cur.fetchone()[0]

    except Exception:

        return "?"


def detect_failed_charge_streak(group_id):
    """Cobros de renovación fallidos en las últimas 24 horas, si son racha.

    Devuelve el recuento cuando alcanza el umbral y 0 en cualquier otro
    caso: uno o dos fallidos sueltos son tarjetas concretas y el comprador
    ya recibió su botón de actualizarla; la racha es lo que huele a
    problema del negocio (o de la cuenta de Stripe entera).
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM audit_logs
                WHERE group_id = %s
                  AND event_type = 'group_subscription_payment_failed'
                  AND created_at >= NOW() - INTERVAL '24 hours'

            """, (group_id,))

            total = (cur.fetchone() or [0])[0]

            return total if total >= FAILED_CHARGES_THRESHOLD else 0

    except Exception as e:

        print("Alertas de negocio: error contando cobros fallidos:", e)

        return 0


def detect_revenue_drop(group_id):
    """(actual, anterior, caida_pct, currency) si los últimos 7 días cayeron
    fuerte frente a los 7 anteriores; None si no hay caída que contar.

    La semana de referencia necesita una base mínima de pagos: sin ella el
    porcentaje es ruido estadístico con signo.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(NULLIF(UPPER(currency), ''), 'EUR'),
                       COALESCE(SUM(amount) FILTER (
                           WHERE payment_date >= NOW() - INTERVAL '7 days'
                       ), 0),
                       COALESCE(SUM(amount) FILTER (
                           WHERE payment_date < NOW() - INTERVAL '7 days'
                       ), 0),
                       COUNT(*) FILTER (
                           WHERE payment_date < NOW() - INTERVAL '7 days'
                       )
                FROM payments
                WHERE group_id = %s
                  AND LOWER(COALESCE(status, '')) IN %s
                  AND payment_date >= NOW() - INTERVAL '14 days'
                GROUP BY 1
                ORDER BY 3 DESC

            """, (group_id, PAID_STATUSES))

            for currency, actual, anterior, pagos_base in cur.fetchall() or []:

                if pagos_base < REVENUE_MIN_BASE_PAYMENTS or not anterior:
                    continue

                caida = (int(anterior) - int(actual)) * 100 // int(anterior)

                if caida >= REVENUE_DROP_PERCENT:

                    return (int(actual), int(anterior), caida, currency)

            return None

    except Exception as e:

        print("Alertas de negocio: error midiendo ingresos:", e)

        return None


def detect_cancellation_spike(group_id):
    """Renovaciones apagadas en los últimos 7 días, si son pico.

    Cuenta el evento group_subscription_autorenew_off (Stripe y PayPal lo
    registran igual). Devuelve el recuento al alcanzar el umbral; 0 si no.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM audit_logs
                WHERE group_id = %s
                  AND event_type = 'group_subscription_autorenew_off'
                  AND created_at >= NOW() - INTERVAL '7 days'

            """, (group_id,))

            total = (cur.fetchone() or [0])[0]

            return total if total >= CANCELLATIONS_THRESHOLD else 0

    except Exception as e:

        print("Alertas de negocio: error contando bajas:", e)

        return 0


def detect_paying_members_locked_out(group_id):
    """Socios con acceso pagado que se quedaron fuera y no se les pudo avisar.

    Cuando alguien sale de la comunidad —o lo saca otro administrador— el bot
    le manda un enlace nuevo si su acceso sigue vivo. A quien nunca abrió el
    bot no se le puede escribir, y eso queda registrado... donde nadie mira.

    Esa persona está pagando y fuera. El propietario es el único que puede
    hacer algo: reconocerla, levantarle un veto puesto por error, o volver a
    meterla a mano. Devuelve el recuento de los últimos 7 días.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(DISTINCT target_user_id)
                FROM audit_logs
                WHERE group_id = %s
                  AND event_type = 'member_return_offer_failed'
                  AND created_at >= NOW() - INTERVAL '7 days'
                  AND target_user_id IS NOT NULL

            """, (group_id,))

            return int((cur.fetchone() or [0])[0] or 0)

    except Exception as e:

        print("Alertas de negocio: error contando socios fuera:", e)

        return 0


def detect_undeliverable_plans(group_id):
    """Planes activos cuya duración el cobro se NIEGA a convertir en acceso.

    El peor estado posible de un catálogo: se puede enseñar, se puede cobrar, y
    el acceso no sale. En producción la única comunidad vendible del sistema
    tenía un plan de 1.300.000 días.

    Desde que el escaparate mira el mismo techo que la concesión de acceso,
    esos planes ya no se ofrecen — lo que quiere decir que su comunidad deja de
    vender del todo y en silencio. Justo por eso hay que decírselo a quien
    puede corregirlo: elegir la duración de verdad es una decisión suya, no de
    un arreglo automático.

    También cuenta los de duración 0. Antes no: 0 significa «acceso permanente»
    para la CONCESIÓN, pero el escaparate no ofrece esos planes a propósito
    (ningún asistente del bot puede crear uno, así que un 0 en la tabla es un
    dato anómalo, y venderlo regalaría acceso de por vida al precio de un mes).
    O sea que un plan a 0 tampoco se vende — y hasta ahora nadie se enteraba,
    porque este aviso además RECOMENDABA poner 0. Seguir ese consejo apagaba la
    alerta y dejaba el plan igual de invendible, pero ya en silencio.

    Devuelve {"largos", "mayor", "ceros"} o None.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*) FILTER (WHERE duration_days > %(max_dias)s),
                       MAX(duration_days) FILTER (WHERE duration_days > %(max_dias)s),
                       COUNT(*) FILTER (WHERE duration_days <= 0)
                FROM plans
                WHERE group_id = %(gid)s
                  AND COALESCE(is_active, TRUE) = TRUE
                  AND duration_days IS NOT NULL
                  AND (duration_days > %(max_dias)s OR duration_days <= 0)

            """, {"gid": group_id, "max_dias": MAX_PLAN_DURATION_DAYS})

            fila = cur.fetchone() or (0, None, 0)

    except Exception as e:

        print("Alertas de negocio: error buscando planes no entregables:", e)

        return None


    largos = int(fila[0] or 0)
    ceros = int(fila[2] or 0)

    if not largos and not ceros:
        return None

    return {
        "largos": largos,
        "mayor": int(fila[1] or 0),
        "ceros": ceros,
    }


def mark_alert_sent(group_id, owner_user_id, alert_key, period_key):
    """True si quedó registrado: entonces toca enviar (y solo entonces)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO business_alerts
                    (group_id, owner_user_id, alert_key, period_key)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (group_id, alert_key, period_key) DO NOTHING

            """, (group_id, owner_user_id, alert_key, period_key))

            hecho = cur.rowcount > 0
            conn.commit()

            return hecho

    except Exception as e:

        print("Alertas de negocio: error registrando alerta:", e)

        return False


def build_alert_keyboard():

    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💰 Abrir panel de ingresos",
                             callback_data="owner_panel_revenue")
    ]])


def collect_group_alerts(group_id, group_name):
    """[(alert_key, period_key, texto)] con todo lo que merece alerta hoy."""

    alertas = []

    # Va primera a propósito: las demás alertas hablan de vender peor, esta de
    # no poder vender.
    imposibles = detect_undeliverable_plans(group_id)

    if imposibles:

        largos = imposibles["largos"]
        ceros = imposibles["ceros"]
        cuantos = largos + ceros

        etiqueta = "plan" if cuantos == 1 else "planes"
        verbo = "tiene" if cuantos == 1 else "tienen"

        detalles = []

        if largos:

            detalles.append(
                f"{largos} con {imposibles['mayor']} días o más, por encima "
                f"del máximo de {MAX_PLAN_DURATION_DAYS}"
            )

        if ceros:
            detalles.append(f"{ceros} con la duración a 0")

        alertas.append((
            "undeliverable_plans", clave_semana(),
            f"🚨 {cuantos} {etiqueta} de {group_name} {verbo} una duración que "
            f"no se puede vender ({'; '.join(detalles)}).\n\n"
            "No se ofrecen a nadie, así que esa comunidad no está vendiendo por "
            "ellos. Antes era peor: se ofrecían, se cobraba y el acceso no se "
            "concedía.\n\n"
            "Edítalo en «Planes» y pon los días reales, entre 1 y "
            f"{MAX_PLAN_DURATION_DAYS} (unos diez años). El 0 NO vale: no lo "
            "ofrece el escaparate."
        ))


    racha = detect_failed_charge_streak(group_id)

    if racha:

        alertas.append((
            "failed_charges", clave_dia(),
            f"🚨 {racha} cobros de renovación fallidos en 24 horas en "
            f"{group_name}.\n\n"
            "Suele ser tarjetas caducadas — cada comprador ya tiene su "
            "botón para actualizarla — pero una racha así también puede "
            "ser un problema de tu cuenta de pagos. Merece un vistazo hoy."
        ))


    caida = detect_revenue_drop(group_id)

    if caida:

        actual, anterior, pct, currency = caida

        alertas.append((
            "revenue_drop", clave_semana(),
            f"📉 Los ingresos de {group_name} caen un {pct}%.\n\n"
            f"Últimos 7 días: {formato_importe(actual, currency)} — "
            f"los 7 anteriores fueron {formato_importe(anterior, currency)}."
        ))


    bajas = detect_cancellation_spike(group_id)

    if bajas:

        alertas.append((
            "cancellation_spike", clave_semana(),
            f"🔻 {bajas} personas han apagado su renovación en "
            f"{group_name} en los últimos 7 días.\n\n"
            "Cuando las bajas vienen en grupo suelen compartir motivo: "
            "una subida de precio, contenido parado, o un competidor. "
            "Preguntar a uno de ellos vale oro."
        ))


    fuera = detect_paying_members_locked_out(group_id)

    if fuera:

        personas = "persona" if fuera == 1 else "personas"
        pronombre = "Está" if fuera == 1 else "Están"

        alertas.append((
            "locked_out", clave_semana(),
            f"🚪 {fuera} {personas} con acceso pagado a {group_name} se han "
            "quedado fuera de la comunidad y no hemos podido avisarles "
            "(nunca abrieron el bot).\n\n"
            f"{pronombre} pagando y sin poder entrar, y es el peor sitio "
            "donde puede estar un cliente. Si reconoces a alguien, "
            "vuelve a invitarle o revisa si tiene un veto puesto por error."
        ))


    return alertas


async def process_business_alerts(context):
    """El job periódico. Idempotente por periodo: repetirlo no duplica."""

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    if not ALERTS_ENABLED:

        return summary


    filas = fetch_owned_active_groups()

    for owner_user_id, group_id, group_name in filas:

        for alert_key, period_key, texto in collect_group_alerts(
                group_id, group_name):

            summary["targets"] += 1

            if not mark_alert_sent(group_id, owner_user_id,
                                   alert_key, period_key):

                summary["skipped"] += 1
                continue

            try:

                await context.bot.send_message(
                    chat_id=owner_user_id,
                    text=texto,
                    reply_markup=build_alert_keyboard(),
                )

                summary["sent"] += 1

            except Exception as e:

                print(f"Alertas de negocio: no se pudo avisar a "
                      f"{owner_user_id}:", str(e)[:200])
                summary["failed"] += 1

            await asyncio.sleep(ALERT_SEND_DELAY_SECONDS)


    if summary["sent"] or summary["failed"]:

        log_event(
            "business_alerts_sent",
            category="billing",
            severity="warning",
            scope="global",
            message="Alertas de negocio enviadas a propietarios.",
            metadata=summary,
        )

    return summary
