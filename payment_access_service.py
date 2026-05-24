import time

from datetime import datetime, timedelta

from audit_log_service import log_event
from bot_config import ADMIN_ID, TOKEN
from db import conn
from invite_link_service import create_telegram_invite_link
from notification_service import notify_super_admins, send_telegram_message
from rbac_helpers import get_group_owner_user_id
from user_activity_logger import log_user_event_by_ids


def format_payment_amount(amount, currency):

    if amount is None:

        return "-"


    try:

        return f"{int(amount) / 100:.2f} {(currency or '').upper()}".strip()

    except Exception:

        return f"{amount} {(currency or '').upper()}".strip()


def get_payment_owner_user_id(group_id, telegram_group_id):

    owner_user_id = get_group_owner_user_id(group_id)


    if owner_user_id:

        return owner_user_id


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id
                FROM commercial_requests
                WHERE (
                    approved_group_id=%s
                    OR approved_telegram_group_id=%s
                )
                AND user_id IS NOT NULL
                ORDER BY updated_at DESC NULLS LAST,
                         created_at DESC
                LIMIT 1

            """, (
                group_id,
                telegram_group_id
            ))

            row = cur.fetchone()


        if row:

            return row[0]

    except Exception as e:

        print("Error buscando owner de pago:", e)


    return None


def get_group_plan_for_access(group_id, plan_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT p.id,
                   p.name,
                   p.duration_days,
                   p.amount,
                   p.currency,
                   p.price_id,
                   g.telegram_group_id,
                   g.name
            FROM plans p
            JOIN groups g ON g.id=p.group_id
            WHERE p.id=%s
            AND p.group_id=%s
            AND p.is_active=TRUE
            AND g.is_active=TRUE
            LIMIT 1

        """, (
            plan_id,
            group_id
        ))

        row = cur.fetchone()


    if not row:

        return None


    return {
        "plan_id": row[0],
        "plan_name": row[1],
        "duration_days": row[2],
        "amount": row[3],
        "currency": row[4],
        "price_id": row[5],
        "telegram_group_id": row[6],
        "group_name": row[7]
    }


def calculate_group_access_expiration(duration_days):

    if duration_days is None or duration_days == 0:

        return None


    duration_value = int(duration_days)


    if duration_value < 1 or duration_value > 3650:

        raise ValueError("Duración de plan fuera de rango.")


    return datetime.now() + timedelta(days=duration_value)


