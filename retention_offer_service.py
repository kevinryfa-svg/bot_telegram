"""
La oferta de salvamento: el último intento antes de perder a un suscriptor.

Cuando alguien pulsa «Desactivar renovación» ya ha decidido casi todo — pero
"casi" es la palabra que paga este módulo. Antes de la confirmación se le
ofrece UNA VEZ quedarse con un descuento en su próximo cobro. Es la palanca
antichurn con mejor ratio esfuerzo/resultado que existe, y por eso todas las
suscripciones serias la tienen.

Las reglas que la mantienen honesta:

  UNA VEZ POR SUSCRIPCIÓN  La oferta se registra al MOSTRARSE, no al
                           aceptarse: quien la vio y canceló igualmente no
                           vuelve a verla en el siguiente intento. Un
                           descuento que aparece cada vez que amagas con
                           irte deja de ser un regalo y pasa a ser un truco
                           — y enseña a cancelar para conseguir rebajas.

  SOLO STRIPE              El descuento se aplica a la suscripción existente
                           (un cupón de un ciclo, creado sin perímetro
                           porque lo aplicamos NOSOTROS solo a la suya). En
                           PayPal no se puede tocar el precio de una
                           suscripción viva: allí el flujo sigue igual.

  EL CUPÓN ES DE UN CICLO  duration="once": el próximo cobro sale con el
                           descuento y los siguientes a precio normal. Nada
                           de descuentos eternos concedidos en un click.
"""

import os

import stripe

from audit_log_service import log_event
from db import conn
from group_subscription_service import recurso_plano


RETENTION_DISCOUNT_PERCENT = int(
    os.environ.get("RETENTION_DISCOUNT_PERCENT", "30")
)

RETENTION_OFFER_ENABLED = os.environ.get(
    "RETENTION_OFFER_ENABLED", "true"
).strip().lower() not in ("0", "false", "no", "off")


def offer_already_made(user_id, group_id):
    """¿Esta persona ya vio la oferta para este acceso?"""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1 FROM retention_offers
                WHERE user_id = %s AND group_id = %s
                LIMIT 1

            """, (user_id, group_id))

            return cur.fetchone() is not None

    except Exception as e:

        print("Salvamento: error comprobando la oferta:", e)

        # En caso de duda, mejor no ofertar dos veces que ofertar de más.
        return True


def record_offer_shown(user_id, group_id, stripe_subscription_id):
    """True si quedó registrada (primera vez): entonces se enseña."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO retention_offers
                    (user_id, group_id, stripe_subscription_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, group_id) DO NOTHING

            """, (user_id, group_id, stripe_subscription_id))

            hecho = cur.rowcount > 0
            conn.commit()

            return hecho

    except Exception as e:

        print("Salvamento: error registrando la oferta:", e)

        return False


def apply_save_discount(user_id, group_id):
    """
    Aplica el descuento del próximo ciclo a la suscripción de este socio.
    True si Stripe lo aceptó. El cupón se crea sin perímetro a propósito:
    lo aplicamos nosotros y solo a SU suscripción — nadie puede teclearlo.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_subscription_id
                FROM users
                WHERE user_id = %s AND group_id = %s
                  AND stripe_subscription_id IS NOT NULL

            """, (user_id, group_id))

            row = cur.fetchone()

        if not row:

            return False

        stripe_subscription_id = row[0]

        cupon = recurso_plano(stripe.Coupon.create(
            percent_off=RETENTION_DISCOUNT_PERCENT,
            duration="once",
            name=f"Salvamento {user_id} · comunidad {group_id}",
        ))

        stripe.Subscription.modify(
            stripe_subscription_id,
            discounts=[{"coupon": cupon["id"]}],
        )

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE retention_offers
                SET accepted = TRUE, accepted_at = NOW()
                WHERE user_id = %s AND group_id = %s

            """, (user_id, group_id))

            conn.commit()

        log_event(
            "retention_offer_accepted",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Oferta de salvamento aceptada: descuento aplicado al próximo ciclo.",
            metadata={
                "stripe_subscription_id": stripe_subscription_id,
                "percent_off": RETENTION_DISCOUNT_PERCENT,
            }
        )

        return True

    except Exception as e:

        print("Salvamento: error aplicando el descuento:", str(e)[:200])

        return False
