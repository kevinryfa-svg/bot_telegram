"""
Cambiar el precio de un plan sin que se descuadre lo que se cobra.

El importe de un plan vive en DOS sitios: `plans.amount`, que es lo que el bot
ENSEÑA, y el precio de Stripe (`plans.stripe_price_id`), que es lo que de verdad
se COBRA. El asistente del panel deja cambiar el primero y pide el segundo a
mano, y nada comprueba que coincidan.

O sea que hoy se puede subir un plan de 7 a 29 EUR, verlo anunciado a 29, y que
al comprador se le cobren 7. O al revés, que es peor: anunciar 7 y cobrar 29.
Nadie se entera hasta que alguien mira un extracto.

Aquí el cambio de precio hace las dos cosas a la vez: escribe el importe y crea
en Stripe un precio que dice exactamente eso.

LO QUE NO TOCA: EL PRECIO DE QUIEN YA ESTÁ DENTRO

Una suscripción de Stripe guarda su propio precio. Crear uno nuevo para el plan
solo afecta a las altas NUEVAS, que es justo la regla 4 del documento de reglas
del dinero. Ni un socio actual paga un céntimo distinto por esto.
"""

from audit_log_service import log_event
from db import conn


def fetch_group_plan(plan_id):
    """El plan con lo que hace falta para ponerle precio. None si no existe."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       group_id,
                       COALESCE(NULLIF(name, ''), 'Plan'),
                       amount,
                       COALESCE(NULLIF(currency, ''), 'EUR'),
                       duration_days,
                       COALESCE(is_recurring, FALSE),
                       stripe_price_id,
                       COALESCE(NULLIF(payment_provider, ''), 'stripe')
                FROM plans
                WHERE id = %s

            """, (int(plan_id),))

            fila = cur.fetchone()

    except Exception as e:

        print("Precio de plan: error leyendo el plan:", e)

        return None

    if not fila:
        return None

    return {
        "id": fila[0],
        "group_id": fila[1],
        "name": fila[2],
        "amount": fila[3],
        "currency": fila[4],
        "duration_days": fila[5],
        "is_recurring": bool(fila[6]),
        "stripe_price_id": fila[7],
        "provider": fila[8],
    }


def crear_precio_stripe_para_plan(plan, amount_major):
    """Crea en Stripe un precio que dice exactamente lo que se va a enseñar.

    Recurrente solo si el plan lo es: convertir un pago único en suscripción (o
    al revés) cambia lo que el comprador cree que está comprando, y eso acaba en
    una devolución con razón.

    OJO CON LAS UNIDADES: plans.amount va en unidades MAYORES (15 son 15 euros),
    al contrario que commercial_plans y payments, que van en céntimos. En este
    fichero se trabaja siempre en mayores.
    """

    from stripe_catalog import create_stripe_product_and_price

    intervalo = int(plan.get("duration_days") or 0) if plan.get("is_recurring") else None

    _producto, price_id = create_stripe_product_and_price(
        plan.get("name") or "Plan",
        amount_major,
        plan.get("currency") or "EUR",
        metadata={
            "purpose": "group_access",
            "plan_id": plan.get("id"),
            "group_id": plan.get("group_id"),
        },
        recurring_interval_days=intervalo or None,
    )

    return price_id


def set_group_plan_price(plan_id, amount_major):
    """Cambia el precio de un plan: lo que se enseña y lo que se cobra.

    Devuelve (ok, detalle). No hace nada si el importe ya es ese: repetirlo
    crearía un precio de Stripe nuevo idéntico en cada ejecución.
    """

    plan = fetch_group_plan(plan_id)

    if not plan:
        return (False, f"no existe el plan {plan_id}")

    try:

        nuevo = float(amount_major)

    except (TypeError, ValueError):

        return (False, "el importe no es un número")

    if nuevo <= 0:
        return (False, "el importe tiene que ser mayor que cero")

    actual = float(plan["amount"] or 0)

    if abs(actual - nuevo) < 0.005 and plan.get("stripe_price_id"):
        return (True, f"el plan {plan_id} ya está a {nuevo:.2f}")

    if (plan.get("provider") or "stripe").lower() != "stripe":

        # Con otro proveedor, el identificador del precio lo emite él y no se
        # puede crear desde aquí: cambiar solo el importe dejaría descuadrado lo
        # que se cobra, que es justo lo que este módulo existe para evitar.
        return (
            False,
            f"el plan {plan_id} cobra por {plan['provider']}: su precio se "
            "cambia en ese proveedor, no aquí"
        )

    try:

        price_id = crear_precio_stripe_para_plan(plan, nuevo)

    except Exception as e:

        return (False, f"Stripe no aceptó el precio nuevo: {str(e)[:160]}")

    try:

        with conn.cursor() as cur:

            # Importe y precio de Stripe se escriben JUNTOS. Escribir solo uno
            # es exactamente el descuadre que este módulo evita.
            cur.execute("""

                UPDATE plans
                SET amount = %s,
                    stripe_price_id = %s,
                    price_id = %s
                WHERE id = %s

            """, (nuevo, price_id, price_id, int(plan_id)))

            conn.commit()

    except Exception as e:

        conn.rollback()

        return (False, f"error guardando el precio: {str(e)[:160]}")

    log_event(
        "group_plan_price_changed",
        category="billing",
        severity="info",
        scope="group",
        group_id=plan.get("group_id"),
        message="Precio de un plan cambiado, con su precio de Stripe nuevo.",
        metadata={
            "plan_id": int(plan_id),
            "antes": actual,
            "ahora": nuevo,
            "currency": plan.get("currency"),
            "stripe_price_id": price_id,
            "recurrente": bool(plan.get("is_recurring")),
        },
    )

    return (
        True,
        f"plan {plan_id}: {actual:.2f} → {nuevo:.2f} {plan['currency']} "
        f"(precio de Stripe nuevo, solo para altas nuevas)"
    )
