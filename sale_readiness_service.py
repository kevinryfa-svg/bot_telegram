"""
¿Puede este bot cobrar AHORA MISMO? La pregunta que nadie hacía.

El escaparate puede estar perfecto —precio en el botón, un toque hasta pagar— y
no vender nada porque el último paso está roto. Y ese último paso tiene dos
puntos de fallo que no dan ninguna señal hasta que alguien lo intenta:

  EL SERVIDOR DE COBRO   El bot NO habla con Stripe directamente para crear el
                         enlace de pago: hace una petición HTTP a su propio
                         servidor web (SERVER_URL/create-checkout-session). Si
                         SERVER_URL está vacía, apunta a un dominio viejo o el
                         servidor no contesta, TODAS las compras mueren con
                         «No he podido abrir la pasarela de pago». Y ojo: la
                         línea de arranque que enseña el dominio sale de
                         RAILWAY_PUBLIC_DOMAIN, no de SERVER_URL, así que ver
                         una dirección correcta en el log NO prueba que la de
                         cobrar lo sea.

  EL PRECIO DE STRIPE    Cada plan guarda un price_id. Si ese precio se borró,
                         se creó en la otra cuenta (test vs live) o nunca
                         existió, el checkout falla al final del embudo, con el
                         comprador ya decidido.

Los dos fallan en silencio y los dos se parecen desde fuera a «la gente no
compra». Esto los pregunta en cada arranque y lo dice en una línea.

LA SONDA NO ENSUCIA NADA

Al servidor se le pide un plan que no puede existir y se espera su 400 «Plan
inválido». Eso demuestra DNS, TLS, enrutado, aplicación viva y base de datos
respondiendo, sin crear ni una sesión de pago de mentira en Stripe.
"""

import os

import requests

from audit_log_service import log_event


CHECKOUT_PROBE_TIMEOUT = float(
    os.environ.get("CHECKOUT_PROBE_TIMEOUT", "10")
)

# Un identificador de plan que no puede existir: se usa solo para que el
# servidor conteste «Plan inválido» y demuestre que está vivo.
PROBE_PLAN = "__sonda_de_arranque_no_existe__"


def checkout_base_url():
    """La dirección que se usa para cobrar. Vacía si no está configurada."""

    return (os.environ.get("SERVER_URL") or "").strip()


def check_checkout_endpoint():
    """(ok, detalle). ¿Se puede llegar al servidor que crea los cobros?"""

    base = checkout_base_url()

    if not base:

        return (
            False,
            "SERVER_URL no está configurada: el bot no sabe a qué dirección "
            "pedir el enlace de pago, así que ninguna compra puede terminar."
        )

    url = f"{base.rstrip('/')}/create-checkout-session"

    try:

        respuesta = requests.post(
            url,
            json={
                "telegram_id": 0,
                "plan": PROBE_PLAN,
                "group_id": 0,
            },
            timeout=CHECKOUT_PROBE_TIMEOUT,
        )

    except Exception as e:

        return (
            False,
            f"no se pudo llegar a {url} ({type(e).__name__}). Con esto, toda "
            "compra contesta «No he podido abrir la pasarela de pago»."
        )

    # 400 es la respuesta ESPERADA: el plan de la sonda no existe. Significa que
    # el servidor está vivo, enrutado y hablando con su base de datos.
    if respuesta.status_code == 400:
        return (True, f"{url} responde correctamente.")

    if respuesta.status_code == 503:

        return (
            False,
            "el servidor contesta pero Stripe está deshabilitado "
            "(ENABLE_STRIPE_PAYMENTS): no se puede cobrar con tarjeta."
        )

    if respuesta.status_code == 404:

        return (
            False,
            f"{url} devuelve 404: esa dirección no es la de este bot. "
            "Revisa SERVER_URL."
        )

    return (
        False,
        f"{url} contesta {respuesta.status_code}, que no es lo esperado. "
        "El cobro puede estar roto."
    )


def check_stripe_prices(ofertas=None):
    """(rotos, comprobados). Precios que Stripe dice que NO existen.

    Solo cuenta como roto lo que Stripe niega explícitamente. Un error de red no
    convierte un precio bueno en malo: eso apagaría la tienda entera por un
    problema pasajero, que es peor que el fallo que se busca.
    """

    import stripe

    if ofertas is None:

        from start_offer_service import fetch_sellable_communities

        ofertas = fetch_sellable_communities(0, limit=100)

    rotos = []
    comprobados = 0

    for oferta in ofertas:

        proveedor = (oferta.get("provider") or "stripe").strip().lower()
        price_id = oferta.get("price_id")

        if proveedor != "stripe" or not price_id:
            continue

        comprobados += 1

        try:

            stripe.Price.retrieve(price_id)

        except Exception as e:

            texto = str(e)

            # «No such price» es la negativa explícita de Stripe. Lo demás
            # (timeouts, 500, problemas de clave) no se interpreta como precio
            # inexistente.
            if "No such price" in texto or "resource_missing" in texto:

                rotos.append({
                    "group_id": oferta.get("group_id"),
                    "nombre": oferta.get("nombre"),
                    "price_id": price_id,
                    "detalle": texto[:200],
                })

            else:

                print(
                    "Cobro: no se pudo comprobar el precio", price_id, "-",
                    texto[:160]
                )

    return rotos, comprobados


def describe_sale_readiness(avisar=True):
    """Una línea para el arranque, y aviso al admin si no se puede cobrar."""

    problemas = []

    ok_servidor, detalle_servidor = check_checkout_endpoint()

    if not ok_servidor:
        problemas.append(f"Servidor de cobro: {detalle_servidor}")

    try:

        rotos, comprobados = check_stripe_prices()

    except Exception as e:

        rotos, comprobados = [], 0

        print("Cobro: no se pudieron comprobar los precios:", str(e)[:200])

    for roto in rotos:

        problemas.append(
            f"El precio de «{roto['nombre']}» ({roto['price_id']}) no existe en "
            "esta cuenta de Stripe: quien pulse comprar no llegará a pagar."
        )


    if not problemas:

        return (
            f"Cobro: listo (servidor de pago accesible, {comprobados} "
            "precio(s) de Stripe verificado(s))."
        )


    linea = "🚨 COBRO ROTO — " + " | ".join(problemas)

    log_event(
        "sale_readiness_broken",
        category="payment",
        severity="critical",
        scope="global",
        message="El bot no puede completar un cobro.",
        metadata={
            "checkout_endpoint_ok": ok_servidor,
            "checkout_endpoint_detail": detalle_servidor,
            "broken_prices": rotos,
        },
    )

    if avisar:

        # Esto no espera al lunes: mientras siga roto, cada persona que pulse
        # comprar se va.
        try:

            from bot_config import ADMIN_ID, TOKEN
            from notification_service import send_telegram_message

            if ADMIN_ID and TOKEN:

                send_telegram_message(
                    TOKEN,
                    int(ADMIN_ID),
                    "🚨 El bot no puede cobrar\n\n"
                    + "\n\n".join(problemas)
                    + "\n\nMientras siga así, cada persona que pulse comprar "
                    "se encuentra un error y se va."
                )

        except Exception as e:

            print("Cobro: no se pudo avisar al admin:", str(e)[:200])


    return linea
