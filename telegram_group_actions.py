import requests


# =========================
# TELEGRAM GROUP ACTIONS — BAN / UNBAN / KICK
# =========================

def ban_chat_member(token, chat_id, user_id):

    try:

        return requests.post(

            f"https://api.telegram.org/bot{token}/banChatMember",

            json={
                "chat_id": chat_id,
                "user_id": user_id
            }

        ).json()

    except Exception as e:

        print(
            "Error baneando usuario:",
            e
        )

        return None



def unban_chat_member(token, chat_id, user_id, only_if_banned=False):

    try:

        return requests.post(

            f"https://api.telegram.org/bot{token}/unbanChatMember",

            json={
                "chat_id": chat_id,
                "user_id": user_id,
                "only_if_banned": only_if_banned
            }

        ).json()

    except Exception as e:

        print(
            "Error desbaneando usuario:",
            e
        )

        return None



def kick_chat_member(token, chat_id, user_id):

    ban_response = ban_chat_member(
        token,
        chat_id,
        user_id
    )

    unban_response = unban_chat_member(
        token,
        chat_id,
        user_id,
        only_if_banned=False
    )


    return {
        "ban": ban_response,
        "unban": unban_response
    }


# =========================
# TELEGRAM GROUP ACTIONS — RESTRICT / UNRESTRICT
# =========================

def restrict_chat_member(token, chat_id, user_id, permissions):

    try:

        return requests.post(

            f"https://api.telegram.org/bot{token}/restrictChatMember",

            json={
                "chat_id": chat_id,
                "user_id": user_id,
                "permissions": permissions
            }

        ).json()

    except Exception as e:

        print(
            "Error restringiendo usuario:",
            e
        )

        return None



def mute_chat_member(token, chat_id, user_id):

    permissions = {
        "can_send_messages": False,
        "can_send_audios": False,
        "can_send_documents": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_video_notes": False,
        "can_send_voice_notes": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False,
        "can_change_info": False,
        "can_invite_users": False,
        "can_pin_messages": False,
        "can_manage_topics": False
    }


    return restrict_chat_member(
        token,
        chat_id,
        user_id,
        permissions
    )



def unmute_chat_member(token, chat_id, user_id):

    permissions = {
        "can_send_messages": True,
        "can_send_audios": True,
        "can_send_documents": True,
        "can_send_photos": True,
        "can_send_videos": True,
        "can_send_video_notes": True,
        "can_send_voice_notes": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True,
        "can_change_info": False,
        "can_invite_users": True,
        "can_pin_messages": False,
        "can_manage_topics": False
    }


    return restrict_chat_member(
        token,
        chat_id,
        user_id,
        permissions
    )


# =========================
# TELEGRAM GROUP ACTIONS — LEAVE GROUP
# =========================

def leave_chat(token, chat_id):

    try:

        return requests.post(

            f"https://api.telegram.org/bot{token}/leaveChat",

            json={
                "chat_id": chat_id
            }

        ).json()

    except Exception as e:

        print(
            "Error saliendo del grupo:",
            e
        )

        return None
