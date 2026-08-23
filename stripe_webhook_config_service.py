"""
Comprobar —y arreglar— qué eventos le manda Stripe al bot.

Un webhook solo recibe los eventos que están marcados en su endpoint. El código
puede manejar charge.refunded perfectamente y no enterarse nunca de una
devolución porque ese evento no está activado en el panel de Stripe. No hay
error, no hay traza, no hay nada: simplemente no llega.

Eso convierte una función entera en código muerto sin que nada lo delate, y es
justo lo que pasaba con las devoluciones y las disputas. Por eso esto no se
queda en avisar: si falta algún evento, lo añade.

Dos límites deliberados:

  - solo toca el endpoint cuya URL es la de este bot. Una cuenta de Stripe puede
    tener endpoints de otros servicios y no son asunto suyo;
  - solo añade. Los eventos que ya estuvieran activados se conservan siempre,
    porque puede haberlos puesto alguien a mano para otra cosa.
"""

import os

import stripe

from audit_log_service import log_event
from bot_config import ADMIN_ID
from notification_service import notify_super_admins


# Los eventos que stripe_handler.py sabe atender. Si se añade uno allí y no
# aquí, Stripe no lo mandará nunca: hay una prueba que compara las dos listas
# justamente para que no se separen.
REQUIRED_EVENTS = (
    "checkout.session.completed",
    # Los métodos que NO confirman en el acto (Bancontact, iDEAL y compañía)
    # terminan la sesión sin pagar y avisan después, en estos dos eventos. Sin
    # el primero, quien paga con uno de ellos no entra nunca; sin el segundo, se
    # queda esperando un acceso que no va a llegar y sin saber por qué.
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
    "charge.refunded",
    "charge.refund.updated",
    "charge.dispute.created",
    "charge.dispute.closed",
)


# La ruta donde main.py publica el webhook de Stripe.
WEBHOOK_PATH = "/webhook"


def campo(endpoint, nombre, defecto=None):
    """
    Lee un campo del endpoint, venga como objeto de Stripe o como diccionario.

    Hace falta porque en el SDK de Stripe los recursos NO son diccionarios: no
    tienen .get(), y pedírselo lanza AttributeError con el nombre del atributo
    como único texto. Eso es exactamente lo que pasó en producción: el log decía
    "error comprobando la configuración: get" y nada más.
    """

    valor = getattr(endpoint, nombre, None)

    if valor is not None:

        return valor


    # Un diccionario (las pruebas y cualquier respuesta ya normalizada).
    if isinstance(endpoint, dict):

        return endpoint.get(nombre, defecto)


    return defecto


def autofix_enabled():
    """
    Arreglarlo solo está activado por omisión a propósito.

    Un aviso que nadie lee deja el agujero abierto igual, y añadir un evento al
    endpoint del propio bot no es una decisión de negocio. Se puede desactivar
    poniendo STRIPE_WEBHOOK_AUTOFIX a 0.
    """

    return str(os.environ.get("STRIPE_WEBHOOK_AUTOFIX", "1")).strip().lower() not in (
        "0", "false", "no", "off"
    )


def expected_webhook_url():
    """La URL que debería tener el endpoint de este bot, o None si no se sabe."""

    server_url = (os.environ.get("SERVER_URL") or "").strip().rstrip("/")

    if not server_url:

        return None


    return f"{server_url}{WEBHOOK_PATH}"


def fetch_webhook_endpoints():
    """Endpoints configurados en la cuenta, o None si no se pudo preguntar."""

    try:

        return list(stripe.WebhookEndpoint.list(limit=100).auto_paging_iter())

    except Exception as e:

        print("Webhook de Stripe: no se pudo listar la configuración:", e)

        return None


def find_our_endpoint(endpoints, expected_url):
    """
    Busca el endpoint de este bot.

    Primero por URL exacta. Si no aparece —el dominio puede haber cambiado— se
    acepta un único endpoint que acabe en la misma ruta, porque equivocarse de
    endpoint sería peor que no arreglar nada.
    """

    if not endpoints:

        return None


    if expected_url:

        for endpoint in endpoints:

            if str(campo(endpoint, "url") or "").rstrip("/") == expected_url:

                return endpoint


    candidatos = [
        endpoint for endpoint in endpoints
        if str(campo(endpoint, "url") or "").rstrip("/").endswith(WEBHOOK_PATH)
        and campo(endpoint, "status") != "disabled"
    ]

    if len(candidatos) == 1:

        return candidatos[0]


    return None


def missing_events(endpoint):
    """Eventos que el bot necesita y el endpoint no está mandando."""

    if not endpoint:

        return list(REQUIRED_EVENTS)


    activados = list(campo(endpoint, "enabled_events") or [])

    # "*" significa todos: no falta nada.
    if "*" in activados:

        return []


    return [evento for evento in REQUIRED_EVENTS if evento not in activados]


