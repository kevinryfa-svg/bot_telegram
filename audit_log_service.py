import json
import os
import requests

from datetime import datetime, timedelta

from db import conn


BETA_MONITOR_EVENT_ALIASES = {
    "checkout_creation_error": "payment_failed",
    "payment_storage_error": "payment_failed",
    "payment_group_not_found": "payment_failed",
    "payment_plan_duration_invalid": "payment_failed",
    "payment_invite_link_error": "invite_link_failed",
    "free_access_invite_link_error": "invite_link_failed",
    "free_access_error": "invite_link_failed",
    "access_join_valid_link": "access_allowed",
    "access_allowed_active_payment_fallback": "access_allowed",
    "access_unauthorized": "unauthorized_access",
    "group_user_promo_redeemed": "group_code_redeemed",
    "group_registration_unauthorized": "bot_added_to_group",
    "bot_added_to_group_detected": "bot_added_to_group",
    "group_registration_leave_chat_success": "bot_removed_from_group"
}


BETA_MONITOR_EVENT_TYPES = {
    "telegram_handler_error",
    "payment_confirmed",
    "payment_failed",
    "invite_link_created",
    "invite_link_failed",
    "unauthorized_access",
    "access_allowed",
    "group_code_redeemed",
    "group_code_failed",
    "backup_message_failed",
    "backup_permission_error",
    "location_denied",
    "support_ticket_created",
    "bot_added_to_group",
    "bot_removed_from_group"
}


BETA_MONITOR_SECRET_KEYS = (
    "token",
    "secret",
    "stripe_secret",
    "webhook_secret",
    "owner_stripe_secret_key",
    "owner_stripe_webhook_secret",
    "invite_link",
    "link",
    "latitude",
    "longitude",
    "lat",
    "lon"
)


def is_beta_monitor_enabled():

    enabled = os.environ.get(
        "BETA_MONITOR_ENABLED",
        "true"
    ).lower()


    if enabled in ("0", "false", "no", "off"):

        return False


    raw_until = os.environ.get("BETA_MONITOR_UNTIL")


    if raw_until:

        try:

            until_date = datetime.strptime(
                raw_until,
                "%Y-%m-%d"
            ).date()

            if datetime.utcnow().date() > until_date:

                return False

        except Exception:

            pass


    return True


def normalize_beta_event_type(event_type):

    return BETA_MONITOR_EVENT_ALIASES.get(
        event_type,
        event_type
    )


def normalize_beta_severity(severity):

    if severity == "critical":

        return "critical"


    if severity in ("error", "warning"):

        return "warning"


    return "info"


def mask_sensitive_value(value):

    if value is None:

        return None


    text = str(value)


    if "t.me/" in text or "joinchat" in text or "+" in text[:10]:

        return f"{text[:12]}***"


    return text[:200]


def sanitize_beta_metadata(value):

    if isinstance(value, dict):

        safe = {}

        for key, item in value.items():

            key_text = str(key).lower()

            if any(secret_key in key_text for secret_key in BETA_MONITOR_SECRET_KEYS):

                safe[key] = "[redacted]"

            else:

                safe[key] = sanitize_beta_metadata(item)


        return safe


    if isinstance(value, list):

        return [
            sanitize_beta_metadata(item)
            for item in value
        ]


    return mask_sensitive_value(value)


def notify_beta_admin_if_needed(event_type, severity, message, metadata=None):

    if severity != "critical":

        return False


    token = os.environ.get("TOKEN")
    admin_id = os.environ.get("ADMIN_ID", "8761243211")


    if not token or not admin_id:

        return False


    try:

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": admin_id,
                "text": (
                    "🚨 Evento crítico beta\n\n"
                    f"Tipo: {event_type}\n"
                    f"Detalle: {mask_sensitive_value(message) or '-'}"
                )
            },
            timeout=10
        )

        return True

    except Exception as e:

        print("Error avisando monitor beta:", e)

        return False


