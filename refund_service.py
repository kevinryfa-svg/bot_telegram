"""
Retirar el acceso cuando se devuelve un pago.

Faltaba por completo. PAYMENT_STATUS_REFUNDED existía y los proveedores de
cripto sabían detectar el estado, pero ningún sitio quitaba el acceso; y el
webhook de Stripe no escuchaba charge.refunded ni charge.dispute.created. El
resultado: alguien pagaba, entraba, pedía la devolución y se quedaba dentro para
siempre. Con una disputa de tarjeta era peor: perdías el dinero y el acceso
seguía dado.

Lo que hace este módulo, en este orden:
  1. marca el pago como devuelto (queda el historial, no se borra nada);
  2. desactiva el acceso;
  3. revoca los enlaces de invitación que tuviera, para que no pueda volver a
     entrar con uno viejo;
  4. lo expulsa del grupo;
  5. avisa a la persona y al propietario de la comunidad.

Es idempotente: los proveedores reintentan los webhooks, y aplicar dos veces la
misma devolución no debe expulsar dos veces ni avisar dos veces.
"""

from db import conn
from audit_log_service import log_event
from bot_config import TOKEN, ADMIN_ID
from i18n_service import DEFAULT_LANGUAGE, load_user_language, t
from invite_link_service import revoke_and_delete_user_group_links
from notification_service import notify_super_admins, send_telegram_message
from payment_gateway_config import PAYMENT_STATUS_REFUNDED
from rbac_helpers import get_group_owner_user_id
from telegram_group_actions import kick_chat_member


REFUND_REASON_REFUND = "refund"
REFUND_REASON_DISPUTE = "dispute"


# =========================
# LOCALIZAR EL PAGO
# =========================

def find_payment_by_external_id(external_payment_id):
    """
    Busca el pago por el identificador que manda el proveedor.

    Devuelve (user_id, group_id, amount, currency, status) o None.
    """

    if not external_payment_id:

        return None


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id,
                       group_id,
                       amount,
                       COALESCE(NULLIF(currency, ''), 'EUR'),
                       COALESCE(status, '')
                FROM payments
                WHERE stripe_payment_id = %s
                ORDER BY id DESC
                LIMIT 1

            """, (str(external_payment_id),))

            return cur.fetchone()

    except Exception as e:

        print("Devolución: error buscando el pago:", e)

        return None


def find_payment_by_transaction(external_payment_id=None,
                                external_checkout_id=None):
    """
    Respaldo por payment_transactions, que es donde registran los proveedores
    que no son Stripe.
    """

    filtros = []
    params = []

    if external_payment_id:

        filtros.append("external_payment_id = %s")
        params.append(str(external_payment_id))


    if external_checkout_id:

        filtros.append("external_checkout_id = %s")
        params.append(str(external_checkout_id))


    if not filtros:

        return None


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT user_id,
                       group_id,
                       amount,
                       COALESCE(NULLIF(currency, ''), 'EUR'),
                       COALESCE(status, '')
                FROM payment_transactions
                WHERE ({" OR ".join(filtros)})
                  AND user_id IS NOT NULL
                  AND group_id IS NOT NULL
                ORDER BY id DESC
                LIMIT 1

            """, params)

            return cur.fetchone()

    except Exception as e:

        print("Devolución: error buscando la transacción:", e)

        return None


# =========================
# MARCAR Y RETIRAR
# =========================

def mark_payment_refunded(user_id, group_id, external_payment_id=None):
    """
    Marca el pago como devuelto. Devuelve True si cambió algo.

    El valor de retorno es lo que hace idempotente todo el proceso: si el pago
    ya estaba marcado, no se vuelve a expulsar ni a avisar.
    """

    cambiado = False

    try:

        with conn.cursor() as cur:

            if external_payment_id:

                cur.execute("""

                    UPDATE payments
                    SET status = %s
                    WHERE stripe_payment_id = %s
                      AND COALESCE(status, '') <> %s

                """, (
                    PAYMENT_STATUS_REFUNDED,
                    str(external_payment_id),
                    PAYMENT_STATUS_REFUNDED
                ))

                cambiado = cur.rowcount > 0


            if not cambiado:

                cur.execute("""

                    UPDATE payments
                    SET status = %s
                    WHERE user_id = %s
                      AND group_id = %s
                      AND COALESCE(status, '') <> %s

                """, (
                    PAYMENT_STATUS_REFUNDED,
                    user_id,
                    group_id,
                    PAYMENT_STATUS_REFUNDED
                ))

                cambiado = cur.rowcount > 0


            # La transacción también, para que los informes cuadren.
            if external_payment_id:

                cur.execute("""

                    UPDATE payment_transactions
                    SET status = %s
                    WHERE external_payment_id = %s

                """, (PAYMENT_STATUS_REFUNDED, str(external_payment_id)))

    except Exception as e:

        print("Devolución: error marcando el pago:", e)

        return False


    return cambiado


def deactivate_access(user_id, group_id):
    """
    Desactiva el acceso sin borrar el historial. Devuelve True si estaba activo.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET subscription_active = FALSE
                WHERE user_id = %s
                  AND group_id = %s
                  AND COALESCE(subscription_active, FALSE) = TRUE

            """, (user_id, group_id))

            return cur.rowcount > 0

    except Exception as e:

        print("Devolución: error desactivando el acceso:", e)

        return False


def fetch_group_for_refund(group_id):
    """Nombre y chat de Telegram, para expulsar y para el mensaje."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT name, telegram_group_id
                FROM groups
                WHERE id = %s

            """, (group_id,))

            return cur.fetchone()

    except Exception as e:

        print("Devolución: error leyendo el grupo:", e)

        return None