def enable_missing_events(endpoint, faltan):
    """
    Añade los eventos que faltan, conservando los que ya hubiera.

    Devuelve la lista final, o None si no se pudo.
    """

    activados = list(campo(endpoint, "enabled_events") or [])

    # Se conserva el orden original y se añade al final: así el diff en el panel
    # de Stripe se lee de un vistazo.
    final = activados + [e for e in faltan if e not in activados]

    try:

        stripe.WebhookEndpoint.modify(
            campo(endpoint, "id"),
            enabled_events=final
        )

        return final

    except Exception as e:

        print("Webhook de Stripe: no se pudieron añadir los eventos:", e)

        return None


# =========================
# EL AVISO
# =========================

def build_missing_events_notice(url, faltan, arreglado):

    cabecera = (
        "✅ Webhook de Stripe corregido"
        if arreglado
        else "⚠️ Al webhook de Stripe le faltan eventos"
    )

    lineas = [
        cabecera,
        "",
        f"Endpoint: {url or 'no encontrado'}",
        "",
        "Eventos que el bot atiende y no estaban activados:"
    ]

    lineas.extend(f"  • {evento}" for evento in faltan)

    lineas.append("")


    if arreglado:

        lineas.append(
            "Ya están activados. Las devoluciones, las disputas y las "
            "suscripciones que dependían de ellos vuelven a funcionar."
        )

    else:

        lineas.append(
            "Mientras no estén activados, esos eventos no llegan nunca y el "
            "código que los atiende no se ejecuta: una devolución no retiraría "
            "el acceso. Actívalos en el panel de Stripe → Developers → Webhooks."
        )


    return "\n".join(lineas)


def build_no_endpoint_notice(expected_url):

    return (
        "⚠️ No se encuentra el webhook de Stripe\n\n"
        f"Se esperaba: {expected_url or '(SERVER_URL no está definida)'}\n\n"
        "Sin endpoint, Stripe no avisa de nada: ni de un pago completado, ni de "
        "una devolución. Revisa el panel de Stripe → Developers → Webhooks."
    )


# =========================
# LA COMPROBACIÓN
# =========================

def verify_stripe_webhook_events(notify=True, token=None):
    """
    Comprueba la configuración del webhook y la arregla si falta algo.

    No lanza nunca: esto corre al arrancar y un fallo aquí no puede tumbar el
    bot. Devuelve un resumen de lo ocurrido.
    """

    summary = {
        "checked": False,
        "endpoint_found": False,
        "missing": [],
        "fixed": False,
        "notified": False
    }


    if not stripe.api_key:

        print("Webhook de Stripe: sin clave configurada, no se comprueba.")

        return summary


    endpoints = fetch_webhook_endpoints()

    if endpoints is None:

        return summary


    summary["checked"] = True

    expected_url = expected_webhook_url()
    endpoint = find_our_endpoint(endpoints, expected_url)


    if not endpoint:

        log_event(
            "stripe_webhook_endpoint_missing",
            category="payment",
            severity="critical",
            message="No se encuentra el endpoint del webhook de Stripe.",
            metadata={"expected_url": str(expected_url or "")[:200]}
        )

        if notify and token:

            enviados = notify_super_admins(
                token,
                build_no_endpoint_notice(expected_url),
                fallback_admin_id=ADMIN_ID
            )

            summary["notified"] = bool(enviados)


        return summary


    summary["endpoint_found"] = True

    faltan = missing_events(endpoint)
    summary["missing"] = faltan


    if not faltan:

        print("Webhook de Stripe: todos los eventos necesarios están activados.")

        return summary


    url = campo(endpoint, "url")

    print(
        "Webhook de Stripe: faltan eventos:",
        ", ".join(faltan)
    )


    if autofix_enabled():

        summary["fixed"] = enable_missing_events(endpoint, faltan) is not None


    log_event(
        "stripe_webhook_events_missing",
        category="payment",
        severity="critical",
        message=(
            "Se añadieron eventos que faltaban en el webhook de Stripe."
            if summary["fixed"]
            else "Al webhook de Stripe le faltan eventos que el bot atiende."
        ),
        metadata={
            "url": str(url or "")[:200],
            "missing": faltan,
            "fixed": summary["fixed"],
            "autofix_enabled": autofix_enabled()
        }
    )


    if notify and token:

        enviados = notify_super_admins(
            token,
            build_missing_events_notice(url, faltan, summary["fixed"]),
            fallback_admin_id=ADMIN_ID
        )

        summary["notified"] = bool(enviados)


    return summary
