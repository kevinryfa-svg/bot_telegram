import json
import time

from datetime import datetime, timedelta

from audit_log_service import log_event
from bot_config import ADMIN_ID, TOKEN
from db import conn
from guardian_service import send_guardian_event_log_sync
from group_service import format_community_kind, normalize_community_type
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link
)
from i18n_service import load_user_language
from notification_service import notify_super_admins, send_telegram_message
from payment_incident_service import (
    INCIDENT_PLAN_MISSING,
    INCIDENT_STORAGE_FAILED,
    report_payment_incident,
    resolve_incidents_for
)
from purchase_message_service import build_buyer_message
from rbac_helpers import get_group_owner_user_id, is_user_group_owner
from user_activity_logger import log_user_event_by_ids


ACTIVE_PAYMENT_STATUSES = ("paid", "completed")
PENDING_PAYMENT_STATUSES = ("pending", "confirming", "manual_review")
FAILED_PAYMENT_STATUSES = ("failed", "cancelled", "expired", "refunded")
PENDING_PAYMENT_STALE_AFTER = timedelta(hours=2)
PAYMENT_URL_METADATA_KEYS = (
    "checkout_url",
    "approval_url",
    "payment_url",
    "hosted_url"
)
_TABLE_COLUMN_CACHE = {}


