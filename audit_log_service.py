import json

from db import conn


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
