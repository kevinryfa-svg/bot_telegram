from datetime import datetime, timedelta

from db import conn


# =========================
# USER SERVICE — GET USER SUBSCRIPTION
# =========================

def get_user_subscription(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id,
                       group_id,
                       expiration

                FROM users

                WHERE user_id=%s
                AND group_id=%s

                LIMIT 1

            """, (

                user_id,
                group_id

            ))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo suscripción usuario/grupo:",
            e
        )

        return None


# =========================
# USER SERVICE — CHECK ACTIVE
# =========================

def is_subscription_active(expiration):

    if expiration is None:

        return True


    return expiration > datetime.now()



def user_has_active_subscription(user_id, group_id):

    row = get_user_subscription(
        user_id,
        group_id
    )


    if not row:

        return False


    expiration = row[2]

    return is_subscription_active(
        expiration
    )


# =========================
# USER SERVICE — UPSERT SUBSCRIPTION
# =========================

def upsert_user_subscription(user_id, group_id, expiration, username=None, first_name=None):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO users
                (user_id, group_id, username, first_name, expiration)

                VALUES (%s, %s, %s, %s, %s)

                ON CONFLICT (user_id, group_id)
                DO UPDATE SET

                    username=EXCLUDED.username,
                    first_name=EXCLUDED.first_name,
                    expiration=EXCLUDED.expiration

            """, (

                user_id,
                group_id,
                username,
                first_name,
                expiration

            ))

            conn.commit()

            return True

    except Exception as e:

        conn.rollback()

        print(
            "Error guardando suscripción usuario/grupo:",
            e
        )

        return False


# =========================
# USER SERVICE — DELETE SUBSCRIPTION
# =========================

def delete_user_subscription(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM users
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
            "Error borrando suscripción usuario/grupo:",
            e
        )

        return False


# =========================
# USER SERVICE — LIST ACTIVE USERS
# =========================

def list_active_users(group_id=None):

    try:

        with conn.cursor() as cur:

            if group_id is None:

                cur.execute("""

                    SELECT user_id,
                           group_id,
                           username,
                           first_name,
                           expiration

                    FROM users

                    WHERE expiration IS NULL
                    OR expiration > NOW()

                    ORDER BY expiration DESC NULLS LAST

                """)

            else:

                cur.execute("""

                    SELECT user_id,
                           group_id,
                           username,
                           first_name,
                           expiration

                    FROM users

                    WHERE group_id=%s
                    AND (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    ORDER BY expiration DESC NULLS LAST

                """, (group_id,))


            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando usuarios activos:",
            e
        )

        return []


# =========================
# USER SERVICE — EXPIRATIONS
# =========================

def list_expired_users():

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id,
                       group_id,
                       expiration

                FROM users

                WHERE expiration IS NOT NULL
                AND expiration < NOW()

            """)

            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando usuarios expirados:",
            e
        )

        return []
