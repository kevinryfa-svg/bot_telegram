import json
import re
from datetime import datetime

from db import conn


SENSITIVE_KEYWORDS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "client_secret",
    "webhook_secret",
    "authorization",
    "password",
    "wallet",
    "invite_link",
    "checkout_url",
    "payment_url",
    "url"
)


EVENT_GROUP_PATTERNS = (
    re.compile(r"(?:marketplace_group|marketplace_preview|marketplace_dynamic_preview|favorite_group|unfavorite_group|public_support_group)_(\d+)"),
    re.compile(r"(?:owner_group_payments|owner_group_subscriptions|owner_group_users|owner_group_logs_[a-z_]+|owner_group_payment_methods)_(\d+)"),
    re.compile(r"(?:guardarian_group_plan|revolut_group_plan|paypal_group_plan|changenow_group_plan)_(\d+)_(\d+)"),
    re.compile(r"^group_(\d+)$")
)


PAYMENT_PROVIDERS = ("stripe", "paypal", "revolut", "changenow", "guardarian")


def mask_sensitive_value(value):

    if value is None:
        return None

    text = str(value)

    if len(text) <= 8:
        return "***"

    return f"{text[:6]}***{text[-4:]}"


def sanitize_metadata(metadata):

    if not metadata:
        return {}

    if not isinstance(metadata, dict):
        return {"value": str(metadata)[:300]}

    sanitized = {}

    for key, value in metadata.items():
        key_text = str(key)
        lower_key = key_text.lower()

        if any(keyword in lower_key for keyword in SENSITIVE_KEYWORDS):
            sanitized[key_text] = mask_sensitive_value(value)
            continue

        if isinstance(value, dict):
            sanitized[key_text] = sanitize_metadata(value)
        elif isinstance(value, (list, tuple)):
            sanitized[key_text] = [
                sanitize_metadata(item) if isinstance(item, dict) else str(item)[:300]
                for item in value[:20]
            ]
        elif isinstance(value, (int, float, bool)) or value is None:
            sanitized[key_text] = value
        else:
            sanitized[key_text] = str(value)[:500]

    return sanitized


def infer_group_plan_provider(event_key=None, metadata=None):

    group_id = None
    plan_id = None
    provider = None
    payment_scope = None

    key = event_key or ""

    for pattern in EVENT_GROUP_PATTERNS:
        match = pattern.search(key)
        if match:
            group_id = int(match.group(1))
            if len(match.groups()) > 1 and match.group(2).isdigit():
                plan_id = int(match.group(2))
            break

    for candidate in PAYMENT_PROVIDERS:
        if candidate in key.lower():
            provider = candidate
            break

    if provider:
        payment_scope = "group" if group_id else "platform"

    if metadata:
        group_id = metadata.get("group_id") or group_id
        plan_id = metadata.get("plan_id") or plan_id
        provider = metadata.get("payment_provider") or metadata.get("provider") or provider
        payment_scope = metadata.get("payment_scope") or payment_scope

    return group_id, plan_id, provider, payment_scope


def get_update_user(update):

    user = getattr(update, "effective_user", None)

    if user:
        return user

    callback_query = getattr(update, "callback_query", None)

    if callback_query:
        return callback_query.from_user

    return None


def log_user_event(
    update,
    event_type,
    event_key=None,
    group_id=None,
    plan_id=None,
    payment_provider=None,
    payment_scope=None,
    metadata=None
):

    user = get_update_user(update)

    if not user:
        return

    inferred_group_id, inferred_plan_id, inferred_provider, inferred_scope = infer_group_plan_provider(
        event_key,
        metadata
    )

    log_user_event_by_ids(
        user_id=user.id,
        username=getattr(user, "username", None),
        first_name=getattr(user, "first_name", None),
        last_name=getattr(user, "last_name", None),
        event_type=event_type,
        event_key=event_key,
        group_id=group_id or inferred_group_id,
        plan_id=plan_id or inferred_plan_id,
        payment_provider=payment_provider or inferred_provider,
        payment_scope=payment_scope or inferred_scope,
        metadata=metadata
    )


def log_user_event_by_ids(
    user_id,
    event_type,
    event_key=None,
    username=None,
    first_name=None,
    last_name=None,
    group_id=None,
    plan_id=None,
    payment_provider=None,
    payment_scope=None,
    metadata=None
):

    if not user_id or not event_type:
        return

    safe_metadata = sanitize_metadata(metadata)

    try:
        with conn.cursor() as cur:
            cur.execute("""

                INSERT INTO bot_user_events
                (
                    user_id,
                    username,
                    first_name,
                    last_name,
                    event_type,
                    event_key,
                    group_id,
                    plan_id,
                    payment_provider,
                    payment_scope,
                    metadata_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)

            """, (
                user_id,
                username,
                first_name,
                last_name,
                event_type,
                event_key,
                group_id,
                plan_id,
                payment_provider,
                payment_scope,
                json.dumps(safe_metadata)
            ))
    except Exception as exc:
        print("user_activity_logger_error:", str(exc)[:200])


