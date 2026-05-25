import time

from datetime import datetime, timedelta

from audit_log_service import log_event
from bot_config import ADMIN_ID, TOKEN
from db import conn
from invite_link_service import create_telegram_invite_link
from notification_service import notify_super_admins, send_telegram_message
from rbac_helpers import get_group_owner_user_id
from user_activity_logger import log_user_event_by_ids


ACTIVE_PAYMENT_STATUSES = ("paid", "completed")
PENDING_PAYMENT_STATUSES = ("pending", "confirming", "manual_review")
FAILED_PAYMENT_STATUSES = ("failed", "cancelled", "expired", "refunded")


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


def get_user_group_access_state(user_id, group_id):

    state = {
        "user_id": user_id,
        "group_id": group_id,
        "telegram_group_id": None,
        "group_name": None,
        "is_free_group": False,
        "has_active_access": False,
        "access_source": "unknown",
        "subscription_status": "none",
        "expires_at": None,
        "last_payment_status": None,
        "last_payment_provider": None,
        "last_payment_created_at": None,
        "has_active_invite_link": False,
        "has_active_code_access": False,
        "has_user_access_record": False,
        "paid_without_access_record": False,
        "can_buy_again": True,
        "can_recover_link": False,
        "can_renew": False,
        "reason": "no_access"
    }


    if not user_id or not group_id:

        state["can_buy_again"] = False
        state["reason"] = "missing_user_or_group"
        return state


    user_expired_explicitly = False


    def mark_active(access_source, reason):

        state["has_active_access"] = True
        state["access_source"] = access_source
        state["subscription_status"] = "active"
        state["can_buy_again"] = False
        state["can_recover_link"] = True
        state["can_renew"] = False
        state["reason"] = reason


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       COALESCE(is_free_group, FALSE)
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))
            group_row = cur.fetchone()


            if not group_row:

                state["can_buy_again"] = False
                state["reason"] = "group_not_found"
                return state


            state["group_name"] = group_row[1]
            state["telegram_group_id"] = group_row[2]
            state["is_free_group"] = bool(group_row[3])

    except Exception as e:

        print("get_user_group_access_state_group_error:", str(e)[:200])
        state["can_buy_again"] = False
        state["reason"] = "group_lookup_error"
        return state


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT expiration,
                       COALESCE(subscription_active, FALSE),
                       last_invite_link,
                       created_at
                FROM users
                WHERE user_id=%s
                AND group_id=%s
                LIMIT 1

            """, (
                user_id,
                group_id
            ))
            user_row = cur.fetchone()


            if user_row:

                expiration, subscription_active, _last_invite_link, _created_at = user_row
                state["has_user_access_record"] = True
                state["expires_at"] = expiration


                if subscription_active and (expiration is None or expiration > datetime.now()):

                    mark_active("unknown", "active_access")

                elif expiration and expiration <= datetime.now():

                    user_expired_explicitly = True

                    state["subscription_status"] = "expired"
                    state["can_buy_again"] = True
                    state["can_renew"] = True
                    state["reason"] = "expired_access"

                elif subscription_active:

                    state["subscription_status"] = "expired"
                    state["can_buy_again"] = True
                    state["can_renew"] = True
                    state["reason"] = "expired_access"


                if (
                    state["is_free_group"]
                    and not state["has_active_access"]
                    and not user_expired_explicitly
                ):

                    mark_active("free", "active_free_access")

    except Exception as e:

        print("get_user_group_access_state_user_error:", str(e)[:200])


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT provider,
                       status,
                       created_at
                FROM payment_transactions
                WHERE user_id=%s
                AND group_id=%s
                ORDER BY updated_at DESC NULLS LAST,
                         created_at DESC
                LIMIT 1

            """, (
                user_id,
                group_id
            ))
            transaction_row = cur.fetchone()


            if transaction_row:

                state["last_payment_provider"] = transaction_row[0]
                state["last_payment_status"] = (transaction_row[1] or "").lower()
                state["last_payment_created_at"] = transaction_row[2]

                if state["last_payment_status"] in PENDING_PAYMENT_STATUSES and not state["has_active_access"]:

                    state["subscription_status"] = "pending"
                    state["can_buy_again"] = False
                    state["can_renew"] = False
                    state["reason"] = "payment_pending"

    except Exception as e:

        print("get_user_group_access_state_transaction_error:", str(e)[:200])


    try:

        with conn.cursor() as cur:

            if not state["last_payment_status"]:

                cur.execute("""

                    SELECT status,
                           payment_date
                    FROM payments
                    WHERE user_id=%s
                    AND group_id=%s
                    ORDER BY payment_date DESC
                    LIMIT 1

                """, (
                    user_id,
                    group_id
                ))
                payment_row = cur.fetchone()


                if payment_row:

                    state["last_payment_provider"] = "stripe"
                    state["last_payment_status"] = (payment_row[0] or "").lower()
                    state["last_payment_created_at"] = payment_row[1]

    except Exception as e:

        print("get_user_group_access_state_payment_error:", str(e)[:200])


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM invite_links
                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                )
                AND COALESCE(is_active, TRUE)=TRUE
                LIMIT 1

            """, (
                user_id,
                group_id,
                state["telegram_group_id"]
            ))
            state["has_active_invite_link"] = cur.fetchone() is not None

            if (
                state["has_active_invite_link"]
                and not state["has_active_access"]
                and not user_expired_explicitly
                and state["subscription_status"] != "pending"
            ):

                mark_active("free" if state["is_free_group"] else "unknown", "active_invite_link")

            elif state["has_active_invite_link"]:

                state["can_recover_link"] = True

    except Exception as e:

        print("get_user_group_access_state_invite_link_error:", str(e)[:200])


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM group_user_promo_redemptions
                WHERE user_id=%s
                AND group_id=%s
                AND (
                    expiration IS NULL
                    OR expiration > NOW()
                )
                LIMIT 1

            """, (
                user_id,
                group_id
            ))
            state["has_active_code_access"] = cur.fetchone() is not None


            if state["has_active_code_access"]:

                mark_active("code", "active_code_access")

    except Exception as e:

        print("get_user_group_access_state_code_error:", str(e)[:200])


    if state["has_active_access"]:

        if state["has_active_code_access"]:

            state["access_source"] = "code"

        elif state["last_payment_status"] in ACTIVE_PAYMENT_STATUSES:

            state["access_source"] = "paid"

        elif state["is_free_group"] and (state["has_user_access_record"] or state["has_active_invite_link"]):

            state["access_source"] = "free"

        elif state["access_source"] == "unknown":

            state["access_source"] = "manual"


    elif (
        state["last_payment_status"] in ACTIVE_PAYMENT_STATUSES
        and not user_expired_explicitly
    ):

        state["paid_without_access_record"] = True
        state["can_buy_again"] = False
        state["can_renew"] = False
        state["subscription_status"] = "paid_without_access_record"
        state["reason"] = "paid_without_access_record"


    return state


