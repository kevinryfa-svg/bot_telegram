"""
Renovación automática del acceso a comunidades (solo Stripe).

Hasta ahora todos los planes eran de pago único: el acceso caducaba y la
persona tenía que acordarse de volver a pagar. Los avisos de renovación
recuperan a una parte; este módulo elimina el problema para quien lo prefiera:
el plan se cobra solo, cada periodo, hasta que el comprador lo cancele.

Las tres decisiones de producto, tomadas con el estándar del sector:

  REINTENTOS   Los reintentos inteligentes de Stripe. Mientras Stripe reintenta
               (invoice.payment_failed → past_due) el acceso NO se toca: la
               expiración sigue siendo la del periodo ya pagado. Solo se revoca
               cuando Stripe da la suscripción por perdida o el comprador
               cancela (customer.subscription.deleted).

  CANCELAR     cancel_at_period_end. Cancelar nunca revoca en el acto: el
               periodo ya está pagado y el acceso dura hasta su final. Y se
               puede reactivar hasta el último día desde «Mis suscripciones».

  PRECIOS      Quien ya está suscrito conserva su precio aunque el propietario
               suba el del plan: la suscripción de Stripe guarda su propio
               Price y el nuevo solo afecta a altas nuevas. Aquí no hay que
               hacer nada — hay una prueba que fija que editar un plan no toca
               las suscripciones existentes.

El ancla de identificación es users.stripe_subscription_id: se guarda al
completarse el checkout y cada evento de Stripe se atribuye por ella. Un evento
cuya suscripción no está anclada a ningún socio NO es nuestro (será de un extra
del propietario o de otra cosa) y se deja pasar.

Los importes de invoice.amount_paid vienen en céntimos, como todo `payments`.
"""

from datetime import datetime

import stripe

from audit_log_service import log_event
from bot_config import TOKEN
from db import conn
from i18n_service import load_user_language, t
from notification_service import send_telegram_message


# Marca en la metadata de la suscripción para poder distinguirla a simple
# vista en el panel de Stripe. La atribución real es por el ancla en la base.
GROUP_SUBSCRIPTION_PURPOSE = "group_access"


def stripe_recurring_interval(duration_days):
    """
    El intervalo de Stripe que corresponde a la duración de un plan.

    Stripe cobra por intervalos (día/semana/mes/año), no por "N días": un plan
    de 30 días se convierte en mensual y uno de 365 en anual, que es lo que el
    comprador espera ver en su extracto. Duraciones no estándar van como
    intervalos de N días literales.
    """

    dias = int(duration_days)

    if dias in (28, 29, 30, 31):
        return ("month", 1)

    if dias in (90, 91, 92):
        return ("month", 3)

    if dias in (180, 182, 183):
        return ("month", 6)

    if dias in (365, 366):
        return ("year", 1)

    if dias == 7:
        return ("week", 1)

    if dias == 14:
        return ("week", 2)

    return ("day", dias)


def recurso_plano(objeto):
    """
    Un recurso del SDK de Stripe como datos planos (dicts anidados).

    En stripe 15.x los recursos NO son diccionarios: no tienen .get(), y
    pedírselo lanza AttributeError con solo "get" como texto — exactamente el
    fallo que ya tumbó en producción la autoconfiguración del webhook. Todo lo
    que venga del SDK pasa por aquí antes de tocarse.
    """

    if objeto is None or isinstance(objeto, (dict, str, int, float, bool)):
        return objeto

    try:
        return objeto.to_dict()
    except Exception:
        return objeto


def extraer_subscription_id(valor):
    """El id de una suscripción, venga como cadena o como objeto expandido."""

    if isinstance(valor, str):
        return valor

    if isinstance(valor, dict):
        return valor.get("id")

    return getattr(valor, "id", None)


