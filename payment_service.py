from datetime import datetime, timedelta

from db import conn


# =========================
# PAYMENT SERVICE — GET PLAN BY PRICE
# =========================

def get_active_plan_by_price(price_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       price_id,
                       duration_days,
                       amount,
                       currency,
                       group_id

                FROM plans

                WHERE price_id=%s
                AND group_id=%s
                AND is_active=TRUE

                LIMIT 1

            """, (

                price_id,
                group_id

            ))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo plan activo por price_id:",
            e
        )

        return None


# =========================
# PAYMENT SERVICE — CALCULATE EXPIRATION
# duration_days currently stores minutes for test plans when value < 1440.
# =========================

def calculate_expiration_from_duration(duration_days):

    if duration_days is None or duration_days == 0:

        return None


    duration_value = int(duration_days)


    if duration_value < 1440:

        return datetime.now() + timedelta(
            minutes=duration_value
        )


    return datetime.now() + timedelta(
        days=duration_value // 1440
    )


# =========================
# PAYMENT SERVICE — SAVE PAYMENT
# =========================

def save_payment(user_id, plan_name, group_id=None, amount=None, currency=None, stripe_payment_id=None, status="paid"):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO payments
                (user_id, group_id, stripe_payment_id, amount, currency, status, plan)

                VALUES (%s, %s, %s, %s, %s, %s, %s)

            """, (

                user_id,
                group_id,
                stripe_payment_id,
                amount,
                currency,
                status,
                plan_name

            ))

            conn.commit()

            return True

    except Exception as e:

        conn.rollback()

        print(
            "Error guardando pago:",
            e
        )

        return False


# =========================
# PAYMENT SERVICE — LIST PAYMENTS
# =========================

def list_recent_payments(limit=50, group_id=None):

    try:

        with conn.cursor() as cur:

            if group_id is None:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           group_id,
                           amount,
                           currency,
                           status,
                           payment_date

                    FROM payments

                    ORDER BY payment_date DESC

                    LIMIT %s

                """, (limit,))

            else:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           group_id,
                           amount,
                           currency,
                           status,
                           payment_date

                    FROM payments

                    WHERE group_id=%s

                    ORDER BY payment_date DESC

                    LIMIT %s

                """, (

                    group_id,
                    limit

                ))


            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando pagos:",
            e
        )

        return []


# =========================
# PAYMENT SERVICE — MULTIGATEWAY PHASE 1
# =========================

from payment_gateway_config import (
    PAYMENT_PROVIDER_CRYPTO,
    PAYMENT_PROVIDER_PAYPAL,
    PAYMENT_PROVIDER_REVOLUT,
    PAYMENT_PROVIDER_STRIPE,
    PAYMENT_STATUS_PENDING,
    is_payment_provider_enabled,
    list_payment_provider_configs
)


class PaymentProviderUnavailable(Exception):

    pass


def get_enabled_payment_providers(include_disabled=False):

    providers = list_payment_provider_configs()


    if include_disabled:

        return providers


    return [
        provider
        for provider in providers
        if provider.get("enabled")
    ]


def is_stripe_payments_enabled():

    return is_payment_provider_enabled(PAYMENT_PROVIDER_STRIPE)


def create_placeholder_checkout(provider, **kwargs):

    if provider in (
        PAYMENT_PROVIDER_PAYPAL,
        PAYMENT_PROVIDER_REVOLUT,
        PAYMENT_PROVIDER_CRYPTO
    ):

        raise PaymentProviderUnavailable(
            "Este método de pago aún no está disponible."
        )


    raise PaymentProviderUnavailable(
        "Proveedor de pago no soportado en esta fase."
    )


def build_payment_methods_admin_text():

    lines = [
        "💳 Métodos de pago",
        "",
        "Estado de proveedores automáticos preparados para el bot.",
        "Stripe sigue siendo el proveedor activo para checkout real. PayPal, Revolut y cripto quedan preparados pero desactivados hasta configurar credenciales reales.",
        ""
    ]


    for provider in list_payment_provider_configs():

        enabled = "activo" if provider.get("enabled") else "desactivado"
        missing = provider.get("missing_env") or []
        missing_text = "ninguna" if not missing else ", ".join(missing)

        lines.extend([
            f"{provider.get('label')}",
            f"Estado: {enabled}",
            f"Flag: {provider.get('flag')}",
            f"Variables pendientes: {missing_text}",
            ""
        ])


    lines.extend([
        "Seguridad fase 1:",
        "- No se concede acceso por PayPal, Revolut ni cripto.",
        "- Ningún webhook nuevo está activo todavía.",
        "- No se guardan secretos en logs ni en el repo.",
        "- El acceso se concede solo cuando el proveedor confirma pago por webhook verificado."
    ])


    return "\n".join(lines)


def build_payment_gateway_architecture_notes():

    return {
        "provider": "stripe/paypal/revolut/crypto",
        "status": PAYMENT_STATUS_PENDING,
        "idempotency": "external_checkout_id + provider + event id",
        "access_rule": "no conceder acceso hasta webhook confirmado",
        "crypto_recommendation": "Coinbase Commerce para fase inicial alojada o BTCPay Server si se quiere autocustodia y más control."
    }