def should_block_new_group_purchase(access_state):

    if not access_state:
        return False

    return (
        access_state.get("has_active_access") is True
        or access_state.get("subscription_status") == "pending"
        or access_state.get("reason") == "paid_without_access_record"
    )


def log_purchase_blocked_existing_access(user_id, group_id, provider="unknown", event_type="purchase_blocked_existing_access", access_state=None):

    access_state = access_state or {}

    log_event(
        event_type,
        category="payment" if event_type != "free_access_blocked_existing_access" else "access",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Se bloqueó un nuevo acceso/pago porque el usuario ya tiene acceso o un pago pendiente.",
        metadata={
            "provider": provider,
            "subscription_status": access_state.get("subscription_status"),
            "last_payment_status": access_state.get("last_payment_status"),
            "access_source": access_state.get("access_source"),
            "has_active_invite_link": access_state.get("has_active_invite_link"),
            "has_active_code_access": access_state.get("has_active_code_access"),
            "paid_without_access_record": access_state.get("paid_without_access_record"),
            "reason": access_state.get("reason")
        }
    )

    log_user_event_by_ids(
        user_id,
        event_type,
        event_key=f"{provider}_{group_id}",
        group_id=group_id,
        payment_provider=provider,
        payment_scope="group",
        metadata={
            "subscription_status": access_state.get("subscription_status"),
            "last_payment_status": access_state.get("last_payment_status"),
            "last_payment_provider": access_state.get("last_payment_provider"),
            "access_source": access_state.get("access_source"),
            "has_active_invite_link": access_state.get("has_active_invite_link"),
            "reason": access_state.get("reason")
        }
    )


def build_existing_access_api_response(access_state):

    if access_state.get("subscription_status") == "pending":

        return {
            "error": "Tienes un pago pendiente para esta comunidad. Espera la confirmación del proveedor o contacta soporte.",
            "reason": "payment_pending",
            "subscription_status": "pending"
        }

    if access_state.get("reason") == "paid_without_access_record":

        return {
            "error": "Encontré un pago confirmado para esta comunidad, pero no puedo reconstruir el acceso automáticamente. Abre soporte o revisa Mis suscripciones antes de crear otro pago.",
            "reason": "paid_without_access_record",
            "subscription_status": "paid_without_access_record"
        }

    return {
        "error": "Ya tienes acceso activo a esta comunidad. Puedes recuperar tu enlace desde Mis suscripciones.",
        "reason": "active_access",
        "subscription_status": access_state.get("subscription_status"),
        "can_recover_link": access_state.get("can_recover_link")
    }


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