def fetch_member_by_subscription(stripe_subscription_id):
    """El socio (user_id, group_id, expiration) anclado a esta suscripción."""

    if not stripe_subscription_id:
        return None

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id, group_id, expiration
                FROM users
                WHERE stripe_subscription_id=%s
                LIMIT 1

            """, (stripe_subscription_id,))

            row = cur.fetchone()

        if not row:
            return None

        return {"user_id": row[0], "group_id": row[1], "expiration": row[2]}

    except Exception as e:

        print("Renovación: error buscando socio por suscripción:", e)

        return None


def attach_subscription_to_member(user_id, group_id, stripe_subscription_id,
                                  stripe_customer_id=None):
    """
    Ancla la suscripción al socio en cuanto el checkout se completa. Sin este
    ancla, ningún evento posterior (renovación, fallo, baja) sería atribuible.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_subscription_id
                FROM users
                WHERE user_id=%s AND group_id=%s

            """, (user_id, group_id))

            fila = cur.fetchone()
            anterior = fila[0] if fila else None


        # LA SALVAGUARDA DEL DOBLE COBRO: si ya había OTRA suscripción anclada
        # (p. ej. compró el plan anual teniendo el mensual), la vieja se apaga
        # al final de su periodo. Sin esto, las dos cobrarían para siempre y
        # el ancla solo recordaría la nueva.
        if anterior and anterior != stripe_subscription_id:

            try:

                stripe.Subscription.modify(anterior, cancel_at_period_end=True)

                log_event(
                    "group_subscription_replaced",
                    category="payment",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Suscripción anterior apagada al anclar una nueva (cambio de plan).",
                    metadata={"anterior": anterior,
                              "nueva": stripe_subscription_id},
                )

            except Exception as e:

                print("Renovación: no se pudo apagar la suscripción anterior:",
                      str(e)[:200])


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET stripe_subscription_id=%s,
                    stripe_customer_id=COALESCE(%s, stripe_customer_id)
                WHERE user_id=%s AND group_id=%s

            """, (stripe_subscription_id, stripe_customer_id, user_id, group_id))

            conn.commit()

        return True

    except Exception as e:

        print("Renovación: error anclando suscripción:", e)

        return False


def align_expiration_with_trial(user_id, group_id, stripe_subscription_id):
    """
    Si la suscripción arranca EN PRUEBA, el alta del checkout habrá concedido
    la duración entera del plan (30 días) cuando lo cubierto es la prueba
    (p. ej. 7): la expiración se recorta al fin de la prueba. Si el cliente
    paga al acabar, invoice.paid la extiende; si cancela o falla el cobro,
    caduca sola — sin sobre-regalo que reclamar.
    """

    try:

        suscripcion = recurso_plano(
            stripe.Subscription.retrieve(stripe_subscription_id)
        ) or {}

        if suscripcion.get("status") != "trialing":
            return False

        fin = suscripcion.get("trial_end") or suscripcion.get("current_period_end")

        if not fin:
            return False

        fin_prueba = datetime.fromtimestamp(int(fin))

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET expiration = %s
                WHERE user_id = %s AND group_id = %s

            """, (fin_prueba, user_id, group_id))

            conn.commit()

        log_event(
            "group_subscription_trial_started",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Suscripción iniciada en periodo de prueba.",
            metadata={
                "stripe_subscription_id": stripe_subscription_id,
                "trial_end": str(fin_prueba),
            }
        )

        return True

    except Exception as e:

        print("Renovación: error alineando la prueba:", str(e)[:200])

        return False


def fetch_group_name(group_id):
    try:

        with conn.cursor() as cur:

            cur.execute("SELECT name FROM groups WHERE id=%s", (group_id,))
            row = cur.fetchone()

        return (row[0] if row else None) or f"Comunidad {group_id}"

    except Exception:

        return f"Comunidad {group_id}"


def renewal_already_recorded(invoice_id):
    """
    Stripe reenvía los webhooks: la misma factura no puede extender el acceso
    dos veces ni repetir el aviso. El pago registrado es la marca.
    """

    if not invoice_id:
        return False

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1 FROM payments WHERE stripe_payment_id=%s LIMIT 1

            """, (invoice_id,))

            return cur.fetchone() is not None

    except Exception as e:

        print("Renovación: error comprobando idempotencia:", e)

        return False


