from db import conn


# =========================
# WARNING SERVICE — GET WARNINGS
# =========================

def get_user_warnings(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT warnings
                FROM link_warnings
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

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO link_warnings
                (user_id, group_id, warnings)

                VALUES (%s, %s, 1)

                ON CONFLICT (user_id, group_id)
                DO UPDATE SET
                    warnings=link_warnings.warnings + 1

                RETURNING warnings

            """, (

                user_id,
                group_id

            ))

            new_total = cur.fetchone()[0]

            conn.commit()

            return new_total

    except Exception as e:

        conn.rollback()

        print(
            "Error añadiendo warning:",
            e
        )

        return get_user_warnings(
            user_id,
            group_id
        )


# =========================
# WARNING SERVICE — RESET WARNINGS
# =========================

def reset_user_warnings(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO link_warnings
                (user_id, group_id, warnings)

                VALUES (%s, %s, 0)

                ON CONFLICT (user_id, group_id)
                DO UPDATE SET warnings=0

            """, (

                user_id,
                group_id

            ))

            conn.commit()

            return True

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

                FROM link_warnings

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
