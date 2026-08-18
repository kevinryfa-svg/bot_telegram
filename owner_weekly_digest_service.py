"""
El resumen semanal del propietario: su negocio, en un mensaje, sin pedirlo.

El panel de ingresos existe, pero hay que ir a mirarlo — y el propietario
que no mira no se entera de que su semana fue mala hasta fin de mes. Cada
lunes, un mensaje con la semana COMPLETA anterior (lunes a domingo): ingresos
contra la semana previa, altas, caducados, renovaciones cobradas, incidencias
abiertas y el estado de entrega.

Las reglas:

  SEMANAS DE CALENDARIO   Se compara lunes-a-domingo contra lunes-a-domingo.
                          Las ventanas móviles ("últimos 7 días") dan
                          porcentajes que cambian según la hora de envío.

  UNA VEZ POR SEMANA      Registrado ANTES de enviar (la clave única es
                          propietario+grupo+semana): un redeploy en lunes no
                          puede duplicar el mensaje.

  SOLO COMUNIDADES VIVAS  Un grupo sin un solo pago histórico y sin socios
                          activos no genera resumen: el silencio también es
                          información, pero el spam no.
"""

import asyncio
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from audit_log_service import log_event
from db import conn
from owner_revenue_service import PAID_STATUSES, formato_importe


DIGEST_ENABLED = os.environ.get(
    "OWNER_WEEKLY_DIGEST_ENABLED", "true"
).strip().lower() not in ("0", "false", "no", "off")

DIGEST_SEND_DELAY_SECONDS = float(
    os.environ.get("OWNER_WEEKLY_DIGEST_DELAY", "0.5")
)


def fetch_owned_active_groups():
    """(owner_user_id, group_id, group_name) de cada comunidad viva con dueño.

    Viva = con algún pago histórico o algún socio activo: a un grupo muerto
    no se le escribe un resumen de nada.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT a.user_id, g.id, COALESCE(g.name, 'Comunidad ' || g.id)
                FROM admins a
                JOIN groups g ON g.id = a.group_id
                WHERE a.role = 'GROUP_OWNER'
                  AND COALESCE(a.is_active, TRUE) = TRUE
                  AND COALESCE(g.is_active, TRUE) = TRUE
                  AND (
                      EXISTS (SELECT 1 FROM payments p WHERE p.group_id = g.id)
                      OR EXISTS (
                          SELECT 1 FROM users u
                          WHERE u.group_id = g.id
                            AND COALESCE(u.subscription_active, FALSE) = TRUE
                      )
                  )
                ORDER BY g.id

            """)

            return cur.fetchall() or []

    except Exception as e:

        print("Resumen semanal: error listando comunidades:", e)

        return []


