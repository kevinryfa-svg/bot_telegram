import requests

from db import conn
from rbac import is_super_admin, has_permission


# =========================
# NOTIFICATIONS — SEND MESSAGE
# =========================

def send_telegram_message(token, chat_id, text, reply_markup=None):

    payload = {
        "chat_id": chat_id,
        "text": text
    }


    if reply_markup is not None:

        payload["reply_markup"] = reply_markup


    try:

        response = requests.post(

            f"https://api.telegram.org/bot{token}/sendMessage",

            json=payload

        ).json()


        if not response.get("ok"):

            print(
                "Error enviando notificación:",
                response
            )


        return response

    except Exception as e:

        print(
            "Excepción enviando notificación:",
            e
        )

        return None


# =========================
# NOTIFICATIONS — SUPER ADMINS
# =========================

def get_super_admin_ids(fallback_admin_id=None):

    admin_ids = []


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT user_id
                FROM admins
                WHERE is_super_admin=TRUE
                AND is_active=TRUE

            """)

            rows = cur.fetchall()


        admin_ids = [
            row[0]
            for row in rows
        ]

    except Exception as e:

        print(
            "Error obteniendo super admins:",
            e
        )


    if fallback_admin_id and fallback_admin_id not in admin_ids:

        admin_ids.append(
            fallback_admin_id
        )


    return admin_ids



def notify_super_admins(token, text, fallback_admin_id=None):

    admin_ids = get_super_admin_ids(
        fallback_admin_id
    )

    sent = 0


    for admin_id in admin_ids:

        response = send_telegram_message(
            token,
            admin_id,
            text
        )

        if response and response.get("ok"):

            sent += 1


    return sent


# =========================
# NOTIFICATIONS — GROUP ADMINS BY PERMISSION
# =========================

def get_group_admin_ids_by_permission(group_id, permission, fallback_admin_id=None):

    admin_ids = []


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                SELECT DISTINCT user_id
                FROM admins
                WHERE group_id=%s
                AND {permission}=TRUE
                AND is_active=TRUE

            """, (group_id,))

            rows = cur.fetchall()


        admin_ids = [
            row[0]
            for row in rows
        ]

    except Exception as e:

        print(
            "Error obteniendo admins de grupo para notificación:",
            e
        )


    if fallback_admin_id and fallback_admin_id not in admin_ids:

        admin_ids.append(
            fallback_admin_id
        )


    return admin_ids



def notify_group_admins(token, group_id, permission, text, fallback_admin_id=None):

    admin_ids = get_group_admin_ids_by_permission(
        group_id,
        permission,
        fallback_admin_id
    )

    sent = 0


    for admin_id in admin_ids:

        response = send_telegram_message(
            token,
            admin_id,
            text
        )

        if response and response.get("ok"):

            sent += 1


    return sent
