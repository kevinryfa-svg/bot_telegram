"""
Reconciliación con Stripe: lo que el webhook se perdió, se encuentra aquí.

Todo el sistema de renovación cuelga de un ancla: users.stripe_subscription_id.
Se escribe cuando el checkout se completa. Si ese webhook no llega —Stripe
reintenta, pero un despliegue en el momento justo, un 500 o un evento no
suscrito lo pierden—, el cliente PAGA y sus renovaciones no se atribuyen a
nadie: no extienden su acceso, no le avisan de nada, y el propietario no ve
un ingreso que sí está entrando. Es exactamente el tipo de fallo que no
aparece en ningún panel porque nadie está mirando ese hueco.

Este repaso compara las suscripciones vivas en Stripe con las ancladas aquí
y hace dos cosas, ninguna de ellas violenta:

  ANCLAR LO HUÉRFANO   Suscripción activa en Stripe, con metadata de acceso a
                       comunidad, cuyo socio no tiene ancla: se le pone. A
                       partir de ese momento sus renovaciones vuelven a
                       contar. No se toca su fecha de acceso: eso lo hará la
                       siguiente factura pagada, con su periodo real.

  SOLTAR LO MUERTO     Ancla local a una suscripción que Stripe ya da por
                       terminada, en un socio cuyo acceso también caducó: se
                       limpia el ancla para que pueda volver a suscribirse.
                       Solo con el acceso ya vencido — a un socio con periodo
                       vivo no se le toca nada.

Lo que NO hace: conceder acceso, quitar acceso, ni cambiar fechas. Un repaso
automático que reparte accesos es un repaso que un día reparte de más.

El resumen se manda al administrador SOLO si hubo algo. Un informe diario
que casi siempre dice "todo bien" se deja de leer justo antes del día que
importa.
"""

import os

import stripe

from audit_log_service import log_event
from db import conn
from group_subscription_service import recurso_plano


RECONCILE_ENABLED = os.environ.get(
    "STRIPE_RECONCILE_ENABLED", "true"
).strip().lower() not in ("0", "false", "no", "off")

# Tope de suscripciones a revisar por pasada: el repaso es diario y no tiene
# ninguna prisa, pero tampoco puede convertirse en una hora de llamadas.
RECONCILE_MAX = int(os.environ.get("STRIPE_RECONCILE_MAX", "300"))


def _entero(valor):

    try:

        return int(str(valor).strip())

    except (TypeError, ValueError):

        return None


def fetch_active_group_subscriptions(limit=None):
    """[(subscription_id, user_id, group_id)] de las vivas en Stripe.

    Se queda solo con las que llevan metadata de acceso a comunidad: las
    suscripciones de extras del propietario son de otro dueño y no se tocan.
    """

    tope = int(limit or RECONCILE_MAX)
    encontradas = []

    try:

        iterador = stripe.Subscription.list(
            status="active", limit=100
        ).auto_paging_iter()

        for suscripcion in iterador:

            if len(encontradas) >= tope:
                break

            # En stripe 15.x los recursos del SDK NO son diccionarios: dict()
            # sobre ellos revienta y .get() no existe. Todo lo que venga del
            # SDK pasa por el mismo aplanador que el resto del repositorio.
            plano = recurso_plano(suscripcion) or {}
            metadata = recurso_plano(plano.get("metadata")) or {}

            if (metadata.get("purpose") or "") != "group_access":
                continue

            user_id = _entero(metadata.get("telegram_id"))
            group_id = _entero(metadata.get("group_id"))

            if user_id is None or group_id is None:
                continue

            encontradas.append((plano.get("id"), user_id, group_id))

    except Exception as e:

        print("Reconciliación: error listando suscripciones de Stripe:",
              str(e)[:200])

    return encontradas


def fetch_local_anchor(user_id, group_id):
    """(existe_socio, ancla) para ese acceso."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_subscription_id
                FROM users
                WHERE user_id=%s AND group_id=%s

            """, (user_id, group_id))

            fila = cur.fetchone()

            if not fila:
                return (False, None)

            return (True, fila[0])

    except Exception as e:

        print("Reconciliación: error leyendo el ancla local:", e)

        # Sin poder leer, no se escribe: un repaso a ciegas es peor que
        # ningún repaso.
        return (True, "?")


def anchor_subscription(user_id, group_id, subscription_id):
    """Pone el ancla que faltaba. No toca fechas de acceso ni estado."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET stripe_subscription_id=%s
                WHERE user_id=%s AND group_id=%s
                  AND stripe_subscription_id IS NULL

            """, (subscription_id, user_id, group_id))

            hecho = cur.rowcount > 0
            conn.commit()

        if hecho:

            log_event(
                "reconcile_anchor_restored",
                category="payment",
                severity="warning",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Suscripción activa en Stripe reanclada al socio.",
                metadata={"stripe_subscription_id": subscription_id}
            )

        return hecho

    except Exception as e:

        conn.rollback()

        print("Reconciliación: error anclando la suscripción:", e)

        return False


