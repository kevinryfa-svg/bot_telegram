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
