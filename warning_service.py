from db import conn


# =========================
# WARNING SERVICE — GET WARNINGS
# =========================

def get_user_warnings(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT warnings
                FROM user_warnings
                WHERE user_id=%s
                AND group_id=%s

                LIMIT 1

            """, (

                user_id,
                group_id

            ))

            row = cur.fetchone()


            if not row:

                return 0


            return row[0]

    except Exception as e:

        print(
            "Error obteniendo warnings:",
            e
        )

        return 0


# =========================
# WARNING SERVICE — ADD WARNING
# =========================

def add_user_warning(user_id, group_id):

    current = get_user_warnings(
        user_id,
        group_id
    )

    new_total = current + 1


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO user_warnings
                (user_id, group_id, warnings)

                VALUES (%s, %s, %s)

                ON CONFLICT (user_id, group_id)
                DO UPDATE SET
                    warnings=EXCLUDED.warnings

            """, (

                user_id,
                group_id,
                new_total

            ))

            conn.commit()

            return new_total

    except Exception as e:

        conn.rollback()

        print(
            "Error añadiendo warning:",
            e
        )

        return current


# =========================
# WARNING SERVICE — RESET WARNINGS
# =========================

def reset_user_warnings(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM user_warnings
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                group_id

            ))

            affected = cur.rowcount

            conn.commit()

            return affected > 0

    except Exception as e:

        conn.rollback()

        print(
            "Error reseteando warnings:",
            e
        )

        return False


# =========================
# WARNING SERVICE — LIST GROUP WARNINGS
# =========================

def list_group_warnings(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id,
                       warnings

                FROM user_warnings

                WHERE group_id=%s

                ORDER BY warnings DESC

            """, (group_id,))

            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando warnings grupo:",
            e
        )

        return []