def record_beta_event(
    event_type,
    severity="info",
    user_id=None,
    group_id=None,
    telegram_group_id=None,
    message=None,
    metadata=None
):

    if not is_beta_monitor_enabled():

        return False


    normalized_event_type = normalize_beta_event_type(event_type)
    normalized_severity = normalize_beta_severity(severity)


    if normalized_event_type not in BETA_MONITOR_EVENT_TYPES:

        return False


    safe_metadata = sanitize_beta_metadata(metadata or {})


    try:

        metadata_json = json.dumps(
            safe_metadata,
            default=str,
            ensure_ascii=False
        )


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO beta_monitor_events
                (
                    event_type,
                    severity,
                    user_id,
                    group_id,
                    telegram_group_id,
                    message,
                    metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)

            """, (
                normalized_event_type,
                normalized_severity,
                user_id,
                group_id,
                telegram_group_id,
                mask_sensitive_value(message),
                metadata_json
            ))

            conn.commit()


        notify_beta_admin_if_needed(
            normalized_event_type,
            normalized_severity,
            message,
            safe_metadata
        )

        return True

    except Exception as e:

        conn.rollback()

        print("Error creando beta monitor event:", event_type, e)

        return False


def list_beta_monitor_events(hours=24, severity=None, event_types=None, limit=50):

    try:

        with conn.cursor() as cur:

            params = [hours]
            filters = ["created_at >= NOW() - (%s || ' hours')::interval"]


            if severity:

                params.append(severity)
                filters.append("severity=%s")


            if event_types:

                params.append(event_types)
                filters.append("event_type = ANY(%s)")


            params.append(limit)

            cur.execute(f"""

                SELECT id,
                       created_at,
                       event_type,
                       severity,
                       user_id,
                       group_id,
                       telegram_group_id,
                       message,
                       resolved
                FROM beta_monitor_events
                WHERE {" AND ".join(filters)}
                ORDER BY created_at DESC
                LIMIT %s

            """, params)

            return cur.fetchall()

    except Exception as e:

        print("Error listando beta monitor events:", e)

        return []


def summarize_beta_monitor_events(hours=6):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT event_type, severity, COUNT(*)
                FROM beta_monitor_events
                WHERE created_at >= NOW() - (%s || ' hours')::interval
                GROUP BY event_type, severity
                ORDER BY severity DESC, event_type ASC

            """, (hours,))

            rows = cur.fetchall()


        totals = {
            "critical": 0,
            "warning": 0,
            "payment_confirmed": 0,
            "access_allowed": 0,
            "unauthorized_access": 0,
            "group_code_redeemed": 0,
            "backup_message_failed": 0,
            "support_ticket_created": 0
        }


        for event_type, severity, count in rows:

            if severity in totals:

                totals[severity] += count

            if event_type in totals:

                totals[event_type] += count


        lines = [
            f"📊 Resumen beta últimas {hours}h",
            "",
            f"Críticos: {totals['critical']}",
            f"Warnings: {totals['warning']}",
            f"Pagos confirmados: {totals['payment_confirmed']}",
            f"Accesos permitidos: {totals['access_allowed']}",
            f"Accesos bloqueados: {totals['unauthorized_access']}",
            f"Códigos canjeados: {totals['group_code_redeemed']}",
            f"Backups fallidos: {totals['backup_message_failed']}",
            f"Tickets soporte: {totals['support_ticket_created']}"
        ]


        return "\n".join(lines)

    except Exception as e:

        print("Error resumiendo beta monitor:", e)

        return "📊 Resumen beta\n\nNo se pudo cargar el resumen."