def invoice_period_end(invoice, stripe_subscription_id):
    """
    Hasta cuándo paga esta factura. La fuente primaria es el periodo de la
    propia línea de factura; si no viene, se le pregunta a la suscripción.
    """

    try:

        lineas = ((invoice.get("lines") or {}).get("data")) or []

        for linea in lineas:

            fin = ((linea.get("period") or {}).get("end"))

            if fin:
                return datetime.fromtimestamp(int(fin))

    except Exception:

        pass


    try:

        suscripcion = recurso_plano(stripe.Subscription.retrieve(stripe_subscription_id))
        fin = (suscripcion or {}).get("current_period_end")

        if fin:
            return datetime.fromtimestamp(int(fin))

    except Exception as e:

        print("Renovación: no se pudo leer el fin de periodo:", e)


    return None


def avisar_comprador(user_id, texto, reply_markup=None):
    try:

        send_telegram_message(TOKEN, user_id, texto, reply_markup=reply_markup)

    except Exception as e:

        print("Renovación: no se pudo avisar al comprador:", str(e)[:200])


# A dónde vuelve el comprador al salir del portal de pago de Stripe: el bot.
BOT_RETURN_URL = "https://t.me/TheStarVipBOT"


def crear_url_portal_pago(stripe_customer_id):
    """
    Una sesión del portal de facturación de Stripe: la página donde el
    comprador cambia su tarjeta sin salir del flujo. Es EL punto donde se
    pierde a un suscriptor que quería quedarse: el aviso de "revisa tu
    tarjeta" sin un sitio donde hacerlo es un callejón.

    Si el portal no está configurado en la cuenta de Stripe (hay que
    activarlo una vez en el panel), devuelve None y el aviso sale sin botón:
    la degradación es el mensaje de siempre, nunca el silencio.
    """

    if not stripe_customer_id:
        return None

    try:

        sesion = recurso_plano(stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=BOT_RETURN_URL,
        ))

        return (sesion or {}).get("url")

    except Exception as e:

        print("Renovación: no se pudo crear el portal de pago:", str(e)[:200])

        return None


