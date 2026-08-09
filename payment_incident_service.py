"""
El cobro salió bien y el acceso no se pudo conceder.

Hay dos formas de que eso pase, y en las dos el comprador se quedaba en
silencio: solo quedaba una línea en el registro de auditoría.

  - plan_not_found: se cobró por un plan que ya no existe. Reintentar el webhook
    no lo va a arreglar nunca, hace falta una persona.
  - storage_failed: el guardado del acceso falló. Aquí el reintento del proveedor
    sí puede salvarlo, así que puede resolverse solo en unos minutos.

Es peor que el caso del enlace que ya estaba cubierto: allí el acceso quedaba
guardado y el botón «Pedir mi enlace» desbloqueaba al cliente por su cuenta.
Aquí no hay nada guardado, así que no hay nada que pueda hacer solo.

Los proveedores reintentan los webhooks, así que avisar sin más significaría
avisar una y otra vez de la misma incidencia. La clave única de la tabla es lo
que lo evita: se registra antes de enviar, igual que en el resto del bot.
"""

from db import conn
from audit_log_service import log_event
from bot_config import TOKEN, ADMIN_ID
from i18n_service import DEFAULT_LANGUAGE, load_user_language, t
from notification_service import notify_super_admins, send_telegram_message
from rbac_helpers import get_group_owner_user_id


INCIDENT_PLAN_MISSING = "plan_not_found"
INCIDENT_STORAGE_FAILED = "storage_failed"


# Las que no se arreglan reintentando: hace falta una persona.
PERMANENT_INCIDENTS = (INCIDENT_PLAN_MISSING,)


def incident_is_permanent(kind):

    return kind in PERMANENT_INCIDENTS


# =========================
# IDENTIFICAR LA INCIDENCIA
# =========================

def build_incident_key(kind, user_id, group_id, external_payment_id=None,
                       transaction_id=None):
    """
    Identifica una incidencia concreta, para no avisar dos veces de la misma.

    Se prefiere el identificador del proveedor porque es lo único estable entre
    reintentos del mismo webhook. Si no viene, la combinación de persona,
    comunidad y tipo evita al menos la repetición inmediata.
    """

    referencia = (
        str(external_payment_id or "").strip()
        or str(transaction_id or "").strip()
        or f"{user_id}:{group_id}"
    )

    return f"{kind}:{referencia}"[:200]


def record_incident(incident_key, kind, user_id, group_id, provider=None,
                    detail=None):
    """
    Registra la incidencia. Devuelve True solo la primera vez.

    Ese valor de retorno es lo que hace que se avise una sola vez aunque el
    proveedor reintente el webhook veinte veces.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO payment_incidents
                    (incident_key, kind, user_id, group_id, provider, detail)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (incident_key) DO NOTHING

            """, (
                incident_key,
                kind,
                user_id,
                group_id,
                provider,
                str(detail or "")[:500]
            ))

            return cur.rowcount > 0

    except Exception as e:

        print("Incidencia de pago: error registrándola:", e)

        # Sin poder registrar no se puede garantizar que no se repita el aviso,
        # así que no se avisa: repetir el mismo mensaje a alguien que acaba de
        # pagar es peor que no decírselo por este canal.
        return False


def mark_buyer_notified(incident_key):

    try:

        with conn.cursor() as cur:

            cur.execute(
                "UPDATE payment_incidents SET buyer_notified = TRUE "
                "WHERE incident_key = %s",
                (incident_key,)
            )

            return True

    except Exception as e:

        print("Incidencia de pago: error marcando el aviso:", e)

        return False


def resolve_incidents_for(user_id, group_id):
    """
    Cierra las incidencias abiertas de esta persona en esta comunidad.

    Se llama cuando el acceso acaba concediéndose: en storage_failed el
    reintento del proveedor suele arreglarlo, y dejar la incidencia abierta
    haría que se persiguiera un problema que ya no existe.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_incidents
                SET resolved_at = NOW()
                WHERE user_id = %s
                  AND group_id = %s
                  AND resolved_at IS NULL

            """, (user_id, group_id))

            return cur.rowcount

    except Exception as e:

        print("Incidencia de pago: error cerrándolas:", e)

        return 0


