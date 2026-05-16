from db import conn


# =========================
# AUDIT LOG — CREATE LOG
# =========================

def create_audit_log(action, admin_user_id=None, target_user_id=None, group_id=None, details=None):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO audit_logs
                (action, admin_user_id, target_user_id, group_id, details)

                VALUES (%s, %s, %s, %s, %s)

            """, (

                action,
                admin_user_id,
                target_user_id,
                group_id,
                details

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
# =========================

def list_recent_audit_logs(limit=50, group_id=None):

    try:

        with conn.cursor() as cur:

            if group_id is None:

                cur.execute("""

                    SELECT created_at,
                           action,
                           admin_user_id,
                           target_user_id,
                           group_id,
                           details

                    FROM audit_logs

                    ORDER BY created_at DESC

                    LIMIT %s

                """, (limit,))

            else:

                cur.execute("""

                    SELECT created_at,
                           action,
                           admin_user_id,
                           target_user_id,
                           group_id,
                           details

                    FROM audit_logs

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
