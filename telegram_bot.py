import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

from config import TOKEN

# URL DEL SERVIDOR
SERVER_URL = "https://worker-production-9e88.up.railway.app"


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Bienvenido al sistema VIP 💎\n\n"
        "Escribe /pagar para comprar acceso."
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

    try:

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

    except Exception as e:

        print("Error creando pago:", e)

        await query.message.reply_text(
            "Error creando el pago ❌"
        )


def main():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pagar", pagar))

    app.add_handler(CallbackQueryHandler(button))

    print("Bot Telegram iniciado")

    app.run_polling()


if __name__ == "__main__":
    main()