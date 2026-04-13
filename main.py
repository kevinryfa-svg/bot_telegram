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
# BOTONES GENERAR CÓDIGO
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

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Selecciona duración del código:",
        reply_markup=reply_markup
    )


# =========================
# CREAR CÓDIGO
# =========================

async def crear_codigo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    data = query.data

    if data == "gen_perm":
        duration = 0
    else:
        duration = int(data.split("_")[1])

    code = generate_code()

    with conn.cursor() as cur:

        cur.execute("""
            INSERT INTO invite_codes
            (code, duration)
            VALUES (%s, %s)
        """, (code, duration))

        conn.commit()

    if duration == 0:
        duracion_texto = "Permanente"
    else:
        duracion_texto = f"{duration} minutos"

    await query.message.reply_text(

        f"✅ Código creado:\n\n"
        f"{code}\n\n"
        f"Duración: {duracion_texto}"

    )


# =========================
# VER CÓDIGOS
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

    if not rows:

        await update.message.reply_text(
            "No hay códigos."
        )
        return

    texto = "🎟️ Últimos códigos:\n\n"

    for code, duration, used in rows:

        estado = "❌ usado" if used else "✅ activo"

        texto += f"{code}\n{duration} min — {estado}\n\n"

    await update.message.reply_text(texto)


# =========================
# BORRAR CÓDIGO
# =========================

async def borrar_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:

        await update.message.reply_text(
            "Uso:\n/borrarcodigo CODIGO"
        )
        return

    code = context.args[0]

    with conn.cursor() as cur:

        cur.execute(
            "DELETE FROM invite_codes WHERE code=%s",
            (code,)
        )

        conn.commit()

    await update.message.reply_text(
        "🗑️ Código eliminado"
    )


# =========================
# VER USUARIOS
# =========================

async def ver_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    with conn.cursor() as cur:

        cur.execute("""
            SELECT user_id, expiration
            FROM users
            ORDER BY expiration DESC
            LIMIT 20
        """)

        users = cur.fetchall()

    if not users:

        await update.message.reply_text(
            "No hay usuarios."
        )
        return

    texto = "👥 Usuarios activos:\n\n"

    for user_id, expiration in users:

        if expiration:

            texto += f"{user_id}\nExpira: {expiration}\n\n"

        else:

            texto += f"{user_id}\nPermanente\n\n"

    await update.message.reply_text(texto)


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

    if duration == 0:
        expiration = None
    else:
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

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Bienvenido 💎\n\nElige una opción:",
        reply_markup=reply_markup
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

        await query.message.reply_text(
            "Introduce tu código:"
        )

        context.user_data["waiting_code"] = True
        return


# =========================
# TEXTO
# =========================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if context.user_data.get("waiting_code"):

        context.user_data["waiting_code"] = False

        await usar_codigo(update, context)


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

    telegram_app.add_handler(CommandHandler("start", start))

    telegram_app.add_handler(CommandHandler("generarcodigo", generar_codigo))

    telegram_app.add_handler(CommandHandler("usuarios", ver_usuarios))

    telegram_app.add_handler(CommandHandler("codigos", ver_codigos))

    telegram_app.add_handler(CommandHandler("borrarcodigo", borrar_codigo))

    telegram_app.add_handler(CallbackQueryHandler(button))

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    threading.Thread(
        target=expiration_thread
    ).start()

    print("Bot iniciado correctamente")

    telegram_app.run_polling()


if __name__ == "__main__":
    main()