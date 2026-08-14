"""
Autoconfiguración del webhook de PayPal: el seguro que ya salvó a Stripe.

PayPal solo manda los eventos suscritos en el webhook. El bot puede atender
BILLING.SUBSCRIPTION.CANCELLED perfectamente y no enterarse nunca de una baja
porque ese evento no está suscrito: sin error, sin traza, sin nada. Es
exactamente el agujero que la comprobación de Stripe destapó en producción
(faltaban 8 de 9 eventos) — aquí las renovaciones y bajas de PayPal se
perderían en silencio.

Al arrancar, para cada webhook configurado (el de la plataforma y el de cada
comunidad), se comprueba qué eventos tiene suscritos y se AÑADEN los que
falten. Nunca se quita nada: si el propietario suscribió eventos suyos, se
conservan. PAYPAL_WEBHOOK_AUTOFIX=0 lo deja en solo-avisar.

A diferencia de Stripe, aquí la capa es HTTP directa (requests → JSON): los
dicts planos son la forma real de producción.
"""

import os

from audit_log_service import log_event
from db import conn

import payment_providers.paypal_provider as pp


# Todos los eventos que el procesador del webhook atiende hoy. Si alguien
# añade un evento nuevo al procesador y no aquí, la prueba de paridad lo dirá.
REQUIRED_EVENTS = (
    "PAYMENT.SALE.COMPLETED",
    "PAYMENT.SALE.DENIED",
    "PAYMENT.SALE.REFUNDED",
    "PAYMENT.SALE.REVERSED",
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.SUSPENDED",
    "BILLING.SUBSCRIPTION.EXPIRED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.DECLINED",
)


AUTOFIX_ENABLED = os.environ.get(
    "PAYPAL_WEBHOOK_AUTOFIX", "1"
).strip().lower() not in ("0", "false", "no", "off")


def fetch_paypal_configured_group_ids():
    """Las comunidades con PayPal activo: cada una tiene su propio webhook."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT group_id
                FROM group_payment_provider_configs
                WHERE provider = 'paypal'
                  AND COALESCE(is_enabled, FALSE) = TRUE
                  AND group_id IS NOT NULL
                ORDER BY group_id

            """)

            return [row[0] for row in cur.fetchall()]

    except Exception as e:

        print("Webhook de PayPal: error listando comunidades configuradas:", e)

        return []


def leer_eventos_del_webhook(base_url, token, webhook_id):
    """Los eventos suscritos hoy. None si el webhook no se puede leer."""

    try:

        respuesta = pp.requests.get(
            f"{base_url}/v1/notifications/webhooks/{webhook_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )

        if respuesta.status_code != 200:

            print(f"Webhook de PayPal {webhook_id}: HTTP {respuesta.status_code} al leerlo")
            return None

        datos = respuesta.json() or {}

        return [
            (e or {}).get("name")
            for e in (datos.get("event_types") or [])
            if (e or {}).get("name")
        ]

    except Exception as e:

        print(f"Webhook de PayPal {webhook_id}: error leyéndolo:", str(e)[:200])

        return None


def suscribir_eventos(base_url, token, webhook_id, eventos_finales):
    """PATCH con la lista COMPLETA (los suyos + los nuestros): PayPal
    reemplaza, así que quitar de la lista sería des-suscribir."""

    try:

        respuesta = pp.requests.patch(
            f"{base_url}/v1/notifications/webhooks/{webhook_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=[{
                "op": "replace",
                "path": "/event_types",
                "value": [{"name": nombre} for nombre in eventos_finales],
            }],
            timeout=20,
        )

        return respuesta.status_code == 200

    except Exception as e:

        print(f"Webhook de PayPal {webhook_id}: error suscribiendo:", str(e)[:200])

        return False


def revisar_webhook(base_url, token, webhook_id, etiqueta):
    """
    Comprueba un webhook y añade lo que falte. Devuelve un dict con el
    resultado: ok / faltaban / arreglado / error.
    """

    actuales = leer_eventos_del_webhook(base_url, token, webhook_id)

    if actuales is None:

        return {"etiqueta": etiqueta, "estado": "ilegible", "faltaban": []}


    # Un webhook suscrito a "*" recibe todo: no hay nada que añadir.
    if "*" in actuales:

        return {"etiqueta": etiqueta, "estado": "ok", "faltaban": []}


    faltan = [e for e in REQUIRED_EVENTS if e not in actuales]

    if not faltan:

        return {"etiqueta": etiqueta, "estado": "ok", "faltaban": []}


    if not AUTOFIX_ENABLED:

        return {"etiqueta": etiqueta, "estado": "faltan_sin_arreglar",
                "faltaban": faltan}


    # La unión conserva lo ajeno: nunca se des-suscribe nada.
    finales = list(dict.fromkeys(list(actuales) + faltan))

    if suscribir_eventos(base_url, token, webhook_id, finales):

        return {"etiqueta": etiqueta, "estado": "arreglado", "faltaban": faltan}


    return {"etiqueta": etiqueta, "estado": "fallo_arreglando", "faltaban": faltan}