def fetch_week_numbers(group_id):
    """
    La semana COMPLETA anterior (lunes a domingo) contra la previa.

    date_trunc('week', ...) en Postgres empieza en lunes: la semana pasada es
    [trunc(now)-7d, trunc(now)) y la anterior, otra ventana igual detrás.
    """

    datos = {
        "ingresos": [],          # [(currency, semana_pasada, semana_anterior)]
        "pagos": 0,
        "altas": 0,
        "caducados": 0,
        "renovaciones": 0,
        "incidencias": 0,
    }

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(NULLIF(UPPER(currency), ''), 'EUR'),
                       COALESCE(SUM(amount) FILTER (
                           WHERE payment_date >= date_trunc('week', NOW()) - INTERVAL '7 days'
                             AND payment_date < date_trunc('week', NOW())
                       ), 0),
                       COALESCE(SUM(amount) FILTER (
                           WHERE payment_date >= date_trunc('week', NOW()) - INTERVAL '14 days'
                             AND payment_date < date_trunc('week', NOW()) - INTERVAL '7 days'
                       ), 0),
                       COUNT(*) FILTER (
                           WHERE payment_date >= date_trunc('week', NOW()) - INTERVAL '7 days'
                             AND payment_date < date_trunc('week', NOW())
                       )
                FROM payments
                WHERE group_id = %s
                  AND LOWER(COALESCE(status, '')) IN %s
                  AND payment_date >= date_trunc('week', NOW()) - INTERVAL '14 days'
                GROUP BY 1
                ORDER BY 2 DESC

            """, (group_id, PAID_STATUSES))

            for currency, semana, anterior, pagos in cur.fetchall() or []:

                datos["ingresos"].append((currency, semana, anterior))
                datos["pagos"] += pagos


            cur.execute("""

                SELECT
                    COUNT(*) FILTER (
                        WHERE created_at >= date_trunc('week', NOW()) - INTERVAL '7 days'
                          AND created_at < date_trunc('week', NOW())
                    ),
                    COUNT(*) FILTER (
                        WHERE expiration >= date_trunc('week', NOW()) - INTERVAL '7 days'
                          AND expiration < date_trunc('week', NOW())
                          AND COALESCE(subscription_active, FALSE) = FALSE
                    )
                FROM users
                WHERE group_id = %s

            """, (group_id,))

            fila = cur.fetchone()

            if fila:

                datos["altas"], datos["caducados"] = fila


            # Renovación: segundo pago (o posterior) de la misma persona.
            cur.execute("""

                SELECT COUNT(*)
                FROM payments p
                WHERE p.group_id = %s
                  AND LOWER(COALESCE(p.status, '')) IN %s
                  AND p.payment_date >= date_trunc('week', NOW()) - INTERVAL '7 days'
                  AND p.payment_date < date_trunc('week', NOW())
                  AND EXISTS (
                      SELECT 1 FROM payments antes
                      WHERE antes.user_id = p.user_id
                        AND antes.group_id = p.group_id
                        AND antes.id < p.id
                        AND LOWER(COALESCE(antes.status, '')) IN %s
                  )

            """, (group_id, PAID_STATUSES, PAID_STATUSES))

            datos["renovaciones"] = (cur.fetchone() or [0])[0]


            cur.execute("""

                SELECT COUNT(*)
                FROM payment_incidents
                WHERE group_id = %s AND resolved_at IS NULL

            """, (group_id,))

            datos["incidencias"] = (cur.fetchone() or [0])[0]

    except Exception as e:

        print("Resumen semanal: error leyendo números:", e)


    return datos


def semana_actual_clave():
    """'2026-33': la clave de deduplicación. Del calendario, no del reloj."""

    try:

        with conn.cursor() as cur:

            cur.execute("SELECT to_char(NOW(), 'IYYY-IW')")

            return cur.fetchone()[0]

    except Exception:

        return "?"


def mark_digest_sent(owner_user_id, group_id, week_key):
    """True si quedó registrado: entonces toca enviarlo (y solo entonces)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO owner_weekly_digests (owner_user_id, group_id, week_key)
                VALUES (%s, %s, %s)
                ON CONFLICT (owner_user_id, group_id, week_key) DO NOTHING

            """, (owner_user_id, group_id, week_key))

            hecho = cur.rowcount > 0
            conn.commit()

            return hecho

    except Exception as e:

        print("Resumen semanal: error registrando:", e)

        return False


def formato_semana(filas):

    if not filas:

        return "0.00 EUR"


    partes = []

    for currency, semana, anterior in filas:

        trozo = formato_importe(semana, currency)

        if anterior:

            delta = (int(semana) - int(anterior)) * 100 // int(anterior)
            signo = "+" if delta >= 0 else ""
            trozo += f" ({signo}{delta}% vs anterior)"

        elif semana:

            trozo += " (semana anterior: 0)"

        partes.append(trozo)


    return " · ".join(partes)


def clave_mes():
    """'2026-08': la clave de la sugerencia, que es mensual y no semanal.

    Del reloj de la base de datos, como la clave de la semana: dos procesos con
    la hora distinta se repartirían el mes y la sugerencia saldría dos veces.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("SELECT to_char(NOW(), 'YYYY-MM')")

            return cur.fetchone()[0]

    except Exception:

        # Con "?" la clave sigue siendo estable: una sugerencia como mucho, en
        # vez de una por pasada.
        return "?"


