import os
import stripe
import threading
import asyncio

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

from datetime import datetime

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

authorized_users = set()

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
# CONTROLAR ENTRADAS
# =========================

async def check_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):

    new_members = update.message.new_chat_members

    for member in new_members:

        user_id = member.id

        print("Usuario entró:", user_id)

        if user_id not in authorized_users:

            print("Usuario NO autorizado:", user_id)

            await context.bot.ban_chat_member(
                chat_id=GROUP_ID,
                user_id=user_id
            )

            await context.bot.unban_chat_member(
                chat_id=GROUP_ID,
                user_id=user_id
            )


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

        print("Pago confirmado:", user_id)

        authorized_users.add(user_id)

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

            print("Link enviado correctamente")

        except Exception as e:

            print("Error enviando link:", e)

    return "OK"


@flask_app.route("/")
def home():
    return "Bot funcionando"


# =========================
# FLASK RUN
# =========================

def run_flask():

    port = int(os.environ.get("PORT"))

    flask_app.run(
        host="0.0.0.0",
        port=port
    )


# =========================
# MAIN
# =========================

def main():

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

    print("Bot iniciado")

    telegram_app.run_polling()


if __name__ == "__main__":
    main()