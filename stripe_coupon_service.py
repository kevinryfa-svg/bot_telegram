"""
Cupones de descuento en el checkout de Stripe.

Ya existían códigos promocionales internos (regalan días), pero no había
forma de hacer un DESCUENTO sobre el precio en el cobro real: "VERANO20 y
pagas un 20% menos". Eso vive en Stripe: un Coupon (el descuento) más un
PromotionCode (la palabra que el comprador teclea en el checkout).

Dos decisiones de diseño que importan:

  ÁMBITO   El checkout de los grupos usa la cuenta de Stripe de la
           PLATAFORMA, así que un cupón sin acotar valdría en TODAS las
           comunidades. Cada cupón se crea con applies_to limitado a los
           productos de Stripe de SU comunidad: el código de un propietario
           no descuenta los planes de otro.

  DURACIÓN "once": descuenta el primer cobro. En un plan de pago único es
           el descuento entero; en una suscripción, el primer ciclo — el
           clásico "primer mes al 50%". Los ciclos siguientes van a precio
           normal, que es lo que el propietario espera.

El registro local (group_stripe_coupons) existe porque Stripe no permite
listar promotion codes por comunidad: es nuestro índice de qué cupón es de
quién, y la papelera para desactivarlos.
"""

import re

import stripe

from audit_log_service import log_event
from db import conn
from group_subscription_service import recurso_plano


FORMATO_CODIGO = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,29}$")


def normalizar_codigo(texto):
    """'verano 20' -> 'VERANO20'. None si no puede ser un código válido."""

    limpio = re.sub(r"\s+", "", (texto or "").upper())

    return limpio if FORMATO_CODIGO.match(limpio) else None


def fetch_group_stripe_products(group_id):
    """Los productos de Stripe de esta comunidad: el perímetro del cupón."""

    with conn.cursor() as cur:

        cur.execute("""

            SELECT DISTINCT stripe_product_id
            FROM plans
            WHERE group_id = %s
              AND COALESCE(is_active, TRUE) = TRUE
              AND COALESCE(NULLIF(payment_provider, ''), 'stripe') = 'stripe'
              AND stripe_product_id IS NOT NULL

        """, (group_id,))

        return [row[0] for row in cur.fetchall()]


def create_group_coupon(group_id, code_text, percent_off, created_by=None):
    """
    Crea el cupón completo: Coupon acotado a los productos del grupo,
    PromotionCode con la palabra, y el registro local. Devuelve un dict con
    ok/error y los datos.
    """

    code = normalizar_codigo(code_text)

    if not code:

        return {"ok": False, "error": "codigo_invalido"}


    try:

        percent = int(percent_off)

    except Exception:

        return {"ok": False, "error": "porcentaje_invalido"}


    if not 1 <= percent <= 100:

        return {"ok": False, "error": "porcentaje_invalido"}


    productos = fetch_group_stripe_products(group_id)

    if not productos:

        # Sin planes de Stripe no hay perímetro: un cupón sin applies_to
        # valdría en las comunidades de otros propietarios.
        return {"ok": False, "error": "sin_planes_stripe"}


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1 FROM group_stripe_coupons
                WHERE code = %s AND COALESCE(is_active, TRUE) = TRUE

            """, (code,))

            if cur.fetchone():

                return {"ok": False, "error": "codigo_repetido"}


        cupon = recurso_plano(stripe.Coupon.create(
            percent_off=percent,
            duration="once",
            name=f"{code} · comunidad {group_id}",
            applies_to={"products": productos},
        ))

        promo = recurso_plano(stripe.PromotionCode.create(
            coupon=cupon["id"],
            code=code,
        ))

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO group_stripe_coupons
                (group_id, code, percent_off, stripe_coupon_id,
                 stripe_promotion_code_id, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id

            """, (group_id, code, percent, cupon["id"], promo["id"], created_by))

            fila_id = cur.fetchone()[0]
            conn.commit()

        log_event(
            "stripe_coupon_created",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=created_by,
            message=f"Cupón de descuento {code} ({percent}%) creado.",
            metadata={
                "code": code,
                "percent_off": percent,
                "stripe_coupon_id": cupon["id"],
                "products": productos,
            }
        )

        return {"ok": True, "id": fila_id, "code": code, "percent_off": percent}

    except Exception as e:

        print("Cupones: error creando:", str(e)[:200])

        return {"ok": False, "error": "stripe", "detalle": str(e)[:200]}