def mark_beta_monitor_events_resolved(hours=24):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE beta_monitor_events
                SET resolved=TRUE
                WHERE created_at >= NOW() - (%s || ' hours')::interval
                AND resolved=FALSE

            """, (hours,))

            affected = cur.rowcount
            conn.commit()

            return affected

    except Exception as e:

        conn.rollback()

        print("Error marcando eventos beta resueltos:", e)

        return 0


# =========================
# AUDIT LOG — CENTRAL EVENT
# =========================

def log_event(
    event_type,
    category="system",
    severity="info",
    message=None,
    scope="global",
    group_id=None,
    telegram_group_id=None,
    actor_user_id=None,
    target_user_id=None,
    metadata=None
):

    safe_metadata = metadata or {}


    try:

        metadata_json = json.dumps(
            safe_metadata,
            default=str,
            ensure_ascii=False
        )


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO audit_logs
                (
                    scope,
                    group_id,
                    telegram_group_id,
                    actor_user_id,
                    target_user_id,
                    event_type,
                    category,
                    severity,
                    message,
                    metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)

            """, (
                scope,
                group_id,
                telegram_group_id,
                actor_user_id,
                target_user_id,
                event_type,
                category,
                severity,
                message,
                metadata_json
            ))

            conn.commit()

            record_beta_event(
                event_type,
                severity=severity,
                user_id=actor_user_id or target_user_id,
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                message=message,
                metadata={
                    "category": category,
                    "scope": scope,
                    "actor_user_id": actor_user_id,
                    "target_user_id": target_user_id,
                    "metadata": safe_metadata
                }
            )

            return True

    except Exception as e:

        conn.rollback()

        print(
            "Error creando audit event:",
            event_type,
            e
        )

        return False


def list_recent_events(limit=50, group_ids=None):

    try:

        with conn.cursor() as cur:

            if group_ids is None:

                cur.execute("""

                    SELECT created_at,
                           event_type,
                           category,
                           severity,
                           group_id,
                           telegram_group_id,
                           actor_user_id,
                           target_user_id,
                           message
                    FROM audit_logs
                    ORDER BY created_at DESC
                    LIMIT %s

                """, (limit,))

            else:

                cur.execute("""

                    SELECT created_at,
                           event_type,
                           category,
                           severity,
                           group_id,
                           telegram_group_id,
                           actor_user_id,
                           target_user_id,
                           message
                    FROM audit_logs
                    WHERE group_id = ANY(%s)
                    ORDER BY created_at DESC
                    LIMIT %s

                """, (
                    group_ids,
                    limit
                ))


            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando audit events:",
            e
        )

        return []


# =========================
# AUDIT LOG — CREATE LOG
# Uses existing logs table from db.py.
# =========================

def create_audit_log(action, admin_user_id=None, target_user_id=None, group_id=None, details=None):

    detail_parts = []


    if admin_user_id is not None:

        detail_parts.append(
            f"admin_user_id={admin_user_id}"
        )


    if target_user_id is not None:

        detail_parts.append(
            f"target_user_id={target_user_id}"
        )


    if details:

        detail_parts.append(
            str(details)
        )


    details_text = " | ".join(detail_parts)


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO logs
                (user_id, group_id, action, details)

                VALUES (%s, %s, %s, %s)

            """, (

                target_user_id,
                group_id,
                action,
                details_text

            ))

            conn.commit()

            return True

    except Exception as e:

        conn.rollback()

        print(
            "Error creando audit log:",
            e
        )

        return False


# =========================
# AUDIT LOG — LIST RECENT LOGS
# Uses existing logs table from db.py.
# =========================

def list_recent_audit_logs(limit=50, group_id=None):

    try:

        with conn.cursor() as cur:

            if group_id is None:

                cur.execute("""

                    SELECT created_at,
                           action,
                           user_id,
                           group_id,
                           details

                    FROM logs

                    ORDER BY created_at DESC

                    LIMIT %s

                """, (limit,))

            else:

                cur.execute("""

                    SELECT created_at,
                           action,
                           user_id,
                           group_id,
                           details

                    FROM logs

                    WHERE group_id=%s

                    ORDER BY created_at DESC

                    LIMIT %s

                """, (

                    group_id,
                    limit

                ))


            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando audit logs:",
            e
        )

        return []