def fetch_dead_anchors(limit=None):
    """Anclas de socios cuyo acceso YA venció: candidatas a estar muertas.

    Solo estas se consultan una a una en Stripe. A un socio con periodo vivo
    no se le pregunta nada: su ancla la gobiernan los webhooks.
    """

    tope = int(limit or RECONCILE_MAX)

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id, group_id, stripe_subscription_id
                FROM users
                WHERE stripe_subscription_id IS NOT NULL
                  AND expiration IS NOT NULL
                  AND expiration < NOW() - INTERVAL '2 days'
                ORDER BY expiration ASC
                LIMIT %s

            """, (tope,))

            return cur.fetchall() or []

    except Exception as e:

        print("Reconciliación: error buscando anclas muertas:", e)

        return []


def subscription_is_dead(subscription_id):
    """True solo si Stripe la da por terminada sin ninguna duda."""

    try:

        suscripcion = recurso_plano(
            stripe.Subscription.retrieve(subscription_id)
        ) or {}
        estado = (suscripcion.get("status") or "").lower()

        return estado in ("canceled", "incomplete_expired")

    except Exception as e:

        # Un error de red no puede convertirse en "está muerta": eso
        # borraría el ancla de alguien que sigue pagando.
        print("Reconciliación: no se pudo consultar la suscripción:",
              str(e)[:200])

        return False


def release_anchor(user_id, group_id, subscription_id):
    """Suelta el ancla muerta para que el socio pueda volver a suscribirse."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET stripe_subscription_id=NULL
                WHERE user_id=%s AND group_id=%s
                  AND stripe_subscription_id=%s

            """, (user_id, group_id, subscription_id))

            hecho = cur.rowcount > 0
            conn.commit()

        if hecho:

            log_event(
                "reconcile_anchor_released",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Ancla de suscripción terminada liberada.",
                metadata={"stripe_subscription_id": subscription_id}
            )

        return hecho

    except Exception as e:

        conn.rollback()

        print("Reconciliación: error liberando el ancla:", e)

        return False


def reconcile_subscriptions():
    """El repaso completo. Devuelve el resumen de lo que encontró y arregló."""

    resumen = {
        "revisadas": 0,
        "ancladas": 0,
        "sin_socio": 0,
        "ancla_distinta": 0,
        "anclas_muertas": 0,
        "liberadas": 0,
    }

    if not RECONCILE_ENABLED:
        return resumen


    for subscription_id, user_id, group_id in fetch_active_group_subscriptions():

        resumen["revisadas"] += 1

        existe, ancla = fetch_local_anchor(user_id, group_id)

        if not existe:

            # Suscripción viva sin fila de acceso: el pago se cobró y el
            # acceso no se guardó. Eso ya lo vigilan las incidencias de pago;
            # aquí solo se cuenta, porque conceder acceso desde un repaso
            # automático es lo que no se va a hacer.
            resumen["sin_socio"] += 1

            log_event(
                "reconcile_subscription_without_member",
                category="payment",
                severity="error",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Suscripción activa en Stripe sin acceso local.",
                metadata={"stripe_subscription_id": subscription_id}
            )

            continue

        if ancla is None:

            if anchor_subscription(user_id, group_id, subscription_id):
                resumen["ancladas"] += 1

            continue

        if ancla != subscription_id and ancla != "?":

            resumen["ancla_distinta"] += 1

            log_event(
                "reconcile_anchor_mismatch",
                category="payment",
                severity="warning",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="El socio tiene anclada otra suscripción.",
                metadata={
                    "anclada": ancla,
                    "encontrada_en_stripe": subscription_id
                }
            )


    for user_id, group_id, subscription_id in fetch_dead_anchors():

        resumen["anclas_muertas"] += 1

        if subscription_is_dead(subscription_id):

            if release_anchor(user_id, group_id, subscription_id):
                resumen["liberadas"] += 1


    return resumen


def build_reconcile_report(resumen):
    """El texto para el administrador. None si no hay nada que contar."""

    interesante = (
        resumen.get("ancladas")
        or resumen.get("sin_socio")
        or resumen.get("ancla_distinta")
        or resumen.get("liberadas")
    )

    if not interesante:
        return None

    lineas = [
        "🔍 Repaso de suscripciones con Stripe",
        "",
        f"Revisadas en Stripe: {resumen['revisadas']}",
    ]

    if resumen.get("ancladas"):

        lineas.append(
            f"✅ Reancladas (sus renovaciones ya no se perdían): "
            f"{resumen['ancladas']}"
        )

    if resumen.get("sin_socio"):

        lineas.append(
            f"🚨 Cobrando en Stripe SIN acceso local: {resumen['sin_socio']} "
            "— revisa las incidencias de pago"
        )

    if resumen.get("ancla_distinta"):

        lineas.append(
            f"⚠️ Con otra suscripción anclada: {resumen['ancla_distinta']}"
        )

    if resumen.get("liberadas"):

        lineas.append(
            f"🧹 Anclas muertas liberadas: {resumen['liberadas']}"
        )

    return "\n".join(lineas)


async def process_stripe_reconciliation(context, admin_id=None):
    """El job. Silencio cuando todo está bien: un informe que siempre dice
    "todo bien" se deja de leer justo antes del día que importa."""

    resumen = reconcile_subscriptions()
    texto = build_reconcile_report(resumen)

    if texto and admin_id:

        try:

            await context.bot.send_message(chat_id=admin_id, text=texto)

        except Exception as e:

            print("Reconciliación: no se pudo avisar al administrador:",
                  str(e)[:200])

    return resumen
