import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from config import TOKEN

# URL DE TU SERVIDOR
SERVER_URL = "https://worker-production-9e88.up.railway.app"


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("💳 Comprar acceso", callback_data="comprar")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Bienvenido al sistema VIP 💎",
        reply_markup=reply_markup
    )


# /pagar
async def pagar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("🟢 1 día — 5€", callback_data="1")],
        [InlineKeyboardButton("🟡 7 días — 10€", callback_data="7")],
        [InlineKeyboardButton("🔵 Permanente — 25€", callback_data="0")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Elige tu plan:",
        reply_markup=reply_markup
    )


# BOTONES
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    plan = query.data

    if plan not in ["1", "7", "0"]:
        return

    response = requests.post(
        f"{SERVER_URL}/create-checkout-session",
        json={
            "telegram_id": telegram_id,
            "plan": plan
        }
    )

    data = response.json()

    payment_url = data["url"]

    await query.message.reply_text(
        f"💳 Paga aquí:\n{payment_url}"
    )


def main():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pagar", pagar))

    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(button))

    print("Bot Telegram iniciado")

    app.run_polling()


if __name__ == "__main__":
    main()