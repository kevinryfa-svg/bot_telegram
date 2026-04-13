import os
import stripe
import psycopg2
from flask import Flask, request
from datetime import datetime, timedelta

from telegram import Bot
from db import conn
from config import TOKEN, GROUP_ID


# STRIPE CONFIG
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

bot = Bot(token=TOKEN)

app = Flask(__name__)


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

        product_name = session["display_items"][0]["custom"]["name"]

        user_id = session["metadata"]["telegram_id"]

        print("Pago detectado:", product_name)

        if product_name == "Acceso 1 día":
            days = 1

        elif product_name == "Acceso 7 días":
            days = 7

        elif product_name == "Acceso PERMANENTE":
            days = 0

        else:
            print("Producto desconocido")
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


@app.route("/", methods=["GET"])
def home():
    return "Bot funcionando"


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8000))

    app.run(
        host="0.0.0.0",
        port=port
    )