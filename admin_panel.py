from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from rbac import get_admin_groups, has_permission, is_super_admin


# =========================
# ADMIN PANEL — MENÚ PRINCIPAL
# =========================

def build_admin_main_menu(user_id, admin_id):

    keyboard = []


    if is_super_admin(user_id, admin_id):

        keyboard.extend([

            [InlineKeyboardButton("👥 Gestión Usuarios", callback_data="menu_users")],
            [InlineKeyboardButton("🎟️ Gestión Accesos", callback_data="menu_codes")],
            [InlineKeyboardButton("📦 Gestión Grupos", callback_data="menu_groups")],
            [InlineKeyboardButton("💳 Gestión Pagos", callback_data="menu_payments")],
            [InlineKeyboardButton("📊 Gestión Negocio", callback_data="menu_business")],
            [InlineKeyboardButton("📜 Logs", callback_data="menu_logs")]

        ])

        return InlineKeyboardMarkup(keyboard)


    groups = get_admin_groups(
        user_id,
        admin_id
    )


    if groups:

        keyboard.append([
            InlineKeyboardButton(
                "📦 Mis grupos administrables",
                callback_data="admin_my_groups"
            )
        ])


    return InlineKeyboardMarkup(keyboard)


# =========================
# ADMIN PANEL — GRUPOS ADMINISTRABLES
# =========================

def build_admin_groups_menu(user_id, admin_id):

    groups = get_admin_groups(
        user_id,
        admin_id
    )

    keyboard = []


    for group_id, group_name, telegram_group_id in groups:

        keyboard.append([

            InlineKeyboardButton(
                f"📦 {group_name}",
                callback_data=f"admin_group_{group_id}"
            )

        ])


    keyboard.append([

        InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_back_main"
        )

    ])


    return InlineKeyboardMarkup(keyboard)


# =========================
# ADMIN PANEL — MENÚ GRUPO
# =========================

def build_single_group_admin_menu(user_id, group_id, admin_id):

    keyboard = []


    if has_permission(user_id, group_id, "can_view_users", admin_id):

        keyboard.append([
            InlineKeyboardButton(
                "👥 Ver usuarios",
                callback_data=f"group_users_{group_id}"
            )
        ])


    if has_permission(user_id, group_id, "can_kick_users", admin_id):

        keyboard.append([
            InlineKeyboardButton(
                "🚫 Expulsar usuario",
                callback_data=f"group_kick_{group_id}"
            )
        ])


    if has_permission(user_id, group_id, "can_ban_users", admin_id):

        keyboard.append([
            InlineKeyboardButton(
                "⛔ Banear usuario",
                callback_data=f"group_ban_{group_id}"
            )
        ])


    if has_permission(user_id, group_id, "can_unban_users", admin_id):

        keyboard.append([
            InlineKeyboardButton(
                "♻️ Desbanear usuario",
                callback_data=f"group_unban_{group_id}"
            )
        ])


    if has_permission(user_id, group_id, "can_warn_users", admin_id):

        keyboard.append([
            InlineKeyboardButton(
                "⚠️ Dar warning",
                callback_data=f"group_warn_{group_id}"
            )
        ])


    if has_permission(user_id, group_id, "can_reset_warnings", admin_id):

        keyboard.append([
            InlineKeyboardButton(
                "🔄 Reset warnings",
                callback_data=f"group_reset_warnings_{group_id}"
            )
        ])


    if has_permission(user_id, group_id, "can_resend_links", admin_id):

        keyboard.append([
            InlineKeyboardButton(
                "📩 Reenviar acceso",
                callback_data=f"group_resend_access_{group_id}"
            )
        ])


    if has_permission(user_id, group_id, "can_view_logs", admin_id):

        keyboard.append([
            InlineKeyboardButton(
                "📜 Logs del grupo",
                callback_data=f"group_logs_{group_id}"
            )
        ])


    keyboard.append([

        InlineKeyboardButton(
            "⬅️ Volver a grupos",
            callback_data="admin_my_groups"
        )

    ])


    return InlineKeyboardMarkup(keyboard)
