from telegram import Update
from telegram.ext import ContextTypes

from bot_config import ADMIN_ID
from db import conn


async def debug_db(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    with conn.cursor() as cur:

        cur.execute("""

        SELECT COUNT(*)
        FROM users

        """)

        total = cur.fetchone()[0]

    await update.message.reply_text(
        f"Usuarios en DB: {total}"
    )


# =========================
# DEBUG LINKS
# =========================

async def debug_links(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    try:

        with conn.cursor() as cur:

            cur.execute("""

            SELECT COUNT(*)
            FROM invite_links

            """)

            total = cur.fetchone()[0]

        await update.message.reply_text(
            f"Links guardados: {total}"
        )

    except Exception as e:

        print("Error debug links:", e)

        await update.message.reply_text(
            "Error leyendo invite_links"
        )


# =========================
# DEBUG COLUMNAS invite_links
# =========================

async def debug_columns(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    try:

        with conn.cursor() as cur:

            cur.execute("""

            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'invite_links'

            """)

            columns = cur.fetchall()

        texto = "📋 Columnas invite_links:\n\n"

        for col in columns:

            texto += f"- {col[0]}\n"

        await update.message.reply_text(texto)

    except Exception as e:

        print("Error debug columns:", e)

        await update.message.reply_text(
            "Error leyendo columnas"
        )


# =========================
# DEBUG GROUPS
# =========================

async def debug_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id

                FROM groups

                ORDER BY id ASC

            """)

            rows = cur.fetchall()


        if not rows:

            await update.message.reply_text(
                "No hay grupos."
            )

            return


        texto = "📦 GROUPS DB\n\n"


        for row in rows:

            texto += (

                f"ID interno: {row[0]}\n"

                f"Nombre: {row[1]}\n"

                f"Telegram ID: {row[2]}\n\n"

            )


        await update.message.reply_text(texto)

    except Exception as e:

        print("Error debug groups:", e)

        await update.message.reply_text(
            f"Error: {e}"
        )


# =========================
# FIX DB - AÑADIR group_id
# =========================

async def fixdb_group_column(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    try:

        with conn.cursor() as cur:

            cur.execute("""

            ALTER TABLE invite_links
            ADD COLUMN group_id BIGINT;

            """)

        await update.message.reply_text(
            "✅ Columna group_id añadida correctamente."
        )

    except Exception as e:

        print("Error fixdb:", e)

        await update.message.reply_text(
            f"⚠️ Posible error (puede que ya exista): {e}"
        )
