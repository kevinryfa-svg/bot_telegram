import os
import stripe
import threading
import asyncio
import time
import random
import string

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

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

PRICE_1_DIA = "price_1TLZBDBbMxuRndhhV03r5m3T"
PRICE_7_DIAS = "price_1TLZCKBbMxuRndhhD8V9VYrp"
PRICE_PERMANENTE = "price_1TLZDQBbMxuRndhhYMG0Qf69"

bot = Bot(token=TOKEN)

telegram_app = ApplicationBuilder().token(TOKEN).build()


# =========================
# GENERAR CÓDIGOS
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
# CREAR CÓDIGO
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

    if not context.args:

        await update.message.reply_text(
            "Uso:\n/codigo TU_CODIGO"
        )

        return

    code = context.args[0]

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
# EXPIRACIONES (CORREGIDO)
# =========================

async def expiration_loop():

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

                    await bot.ban_chat_member(
                        chat_id=GROUP_ID,
                        user_id=user_id
                    )

                    await bot.unban_chat_member(
                        chat_id=GROUP_ID,
                        user_id=user_id
                    )

        except Exception as e:

            print("Error expiraciones:", e)

        await asyncio.sleep(60)


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
# MAIN
# =========================

async def main():

    create_tables()

    telegram_app.add_handler(
        CommandHandler("start", start)
    )

    telegram_app.add_handler(
        CommandHandler("generarcodigo", generar_codigo)
    )

    telegram_app.add_handler(
        CommandHandler("codigo", usar_codigo)
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            check_new_member
        )
    )

    telegram_app.create_task(
        expiration_loop()
    )

    print("Bot iniciado correctamente")

    await telegram_app.run_polling()


if __name__ == "__main__":

    asyncio.run(main())