import time
import requests

from db import conn
from group_service import format_community_kind, resolve_telegram_group_id


def mask_invite_link(invite_link):

    if not invite_link:

        return invite_link


    return f"{str(invite_link)[:12]}***"


def sanitize_log_value(value, token=None):

    if isinstance(value, dict):

        safe = {}

        for key, item in value.items():

            if key == "invite_link":

                safe[key] = mask_invite_link(item)

            else:

                safe[key] = sanitize_log_value(
                    item,
                    token=token
                )


        return safe


    if isinstance(value, list):

        return [
            sanitize_log_value(
                item,
                token=token
            )
            for item in value
        ]


    text = str(value)


    if token:

        text = text.replace(
            token,
            "[redacted]"
        )


    return text


# =========================
# INVITE LINKS — MIGRACIÓN A SUPERGRUPO
# =========================
# Cuando un grupo se convierte en supergrupo, Telegram cambia su chat_id y
# rechaza cualquier petición al id antiguo con
# "group chat was upgraded to a supergroup chat", devolviendo el nuevo id en
# parameters.migrate_to_chat_id. Sin tratarlo, el bot no puede crear enlaces
# de acceso para ese grupo: el usuario paga y no recibe su enlace.

def extract_migrated_chat_id(response):

    if not isinstance(response, dict):

        return None


    parameters = response.get("parameters") or {}
    migrated = parameters.get("migrate_to_chat_id")


    if migrated in (None, ""):

        return None


    try:

        return int(migrated)

    except Exception:

        return None


def apply_group_chat_migration(old_chat_id, new_chat_id):
    """Guarda el nuevo chat_id para que el grupo vuelva a funcionar."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET telegram_group_id=%s
                WHERE telegram_group_id=%s

            """, (
                new_chat_id,
                old_chat_id
            ))

            cur.execute("""

                UPDATE invite_links
                SET telegram_group_id=%s
                WHERE telegram_group_id=%s

            """, (
                new_chat_id,
                old_chat_id
            ))

        print(
            "Grupo migrado a supergrupo: "
            f"{old_chat_id} -> {new_chat_id} (actualizado en la base de datos)"
        )

        return True

    except Exception as e:

        print(
            "Error guardando la migración a supergrupo:",
            e
        )

        return False


# =========================
# INVITE LINKS — CREATE TELEGRAM LINK
# =========================

def create_telegram_invite_link(token, telegram_group_id, expire_seconds=180, member_limit=1, community_type=None, return_details=False):

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

            # El grupo pasó a supergrupo: guardar el nuevo id y reintentar.
            migrated_chat_id = extract_migrated_chat_id(response)

            if migrated_chat_id and migrated_chat_id != telegram_group_id:

                apply_group_chat_migration(
                    telegram_group_id,
                    migrated_chat_id
                )

                payload["chat_id"] = migrated_chat_id

                response = requests.post(

                    f"https://api.telegram.org/bot{token}/createChatInviteLink",

                    json=payload

                ).json()


        if "result" not in response:

            kind = format_community_kind(community_type)

            print(
                f"Error creando invite link para {kind}:",
                sanitize_log_value(
                    response,
                    token=token
                )
            )

            if return_details:

                return {
                    "ok": False,
                    "description": response.get("description"),
                    "error_code": response.get("error_code"),
                    "response_ok": response.get("ok"),
                    "retry_after": (response.get("parameters") or {}).get("retry_after")
                }


            return None


        invite_link = response["result"]["invite_link"]


        if return_details:

            return {
                "ok": True,
                "invite_link": invite_link,
                "response_ok": response.get("ok")
            }


        return invite_link

    except Exception as e:

        kind = format_community_kind(community_type)

        print(
            f"Excepción creando invite link para {kind}:",
            sanitize_log_value(
                e,
                token=token
            )
        )

        if return_details:

            return {
                "ok": False,
                "description": str(e)[:500],
                "error": str(e)[:500],
                "response_ok": None
            }


        return None


def create_telegram_public_invite_link(token, telegram_group_id, name=None, community_type=None, return_details=False):

    payload = {
        "chat_id": telegram_group_id
    }


    if name:

        payload["name"] = name[:32]


    try:

        response = requests.post(

            f"https://api.telegram.org/bot{token}/createChatInviteLink",

            json=payload

        ).json()


        if "result" not in response:

            # El grupo pasó a supergrupo: guardar el nuevo id y reintentar.
            migrated_chat_id = extract_migrated_chat_id(response)

            if migrated_chat_id and migrated_chat_id != telegram_group_id:

                apply_group_chat_migration(
                    telegram_group_id,
                    migrated_chat_id
                )

                payload["chat_id"] = migrated_chat_id

                response = requests.post(

                    f"https://api.telegram.org/bot{token}/createChatInviteLink",

                    json=payload

                ).json()


        if "result" not in response:

            kind = format_community_kind(community_type)

            print(
                f"Error creando invite link público para {kind}:",
                sanitize_log_value(
                    response,
                    token=token
                )
            )

            if return_details:

                return {
                    "ok": False,
                    "description": response.get("description"),
                    "error_code": response.get("error_code"),
                    "response_ok": response.get("ok"),
                    "retry_after": (response.get("parameters") or {}).get("retry_after")
                }


            return None


        invite_link = response["result"]["invite_link"]


        if return_details:

            return {
                "ok": True,
                "invite_link": invite_link,
                "response_ok": response.get("ok")
            }


        return invite_link

    except Exception as e:

        kind = format_community_kind(community_type)

        print(
            f"Excepción creando invite link público para {kind}:",
            sanitize_log_value(
                e,
                token=token
            )
        )

        if return_details:

            return {
                "ok": False,
                "description": str(e)[:500],
                "error": str(e)[:500],
                "response_ok": None
            }


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
                    sanitize_log_value(
                        response,
                        token=token
                    )
                )


        return response

    except Exception as e:

        print(
            "Excepción revocando invite link:",
            sanitize_log_value(
                e,
                token=token
            )
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

        telegram_group_id = resolve_telegram_group_id(group_id)

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, telegram_group_id, invite_link, is_active)

                VALUES (%s, %s, %s, %s, %s)

            """, (

                user_id,
                group_id,
                telegram_group_id,
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
