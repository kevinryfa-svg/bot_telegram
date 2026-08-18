"""
La puerta de entrada de un propietario: publicar su comunidad, pagando.

El camino de alguien que quería pagar por publicar su comunidad estaba roto en
tres sitios seguidos, y ninguno daba error:

  1. Los cuatro planes comerciales («1 mes», «3 meses», «6 meses», «1 año») se
     siembran con amount NULL, así que la pantalla los enseñaba como «pendiente
     de precio».
  2. No había NINGUNA pantalla para ponerles precio. Ni en el panel global.
  3. Y aunque un plan hubiera tenido precio, al pulsarlo el bot contestaba
     literalmente «El pago automático comercial todavía está pendiente de
     conectar».

O sea que la plataforma no podía cobrarle a un propietario ni queriendo: hacía
falta que una persona contestara una solicitud, se pusiera de acuerdo en un
importe por fuera, y activara el cupo a mano. Eso no es un negocio que funcione
solo, es una lista de espera.

Este módulo conecta los tres: pone el precio donde ya vive (commercial_plans, que
gestiona el super admin), crea el precio de Stripe a partir de ese importe sin
tocar el panel de Stripe, cobra, y al confirmarse el pago da el cupo.

DÓNDE VIVE LA DECISIÓN DE NEGOCIO

El importe lo decide el dueño del bot, no este código: mientras no haya ningún
plan con precio, el camino de siempre (dejar una solicitud para que la revise una
persona) se queda exactamente como estaba. Eso es la versión honesta de «dormido
hasta activar»: no hace falta encender ninguna bandera, basta con poner un
precio.

QUÉ PASA CUANDO SE DEJA DE PAGAR

Se le quita el cupo —no puede publicar comunidades NUEVAS— y su estado pasa a
expirado. Lo que NO se toca son las comunidades que ya tiene ni los accesos de
quien le compró: esos los pagaron sus compradores. Apagarlos por una factura del
propietario sería quitarle a un tercero algo que pagó, y eso no se hace ni con
una deuda delante.
"""

import os

import stripe

from audit_log_service import log_event
from db import conn


PLATFORM_PLAN_PURPOSE = "platform_plan"

# El producto del catálogo comercial al que corresponde publicar en este bot.
PLATFORM_PLAN_PRODUCT = "shared_bot_space"

# Cuántas comunidades puede publicar quien paga el plan. Una: el plan se llama
# «publicar MI comunidad», y subirlo es una decisión comercial, no técnica.
PLATFORM_PLAN_GROUP_QUOTA = int(
    os.environ.get("PLATFORM_PLAN_GROUP_QUOTA", "1")
)


def format_plan_amount(plan):
    """«29,00 EUR». amount de commercial_plans va en CÉNTIMOS.

    La misma trampa de unidad que ya costó un panel de ingresos entero: aquí un
    fallo se cobra, así que la división vive en un solo sitio y todo pasa por
    aquí.
    """

    if not plan or plan.get("amount") is None:
        return None

    centimos = int(plan.get("amount") or 0)
    moneda = (plan.get("currency") or "EUR").upper()

    return f"{centimos / 100:.2f}".replace(".", ",") + f" {moneda}"


def describe_plan_period(plan):
    """«al mes», «cada 3 meses», «al año»: lo que el comprador espera leer."""

    dias = int((plan or {}).get("duration_days") or 0)

    if dias in (28, 29, 30, 31):
        return "al mes"

    if dias in (365, 366):
        return "al año"

    if dias in (90, 91, 92):
        return "cada 3 meses"

    if dias in (180, 181, 182, 183):
        return "cada 6 meses"

    if dias > 0:
        return f"cada {dias} días"

    return ""


