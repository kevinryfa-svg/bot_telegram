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
# /generarcodigo
# =========================

async def generar_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [

        [InlineKeyboardButton("⏱️ 15 minutos", callback_data="gen_15")],
        [InlineKeyboardButton("📅 1 día", callback_data="gen_1440")],
        [InlineKeyboardButton("📅 7 días", callback_data="gen_10080")],
        [InlineKeyboardButton("📅 30 días", callback_data="gen_43200")],
        [InlineKeyboardButton("♾️ Permanente", callback_data="gen_perm")]

    ]

    await update.message.reply_text(
        "Selecciona duración:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# CREAR CÓDIGO
# =========================

async def crear_codigo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    if not data.startswith("gen_"):
        return

    if data == "gen_perm":
        duration = 0
    else:
        duration = int(data.split("_")[1])

    code = generate_code()

    with conn.cursor() as cur:

        cur.execute("""
            INSERT INTO invite_codes (code, duration, used)
            VALUES (%s, %s, FALSE)
        """, (code, duration))

        conn.commit()

    await query.message.reply_text(
        f"✅ Código creado:\n\n{code}"
    )


# =========================
# /codigos
# =========================

async def ver_codigos(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    with conn.cursor() as cur:

        cur.execute("""
            SELECT code, duration, used
            FROM invite_codes
            ORDER BY code DESC
            LIMIT 20
        """)

        rows = cur.fetchall()

    texto = "🎟️ Códigos:\n\n"

    for code, duration, used in rows:

        estado = "❌ usado" if used else "✅ activo"

        texto += f"{code}\n{duration} min — {estado}\n\n"

    await update.message.reply_text(texto)


# =========================
# /usuarios
# =========================

async def ver_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    with conn.cursor() as cur:

        cur.execute("""
            SELECT user_id, expiration
            FROM users
            ORDER BY expiration DESC
        """)

        users = cur.fetchall()

    texto = "👥 Usuarios:\n\n"

    for user_id, expiration in users:

        texto += f"{user_id} — {expiration}\n"

    await update.message.reply_text(texto)


# =========================
# USAR CÓDIGO
# =========================

async def receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("waiting_code"):
        return

    user_code = update.message.text.strip().upper()

    with conn.cursor() as cur:

        cur.execute("""
            SELECT duration, used
            FROM invite_codes
            WHERE code=%s
        """, (user_code,))

        row = cur.fetchone()

        if not row:

            await update.message.reply_text(
                "❌ Código inválido"
            )
            return

        duration, used = row

        if used:

            await update.message.reply_text(
                "❌ Código ya usado"
            )
            return

        if duration == 0:
            expiration = None
        else:
            expiration = datetime.now() + timedelta(minutes=duration)

        cur.execute("""
            INSERT INTO users (user_id, expiration)
            VALUES (%s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET expiration=%s
        """, (update.effective_user.id, expiration, expiration))

        cur.execute("""
            UPDATE invite_codes
            SET used=TRUE
            WHERE code=%s
        """, (user_code,))

        conn.commit()

    invite_link = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",
        json={
            "chat_id": GROUP_ID,
            "member_limit": 1
        }
    ).json()

    link = invite_link["result"]["invite_link"]

    await update.message.reply_text(
        f"🔗 Acceso concedido:\n{link}"
    )

    context.user_data["waiting_code"] = False


# =========================
# STRIPE CREAR PAGO
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

    return jsonify({
        "url": session.url
    })


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

    if data.startswith("gen_"):

        await crear_codigo_callback(update, context)
        return

    if data == "codigo":

        context.user_data["waiting_code"] = True

        await query.message.reply_text(
            "Introduce tu código:"
        )

        return

    # PAGOS STRIPE

    user_id = query.from_user.id

    response = requests.post(
        f"{SERVER_URL}/create-checkout-session",
        json={
            "telegram_id": user_id,
            "plan": data
        }
    )

    payment_url = response.json()["url"]

    await query.message.reply_text(
        f"💳 Paga aquí:\n{payment_url}"
    )


# =========================
# MAIN
# =========================

def main():

    create_tables()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("generarcodigo", generar_codigo))
    telegram_app.add_handler(CommandHandler("codigos", ver_codigos))
    telegram_app.add_handler(CommandHandler("usuarios", ver_usuarios))

    telegram_app.add_handler(CallbackQueryHandler(button))

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_code
        )
    )

    print("Bot iniciado correctamente")

    telegram_app.run_polling()


if __name__ == "__main__":
    main()