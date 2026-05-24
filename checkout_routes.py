import stripe

from flask import request, jsonify

from db import conn
from payment_gateway_config import (
    PAYMENT_PROVIDER_STRIPE,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_PENDING,
    PURCHASE_TYPE_GROUP_ACCESS
)
from payment_service import (
    create_payment_transaction,
    is_stripe_payments_enabled
)


def register_checkout_routes(app):

    # =========================
    # STRIPE CHECKOUT
    # =========================

    @app.route("/create-checkout-session", methods=["POST"])
    def create_checkout_session():

        if not is_stripe_payments_enabled():

            return jsonify({"error": "Stripe no está habilitado"}), 503


        data = request.json

        telegram_id = data["telegram_id"]
        plan = data["plan"]
        group_id = data.get("group_id")

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT price_id

                    FROM plans

                    WHERE price_id=%s
                    AND group_id=%s
                    AND is_active=TRUE

                """, (

                    plan,
                    group_id

                ))

                row = cur.fetchone()

            if not row:

                return jsonify({"error": "Plan inválido"}), 400

            price_id = row[0]

        except Exception as e:

            print("Error obteniendo price_id:", e)

            return jsonify({"error": "Error interno"}), 500


        try:

            session = stripe.checkout.Session.create(

                payment_method_types=["card"],

                line_items=[{
                    "price": price_id,
                    "quantity": 1,
                }],

                mode="payment",

                success_url="https://t.me/TheStarVipBOT",
                cancel_url="https://t.me/TheStarVipBOT",

                metadata={
                    "telegram_id": str(telegram_id),
                    "group_id": str(group_id),
                    "price_id": price_id
                }

            )

        except Exception as e:

            print("Error creando sesión Stripe:", e)

            return jsonify({"error": "Error creando sesión"}), 500


        create_payment_transaction(
            PAYMENT_PROVIDER_STRIPE,
            status=PAYMENT_STATUS_PENDING,
            payment_scope=PAYMENT_SCOPE_PLATFORM,
            purchase_type=PURCHASE_TYPE_GROUP_ACCESS,
            user_id=telegram_id,
            group_id=group_id,
            external_checkout_id=session.get("id"),
            idempotency_key=session.get("id"),
            metadata={
                "price_id": price_id,
                "source": "create_checkout_session"
            }
        )

        return jsonify({
            "url": session.url
        })
