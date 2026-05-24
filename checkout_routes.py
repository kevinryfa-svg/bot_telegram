import os
import stripe

from flask import request, jsonify, redirect

from db import conn
from payment_gateway_config import (
    PAYMENT_PROVIDER_PAYPAL,
    PAYMENT_PROVIDER_STRIPE,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_PENDING,
    PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION,
    PURCHASE_TYPE_GROUP_ACCESS
)
from payment_service import (
    PaymentProviderUnavailable,
    create_payment_transaction,
    is_stripe_payments_enabled
)
from payment_providers.paypal_provider import (
    cancel_paypal_order,
    capture_paypal_order,
    create_platform_paypal_order,
    process_paypal_webhook
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


    # =========================
    # PAYPAL PLATFORM CHECKOUT
    # =========================

    @app.route("/create-paypal-platform-order", methods=["POST"])
    def create_paypal_platform_order():

        data = request.json or {}

        try:

            user_id = int(data.get("user_id") or data.get("telegram_id"))
            amount = int(data.get("amount"))
            currency = (data.get("currency") or "EUR").upper()
            purchase_type = data.get("purchase_type") or PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION
            platform_product_key = data.get("platform_product_key")
            description = data.get("description") or "Pago de plataforma"

        except Exception:

            return jsonify({"error": "Datos de pago inválidos"}), 400


        try:

            order = create_platform_paypal_order(
                user_id=user_id,
                amount=amount,
                currency=currency,
                purchase_type=purchase_type,
                platform_product_key=platform_product_key,
                description=description,
                metadata={
                    "source": "create_paypal_platform_order"
                }
            )

        except PaymentProviderUnavailable as e:

            return jsonify({"error": str(e)}), 503

        except ValueError as e:

            return jsonify({"error": str(e)}), 400

        except Exception as e:

            print("Error creando orden PayPal plataforma:", e)

            return jsonify({"error": "Error creando orden PayPal"}), 500


        return jsonify({
            "provider": PAYMENT_PROVIDER_PAYPAL,
            "payment_scope": PAYMENT_SCOPE_PLATFORM,
            "order_id": order.get("order_id"),
            "url": order.get("approval_url")
        })


    @app.route("/paypal/return", methods=["GET"])
    def paypal_return():

        order_id = request.args.get("token")

        if order_id:

            try:

                capture_paypal_order(order_id)

            except Exception as e:

                print("Error capturando orden PayPal:", e)


        return redirect(
            os.environ.get("PAYPAL_SUCCESS_REDIRECT") or "https://t.me/TheStarVipBOT"
        )


    @app.route("/paypal/cancel", methods=["GET"])
    def paypal_cancel():

        order_id = request.args.get("token")

        if order_id:

            cancel_paypal_order(order_id)


        return redirect(
            os.environ.get("PAYPAL_CANCEL_REDIRECT") or "https://t.me/TheStarVipBOT"
        )


    @app.route("/webhook/paypal", methods=["POST"])
    def paypal_webhook():

        event_body = request.get_json(silent=True) or {}

        try:

            result = process_paypal_webhook(
                event_body,
                request.headers
            )

        except Exception as e:

            print("Error procesando webhook PayPal:", e)

            return "Error", 500


        return result.get("message", "OK"), result.get("status_code", 200)