def grant_group_access_after_payment(
    provider,
    user_id,
    group_id,
    plan_id,
    external_payment_id=None,
    external_checkout_id=None,
    amount=None,
    currency=None,
    transaction_id=None
):

    plan = get_group_plan_for_access(group_id, plan_id)


    if not plan:

        log_event(
            "payment_group_plan_not_found",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Pago confirmado pero no se encontró el plan del grupo.",
            metadata={
                "provider": provider,
                "plan_id": plan_id,
                "transaction_id": transaction_id
            }
        )

        return {
            "ok": False,
            "reason": "plan_not_found"
        }


    expiration = calculate_group_access_expiration(
        plan.get("duration_days")
    )
    telegram_group_id = plan.get("telegram_group_id")
    group_name = plan.get("group_name") or f"Grupo {group_id}"
    plan_name = plan.get("plan_name") or "Plan"
    payment_reference = f"{provider}:{external_payment_id or external_checkout_id or transaction_id}"


    max_expire = int(time.time()) + 180

    if expiration is None:

        expire_timestamp = max_expire

    else:

        expire_timestamp = min(
            max_expire,
            int(expiration.timestamp())
        )


    expire_seconds = max(
        60,
        expire_timestamp - int(time.time())
    )
    link = create_telegram_invite_link(
        TOKEN,
        telegram_group_id,
        expire_seconds=expire_seconds,
        member_limit=1
    )


    if not link:

        log_event(
            "payment_invite_link_error",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Pago confirmado pero no se pudo crear invite link.",
            metadata={
                "provider": provider,
                "transaction_id": transaction_id,
                "plan_id": plan_id
            }
        )

        return {
            "ok": False,
            "reason": "invite_link_failed"
        }


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO users
                (
                    user_id,
                    group_id,
                    expiration,
                    subscription_active,
                    last_invite_link
                )
                VALUES (%s, %s, %s, TRUE, %s)
                ON CONFLICT (user_id, group_id)
                DO UPDATE SET
                    expiration=EXCLUDED.expiration,
                    subscription_active=TRUE,
                    last_invite_link=EXCLUDED.last_invite_link

            """, (
                user_id,
                group_id,
                expiration,
                link
            ))

            cur.execute("""

                INSERT INTO payments
                (
                    user_id,
                    group_id,
                    stripe_payment_id,
                    amount,
                    currency,
                    status,
                    plan
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)

            """, (
                user_id,
                group_id,
                payment_reference,
                amount,
                currency,
                "paid",
                plan_name
            ))

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (
                user_id,
                group_id,
                telegram_group_id,
                telegram_group_id
            ))

            cur.execute("""

                INSERT INTO invite_links
                (
                    user_id,
                    group_id,
                    telegram_group_id,
                    invite_link,
                    is_active
                )
                VALUES (%s, %s, %s, %s, TRUE)

            """, (
                user_id,
                group_id,
                telegram_group_id,
                link
            ))

            conn.commit()

    except Exception as e:

        conn.rollback()

        log_event(
            "payment_storage_error",
            category="payment",
            severity="error",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Pago confirmado pero falló el guardado del acceso/link.",
            metadata={
                "provider": provider,
                "transaction_id": transaction_id,
                "plan_id": plan_id,
                "error": str(e)
            }
        )

        return {
            "ok": False,
            "reason": "storage_failed"
        }


    amount_text = format_payment_amount(amount, currency)

    send_telegram_message(
        TOKEN,
        user_id,
        f"🔗 Tu acceso VIP:\n{link}"
    )

    notify_super_admins(
        TOKEN,
        f"💳 Nuevo pago recibido\n\n"
        f"Proveedor: {provider}\n"
        f"Grupo: {group_name}\n"
        f"Usuario: {user_id}\n"
        f"Plan: {plan_name}\n"
        f"Importe: {amount_text}\n"
        "Acceso: activo",
        fallback_admin_id=ADMIN_ID
    )

    owner_user_id = get_payment_owner_user_id(
        group_id,
        telegram_group_id
    )


    if owner_user_id and int(owner_user_id) != int(ADMIN_ID):

        send_telegram_message(
            TOKEN,
            owner_user_id,
            f"💳 Nuevo pago en tu comunidad\n\n"
            f"Proveedor: {provider}\n"
            f"Grupo: {group_name}\n"
            f"Usuario: {user_id}\n"
            f"Plan: {plan_name}\n"
            f"Importe: {amount_text}\n"
            "Acceso: activo"
        )


    log_event(
        "payment_confirmed",
        category="payment",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Pago confirmado y acceso activado.",
        metadata={
            "provider": provider,
            "transaction_id": transaction_id,
            "external_payment_id": external_payment_id,
            "external_checkout_id": external_checkout_id,
            "plan_id": plan_id,
            "amount": amount,
            "currency": currency,
            "expiration": expiration
        }
    )

    log_event(
        "invite_link_created",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Invite link creado tras pago confirmado.",
        metadata={
            "provider": provider,
            "transaction_id": transaction_id,
            "external_checkout_id": external_checkout_id
        }
    )

    log_user_event_by_ids(
        user_id,
        "payment_completed",
        event_key=f"{provider}_group_payment",
        group_id=group_id,
        plan_id=plan_id,
        payment_provider=provider,
        payment_scope="group",
        metadata={
            "transaction_id": transaction_id,
            "amount": amount,
            "currency": currency
        }
    )

    log_user_event_by_ids(
        user_id,
        "invite_link_created",
        event_key="payment_invite_link",
        group_id=group_id,
        plan_id=plan_id,
        payment_provider=provider,
        payment_scope="group",
        metadata={"transaction_id": transaction_id}
    )

    return {
        "ok": True,
        "link": link,
        "expiration": expiration,
        "telegram_group_id": telegram_group_id,
        "plan_name": plan_name,
        "group_name": group_name
    }
