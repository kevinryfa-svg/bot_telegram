import time
import requests

from db import conn
from group_service import resolve_telegram_group_id


# =========================
# INVITE LINKS — CREATE TELEGRAM LINK
# =========================

def create_telegram_invite_link(token, telegram_group_id, expire_seconds=180, member_limit=1):

    payload = {
        "chat_id": telegram_group_id,
        "member_limit": member_limit
    }


    if expire_seconds:

        payload["expire_date"] = int(time.time()) + int(expire_seconds)


    try:

        response = requests.post(

            f"https://api.telegram.org/bot{token}/createChatInviteLink",

            json=payload

        ).json()


        if "result" not in response:

            print(
                "Error creando invite link:",
                response
            )

            return None


        return response["result"]["invite_link"]

    except Exception as e:

        print(
            "Excepción creando invite link:",
            e
        )

        return None


# =========================
# INVITE LINKS — REVOKE TELEGRAM LINK
# =========================

def revoke_telegram_invite_link(token, telegram_group_id, invite_link):

    try:

        response = requests.post(

            f"https://api.telegram.org/bot{token}/revokeChatInviteLink",

            json={
                "chat_id": telegram_group_id,
                "invite_link": invite_link
            }

        ).json()


        if not response.get("ok"):

            description = response.get(
                "description",
                ""
            )

            if description != "Bad Request: INVITE_HASH_EXPIRED":

                print(
                    "Error real revocando link:",
                    response
                )


        return response

    except Exception as e:

        print(
            "Excepción revocando invite link:",
            e
        )

        return None


# =========================
# INVITE LINKS — DB LIST USER LINKS
# =========================

def list_user_group_links(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

                ORDER BY created_at DESC

            """, (

                user_id,
                group_id

            ))

            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando links usuario/grupo:",
            e
        )

        return []


# =========================
# INVITE LINKS — DB DELETE USER LINKS
# =========================

def delete_user_group_links(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                group_id

            ))

            affected = cur.rowcount

            conn.commit()

            return affected

    except Exception as e:

        conn.rollback()

        print(
            "Error borrando links usuario/grupo:",
            e
        )

        return 0


# =========================
# INVITE LINKS — DB SAVE LINK
# =========================

def save_user_group_link(user_id, group_id, invite_link, is_active=True):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, invite_link, is_active)

                VALUES (%s, %s, %s, %s)

            """, (

                user_id,
                group_id,
                invite_link,
                is_active

            ))

            conn.commit()

            return True

    except Exception as e:

        conn.rollback()

        print(
            "Error guardando link usuario/grupo:",
            e
        )

        return False


# =========================
# INVITE LINKS — MARK INACTIVE
# =========================

def mark_link_inactive(invite_link):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE invite_links

                SET is_active=FALSE,
                    revoked_at=NOW()

                WHERE invite_link=%s

            """, (invite_link,))

            affected = cur.rowcount

            conn.commit()

            return affected > 0

    except Exception as e:

        conn.rollback()

        print(
            "Error marcando link inactivo:",
            e
        )

        return False


# =========================
# INVITE LINKS — REVOKE + DELETE USER LINKS
# group_id here must be the Telegram group id currently stored in invite_links.
# =========================

def revoke_and_delete_user_group_links(token, user_id, telegram_group_id):

    links = list_user_group_links(
        user_id,
        telegram_group_id
    )


    for (invite_link,) in links:

        revoke_telegram_invite_link(
            token,
            telegram_group_id,
            invite_link
        )

        mark_link_inactive(
            invite_link
        )


    return delete_user_group_links(
        user_id,
        telegram_group_id
    )


# =========================
# INVITE LINKS — CREATE FRESH USER LINK
# group_id here must be the Telegram group id currently stored in invite_links.
# =========================

def create_fresh_user_group_link(token, user_id, telegram_group_id, expire_seconds=180):

    revoke_and_delete_user_group_links(
        token,
        user_id,
        telegram_group_id
    )


    invite_link = create_telegram_invite_link(
        token,
        telegram_group_id,
        expire_seconds=expire_seconds,
        member_limit=1
    )


    if not invite_link:

        return None


    saved = save_user_group_link(
        user_id,
        telegram_group_id,
        invite_link,
        True
    )


    if not saved:

        return None


    return invite_link
