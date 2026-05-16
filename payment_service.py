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
# duration_days currently stores minutes for test plans when value < 1440.
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

def save_payment(user_id, plan_name, group_id=None, amount=None, currency=None, stripe_payment_id=None, status="paid"):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO payments
                (user_id, group_id, stripe_payment_id, amount, currency, status, plan)

                VALUES (%s, %s, %s, %s, %s, %s, %s)

            """, (

                user_id,
                group_id,
                stripe_payment_id,
                amount,
                currency,
                status,
                plan_name

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
                           status,
                           payment_date

                    FROM payments

                    ORDER BY payment_date DESC

                    LIMIT %s

                """, (limit,))

            else:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           group_id,
                           amount,
                           currency,
                           status,
                           payment_date

                    FROM payments

                    WHERE group_id=%s

                    ORDER BY payment_date DESC

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