def build_weekly_digest_text(group_id, group_name, sugerencia=None):

    from group_delivery_health_service import describe_group_delivery

    numeros = fetch_week_numbers(group_id)

    lineas = [
        f"📬 Tu semana en {group_name}",
        "",
        f"💰 Ingresos: {formato_semana(numeros['ingresos'])}",
        f"Pagos cobrados: {numeros['pagos']} "
        f"(de ellos, renovaciones: {numeros['renovaciones']})",
        "",
        f"👥 Altas: {numeros['altas']} · Caducados sin volver: {numeros['caducados']}",
        "",
        f"🩺 Entrega de accesos: {describe_group_delivery(group_id)}",
    ]

    if numeros["incidencias"]:

        lineas.append(
            f"⚠️ Incidencias de pago abiertas: {numeros['incidencias']} — "
            "hay cobros sin acceso concedido esperándote."
        )

    lineas.extend([
        "",
        "El panel de ingresos tiene el detalle completo y el CSV.",
    ])

    if sugerencia:

        from owner_addon_service import format_addon_monthly_price

        # El precio va DENTRO del texto, no solo en el botón: una sugerencia sin
        # precio obliga a entrar para saber cuánto cuesta, y eso ya no es una
        # oferta, es un anzuelo.
        lineas.extend([
            "",
            f"📣 Pocas altas esta semana. {sugerencia.get('name')} publica tu "
            "comunidad en canales de publicidad de forma automática, por "
            f"{format_addon_monthly_price(sugerencia)}. Se cancela cuando "
            "quieras.",
        ])

    return "\n".join(lineas)


def build_digest_keyboard(sugerencia=None):

    filas = [[InlineKeyboardButton("💰 Abrir panel de ingresos",
                                   callback_data="owner_panel_revenue")]]

    if sugerencia:

        from owner_addon_service import format_addon_monthly_price

        filas.append([InlineKeyboardButton(
            f"📣 {sugerencia.get('name')} · "
            f"{format_addon_monthly_price(sugerencia)}",
            callback_data="owner_addons_menu"
        )])

    return InlineKeyboardMarkup(filas)


async def process_weekly_digests(context):
    """El job de los lunes. Idempotente por semana: un redeploy no duplica."""

    summary = {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}

    if not DIGEST_ENABLED:

        return summary


    week_key = semana_actual_clave()
    filas = fetch_owned_active_groups()

    summary["targets"] = len(filas)

    for owner_user_id, group_id, group_name in filas:

        if not mark_digest_sent(owner_user_id, group_id, week_key):

            summary["skipped"] += 1
            continue

        # La sugerencia se pide UNA vez por comunidad y se pasa al texto y al
        # botón. Pedirla dos veces gastaría la marca mensual en la primera
        # llamada y la segunda volvería vacía: el texto ofrecería un servicio
        # que el teclado no tendría, o al revés.
        sugerencia = None

        try:

            from owner_addon_service import fetch_addon_suggestion

            sugerencia = fetch_addon_suggestion(
                group_id,
                owner_user_id,
                fetch_week_numbers(group_id).get("altas"),
                period_key=clave_mes(),
            )

        except Exception as e:

            print("Resumen semanal: no se pudo preparar la sugerencia:",
                  str(e)[:200])

        try:

            await context.bot.send_message(
                chat_id=owner_user_id,
                text=build_weekly_digest_text(
                    group_id, group_name, sugerencia=sugerencia
                ),
                reply_markup=build_digest_keyboard(sugerencia=sugerencia),
            )

            summary["sent"] += 1

        except Exception as e:

            print(f"Resumen semanal: no se pudo enviar a {owner_user_id}:",
                  str(e)[:200])
            summary["failed"] += 1

        await asyncio.sleep(DIGEST_SEND_DELAY_SECONDS)


    if summary["sent"] or summary["failed"]:

        log_event(
            "owner_weekly_digests_sent",
            category="billing",
            severity="info",
            scope="global",
            message="Resúmenes semanales enviados a propietarios.",
            metadata=summary,
        )

    return summary