def fetch_member_customer_id(user_id, group_id):
    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_customer_id
                FROM users
                WHERE user_id=%s AND group_id=%s

            """, (user_id, group_id))

            row = cur.fetchone()

        return row[0] if row else None

    except Exception:

        return None


def formato_fecha(valor):
    try:
        return valor.strftime("%d/%m/%Y")
    except Exception:
        return "la fecha de fin de tu periodo"


# =========================
# LOS EVENTOS
# =========================

def process_group_subscription_invoice_paid(invoice, event_type):
    """
    Una renovación cobrada: extender el acceso hasta el fin del periodo pagado,
    registrar el pago y decírselo al comprador.

    La PRIMERA factura (billing_reason=subscription_create) no extiende nada:
    el alta la hace checkout.session.completed con su enlace y su mensaje, y
    este evento puede llegar antes o después que aquel.
    """

    stripe_subscription_id = extraer_subscription_id(invoice.get("subscription"))
    socio = fetch_member_by_subscription(stripe_subscription_id)

    if not socio:
        return False


    if (invoice.get("billing_reason") or "") == "subscription_create":
        return True


    invoice_id = invoice.get("id")

    if renewal_already_recorded(invoice_id):
        return True


    fin_periodo = invoice_period_end(invoice, stripe_subscription_id)
    user_id, group_id = socio["user_id"], socio["group_id"]
    group_name = fetch_group_name(group_id)

    amount_paid = invoice.get("amount_paid")
    currency = (invoice.get("currency") or "").upper() or None

    try:

        with conn.cursor() as cur:

            if fin_periodo is not None:

                cur.execute("""

                    UPDATE users
                    SET expiration=%s, subscription_active=TRUE
                    WHERE user_id=%s AND group_id=%s

                """, (fin_periodo, user_id, group_id))

            cur.execute("""

                INSERT INTO payments
                (user_id, group_id, stripe_payment_id, amount, currency, status, plan)
                VALUES (%s, %s, %s, %s, %s, 'paid', %s)

            """, (user_id, group_id, invoice_id, amount_paid, currency,
                  f"Renovación · {group_name}"))

            conn.commit()

    except Exception as e:

        print("Renovación: error guardando la renovación:", e)


    log_event(
        "group_subscription_renewed",
        category="payment",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Renovación automática cobrada y acceso extendido.",
        metadata={
            "stripe_subscription_id": stripe_subscription_id,
            "invoice_id": invoice_id,
            "amount": amount_paid,
            "currency": currency,
            "new_expiration": str(fin_periodo)
        }
    )

    language = load_user_language(user_id)

    # Con el importe delante: un cargo que se reconoce no se disputa.
    if amount_paid:

        try:
            precio = f"{int(amount_paid) / 100:.2f} {(currency or 'EUR').upper()}"
        except Exception:
            precio = None

    else:

        precio = None

    if precio:

        avisar_comprador(user_id, t(
            "renewal.renewed_priced", language,
            group=group_name,
            until=formato_fecha(fin_periodo),
            price=precio
        ))

    else:

        avisar_comprador(user_id, t(
            "renewal.renewed", language,
            group=group_name,
            until=formato_fecha(fin_periodo)
        ))

    return True


def process_group_subscription_invoice_failed(invoice, event_type):
    """
    Un cobro de renovación ha fallado. El acceso NO se toca: el periodo pagado
    sigue corriendo y Stripe reintentará solo. Lo único urgente es que el
    comprador se entere, porque casi siempre es su tarjeta.
    """

    stripe_subscription_id = extraer_subscription_id(invoice.get("subscription"))
    socio = fetch_member_by_subscription(stripe_subscription_id)

    if not socio:
        return False


    user_id, group_id = socio["user_id"], socio["group_id"]
    group_name = fetch_group_name(group_id)

    log_event(
        "group_subscription_payment_failed",
        category="payment",
        severity="warning",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Cobro de renovación fallido; Stripe reintentará.",
        metadata={
            "stripe_subscription_id": stripe_subscription_id,
            "invoice_id": invoice.get("id"),
            "attempt_count": invoice.get("attempt_count")
        }
    )

    language = load_user_language(user_id)

    # El botón que salva la suscripción: cambiar la tarjeta en un toque. La
    # factura trae el customer; si no viniera, está guardado en el socio.
    url_portal = crear_url_portal_pago(
        invoice.get("customer") or fetch_member_customer_id(user_id, group_id)
    )

    teclado = None

    if url_portal:

        teclado = {"inline_keyboard": [[{
            "text": t("renewal.update_card_button", language),
            "url": url_portal
        }]]}

    avisar_comprador(user_id, t(
        "renewal.payment_failed", language,
        group=group_name
    ), reply_markup=teclado)

    return True


def process_group_subscription_updated(subscription, event_type,
                                       previous_attributes=None):
    """
    Solo interesa un cambio: el interruptor de la renovación. Al desactivarla
    (cancel_at_period_end) se le confirma al comprador hasta cuándo tiene
    acceso; al reactivarla, que todo sigue como estaba. El resto de updates
    (cambios de estado internos de Stripe) no necesitan conversación.
    """

    stripe_subscription_id = extraer_subscription_id(subscription.get("id"))
    socio = fetch_member_by_subscription(stripe_subscription_id)

    if not socio:
        return False


    previo = previous_attributes or {}

    if "cancel_at_period_end" not in previo:
        return True


    user_id, group_id = socio["user_id"], socio["group_id"]
    group_name = fetch_group_name(group_id)
    language = load_user_language(user_id)

    if subscription.get("cancel_at_period_end"):

        fin = subscription.get("current_period_end")
        hasta = formato_fecha(datetime.fromtimestamp(int(fin))) if fin \
            else formato_fecha(socio.get("expiration"))

        log_event(
            "group_subscription_autorenew_off",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Renovación automática desactivada por el comprador.",
            metadata={"stripe_subscription_id": stripe_subscription_id}
        )

        avisar_comprador(user_id, t(
            "renewal.cancelled_at_period_end", language,
            group=group_name,
            until=hasta
        ))

    else:

        log_event(
            "group_subscription_autorenew_on",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Renovación automática reactivada por el comprador.",
            metadata={"stripe_subscription_id": stripe_subscription_id}
        )

        avisar_comprador(user_id, t(
            "renewal.reactivated", language,
            group=group_name
        ))

    return True


def process_group_subscription_deleted(subscription, event_type):
    """
    La suscripción ha muerto: o el comprador canceló y el periodo terminó, o
    Stripe agotó los reintentos. Es EL punto de revocación de la renovación
    automática: la expiración se recorta a ahora (si aún estaba en el futuro),
    el ancla se limpia para que el socio pueda volver a suscribirse, y el
    trabajador de expiraciones hace el resto como con cualquier caducidad.
    """

    stripe_subscription_id = extraer_subscription_id(subscription.get("id"))
    socio = fetch_member_by_subscription(stripe_subscription_id)

    if not socio:
        return False


    user_id, group_id = socio["user_id"], socio["group_id"]
    group_name = fetch_group_name(group_id)

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET stripe_subscription_id=NULL,
                    expiration=LEAST(COALESCE(expiration, NOW()), NOW())
                WHERE user_id=%s AND group_id=%s

            """, (user_id, group_id))

            conn.commit()

    except Exception as e:

        print("Renovación: error cerrando la suscripción:", e)


    log_event(
        "group_subscription_ended",
        category="payment",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Suscripción terminada; acceso cerrado al fin del periodo pagado.",
        metadata={"stripe_subscription_id": stripe_subscription_id}
    )

    language = load_user_language(user_id)

    avisar_comprador(user_id, t(
        "renewal.ended", language,
        group=group_name
    ))

    return True


