from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from rbac_helpers import is_super_admin


# =========================
# PANEL ADMIN PRINCIPAL
# =========================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id


    if not is_super_admin(user_id):

        await update.message.reply_text(
            "⛔ No tienes permisos para acceder al panel."
        )

        return


    keyboard = [

        [InlineKeyboardButton("👥 Gestión Usuarios", callback_data="menu_users")],

        [InlineKeyboardButton("🎟️ Gestión Accesos", callback_data="menu_codes")],

        [InlineKeyboardButton("📦 Gestión Grupos", callback_data="menu_groups")],

        [InlineKeyboardButton("💳 Gestión Pagos", callback_data="menu_payments")],

        [InlineKeyboardButton("📊 Gestión Negocio", callback_data="menu_business")],

        [InlineKeyboardButton("📜 Logs", callback_data="menu_logs")]

    ]

    await update.message.reply_text(

        "🔐 PANEL ADMIN",

        reply_markup=InlineKeyboardMarkup(keyboard)

    )
