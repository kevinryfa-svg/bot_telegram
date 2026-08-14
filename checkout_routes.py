import os
import hmac
import stripe
import traceback

from flask import request, jsonify, redirect

from db import conn
from payment_gateway_config import (
    PAYMENT_PROVIDER_CHANGENOW,
    PAYMENT_PROVIDER_GUARDARIAN,
    PAYMENT_PROVIDER_PAYPAL,
    PAYMENT_PROVIDER_REVOLUT,
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
from payment_access_service import (
    build_existing_access_api_response,
    get_user_group_access_state,
    log_purchase_blocked_existing_access,
    should_block_new_group_purchase
)
from payment_providers.paypal_provider import (
    cancel_paypal_order,
    capture_paypal_order,
    create_group_paypal_order,
    create_platform_paypal_order,
    process_paypal_webhook
)
from payment_providers.revolut_provider import (
    create_group_revolut_order,
    create_platform_revolut_order,
    process_revolut_webhook
)
from payment_providers.changenow_provider import (
    create_group_changenow_order,
    create_platform_changenow_order,
    process_changenow_webhook
)
from payment_providers.guardarian_provider import (
    create_group_guardarian_order,
    create_platform_guardarian_order,
    process_guardarian_webhook
)


def _webhook_shared_secret_ok(env_var_name):
    """
    Verificación opcional de webhooks por token compartido.

    Desactivada por defecto: si la variable de entorno no está definida, no
    se exige nada y el comportamiento actual queda intacto. Si se define, el
    webhook debe incluir ese mismo valor en la cabecera 'X-Webhook-Token' o
    en el query param 'token' (configura la URL del webhook en el panel del
    proveedor como .../webhook/xxx?token=EL_SECRETO).

    Añade defensa en profundidad para ChangeNOW y Guardarian, que no firman
    sus webhooks, sin riesgo de rechazar webhooks legítimos mientras no se
    active explícitamente.
    """

    expected = os.environ.get(env_var_name)

    if not expected:

        return True


    provided = (
        request.headers.get("X-Webhook-Token")
        or request.args.get("token")
        or ""
    )

    return hmac.compare_digest(str(provided), str(expected))


def register_checkout_routes(app):

    @app.route("/owner-addon-success", methods=["GET"])
    def owner_addon_success():

        return redirect("https://t.me/TheStarVipBOT")


    @app.route("/owner-addon-cancel", methods=["GET"])
    def owner_addon_cancel():

        return redirect("https://t.me/TheStarVipBOT")


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

                    SELECT COALESCE(stripe_price_id, price_id),
                           COALESCE(is_recurring, FALSE),
                           COALESCE(trial_days, 0)

                    FROM plans

                    WHERE COALESCE(stripe_price_id, price_id)=%s
                    AND group_id=%s
                    AND is_active=TRUE
                    AND COALESCE(NULLIF(payment_provider, ''), 'stripe')='stripe'

                """, (

                    plan,
                    group_id

                ))

                row = cur.fetchone()

            if not row:

                return jsonify({"error": "Plan inválido"}), 400

            price_id = row[0]
            plan_es_recurrente = bool(row[1])
            plan_trial_days = int(row[2] or 0)

        except Exception as e:

            print("Error obteniendo price_id:", e)

            return jsonify({"error": "Error interno"}), 500


        access_state = get_user_group_access_state(telegram_id, group_id)
        community_type = access_state.get("community_type") or "group"


        if should_block_new_group_purchase(access_state):

            log_purchase_blocked_existing_access(
                telegram_id,
                group_id,
                provider=PAYMENT_PROVIDER_STRIPE,
                access_state=access_state
            )

            return jsonify(build_existing_access_api_response(access_state)), 409


        try:

            metadata_session = {
                "telegram_id": str(telegram_id),
                "group_id": str(group_id),
                "price_id": price_id,
                "community_type": community_type
            }

            session_kwargs = dict(

                payment_method_types=["card"],

                line_items=[{
                    "price": price_id,
                    "quantity": 1,
                }],

                # Un precio recurrente exige mode="subscription": es lo que
                # convierte el plan en renovación automática. La metadata se
                # copia también a la suscripción para poder reconocerla en el
                # panel de Stripe; la atribución real de los webhooks es por el
                # ancla users.stripe_subscription_id.
                mode="subscription" if plan_es_recurrente else "payment",

                # El campo "¿Tienes un código?" del checkout. Los cupones se
                # crean acotados a los productos de cada comunidad, así que el
                # código de un propietario no descuenta los planes de otro.
                allow_promotion_codes=True,

                success_url="https://t.me/TheStarVipBOT",
                cancel_url="https://t.me/TheStarVipBOT",

                metadata=metadata_session

            )

            if plan_es_recurrente:

                session_kwargs["subscription_data"] = {
                    "metadata": {
                        **metadata_session,
                        "purpose": "group_access"
                    }
                }

                # Prueba gratis: tarjeta por delante, primer cobro al acabar.
                # Solo tiene sentido en suscripciones, que es como la modela
                # Stripe. Cancelar durante la prueba = cobro cero.
                if plan_trial_days > 0:

                    session_kwargs["subscription_data"]["trial_period_days"] = (
                        plan_trial_days
                    )

            session = stripe.checkout.Session.create(**session_kwargs)

        except Exception as e:

            print(
                "Error creando sesión Stripe:",
                {
                    "provider": "stripe",
                    "user_id": telegram_id,
                    "group_id": group_id,
                    "plan_id": plan,
                    "price_id": price_id,
                    "error": str(e)
                }
            )
            print(traceback.format_exc())

            return jsonify({"error": "Error creando sesión"}), 500


        stripe_session_id = session.id

        create_payment_transaction(
            PAYMENT_PROVIDER_STRIPE,
            status=PAYMENT_STATUS_PENDING,
            payment_scope=PAYMENT_SCOPE_PLATFORM,
            purchase_type=PURCHASE_TYPE_GROUP_ACCESS,
            user_id=telegram_id,
            group_id=group_id,
            external_checkout_id=stripe_session_id,
            idempotency_key=stripe_session_id,
            metadata={
                "checkout_url": session.url,
                "price_id": price_id,
                "community_type": community_type,
                "source": "create_checkout_session"
            }
        )

        return jsonify({
            "url": session.url
        })


    # =========================
    # PAYPAL PLATFORM CHECKOUT
    # =========================

    @app.route("/create-paypal-group-order", methods=["POST"])
    def create_paypal_group_order():

        data = request.json or {}

        try:

            user_id = int(data.get("user_id") or data.get("telegram_id"))
            group_id = int(data.get("group_id"))
            plan_id = int(data.get("plan_id"))

        except Exception:

            return jsonify({"error": "Datos de pago inválidos"}), 400


        try:

            access_state = get_user_group_access_state(user_id, group_id)


            if should_block_new_group_purchase(access_state):

                log_purchase_blocked_existing_access(
                    user_id,
                    group_id,
                    provider=PAYMENT_PROVIDER_PAYPAL,
                    access_state=access_state
                )

                return jsonify(build_existing_access_api_response(access_state)), 409


            order = create_group_paypal_order(
                user_id=user_id,
                group_id=group_id,
                plan_id=plan_id,
                metadata={
                    "community_type": access_state.get("community_type") or "group",
                    "source": "create_paypal_group_order"
                }
            )

        except PaymentProviderUnavailable as e:

            return jsonify({"error": str(e)}), 503

        except ValueError as e:

            return jsonify({"error": str(e)}), 400

        except Exception as e:

            print("Error creando orden PayPal de grupo:", e)

            return jsonify({"error": "Error creando orden PayPal"}), 500


        return jsonify({
            "provider": PAYMENT_PROVIDER_PAYPAL,
            "payment_scope": "group",
            "order_id": order.get("order_id"),
            "subscription_id": order.get("subscription_id"),
            "url": order.get("approval_url")
        })


    @app.route("/create-revolut-group-order", methods=["POST"])
    def create_revolut_group_order():

        data = request.json or {}

        try:

            user_id = int(data.get("user_id") or data.get("telegram_id"))
            group_id = int(data.get("group_id"))
            plan_id = int(data.get("plan_id"))

        except Exception:

            return jsonify({"error": "Datos de pago inválidos"}), 400


        try:

            access_state = get_user_group_access_state(user_id, group_id)


            if should_block_new_group_purchase(access_state):

                log_purchase_blocked_existing_access(
                    user_id,
                    group_id,
                    provider=PAYMENT_PROVIDER_REVOLUT,
                    access_state=access_state
                )

                return jsonify(build_existing_access_api_response(access_state)), 409


            order = create_group_revolut_order(
                user_id=user_id,
                group_id=group_id,
                plan_id=plan_id,
                metadata={
                    "community_type": access_state.get("community_type") or "group",
                    "source": "create_revolut_group_order"
                }
            )

        except PaymentProviderUnavailable as e:

            return jsonify({"error": str(e)}), 503

        except ValueError as e:

            return jsonify({"error": str(e)}), 400

        except Exception as e:

            print("Error creando orden Revolut de grupo:", e)

            return jsonify({"error": "Error creando orden Revolut"}), 500


        return jsonify({
            "provider": PAYMENT_PROVIDER_REVOLUT,
            "payment_scope": "group",
            "order_id": order.get("order_id"),
            "url": order.get("checkout_url")
        })


    @app.route("/create-changenow-group-order", methods=["POST"])
    def create_changenow_group_order():

        data = request.json or {}

        try:

            user_id = int(data.get("user_id") or data.get("telegram_id"))
            group_id = int(data.get("group_id"))
            plan_id = int(data.get("plan_id"))

        except Exception:

            return jsonify({"error": "Datos de pago inválidos"}), 400


        try:

            access_state = get_user_group_access_state(user_id, group_id)


            if should_block_new_group_purchase(access_state):

                log_purchase_blocked_existing_access(
                    user_id,
                    group_id,
                    provider=PAYMENT_PROVIDER_CHANGENOW,
                    access_state=access_state
                )

                return jsonify(build_existing_access_api_response(access_state)), 409


            order = create_group_changenow_order(
                user_id=user_id,
                group_id=group_id,
                plan_id=plan_id,
                metadata={
                    "community_type": access_state.get("community_type") or "group",
                    "source": "create_changenow_group_order"
                }
            )

        except PaymentProviderUnavailable as e:

            return jsonify({"error": str(e)}), 503

        except ValueError as e:

            return jsonify({"error": str(e)}), 400

        except Exception as e:

            print("Error creando orden ChangeNOW de grupo:", e)

            return jsonify({"error": "Error creando orden ChangeNOW"}), 500


        return jsonify({
            "provider": PAYMENT_PROVIDER_CHANGENOW,
            "payment_scope": "group",
            **order
        })


    @app.route("/create-guardarian-group-order", methods=["POST"])
    def create_guardarian_group_order():

        data = request.json or {}

        try:

            user_id = int(data.get("user_id") or data.get("telegram_id"))
            group_id = int(data.get("group_id"))
            plan_id = int(data.get("plan_id"))

        except Exception:

            return jsonify({"error": "Datos de pago inválidos"}), 400


        try:

            access_state = get_user_group_access_state(user_id, group_id)


            if should_block_new_group_purchase(access_state):

                log_purchase_blocked_existing_access(
                    user_id,
                    group_id,
                    provider=PAYMENT_PROVIDER_GUARDARIAN,
                    access_state=access_state
                )

                return jsonify(build_existing_access_api_response(access_state)), 409


            order = create_group_guardarian_order(
                user_id=user_id,
                group_id=group_id,
                plan_id=plan_id,
                metadata={
                    "community_type": access_state.get("community_type") or "group",
                    "source": "create_guardarian_group_order"
                }
            )

        except PaymentProviderUnavailable as e:

            return jsonify({"error": str(e)}), 503

        except ValueError as e:

            return jsonify({"error": str(e)}), 400

        except Exception as e:

            print("Error creando orden Guardarian de grupo:", e)
            print(traceback.format_exc())

            return jsonify({"error": "Error creando orden Guardarian"}), 500


        return jsonify({
            "provider": PAYMENT_PROVIDER_GUARDARIAN,
            "payment_scope": "group",
            **order
        })


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


    @app.route("/create-changenow-platform-order", methods=["POST"])
    def create_changenow_platform_order():

        data = request.json or {}

        try:

            user_id = int(data.get("user_id") or data.get("telegram_id"))
            amount = data.get("amount")
            amount = int(amount) if amount is not None else None
            currency = (data.get("currency") or "EUR").upper()
            purchase_type = data.get("purchase_type") or PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION
            platform_product_key = data.get("platform_product_key")
            description = data.get("description") or "Pago cripto de plataforma"

        except Exception:

            return jsonify({"error": "Datos de pago inválidos"}), 400


        try:

            order = create_platform_changenow_order(
                user_id=user_id,
                amount=amount,
                currency=currency,
                purchase_type=purchase_type,
                platform_product_key=platform_product_key,
                description=description,
                metadata={
                    "source": "create_changenow_platform_order"
                }
            )

        except PaymentProviderUnavailable as e:

            return jsonify({"error": str(e)}), 503

        except ValueError as e:

            return jsonify({"error": str(e)}), 400

        except Exception as e:

            print("Error creando orden ChangeNOW plataforma:", e)

            return jsonify({"error": "Error creando orden ChangeNOW"}), 500


        return jsonify({
            "provider": PAYMENT_PROVIDER_CHANGENOW,
            "payment_scope": PAYMENT_SCOPE_PLATFORM,
            **order
        })


    @app.route("/create-guardarian-platform-order", methods=["POST"])
    def create_guardarian_platform_order():

        data = request.json or {}

        try:

            user_id = int(data.get("user_id") or data.get("telegram_id"))
            amount = int(data.get("amount"))
            currency = (data.get("currency") or "EUR").upper()
            purchase_type = data.get("purchase_type") or PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION
            platform_product_key = data.get("platform_product_key")
            description = data.get("description") or "Pago EUR a USDT de plataforma"

        except Exception:

            return jsonify({"error": "Datos de pago inválidos"}), 400


        try:

            order = create_platform_guardarian_order(
                user_id=user_id,
                amount=amount,
                currency=currency,
                purchase_type=purchase_type,
                platform_product_key=platform_product_key,
                description=description,
                metadata={
                    "source": "create_guardarian_platform_order"
                }
            )

        except PaymentProviderUnavailable as e:

            return jsonify({"error": str(e)}), 503

        except ValueError as e:

            return jsonify({"error": str(e)}), 400

        except Exception as e:

            print("Error creando orden Guardarian plataforma:", e)
            print(traceback.format_exc())

            return jsonify({"error": "Error creando orden Guardarian"}), 500


        return jsonify({
            "provider": PAYMENT_PROVIDER_GUARDARIAN,
            "payment_scope": PAYMENT_SCOPE_PLATFORM,
            **order
        })


    # =========================
    # REVOLUT PLATFORM CHECKOUT
    # =========================

    @app.route("/create-revolut-platform-order", methods=["POST"])
    def create_revolut_platform_order():

        data = request.json or {}

        try:

            user_id = int(data.get("user_id") or data.get("telegram_id"))
            purchase_type = data.get("purchase_type") or PURCHASE_TYPE_COMMERCIAL_SUBSCRIPTION
            amount_value = data.get("amount")


            if amount_value is None and purchase_type == PURCHASE_TYPE_GROUP_ACCESS:

                amount_value = 1


            amount = int(amount_value)
            currency = (data.get("currency") or "EUR").upper()
            platform_product_key = data.get("platform_product_key")
            group_id = data.get("group_id")
            plan_id = data.get("plan_id")
            description = data.get("description") or "Pago de plataforma"


            if group_id is not None:

                group_id = int(group_id)


            if plan_id is not None:

                plan_id = int(plan_id)

        except Exception:

            return jsonify({"error": "Datos de pago inválidos"}), 400


        try:

            order = create_platform_revolut_order(
                user_id=user_id,
                amount=amount,
                currency=currency,
                purchase_type=purchase_type,
                platform_product_key=platform_product_key,
                group_id=group_id,
                plan_id=plan_id,
                description=description,
                metadata={
                    "source": "create_revolut_platform_order"
                }
            )

        except PaymentProviderUnavailable as e:

            return jsonify({"error": str(e)}), 503

        except ValueError as e:

            return jsonify({"error": str(e)}), 400

        except Exception as e:

            print("Error creando orden Revolut plataforma:", e)

            return jsonify({"error": "Error creando orden Revolut"}), 500


        return jsonify({
            "provider": PAYMENT_PROVIDER_REVOLUT,
            "payment_scope": PAYMENT_SCOPE_PLATFORM,
            "order_id": order.get("order_id"),
            "url": order.get("checkout_url")
        })


    @app.route("/revolut/return", methods=["GET"])
    def revolut_return():

        return redirect(
            os.environ.get("REVOLUT_SUCCESS_REDIRECT") or "https://t.me/TheStarVipBOT"
        )


    @app.route("/revolut/cancel", methods=["GET"])
    def revolut_cancel():

        return redirect(
            os.environ.get("REVOLUT_CANCEL_REDIRECT") or "https://t.me/TheStarVipBOT"
        )


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


    @app.route("/webhook/revolut", methods=["POST"])
    def revolut_webhook():

        raw_body = request.get_data(as_text=True)
        event_body = request.get_json(silent=True) or {}

        try:

            result = process_revolut_webhook(
                event_body,
                request.headers,
                raw_body
            )

        except Exception as e:

            print("Error procesando webhook Revolut:", e)

            return "Error", 500


        return result.get("message", "OK"), result.get("status_code", 200)


    @app.route("/webhook/changenow", methods=["POST"])
    def changenow_webhook():

        if not _webhook_shared_secret_ok("CHANGENOW_WEBHOOK_SECRET"):

            print("Webhook ChangeNOW rechazado: token compartido inválido.")

            return "Unauthorized", 401


        event_body = request.get_json(silent=True) or {}

        try:

            result = process_changenow_webhook(event_body)

        except Exception as e:

            print("Error procesando webhook ChangeNOW:", e)

            return "Error", 500


        return result.get("message", "OK"), result.get("status_code", 200)


    @app.route("/webhook/guardarian", methods=["POST"])
    def guardarian_webhook():

        if not _webhook_shared_secret_ok("GUARDARIAN_WEBHOOK_SECRET"):

            print("Webhook Guardarian rechazado: token compartido inválido.")

            return "Unauthorized", 401


        event_body = request.get_json(silent=True) or {}

        try:

            result = process_guardarian_webhook(event_body)

        except Exception as e:

            print("Error procesando webhook Guardarian:", e)
            print(traceback.format_exc())

            return "Error", 500


        return result.get("message", "OK"), result.get("status_code", 200)
