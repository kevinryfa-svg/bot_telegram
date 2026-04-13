import os
import stripe
import threading
import asyncio
import time
import random
import string
import requests

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

ADMIN_ID = 8761243211

SERVER_URL = os.environ.get("SERVER_URL")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

PRICE_1_DIA = "price_1TLZBDBbMxuRndhhV03r5m3T"
PRICE_7_DIAS = "price_1TLZCKBbMxuRndhhD8V9VYrp"
PRICE_PERMANENTE = "price_1TLZDQBbMxuRndhhYMG0Qf69"

bot = Bot(token=TOKEN)

telegram_app = ApplicationBuilder().token(TOKEN).build()


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
# CREAR CÓDIGO (ADMIN)
# =========================

async def generar_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text("No autorizado")
        return

    if not context.args:

        await update.message.reply_text(
            "Uso:\n/generarcodigo minutos"
        )

        return

    duration = int(context.args[0])

    code = generate_code()

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO invite_codes
            (code, duration)

            VALUES (%s, %s)

        """, (code, duration))

        conn.commit()

    await update.message.reply_text(

        f"✅ Código creado:\n\n"
        f"{code}\n\n"
        f"Duración: {duration} minutos"

    )


# =========================
# USAR CÓDIGO
# =========================

async def usar_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    code = update.message.text.strip()

    user_id = update.effective_user.id

    with conn.cursor() as cur:

        cur.execute("""

            SELECT duration, used
            FROM invite_codes
            WHERE code=%s

        """, (code,))

        result = cur.fetchone()

    if not result:

        await update.message.reply_text("❌ Código inválido")
        return

    duration, used = result

    if used:

        await update.message.reply_text("❌ Código ya usado")
        return

    expiration = datetime.now() + timedelta(
        minutes=duration
    )

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO users
            (user_id, expiration)

            VALUES (%s, %s)

            ON CONFLICT (user_id)
            DO UPDATE SET expiration=%s

        """, (user_id, expiration, expiration))

        cur.execute("""

            UPDATE invite_codes
            SET used=TRUE
            WHERE code=%s

        """, (code,))

        conn.commit()

    invite_link = await bot.create_chat_invite_link(
        chat_id=GROUP_ID,
        member_limit=1
    )

    await bot.send_message(
        chat_id=user_id,
        text=f"🔗 Tu acceso VIP:\n{invite_link.invite_link}"
    )

    await update.message.reply_text(
        "✅ Código activado correctamente"
    )


# =========================
# BOTONES
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [

        [InlineKeyboardButton("🟢 1 día — 5€", callback_data="1")],

        [InlineKeyboardButton("🟡 7 días — 10€", callback_data="7")],

        [InlineKeyboardButton("🔵 Permanente — 25€", callback_data="0")],

        [InlineKeyboardButton("🎟️ Usar código", callback_data="codigo")]

    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(

        "Bienvenido 💎\n\n"
        "Elige una opción:",

        reply_markup=reply_markup

    )


# =========================
# BOTÓN CLICK
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    plan = query.data

    if plan == "codigo":

        await query.message.reply_text(
            "Introduce tu código:"
        )

        context.user_data["waiting_code"] = True
        return

    try:

        response = requests.post(
            f"{SERVER_URL}/create-checkout-session",
            json={
                "telegram_id": user_id,
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


# =========================
# RECIBIR CÓDIGO TEXTO
# =========================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if context.user_data.get("waiting_code"):

        context.user_data["waiting_code"] = False

        await usar_codigo(update, context)


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

            await context.bot.ban_chat_member(
                chat_id=GROUP_ID,
                user_id=user_id
            )

            await context.bot.unban_chat_member(
                chat_id=GROUP_ID,
                user_id=user_id
            )


# =========================
# EXPIRACIONES
# =========================

def expiration_thread():

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

            print("Error expiraciones:", e)

        time.sleep(60)


# =========================
# MAIN
# =========================

def main():

    create_tables()

    telegram_app.add_handler(
        CommandHandler("start", start)
    )

    telegram_app.add_handler(
        CommandHandler("generarcodigo", generar_codigo)
    )

    telegram_app.add_handler(
        CallbackQueryHandler(button)
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            check_new_member
        )
    )

    threading.Thread(
        target=expiration_thread
    ).start()

    print("Bot iniciado correctamente")

    telegram_app.run_polling()


if __name__ == "__main__":
    main()