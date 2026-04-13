import os
import stripe
import threading
import asyncio
import time

from flask import Flask, request

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

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

PRICE_1_DIA = "price_1TLZBDBbMxuRndhhV03r5m3T"
PRICE_7_DIAS = "price_1TLZCKBbMxuRndhhD8V9VYrp"
PRICE_PERMANENTE = "price_1TLZDQBbMxuRndhhYMG0Qf69"

bot = Bot(token=TOKEN)

flask_app = Flask(__name__)

telegram_app = ApplicationBuilder().token(TOKEN).build()


# =========================
# GUARDAR USUARIO
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
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [

        [InlineKeyboardButton("🟢 1 día — 5€", callback_data="1")],
        [InlineKeyboardButton("🟡 7 días — 10€", callback_data="7")],
        [InlineKeyboardButton("🔵 Permanente — 25€", callback_data="0")]

    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Bienvenido 💎\n\nElige tu plan:",
        reply_markup=reply_markup
    )


# =========================
# BOTONES
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    plan = query.data

    if plan == "1":
        price = PRICE_1_DIA

    elif plan == "7":
        price = PRICE_7_DIAS

    else:
        price = PRICE_PERMANENTE

    try:

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


# =========================
# CONTROL ENTRADAS
# =========================

async def check_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):

    new_members = update.message.new_chat_members

    for member in new_members:

        user_id = member.id

        with conn.cursor() as cur:

            cur.execute(
                "SELECT expiration FROM users WHERE user_id=%s",
                (user_id,)
            )

            result = cur.fetchone()

        if not result:

            print("Intruso expulsado:", user_id)

            await context.bot.ban_chat_member(
                chat_id=GROUP_ID,
                user_id=user_id
            )

            await context.bot.unban_chat_member(
                chat_id=GROUP_ID,
                user_id=user_id
            )


# =========================
# REVISAR EXPIRACIONES
# =========================

def check_expirations():

    while True:

        try:

            with conn.cursor() as cur:

                cur.execute(
                    "SELECT user_id, expiration FROM users"
                )

                users = cur.fetchall()

            now = datetime.now()

            for user_id, expiration in users:

                if expiration and now > expiration:

                    print("Expulsando por expiración:", user_id)

                    asyncio.run(
                        bot.ban_chat_member(
                            chat_id=GROUP_ID,
                            user_id=user_id
                        )
                    )

                    asyncio.run(
                        bot.unban_chat_member(
                            chat_id=GROUP_ID,
                            user_id=user_id
                        )
                    )

        except Exception as e:

            print("Error revisando expiraciones:", e)

        # producción real

        time.sleep(60)


# =========================
# WEBHOOK STRIPE
# =========================

@flask_app.route("/webhook", methods=["POST"])
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

        user_id = int(session["metadata"]["telegram_id"])

        line_items = stripe.checkout.Session.list_line_items(
            session["id"]
        )

        price_id = line_items["data"][0]["price"]["id"]

        # TIEMPOS REALES

        if price_id == PRICE_1_DIA:
            days = 1

        elif price_id == PRICE_7_DIAS:
            days = 7

        else:
            days = 0

        add_user(user_id, days)

        try:

            async def send_link():

                invite_link = await bot.create_chat_invite_link(
                    chat_id=GROUP_ID,
                    member_limit=1
                )

                await bot.send_message(
                    chat_id=user_id,
                    text=f"🔗 Tu acceso VIP:\n{invite_link.invite_link}"
                )

            asyncio.run(send_link())

        except Exception as e:

            print("Error enviando link:", e)

    return "OK"


@flask_app.route("/")
def home():
    return "Bot funcionando"


# =========================
# RUN
# =========================

def run_flask():

    port = int(os.environ.get("PORT"))

    flask_app.run(
        host="0.0.0.0",
        port=port
    )


def main():

    create_tables()

    telegram_app.add_handler(
        CommandHandler("start", start)
    )

    telegram_app.add_handler(
        CallbackQueryHandler(button)
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            check_new_member
        )
    )

    threading.Thread(
        target=run_flask
    ).start()

    threading.Thread(
        target=check_expirations
    ).start()

    telegram_app.run_polling()


if __name__ == "__main__":
    main()