def fetch_purchasable_platform_plans():
    """Los planes de publicación que SE PUEDEN cobrar: activos y con importe.

    Un plan sin importe no se ofrece: enseñar «pendiente de precio» en una
    pantalla de compra es pedirle al comprador que adivine.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, product_type, name, duration_days, amount,
                       COALESCE(currency, 'EUR'), stripe_price_id
                FROM commercial_plans
                WHERE product_type = %s
                  AND COALESCE(is_active, TRUE) = TRUE
                  AND amount IS NOT NULL
                  AND amount > 0
                  AND duration_days IS NOT NULL
                  AND duration_days > 0
                ORDER BY duration_days ASC, id ASC

            """, (PLATFORM_PLAN_PRODUCT,))

            filas = cur.fetchall() or []

    except Exception as e:

        print("Plan de publicación: error leyendo los planes:", e)

        return []

    return [
        {
            "id": fila[0],
            "product_type": fila[1],
            "name": fila[2],
            "duration_days": fila[3],
            "amount": fila[4],
            "currency": fila[5],
            "stripe_price_id": fila[6],
        }
        for fila in filas
    ]


def platform_plan_is_purchasable():
    """¿Hay algo que un propietario pueda comprar ahora mismo?"""

    return bool(fetch_purchasable_platform_plans())


def fetch_platform_plan(plan_id):
    """Un plan concreto, con las mismas garantías que la lista."""

    for plan in fetch_purchasable_platform_plans():

        if int(plan["id"]) == int(plan_id):
            return plan

    return None


