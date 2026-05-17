from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from db import conn
from formatters import (
    format_tiempo_restante
)


# =========================
# START BOT — MENÚ GRUPOS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id


    # =========================
    # OBTENER GRUPOS ACTIVOS
    # =========================

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name

                FROM groups

                WHERE is_active=TRUE
                AND telegram_group_id != 0

                ORDER BY id ASC

            """)

            groups = cur.fetchall()

    except Exception as e:

        print("Error cargando grupos:", e)

        await update.message.reply_text(
            "❌ Error cargando grupos."
        )

        return


    if not groups:

        await update.message.reply_text(
            "⚠️ No hay grupos disponibles todavía."
        )

        return


    # =========================
    # CREAR BOTONES DE GRUPOS
    # =========================

    keyboard = []


    for group_id, group_name in groups:

        keyboard.append([

            InlineKeyboardButton(

                group_name,

                callback_data=f"group_{group_id}"

            )

        ])


    # =========================
    # NUEVO — BOTÓN MIS SUSCRIPCIONES
    # =========================

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT group_id

                FROM invite_links

                WHERE user_id=%s

            """, (user_id,))

            user_groups = cur.fetchall()


        if user_groups:

            keyboard.append([

                InlineKeyboardButton(

                    "🔐 Ver mis suscripciones activas",

                    callback_data="mis_subs"

                )

            ])

    except Exception as e:

        print("Error verificando suscripciones:", e)


    # =========================
    # COMPROBAR SUSCRIPCIONES ACTIVAS
    # =========================

    suscripciones_texto = ""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT g.name, u.expiration

                FROM invite_links il

                JOIN groups g
                ON il.group_id = g.telegram_group_id

                LEFT JOIN users u
                ON il.user_id = u.user_id

                WHERE il.user_id=%s

            """, (user_id,))

            rows = cur.fetchall()


        if rows:

            for group_name, expiration in rows:

                if expiration:

                    tiempo_texto = format_tiempo_restante(
                        expiration
                    )

                else:

                    tiempo_texto = "♾️ Permanente"


                suscripciones_texto += (

                    f"⏳ Tu suscripción actual al grupo {group_name}:\n"

                    f"{tiempo_texto}\n\n"

                )

    except Exception as e:

        print(
            "Error verificando suscripciones:",
            e
        )


    # =========================
    # MENSAJE BIENVENIDA
    # =========================

    suscripciones_texto = ""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT g.name, u.expiration

                FROM users u

                JOIN groups g
                ON u.group_id = g.id

                WHERE u.user_id=%s

                ORDER BY g.name ASC

            """, (user_id,))

            subs = cur.fetchall()

            if subs:

                for group_name, expiration in subs:

                    # FILTRAR EN PYTHON (no en SQL)

                    if expiration is None or expiration > datetime.now():

                        tiempo_texto = format_tiempo_restante(
                            expiration
                        )

                        suscripciones_texto += (

                            f"⏳ Tu suscripción actual al grupo "
                            f"({group_name}):\n"

                            f"{tiempo_texto}\n\n"

                        )

    except Exception as e:

        print(
            "Error cargando suscripciones:",
            e
        )


    if suscripciones_texto:

        mensaje = (

            "👋 Bienvenido\n\n"

            f"{suscripciones_texto}"

            "A continuación puedes ver los grupos disponibles para suscribirte.\n\n"

            "Selecciona uno para ver sus planes."

        )

    else:

        mensaje = (

            "👋 Bienvenido\n\n"

            "Nos alegra que estés aquí.\n\n"

            "A continuación puedes ver los grupos disponibles para suscribirte.\n\n"

            "Selecciona uno para ver sus planes."

        )


    message = update.message or update.callback_query.message


    await message.reply_text(

        mensaje,

        reply_markup=InlineKeyboardMarkup(keyboard)

    )
