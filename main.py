import os
import stripe
import threading

from flask import Flask
from datetime import datetime, timedelta

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

from db import conn
from config import TOKEN


# =========================
# TELEGRAM
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


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "Bot funcionando correctamente ✅"
    )


def run_bot():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CallbackQueryHandler(button)
    )

    print("Bot Telegram iniciado (polling)")

    app.run_polling()


# =========================
# FLASK
# =========================

flask_app = Flask(__name__)


@flask_app.route("/")
def home():

    return "Bot funcionando"


# =========================
# START
# =========================

if __name__ == "__main__":

    threading.Thread(
        target=run_bot
    ).start()

    port = int(os.environ.get("PORT"))

    flask_app.run(
        host="0.0.0.0",
        port=port
    )