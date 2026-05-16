from telegram import Update
from telegram.ext import ContextTypes

from db import conn


ADMIN_ID = 8761243211


# =========================
# VER CÓDIGOS
# =========================

async def ver_codigos(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT code,
                       duration,
                       used

                FROM invite_codes

                ORDER BY code DESC

                LIMIT 50

            """)

            rows = cur.fetchall()

    except Exception as e:

        print("Error cargando códigos:", e)

        await update.message.reply_text(
            "❌ Error cargando códigos."
        )

        return


    if not rows:

        await update.message.reply_text(
            "⚠️ No hay códigos disponibles."
        )

        return


    texto = "🎟️ Códigos:\n\n"


    for code, duration, used in rows:

        estado = "❌ usado" if used else "✅ activo"

        if duration == 0:

            duracion_texto = "♾️ Permanente"

        else:

            duracion_texto = f"{duration} min"


        texto += (

            f"{code}\n"
            f"{duracion_texto} — {estado}\n\n"

        )


    await update.message.reply_text(
        texto
    )


# =========================
# VER USUARIOS
# =========================

async def ver_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id,
                       expiration

                FROM users

                ORDER BY expiration DESC

            """)

            users = cur.fetchall()

    except Exception as e:

        print("Error cargando usuarios:", e)

        await update.message.reply_text(
            "❌ Error cargando usuarios."
        )

        return


    if not users:

        await update.message.reply_text(
            "⚠️ No hay usuarios registrados."
        )

        return


    texto = "👥 Usuarios:\n\n"


    for user_id, expiration in users:

        if expiration:

            texto += f"{user_id} — {expiration}\n"

        else:

            texto += f"{user_id} — ♾️ Permanente\n"


    await update.message.reply_text(
        texto
    )
