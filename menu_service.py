from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# =========================
# MENU SERVICE — BASIC KEYBOARD
# =========================

def build_keyboard(rows):

    return InlineKeyboardMarkup(rows)


# =========================
# MENU SERVICE — BACK BUTTONS
# =========================

def back_to_admin_panel_button():

    return InlineKeyboardButton(
        "⬅️ Volver al panel",
        callback_data="admin_panel"
    )



def close_button():

    return InlineKeyboardButton(
        "❌ Cerrar",
        callback_data="close_panel"
    )


# =========================
# MENU SERVICE — ADMIN MAIN MENU
# =========================

def build_admin_main_menu():

    keyboard = [

        [
            InlineKeyboardButton("👥 Usuarios", callback_data="admin_users"),
            InlineKeyboardButton("🎟 Códigos", callback_data="admin_codes")
        ],

        [
            InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats"),
            InlineKeyboardButton("📜 Logs", callback_data="admin_logs")
        ],

        [
            InlineKeyboardButton("🔗 Reenviar links", callback_data="admin_resend_links"),
            InlineKeyboardButton("♻️ Revocar links", callback_data="admin_revoke_links")
        ],

        [
            InlineKeyboardButton("🛡 Admins", callback_data="admin_manage_admins"),
            InlineKeyboardButton("📌 Grupos", callback_data="admin_groups")
        ],

        [
            close_button()
        ]

    ]


    return build_keyboard(keyboard)


# =========================
# MENU SERVICE — USER MODERATION MENU
# =========================

def build_user_moderation_menu(target_user_id, group_id):

    keyboard = [

        [
            InlineKeyboardButton(
                "🚪 Expulsar",
                callback_data=f"kick_user_{target_user_id}_{group_id}"
            ),
            InlineKeyboardButton(
                "⛔ Banear",
                callback_data=f"ban_user_{target_user_id}_{group_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "♻️ Desbanear",
                callback_data=f"unban_user_{target_user_id}_{group_id}"
            ),
            InlineKeyboardButton(
                "⚠️ Warning",
                callback_data=f"warn_user_{target_user_id}_{group_id}"
            )
        ],

        [
            back_to_admin_panel_button()
        ]

    ]


    return build_keyboard(keyboard)


# =========================
# MENU SERVICE — ALLOW / DENY ACCESS MENU
# =========================

def build_access_review_menu(target_user_id, group_id):

    keyboard = [

        [
            InlineKeyboardButton(
                "✅ Permitir",
                callback_data=f"allow_user_{target_user_id}_{group_id}"
            ),
            InlineKeyboardButton(
                "🚪 Expulsar",
                callback_data=f"deny_user_{target_user_id}_{group_id}"
            )
        ]

    ]


    return build_keyboard(keyboard)