def create_recovery_promotion_code(group_id, transaction_id, percent_off=20,
                                   valid_hours=24):
    """
    Un cupón PERSONAL de recuperación de carrito: un solo uso, caduca en
    {valid_hours} horas, acotado a los productos de la comunidad. El código es
    legible y único por intento (REGRESA + id de la transacción): si se
    comparte no sirve (max_redemptions=1) y muere solo (redeem_by).

    Devuelve el código o None — quien llama decide si sin cupón hay mensaje
    (no lo hay: un segundo aviso sin descuento es ruido).
    """

    productos = fetch_group_stripe_products(group_id)

    if not productos:

        return None


    try:

        import time as time_mod

        limite = int(time_mod.time()) + int(valid_hours) * 3600
        code = f"REGRESA{int(transaction_id)}"

        cupon = recurso_plano(stripe.Coupon.create(
            percent_off=int(percent_off),
            duration="once",
            redeem_by=limite,
            name=f"{code} · recuperación comunidad {group_id}",
            applies_to={"products": productos},
        ))

        recurso_plano(stripe.PromotionCode.create(
            coupon=cupon["id"],
            code=code,
            max_redemptions=1,
            expires_at=limite,
        ))

        return code

    except Exception as e:

        print("Cupones: error creando el de recuperación:", str(e)[:200])

        return None


def deactivate_group_coupon(group_id, coupon_row_id, actor_user_id=None):
    """
    Apaga el código en Stripe (nadie más puede teclearlo) y lo marca local.
    El Coupon en sí no se borra: los checkouts ya en vuelo terminan bien.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_promotion_code_id, code
                FROM group_stripe_coupons
                WHERE id = %s AND group_id = %s
                  AND COALESCE(is_active, TRUE) = TRUE

            """, (coupon_row_id, group_id))

            row = cur.fetchone()

        if not row:

            return False

        promo_id, code = row

        stripe.PromotionCode.modify(promo_id, active=False)

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_stripe_coupons
                SET is_active = FALSE, deactivated_at = NOW()
                WHERE id = %s

            """, (coupon_row_id,))

            conn.commit()

        log_event(
            "stripe_coupon_deactivated",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=actor_user_id,
            message=f"Cupón {code} desactivado.",
            metadata={"coupon_row_id": coupon_row_id}
        )

        return True

    except Exception as e:

        print("Cupones: error desactivando:", str(e)[:200])

        return False


def list_group_coupons(group_id):
    """Los cupones vivos de la comunidad, del registro local."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, code, percent_off, created_at
                FROM group_stripe_coupons
                WHERE group_id = %s
                  AND COALESCE(is_active, TRUE) = TRUE
                ORDER BY created_at DESC
                LIMIT 20

            """, (group_id,))

            return cur.fetchall() or []

    except Exception as e:

        print("Cupones: error listando:", e)

        return []


def build_coupons_text(group_id, group_name):

    cupones = list_group_coupons(group_id)

    lineas = [
        f"🎟 Cupones de descuento de {group_name}",
        "",
        "El comprador teclea el código en el checkout de Stripe y el "
        "descuento se aplica al primer cobro (en suscripciones, al primer "
        "ciclo). Solo vale para los planes de Stripe de esta comunidad.",
        "",
    ]

    if not cupones:

        lineas.append("No hay cupones activos.")

    else:

        for _id, code, percent, creado in cupones:

            try:
                fecha = creado.strftime("%d/%m/%Y")
            except Exception:
                fecha = ""

            lineas.append(f"• {code} — {percent}% (desde {fecha})")


    return "\n".join(lineas)
