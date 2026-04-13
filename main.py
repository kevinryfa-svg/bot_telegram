from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

from config import TOKEN


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [

        [InlineKeyboardButton(
            "🟢 1 día — 5€",
            callback_data="1"
        )],

        [InlineKeyboardButton(
            "🟡 7 días — 10€",
            callback_data="7"
        )],

        [InlineKeyboardButton(
            "🔵 Permanente — 25€",
            callback_data="0"
        )]

    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Bienvenido 💎\n\nElige tu plan:",
        reply_markup=reply_markup
    )


# =========================
# BUTTON
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "Bot funcionando correctamente ✅"
    )


# =========================
# MAIN
# =========================

def main():

    print("Bot Telegram iniciado")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CallbackQueryHandler(button)
    )

    app.run_polling()


if __name__ == "__main__":
    main()