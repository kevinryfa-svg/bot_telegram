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


def resolver_plan_de_grupo(group_id):
    """(plan_id, detalle). El plan de una comunidad al que cambiar el precio.

    Se elige el más barato de los que SE PUEDEN vender y entregar por Stripe. Si
    hay empate a precio, se niega y los enumera: elegir por sorteo entre dos
    planes de verdad es cómo se le cambia el precio al que no era.
    """

    from payment_access_service import MAX_PLAN_DURATION_DAYS

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, COALESCE(NULLIF(name, ''), 'Plan'), amount,
                       duration_days
                FROM plans
                WHERE group_id = %s
                  AND COALESCE(is_active, TRUE) = TRUE
                  AND COALESCE(NULLIF(payment_provider, ''), 'stripe') = 'stripe'
                  AND amount IS NOT NULL AND amount > 0
                  AND duration_days IS NOT NULL
                  AND duration_days > 0
                  AND duration_days <= %s
                ORDER BY amount ASC, id ASC

            """, (int(group_id), MAX_PLAN_DURATION_DAYS))

            filas = cur.fetchall() or []

    except Exception as e:

        return (None, f"error leyendo los planes del grupo {group_id}: {e}")

    if not filas:
        return (None, f"el grupo {group_id} no tiene ningún plan cobrable por Stripe")

    inventario = ", ".join(
        f"#{f[0]} {f[1]} {float(f[2]):.2f} ({f[3]}d)" for f in filas
    )

    if len(filas) > 1 and float(filas[0][2]) == float(filas[1][2]):

        return (
            None,
            f"el grupo {group_id} tiene varios planes al mismo precio y no se "
            f"elige por sorteo: {inventario}"
        )

    return (filas[0][0], f"grupo {group_id} → plan #{filas[0][0]} ({inventario})")


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


def planes_stripe_vendibles():
    """Los planes activos que se cobran por Stripe y se pueden entregar."""

    from payment_access_service import MAX_PLAN_DURATION_DAYS

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT p.id, p.group_id,
                       COALESCE(NULLIF(g.name, ''), 'la comunidad'),
                       COALESCE(NULLIF(p.name, ''), 'Plan'),
                       p.amount,
                       COALESCE(NULLIF(p.currency, ''), 'EUR'),
                       p.duration_days,
                       COALESCE(p.is_recurring, FALSE),
                       COALESCE(NULLIF(p.stripe_price_id, ''), '')
                FROM plans p
                JOIN groups g ON g.id = p.group_id
                WHERE COALESCE(p.is_active, TRUE) = TRUE
                  AND COALESCE(g.is_active, TRUE) = TRUE
                  AND COALESCE(NULLIF(p.payment_provider, ''), 'stripe') = 'stripe'
                  AND p.amount IS NOT NULL AND p.amount > 0
                  AND p.duration_days IS NOT NULL
                  AND p.duration_days > 0
                  AND p.duration_days <= %s
                ORDER BY p.group_id, p.id

            """, (MAX_PLAN_DURATION_DAYS,))

            filas = cur.fetchall() or []

    except Exception as e:

        print("Precio de plan: error listando planes vendibles:", e)

        return []

    return [
        {
            "id": f[0], "group_id": f[1], "group_name": f[2], "name": f[3],
            "amount": f[4], "currency": f[5], "duration_days": f[6],
            "is_recurring": bool(f[7]), "stripe_price_id": f[8] or None,
        }
        for f in filas
    ]


def reparar_precios_de_planes():
    """Le crea precio de Stripe a los planes que se venden y no lo tienen.

    Un plan puede estar activo, con importe y con duración —o sea, en el
    escaparate— y no tener identificador de precio de Stripe. Entonces se
    anuncia, se pulsa, y el cobro no se puede ni empezar: se ofrece algo que no
    se puede comprar, que es la peor mentira que puede decir una tienda.

    El precio se crea con el importe QUE YA SE ANUNCIA, así que nadie paga nada
    distinto de lo que vio. Y solo se toca lo que falta: un precio existente no
    se reemplaza aquí ni aunque Stripe no lo reconozca, porque reemplazarlo a
    ciegas cambiaría lo que se cobra a partir de ese momento sin que nadie lo
    haya decidido.
    """

    reparados = []

    for plan in planes_stripe_vendibles():

        if plan.get("stripe_price_id"):
            continue

        try:

            price_id = crear_precio_stripe_para_plan(plan, float(plan["amount"]))

        except Exception as e:

            print(
                "Precio de plan: no se pudo crear el precio del plan",
                plan["id"], "-", str(e)[:160]
            )

            continue

        try:

            with conn.cursor() as cur:

                # El WHERE con el hueco evita que dos arranques a la vez dejen
                # dos precios distintos para el mismo plan.
                cur.execute("""

                    UPDATE plans
                    SET stripe_price_id = %s,
                        price_id = COALESCE(NULLIF(price_id, ''), %s)
                    WHERE id = %s
                      AND COALESCE(NULLIF(stripe_price_id, ''), '') = ''

                """, (price_id, price_id, plan["id"]))

                cambiado = cur.rowcount > 0
                conn.commit()

        except Exception as e:

            conn.rollback()

            print("Precio de plan: error guardando el precio creado:", e)

            continue

        if not cambiado:
            continue

        reparados.append(plan)

        log_event(
            "group_plan_stripe_price_repaired",
            category="billing",
            severity="warning",
            scope="group",
            group_id=plan["group_id"],
            message="Plan a la venta sin precio de Stripe: se le ha creado uno.",
            metadata={
                "plan_id": plan["id"],
                "group": plan["group_name"],
                "amount": float(plan["amount"]),
                "currency": plan["currency"],
                "stripe_price_id": price_id,
            },
        )

    return reparados


def describe_price_repairs():
    """Una línea para el arranque. Si no había nada roto, se calla."""

    reparados = reparar_precios_de_planes()

    if not reparados:
        return None

    detalle = ", ".join(
        f"{p['group_name']}/{p['name']} {float(p['amount']):.2f} {p['currency']}"
        for p in reparados
    )

    return (
        f"Precios de plan: {len(reparados)} plan(es) estaban a la venta SIN "
        f"precio de Stripe y no se podían cobrar; se les ha creado uno con su "
        f"importe anunciado ({detalle})."
    )


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