def process_group_subscription_lifecycle_event(event):
    """
    El despacho, llamado desde el webhook DESPUÉS del de extras del
    propietario: cada uno reconoce solo lo suyo por su propia ancla, así que el
    orden entre ellos no importa, pero los dos antes que nada más.

    Devuelve True si el evento era de una suscripción de acceso a comunidad.
    """

    try:

        event_type = event["type"]

        # Conversión defensiva: el webhook ya entrega dicts planos, pero si a
        # este despacho le llegara alguna vez un StripeObject del SDK, sin
        # esto cada .get() reventaría y el evento se perdería en silencio.
        datos = recurso_plano(event["data"])
        objeto = recurso_plano(datos["object"])

        if event_type == "invoice.paid":
            return process_group_subscription_invoice_paid(objeto, event_type)

        if event_type == "invoice.payment_failed":
            return process_group_subscription_invoice_failed(objeto, event_type)

        if event_type == "customer.subscription.updated":
            return process_group_subscription_updated(
                objeto,
                event_type,
                previous_attributes=recurso_plano(
                    datos.get("previous_attributes")
                )
            )

        if event_type == "customer.subscription.deleted":
            return process_group_subscription_deleted(objeto, event_type)

    except Exception as e:

        print(f"Renovación: error procesando {event.get('type')}: {e}")


    return False


# =========================
# EL INTERRUPTOR DEL COMPRADOR
# =========================

