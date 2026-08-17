"""
PEDIR una devolución desde el bot, cuando no hay otra salida.

Ojo con el reparto de papeles, porque son dos módulos distintos:

  refund_service          la devolución que YA ocurrió. Es el webhook
                          (charge.refunded / disputa): marca el pago,
                          retira el acceso, revoca enlaces, expulsa y avisa.

  este módulo             PEDIRLE a Stripe que devuelva. Nada más. Lo que
                          pasa después lo hace el webhook, que ya sabe
                          hacerlo bien y es idempotente.

El aviso de "ha pagado alguien con el acceso vetado" acaba diciendo:

    "Se le ha cobrado y no se le puede dar acceso porque está vetado. Hay que
     devolverle el pago, o levantarle el veto si el baneo ya no corresponde."

Y ahí se acababa: devolver el pago significaba entrar al panel de Stripe,
buscar el cobro entre todos y hacerlo a mano — con el cliente esperando y con
la posibilidad de devolver el equivocado. Aquí está el botón.

Las reglas, que son las que hacen que un botón de devolver dinero no dé
miedo:

  UNA PERSONA DECIDE   Nunca automático. Lo pulsa el propietario de esa
                       comunidad o la plataforma, con una pantalla de
                       confirmación que dice el importe exacto y a quién.

  EL ÚLTIMO COBRADO    Se devuelve el último pago COBRADO de esa persona en
                       esa comunidad, que es el que acaba de entrar. Nada de
                       adivinar entre varios.

  UNA VEZ              La petición se registra ANTES de llamar a Stripe, con
                       clave única por pago: dos personas pulsando a la vez
                       no pueden devolver dos veces. Si Stripe falla, la
                       marca se borra para poder reintentar.

  NO SE TOCA EL PAGO   Este módulo NO marca el pago como devuelto ni retira
                       el acceso, aunque sería fácil: eso lo hace el webhook
                       al llegar la devolución. Si se adelantara aquí, el
                       webhook vería el pago ya marcado, se lo saltaría por
                       idempotencia, y nadie retiraría el acceso ni avisaría
                       al comprador.

  SOLO STRIPE          Es el único proveedor cuya devolución se puede pedir
                       por API con lo que guardamos. En los demás se dice
                       claramente que hay que hacerlo en su panel, en vez de
                       fingir que se hizo.
"""

import stripe

from audit_log_service import log_event
from bot_config import TOKEN
from db import conn


def fetch_last_paid_payment(user_id, group_id):
    """(id, stripe_payment_id, amount, currency, plan) del último cobrado."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, stripe_payment_id, amount, currency, plan
                FROM payments
                WHERE user_id = %s
                  AND group_id = %s
                  AND LOWER(COALESCE(status, '')) IN ('paid', 'completed')
                ORDER BY payment_date DESC NULLS LAST, id DESC
                LIMIT 1

            """, (user_id, group_id))

            return cur.fetchone()

    except Exception as e:

        print("Devolución: error buscando el pago:", e)

        return None


def resolve_refund_target(payment_reference):
    """Qué hay que pasarle a Stripe para devolver ese pago.

    Devuelve ({"payment_intent": ...} | {"charge": ...}) o None si con lo
    que guardamos no se puede pedir la devolución por API. Los formatos que
    llegan aquí son los que escribe el camino de cobro: "stripe:pi_...",
    "stripe:cs_...", o el id de factura de una renovación ("in_...").
    """

    if not payment_reference:
        return None

    referencia = str(payment_reference).strip()

    # El camino de cobro guarda "proveedor:id". Las renovaciones guardan el
    # id de la factura a secas.
    if ":" in referencia:

        proveedor, _, resto = referencia.partition(":")

        if proveedor.strip().lower() not in ("stripe", ""):
            return None

        referencia = resto.strip()


    if referencia.startswith("pi_"):
        return {"payment_intent": referencia}

    if referencia.startswith("ch_"):
        return {"charge": referencia}

    if referencia.startswith("in_"):

        # La factura no se puede devolver: hay que sacarle el cobro.
        try:

            from group_subscription_service import recurso_plano

            factura = recurso_plano(stripe.Invoice.retrieve(referencia)) or {}
            intento = factura.get("payment_intent")
            cobro = factura.get("charge")

            if isinstance(intento, str) and intento:
                return {"payment_intent": intento}

            if isinstance(cobro, str) and cobro:
                return {"charge": cobro}

        except Exception as e:

            print("Devolución: no se pudo leer la factura:", str(e)[:200])

        return None


    if referencia.startswith("cs_"):

        try:

            from group_subscription_service import recurso_plano

            sesion = recurso_plano(
                stripe.checkout.Session.retrieve(referencia)
            ) or {}
            intento = sesion.get("payment_intent")

            if isinstance(intento, str) and intento:
                return {"payment_intent": intento}

        except Exception as e:

            print("Devolución: no se pudo leer la sesión:", str(e)[:200])

        return None


    return None


