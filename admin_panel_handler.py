from telegram import (
    Update
)
from telegram.ext import ContextTypes

from admin_menu_catalog import build_admin_menu_button_rows
from rbac_helpers import is_super_admin
from ui_menu_helpers import make_keyboard_from_specs


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


    keyboard = build_admin_menu_button_rows(
        is_super_admin=True
    )

    await update.message.reply_text(

        "🔐 PANEL ADMIN",

        reply_markup=make_keyboard_from_specs(keyboard)

    )
