import os
import stripe
import requests
import psycopg2

from flask import Flask, request, jsonify
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

from db import conn
from config import TOKEN, GROUP_ID


# -------------------------
# CONFIG STRIPE
# -------------------------

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

# PRICE IDS
PRICE_1_DIA = "price_1TLZBDBbMxuRndhhV03r5m3T"
PRICE_7_DIAS = "price_1TLZCKBbMxuRndhhD8V9VYrp"
PRICE_PERMANENTE = "price_1TLZDQBbMxuRndhhYMG0Qf69"

# DOMINIO CORRECTO
SERVER_URL = "https://worker-production-9e88.up.railway.app"

bot = Bot(token=TOKEN)

app = Flask(__name__)


# -------------------------
# GUARDAR USUARIO
# -------------------------

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


# -------------------------
# CREAR SESIÓN STRIPE
# -------------------------

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

    try:

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

    except Exception as e:

        print("Stripe error:", e)

        return jsonify({
            "error": str(e)
        }), 500


# -------------------------
# WEBHOOK STRIPE
# -------------------------

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

        line_items = stripe.checkout.Session.list_line_items(
            session["id"]
        )

        price_id = line_items["data"][0]["price"]["id"]

        if price_id == PRICE_1_DIA:
            days = 1

        elif price_id == PRICE_7_DIAS:
            days = 7

        elif price_id == PRICE_PERMANENTE:
            days = 0

        else:
            return "OK"

        add_user(int(user_id), days)

        invite_link = bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1
        )

        bot.send_message(
            chat_id=int(user_id),
            text=f"🔗 Tu acceso VIP:\n{invite_link.invite_link}"
        )

    return "OK"


# -------------------------
# TELEGRAM BOT
# -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Bienvenido 💎\n\nUsa /pagar para comprar acceso."
    )


async def pagar(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        "Elige tu plan:",
        reply_markup=reply_markup
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    plan = query.data

    try:

        response = requests.post(
            f"{SERVER_URL}/create-checkout-session",
            json={
                "telegram_id": telegram_id,
                "plan": plan
            }
        )

        data = response.json()

        if "url" not in data:

            await query.message.reply_text(
                f"Error Stripe:\n{data}"
            )

            return

        payment_url = data["url"]

        await query.message.reply_text(
            f"💳 Paga aquí:\n{payment_url}"
        )

    except Exception as e:

        await query.message.reply_text(
            f"Error creando pago:\n{e}"
        )


def run_telegram():

    telegram_app = ApplicationBuilder().token(TOKEN).build()

    telegram_app.add_handler(
        CommandHandler("start", start)
    )

    telegram_app.add_handler(
        CommandHandler("pagar", pagar)
    )

    telegram_app.add_handler(
        CallbackQueryHandler(button)
    )

    telegram_app.run_polling()


# -------------------------
# MAIN
# -------------------------

if __name__ == "__main__":

    import threading

    threading.Thread(
        target=run_telegram
    ).start()

    port = int(os.environ.get("PORT", 8000))

    app.run(
        host="0.0.0.0",
        port=port
    )