def mark_refund_requested(payment_id, actor_user_id):
    """Registra la petición. True si esta llamada fue la primera.

    Es la puerta de idempotencia: dos personas pulsando el mismo botón a la
    vez solo pueden pedir la devolución una vez.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO refund_requests (payment_id, actor_user_id)
                VALUES (%s, %s)
                ON CONFLICT (payment_id) DO NOTHING

            """, (payment_id, actor_user_id))

            hecho = cur.rowcount > 0
            conn.commit()

            return hecho

    except Exception as e:

        conn.rollback()

        print("Devolución: error registrando la petición:", e)

        # Sin poder registrar no se pide: preferible no devolver que devolver
        # dos veces el mismo cobro.
        return False


def clear_refund_request(payment_id):
    """Borra la marca cuando Stripe rechaza, para poder reintentar."""

    try:

        with conn.cursor() as cur:

            cur.execute(
                "DELETE FROM refund_requests WHERE payment_id=%s",
                (payment_id,)
            )
            conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print("Devolución: error borrando la petición:", e)

        return False


def describe_refundable(user_id, group_id):
    """Lo que hay que enseñarle a quien va a pulsar. None si no hay nada.

    {"payment_id", "importe", "plan", "puede_api"} — puede_api False cuando
    la devolución hay que hacerla en el panel del proveedor.
    """

    fila = fetch_last_paid_payment(user_id, group_id)

    if not fila:
        return None

    payment_id, referencia, amount, currency, plan = fila

    try:
        importe = f"{int(amount) / 100:.2f} {(currency or 'EUR').upper()}"
    except Exception:
        importe = "importe desconocido"

    return {
        "payment_id": payment_id,
        "referencia": referencia,
        "importe": importe,
        "plan": plan or "—",
        "puede_api": resolve_refund_target(referencia) is not None,
    }


def refund_last_payment(user_id, group_id, actor_user_id):
    """Devuelve el último pago cobrado. Devuelve el resultado, sin lanzar.

    {"ok", "reason", "importe", "payment_id"}. Los motivos posibles:
    'no_payment' (no hay nada cobrado), 'unsupported' (con lo que guardamos
    no se puede pedir por API), 'already' (otro toque llegó antes),
    'stripe_error'.
    """

    resultado = {"ok": False, "reason": None, "importe": None,
                 "payment_id": None}

    fila = fetch_last_paid_payment(user_id, group_id)

    if not fila:

        resultado["reason"] = "no_payment"
        return resultado

    payment_id, referencia, amount, currency, _plan = fila
    resultado["payment_id"] = payment_id

    try:
        resultado["importe"] = f"{int(amount) / 100:.2f} {(currency or 'EUR').upper()}"
    except Exception:
        pass


    destino = resolve_refund_target(referencia)

    if not destino:

        resultado["reason"] = "unsupported"
        return resultado


    # Marcar ANTES de llamar a Stripe: si dos personas pulsan a la vez, solo
    # una pasa por aquí. Lo que NO se toca es el pago: marcarlo como devuelto
    # aquí haría que el webhook se lo saltara por idempotencia y nadie
    # retiraría el acceso ni avisaría al comprador.
    if not mark_refund_requested(payment_id, actor_user_id):

        resultado["reason"] = "already"
        return resultado


    try:

        stripe.Refund.create(**destino)

    except Exception as e:

        clear_refund_request(payment_id)

        log_event(
            "payment_refund_failed",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            message="La devolución del pago falló en Stripe.",
            metadata={"error": str(e)[:200], "payment_id": payment_id}
        )

        resultado["reason"] = "stripe_error"

        return resultado


    log_event(
        "payment_refunded",
        category="payment",
        severity="warning",
        scope="group",
        group_id=group_id,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        message="Devolución pedida a Stripe desde el bot.",
        metadata={
            "payment_id": payment_id,
            "importe": resultado["importe"],
            "destino": list(destino.keys())[0],
        }
    )

    resultado["ok"] = True

    return resultado
