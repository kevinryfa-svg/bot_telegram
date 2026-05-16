from db import conn


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