def fetch_tracking_overview():

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM bot_user_events WHERE event_type='start'")
            started_users = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT user_id) FROM bot_user_events WHERE created_at >= NOW() - INTERVAL '24 hours'")
            active_24h = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT user_id) FROM bot_user_events WHERE created_at >= NOW() - INTERVAL '7 days'")
            active_7d = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM bot_user_events WHERE created_at >= NOW() - INTERVAL '24 hours'")
            events_24h = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE event_type IN ('checkout_started', 'payment_created')
                AND created_at >= NOW() - INTERVAL '7 days'
            """)
            payments_started = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE event_type='payment_completed'
                AND created_at >= NOW() - INTERVAL '7 days'
            """)
            payments_completed = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE event_type='support_opened'
                AND created_at >= NOW() - INTERVAL '7 days'
            """)
            support_opened = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE event_type='survey_completed'
                AND created_at >= NOW() - INTERVAL '7 days'
            """)
            surveys_completed = cur.fetchone()[0]

            cur.execute("""
                SELECT event_key, COUNT(*)
                FROM bot_user_events
                WHERE event_key IS NOT NULL
                AND created_at >= NOW() - INTERVAL '7 days'
                GROUP BY event_key
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)
            top_events = cur.fetchall()

            cur.execute("""
                SELECT e.group_id, COALESCE(g.name, 'Grupo ' || e.group_id::text), COUNT(*)
                FROM bot_user_events e
                LEFT JOIN groups g ON g.id=e.group_id
                WHERE e.group_id IS NOT NULL
                AND e.created_at >= NOW() - INTERVAL '7 days'
                GROUP BY e.group_id, g.name
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)
            top_groups = cur.fetchall()

        return {
            "started_users": started_users,
            "active_24h": active_24h,
            "active_7d": active_7d,
            "events_24h": events_24h,
            "payments_started": payments_started,
            "payments_completed": payments_completed,
            "support_opened": support_opened,
            "surveys_completed": surveys_completed,
            "top_events": top_events,
            "top_groups": top_groups
        }
    except Exception as exc:
        print("user_tracking_overview_error:", str(exc)[:200])
        return {}


def fetch_recent_user_events(limit=20, event_type=None, user_id=None, group_id=None):

    params = []
    filters = []

    if event_type:
        filters.append("event_type=%s")
        params.append(event_type)

    if user_id:
        filters.append("user_id=%s")
        params.append(user_id)

    if group_id:
        filters.append("group_id=%s")
        params.append(group_id)

    where_sql = "WHERE " + " AND ".join(filters) if filters else ""
    params.append(limit)

    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT user_id,
                       COALESCE(username, ''),
                       COALESCE(first_name, ''),
                       event_type,
                       COALESCE(event_key, ''),
                       group_id,
                       plan_id,
                       COALESCE(payment_provider, ''),
                       created_at
                FROM bot_user_events
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
            """, tuple(params))
            return cur.fetchall()
    except Exception as exc:
        print("user_tracking_recent_error:", str(exc)[:200])
        return []


def fetch_user_activity_profile(search_text):

    value = (search_text or "").strip()

    if not value:
        return None

    params = []

    if value.startswith("@"):
        where_sql = "LOWER(username)=LOWER(%s)"
        params.append(value[1:])
    elif value.isdigit():
        where_sql = "user_id=%s"
        params.append(int(value))
    else:
        where_sql = "LOWER(username)=LOWER(%s)"
        params.append(value)

    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT user_id,
                       COALESCE(MAX(username), ''),
                       COALESCE(MAX(first_name), ''),
                       COALESCE(MAX(last_name), ''),
                       MIN(created_at),
                       MAX(created_at),
                       COUNT(*)
                FROM bot_user_events
                WHERE {where_sql}
                GROUP BY user_id
                ORDER BY MAX(created_at) DESC
                LIMIT 1
            """, tuple(params))
            profile = cur.fetchone()

            if not profile:
                return None

            user_id = profile[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE user_id=%s AND event_type IN ('checkout_started', 'payment_created')
            """, (user_id,))
            checkout_count = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE user_id=%s AND event_type='payment_completed'
            """, (user_id,))
            payment_count = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE user_id=%s AND event_type='payment_failed'
            """, (user_id,))
            payment_failed_count = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE user_id=%s AND event_type IN ('support_opened', 'support_message')
            """, (user_id,))
            support_count = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE user_id=%s AND event_type='survey_sent'
            """, (user_id,))
            survey_sent_count = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM bot_user_events
                WHERE user_id=%s AND event_type='survey_completed'
            """, (user_id,))
            survey_completed_count = cur.fetchone()[0]

            cur.execute("""
                SELECT DISTINCT e.group_id, COALESCE(g.name, 'Grupo ' || e.group_id::text)
                FROM bot_user_events e
                LEFT JOIN groups g ON g.id=e.group_id
                WHERE e.user_id=%s AND e.group_id IS NOT NULL
                ORDER BY e.group_id DESC
                LIMIT 12
            """, (user_id,))
            groups = cur.fetchall()

        return {
            "profile": profile,
            "checkout_count": checkout_count,
            "payment_count": payment_count,
            "payment_failed_count": payment_failed_count,
            "support_count": support_count,
            "survey_sent_count": survey_sent_count,
            "survey_completed_count": survey_completed_count,
            "groups": groups,
            "events": fetch_recent_user_events(limit=20, user_id=user_id)
        }
    except Exception as exc:
        print("user_tracking_profile_error:", str(exc)[:200])
        return None