def notificar_resultado(resultado, owner_user_id=None, token_bot=None):

    estado = resultado["estado"]

    if estado == "ok":
        return


    if estado == "arreglado":

        texto = (
            "✅ Webhook de PayPal: faltaban eventos y el bot los ha activado "
            f"solo: {', '.join(resultado['faltaban'])}. Sin ellos, las "
            "renovaciones o bajas se perderían en silencio."
        )

    elif estado == "ilegible":

        texto = (
            "⚠️ Webhook de PayPal: no se ha podido leer la configuración. "
            "Revisa que el webhook_id y las credenciales sigan siendo válidos."
        )

    else:

        texto = (
            "⚠️ Webhook de PayPal: faltan eventos y no se han podido activar "
            f"automáticamente: {', '.join(resultado['faltaban'])}. Actívalos "
            "en el panel de PayPal (Apps & Credentials → Webhooks) o las "
            "renovaciones y bajas se perderán en silencio."
        )


    log_event(
        "paypal_webhook_config_check",
        category="payment",
        severity="info" if estado == "arreglado" else "warning",
        scope="global",
        message=f"Webhook PayPal ({resultado['etiqueta']}): {estado}.",
        metadata=resultado,
    )


    if owner_user_id and token_bot:

        try:

            from notification_service import send_telegram_message

            send_telegram_message(token_bot, owner_user_id, texto)

        except Exception as e:

            print("Webhook de PayPal: no se pudo avisar al propietario:",
                  str(e)[:200])


def verify_paypal_webhook_events(notify=True, token_bot=None):
    """
    La pasada completa: el webhook de la plataforma (si está configurado por
    entorno) y el de cada comunidad con PayPal activo. Cada uno con SUS
    credenciales y en SU modo (sandbox/live).
    """

    resultados = []

    # Plataforma: por variables de entorno, como la verificación de firmas.
    webhook_plataforma = os.environ.get("PAYPAL_WEBHOOK_ID")

    if webhook_plataforma:

        try:

            token = pp.get_paypal_access_token()

            resultado = revisar_webhook(
                pp.get_paypal_base_url(),
                token,
                webhook_plataforma,
                "plataforma",
            )

            resultados.append(resultado)

            if notify:
                notificar_resultado(resultado, token_bot=token_bot)

        except Exception as e:

            print("Webhook de PayPal (plataforma): error:",
                  f"{type(e).__name__}: {str(e)[:200]}")


    for group_id in fetch_paypal_configured_group_ids():

        try:

            credentials = pp.get_group_paypal_credentials(group_id)

            resultado = revisar_webhook(
                pp.get_paypal_base_url_for_mode(credentials.get("mode")),
                pp.get_paypal_access_token_for_credentials(
                    credentials.get("client_id"),
                    credentials.get("client_secret"),
                    credentials.get("mode"),
                ),
                credentials.get("webhook_id"),
                f"grupo {group_id}",
            )

            resultados.append(resultado)

            if notify:
                notificar_resultado(
                    resultado,
                    owner_user_id=credentials.get("owner_user_id"),
                    token_bot=token_bot,
                )

        except Exception as e:

            # Una comunidad con la configuración rota no puede parar la
            # revisión de las demás.
            print(f"Webhook de PayPal (grupo {group_id}): error:",
                  f"{type(e).__name__}: {str(e)[:200]}")


    arreglados = [r for r in resultados if r["estado"] == "arreglado"]
    problemas = [r for r in resultados if r["estado"] not in ("ok", "arreglado")]

    if not resultados:

        print("Webhook de PayPal: nada que comprobar (sin webhooks configurados).")

    elif not arreglados and not problemas:

        print("Webhook de PayPal: todos los eventos necesarios están suscritos.")

    else:

        print(
            "Webhook de PayPal:",
            f"{len(arreglados)} arreglados,",
            f"{len(problemas)} con problemas,",
            f"{len(resultados)} revisados",
        )


    return resultados
