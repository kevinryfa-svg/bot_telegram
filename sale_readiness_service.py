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


def _fallo_de_otro_proveedor(oferta, proveedor):
    """Una oferta que cobra por PayPal (o similar): ¿puede cobrar de verdad?

    El diagnóstico solo sabía de Stripe, y eso deja un agujero del tamaño de una
    comunidad entera: la que se anuncia con su precio y cobra por un método
    apagado o mal configurado se ve, desde fuera, exactamente igual que una que
    vende bien.
    """

    from payment_gateway_config import is_payment_provider_enabled

    nombre = oferta.get("nombre")
    group_id = oferta.get("group_id")

    try:

        habilitado = is_payment_provider_enabled(proveedor)

    except Exception:

        habilitado = False

    if not habilitado:

        return {
            "group_id": group_id,
            "nombre": nombre,
            "price_id": oferta.get("price_id"),
            "detalle": (
                f"se ofrece y cobra por {proveedor}, que está DESHABILITADO: "
                "quien pulse comprar no puede pagar"
            ),
        }

    if proveedor == "paypal":

        # Las credenciales del grupo se comprueban de verdad: es donde estaba el
        # webhook_id con forma de client_id, que hacía que PayPal cobrara y el
        # bot no pudiera confirmar el pago.
        try:

            from payment_providers.paypal_provider import (
                get_group_paypal_credentials,
            )

            get_group_paypal_credentials(group_id)

        except Exception as e:

            return {
                "group_id": group_id,
                "nombre": nombre,
                "price_id": oferta.get("price_id"),
                "detalle": (
                    f"se ofrece y cobra por PayPal, pero su configuración no "
                    f"sirve: {str(e)[:160]}"
                ),
            }

    return None


def _descuadre_de_importe(oferta, precio_stripe):
    """El plan anuncia un importe y Stripe cobraría otro. None si cuadran.

    Se compara en la unidad de Stripe (céntimos para el euro) porque es la única
    que no admite interpretación: plans.amount va en unidades MAYORES y el
    unit_amount de Stripe en MENORES, y confundirlas es cómo se acaba cobrando
    cien veces de más.
    """

    from payment_gateway_config import amount_to_minor_units

    anunciado = (oferta or {}).get("amount")

    if anunciado is None:
        return None

    try:

        esperado = amount_to_minor_units(anunciado, oferta.get("currency") or "EUR")

    except Exception:

        return None

    cobrado = None

    try:

        cobrado = (
            precio_stripe.get("unit_amount")
            if hasattr(precio_stripe, "get")
            else None
        )

    except Exception:

        cobrado = None

    if cobrado is None or int(cobrado) == int(esperado):
        return None

    moneda = (oferta.get("currency") or "EUR").upper()

    return {
        "group_id": oferta.get("group_id"),
        "nombre": oferta.get("nombre"),
        "price_id": oferta.get("price_id"),
        "detalle": (
            f"se anuncia {int(esperado) / 100:.2f} {moneda} y Stripe cobraría "
            f"{int(cobrado) / 100:.2f} {moneda}"
        ),
        "descuadre": True,
    }


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

        if proveedor != "stripe":

            # Se ofrece y cobra por otro método: hay que comprobar ESE, no
            # callarse. Una comunidad puede estar en el escaparate con su precio
            # y su botón, y tener el cobro apagado o mal configurado.
            fallo = _fallo_de_otro_proveedor(oferta, proveedor)

            if fallo:
                rotos.append(fallo)

            continue

        if not price_id:

            rotos.append({
                "group_id": oferta.get("group_id"),
                "nombre": oferta.get("nombre"),
                "price_id": None,
                "detalle": (
                    "está a la venta por Stripe y no tiene identificador de "
                    "precio: el cobro no se puede ni empezar"
                ),
            })

            continue

        comprobados += 1

        try:

            precio = stripe.Price.retrieve(price_id)

            # Y que diga lo MISMO que se anuncia. El asistente del panel deja
            # cambiar el importe del plan y pide el identificador de Stripe a
            # mano: si alguien cambia uno y no el otro, el bot enseña un precio
            # y cobra otro, y no se entera nadie hasta que se mira un extracto.
            descuadre = _descuadre_de_importe(oferta, precio)

            if descuadre:
                rotos.append(descuadre)

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

        if roto.get("descuadre"):

            problemas.append(
                f"«{roto['nombre']}» anuncia un precio y Stripe cobraría otro: "
                f"{roto['detalle']}. Cobrar algo distinto de lo anunciado es "
                "una devolución garantizada."
            )

        else:

            problemas.append(
                f"El precio de «{roto['nombre']}» ({roto['price_id']}) no existe "
                "en esta cuenta de Stripe: quien pulse comprar no llegará a pagar."
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
