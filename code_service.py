import random
import string

from datetime import datetime, timedelta

from db import conn


# =========================
# CODE SERVICE — GENERATE CODE
# =========================

def generate_code():

    return ''.join(
        random.choices(
            string.ascii_uppercase +
            string.digits,
            k=20
        )
    )


# =========================
# CODE SERVICE — GET CODE
# =========================

def get_invite_code(code):

    code = str(code).strip().upper()


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT code,
                       duration,
                       used

                FROM invite_codes

                WHERE code=%s

                LIMIT 1

            """, (code,))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo código:",
            e
        )

        return None


# =========================
# CODE SERVICE — VALIDATE CODE
# =========================

def validate_invite_code(code):

    row = get_invite_code(code)


    if not row:

        return False, "❌ Código inválido", None


    code_value, duration, used = row


    if used:

        return False, "❌ Código ya usado", None


    return True, "✅ Código válido", {
        "code": code_value,
        "duration": duration,
        "used": used
    }


# =========================
# CODE SERVICE — MARK USED
# =========================

def mark_invite_code_used(code):

    code = str(code).strip().upper()


    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE invite_codes
                SET used=TRUE
                WHERE code=%s

            """, (code,))

            affected = cur.rowcount

            conn.commit()

            return affected > 0

    except Exception as e:

        conn.rollback()

        print(
            "Error marcando código usado:",
            e
        )

        return False


# =========================
# CODE SERVICE — DELETE CODE
# =========================

def delete_invite_code(code):

    code = str(code).strip().upper()


    try:

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_codes
                WHERE code=%s

            """, (code,))

            affected = cur.rowcount

            conn.commit()

            return affected > 0

    except Exception as e:

        conn.rollback()

        print(
            "Error eliminando código:",
            e
        )

        return False


# =========================
# CODE SERVICE — LIST CODES
# =========================

def list_invite_codes(limit=50):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT code,
                       duration,
                       used

                FROM invite_codes

                ORDER BY code DESC

                LIMIT %s

            """, (limit,))

            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando códigos:",
            e
        )

        return []


# =========================
# CODE SERVICE — CALCULATE EXPIRATION
# =========================

def expiration_from_duration_minutes(duration):

    if duration == 0:

        return None


    return datetime.now() + timedelta(
        minutes=int(duration)
    )