def table_has_column(table_name, column_name):

    cache_key = (table_name, column_name)


    if cache_key in _TABLE_COLUMN_CACHE:

        return _TABLE_COLUMN_CACHE[cache_key]


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = ANY (current_schemas(FALSE))
                AND table_name=%s
                AND column_name=%s
                LIMIT 1

            """, (
                table_name,
                column_name
            ))

            exists = cur.fetchone() is not None

        _TABLE_COLUMN_CACHE[cache_key] = exists

        return exists

    except Exception as e:

        print("table_has_column_error:", str(e)[:200])
        _TABLE_COLUMN_CACHE[cache_key] = False

        return False


def is_url(value):

    return isinstance(value, str) and value.startswith(("http://", "https://"))


def normalize_metadata_dict(metadata):

    if not metadata:

        return {}


    if isinstance(metadata, dict):

        return metadata


    if isinstance(metadata, str):

        try:

            parsed = json.loads(metadata)

            return parsed if isinstance(parsed, dict) else {}

        except Exception:

            return {}


    return {}


def extract_payment_checkout_url(*sources):

    for source in sources:

        metadata = normalize_metadata_dict(source)

        for key in PAYMENT_URL_METADATA_KEYS:

            value = metadata.get(key)

            if is_url(value):

                return value


    for source in sources:

        if is_url(source):

            return source


    return None


def is_pending_payment_stale(created_at, updated_at):

    timestamp = updated_at or created_at


    if not timestamp:

        return False


    try:

        now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()

        return now - timestamp > PENDING_PAYMENT_STALE_AFTER

    except Exception:

        return False


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
        "community_type": "group",
        "is_free_group": False,
        "has_active_access": False,
        "is_group_owner": False,
        "access_source": "unknown",
        "subscription_status": "none",
        "expires_at": None,
        "last_payment_status": None,
        "last_payment_provider": None,
        "last_payment_created_at": None,
        "pending_payment_created_at": None,
        "pending_payment_updated_at": None,
        "pending_payment_checkout_url": None,
        "pending_payment_can_resume": False,
        "pending_payment_is_stale": False,
        "pending_payment_provider": None,
        "pending_payment_transaction_id": None,
        "has_active_invite_link": False,
        "has_active_code_access": False,
        "has_user_access_record": False,
        "paid_without_access_record": False,
        "ignored_pending_payment": False,
        "ignored_pending_provider": None,
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
    latest_active_payment_status = None
    latest_active_payment_provider = None
    latest_pending_payment_status = None
    latest_pending_payment_provider = None
    latest_pending_payment_is_stale = False


    def mark_active(access_source, reason):

        state["has_active_access"] = True
        state["access_source"] = access_source
        state["subscription_status"] = "active"
        state["can_buy_again"] = False
        state["can_recover_link"] = True
        state["can_renew"] = False
        state["reason"] = reason


    def mark_owner_access():

        state["is_group_owner"] = True
        state["has_active_access"] = True
        state["access_source"] = "owner"
        state["subscription_status"] = "active"
        state["can_buy_again"] = False
        state["can_recover_link"] = False
        state["can_renew"] = False
        state["reason"] = "owner_access"


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       COALESCE(is_free_group, FALSE),
                       COALESCE(community_type, 'group')
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
            state["community_type"] = normalize_community_type(group_row[4])


            if is_user_group_owner(user_id, group_id):

                mark_owner_access()

    except Exception as e:

        print("get_user_group_access_state_group_error:", str(e)[:200])
        state["can_buy_again"] = False
        state["reason"] = "group_lookup_error"
        return state


    if state["is_group_owner"]:

        return state


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT expiration,
                       COALESCE(subscription_active, FALSE),
                       last_invite_link
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

                expiration, subscription_active, _last_invite_link = user_row
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

            cur.execute("""

                SELECT provider,
                       status
                FROM payment_transactions
                WHERE user_id=%s
                AND group_id=%s
                AND LOWER(COALESCE(status, '')) = ANY(%s)
                ORDER BY updated_at DESC NULLS LAST,
                         created_at DESC
                LIMIT 1

            """, (
                user_id,
                group_id,
                list(ACTIVE_PAYMENT_STATUSES)
            ))
            active_transaction_row = cur.fetchone()


            if active_transaction_row:

                latest_active_payment_provider = active_transaction_row[0]
                latest_active_payment_status = (active_transaction_row[1] or "").lower()


            cur.execute("""

                SELECT id,
                       provider,
                       status,
                       created_at,
                       updated_at,
                       external_checkout_id,
                       external_payment_id,
                       metadata_json,
                       metadata
                FROM payment_transactions
                WHERE user_id=%s
                AND group_id=%s
                AND LOWER(COALESCE(status, '')) = ANY(%s)
                ORDER BY updated_at DESC NULLS LAST,
                         created_at DESC
                LIMIT 1

            """, (
                user_id,
                group_id,
                list(PENDING_PAYMENT_STATUSES)
            ))
            pending_transaction_row = cur.fetchone()


            if pending_transaction_row:

                (
                    transaction_id,
                    provider,
                    status,
                    created_at,
                    updated_at,
                    external_checkout_id,
                    external_payment_id,
                    metadata_json,
                    metadata
                ) = pending_transaction_row
                latest_pending_payment_provider = provider
                latest_pending_payment_status = (status or "").lower()
                latest_pending_payment_is_stale = is_pending_payment_stale(
                    created_at,
                    updated_at
                )

                state["pending_payment_transaction_id"] = transaction_id
                state["pending_payment_provider"] = provider
                state["pending_payment_created_at"] = created_at
                state["pending_payment_updated_at"] = updated_at
                state["pending_payment_checkout_url"] = extract_payment_checkout_url(
                    metadata_json,
                    metadata,
                    external_checkout_id,
                    external_payment_id
                )
                state["pending_payment_can_resume"] = bool(state["pending_payment_checkout_url"])
                state["pending_payment_is_stale"] = latest_pending_payment_is_stale

    except Exception as e:

        print("get_user_group_access_state_transaction_error:", str(e)[:200])


    try:

        if not table_has_column("payments", "status"):

            raise LookupError("payments.status column unavailable")


        with conn.cursor() as cur:

            cur.execute("""

                SELECT status,
                       payment_date
                FROM payments
                WHERE user_id=%s
                AND group_id=%s
                AND LOWER(COALESCE(status, '')) = ANY(%s)
                ORDER BY payment_date DESC
                LIMIT 1

            """, (
                user_id,
                group_id,
                list(ACTIVE_PAYMENT_STATUSES)
            ))
            active_payment_row = cur.fetchone()


            if active_payment_row:

                latest_active_payment_provider = "stripe"
                latest_active_payment_status = (active_payment_row[0] or "").lower()


            cur.execute("""

                SELECT status,
                       payment_date
                FROM payments
                WHERE user_id=%s
                AND group_id=%s
                AND LOWER(COALESCE(status, '')) = ANY(%s)
                ORDER BY payment_date DESC
                LIMIT 1

            """, (
                user_id,
                group_id,
                list(PENDING_PAYMENT_STATUSES)
            ))
            pending_payment_row = cur.fetchone()


            if pending_payment_row and not latest_pending_payment_status:

                latest_pending_payment_provider = "stripe"
                latest_pending_payment_status = (pending_payment_row[0] or "").lower()
                latest_pending_payment_is_stale = is_pending_payment_stale(
                    pending_payment_row[1],
                    pending_payment_row[1]
                )
                state["pending_payment_provider"] = "stripe"
                state["pending_payment_created_at"] = pending_payment_row[1]
                state["pending_payment_updated_at"] = pending_payment_row[1]
                state["pending_payment_is_stale"] = latest_pending_payment_is_stale


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

    except LookupError:

        pass

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


            if state["has_active_code_access"] and not user_expired_explicitly:

                mark_active("code", "active_code_access")

    except Exception as e:

        print("get_user_group_access_state_code_error:", str(e)[:200])


    if user_expired_explicitly:

        state["has_active_access"] = False
        state["access_source"] = "unknown"
        state["subscription_status"] = "expired"
        state["paid_without_access_record"] = False
        state["can_buy_again"] = True
        state["can_recover_link"] = state["has_active_invite_link"]
        state["can_renew"] = True
        state["reason"] = "expired_access"

    elif state["has_active_access"]:

        if latest_pending_payment_status:

            state["ignored_pending_payment"] = True
            state["ignored_pending_provider"] = latest_pending_payment_provider

        if state["has_active_code_access"]:

            state["access_source"] = "code"

        elif latest_active_payment_status or state["last_payment_status"] in ACTIVE_PAYMENT_STATUSES:

            state["access_source"] = "paid"

        elif state["is_free_group"] and (state["has_user_access_record"] or state["has_active_invite_link"]):

            state["access_source"] = "free"

        elif state["access_source"] == "unknown":

            state["access_source"] = "manual"


    elif latest_active_payment_status or state["last_payment_status"] in ACTIVE_PAYMENT_STATUSES:

        state["paid_without_access_record"] = True
        state["can_buy_again"] = False
        state["can_renew"] = False
        state["subscription_status"] = "paid_without_access_record"
        state["reason"] = "paid_without_access_record"

    elif latest_pending_payment_status and not state["can_recover_link"]:

        state["last_payment_provider"] = latest_pending_payment_provider
        state["last_payment_status"] = latest_pending_payment_status

        if latest_pending_payment_is_stale:

            state["subscription_status"] = "none"
            state["can_buy_again"] = True
            state["can_renew"] = True
            state["reason"] = "payment_pending_stale"

        else:

            state["subscription_status"] = "pending"
            state["can_buy_again"] = False
            state["can_renew"] = False
            state["reason"] = "payment_pending"


    return state


def should_block_new_group_purchase(access_state):

    if not access_state:
        return False

    return (
        access_state.get("is_group_owner") is True
        or access_state.get("reason") == "owner_access"
        or access_state.get("has_active_access") is True
        or (
            access_state.get("subscription_status") == "pending"
            and access_state.get("pending_payment_is_stale") is not True
        )
        or access_state.get("reason") == "paid_without_access_record"
    )


def log_purchase_blocked_existing_access(user_id, group_id, provider="unknown", event_type="purchase_blocked_existing_access", access_state=None):

    access_state = access_state or {}
    actual_event_type = (
        "owner_self_purchase_blocked"
        if access_state.get("is_group_owner") or access_state.get("reason") == "owner_access"
        else event_type
    )

    log_event(
        actual_event_type,
        category="payment" if actual_event_type != "free_access_blocked_existing_access" else "access",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message=(
            "Se bloqueó autocobro del owner de la comunidad."
            if actual_event_type == "owner_self_purchase_blocked"
            else "Se bloqueó un nuevo acceso/pago porque el usuario ya tiene acceso o un pago pendiente."
        ),
        metadata={
            "provider": provider,
            "user_id": user_id,
            "subscription_status": access_state.get("subscription_status"),
            "last_payment_status": access_state.get("last_payment_status"),
            "access_source": access_state.get("access_source"),
            "is_group_owner": access_state.get("is_group_owner"),
            "has_active_invite_link": access_state.get("has_active_invite_link"),
            "has_active_code_access": access_state.get("has_active_code_access"),
            "paid_without_access_record": access_state.get("paid_without_access_record"),
            "ignored_pending_payment": access_state.get("ignored_pending_payment"),
            "ignored_pending_provider": access_state.get("ignored_pending_provider"),
            "pending_payment_is_stale": access_state.get("pending_payment_is_stale"),
            "pending_payment_can_resume": access_state.get("pending_payment_can_resume"),
            "pending_payment_provider": access_state.get("pending_payment_provider"),
            "pending_payment_transaction_id": access_state.get("pending_payment_transaction_id"),
            "reason": access_state.get("reason")
        }
    )

    log_user_event_by_ids(
        user_id,
        actual_event_type,
        event_key=f"{provider}_{group_id}",
        group_id=group_id,
        payment_provider=provider,
        payment_scope="group",
        metadata={
            "provider": provider,
            "subscription_status": access_state.get("subscription_status"),
            "last_payment_status": access_state.get("last_payment_status"),
            "last_payment_provider": access_state.get("last_payment_provider"),
            "access_source": access_state.get("access_source"),
            "is_group_owner": access_state.get("is_group_owner"),
            "has_active_invite_link": access_state.get("has_active_invite_link"),
            "ignored_pending_payment": access_state.get("ignored_pending_payment"),
            "ignored_pending_provider": access_state.get("ignored_pending_provider"),
            "pending_payment_is_stale": access_state.get("pending_payment_is_stale"),
            "pending_payment_can_resume": access_state.get("pending_payment_can_resume"),
            "pending_payment_provider": access_state.get("pending_payment_provider"),
            "reason": access_state.get("reason")
        }
    )


def build_existing_access_api_response(access_state):

    if access_state.get("is_group_owner") or access_state.get("reason") == "owner_access":

        return {
            "error": "Eres el propietario de esta comunidad. No necesitas comprar acceso.",
            "reason": "owner_access"
        }


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
                   g.name,
                   COALESCE(g.community_type, 'group')
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
        "group_name": row[7],
        "community_type": normalize_community_type(row[8])
    }


# El techo de lo que este sistema sabe ENTREGAR. Un plan de más días que esto
# no se puede convertir en acceso: calculate_group_access_expiration se niega,
# el pago queda cobrado y sin entregar, y solo lo salva el botón de reparación
# del propietario. Vive aquí, junto a la función que decide el acceso, porque
# quien ofrezca un plan tiene que preguntar por el MISMO número: ofrecer algo
# que el cobro va a rechazar es la peor combinación posible.
#
# El 0 es aparte: significa acceso permanente y sí se puede entregar
# (expiration = None).
MAX_PLAN_DURATION_DAYS = 3650


def calculate_group_access_expiration(duration_days):

    if duration_days is None or duration_days == 0:

        return None


    duration_value = int(duration_days)


    if duration_value < 1 or duration_value > MAX_PLAN_DURATION_DAYS:

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

        # Antes esto se quedaba en una línea del registro: el comprador pagaba
        # y no recibía nada, y el proveedor reintentaba un webhook que no podía
        # salir bien nunca.
        report_payment_incident(
            INCIDENT_PLAN_MISSING,
            user_id,
            group_id,
            provider=provider,
            external_payment_id=external_payment_id,
            transaction_id=transaction_id,
            detail=f"plan_id={plan_id}"
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
    community_type = plan.get("community_type") or "group"
    community_kind = format_community_kind(community_type)
    plan_name = plan.get("plan_name") or "Plan"
    payment_reference = f"{provider}:{external_payment_id or external_checkout_id or transaction_id}"


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO users
                (
                    user_id,
                    group_id,
                    expiration,
                    subscription_active
                )
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (user_id, group_id)
                DO UPDATE SET
                    expiration=EXCLUDED.expiration,
                    subscription_active=TRUE

            """, (
                user_id,
                group_id,
                expiration
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
            message="Pago confirmado pero falló el guardado del acceso local.",
            metadata={
                "provider": provider,
                "transaction_id": transaction_id,
                "plan_id": plan_id,
                "error": str(e)
            }
        )

        report_payment_incident(
            INCIDENT_STORAGE_FAILED,
            user_id,
            group_id,
            provider=provider,
            external_payment_id=external_payment_id,
            transaction_id=transaction_id,
            detail=str(e)
        )

        return {
            "ok": False,
            "reason": "storage_failed"
        }


    # El acceso ya está guardado. Si había una incidencia abierta por un intento
    # anterior —el reintento del proveedor es justo lo que salva un
    # storage_failed— se cierra aquí, para no perseguir un problema resuelto.
    resolve_incidents_for(user_id, group_id)


    # REFERIDOS: si este alta venía de la recomendación de un socio, los dos
    # cobran sus días aquí — cuando hay pago, no cuando hubo clic. Es
    # idempotente (el estado 'pending' es la puerta), así que el reintento
    # de un webhook no regala días dos veces. Y nunca puede tumbar la
    # entrega del acceso: eso ya está guardado más arriba.
    try:

        from referral_service import convert_referral, notify_referral_conversion

        conversion = convert_referral(user_id, group_id)

        if conversion:

            notify_referral_conversion(TOKEN, conversion, group_name)

    except Exception as e:

        print("Referidos: error al convertir tras el pago:", str(e)[:200])


    # 24 h por defecto (ACCESS_LINK_EXPIRE_SECONDS) en vez de 180 s: el
    # enlace es de un solo uso y al entrar se comprueba el acceso, así que
    # los tres minutos solo dejaban fuera a clientes que ya habían pagado.
    max_expire = int(time.time()) + max(ACCESS_LINK_EXPIRE_SECONDS, 60)

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
        member_limit=1,
        community_type=community_type
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
            message=f"Pago confirmado pero no se pudo crear invite link para {community_kind}.",
            metadata={
                "provider": provider,
                "transaction_id": transaction_id,
                "plan_id": plan_id,
                "community_type": community_type,
                # Se llamaba "user_message" y nunca se le enviaba a ningún
                # usuario: es el diagnóstico para quien lea el registro. El
                # comprador recibe el mensaje de purchase_message_service.
                "diagnostico": (
                    f"No se pudo crear el enlace de invitación del {community_kind}. "
                    "Lo habitual es que el bot haya perdido el permiso de invitar."
                )
            }
        )

        log_event(
            "payment_access_recorded_invite_link_pending",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Pago confirmado con acceso local activo, pero sin invite link de Telegram.",
            metadata={
                "provider": provider,
                "transaction_id": transaction_id,
                "plan_id": plan_id,
                "external_payment_id": external_payment_id,
                "external_checkout_id": external_checkout_id,
                "access_recorded": True,
                "invite_link_ok": False
            }
        )

        send_guardian_event_log_sync(
            group_id,
            "guardian_payment_invite_link_failed",
            "Pago confirmado con acceso local activo, pero falló la creación del invite link.",
            telegram_group_id=telegram_group_id,
            severity="warning",
            actor_user_id=user_id,
            target_user_id=user_id,
            metadata={
                "provider": provider,
                "user_id": user_id,
                "plan_id": plan_id,
                "plan_name": plan_name,
                "expiration": expiration,
                "transaction_id": str(transaction_id or "")[:16],
                "access_recorded": True,
                "invite_link_ok": False
            }
        )

        # El acceso ya está guardado (access_recorded), pero aquí no se le
        # enviaba NADA al comprador: pagaba con PayPal, Revolut, ChangeNOW o
        # Guardarian y recibía silencio. El botón de pedir el enlace funciona
        # justo porque el acceso existe.
        texto_pendiente, teclado_pendiente = build_buyer_message(
            group_name=group_name,
            plan_name=plan_name,
            amount_total=amount,
            currency=currency,
            expiration=expiration,
            expire_seconds=None,
            link=None,
            telegram_group_id=telegram_group_id,
            language=load_user_language(user_id)
        )

        send_telegram_message(
            TOKEN,
            user_id,
            texto_pendiente,
            reply_markup=teclado_pendiente.to_dict()
        )

        return {
            "ok": True,
            "reason": "invite_link_failed",
            "invite_link_ok": False,
            "access_recorded": True,
            "link": None,
            "expiration": expiration,
            "telegram_group_id": telegram_group_id,
            "plan_name": plan_name,
            "group_name": group_name
        }


    link_saved = True

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET last_invite_link=%s,
                    subscription_active=TRUE
                WHERE user_id=%s
                AND group_id=%s

            """, (
                link,
                user_id,
                group_id
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
        link_saved = False

        log_event(
            "payment_invite_link_storage_error",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Pago confirmado y acceso local guardado, pero falló el guardado del invite link.",
            metadata={
                "provider": provider,
                "transaction_id": transaction_id,
                "plan_id": plan_id,
                "error": str(e)
            }
        )


    amount_text = format_payment_amount(amount, currency)

    # Antes era "🔗 Tu acceso VIP:" y el enlace pelado, igual que en Stripe. Al
    # compartir el constructor, quien paga con PayPal, Revolut, ChangeNOW o
    # Guardarian recibe exactamente lo mismo que quien paga con tarjeta.
    texto_comprador, teclado_comprador = build_buyer_message(
        group_name=group_name,
        plan_name=plan_name,
        amount_total=amount,
        currency=currency,
        expiration=expiration,
        expire_seconds=expire_seconds,
        link=link,
        telegram_group_id=telegram_group_id,
        language=load_user_language(user_id)
    )

    send_telegram_message(
        TOKEN,
        user_id,
        texto_comprador,
        reply_markup=teclado_comprador.to_dict()
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
            f"{format_community_kind(community_type).capitalize()}: {group_name}\n"
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
            "expiration": expiration,
            "invite_link_ok": bool(link),
            "invite_link_saved": link_saved
        }
    )

    send_guardian_event_log_sync(
        group_id,
        "guardian_payment_confirmed",
        "Pago confirmado y acceso local activado.",
        telegram_group_id=telegram_group_id,
        severity="info",
        actor_user_id=user_id,
        target_user_id=user_id,
        metadata={
            "provider": provider,
            "user_id": user_id,
            "plan_id": plan_id,
            "plan_name": plan_name,
            "amount": amount,
            "currency": currency,
            "expiration": expiration,
            "transaction_id": str(transaction_id or "")[:16],
            "invite_link_ok": bool(link),
            "invite_link_saved": link_saved
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
            "external_checkout_id": external_checkout_id,
            "invite_link_saved": link_saved
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
        "group_name": group_name,
        "invite_link_ok": True,
        "invite_link_saved": link_saved,
        "access_recorded": True
    }
