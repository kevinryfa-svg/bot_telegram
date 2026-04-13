import os
import stripe

from flask import Flask, request
from datetime import datetime, timedelta

from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

from db import conn
from config import TOKEN, GROUP_ID


# =========================
# CONFIG
# =========================

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

PRICE_1_DIA = "price_1TLZBDBbMxuRndhhV03r5m3T"
PRICE_7_DIAS = "price_1TLZCKBbMxuRndhhD8V9VYrp"
PRICE_PERMANENTE = "price_1TLZDQBbMxuRndhhYMG0Qf69"

SERVER_URL = "https://bottelegram-production-60c0.up.railway.app"

bot = Bot(token=TOKEN)

app = Flask(__name__)


# =========================
# DATABASE
# =========================

def add_user(user_id, days):

    if days == 0:
        expiration = None
    else:
        expiration = datetime.now() + timedelta(days=days)

    with conn.cursor() as cur:

        cur.execute("""
            INSERT INTO users (user_id, expiration)
            VALUES (%s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET expiration=%s
        """, (user_id, expiration, expiration))

        conn.commit()


# =========================
# TELEGRAM BOT
# =========================

telegram_app = Application.builder().token(TOKEN).build()


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

    telegram_id = query.from_user.id
    plan = query.data

    try:

        if plan == "1":
            price = PRICE_1_DIA

        elif plan == "7":
            price = PRICE_7_DIAS

        else:
            price = PRICE_PERMANENTE

        session = stripe.checkout.Session.create(

            payment_method_types=["card"],

            line_items=[{
                "price": price,
                "quantity": 1,
            }],

            mode="payment",

            success_url="https://t.me/TheStarVipBOT",
            cancel_url="https://t.me/TheStarVipBOT",

            metadata={
                "telegram_id": str(telegram_id)
            }

        )

        await query.message.reply_text(
            f"💳 Paga aquí:\n{session.url}"
        )

    except Exception as e:

        await query.message.reply_text(
            f"Error Stripe:\n{e}"
        )


telegram_app.add_handler(
    CommandHandler("start", start)
)

telegram_app.add_handler(
    CallbackQueryHandler(button)
)


# =========================
# TELEGRAM WEBHOOK
# =========================

@app.route(f"/{TOKEN}", methods=["POST"])
def telegram_webhook():

    update = Update.de_json(
        request.get_json(force=True),
        bot
    )

    telegram_app.update_queue.put_nowait(update)

    return "OK"


# =========================
# STRIPE WEBHOOK
# =========================

@app.route("/webhook", methods=["POST"])
def stripe_webhook():

    payload = request.data
    sig_header = request.headers.get("stripe-signature")

    try:

        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            WEBHOOK_SECRET
        )

    except Exception as e:

        print("Webhook error:", e)

        return "Error", 400

    if event["type"] == "checkout.session.completed":

        session = event["data"]["object"]

        user_id = session["metadata"]["telegram_id"]

        add_user(int(user_id), 1)

        invite_link = bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1
        )

        bot.send_message(
            chat_id=int(user_id),
            text=f"🔗 Tu acceso VIP:\n{invite_link.invite_link}"
        )

    return "OK"


# =========================
# HOME
# =========================

@app.route("/")
def home():

    return "Bot funcionando"


# =========================
# START
# =========================

if __name__ == "__main__":

    port = int(os.environ.get("PORT"))

    print("Configurando webhook...")

    bot.delete_webhook(
        drop_pending_updates=True
    )

    bot.set_webhook(
        url=f"{SERVER_URL}/{TOKEN}"
    )

    print("Webhook configurado")

    telegram_app.initialize()

    app.run(
        host="0.0.0.0",
        port=port
    )