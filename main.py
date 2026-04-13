from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from datetime import datetime, timedelta
from config import TOKEN, ADMIN_IDS, GROUP_ID
from db import create_tables, conn


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot funcionando ✅")


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

        expiration = datetime.now() + timedelta(days=days)

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, expiration)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET expiration=%s
            """, (user_id, expiration, expiration))

            conn.commit()

        invite_link = await context.bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "✅ Acceso aprobado\n\n"
                f"Tu acceso vence: {expiration}\n\n"
                "🔗 Aquí tienes tu enlace único:\n"
                f"{invite_link.invite_link}"
            )
        )

        await update.message.reply_text(
            "Usuario añadido y enlace enviado ✅"
        )

    except Exception as e:

        print("Error en adduser:", e)

        await update.message.reply_text(
            "Uso correcto: /adduser user_id días"
        )


# /removeuser
async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("No eres admin ❌")
        return

    try:
        user_id = int(context.args[0])

        await context.bot.ban_chat_member(
            chat_id=GROUP_ID,
            user_id=user_id
        )

        await context.bot.unban_chat_member(
            chat_id=GROUP_ID,
            user_id=user_id
        )

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM users WHERE user_id=%s",
                (user_id,)
            )
            conn.commit()

        await update.message.reply_text(
            "Usuario eliminado correctamente ⛔"
        )

    except Exception as e:

        print("Error en removeuser:", e)

        await update.message.reply_text(
            "Uso correcto: /removeuser user_id"
        )


# /renew
async def renew(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("No eres admin ❌")
        return

    try:
        user_id = int(context.args[0])
        days = int(context.args[1])

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET expiration = expiration + INTERVAL '%s days'
                WHERE user_id=%s
            """, (days, user_id))

            conn.commit()

        await update.message.reply_text(
            "Usuario renovado correctamente 🔄"
        )

    except Exception as e:

        print("Error en renew:", e)

        await update.message.reply_text(
            "Uso correcto: /renew user_id días"
        )


# /users
async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("No eres admin ❌")
        return

    with conn.cursor() as cur:
        cur.execute("""
            SELECT user_id, expiration FROM users
        """)

        result = cur.fetchall()

    if not result:
        await update.message.reply_text(
            "No hay usuarios activos."
        )
        return

    text = "Usuarios activos:\n\n"

    for user in result:

        text += (
            f"ID: {user[0]}\n"
            f"Expira: {user[1]}\n\n"
        )

    await update.message.reply_text(text)


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

        if not expiration:
            continue

        remaining = expiration - now

        try:

            # Aviso 24h
            if timedelta(hours=23, minutes=59) < remaining <= timedelta(hours=24):

                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ Tu acceso vence en 24 horas."
                )

            # Aviso 1h
            if timedelta(minutes=59) < remaining <= timedelta(hours=1):

                await context.bot.send_message(
                    chat_id=user_id,
                    text="⏰ Tu acceso vence en 1 hora."
                )

            # Expulsión
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
    app.add_handler(CommandHandler("id", id))
    app.add_handler(CommandHandler("adduser", adduser))
    app.add_handler(CommandHandler("removeuser", removeuser))
    app.add_handler(CommandHandler("renew", renew))
    app.add_handler(CommandHandler("users", users))

    app.job_queue.run_repeating(
        check_users,
        interval=60,
        first=10
    )

    print("Bot listo...")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()