def fetch_renewal_state(user_id, group_id):
    """
    Para la pantalla «Mis suscripciones»: si este acceso tiene renovación
    automática y en qué estado está. None si no es una suscripción.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_subscription_id
                FROM users
                WHERE user_id=%s AND group_id=%s
                AND stripe_subscription_id IS NOT NULL

            """, (user_id, group_id))

            row = cur.fetchone()

        if not row:
            return None

        stripe_subscription_id = row[0]

        suscripcion = recurso_plano(
            stripe.Subscription.retrieve(stripe_subscription_id)
        ) or {}

        cancelada = suscripcion.get("cancel_at_period_end")
        fin = suscripcion.get("current_period_end")
        pausa = suscripcion.get("pause_collection") or None
        reanuda = (pausa or {}).get("resumes_at") if isinstance(pausa, dict) else None

        return {
            "stripe_subscription_id": stripe_subscription_id,
            "cancel_at_period_end": bool(cancelada),
            "current_period_end": datetime.fromtimestamp(int(fin)) if fin else None,
            "paused": bool(pausa),
            "resumes_at": datetime.fromtimestamp(int(reanuda)) if reanuda else None,
        }

    except Exception as e:

        print("Renovación: error leyendo el estado de la suscripción:", str(e)[:200])

        return None


def pause_renewal(user_id, group_id, days=30):
    """
    La tercera vía entre pagar y cancelar: pausa de {days} días con vuelta
    automática. behavior="void": las facturas del periodo en pausa se anulan
    (no se cobra nada), y resumes_at reanuda los cobros solo — el que se va
    por saturación o dinero corto no se pierde, se pausa.

    El acceso sigue su curso natural: dura hasta el fin del periodo YA pagado
    y, al reanudarse el cobro, invoice.paid lo extiende como cualquier
    renovación. No se paga → no se accede → se vuelve sin hacer nada.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_subscription_id
                FROM users
                WHERE user_id=%s AND group_id=%s
                AND stripe_subscription_id IS NOT NULL

            """, (user_id, group_id))

            row = cur.fetchone()

        if not row:
            return False

        import time as time_mod

        stripe.Subscription.modify(
            row[0],
            pause_collection={
                "behavior": "void",
                "resumes_at": int(time_mod.time()) + int(days) * 86400,
            },
        )

        log_event(
            "group_subscription_paused",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message=f"Renovación pausada {days} días por el comprador.",
            metadata={"stripe_subscription_id": row[0], "days": days},
        )

        return True

    except Exception as e:

        print("Renovación: error pausando:", str(e)[:200])

        return False


def resume_renewal(user_id, group_id):
    """Deshace la pausa: los cobros vuelven en el siguiente ciclo."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_subscription_id
                FROM users
                WHERE user_id=%s AND group_id=%s
                AND stripe_subscription_id IS NOT NULL

            """, (user_id, group_id))

            row = cur.fetchone()

        if not row:
            return False

        # La cadena vacía es como Stripe borra pause_collection.
        stripe.Subscription.modify(row[0], pause_collection="")

        log_event(
            "group_subscription_resumed",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Renovación reanudada por el comprador.",
            metadata={"stripe_subscription_id": row[0]},
        )

        return True

    except Exception as e:

        print("Renovación: error reanudando:", str(e)[:200])

        return False


def set_renewal_enabled(user_id, group_id, enabled):
    """
    El interruptor. Desactivar = cancel_at_period_end (el acceso dura hasta el
    final del periodo ya pagado); reactivar lo deshace. Nunca cancelación
    inmediata: ese dinero ya está pagado.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_subscription_id
                FROM users
                WHERE user_id=%s AND group_id=%s
                AND stripe_subscription_id IS NOT NULL

            """, (user_id, group_id))

            row = cur.fetchone()

        if not row:
            return False

        stripe.Subscription.modify(
            row[0],
            cancel_at_period_end=(not enabled)
        )

        return True

    except Exception as e:

        print("Renovación: error cambiando el interruptor:", str(e)[:200])

        return False
