import os
import stripe
import threading
import random
import string
import requests

from flask import Flask, request, jsonify

from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from datetime import datetime, timedelta

from db import conn, create_tables


# =========================
# CONFIG
# =========================

TOKEN = os.environ.get("TOKEN")
GROUP_ID = int(os.environ.get("GROUP_ID"))
SERVER_URL = os.environ.get("SERVER_URL")

ADMIN_ID = 8761243211

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

PRICE_1_DIA = "price_1TLZBDBbMxuRndhhV03r5m3T"
PRICE_7_DIAS = "price_1TLZCKBbMxuRndhhD8V9VYrp"
PRICE_PERMANENTE = "price_1TLZDQBbMxuRndhhYMG0Qf69"

bot = Bot(token=TOKEN)

telegram_app = ApplicationBuilder().token(TOKEN).build()

app = Flask(__name__)


# =========================
# GENERAR CÓDIGO
# =========================

def generate_code():

    return ''.join(
        random.choices(
            string.ascii_uppercase +
            string.digits,
            k=20
        )
    )


# =========================
# STRIPE CHECKOUT
# =========================

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():

    data = request.json

    telegram_id = data["telegram_id"]
    plan = data["plan"]

    if plan == "1":
        price_id = PRICE_1_DIA

    elif plan == "7":
        price_id = PRICE_7_DIAS

    elif plan == "0":
        price_id = PRICE_PERMANENTE

    else:
        return jsonify({"error": "Plan inválido"}), 400

    session = stripe.checkout.Session.create(

        payment_method_types=["card"],

        line_items=[{
            "price": price_id,
            "quantity": 1,
        }],

        mode="payment",

        success_url="https://t.me/TheStarVipBOT",
        cancel_url="https://t.me/TheStarVipBOT",

        metadata={
            "telegram_id": str(telegram_id)
        }

    )

    return jsonify({"url": session.url})


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

        invite_link = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",
            json={
                "chat_id": GROUP_ID,
                "member_limit": 1
            }
        ).json()

        link = invite_link["result"]["invite_link"]

        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": int(user_id),
                "text": f"🔗 Tu acceso VIP:\n{link}"
            }
        )

        print("Pago confirmado:", user_id)

    return "OK"


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [

        [InlineKeyboardButton("🟢 1 día — 5€", callback_data="1")],
        [InlineKeyboardButton("🟡 7 días — 10€", callback_data="7")],
        [InlineKeyboardButton("🔵 Permanente — 25€", callback_data="0")],
        [InlineKeyboardButton("🎟️ Usar código", callback_data="codigo")]

    ]

    await update.message.reply_text(

        "Bienvenido 💎",

        reply_markup=InlineKeyboardMarkup(keyboard)

    )


# =========================
# BOTONES
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "codigo":

        context.user_data["waiting_code"] = True

        await query.message.reply_text(
            "Introduce tu código:"
        )

        return

    # PAGOS STRIPE

    user_id = query.from_user.id

    try:

        response = requests.post(
            f"{SERVER_URL}/create-checkout-session",
            json={
                "telegram_id": user_id,
                "plan": data
            }
        )

        data_json = response.json()

        payment_url = data_json["url"]

        await query.message.reply_text(
            f"💳 Paga aquí:\n{payment_url}"
        )

    except Exception as e:

        await query.message.reply_text(
            f"Error creando pago:\n{e}"
        )


# =========================
# RUN FLASK
# =========================

def run_flask():

    port = int(os.environ.get("PORT"))

    app.run(
        host="0.0.0.0",
        port=port
    )


# =========================
# MAIN
# =========================

def main():

    create_tables()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(button))

    # Flask en thread

    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    print("Bot iniciado correctamente")

    telegram_app.run_polling()


if __name__ == "__main__":
    main()