from datetime import datetime, timedelta

from db import conn


# =========================
# PAYMENT SERVICE — GET PLAN BY PRICE
# =========================

def get_active_plan_by_price(price_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       price_id,
                       duration_days,
                       amount,
                       currency,
                       group_id

                FROM plans

                WHERE price_id=%s
                AND group_id=%s
                AND is_active=TRUE

                LIMIT 1

            """, (

                price_id,
                group_id

            ))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo plan activo por price_id:",
            e
        )

        return None


# =========================
# PAYMENT SERVICE — CALCULATE EXPIRATION
# =========================

def calculate_expiration_from_duration(duration_days):

    if duration_days is None or duration_days == 0:

        return None


    duration_value = int(duration_days)


    if duration_value < 1440:

        return datetime.now() + timedelta(
            minutes=duration_value
        )


    return datetime.now() + timedelta(
        days=duration_value // 1440
    )


# =========================
# PAYMENT SERVICE — SAVE PAYMENT
# =========================

def save_payment(user_id, plan_name, group_id=None, amount=None, currency=None, stripe_session_id=None):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO payments
                (user_id, plan, group_id, amount, currency, stripe_session_id)

                VALUES (%s, %s, %s, %s, %s, %s)

            """, (

                user_id,
                plan_name,
                group_id,
                amount,
                currency,
                stripe_session_id

            ))

            conn.commit()

            return True

    except Exception as e:

        conn.rollback()

        print(
            "Error guardando pago:",
            e
        )

        return False


# =========================
# PAYMENT SERVICE — LIST PAYMENTS
# =========================

def list_recent_payments(limit=50, group_id=None):

    try:

        with conn.cursor() as cur:

            if group_id is None:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           group_id,
                           amount,
                           currency,
                           created_at

                    FROM payments

                    ORDER BY created_at DESC

                    LIMIT %s

                """, (limit,))

            else:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           group_id,
                           amount,
                           currency,
                           created_at

                    FROM payments

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
            "Error listando pagos:",
            e
        )

        return []
