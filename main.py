from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from datetime import datetime, timedelta
from config import TOKEN, ADMIN_IDS, GROUP_ID
from db import create_tables, conn


# LINKS STRIPE
LINK_1_DIA = "https://buy.stripe.com/dRm4gy1JY1fx1YAdOg8bS00"
LINK_7_DIAS = "https://buy.stripe.com/4gM6oG4Wa1fxbzaeSk8bS01"
LINK_PERMANENTE = "https://buy.stripe.com/fZu3cu9cq9M31YA39C8bS02"


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bienvenido al bot VIP 💎\n\n"
        "Usa /pagar para ver los planes disponibles."
    )


# /pagar
async def pagar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "🟢 1 día — 5€",
                url=LINK_1_DIA
            )
        ],
        [
            InlineKeyboardButton(
                "🟡 7 días — 10€",
                url=LINK_7_DIAS
            )
        ],
        [
            InlineKeyboardButton(
                "🔵 Permanente — 25€",
                url=LINK_PERMANENTE
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "💎 Elige tu plan VIP:\n\n"
        "Pulsa el botón para pagar.",
        reply_markup=reply_markup
    )


# /id
async def id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Tu ID es: {user_id}")


# /adduser
async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("No eres admin ❌")
        return

    try:
        user_id = int(context.args[0])
        days = int(context.args[1])

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

        await context.bot.unban_chat_member(
            chat_id=GROUP_ID,
            user_id=user_id
        )

        invite_link = await context.bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "✅ Pago recibido\n\n"
                "Aquí tienes tu enlace VIP:\n"
                f"{invite_link.invite_link}"
            )
        )

        await update.message.reply_text(
            "Usuario añadido correctamente ✅"
        )

    except Exception as e:

        print("Error en adduser:", e)

        await update.message.reply_text(
            "Uso correcto: /adduser user_id días"
        )


# Sistema automático
async def check_users(context: ContextTypes.DEFAULT_TYPE):

    with conn.cursor() as cur:
        cur.execute("""
            SELECT user_id, expiration FROM users
        """)

        users = cur.fetchall()

    now = datetime.now()

    for user in users:

        user_id = user[0]
        expiration = user[1]

        if expiration is None:
            continue

        try:

            if now > expiration:

                await context.bot.ban_chat_member(
                    chat_id=GROUP_ID,
                    user_id=user_id
                )

                await context.bot.unban_chat_member(
                    chat_id=GROUP_ID,
                    user_id=user_id
                )

                await context.bot.send_message(
                    chat_id=user_id,
                    text="⛔ Tu acceso ha expirado."
                )

                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM users WHERE user_id=%s",
                        (user_id,)
                    )
                    conn.commit()

                print(f"Usuario expulsado: {user_id}")

        except Exception as e:

            print(f"Error con usuario {user_id}: {e}")


def main():

    print("Iniciando bot...")

    create_tables()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pagar", pagar))
    app.add_handler(CommandHandler("id", id))
    app.add_handler(CommandHandler("adduser", adduser))

    app.job_queue.run_repeating(
        check_users,
        interval=60,
        first=10
    )

    print("Bot listo...")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()