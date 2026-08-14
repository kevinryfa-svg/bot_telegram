"""
El interruptor del comprador para las suscripciones de PayPal.

Los planes de grupo de PayPal SIEMPRE fueron suscripciones (billing
subscriptions): cada ciclo llega un PAYMENT.SALE.COMPLETED y el acceso se
renueva. Lo que no había era forma de apagarlo desde el bot: el comprador
tenía que bucear en su cuenta de PayPal.

Una diferencia con Stripe que manda en los textos: PayPal NO permite reactivar
una suscripción cancelada (solo las suspendidas se reanudan). Así que aquí
cancelar es definitivo — el acceso dura hasta el final del periodo ya pagado,
y para volver hay que suscribirse de nuevo. Por eso el botón pide
confirmación y el texto no promete ninguna reactivación.

El ancla es payment_transactions.external_checkout_id (el id I-... de la
suscripción), guardado al crear el pedido.
"""

from db import conn

# Referencias a través del módulo, no importadas por valor: el proveedor es la
# única fuente de credenciales/red y así cualquier sustitución (pruebas,
# parches en caliente) llega también aquí.
import payment_providers.paypal_provider as _pp

from payment_gateway_config import (
    PAYMENT_PROVIDER_PAYPAL,
    PAYMENT_STATUS_PAID,
    PURCHASE_TYPE_GROUP_ACCESS,
)


def fetch_paypal_subscription_for_member(user_id, group_id):
    """El id de suscripción PayPal del último acceso pagado de este socio."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT external_checkout_id
                FROM payment_transactions
                WHERE provider=%s
                  AND user_id=%s
                  AND group_id=%s
                  AND purchase_type=%s
                  AND status=%s
                  AND external_checkout_id IS NOT NULL
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT 1

            """, (
                PAYMENT_PROVIDER_PAYPAL,
                user_id,
                group_id,
                PURCHASE_TYPE_GROUP_ACCESS,
                PAYMENT_STATUS_PAID,
            ))

            row = cur.fetchone()

        return row[0] if row else None

    except Exception as e:

        print("PayPal renovación: error buscando la suscripción del socio:", e)

        return None


def _credenciales_y_base(group_id):
    credentials = _pp.get_group_paypal_credentials(group_id)

    if not credentials:
        return None, None, None

    token = _pp.get_paypal_access_token_for_credentials(
        credentials.get("client_id"),
        credentials.get("client_secret"),
        credentials.get("mode") or "sandbox",
    )

    base = _pp.get_paypal_base_url_for_mode(credentials.get("mode") or "sandbox")

    return credentials, token, base


def fetch_paypal_renewal_state(user_id, group_id):
    """
    Para «Mis suscripciones»: si el acceso de este socio es una suscripción de
    PayPal y en qué estado está. None si no lo es o no se puede saber.
    """

    subscription_id = fetch_paypal_subscription_for_member(user_id, group_id)

    if not subscription_id:
        return None

    try:

        credentials, token, base = _credenciales_y_base(group_id)

        if not token:
            return None

        # El módulo requests es compartido: se usa la referencia del proveedor
        # para que las pruebas lo sustituyan en UN sitio, no en dos.
        respuesta = _pp.requests.get(
            f"{base}/v1/billing/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )

        datos = respuesta.json() or {}
        estado = (datos.get("status") or "").upper()

        return {
            "provider": "paypal",
            "subscription_id": subscription_id,
            "status": estado,
            "activa": estado in ("ACTIVE", "APPROVED"),
            "cancelada": estado in ("CANCELLED", "EXPIRED", "SUSPENDED"),
        }

    except Exception as e:

        print("PayPal renovación: error leyendo el estado:", str(e)[:200])

        return None


def cancel_paypal_renewal(user_id, group_id):
    """
    Apaga los cobros futuros. El acceso del periodo ya pagado no se toca (lo
    gobierna users.expiration, no PayPal). Devuelve True si PayPal aceptó.

    DEFINITIVO en PayPal: una suscripción cancelada no se puede reactivar;
    para volver hay que suscribirse de nuevo. El que llama ya lo ha avisado.
    """

    subscription_id = fetch_paypal_subscription_for_member(user_id, group_id)

    if not subscription_id:
        return False

    try:

        credentials, token, base = _credenciales_y_base(group_id)

        if not token:
            return False

        respuesta = _pp.requests.post(
            f"{base}/v1/billing/subscriptions/{subscription_id}/cancel",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"reason": "Cancelada por el comprador desde el bot."},
            timeout=15,
        )

        # PayPal responde 204 sin cuerpo cuando acepta la cancelación.
        return respuesta.status_code in (200, 204)

    except Exception as e:

        print("PayPal renovación: error cancelando:", str(e)[:200])

        return False
