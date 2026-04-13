import os
import stripe
import threading

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
    ContextTypes
)

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


# =========================
# TELEGRAM START
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
# BOTONES PAGO
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

        user_id = session["metadata"]["telegram_id"]

        print("Pago confirmado:", user_id)

        try:

            # Crear link único (SIN async)

            invite_link = bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                member_limit=1
            )

            # Enviar mensaje

            bot.send_message(
                chat_id=int(user_id),
                text=f"🔗 Tu acceso VIP:\n{invite_link.invite_link}"
            )

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

    print("Iniciando Flask...")

    threading.Thread(
        target=run_flask
    ).start()

    print("Iniciando Telegram...")

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