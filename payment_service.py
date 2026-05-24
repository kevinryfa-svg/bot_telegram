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



# =========================
# PAYMENT SERVICE — GROUP PROVIDER SETTINGS PHASE 1B
# =========================

GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED = "not_configured"
GROUP_PAYMENT_PROVIDER_STATUS_PENDING = "pending"
GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE = "active"
GROUP_PAYMENT_PROVIDER_STATUS_DISABLED = "disabled"
GROUP_PAYMENT_PROVIDER_STATUS_ERROR = "error"


GROUP_PAYMENT_PROVIDER_STATUS_LABELS = {
    GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED: "pendiente / no configurado",
    GROUP_PAYMENT_PROVIDER_STATUS_PENDING: "pendiente",
    GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE: "activo",
    GROUP_PAYMENT_PROVIDER_STATUS_DISABLED: "deshabilitado",
    GROUP_PAYMENT_PROVIDER_STATUS_ERROR: "error"
}


def fetch_group_payment_provider_config(group_id, provider):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT provider,
                       is_enabled,
                       status,
                       public_config_json,
                       secret_ref,
                       updated_at
                FROM group_payment_provider_configs
                WHERE group_id=%s
                AND provider=%s
                LIMIT 1

            """, (
                group_id,
                provider
            ))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo configuración de proveedor de grupo:",
            e
        )

        return None


def ensure_group_payment_provider_config(owner_user_id, group_id, provider, status=GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED):

    valid_providers = [
        provider_config.get("provider")
        for provider_config in list_payment_provider_configs()
    ]


    if provider not in valid_providers:

        return None


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO group_payment_provider_configs
                (owner_user_id, group_id, provider, is_enabled, status, public_config_json)
                VALUES (%s, %s, %s, FALSE, %s, '{}'::jsonb)
                ON CONFLICT (group_id, provider)
                DO UPDATE SET owner_user_id=EXCLUDED.owner_user_id,
                              updated_at=CURRENT_TIMESTAMP
                RETURNING id,
                          owner_user_id,
                          group_id,
                          provider,
                          is_enabled,
                          status,
                          updated_at

            """, (
                owner_user_id,
                group_id,
                provider,
                status
            ))

            row = cur.fetchone()

            conn.commit()

            return row

    except Exception as e:

        conn.rollback()

        print(
            "Error preparando configuración de proveedor de grupo:",
            e
        )

        return None


def list_group_payment_provider_statuses(group_id):

    saved_rows = {}


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT provider,
                       is_enabled,
                       status,
                       public_config_json,
                       secret_ref,
                       updated_at
                FROM group_payment_provider_configs
                WHERE group_id=%s

            """, (group_id,))

            saved_rows = {
                row[0]: row
                for row in cur.fetchall()
            }

    except Exception as e:

        print(
            "Error listando proveedores de pago del grupo:",
            e
        )


    statuses = []


    for provider_config in list_payment_provider_configs():

        provider = provider_config.get("provider")
        saved = saved_rows.get(provider)
        global_enabled = provider_config.get("enabled") is True


        if saved:

            _provider, is_enabled, status, _public_config, secret_ref, updated_at = saved

        else:

            is_enabled = False
            status = GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED
            secret_ref = None
            updated_at = None


        if not global_enabled:

            effective_status = GROUP_PAYMENT_PROVIDER_STATUS_DISABLED
            effective_label = "deshabilitado globalmente"
            can_be_enabled = False

        elif is_enabled and status == GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE:

            effective_status = GROUP_PAYMENT_PROVIDER_STATUS_ACTIVE
            effective_label = "activo para este grupo"
            can_be_enabled = True

        else:

            effective_status = status or GROUP_PAYMENT_PROVIDER_STATUS_NOT_CONFIGURED
            effective_label = GROUP_PAYMENT_PROVIDER_STATUS_LABELS.get(
                effective_status,
                effective_status
            )
            can_be_enabled = True


        statuses.append({
            "provider": provider,
            "label": provider_config.get("label"),
            "flag": provider_config.get("flag"),
            "global_enabled": global_enabled,
            "group_enabled": is_enabled is True,
            "status": effective_status,
            "status_label": effective_label,
            "has_secret_ref": bool(secret_ref),
            "missing_env": provider_config.get("missing_env") or [],
            "can_be_enabled": can_be_enabled,
            "updated_at": updated_at
        })


    return statuses


def build_group_payment_methods_text(group_id, group_name, telegram_group_id, owner_user_id=None):

    lines = [
        "💳 Métodos de pago del grupo",
        "",
        f"Comunidad: {group_name or f'Grupo {group_id}'}",
        f"ID interno: {group_id}",
        f"ID Telegram: {telegram_group_id or 'pendiente'}"
    ]


    if owner_user_id:

        lines.append(f"Owner: {owner_user_id}")


    lines.extend([
        "",
        "Aquí se prepara la configuración de métodos de pago propios de esta comunidad.",
        "En esta fase todavía no se activan cobros reales por owner/grupo ni se piden credenciales.",
        "Los métodos siempre respetan los flags globales de la plataforma.",
        ""
    ])


    for provider in list_group_payment_provider_statuses(group_id):

        lines.extend([
            provider.get("label") or provider.get("provider"),
            f"Estado global: {'activo' if provider.get('global_enabled') else 'deshabilitado'}",
            f"Estado del grupo: {provider.get('status_label')}",
            f"Flag: {provider.get('flag')}",
            ""
        ])


    lines.extend([
        "Qué falta para activar pagos propios en próximas fases:",
        "- Captura segura de credenciales por proveedor.",
        "- Webhooks verificados por owner/grupo.",
        "- Idempotencia por proveedor y evento externo.",
        "- Concesión de acceso solo tras confirmación real del pago.",
        "",
        "Stripe global sigue funcionando como hasta ahora."
    ])


    return "\n".join(lines)