# =========================
# MENSAJES
# =========================

def build_refund_notice(group_name, reason, language=DEFAULT_LANGUAGE):

    if reason == REFUND_REASON_DISPUTE:

        return t("refund.dispute_notice", language, group=group_name)


    return t("refund.notice", language, group=group_name)


# =========================
# PROCESO COMPLETO
# =========================

def process_refund(external_payment_id=None, external_checkout_id=None,
                   reason=REFUND_REASON_REFUND, user_id=None, group_id=None,
                   refunded_amount=None):
    """
    Retira el acceso asociado a un pago devuelto.

    refunded_amount sirve para los avisos que dicen cuánto se ha devuelto pero
    no cuánto se cobró (el objeto reembolso de Stripe, por ejemplo). Si es menor
    que el importe del pago guardado, se trata como devolución parcial y el
    acceso no se toca.

    No lanza nunca: un webhook que revienta hace que el proveedor reintente sin
    fin. Devuelve un resumen de lo ocurrido.
    """

    summary = {
        "found": False,
        "already_refunded": False,
        "partial": False,
        "access_revoked": False,
        "kicked": False,
        "notified": False,
        "reason": reason
    }


    fila = None

    if user_id is None or group_id is None:

        fila = (
            find_payment_by_external_id(external_payment_id)
            or find_payment_by_transaction(
                external_payment_id=external_payment_id,
                external_checkout_id=external_checkout_id
            )
        )

        if not fila:

            log_event(
                "refund_payment_not_found",
                category="payment",
                severity="warning",
                message="Devolución recibida de un pago que no se encuentra.",
                metadata={
                    "external_payment_id": str(external_payment_id or "")[:64],
                    "external_checkout_id": str(external_checkout_id or "")[:64],
                    "reason": reason
                }
            )

            return summary


        user_id, group_id = fila[0], fila[1]


    summary["found"] = True

    # Devolución parcial: se ha devuelto parte del dinero, pero lo que compró
    # sigue siendo suyo. Solo se puede comprobar aquí cuando el aviso trae el
    # importe devuelto y conocemos el del pago.
    if refunded_amount is not None and fila and fila[2] is not None:

        try:

            if int(refunded_amount) < int(fila[2]):

                summary["partial"] = True

                log_event(
                    "refund_partial_ignored",
                    category="payment",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Devolución parcial: el acceso se mantiene.",
                    metadata={
                        "external_payment_id": str(external_payment_id or "")[:64],
                        "amount": fila[2],
                        "refunded_amount": refunded_amount,
                        "reason": reason
                    }
                )

                return summary

        except (TypeError, ValueError):

            # Importes no comparables: se sigue por el camino normal antes que
            # dejar sin retirar un acceso que sí toca retirar.
            pass


    # Marcar primero: es lo que evita expulsar y avisar dos veces cuando el
    # proveedor reintenta el webhook.
    if not mark_payment_refunded(user_id, group_id, external_payment_id):

        summary["already_refunded"] = True

        return summary


    summary["access_revoked"] = deactivate_access(user_id, group_id)

    grupo = fetch_group_for_refund(group_id)
    group_name = (grupo[0] if grupo else None) or f"Comunidad {group_id}"
    telegram_group_id = grupo[1] if grupo else None


    if telegram_group_id:

        # Los enlaces viejos primero: si se expulsa sin revocarlos, podría
        # volver a entrar con uno que todavía valga.
        try:

            revoke_and_delete_user_group_links(
                TOKEN,
                user_id,
                telegram_group_id
            )

        except Exception as e:

            print("Devolución: error revocando enlaces:", e)


        try:

            kick_chat_member(TOKEN, telegram_group_id, user_id)

            summary["kicked"] = True

        except Exception as e:

            print("Devolución: no se pudo expulsar:", e)


    # Se le dice por qué, aunque sea él quien pidió la devolución: quedarse sin
    # acceso y sin explicación acaba en un ticket de soporte de todas formas.
    try:

        respuesta = send_telegram_message(
            TOKEN,
            user_id,
            build_refund_notice(
                group_name,
                reason,
                language=load_user_language(user_id)
            )
        )

        summary["notified"] = bool(respuesta and respuesta.get("ok"))

    except Exception as e:

        print("Devolución: no se pudo avisar al usuario:", e)


    aviso_admin = (
        "↩️ Devolución procesada\n\n"
        f"Comunidad: {group_name}\n"
        f"Usuario: {user_id}\n"
        f"Motivo: {'disputa de tarjeta' if reason == REFUND_REASON_DISPUTE else 'devolución'}\n"
        f"Acceso retirado: {'sí' if summary['access_revoked'] else 'no estaba activo'}\n"
        f"Expulsado del grupo: {'sí' if summary['kicked'] else 'no'}"
    )

    try:

        owner_user_id = get_group_owner_user_id(group_id)

        if owner_user_id and int(owner_user_id) != int(ADMIN_ID):

            send_telegram_message(TOKEN, owner_user_id, aviso_admin)


        notify_super_admins(TOKEN, aviso_admin, fallback_admin_id=ADMIN_ID)

    except Exception as e:

        print("Devolución: no se pudo avisar a los responsables:", e)


    log_event(
        "refund_processed",
        category="payment",
        severity="warning",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Devolución procesada y acceso retirado.",
        metadata={
            "external_payment_id": str(external_payment_id or "")[:64],
            "reason": reason,
            "access_revoked": summary["access_revoked"],
            "kicked": summary["kicked"],
            "notified": summary["notified"]
        }
    )

    return summary
