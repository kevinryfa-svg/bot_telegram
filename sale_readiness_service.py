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

        from plan_price_service import parece_precio_de_stripe

        if not parece_precio_de_stripe(price_id):

            # Ni se pregunta a Stripe: esto no puede ser un precio. En
            # producción, dentro de este campo había una respuesta de soporte
            # entera. Decirlo con sus propias palabras evita que el aviso
            # mande a buscar un precio borrado que nunca existió.
            rotos.append({
                "group_id": oferta.get("group_id"),
                "nombre": oferta.get("nombre"),
                "price_id": price_id,
                "detalle": (
                    "lo que tiene guardado como precio de Stripe no puede "
                    f"serlo: «{str(price_id)[:60]}». El cobro no se puede "
                    "ni empezar"
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

        elif roto.get("detalle") and not roto["detalle"].startswith("No such price"):

            # El fallo trae su propia explicación (proveedor apagado,
            # credenciales que no sirven, sin identificador de precio): contarlo
            # todo como «el precio no existe en Stripe» manda a mirar donde no
            # es, que es lo que me pasó a mí leyendo este log.
            problemas.append(f"«{roto['nombre']}»: {roto['detalle']}")

        else:

            problemas.append(
                f"El precio de «{roto['nombre']}» ({roto['price_id']}) no existe "
                "en esta cuenta de Stripe: quien pulse comprar no llegará a pagar."
            )


    # El nombre de la página de pago NO es un cobro roto: se cobra
    # perfectamente. Es peor de otra manera —se pierde al comprador sin que
    # nada falle— así que se dice aparte y no dispara la alarma de avería.
    avisos = []

    try:

        ok_nombre, detalle_nombre = check_nombre_de_la_pagina_de_pago()

        if not ok_nombre:
            avisos.append(f"Nombre en la página de pago: {detalle_nombre}")

    except Exception as e:

        print("Cobro: no se pudo comprobar el nombre de pago:", str(e)[:200])


    if not problemas:

        linea_ok = (
            f"Cobro: listo (servidor de pago accesible, {comprobados} "
            "precio(s) de Stripe verificado(s))."
        )

        if avisos:
            return linea_ok + " ⚠️ " + " | ".join(avisos)

        return linea_ok


    linea = "🚨 COBRO ROTO — " + " | ".join(problemas + avisos)

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


# =========================
# VIGILARLO, NO SOLO MIRARLO AL ARRANCAR
# =========================
# Esta comprobación solo corría al arrancar. Con despliegues de vez en cuando,
# eso significa enterarse de que el cobro está roto días después — y así es
# exactamente como este bot estuvo meses sin poder cobrar: nadie lo miró.
#
# Ahora se mira cada hora. Y se avisa por CAMBIO DE ESTADO, no cada vez: un
# aviso cada hora se convierte en ruido que se ignora, que es justo lo que hace
# que el aviso importante pase desapercibido.

_ultimo_estado_del_cobro = {"roto": None}


def vigilar_cobro(avisar=True):
    """(roto, linea). Comprueba el cobro y avisa SOLO cuando el estado cambia.

    Devuelve `roto=True/False` y la línea que describe el estado, para que quien
    llame pueda registrarla. Nunca lanza: es un vigilante, y un vigilante que
    tumba el proceso que vigila no sirve de nada.
    """

    try:

        linea = describe_sale_readiness(avisar=False)

    except Exception as e:

        print("Cobro: la vigilancia falló:", str(e)[:200])

        return (None, None)

    roto = linea.startswith("🚨")

    antes = _ultimo_estado_del_cobro.get("roto")

    _ultimo_estado_del_cobro["roto"] = roto

    if antes == roto:

        # Sin cambios: ni ruido ni aviso. El estado ya está donde tiene que
        # estar y quien tenía que enterarse ya se enteró.
        return (roto, linea)

    print(linea)

    if not avisar:
        return (roto, linea)

    try:

        from bot_config import ADMIN_ID, TOKEN
        from notification_service import send_telegram_message

        if not (ADMIN_ID and TOKEN):
            return (roto, linea)

        if roto:

            send_telegram_message(
                TOKEN,
                int(ADMIN_ID),
                "🚨 El bot ha dejado de poder cobrar\n\n"
                + linea.replace("🚨 COBRO ROTO — ", "")
                + "\n\nMientras siga así, cada persona que pulse comprar se "
                "encuentra un error y se va."
            )

        elif antes is not None:

            # Solo cuando venimos de estar rotos: un «ya funciona» sin haber
            # avisado antes de que no funcionaba no le dice nada a nadie.
            send_telegram_message(
                TOKEN,
                int(ADMIN_ID),
                "✅ El cobro vuelve a funcionar\n\n" + linea
            )

    except Exception as e:

        print("Cobro: no se pudo avisar del cambio de estado:", str(e)[:200])

    return (roto, linea)


# =========================
# EL NOMBRE QUE SE LEE CON LA TARJETA EN LA MANO
# =========================
# El cobro puede funcionar perfectamente y aun así no cobrar nada. La página de
# Stripe lleva un nombre de negocio arriba, y en producción ese nombre era
# «TIENDA INFORMATICA»: alguien que iba a pagar por entrar a una comunidad de
# Telegram llegaba a una página que decía el nombre de una tienda de
# ordenadores. Eso no da un error, no sale en ningún log y no lo ve nadie desde
# dentro del bot —solo lo ve el comprador, en el único segundo en el que puede
# arrepentirse—. Se cierra la pestaña y en las métricas queda como «no compró».
#
# El nombre sale de una cadena de reservas de Stripe: primero el nombre público
# de la cuenta, y si está vacío, el concepto que aparece en el extracto del
# banco. Por eso se puede tener el nombre de marca bien puesto en un sitio y la
# página enseñando otro: son campos distintos.

NOMBRE_DE_PAGO_TIMEOUT = float(
    os.environ.get("NOMBRE_DE_PAGO_TIMEOUT", "10")
)

# EL NOMBRE QUE SE QUIERE QUE SALGA. Con esto puesto, se avisa solo cuando la
# página se aparta de ÉL, y no de cómo se llame la cuenta en Stripe.
#
# Porque un nombre distinto no siempre es un descuido: quien vende acceso a una
# comunidad privada puede querer a propósito que en el extracto del banco de su
# comprador salga algo neutro, y esa es una decisión suya, no una avería. Sin
# esta variable, el aviso saltaría cada hora para siempre por algo elegido — y
# un aviso que se sabe que hay que ignorar es el que hace que se ignoren todos.
def nombre_de_pago_esperado():
    """El nombre que se quiere ver, o cadena vacía. Se lee cada vez.

    Al leerlo en cada comprobación, cambiarlo en el servidor surte efecto en la
    siguiente ronda: no hace falta reiniciar el bot para dejar de recibir —o
    volver a recibir— este aviso.
    """

    return (os.environ.get("NOMBRE_DE_PAGO_ESPERADO") or "").strip()


def nombre_que_vera_el_comprador(cuenta):
    """El nombre que Stripe pinta arriba en la página de pago.

    Mismo orden de reservas que usa Stripe: el nombre público de la cuenta y,
    si no lo hay, el concepto del extracto bancario.
    """

    perfil = (cuenta.get("business_profile") or {})
    ajustes = (cuenta.get("settings") or {})
    pagos = (ajustes.get("payments") or {})

    for candidato in (perfil.get("name"), pagos.get("statement_descriptor")):

        if (candidato or "").strip():
            return candidato.strip()

    return None


def nombre_de_marca_de_la_cuenta(cuenta):
    """Cómo se llama a sí misma la cuenta. La referencia para comparar."""

    panel = ((cuenta.get("settings") or {}).get("dashboard") or {})

    return (panel.get("display_name") or "").strip() or None


def _mismo_nombre(uno, otro):
    """«thestarvip.online» y «TheStarVip» son el mismo negocio; la tienda de
    ordenadores no."""

    def limpio(texto):

        return "".join(
            c for c in (texto or "").lower() if c.isalnum()
        )

    a, b = limpio(uno), limpio(otro)

    if not a or not b:
        return False

    return a.startswith(b) or b.startswith(a)


def _leer_cuenta_de_stripe():
    """Los datos de la cuenta, o None. Con plazo, porque esto corre al arrancar.

    Se pregunta a mano en vez de con la librería de Stripe por una razón sola:
    el plazo. La librería espera hasta 80 segundos por defecto, y esto se
    ejecuta en el arranque del bot —80 segundos de bot parado por una
    comprobación cosmética es peor que no hacerla.
    """

    clave = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()

    if not clave:
        return None

    respuesta = requests.get(
        "https://api.stripe.com/v1/account",
        headers={"Authorization": f"Bearer {clave}"},
        timeout=NOMBRE_DE_PAGO_TIMEOUT,
    )

    respuesta.raise_for_status()

    return respuesta.json()


def check_nombre_de_la_pagina_de_pago():
    """(ok, detalle). ¿La página de pago dice el nombre del negocio?

    Un fallo de red no es un nombre mal puesto: si no se puede preguntar, se
    calla. Este aviso solo tiene sentido si se está seguro.
    """

    try:

        cuenta = _leer_cuenta_de_stripe()

    except Exception as e:

        return (True, f"no se pudo preguntar a Stripe: {str(e)[:120]}")

    if not cuenta:
        return (True, "sin credenciales de Stripe: no se comprueba")

    visible = nombre_que_vera_el_comprador(cuenta)

    # Con un nombre esperado puesto, ÉL es la referencia: el de la cuenta deja
    # de importar, porque la decisión ya está tomada.
    esperado = nombre_de_pago_esperado()

    marca = esperado or nombre_de_marca_de_la_cuenta(cuenta)

    if not visible:

        return (True, "Stripe no enseña ningún nombre de negocio")

    if not marca or _mismo_nombre(visible, marca):

        return (True, f"la página de pago dice «{visible}»")

    if esperado:

        return (False, (
            f"la página de pago dice «{visible}» y se esperaba «{esperado}». "
            "Alguien lo ha cambiado en Stripe."
        ))

    return (False, (
        f"la página de pago dice «{visible}» y el negocio se llama «{marca}». "
        "Quien va a pagar lee un nombre que no reconoce justo antes de poner "
        "la tarjeta, y se va. Se arregla poniendo el nombre público de la "
        "cuenta en Stripe (Configuración → Empresa → Nombre público) o "
        f"cambiando el concepto del extracto, que ahora es «{visible}»."
    ))
