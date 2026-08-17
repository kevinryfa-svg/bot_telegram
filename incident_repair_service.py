"""
Resolver un cobro sin acceso en un toque, desde el propio aviso.

Cuando un pago entra y el acceso no se puede conceder —el plan ya no existe,
la duración estaba mal, la comunidad no aparece— el bot avisa al propietario
y a la plataforma con todos los identificadores. Y ahí se acababa: arreglarlo
significaba entrar a la base de datos o inventarse un código promocional. El
comprador, mientras, espera con el dinero pagado.

Aquí el aviso lleva botón: elegir la duración y conceder. Lo hace una
PERSONA con permiso sobre esa comunidad, no un repaso automático — quién
recibe acceso gratis no es una decisión que deba tomar un job.

Las reglas:

  QUIEN PUEDE, PUEDE   Solo el propietario de esa comunidad o un super
                       admin. Se comprueba al pulsar, no al pintar el botón:
                       un callback se puede reenviar.

  NO INVENTA DINERO    No se escribe un pago nuevo: el pago ya existe y
                       duplicarlo falsearía los ingresos del propietario. Se
                       concede el acceso y se cierra la incidencia.

  UNA VEZ              Una incidencia ya resuelta no se puede volver a
                       resolver: el segundo toque no regala otro mes.

  SIEMPRE SE ENTREGA   Al conceder, el comprador recibe su enlace en el
                       momento. Conceder acceso sin avisar es dejar al
                       cliente esperando exactamente igual que antes.
"""

from datetime import datetime, timedelta

from audit_log_service import log_event
from bot_config import TOKEN
from db import conn
from invite_link_service import create_telegram_invite_link


def fetch_open_incident(incident_id):
    """(id, kind, user_id, group_id, telegram_group_id, group_name) o None.

    Solo abiertas: una resuelta no vuelve a conceder nada.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT i.id,
                       i.kind,
                       i.user_id,
                       i.group_id,
                       g.telegram_group_id,
                       COALESCE(g.name, 'la comunidad')
                FROM payment_incidents i
                LEFT JOIN groups g ON g.id = i.group_id
                WHERE i.id = %s
                  AND i.resolved_at IS NULL

            """, (incident_id,))

            return cur.fetchone()

    except Exception as e:

        print("Reparación de incidencia: error leyendo la incidencia:", e)

        return None


def fetch_repair_durations(group_id):
    """[(duration_days, nombre)] de los planes activos de esa comunidad.

    Se ofrecen las duraciones que el propietario ya vende: son las que sabe
    interpretar. Si no queda ninguna, la lista está vacía y quien repara
    tendrá que arreglar antes su catálogo.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT duration_days, name
                FROM plans
                WHERE group_id = %s
                  AND COALESCE(is_active, TRUE) = TRUE
                  AND duration_days IS NOT NULL
                  AND duration_days > 0
                ORDER BY duration_days ASC

            """, (group_id,))

            return cur.fetchall() or []

    except Exception as e:

        print("Reparación de incidencia: error leyendo duraciones:", e)

        return []


def close_incident(incident_id, actor_user_id):
    """Cierra la incidencia. True si esta llamada fue la que la cerró."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_incidents
                SET resolved_at = NOW()
                WHERE id = %s AND resolved_at IS NULL

            """, (incident_id,))

            hecho = cur.rowcount > 0
            conn.commit()

        if hecho:

            log_event(
                "payment_incident_repaired",
                category="payment",
                severity="info",
                scope="global",
                actor_user_id=actor_user_id,
                message="Incidencia de cobro sin acceso resuelta a mano.",
                metadata={"incident_id": incident_id}
            )

        return hecho

    except Exception as e:

        conn.rollback()

        print("Reparación de incidencia: error cerrando:", e)

        return False


def grant_access_for_incident(user_id, group_id, duration_days):
    """Concede el acceso y devuelve su fecha de fin. None si no se pudo.

    NO escribe un pago: el pago ya existe y duplicarlo falsearía los
    ingresos del propietario.
    """

    try:

        expiration = datetime.now() + timedelta(days=int(duration_days))

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO users (user_id, group_id, expiration, subscription_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (user_id, group_id)
                DO UPDATE SET
                    expiration = GREATEST(
                        EXCLUDED.expiration,
                        COALESCE(users.expiration, EXCLUDED.expiration)
                    ),
                    subscription_active = TRUE
                RETURNING expiration

            """, (user_id, group_id, expiration))

            fila = cur.fetchone()
            conn.commit()

        return fila[0] if fila else None

    except Exception as e:

        conn.rollback()

        print("Reparación de incidencia: error concediendo el acceso:", e)

        return None


async def repair_incident(context, incident_id, actor_user_id, duration_days):
    """El arreglo completo: conceder, entregar el enlace y cerrar.

    Devuelve un diccionario con lo que pasó, para que quien llama se lo
    cuente a quien pulsó sin tener que adivinar nada.
    """

    resultado = {
        "ok": False,
        "reason": None,
        "user_id": None,
        "expiration": None,
        "link_sent": False,
    }

    incidencia = fetch_open_incident(incident_id)

    if not incidencia:

        resultado["reason"] = "not_open"
        return resultado

    _id, _kind, user_id, group_id, telegram_group_id, group_name = incidencia

    if not user_id or not group_id:

        resultado["reason"] = "incomplete"
        return resultado


    resultado["user_id"] = user_id

    expiration = grant_access_for_incident(user_id, group_id, duration_days)

    if expiration is None:

        resultado["reason"] = "grant_failed"
        return resultado


    resultado["expiration"] = expiration

    # Cerrar DESPUÉS de conceder: si se cerrara primero y la concesión
    # fallara, la incidencia quedaría enterrada con el cliente sin acceso.
    close_incident(incident_id, actor_user_id)

    # Y entregar. Conceder acceso sin avisar deja al cliente esperando
    # exactamente igual que antes de arreglar nada.
    from i18n_service import load_user_language, t
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    language = load_user_language(user_id)

    enlace = create_telegram_invite_link(
        TOKEN,
        telegram_group_id,
        expire_seconds=86400,
        member_limit=1,
    )

    teclado = None

    if enlace:

        teclado = InlineKeyboardMarkup([[InlineKeyboardButton(
            t("incident.repaired_button", language),
            url=enlace
        )]])

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=t("incident.repaired", language, group=group_name),
            reply_markup=teclado,
        )

        resultado["link_sent"] = True

    except Exception as e:

        log_event(
            "payment_incident_repair_notice_failed",
            category="payment",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            message="Acceso concedido pero no se pudo avisar al comprador.",
            metadata={"error": str(e)[:200], "link_ok": bool(enlace)}
        )


    log_event(
        "payment_incident_access_granted",
        category="payment",
        severity="warning",
        scope="group",
        group_id=group_id,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        message="Acceso concedido a mano desde el aviso de incidencia.",
        metadata={
            "incident_id": incident_id,
            "duration_days": int(duration_days),
            "expiration": str(expiration),
            "link_ok": bool(enlace),
        }
    )

    resultado["ok"] = True

    return resultado