def fetch_group_name(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("SELECT name FROM groups WHERE id = %s", (group_id,))

            row = cur.fetchone()

        if row and row[0]:

            return row[0]

    except Exception as e:

        print("Incidencia de pago: error leyendo la comunidad:", e)


    return f"Comunidad {group_id}"


# =========================
# MENSAJES
# =========================

def build_buyer_incident_text(group_name, kind, language=DEFAULT_LANGUAGE):
    """
    Lo que se le dice a quien ha pagado.

    No se le cuenta cuál de los dos fallos ha sido, porque no le sirve de nada;
    sí se le dice lo único que le importa: que el cobro está registrado, que no
    ha perdido el dinero y que hay alguien mirándolo.
    """

    if incident_is_permanent(kind):

        return t("purchase.incident_manual", language, group=group_name)


    return t("purchase.incident_retrying", language, group=group_name)


def build_buyer_incident_keyboard(language=DEFAULT_LANGUAGE):
    """
    Solo soporte: aquí no hay acceso guardado, así que un botón de «pedir mi
    enlace» no tendría nada que darle y solo generaría más frustración.
    """

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("button.support", language),
            callback_data="public_support"
        )]
    ])


def build_staff_incident_text(group_name, kind, user_id, group_id,
                              provider=None, detail=None,
                              external_payment_id=None):
    """
    Aviso para quien puede arreglarlo. Lleva los identificadores a propósito:
    sin ellos hay que buscar el pago a mano.
    """

    if incident_is_permanent(kind):

        cabecera = "🚨 Cobro sin acceso: hace falta intervenir"
        cierre = (
            "El plan por el que se cobró ya no existe, así que el reintento del "
            "proveedor no lo va a arreglar. Hay que conceder el acceso a mano o "
            "devolver el pago."
        )

    else:

        cabecera = "⚠️ Cobro sin acceso: fallo al guardar"
        cierre = (
            "El proveedor reintentará el webhook, así que puede resolverse solo. "
            "Si en unas horas la incidencia sigue abierta, hay que mirarla."
        )


    lineas = [
        cabecera,
        "",
        f"Comunidad: {group_name} (id {group_id})",
        f"Usuario: {user_id}",
        f"Motivo: {kind}"
    ]


    if provider:

        lineas.append(f"Proveedor: {provider}")


    if external_payment_id:

        lineas.append(f"Pago: {external_payment_id}")


    if detail:

        lineas.append(f"Detalle: {str(detail)[:300]}")


    lineas.extend(["", cierre])

    return "\n".join(lineas)


# =========================
# EL AVISO COMPLETO
# =========================

def report_payment_incident(kind, user_id, group_id, provider=None,
                            external_payment_id=None, transaction_id=None,
                            detail=None, notify_buyer=True):
    """
    Registra la incidencia y avisa una sola vez al comprador y a los responsables.

    No lanza nunca: se llama desde dentro de un webhook de cobro, y reventar
    aquí haría que el proveedor reintentase sin fin por un fallo del aviso.
    """

    summary = {
        "recorded": False,
        "buyer_notified": False,
        "staff_notified": False,
        "permanent": incident_is_permanent(kind)
    }


    try:

        incident_key = build_incident_key(
            kind,
            user_id,
            group_id,
            external_payment_id=external_payment_id,
            transaction_id=transaction_id
        )

        # Registrar primero: es lo que evita repetir el aviso en cada reintento.
        if not record_incident(
            incident_key,
            kind,
            user_id,
            group_id,
            provider=provider,
            detail=detail
        ):

            return summary


        summary["recorded"] = True

        group_name = fetch_group_name(group_id)


        if notify_buyer and user_id:

            try:

                language = load_user_language(user_id)

                respuesta = send_telegram_message(
                    TOKEN,
                    user_id,
                    build_buyer_incident_text(group_name, kind, language),
                    reply_markup=build_buyer_incident_keyboard(language).to_dict()
                )

                if respuesta and respuesta.get("ok"):

                    summary["buyer_notified"] = True

                    mark_buyer_notified(incident_key)

            except Exception as e:

                print("Incidencia de pago: no se pudo avisar al comprador:", e)


        aviso = build_staff_incident_text(
            group_name,
            kind,
            user_id,
            group_id,
            provider=provider,
            detail=detail,
            external_payment_id=external_payment_id
        )

        try:

            owner_user_id = get_group_owner_user_id(group_id)

            if owner_user_id and int(owner_user_id) != int(ADMIN_ID):

                send_telegram_message(TOKEN, owner_user_id, aviso)


            enviados = notify_super_admins(
                TOKEN,
                aviso,
                fallback_admin_id=ADMIN_ID
            )

            summary["staff_notified"] = bool(enviados)

        except Exception as e:

            print("Incidencia de pago: no se pudo avisar a los responsables:", e)


        log_event(
            "payment_incident_reported",
            category="payment",
            severity="critical",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Cobro confirmado sin poder conceder el acceso.",
            metadata={
                "kind": kind,
                "provider": provider,
                "external_payment_id": str(external_payment_id or "")[:64],
                "permanent": summary["permanent"],
                "buyer_notified": summary["buyer_notified"]
            }
        )

    except Exception as e:

        print("Incidencia de pago: error inesperado al reportarla:", e)


    return summary