def set_platform_plan_amount(plan_id, amount_cents, currency="EUR"):
    """Le pone precio a un plan. Borra el precio de Stripe anterior.

    Sin borrarlo, cambiar el importe dejaría el precio viejo pegado al plan y se
    seguiría cobrando el anterior: el número de la pantalla y el del cargo
    dejarían de ser el mismo, que es la peor cosa que puede pasarle a un precio.
    """

    centimos = int(amount_cents)

    if centimos <= 0:
        return False

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE commercial_plans
                SET amount=%s, currency=%s, stripe_price_id=NULL
                WHERE id=%s

            """, (centimos, (currency or "EUR").upper(), int(plan_id)))

            cambiado = cur.rowcount > 0
            conn.commit()

    except Exception as e:

        conn.rollback()

        print("Plan de publicación: error guardando el importe:", e)

        return False

    if cambiado:

        log_event(
            "platform_plan_amount_set",
            category="billing",
            severity="info",
            scope="global",
            message="Importe de un plan de publicación configurado.",
            metadata={
                "plan_id": int(plan_id),
                "amount_cents": centimos,
                "currency": (currency or "EUR").upper(),
            },
        )

    return cambiado


def ensure_platform_plan_stripe_price(plan):
    """El price_id del plan, creándolo en Stripe la primera vez.

    Antes esto era trabajo manual: la pantalla decía «un administrador debe
    añadir el price_id de Stripe», y mientras nadie lo hiciera el plan no se
    podía comprar. El importe ya está en la base: crear el precio con él es
    exactamente lo que hace el resto del sistema con los planes de acceso.
    """

    if not plan:
        return None

    if plan.get("stripe_price_id"):
        return plan["stripe_price_id"]

    centimos = int(plan.get("amount") or 0)

    if centimos <= 0:
        return None

    from stripe_catalog import create_stripe_product_and_price

    _producto, price_id = create_stripe_product_and_price(
        f"Publicar mi comunidad · {plan.get('name') or 'Plan'}",
        # CÉNTIMOS → unidades mayores. Pasar 2900 tal cual crearía un precio de
        # 2.900 EUR.
        centimos / 100.0,
        plan.get("currency") or "EUR",
        metadata={
            "purpose": PLATFORM_PLAN_PURPOSE,
            "commercial_plan_id": plan.get("id"),
        },
        recurring_interval_days=int(plan.get("duration_days") or 30),
    )

    try:

        with conn.cursor() as cur:

            # El WHERE ... IS NULL evita que dos compras a la vez dejen dos
            # precios distintos para el mismo plan.
            cur.execute("""

                UPDATE commercial_plans
                SET stripe_price_id=%s
                WHERE id=%s AND stripe_price_id IS NULL

            """, (price_id, int(plan["id"])))

            conn.commit()

    except Exception as e:

        conn.rollback()

        print("Plan de publicación: error guardando el precio de Stripe:", e)

    log_event(
        "platform_plan_price_created",
        category="billing",
        severity="info",
        scope="global",
        message="Precio recurrente de un plan de publicación creado en Stripe.",
        metadata={
            "commercial_plan_id": plan.get("id"),
            "stripe_price_id": price_id,
            "amount_cents": centimos,
            "duration_days": plan.get("duration_days"),
        },
    )

    return price_id


def build_platform_plan_urls():
    """Vuelta al bot: el que paga aterriza donde puede seguir configurando."""

    bot = os.environ.get("BOT_USERNAME", "TheStarVipBOT")

    return (
        f"https://t.me/{bot}?start=plan_ok",
        f"https://t.me/{bot}?start=plan_no",
    )


def create_platform_plan_checkout(user_id, plan):
    """La sesión de Stripe. Lanza si el plan no se puede cobrar."""

    price_id = ensure_platform_plan_stripe_price(plan)

    if not price_id:

        raise ValueError(
            "Ese plan no tiene importe configurado, así que no se puede cobrar."
        )

    success_url, cancel_url = build_platform_plan_urls()

    metadata = {
        "purpose": PLATFORM_PLAN_PURPOSE,
        "user_id": str(int(user_id)),
        "commercial_plan_id": str(int(plan["id"])),
    }

    return stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=f"{PLATFORM_PLAN_PURPOSE}:{int(user_id)}",
        metadata=metadata,
        subscription_data={"metadata": metadata},
    )


def activate_platform_plan(user_id, stripe_subscription_id=None,
                           stripe_customer_id=None, period_end=None,
                           status="active"):
    """Convierte el pago en permiso: cupo, estado y fecha hasta cuándo.

    Idempotente: el mismo webhook reintentado deja el perfil igual, así que la
    idempotencia no necesita tabla propia.
    """

    from rbac_helpers import set_creator_group_quota

    try:

        fila = set_creator_group_quota(
            user_id, PLATFORM_PLAN_GROUP_QUOTA, commercial_status=status
        )

    except Exception as e:

        conn.rollback()

        print("Plan de publicación: error activando el cupo:", e)

        return False

    if period_end:

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE commercial_creator_profiles
                    SET subscription_until=%s, updated_at=NOW()
                    WHERE user_id=%s

                """, (period_end, user_id))

                conn.commit()

        except Exception as e:

            conn.rollback()

            # El cupo ya está dado: que falle anotar la fecha no puede dejar sin
            # publicar a quien ha pagado.
            print("Plan de publicación: error anotando la fecha de fin:", e)

    log_event(
        "platform_plan_activated",
        category="billing",
        severity="info",
        scope="global",
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Plan de publicación activado tras el pago.",
        metadata={
            "stripe_subscription_id": stripe_subscription_id,
            "stripe_customer_id": stripe_customer_id,
            "group_quota": PLATFORM_PLAN_GROUP_QUOTA,
            "status": status,
            "period_end": str(period_end) if period_end else None,
        },
    )

    return bool(fila)


def deactivate_platform_plan(user_id, reason="canceled"):
    """Deja de poder publicar comunidades NUEVAS. Lo publicado no se toca."""

    from rbac_helpers import set_creator_group_quota

    try:

        set_creator_group_quota(user_id, 0, commercial_status="expired")

    except Exception as e:

        conn.rollback()

        print("Plan de publicación: error retirando el cupo:", e)

        return False

    log_event(
        "platform_plan_deactivated",
        category="billing",
        severity="warning",
        scope="global",
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Plan de publicación desactivado: no puede publicar más.",
        metadata={"reason": reason},
    )

    return True


def describe_platform_plan_for_startup():
    """Una línea para el arranque: si nadie puede pagar, se dice."""

    planes = fetch_purchasable_platform_plans()

    if not planes:

        return (
            "Plan de publicación: SIN PRECIO. Nadie puede pagar por publicar su "
            "comunidad; quien lo intente dejará una solicitud para que la revise "
            "una persona. Se pone el precio en «Planes comerciales del bot»."
        )

    precios = ", ".join(
        f"{plan['name']}: {format_plan_amount(plan)}" for plan in planes
    )

    return f"Plan de publicación: {len(planes)} a la venta ({precios})."
