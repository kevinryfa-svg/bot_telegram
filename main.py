import os
import stripe
import threading
import random
import string
import requests
import time
import asyncio

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


# =========================
# FORMATEAR TIEMPO RESTANTE
# =========================

def format_tiempo_restante(expiration):

    if expiration is None:

        return "♾️ Permanente"

    tiempo_restante = expiration - datetime.now()

    total_segundos = int(
        tiempo_restante.total_seconds()
    )

    if total_segundos <= 0:

        return "Expirado"

    dias = total_segundos // 86400

    horas = (

        total_segundos % 86400

    ) // 3600

    minutos = (

        total_segundos % 3600

    ) // 60


    # Protección contra mostrar 0m cuando aún quedan segundos

    if dias == 0 and horas == 0 and minutos == 0:

        minutos = 1


    # Mostrar SIEMPRE días, horas y minutos

    return (

        f"{dias}d "

        f"{horas}h "

        f"{minutos}m"

    )


from db import conn, create_tables


# =========================
# CONFIG
# =========================

TOKEN = os.environ.get("TOKEN")
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
SERVER_URL = os.environ.get("SERVER_URL")

ADMIN_ID = 8761243211

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

bot = Bot(token=TOKEN)

telegram_app = ApplicationBuilder().token(TOKEN).build()

app = Flask(__name__)


# =========================
# HOME TEST
# =========================

@app.route("/")
def home():
    return "Bot funcionando"


# =========================
# RUN FLASK
# =========================

def run_flask():

    port = int(os.environ.get("PORT", 8000))

    app.run(
        host="0.0.0.0",
        port=port
    )


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
# REVOCAR LINK SEGURO
# =========================

def revoke_link(chat_id, link):

    try:

        response = requests.post(

            f"https://api.telegram.org/bot{TOKEN}/revokeChatInviteLink",

            json={
                "chat_id": chat_id,
                "invite_link": link
            }

        ).json()


        # =========================
        # IGNORAR EXPIRED
        # =========================

        if not response.get("ok"):

            description = response.get(
                "description",
                ""
            )

            if description != "Bad Request: INVITE_HASH_EXPIRED":

                print(
                    "Error real revocando:",
                    response
                )

    except Exception as e:

        print(
            "Error revoke_link:",
            e
        )


# =========================
# OBTENER GROUP_ID DINÁMICO
# =========================

def get_group_id():

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT telegram_group_id

                FROM groups

                WHERE telegram_group_id IS NOT NULL
                AND telegram_group_id != 0

                ORDER BY telegram_group_id DESC

                LIMIT 1

            """)

            row = cur.fetchone()

            if row and row[0]:

                telegram_group_id = int(row[0])

                # DEBUG SILENCIADO

                return telegram_group_id

    except Exception as e:

        print(
            "Error obteniendo telegram_group_id:",
            e
        )


    # DEBUG SILENCIADO

    return int(GROUP_ID)
    

# =========================
# CREAR CÓDIGO ADMIN
# =========================

async def generar_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [

        [InlineKeyboardButton("⏱️ 15 min", callback_data="gen_15")],
        [InlineKeyboardButton("📅 1 día", callback_data="gen_1440")],
        [InlineKeyboardButton("📅 7 días", callback_data="gen_10080")],
        [InlineKeyboardButton("📅 30 días", callback_data="gen_43200")],
        [InlineKeyboardButton("♾️ Permanente", callback_data="gen_perm")]

    ]

    await update.message.reply_text(

        "Selecciona duración:",

        reply_markup=InlineKeyboardMarkup(keyboard)

    )

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


# =========================
# USAR CÓDIGO
# =========================

async def receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # =========================
    # ⚠️ CONTROL GLOBAL — SOLO ACTUAR SI CORRESPONDE
    # =========================

    if not (
        context.user_data.get("waiting_code")
        or context.user_data.get("delete_code")
        or context.user_data.get("search_user")
        or context.user_data.get("kick_user")
        or context.user_data.get("ban_user")
        or context.user_data.get("unban_user")
    ):
        return

    # =========================
    # ELIMINAR CÓDIGO
    # =========================

    if context.user_data.get("delete_code"):

        code = update.message.text.strip().upper()

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_codes
                WHERE code=%s

            """, (code,))

            conn.commit()

        await update.message.reply_text(
            f"❌ Código eliminado:\n{code}"
        )

        context.user_data["delete_code"] = False

        return


    # =========================
    # BUSCAR USUARIO
    # =========================

    if context.user_data.get("search_user"):

        user_id = update.message.text.strip()

        with conn.cursor() as cur:

            cur.execute("""

                SELECT expiration
                FROM users
                WHERE user_id=%s

            """, (user_id,))

            row = cur.fetchone()

        if row:

            expiration = row[0]

            await update.message.reply_text(
                f"👤 Usuario {user_id}\nExpira: {expiration}"
            )

        else:

            await update.message.reply_text(
                "Usuario no encontrado"
            )

        context.user_data["search_user"] = False

        return


    # =========================
    # EXPULSAR USUARIO
    # =========================

    if context.user_data.get("kick_user"):

        user_id = update.message.text.strip()

        with conn.cursor() as cur:

            # eliminar usuario

            cur.execute("""

                DELETE FROM users
                WHERE user_id=%s

            """, (user_id,))


            # revocar links del usuario

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            links = cur.fetchall()

            for (link,) in links:

                try:

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/revokeChatInviteLink",

                        json={
                            "chat_id": get_group_id(),
                            "invite_link": link
                        }

                    )

                except Exception as e:

                    print("Error revocando link:", e)


            # borrar links

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            conn.commit()


        requests.post(

            f"https://api.telegram.org/bot{TOKEN}/banChatMember",

            json={
                "chat_id": get_group_id(),
                "user_id": user_id
            }

        )

        requests.post(

            f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

            json={
                "chat_id": get_group_id(),
                "user_id": user_id
            }

        )

        await update.message.reply_text(
            f"🚫 Usuario expulsado:\n{user_id}"
        )

        context.user_data["kick_user"] = False

        return


    # =========================
    # BAN PERMANENTE
    # =========================

    if context.user_data.get("ban_user"):

        user_id = update.message.text.strip()

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT invite_link
                    FROM invite_links
                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    get_group_id()

                ))

                links = cur.fetchall()

                for (link,) in links:

                    try:

                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/revokeChatInviteLink",

                            json={
                                "chat_id": get_group_id(),
                                "invite_link": link
                            }

                        )

                    except Exception as e:

                        print("Error revocando link:", e)


                # borrar avisos

                cur.execute("""

                    DELETE FROM invite_links
                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    get_group_id()

                ))


                # guardar en baneados

                cur.execute("""

                    INSERT INTO banned_users
                    (user_id)

                    VALUES (%s)

                    ON CONFLICT (user_id)
                    DO NOTHING

                """, (user_id,))


                # 🔴 NO ELIMINAR USUARIO
                # MANTENER USERS PARA CONSERVAR EXPIRATION

                print("Usuario marcado como baneado sin borrar users:", user_id)


                conn.commit()


            requests.post(

                f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                json={
                    "chat_id": get_group_id(),
                    "user_id": user_id
                }

            )


            await update.message.reply_text(
                f"⛔ Usuario baneado permanentemente:\n{user_id}"
            )

        except Exception as e:

            print("Error baneando:", e)


        context.user_data["ban_user"] = False

        return


    # =========================
    # DESBAN PERMANENTE
    # =========================

    if context.user_data.get("unban_user"):

        user_id = int(update.message.text.strip())

        try:

            with conn.cursor() as cur:

                # quitar de baneados

                cur.execute("""

                    DELETE FROM banned_users
                    WHERE user_id=%s

                """, (user_id,))


                # limpiar avisos

                cur.execute("""

                    DELETE FROM link_warnings
                    WHERE user_id=%s

                """, (user_id,))


                # 🔴 RESETEAR WARNINGS A 0 (CLAVE PARA EVITAR AVISOS FALSOS)

                cur.execute("""

                    INSERT INTO link_warnings
                    (user_id, warnings)

                    VALUES (%s, 0)

                    ON CONFLICT (user_id)
                    DO UPDATE SET warnings=0

                """, (user_id,))


                # 🔴 BORRAR LINKS ANTIGUOS (ESTO ARREGLA LOS WARNINGS)

                cur.execute("""

                    DELETE FROM invite_links
                    WHERE user_id=%s

                """, (user_id,))


                # comprobar si tiene suscripción válida

                cur.execute("""

                    SELECT expiration
                    FROM users
                    WHERE user_id=%s

                """, (user_id,))

                row = cur.fetchone()

                expiration = None

                if row:

                    expiration = row[0]

                else:

                    # 🔴 SI NO EXISTE EN USERS, CREARLO TEMPORALMENTE
                    # EVITA QUE SEA DETECTADO COMO INTRUSO

                    expiration = datetime.now() + timedelta(minutes=5)

                    cur.execute("""

                        INSERT INTO users
                        (user_id, expiration)

                        VALUES (%s, %s)

                        ON CONFLICT (user_id)
                        DO NOTHING

                    """, (user_id, expiration))


                # permitir volver a entrar

                requests.post(

                    f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                    json={
                        "chat_id": get_group_id(),
                        "user_id": user_id
                    }

                )


                # =========================
                # SI TIENE SUSCRIPCIÓN ACTIVA
                # =========================

                if expiration is None or expiration > datetime.now():

                    # calcular tiempo restante

                    tiempo_texto = format_tiempo_restante(
                        expiration
                    )


                    # borrar links antiguos

                    cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s

                    """, (user_id,))


                    # crear link nuevo

                    invite_link = requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

                        json={
                            "chat_id": get_group_id(),
                            "member_limit": 1
                        }

                    ).json()


                    link = invite_link["result"]["invite_link"]


                    # guardar link

                    cur.execute("""

                        INSERT INTO invite_links
                        (user_id, group_id, invite_link)

                        VALUES (%s, %s, %s)

                    """, (

                        user_id,
                        get_group_id(),
                        link

                    ))


                    conn.commit()


                    # enviar link nuevo con tiempo restante

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                        json={

                            "chat_id": user_id,

                            "text":

                            "♻️ Has sido desbaneado.\n\n"

                            "Tu suscripción sigue activa.\n\n"

                            f"⏳ Tiempo restante: {tiempo_texto}\n\n"

                            "Aquí tienes tu nuevo acceso:\n\n"

                            f"{link}"

                        }

                    )


                    await update.message.reply_text(

                        f"♻️ Usuario desbaneado y link enviado:\n{user_id}"

                    )


                else:

                    conn.commit()


                    await update.message.reply_text(

                        f"♻️ Usuario desbaneado:\n{user_id}"

                    )


        except Exception as e:

            print("Error desbaneando:", e)


        context.user_data["unban_user"] = False

        return
    

    # =========================
    # CREACIÓN GRUPO — WIZARD
    # =========================

    if context.user_data.get("creating_group"):

        step = context.user_data.get("group_step")

        text = update.message.text.strip()


        # PASO 1 — NOMBRE GRUPO

        if step == 1:

            context.user_data["new_group_data"]["name"] = text

            context.user_data["group_step"] = 2

            await update.message.reply_text(

                "Paso 2️⃣\n\n"

                "Envía ahora el ID del grupo de Telegram.\n\n"

                "⚠️ El bot debe estar añadido como ADMIN."

            )

            return


        # =========================
        # PASO 2 — GROUP ID
        # =========================

        if step == 2:

            try:

                group_id = int(text)

            except:

                await update.message.reply_text(
                    "❌ ID inválido. Intenta nuevamente."
                )

                return


            context.user_data["new_group_data"]["telegram_group_id"] = group_id
            context.user_data["group_step"] = 3

            await update.message.reply_text(

                "Paso 3️⃣\n\n"

                "Verificando permisos del bot..."

            )


            # Verificar bot admin

            try:

                bot_id = int(TOKEN.split(":")[0])

                r = requests.get(

                    f"https://api.telegram.org/bot{TOKEN}/getChatMember",

                    params={

                        "chat_id": group_id,
                        "user_id": bot_id

                    }

                ).json()


                status = r["result"]["status"]

                if status not in ["administrator", "creator"]:

                    await update.message.reply_text(

                        "❌ El bot no es administrador del grupo."

                    )

                    return


            except Exception as e:

                print("Error verificando admin:", e)

                await update.message.reply_text(

                    "❌ No se pudo verificar el grupo."

                )

                return


            context.user_data["group_step"] = 4

            await update.message.reply_text(

                "Paso 4️⃣\n\n"

                "¿Cuántos planes quieres crear?\n\n"

                "Ejemplo: 1, 2, 3..."

            )

            return
    
    # =========================
    # CREACIÓN PLANES — PASO 4
    # =========================

        if step == 4:

            try:

                total_plans = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            context.user_data["new_group_data"]["total_plans"] = total_plans
            context.user_data["new_group_data"]["plans"] = []

            context.user_data["current_plan"] = 1
            context.user_data["group_step"] = 5

            await update.message.reply_text(

                f"Paso 5️⃣\n\n"

                f"Introduce el NOMBRE del plan 1."

            )

            return


        # =========================
        # PASO 5 — NOMBRE PLAN
        # =========================

        if step == 5:

            context.user_data["current_plan_name"] = text
            context.user_data["group_step"] = 6

            await update.message.reply_text(

                "Paso 6️⃣\n\n"

                "Introduce el PRICE ID de Stripe."

            )

            return


        # =========================
        # PASO 6 — PRICE ID
        # =========================

        if step == 6:

            context.user_data["current_price_id"] = text
            context.user_data["group_step"] = 7

            await update.message.reply_text(

                "Paso 7️⃣\n\n"

                "Introduce duración en días."

            )

            return


        # =========================
        # PASO 7 — DURACIÓN
        # =========================

        if step == 7:

            try:

                duration_days = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            context.user_data["current_duration"] = duration_days
            context.user_data["group_step"] = 8

            await update.message.reply_text(

                "Paso 8️⃣\n\n"

                "Introduce el PRECIO del plan.\n"

                "Ejemplo: 10"

            )

            return


        # =========================
        # PASO 8 — PRECIO
        # =========================

        if step == 8:

            try:

                amount = int(text)

            except:

                await update.message.reply_text(
                    "❌ Precio inválido."
                )

                return


            context.user_data["current_amount"] = amount
            context.user_data["group_step"] = 9

            await update.message.reply_text(

                "Paso 9️⃣\n\n"

                "Introduce la MONEDA.\n"

                "Ejemplo: EUR"

            )

            return


        # =========================
        # PASO 9 — MONEDA
        # =========================

        if step == 9:

            currency = text.upper()


            plans = context.user_data["new_group_data"]["plans"]

            plans.append({

                "name": context.user_data["current_plan_name"],
                "price_id": context.user_data["current_price_id"],
                "duration_days": context.user_data["current_duration"],
                "amount": context.user_data["current_amount"],
                "currency": currency

            })


            total_plans = context.user_data["new_group_data"]["total_plans"]

            current = context.user_data["current_plan"]


            if current < total_plans:

                context.user_data["current_plan"] += 1
                context.user_data["group_step"] = 5

                next_plan = context.user_data["current_plan"]

                await update.message.reply_text(

                    f"Plan {next_plan}\n\n"

                    "Introduce el NOMBRE del plan."

                )

                return


            # =========================
            # GUARDAR PLANES EN DB
            # =========================

            group_data = context.user_data["new_group_data"]

            group_name = group_data["name"]
            telegram_group_id = group_data["telegram_group_id"]


            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id
                    FROM groups
                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                row = cur.fetchone()


                if row:

                    group_id = row[0]

                else:

                    cur.execute("""

                        INSERT INTO groups
                        (name, telegram_group_id)

                        VALUES (%s, %s)

                        RETURNING id

                    """, (

                        group_name,
                        telegram_group_id

                    ))

                    group_id = cur.fetchone()[0]


                for plan in group_data["plans"]:

                    cur.execute("""

                        INSERT INTO plans
                        (
                            group_id,
                            name,
                            price_id,
                            duration_days,
                            amount,
                            currency
                        )

                        VALUES (%s, %s, %s, %s, %s, %s)

                    """, (

                        group_id,
                        plan["name"],
                        plan["price_id"],
                        plan["duration_days"],
                        plan["amount"],
                        plan["currency"]

                    ))


            await update.message.reply_text(

                "✅ Grupo y planes creados correctamente."

            )


            context.user_data["creating_group"] = False

            return

async def receive_admin_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # =========================
    # RECIBIR PREVIEW MEDIA
    # =========================

    if context.user_data.get("editing_preview"):

        file_id = None

        if update.message.photo:

            file_id = update.message.photo[-1].file_id

        elif update.message.video:

            file_id = update.message.video.file_id

        else:

            await update.message.reply_text(
                "❌ Debes enviar imagen o video."
            )

            return


        context.user_data["new_preview_file"] = file_id


        keyboard = [

            [InlineKeyboardButton(
                "💾 Guardar cambios",
                callback_data="save_preview"
            )],

            [InlineKeyboardButton(
                "❌ Descartar",
                callback_data="cancel_preview"
            )]

        ]


        await update.message.reply_text(

            "Preview recibido.\n\n"

            "¿Deseas guardar cambios?",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if context.user_data.get("editing_plan"):

        step = context.user_data.get("edit_plan_step")

        text = update.message.text.strip()


        # =========================
        # PASO 1 — NUEVO NOMBRE
        # =========================

        if step == 1:

            context.user_data["edit_plan_name"] = text
            context.user_data["edit_plan_step"] = 2

            await update.message.reply_text(

                "Paso 2️⃣\n\n"

                "Introduce el nuevo PRICE ID."

            )

            return


        # =========================
        # PASO 2 — NUEVO PRICE ID
        # =========================

        if step == 2:

            context.user_data["edit_plan_price"] = text
            context.user_data["edit_plan_step"] = 3

            await update.message.reply_text(

                "Paso 3️⃣\n\n"

                "Introduce la nueva duración en días."

            )

            return


        # =========================
        # PASO 3 — NUEVA DURACIÓN
        # =========================

        if step == 3:

            try:

                duration_days = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            context.user_data["edit_plan_duration"] = duration_days
            context.user_data["edit_plan_step"] = 4

            await update.message.reply_text(

                "Paso 4️⃣\n\n"

                "Introduce el nuevo PRECIO."

            )

            return


        # =========================
        # PASO 4 — NUEVO PRECIO
        # =========================

        if step == 4:

            try:

                amount = int(text)

            except:

                await update.message.reply_text(
                    "❌ Precio inválido."
                )

                return


            context.user_data["edit_plan_amount"] = amount
            context.user_data["edit_plan_step"] = 5

            await update.message.reply_text(

                "Paso 5️⃣\n\n"

                "Introduce la nueva MONEDA."

            )

            return


        # =========================
        # PASO 5 — NUEVA MONEDA
        # =========================

        if step == 5:

            currency = text.upper()

            plan_id = context.user_data.get("editing_plan_id")

            name = context.user_data.get("edit_plan_name")

            price_id = context.user_data.get("edit_plan_price")

            duration_days = context.user_data.get("edit_plan_duration")

            amount = context.user_data.get("edit_plan_amount")


            try:

                with conn.cursor() as cur:

                    cur.execute("""

                        UPDATE plans

                        SET
                            name=%s,
                            price_id=%s,
                            duration_days=%s,
                            amount=%s,
                            currency=%s

                        WHERE id=%s

                    """, (

                        name,
                        price_id,
                        duration_days,
                        amount,
                        currency,
                        plan_id

                    ))

                    conn.commit()

            except Exception as e:

                print("Error editando plan:", e)

                await update.message.reply_text(
                    "❌ Error editando plan."
                )

                return


            context.user_data["editing_plan"] = False

            await update.message.reply_text(

                "✅ Plan actualizado correctamente."

            )

            return


    # =========================
    # AÑADIR PLAN — WIZARD
    # =========================

    if context.user_data.get("adding_plan"):

        step = context.user_data.get("add_plan_step")

        text = update.message.text.strip()

        group_id = context.user_data.get("selected_group_admin")


        # =========================
        # PASO 1 — NOMBRE
        # =========================

        if step == 1:

            context.user_data.setdefault("new_plan", {})

            context.user_data["new_plan"]["name"] = text
            context.user_data["add_plan_step"] = 2

            await update.message.reply_text(

                "Paso 2️⃣\n\n"
                "Introduce el PRICE ID."

            )

            return


        # =========================
        # PASO 2 — PRICE ID
        # =========================

        if step == 2:

            context.user_data["new_plan"]["price_id"] = text
            context.user_data["add_plan_step"] = 3

            await update.message.reply_text(

                "Paso 3️⃣\n\n"
                "Introduce duración en días."

            )

            return


        # =========================
        # PASO 3 — DURACIÓN
        # =========================

        if step == 3:

            try:

                duration_days = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            context.user_data["new_plan"]["duration_days"] = duration_days
            context.user_data["add_plan_step"] = 4

            await update.message.reply_text(

                "Paso 4️⃣\n\n"
                "Introduce el PRECIO."

            )

            return


        # =========================
        # PASO 4 — PRECIO
        # =========================

        if step == 4:

            try:

                amount = int(text)

            except:

                await update.message.reply_text(
                    "❌ Precio inválido."
                )

                return


            context.user_data["new_plan"]["amount"] = amount
            context.user_data["add_plan_step"] = 5

            await update.message.reply_text(

                "Paso 5️⃣\n\n"
                "Introduce la MONEDA (EUR, USD...)."

            )

            return


        # =========================
        # PASO 5 — MONEDA Y GUARDAR
        # =========================

        if step == 5:

            currency = text.upper()

            plan = context.user_data["new_plan"]

            try:

                with conn.cursor() as cur:

                    cur.execute("""

                        INSERT INTO plans
                        (
                            group_id,
                            name,
                            price_id,
                            duration_days,
                            amount,
                            currency
                        )

                        VALUES (%s, %s, %s, %s, %s, %s)

                    """, (

                        group_id,
                        plan["name"],
                        plan["price_id"],
                        plan["duration_days"],
                        plan["amount"],
                        currency

                    ))

                    conn.commit()

            except Exception as e:

                print("Error guardando plan:", e)

                await update.message.reply_text(
                    "❌ Error guardando plan."
                )

                return


            context.user_data["adding_plan"] = False
            context.user_data.pop("new_plan", None)

            await update.message.reply_text(

                "✅ Plan creado correctamente."

            )

            return


    # =========================
    # USO NORMAL DE CÓDIGO
    # =========================

    if context.user_data.get("waiting_code"):

        await receive_code(update, context)

        return

    # ⚠️ IMPORTANTE:
    # Si no estamos esperando código → NO procesar

    if not context.user_data.get("waiting_code"):
        return

    user_code = update.message.text.strip().upper()

    with conn.cursor() as cur:

        cur.execute("""

            SELECT user_id
            FROM banned_users
            WHERE user_id=%s

        """, (update.effective_user.id,))

        banned = cur.fetchone()

        if banned:

            await update.message.reply_text(
                "⛔ Estás baneado permanentemente."
            )

            return


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

            INSERT INTO users
            (user_id, username, first_name, expiration)

            VALUES (%s, %s, %s, %s)

            ON CONFLICT (user_id)
            DO UPDATE SET

                username=%s,
                first_name=%s,
                expiration=%s

        """, (

            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.first_name,
            expiration,
            update.effective_user.username,
            update.effective_user.first_name,
            expiration

        ))

        cur.execute("""

            UPDATE invite_codes
            SET used=TRUE
            WHERE code=%s

        """, (user_code,))


        cur.execute("""

            SELECT invite_link
            FROM invite_links
            WHERE user_id=%s
            AND group_id=%s

        """, (

            update.effective_user.id,
            get_group_id()

        ))


        old_links = cur.fetchall()

        for (old_link,) in old_links:

            try:

                revoke_link(
                    get_group_id(),
                    old_link
                )

                cur.execute("""

                    UPDATE invite_links

                    SET is_active=FALSE,
                        revoked_at=NOW()

                    WHERE invite_link=%s

                """, (old_link,))

            except Exception as e:

                print("Error revocando link:", e)


        # borrar antiguos

        cur.execute("""

            DELETE FROM invite_links
            WHERE user_id=%s
            AND group_id=%s

        """, (

            update.effective_user.id,
            get_group_id()

        ))

        conn.commit()


    invite_link = requests.post(

        f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

        json={
            "chat_id": get_group_id(),
            "member_limit": 1
        }

    ).json()


    link = invite_link["result"]["invite_link"]


    try:

        with conn.cursor() as cur:

            cur.execute("""

    INSERT INTO invite_links
    (user_id, group_id, invite_link)

    VALUES (%s, %s, %s)

""", (

    update.effective_user.id,
    get_group_id(),
    link

))

            conn.commit()

    except Exception as e:

        print("Error guardando invite link:", e)


    # =========================
    # CALCULAR TIEMPO RESTANTE
    # =========================

    tiempo_texto = format_tiempo_restante(
        expiration
    )


    await update.message.reply_text(

        "🔗 Acceso concedido\n\n"

        f"⏳ Tiempo restante: {tiempo_texto}\n\n"

        f"{link}"

    )


    context.user_data["waiting_code"] = False


# =========================
# STRIPE CHECKOUT
# =========================

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():

    data = request.json

    telegram_id = data["telegram_id"]
    plan = data["plan"]
    group_id = data.get("group_id")

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT price_id

                FROM plans

                WHERE price_id=%s
                AND group_id=%s
                AND is_active=TRUE

            """, (

                plan,
                group_id

            ))

            row = cur.fetchone()

        if not row:

            return jsonify({"error": "Plan inválido"}), 400

        price_id = row[0]

    except Exception as e:

        print("Error obteniendo price_id:", e)

        return jsonify({"error": "Error interno"}), 500


    try:

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
                "telegram_id": str(telegram_id),
                "group_id": str(group_id),
                "price_id": price_id
            }

        )

    except Exception as e:

        print("Error creando sesión Stripe:", e)

        return jsonify({"error": "Error creando sesión"}), 500


    return jsonify({
        "url": session.url
    })


# =========================
# WEBHOOK STRIPE
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

        user_id = int(
            session["metadata"]["telegram_id"]
        )


        # =========================
        # COMPROBAR SI ESTÁ BANEADO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id
                FROM banned_users
                WHERE user_id=%s

            """, (user_id,))

            banned = cur.fetchone()

            if banned:

                print("Usuario baneado intentó pagar:", user_id)

                return "OK"


        # =========================
        # OBTENER PLAN PAGADO
        # =========================

        line_items = stripe.checkout.Session.list_line_items(
            session["id"]
        )

        price_id = line_items["data"][0]["price"]["id"]

        metadata_group_id = int(
            session["metadata"]["group_id"]
        )

        # =========================
        # CALCULAR DURACIÓN
        # =========================

        try:

            metadata_group_id = int(
                session["metadata"]["group_id"]
            )

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT duration_days, name

                    FROM plans

                    WHERE price_id=%s
                    AND group_id=%s

                """, (

                    price_id,
                    metadata_group_id

                ))

                row = cur.fetchone()


            if not row:

                print(
                    "ERROR: plan no encontrado:",
                    price_id,
                    metadata_group_id
                )

                expiration = None
                plan_name = "Desconocido"

            else:

                duration_days, plan_name = row

                # Protección contra valores inválidos

                if duration_days is None or duration_days == 0:

                    expiration = None

                else:

                    duration_value = int(duration_days)

                    # =========================
                    # MODO INTELIGENTE DURACIÓN
                    # < 1440 → minutos
                    # >= 1440 → días
                    # =========================

                    if duration_value < 1440:

                        expiration = datetime.now() + timedelta(
                            minutes=duration_value
                        )

                    else:

                        expiration = datetime.now() + timedelta(
                            days=duration_value // 1440
                        )

        except Exception as e:

            print(
                "Error calculando duración:",
                e
            )

            expiration = None
            plan_name = "Error"


        # =========================
        # GUARDAR USUARIO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

            INSERT INTO users
            (user_id, group_id, expiration)

            VALUES (%s, %s, %s)

            ON CONFLICT (user_id, group_id)

            DO UPDATE SET expiration=%s

            """, (

                user_id,
                metadata_group_id,
                expiration,
                expiration

            ))


            # =========================
            # REGISTRAR PAGO
            # =========================

            cur.execute("""

            INSERT INTO payments
            (user_id, plan)

            VALUES (%s, %s)

            """, (

                user_id,
                plan_name

            ))


            conn.commit()


        print("Usuario guardado:", user_id)


        # =========================
        # CREAR LINK VIP (1 uso)
        # =========================

        group_id = int(
            session["metadata"]["group_id"]
        )

        # Obtener telegram_group_id real

        with conn.cursor() as cur:

            cur.execute("""

                SELECT telegram_group_id

                FROM groups

                WHERE id=%s

            """, (group_id,))

            row = cur.fetchone()

            if not row:

                print("ERROR: grupo no encontrado en DB:", group_id)

                return "OK"

            telegram_group_id = row[0]


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        max_expire = int(time.time()) + 180

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        invite_link = requests.post(

            f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

            json={
                "chat_id": telegram_group_id,
                "member_limit": 1,
                "expire_date": expire_timestamp
            }

        ).json()


        print("Respuesta createChatInviteLink:", invite_link)


        if "result" not in invite_link:

            print("ERROR creando invite link:", invite_link)

            return "OK"


        link = invite_link["result"]["invite_link"]


        # =========================
        # GUARDAR LINK EN DATABASE
        # =========================

        try:

            with conn.cursor() as cur:

                # borrar links antiguos

                cur.execute("""

                    DELETE FROM invite_links
                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    telegram_group_id

                ))


                # guardar nuevo

                cur.execute("""

                    INSERT INTO invite_links
                    (user_id, group_id, invite_link)

                    VALUES (%s, %s, %s)

                """, (

                    user_id,
                    telegram_group_id,
                    link

                ))


                conn.commit()

        except Exception as e:

            print("Error guardando invite link:", e)


        # =========================
        # ENVIAR LINK AL USUARIO
        # =========================

        requests.post(

            f"https://api.telegram.org/bot{TOKEN}/sendMessage",

            json={
                "chat_id": user_id,
                "text": f"🔗 Tu acceso VIP:\n{link}"
            }

        )


        # =========================
        # AVISAR AL ADMIN
        # =========================

        requests.post(

            f"https://api.telegram.org/bot{TOKEN}/sendMessage",

            json={
                "chat_id": ADMIN_ID,
                "text":
                f"💳 Nuevo pago recibido\n\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}"
            }

        )


        print("Pago confirmado:", user_id)


    return "OK"


# =========================
# CONTROL ENTRADAS GRUPO
# =========================

async def check_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    if not update.message.new_chat_members:
        return

    for member in update.message.new_chat_members:

        telegram_group_id = update.message.chat.id

        user_id = member.id

        # =========================
        # IGNORAR AL BOT
        # =========================

        if user_id == context.bot.id:

            print("Bot detectado entrando — ignorando control.")

            return

        try:

            with conn.cursor() as cur:

                # =========================
                # 🔒 COMPROBAR SI ESTÁ BANEADO
                # =========================

                cur.execute("""

                SELECT user_id
                FROM banned_users
                WHERE user_id=%s

                """, (user_id,))

                banned = cur.fetchone()

                if banned:

                    print("Usuario baneado detectado:", user_id)

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                        json={
                            "chat_id": telegram_group_id,
                            "user_id": user_id
                        }

                    )

                    return


                # =========================
                # 🔎 BUSCAR USUARIO AUTORIZADO
                # =========================

                cur.execute("""

                SELECT expiration
                FROM users
                WHERE user_id=%s

                """, (user_id,))

                row = cur.fetchone()


                # =========================
                # ❌ NO EXISTE → LINK COMPARTIDO
                # =========================

                if not row:

                    print("Intruso detectado:", user_id)


                    # expulsar intruso

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                        json={
                            "chat_id": telegram_group_id,
                            "user_id": user_id
                        }

                    )

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                        json={
                            "chat_id": telegram_group_id,
                            "user_id": user_id
                        }

                    )


                    # buscar dueño del link

                    used_link = None

                    try:

                        if hasattr(update.message, "invite_link"):

                            used_link = update.message.invite_link.invite_link

                    except Exception as e:

                        print("Error obteniendo invite_link:", e)

                        used_link = None


                    owner = None

                    # =========================
                    # INTENTAR BUSCAR OWNER POR LINK
                    # =========================

                    if used_link:

                        cur.execute("""

                        SELECT user_id
                        FROM invite_links
                        WHERE invite_link=%s
                        AND group_id=%s

                        """, (

                            used_link,
                            telegram_group_id

                        ))

                        owner = cur.fetchone()

                        print("Owner encontrado por link:", owner)


                    # =========================
                    # SI NO HAY LINK → BUSCAR ÚLTIMO LINK
                    # =========================

                    if not owner:

                        print("Fallback activado — buscando último link")

                        owner = None

                        cur.execute("""

                        SELECT user_id
                        FROM invite_links
                        WHERE group_id=%s
                        ORDER BY created_at DESC
                        LIMIT 1

                        """, (telegram_group_id,))

                        fallback_owner = cur.fetchone()

                        if fallback_owner:

                            owner_id = fallback_owner[0]

                            # =========================
                            # SI EL QUE ENTRA NO ES EL OWNER
                            # =========================

                            if user_id != owner_id:

                                print("Intruso detectado por fallback:", user_id)

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                                    json={
                                        "chat_id": telegram_group_id,
                                        "user_id": user_id
                                    }

                                )

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                                    json={
                                        "chat_id": telegram_group_id,
                                        "user_id": user_id
                                    }

                                )

                            owner = (owner_id,)

                            print("Owner encontrado por fallback:", owner_id)

                            # =========================
                            # FORZAR EJECUCIÓN WARNINGS
                            # =========================

                            warnings = 0

                            if owner:

                                owner_id = owner[0]

                                print(
                                    "Owner encontrado por fallback:",
                                    owner_id
                                )

                                # =========================
                                # SUMAR AVISO
                                # =========================

                                cur.execute("""

                                    INSERT INTO link_warnings
                                    (user_id, warnings)

                                    VALUES (%s, 1)

                                    ON CONFLICT (user_id)

                                    DO UPDATE SET

                                        warnings = link_warnings.warnings + 1

                                    RETURNING warnings

                                """, (owner_id,))

                                warnings = cur.fetchone()[0]


                                # =========================
                                # REVOCAR LINKS
                                # =========================


                            cur.execute("""

                            SELECT invite_link
                            FROM invite_links
                            WHERE user_id=%s
                            AND group_id=%s

                            """, (

                                owner_id,
                                telegram_group_id

                            ))

                            links = cur.fetchall()

                            for (link,) in links:

                                try:

                                    requests.post(

                                        f"https://api.telegram.org/bot{TOKEN}/revokeChatInviteLink",

                                        json={
                                            "chat_id": telegram_group_id,
                                            "invite_link": link
                                        }

                                    )

                                except Exception as e:

                                    print("Error revocando link:", e)


                            cur.execute("""

                            DELETE FROM invite_links
                            WHERE user_id=%s
                            AND group_id=%s

                            """, (

                                owner_id,
                                telegram_group_id

                            ))


                        # =========================
                        # SI LLEGA A 3 → BAN
                        # =========================

                        if warnings >= 3:

                            cur.execute("""

                            INSERT INTO banned_users
                            (user_id)

                            VALUES (%s)

                            ON CONFLICT DO NOTHING

                            """, (owner_id,))

                            conn.commit()


                            requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                                json={
                                    "chat_id": telegram_group_id,
                                    "user_id": owner_id
                                }

                            )


                            requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                json={

                                    "chat_id": owner_id,

                                    "text":

                                    "⛔ Has sido baneado permanentemente.\n\n"

                                    "Motivo: Compartir links repetidamente."

                                }

                            )


                            requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                json={

                                    "chat_id": ADMIN_ID,

                                    "text":

                                    f"⛔ USUARIO BANEADO\n\n"

                                    f"User ID: {owner_id}\n"

                                    f"Motivo: 3/3 advertencias."

                                }

                            )


                        else:






                            # =========================
                            # CREAR LINK NUEVO
                            # =========================

                            # =========================
                            # OBTENER EXPIRACIÓN OWNER
                            # =========================

                            cur.execute("""

                                SELECT expiration
                                FROM users
                                WHERE user_id=%s

                            """, (owner_id,))

                            owner_row = cur.fetchone()

                            owner_expiration = None

                            if owner_row:

                                owner_expiration = owner_row[0]


                            # =========================
                            # CALCULAR EXPIRACIÓN REAL
                            # =========================

                            max_expire = int(time.time()) + 180

                            if owner_expiration is None:

                                expire_timestamp = max_expire

                            else:

                                subscription_expire = int(
                                    owner_expiration.timestamp()
                                )

                                expire_timestamp = min(
                                    max_expire,
                                    subscription_expire
                                )


                            invite_link = requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

                                json={
                                    "chat_id": telegram_group_id,
                                    "member_limit": 1,
                                    "expire_date": expire_timestamp
                                }

                            ).json()


                            if "result" in invite_link:

                                new_link = invite_link["result"]["invite_link"]

                            else:

                                print(
                                    "Error creando nuevo link:",
                                    invite_link
                                )

                                return


                            # =========================
                            # GUARDAR LINK NUEVO
                            # =========================

                            cur.execute("""

                                INSERT INTO invite_links
                                (user_id, group_id, invite_link)

                                VALUES (%s, %s, %s)

                            """, (

                                owner_id,
                                telegram_group_id,
                                new_link

                            ))

                            conn.commit()


                            # =========================
                            # ENVIAR AVISO AL USUARIO
                            # =========================

                            requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                json={

                                    "chat_id": owner_id,

                                    "text":

                                    f"⚠️ AVISO {warnings}/3\n\n"

                                    "Hemos detectado que has compartido tu link.\n\n"

                                    "Tu link anterior ha sido invalidado.\n"

                                    "Aquí tienes uno nuevo:\n\n"

                                    f"{new_link}\n\n"

                                    "Si llegas a 3 avisos serás baneado."

                                }

                            )


                            # =========================
                            # ENVIAR AVISO AL ADMIN
                            # =========================

                            requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                json={

                                    "chat_id": ADMIN_ID,

                                    "text":

                                    f"⚠️ LINK COMPARTIDO\n\n"

                                    f"Usuario: {owner_id}\n"

                                    f"Aviso: {warnings}/3\n"

                                    f"Intruso: {user_id}"

                                }

                            )

                            return


                else:

                    expiration = row[0]


                    # =========================
                    # VERIFICAR QUE TIENE LINK ASIGNADO
                    # =========================

                    cur.execute("""

                    SELECT id
                    FROM invite_links
                    WHERE user_id=%s
                    AND group_id=%s

                    """, (

                        user_id,
                        telegram_group_id

                    ))

                    link_exists = cur.fetchone()

                    if not link_exists:

                        print("Intruso sin link asignado:", user_id)

                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                            json={
                                "chat_id": telegram_group_id,
                                "user_id": user_id
                            }

                        )

                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                            json={
                                "chat_id": telegram_group_id,
                                "user_id": user_id
                            }

                        )

                        # =========================
                        # BUSCAR OWNER POR FALLBACK
                        # =========================

                        owner = None

                        warnings = 0

                        cur.execute("""

                        SELECT user_id
                        FROM invite_links
                        WHERE group_id=%s
                        ORDER BY created_at DESC
                        LIMIT 1

                        """, (telegram_group_id,))

                        fallback_owner = cur.fetchone()

                        if fallback_owner:

                            owner_id = fallback_owner[0]

                            owner = (owner_id,)

                            print(
                                "Owner encontrado por fallback:",
                                owner_id
                            )

                            # =========================
                            # SUMAR AVISO
                            # =========================

                            cur.execute("""

                                INSERT INTO link_warnings
                                (user_id, warnings)

                                VALUES (%s, 1)

                                ON CONFLICT (user_id)

                                DO UPDATE SET

                                    warnings = link_warnings.warnings + 1

                                RETURNING warnings

                            """, (owner_id,))

                            row = cur.fetchone()

                            if not row:

                                warnings = 1

                            else:

                                warnings = row[0]

                            print(
                                "Warnings actuales:",
                                warnings
                            )

                            # =========================
                            # BAN SI LLEGA A 3
                            # =========================

                            if warnings >= 3:

                                print(
                                    "Usuario baneado por warnings:",
                                    owner_id
                                )

                                cur.execute("""

                                    INSERT INTO banned_users
                                    (user_id)

                                    VALUES (%s)

                                    ON CONFLICT DO NOTHING

                                """, (owner_id,))

                                conn.commit()

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                                    json={
                                        "chat_id": telegram_group_id,
                                        "user_id": owner_id
                                    }

                                )

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                    json={

                                        "chat_id": owner_id,

                                        "text":

                                        "⛔ Has sido baneado permanentemente.\n\n"

                                        "Motivo: Compartir links repetidamente."

                                    }

                                )

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                    json={

                                        "chat_id": ADMIN_ID,

                                        "text":

                                        f"⛔ USUARIO BANEADO\n\n"

                                        f"User ID: {owner_id}"

                                    }

                                )

                                return

                            # =========================
                            # REVOCAR LINKS DEL OWNER
                            # =========================

                            cur.execute("""

                                SELECT invite_link
                                FROM invite_links
                                WHERE user_id=%s
                                AND group_id=%s

                            """, (

                                owner_id,
                                telegram_group_id

                            ))

                            links = cur.fetchall()

                            for (link,) in links:

                                try:

                                    requests.post(

                                        f"https://api.telegram.org/bot{TOKEN}/revokeChatInviteLink",

                                        json={
                                            "chat_id": telegram_group_id,
                                            "invite_link": link
                                        }

                                    )

                                except Exception as e:

                                    print(
                                        "Error revocando link:",
                                        e
                                    )

                            # =========================
                            # BORRAR LINKS ANTIGUOS
                            # =========================

                            cur.execute("""

                                DELETE FROM invite_links
                                WHERE user_id=%s
                                AND group_id=%s

                            """, (

                                owner_id,
                                telegram_group_id

                            ))

                            conn.commit()

                            # =========================
                            # CREAR LINK NUEVO
                            # =========================

                            invite_link = requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

                                json={
                                    "chat_id": telegram_group_id,
                                    "member_limit": 1,
                                    "expire_date": int(time.time()) + 60
                                }

                            ).json()

                            if "result" in invite_link:

                                new_link = invite_link["result"]["invite_link"]

                                # =========================
                                # GUARDAR LINK NUEVO
                                # =========================

                                cur.execute("""

                                    INSERT INTO invite_links
                                    (user_id, group_id, invite_link)

                                    VALUES (%s, %s, %s)

                                """, (

                                    owner_id,
                                    telegram_group_id,
                                    new_link

                                ))

                                conn.commit()

                                # =========================
                                # ENVIAR AVISO USUARIO
                                # =========================

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                    json={

                                        "chat_id": owner_id,

                                        "text":

                                        f"⚠️ AVISO {warnings}/3\n\n"

                                        "Hemos detectado que has compartido tu link.\n\n"

                                        "Tu link anterior ha sido invalidado.\n"

                                        "Aquí tienes uno nuevo:\n\n"

                                        f"{new_link}\n\n"

                                        "Si llegas a 3 avisos serás baneado."

                                    }

                                )

                                # =========================
                                # ENVIAR AVISO ADMIN
                                # =========================

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                    json={

                                        "chat_id": ADMIN_ID,

                                        "text":

                                        f"⚠️ LINK COMPARTIDO\n\n"

                                        f"Usuario: {owner_id}\n"

                                        f"Aviso: {warnings}/3\n"

                                        f"Intruso: {user_id}"

                                    }

                                )

                        return


                    # =========================
                    # VERIFICAR QUE EL LINK ES DEL USUARIO
                    # =========================

                    used_link = None

                    try:

                        if hasattr(update.message, "invite_link"):

                            used_link = update.message.invite_link.invite_link

                    except Exception as e:

                        print("Error obteniendo invite_link:", e)


                    if used_link:

                        cur.execute("""

                            SELECT user_id
                            FROM invite_links
                            WHERE invite_link=%s
                            AND group_id=%s

                        """, (

                            used_link,
                            telegram_group_id

                        ))

                        owner = cur.fetchone()

                        if owner:

                            owner_id = owner[0]

                            if owner_id != user_id:

                                print("Intruso usando link ajeno:", user_id)

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                                    json={
                                        "chat_id": telegram_group_id,
                                        "user_id": user_id
                                    }

                                )

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                                    json={
                                        "chat_id": telegram_group_id,
                                        "user_id": user_id
                                    }

                                )

                                return


                    if expiration and datetime.now() > expiration:

                        print("Usuario expirado:", user_id)


                        cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            telegram_group_id

                        ))


                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                            json={
                                "chat_id": telegram_group_id,
                                "user_id": user_id
                            }

                        )

                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                            json={
                                "chat_id": telegram_group_id,
                                "user_id": user_id
                            }

                        )

                    else:

                        # =========================
                        # NUEVA BIENVENIDA CON TIEMPO RESTANTE
                        # =========================

                        try:

                            tiempo_texto = format_tiempo_restante(
                                expiration
                            )


                            bienvenida = requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                json={

                                    "chat_id": user_id,

                                    "text":

                                    "👋 Bienvenido al VIP\n\n"

                                    f"⏳ Tiempo restante: {tiempo_texto}\n\n"

                                    "Disfruta el contenido."

                                }

                            ).json()


                            if "result" in bienvenida:

                                message_id = bienvenida["result"]["message_id"]

                                time.sleep(10)

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/deleteMessage",

                                    json={

                                        "chat_id": telegram_group_id,

                                        "message_id": message_id

                                    }

                                )

                        except Exception as e:

                            print("Error bienvenida:", e)


                            tiempo_texto = format_tiempo_restante(
                                expiration_real
                            )


                            bienvenida = requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                                json={

                                    "chat_id": user_id,

                                    "text":

                                    "👋 Bienvenido al VIP\n\n"

                                    f"⏳ Tiempo restante: {tiempo_texto}\n\n"

                                    "Disfruta el contenido."

                                }

                            ).json()


                            if "result" in bienvenida:

                                message_id = bienvenida["result"]["message_id"]

                                time.sleep(10)

                                requests.post(

                                    f"https://api.telegram.org/bot{TOKEN}/deleteMessage",

                                    json={

                                        "chat_id": telegram_group_id,

                                        "message_id": message_id

                                    }

                                )

                        except Exception as e:

                            print("Error bienvenida:", e)


        except Exception as e:

            print("Error verificando miembro:", e)


# =========================
# VERIFICAR ADMIN DESPUÉS DE 30s
# =========================

async def verificar_admin_despues(group_id, group_name, bot_id, context, added_by):

    print("Esperando 30 segundos antes de verificar permisos...")

    await asyncio.sleep(30)

    try:

        print("Verificando permisos del bot...")

        r = requests.get(

            f"https://api.telegram.org/bot{TOKEN}/getChatMember",

            params={

                "chat_id": group_id,
                "user_id": bot_id

            }

        ).json()

        print("Respuesta completa getChatMember:", r)

        status = r["result"]["status"]

        print("Status del bot en grupo:", status)


        if status not in ["administrator", "creator"]:

            print("Bot NO es administrador después de 30s.")

            try:

                await context.bot.send_message(

                    chat_id=group_id,

                    text=

                    "⚠️ No tengo permisos de administrador.\n\n"

                    "Saldré del grupo en este momento."

                )

            except Exception as e:

                print("Error enviando mensaje al grupo:", e)


            try:

                await context.bot.send_message(

                    chat_id=ADMIN_ID,

                    text=

                    "⚠️ BOT SALIENDO DEL GRUPO\n\n"

                    f"Grupo: {group_name}\n"

                    f"ID: {group_id}\n\n"

                    "No fue asignado como administrador."

                )

            except Exception as e:

                print("Error enviando aviso admin:", e)


            try:

                await context.bot.leave_chat(group_id)

                print("Bot salió del grupo automáticamente.")

            except Exception as e:

                print("Error saliendo del grupo:", e)


            return


        print(f"Bot ES administrador en grupo: {group_name} ({group_id})")


        # =========================
        # GUARDAR GRUPO EN DATABASE
        # =========================

        print("Intentando guardar grupo en DB...")

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id
                FROM groups
                WHERE telegram_group_id=%s

            """, (group_id,))

            existing = cur.fetchone()

            if existing:

                print("Grupo ya existe en DB — no se duplica.")

                print(f"Registro finalizado para grupo: {group_name}")

            else:

                cur.execute("""

                    INSERT INTO groups
                    (name, telegram_group_id)

                    VALUES (%s, %s)

                """, (

                    group_name,
                    group_id

                ))

                conn.commit()

                print("Grupo guardado correctamente en DB.")

                print(f"Registro finalizado para grupo: {group_name}")


        try:

            print("Enviando confirmación al ADMIN...")

            await context.bot.send_message(

                chat_id=ADMIN_ID,

                text=

                "✅ NUEVO GRUPO DETECTADO\n\n"

                f"Nombre: {group_name}\n"

                f"ID: {group_id}\n\n"

                "Grupo registrado correctamente."

            )

            print("Mensaje enviado al ADMIN.")

        except Exception as e:

            print("Error enviando confirmación:", e)


    except Exception as e:

        print("Error verificando grupo:", e)


# =========================
# DETECTAR BOT AÑADIDO A GRUPO
# =========================

async def detect_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("detect_bot_added ejecutado")

    if not update.message:
        return

    if not update.message.new_chat_members:
        return


    bot_id = context.bot.id


    for member in update.message.new_chat_members:


        # =========================
        # SI EL MIEMBRO ES EL BOT
        # =========================

        if member.id == bot_id:

            group_id = update.message.chat.id
            group_name = update.message.chat.title

            print(
                "Bot añadido a grupo:",
                group_name,
                group_id
            )


            try:

                added_by = update.message.from_user.id

            except:

                added_by = None


            print(
                "Bot añadido por usuario:",
                added_by
            )


            # =========================
            # AVISO SI NO FUE EL ADMIN
            # =========================

            if added_by and added_by != ADMIN_ID:

                try:

                    await context.bot.send_message(

                        chat_id=ADMIN_ID,

                        text=

                        "⚠️ BOT AÑADIDO POR USUARIO NO AUTORIZADO\n\n"

                        f"Grupo: {group_name}\n"

                        f"ID: {group_id}\n"

                        f"Usuario: {added_by}\n\n"

                        "El grupo será registrado igualmente."

                    )

                except Exception as e:

                    print(
                        "Error enviando aviso admin:",
                        e
                    )


            print(
                "Continuando registro del grupo..."
            )


            # =========================
            # AVISO AL GRUPO
            # =========================

            try:

                await context.bot.send_message(

                    chat_id=group_id,

                    text=

                    "⚠️ Necesito permisos de administrador.\n\n"

                    "Por favor asígnamelos en los próximos 30 segundos.\n\n"

                    "Si no, abandonaré el grupo automáticamente."

                )

            except Exception as e:

                print(
                    "Error enviando aviso al grupo:",
                    e
                )


            # =========================
            # VERIFICAR ADMIN DESPUÉS
            # =========================

            asyncio.create_task(

                verificar_admin_despues(

                    group_id,

                    group_name,

                    bot_id,

                    context,

                    added_by

                )

            )

            return


# =========================
# DETECTAR USUARIO ENTRANDO AL GRUPO
# =========================

async def detect_user_join(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    if not update.message.new_chat_members:
        return


    telegram_group_id = update.message.chat.id


    for member in update.message.new_chat_members:

        user_id = member.id
        username = member.username
        first_name = member.first_name


        # Evitar verificar al propio bot

        if user_id == context.bot.id:
            return


        print(
            "Usuario detectado entrando:",
            user_id
        )


        try:

            with conn.cursor() as cur:

                # =========================
                # OBTENER group_id REAL
                # =========================

                cur.execute("""

                    SELECT id

                    FROM groups

                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                group_row = cur.fetchone()


                if not group_row:

                    print(
                        "Grupo no encontrado en DB:",
                        telegram_group_id
                    )

                    return


                group_id = group_row[0]


                # =========================
                # VERIFICAR SUSCRIPCIÓN
                # =========================

                cur.execute("""

                    SELECT expiration

                    FROM users

                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    group_id

                ))

                user_row = cur.fetchone()


                # =========================
                # SI NO EXISTE → LINK NO REGISTRADO
                # =========================

                if not user_row:

                    print(
                        "Usuario sin suscripción:",
                        user_id
                    )


                    keyboard = [

                        [

                            InlineKeyboardButton(
                                "✅ ACEPTAR",
                                callback_data=
                                f"allow_user_{user_id}_{group_id}"
                            )

                        ],

                        [

                            InlineKeyboardButton(
                                "❌ EXPULSAR",
                                callback_data=
                                f"deny_user_{user_id}_{group_id}"
                            )

                        ]

                    ]


                    try:

                        await context.bot.send_message(

                            chat_id=ADMIN_ID,

                            text=

                            "🚨 ACCESO NO AUTORIZADO DETECTADO\n\n"

                            f"Usuario: {first_name}\n"

                            f"Username: @{username}\n"

                            f"ID: {user_id}\n\n"

                            "Ha entrado con un link no registrado.\n\n"

                            "¿Deseas permitirlo o expulsarlo?",

                            reply_markup=
                            InlineKeyboardMarkup(keyboard)

                        )

                    except Exception as e:

                        print(
                            "Error enviando aviso admin:",
                            e
                        )


                    return


                expiration = user_row[0]


                # =========================
                # SI EXPIRADO → EXPULSAR
                # =========================

                if expiration and datetime.now() > expiration:

                    print(
                        "Usuario expirado detectado:",
                        user_id
                    )


                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                        json={

                            "chat_id": telegram_group_id,

                            "user_id": user_id

                        }

                    )


                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                        json={

                            "chat_id": telegram_group_id,

                            "user_id": user_id

                        }

                    )


                    return


        except Exception as e:

            print(
                "Error verificando usuario:",
                e
            )   

def check_expirations():

    while True:

        with conn.cursor() as cur:

            cur.execute("""

            SELECT user_id, group_id, expiration
            FROM users
            WHERE expiration IS NOT NULL

            """)

            rows = cur.fetchall()

            now = datetime.now()

            for user_id, group_id, expiration in rows:

                if expiration and now > expiration:

                    try:

                        print(
                            "Expulsando expirado:",
                            user_id,
                            "grupo:",
                            group_id
                        )

                        # =========================
                        # OBTENER TELEGRAM_GROUP_ID
                        # =========================

                        cur.execute("""

                        SELECT telegram_group_id
                        FROM groups
                        WHERE id=%s

                        """, (group_id,))

                        group_row = cur.fetchone()

                        if not group_row:
                            continue

                        telegram_group_id = group_row[0]


                        # =========================
                        # OBTENER LINK DEL GRUPO
                        # =========================

                        cur.execute("""

                        SELECT invite_link
                        FROM invite_links
                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            group_id

                        ))

                        links = cur.fetchall()


                        # =========================
                        # REVOCAR LINKS
                        # =========================

                        for (link,) in links:

                            try:

                                revoke_link(
                                    telegram_group_id,
                                    link
                                )

                                # =========================
                                # MARCAR LINK COMO INACTIVO
                                # =========================

                                cur.execute("""

                                UPDATE invite_links

                                SET is_active=FALSE,

                                    revoked_at=NOW()

                                WHERE invite_link=%s

                                """, (link,))


                            except Exception as e:

                                print(

                                    "Error revocando link expirado:",

                                    e

                                )


                        # =========================
                        # EXPULSAR USUARIO
                        # =========================

                        try:

                            requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                                json={

                                    "chat_id": telegram_group_id,

                                    "user_id": user_id

                                }

                            )

                            requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                                json={

                                    "chat_id": telegram_group_id,

                                    "user_id": user_id

                                }

                            )

                        except Exception as e:

                            print(
                                "Error expulsando usuario:",
                                e
                            )


                        # =========================
                        # DESACTIVAR LINK EXPIRADO
                        # =========================

                        cur.execute("""

                        UPDATE invite_links

                        SET is_active=FALSE,
                            revoked_at=NOW()

                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            group_id

                        ))


                        # =========================
                        # BORRAR LINK DESACTIVADO
                        # =========================

                        cur.execute("""

                        DELETE FROM invite_links

                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            group_id

                        ))


                        # =========================
                        # BORRAR SOLO SUSCRIPCIÓN EXPIRADA
                        # =========================

                        cur.execute("""

                        DELETE FROM users
                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            group_id

                        ))


                        conn.commit()


                        # =========================
                        # AVISAR ADMIN
                        # =========================

                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                            json={

                                "chat_id": ADMIN_ID,

                                "text":

                                f"⛔ Usuario expirado eliminado\n\n"

                                f"User ID: {user_id}\n"

                                f"Grupo ID: {group_id}"

                            }

                        )


                    except Exception as e:

                        print(

                            "Error procesando expiración:",

                            e

                        )

        time.sleep(60)


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


# =========================
# PANEL ADMIN PRINCIPAL
# =========================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [

        [InlineKeyboardButton("👥 Gestión Usuarios", callback_data="menu_users")],

        [InlineKeyboardButton("🎟️ Gestión Accesos", callback_data="menu_codes")],

        [InlineKeyboardButton("📦 Gestión Grupos", callback_data="menu_groups")],

        [InlineKeyboardButton("💳 Gestión Pagos", callback_data="menu_payments")],

        [InlineKeyboardButton("📊 Gestión Negocio", callback_data="menu_business")],

        [InlineKeyboardButton("📜 Logs", callback_data="menu_logs")]

    ]

    await update.message.reply_text(

        "🔐 PANEL ADMIN",

        reply_markup=InlineKeyboardMarkup(keyboard)

    )


# =========================
# BOTONES
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data


    # =========================
    # MIS SUSCRIPCIONES ACTIVAS
    # =========================

    if data == "mis_subs":

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT DISTINCT il.group_id, g.name

                    FROM invite_links il

                    JOIN groups g
                    ON il.group_id = g.telegram_group_id

                    WHERE il.user_id=%s

                    AND il.is_active=TRUE

                """, (user_id,))

                rows = cur.fetchall()

        except Exception as e:

            print("Error cargando suscripciones:", e)

            await query.message.reply_text(
                "❌ Error cargando suscripciones."
            )

            return


        if not rows:

            await query.message.reply_text(
                "⚠️ No tienes suscripciones activas."
            )

            return


        keyboard = []


        for group_id, group_name in rows:

            keyboard.append([

                InlineKeyboardButton(

                    f"📦 {group_name}",

                    callback_data=f"mysub_{group_id}"

                )

            ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="back_groups"

            )

        ])


        await query.message.reply_text(

            "📦 Tus suscripciones activas:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # DETALLE DE SUSCRIPCIÓN
    # =========================

    if data.startswith("mysub_"):

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id

        telegram_group_id = int(
            data.split("_")[1]
        )


        try:

            with conn.cursor() as cur:

                # =========================
                # OBTENER NOMBRE GRUPO
                # =========================

                cur.execute("""

                    SELECT name

                    FROM groups

                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                group_row = cur.fetchone()


                if not group_row:

                    await query.message.reply_text(
                        "❌ Grupo no encontrado."
                    )

                    return


                group_name = group_row[0]


                # =========================
                # OBTENER group_id REAL
                # =========================

                cur.execute("""

                    SELECT id

                    FROM groups

                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                group_id_row = cur.fetchone()


                if not group_id_row:

                    await query.message.reply_text(
                        "❌ Grupo no encontrado."
                    )

                    return


                real_group_id = group_id_row[0]


                # =========================
                # OBTENER EXPIRATION
                # =========================

                cur.execute("""

                    SELECT expiration

                    FROM users

                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    real_group_id

                ))

                user_row = cur.fetchone()


                if not user_row:

                    await query.message.reply_text(
                        "❌ No tienes suscripción activa."
                    )

                    return


                expiration = user_row[0]


                # =========================
                # OBTENER LINK ACTUAL
                # =========================

                cur.execute("""

                    SELECT invite_link

                    FROM invite_links

                    WHERE user_id=%s
                    AND group_id=%s
                    AND is_active=TRUE

                    ORDER BY created_at DESC

                    LIMIT 1

                """, (

                    user_id,
                    telegram_group_id

                ))

                link_row = cur.fetchone()


        except Exception as e:

            print("Error cargando detalle suscripción:", e)

            await query.message.reply_text(
                "❌ Error cargando suscripción."
            )

            return


        # =========================
        # FORMATEAR TIEMPO
        # =========================

        tiempo_texto = format_tiempo_restante(
            expiration
        )


        # =========================
        # REVOCAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link

                FROM invite_links

                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                telegram_group_id

            ))

            old_links = cur.fetchall()


            for (old_link,) in old_links:

                try:

                    revoke_link(
                        telegram_group_id,
                        old_link
                    )

                    cur.execute("""

                        UPDATE invite_links

                        SET is_active=FALSE,
                            revoked_at=NOW()

                        WHERE invite_link=%s

                    """, (old_link,))

                except Exception as e:

                    print(
                        "Error revocando link:",
                        e
                    )


            cur.execute("""

                DELETE FROM invite_links

                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                telegram_group_id

            ))

            conn.commit()


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        max_expire = int(time.time()) + 180

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        # =========================
        # CREAR LINK NUEVO
        # =========================

        invite_link = requests.post(

            f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

            json={
                "chat_id": telegram_group_id,
                "member_limit": 1,
                "expire_date": expire_timestamp
            }

        ).json()


        if "result" not in invite_link:

            await query.message.reply_text(
                "❌ Error creando acceso."
            )

            return


        link = invite_link["result"]["invite_link"]


        # =========================
        # GUARDAR LINK NUEVO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, invite_link)

                VALUES (%s, %s, %s)

            """, (

                user_id,
                telegram_group_id,
                link

            ))

            conn.commit()


        keyboard = [

            [

                InlineKeyboardButton(

                    "⬅️ Volver",

                    callback_data="mis_subs"

                )

            ]

        ]


        mensaje = (

            f"📦 {group_name}\n\n"

            f"⏳ Tiempo restante:\n"
            f"{tiempo_texto}\n\n"

            "⚠️ Este link expirará en 3 minutos.\n\n"

            f"🔗 Tu nuevo acceso:\n"
            f"{link}"

        )


        await query.message.reply_text(

            mensaje,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ENTRAR A GRUPO
    # =========================

    if data.startswith("group_"):

        try:
            await query.message.delete()
        except:
            pass


        group_id = int(data.split("_")[1])


        # =========================
        # GUARDAR GRUPO SELECCIONADO
        # =========================

        context.user_data["selected_group"] = group_id


        # =========================
        # OBTENER PLANES DEL GRUPO
        # =========================

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT name,
                           price_id,
                           amount,
                           currency

                    FROM plans

                    WHERE group_id=%s
                    AND is_active=TRUE

                    ORDER BY id ASC

                """, (group_id,))

                plans = cur.fetchall()

        except Exception as e:

            print("Error cargando planes:", e)

            await query.message.reply_text(
                "❌ Error cargando planes."
            )

            return


        if not plans:

            await query.message.reply_text(
                "⚠️ Este grupo no tiene planes disponibles."
            )

            return


        keyboard = []


        for name, price_id, amount, currency in plans:

            if amount and currency:

                button_text = f"{name} — {amount} {currency}"

            else:

                button_text = name


            keyboard.append([

                InlineKeyboardButton(

                    button_text,

                    callback_data=price_id

                )

            ])


        keyboard.append([

            InlineKeyboardButton(

                "🎟️ Usar código",

                callback_data="codigo"

            )

        ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="back_groups"

            )

        ])


        await query.message.reply_text(

            "Selecciona un plan:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # VOLVER A GRUPOS
    # =========================

    if data == "back_groups":

        try:
            await query.message.delete()
        except:
            pass

        await start(update, context)

        return
    

    # =========================
    # RECUPERAR ACCESO
    # =========================

    if data == "recover_access":

        user_id = query.from_user.id

        with conn.cursor() as cur:

            cur.execute("""

                SELECT expiration
                FROM users
                WHERE user_id=%s

            """, (user_id,))

            row = cur.fetchone()

        if not row:

            await query.message.reply_text(
                "❌ No tienes acceso activo."
            )

            return


        expiration = row[0]

        if expiration and datetime.now() > expiration:

            await query.message.reply_text(
                "⛔ Tu suscripción ha expirado."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s
                ORDER BY created_at DESC
                LIMIT 1

            """, (

                user_id,
                get_group_id()

            ))

            link_row = cur.fetchone()


        # =========================
        # REVOCAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            old_links = cur.fetchall()


        for (old_link,) in old_links:

            try:

                requests.post(

                    f"https://api.telegram.org/bot{TOKEN}/revokeChatInviteLink",

                    json={
                        "chat_id": get_group_id(),
                        "invite_link": old_link
                    }

                )

            except Exception as e:

                print(
                    "Error revocando link:",
                    e
                )


        # =========================
        # BORRAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            conn.commit()


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        max_expire = int(time.time()) + 180

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        # =========================
        # CREAR LINK NUEVO TEMPORAL
        # =========================

        invite_link = requests.post(

            f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

            json={
                "chat_id": get_group_id(),
                "member_limit": 1,
                "expire_date": expire_timestamp
            }

        ).json()


        link = invite_link["result"]["invite_link"]


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, invite_link)

                VALUES (%s, %s, %s)

            """, (

                user_id,
                get_group_id(),
                link

            ))

            conn.commit()


        await query.message.reply_text(

            f"🔗 Tu acceso VIP:\n{link}"

        )

        return


    # =========================
    # MENÚ USUARIOS
    # =========================

    if data == "menu_users":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📋 Ver usuarios", callback_data="admin_users")],

            [InlineKeyboardButton("🔍 Buscar usuario", callback_data="admin_search_user")],

            [InlineKeyboardButton("🚫 Expulsar usuario", callback_data="admin_kick_user")],

            [InlineKeyboardButton("⛔ Banear usuario", callback_data="admin_ban_user")],

            [InlineKeyboardButton("♻️ Desbanear usuario", callback_data="admin_unban_user")],

            [InlineKeyboardButton("🔄 Reset warnings", callback_data="admin_reset_warnings")],

            [InlineKeyboardButton("🔀 Mover usuario grupo", callback_data="admin_move_user")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await query.message.reply_text(

            "👥 GESTIÓN USUARIOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ADMIN — PERMITIR USUARIO
    # =========================

    if data.startswith("allow_user_"):

        parts = data.split("_")

        user_id = int(parts[2])
        group_id = int(parts[3])

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO users

                    (user_id, group_id, expiration)

                    VALUES (%s, %s, NULL)

                    ON CONFLICT
                    (user_id, group_id)

                    DO UPDATE SET expiration=NULL

                """, (

                    user_id,
                    group_id

                ))

                conn.commit()


            await query.message.reply_text(

                "✅ Usuario permitido permanentemente."

            )


        except Exception as e:

            print(
                "Error permitiendo usuario:",
                e
            )

        return


    # =========================
    # ADMIN — EXPULSAR USUARIO
    # =========================

    if data.startswith("deny_user_"):

        parts = data.split("_")

        user_id = int(parts[2])
        group_id = int(parts[3])


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT telegram_group_id

                    FROM groups

                    WHERE id=%s

                """, (group_id,))

                row = cur.fetchone()


            if row:

                telegram_group_id = row[0]


                requests.post(

                    f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                    json={

                        "chat_id": telegram_group_id,

                        "user_id": user_id

                    }

                )


                requests.post(

                    f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                    json={

                        "chat_id": telegram_group_id,

                        "user_id": user_id

                    }

                )


            await query.message.reply_text(

                "❌ Usuario expulsado."

            )


        except Exception as e:

            print(
                "Error expulsando usuario:",
                e
            )

        return


    # =========================
    # MENÚ ACCESOS
    # =========================

    if data == "menu_codes":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📤 Crear código", callback_data="admin_create_code")],

            [InlineKeyboardButton("📋 Ver códigos", callback_data="admin_codes")],

            [InlineKeyboardButton("❌ Eliminar código", callback_data="admin_delete_code")],

            [InlineKeyboardButton("🔄 Revocar links", callback_data="admin_revoke_links")],

            [InlineKeyboardButton("📩 Reenviar links", callback_data="admin_resend_links")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await query.message.reply_text(

            "🎟️ GESTIÓN ACCESOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ GRUPOS
    # =========================

    if data == "menu_groups":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("➕ Añadir grupo", callback_data="admin_add_group")],

            [InlineKeyboardButton("✏️ Editar grupo", callback_data="admin_edit_group")],

            [InlineKeyboardButton("📋 Ver grupos", callback_data="admin_view_groups")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await query.message.reply_text(

            "📦 GESTIÓN GRUPOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # CANCELAR CREACIÓN GRUPO
    # =========================

    if data == "cancel_create_group":

        context.user_data["creating_group"] = False
        context.user_data.pop("new_group_data", None)
        context.user_data.pop("group_step", None)

        keyboard = [

            [InlineKeyboardButton("➕ Añadir grupo", callback_data="admin_add_group")],

            [InlineKeyboardButton("✏️ Editar grupo", callback_data="admin_edit_group")],

            [InlineKeyboardButton("📋 Ver grupos", callback_data="admin_view_groups")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await query.message.reply_text(

            "📦 GESTIÓN GRUPOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # VER GRUPOS
    # =========================

    if data == "admin_view_groups":

        print("DEBUG: admin_view_groups pulsado")

        try:
            await query.message.delete()
        except:
            pass

        try:

            print("DEBUG: consultando groups...")

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id, name, telegram_group_id

                    FROM groups

                    WHERE telegram_group_id != 0

                    ORDER BY id ASC

                """)

                groups = cur.fetchall()

            print("DEBUG groups:", groups)

        except Exception as e:

            print("ERROR cargando grupos:", e)

            await query.message.reply_text(
                f"❌ Error cargando grupos:\n{str(e)}"
            )

            return


        if not groups:

            await query.message.reply_text(
                "⚠️ No hay grupos registrados."
            )

            return


        texto = "📋 GRUPOS REGISTRADOS\n\n"


        try:

            for group_id, name, telegram_id in groups:

                texto += (

                    f"🆔 ID interno: {group_id}\n"
                    f"📦 Nombre: {name}\n"
                    f"📡 Telegram ID: {telegram_id}\n\n"

                )

        except Exception as e:

            print("ERROR construyendo texto:", e)

            await query.message.reply_text(
                f"❌ Error procesando grupos:\n{str(e)}"
            )

            return


        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="menu_groups"
            )]

        ]


        await query.message.reply_text(

            texto,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ PAGOS
    # =========================

    if data == "menu_payments":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📋 Ver pagos", callback_data="admin_view_payments")],

            [InlineKeyboardButton("🔍 Buscar pago", callback_data="admin_search_payment")],

            [InlineKeyboardButton("📩 Reenviar acceso", callback_data="admin_resend_access")],

            [InlineKeyboardButton("❌ Cancelar suscripción", callback_data="admin_cancel_subscription")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await query.message.reply_text(

            "💳 GESTIÓN PAGOS",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ NEGOCIO
    # =========================

    if data == "menu_business":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats")],

            [InlineKeyboardButton("👥 Usuarios activos", callback_data="admin_active_users")],

            [InlineKeyboardButton("💰 Ingresos", callback_data="admin_income")],

            [InlineKeyboardButton("🔄 Revocar todos links", callback_data="admin_revoke_links")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await query.message.reply_text(

            "📊 GESTIÓN NEGOCIO",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # MENÚ LOGS
    # =========================

    if data == "menu_logs":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("📜 Ver logs", callback_data="admin_logs")],

            [InlineKeyboardButton("👥 Logs usuarios", callback_data="admin_logs_users")],

            [InlineKeyboardButton("💳 Logs pagos", callback_data="admin_logs_payments")],

            [InlineKeyboardButton("🔐 Logs seguridad", callback_data="admin_logs_security")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await query.message.reply_text(

            "📜 LOGS SISTEMA",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # VOLVER AL MENÚ PRINCIPAL
    # =========================

    if data == "admin_back_main":

        try:
            await query.message.delete()
        except:
            pass

        keyboard = [

            [InlineKeyboardButton("👥 Gestión Usuarios", callback_data="menu_users")],

            [InlineKeyboardButton("🎟️ Gestión Accesos", callback_data="menu_codes")],

            [InlineKeyboardButton("📦 Gestión Grupos", callback_data="menu_groups")],

            [InlineKeyboardButton("💳 Gestión Pagos", callback_data="menu_payments")],

            [InlineKeyboardButton("📊 Gestión Negocio", callback_data="menu_business")],

            [InlineKeyboardButton("📜 Logs", callback_data="menu_logs")]

        ]

        await query.message.reply_text(

            "🔐 PANEL ADMIN",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # AÑADIR GRUPO — INICIO WIZARD
    # =========================

    if data == "admin_add_group":

        try:
            await query.message.delete()
        except:
            pass

        context.user_data["creating_group"] = True
        context.user_data["group_step"] = 1
        context.user_data["new_group_data"] = {}

        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Cancelar creación",
                callback_data="cancel_create_group"
            )]

        ]

        await query.message.reply_text(

            "📦 CREAR NUEVO GRUPO\n\n"

            "Paso 1️⃣\n"
            "Introduce el nombre del grupo.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return
    

    # =========================
    # EDITAR GRUPO — LISTA
    # =========================

    if data == "admin_edit_group":

        try:
            await query.message.delete()
        except:
            pass


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id, name

                    FROM groups

                    WHERE telegram_group_id != 0

                    ORDER BY id ASC

                """)

                groups = cur.fetchall()

        except Exception as e:

            print("Error cargando grupos:", e)

            await query.message.reply_text(
                "❌ Error cargando grupos."
            )

            return


        if not groups:

            await query.message.reply_text(
                "⚠️ No hay grupos disponibles."
            )

            return


        keyboard = []


        for group_id, group_name in groups:

            keyboard.append([

                InlineKeyboardButton(

                    group_name,

                    callback_data=f"edit_group_{group_id}"

                )

            ])


        keyboard.append([

            InlineKeyboardButton(

                "⬅️ Volver",

                callback_data="menu_groups"

            )

        ])


        await query.message.reply_text(

            "Selecciona el grupo a editar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return
    

    # =========================
    # MENÚ INTERNO DEL GRUPO
    # =========================

    if data.startswith("edit_group_") and data.split("_")[2].isdigit():

        try:
            await query.message.delete()
        except:
            pass


        group_id = int(data.split("_")[2])


        # Guardar grupo seleccionado

        context.user_data["selected_group_admin"] = group_id


        keyboard = [

            [InlineKeyboardButton("✏️ Editar nombre", callback_data="edit_group_name")],

            [InlineKeyboardButton("🎬 Editar preview", callback_data="edit_group_preview")],

            [InlineKeyboardButton("💳 Editar planes", callback_data="edit_group_plans")],

            [InlineKeyboardButton("🔗 Editar Stripe", callback_data="edit_group_stripe")],

            [InlineKeyboardButton("👑 Administradores", callback_data="edit_group_admins")],

            [InlineKeyboardButton("❌ Eliminar grupo", callback_data="delete_group_confirm")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_edit_group")]

        ]


        await query.message.reply_text(

            "🔧 CONFIGURACIÓN DEL GRUPO",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # EDITAR PREVIEW
    # =========================

    if data == "edit_group_preview":

        try:
            await query.message.delete()
        except:
            pass


        group_id = context.user_data.get("selected_group_admin")


        # =========================
        # OBTENER PREVIEW ACTUAL
        # =========================

        current_preview = None

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT preview_file_id

                    FROM groups

                    WHERE id=%s

                """, (group_id,))

                row = cur.fetchone()

                if row:

                    current_preview = row[0]

        except Exception as e:

            print("Error obteniendo preview:", e)


        context.user_data["editing_preview"] = True


        # =========================
        # MOSTRAR PREVIEW ACTUAL
        # =========================

        if current_preview:

            try:

                await context.bot.send_photo(

                    chat_id=query.message.chat_id,

                    photo=current_preview,

                    caption="📸 Preview actual del grupo"

                )

            except:

                try:

                    await context.bot.send_video(

                        chat_id=query.message.chat_id,

                        video=current_preview,

                        caption="📸 Preview actual del grupo"

                    )

                except Exception as e:

                    print("Error mostrando preview:", e)


        keyboard = [

            [InlineKeyboardButton("⏭ Omitir", callback_data="skip_preview")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="edit_group_back")]

        ]


        await query.message.reply_text(

            "🎬 Envía una imagen o video para el nuevo preview.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return
    
    # =========================
    # OMITIR PREVIEW
    # =========================

    if data == "skip_preview":

        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)

        group_id = context.user_data.get("selected_group_admin")


        keyboard = [

            [InlineKeyboardButton("✏️ Editar nombre", callback_data="edit_group_name")],

            [InlineKeyboardButton("🎬 Editar preview", callback_data="edit_group_preview")],

            [InlineKeyboardButton("💳 Editar planes", callback_data="edit_group_plans")],

            [InlineKeyboardButton("🔗 Editar Stripe", callback_data="edit_group_stripe")],

            [InlineKeyboardButton("👑 Administradores", callback_data="edit_group_admins")],

            [InlineKeyboardButton("❌ Eliminar grupo", callback_data="delete_group_confirm")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_edit_group")]

        ]


        await query.message.reply_text(

            "⏭ Preview omitido.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # GUARDAR PREVIEW
    # =========================

    if data == "save_preview":

        group_id = context.user_data.get("selected_group_admin")

        file_id = context.user_data.get("new_preview_file")


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups

                    SET preview_file_id=%s

                    WHERE id=%s

                """, (

                    file_id,
                    group_id

                ))

                conn.commit()

        except Exception as e:

            print("Error guardando preview:", e)


        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)


        keyboard = [

            [InlineKeyboardButton("✏️ Editar nombre", callback_data="edit_group_name")],

            [InlineKeyboardButton("🎬 Editar preview", callback_data="edit_group_preview")],

            [InlineKeyboardButton("💳 Editar planes", callback_data="edit_group_plans")],

            [InlineKeyboardButton("🔗 Editar Stripe", callback_data="edit_group_stripe")],

            [InlineKeyboardButton("👑 Administradores", callback_data="edit_group_admins")],

            [InlineKeyboardButton("❌ Eliminar grupo", callback_data="delete_group_confirm")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_edit_group")]

        ]


        await query.message.reply_text(

            "✅ Preview actualizado correctamente.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    # =========================
    # CANCELAR PREVIEW
    # =========================

    if data == "cancel_preview":

        context.user_data["editing_preview"] = False
        context.user_data.pop("new_preview_file", None)

        group_id = context.user_data.get("selected_group_admin")


        keyboard = [

            [InlineKeyboardButton("✏️ Editar nombre", callback_data="edit_group_name")],

            [InlineKeyboardButton("🎬 Editar preview", callback_data="edit_group_preview")],

            [InlineKeyboardButton("💳 Editar planes", callback_data="edit_group_plans")],

            [InlineKeyboardButton("🔗 Editar Stripe", callback_data="edit_group_stripe")],

            [InlineKeyboardButton("👑 Administradores", callback_data="edit_group_admins")],

            [InlineKeyboardButton("❌ Eliminar grupo", callback_data="delete_group_confirm")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_edit_group")]

        ]


        await query.message.reply_text(

            "❌ Cambios descartados.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return



    # =========================
    # EDITAR PLANES — MENÚ
    # =========================

    if data == "edit_group_plans":

        try:
            await query.message.delete()
        except:
            pass


        group_id = context.user_data.get("selected_group_admin")


        keyboard = [

            [InlineKeyboardButton(
                "📋 Ver planes",
                callback_data="view_group_plans"
            )],

            [InlineKeyboardButton(
                "➕ Añadir plan",
                callback_data="add_group_plan"
            )],

            [InlineKeyboardButton(
                "✏️ Editar plan",
                callback_data="edit_group_plan_select"
            )],

            [InlineKeyboardButton(
                "🗑 Eliminar plan",
                callback_data="delete_group_plan_select"
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=f"edit_group_{group_id}"
            )]

        ]


        await query.message.reply_text(

            "💳 GESTIÓN DE PLANES\n\n"
            "Selecciona una opción:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # AÑADIR PLAN — INICIO
    # =========================

    if data == "add_group_plan":

        group_id = context.user_data.get("selected_group_admin")

        if not group_id:

            await query.message.reply_text(
                "❌ No se encontró el grupo."
            )

            return


        context.user_data["adding_plan"] = True
        context.user_data["add_plan_step"] = 1
        context.user_data["new_plan"] = {}


        await query.message.reply_text(

            "➕ CREAR NUEVO PLAN\n\n"

            "Paso 1️⃣\n"
            "Introduce el nombre del plan.\n\n"

            "Ejemplo:\n"
            "VIP Mensual"

        )

        return


    # =========================
    # VER PLANES DEL GRUPO
    # =========================

    if data == "view_group_plans":

        try:
            await query.message.delete()
        except:
            pass


        group_id = context.user_data.get("selected_group_admin")


        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id,
                           name,
                           amount,
                           currency,
                           duration_days

                    FROM plans

                    WHERE group_id=%s
                    AND is_active=TRUE

                    ORDER BY id ASC

                """, (group_id,))

                plans = cur.fetchall()

        except Exception as e:

            print("Error cargando planes:", e)

            await query.message.reply_text(
                "❌ Error cargando planes."
            )

            return


        if not plans:

            keyboard = [

                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="edit_group_plans"
                )]

            ]

            await query.message.reply_text(

                "⚠️ Este grupo no tiene planes creados.",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

            return


        texto = "📋 PLANES DEL GRUPO\n\n"


        for plan_id, name, amount, currency, duration in plans:

            if duration == 0:

                duracion_texto = "♾️ Permanente"

            else:

                duracion_texto = f"{duration} días"


            if amount and currency:

                precio_texto = f"{amount} {currency}"

            else:

                precio_texto = "No definido"


            texto += (

                f"🆔 {plan_id}\n"

                f"📦 {name}\n"

                f"💰 {precio_texto}\n"

                f"⏳ {duracion_texto}\n\n"

            )


        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )]

        ]


        await query.message.reply_text(

            texto,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # EDITAR PLAN — SELECCIÓN
    # =========================

    if data == "edit_group_plan_select":

        group_id = context.user_data.get("selected_group_admin")

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE
                ORDER BY id ASC

            """, (group_id,))

            plans = cur.fetchall()


        if not plans:

            await query.message.reply_text(
                "⚠️ No hay planes disponibles."
            )

            return


        keyboard = []


        for plan_id, name in plans:

            keyboard.append([

                InlineKeyboardButton(
                    name,
                    callback_data=f"edit_plan_{plan_id}"
                )

            ])


        keyboard.append([

            InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )

        ])


        await query.message.reply_text(

            "✏️ Selecciona el plan a editar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ELIMINAR GRUPO — CONFIRMAR
    # =========================

    if data == "delete_group_confirm":

        group_id = context.user_data.get("selected_group_admin")

        if not group_id:

            await query.message.reply_text(
                "❌ No se encontró el grupo."
            )

            return

        try:

            with conn.cursor() as cur:

                # =========================
                # BORRAR PLANES
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM plans
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando plans:", e)


                # =========================
                # BORRAR USUARIOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM users
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando users:", e)


                # =========================
                # BORRAR LINKS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM invite_links
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando invite_links:", e)


                # =========================
                # BORRAR WARNINGS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM link_warnings
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando link_warnings:", e)


                # =========================
                # BORRAR PAGOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM payments
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando payments:", e)


                # =========================
                # BORRAR SUBSCRIPTIONS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM subscriptions
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando subscriptions:", e)


                # =========================
                # BORRAR BANEADOS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM banned_users
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando banned_users:", e)


                # =========================
                # BORRAR ADMINS
                # =========================

                try:

                    cur.execute("""

                        DELETE FROM admins
                        WHERE group_id=%s

                    """, (group_id,))

                except Exception as e:

                    print("Error borrando admins:", e)


                # =========================
                # BORRAR GRUPO
                # =========================

                cur.execute("""

                    DELETE FROM groups
                    WHERE id=%s

                """, (group_id,))


                conn.commit()


            await query.message.reply_text(
                "🗑 Grupo eliminado correctamente."
            )

        except Exception as e:

            print("Error eliminando grupo:", e)

            await query.message.reply_text(
                "❌ Error eliminando grupo."
            )

        return


    # =========================
    # ELIMINAR PLAN — SELECCIÓN
    # =========================

    if data == "delete_group_plan_select":

        group_id = context.user_data.get("selected_group_admin")

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE
                ORDER BY id ASC

            """, (group_id,))

            plans = cur.fetchall()


        if not plans:

            await query.message.reply_text(
                "⚠️ No hay planes disponibles."
            )

            return


        keyboard = []


        for plan_id, name in plans:

            keyboard.append([

                InlineKeyboardButton(
                    name,
                    callback_data=f"delete_plan_{plan_id}"
                )

            ])


        keyboard.append([

            InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )

        ])


        await query.message.reply_text(

            "🗑 Selecciona el plan a eliminar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ELIMINAR PLAN — REAL
    # =========================

    if data.startswith("delete_plan_"):

        plan_id = int(data.split("_")[2])

        group_id = context.user_data.get("selected_group_admin")

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE plans

                    SET is_active=FALSE

                    WHERE id=%s

                """, (plan_id,))


                # =========================
                # NUEVO — VERIFICAR SI QUEDAN PLANES
                # =========================

                cur.execute("""

                    SELECT COUNT(*)
                    FROM plans
                    WHERE group_id=%s
                    AND is_active=TRUE

                """, (group_id,))

                remaining_plans = cur.fetchone()[0]


                # =========================
                # NUEVO — SI NO QUEDAN PLANES
                # NO BORRAR GRUPO — SOLO INFORMAR
                # =========================

                if remaining_plans == 0:

                    print(
                        "Grupo sin planes restantes:",
                        group_id
                    )


                conn.commit()

        except Exception as e:

            print("Error eliminando plan:", e)

            await query.message.reply_text(
                "❌ Error eliminando plan."
            )

            return


        await query.message.reply_text(
            "🗑 Plan eliminado correctamente."
        )

        return


    # =========================
    # ADMIN USERS
    # =========================

    if data == "admin_users":

        print("DEBUG: admin_users pulsado")

        if query.from_user.id != ADMIN_ID:
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id, username, first_name, expiration
                    FROM users
                    ORDER BY expiration DESC NULLS LAST

                """)

                users = cur.fetchall()


            if not users:

                await query.message.reply_text(
                    "No hay usuarios activos."
                )

                return


            texto = f"👥 Usuarios activos: {len(users)}\n\n"


            for user_id, username, first_name, expiration in users:

                nombre = first_name if first_name else "Sin nombre"

                if username:
                    nombre += f" (@{username})"

                if expiration:

                    exp = expiration.strftime("%Y-%m-%d")

                else:

                    exp = "♾️ Permanente"


                texto += (

                    f"ID: {user_id}\n"
                    f"Nombre: {nombre}\n"
                    f"Expira: {exp}\n\n"

                )


            await query.message.reply_text(texto)

        except Exception as e:

            print("ERROR admin_users:", e)

            await query.message.reply_text(
                "❌ Error mostrando usuarios"
            )

        return


    # =========================
    # VER CÓDIGOS
    # =========================

    if data == "admin_codes":

        if query.from_user.id != ADMIN_ID:
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

            await query.message.reply_text(
                "No hay códigos creados."
            )

            return


        texto = "🎟️ Últimos códigos:\n\n"


        for code, duration, used in rows:

            if duration == 0:

                duracion_texto = "♾️ Permanente"

            elif duration < 1440:

                duracion_texto = f"{duration} min"

            else:

                duracion_texto = f"{duration//1440} días"


            estado = "❌ USADO" if used else "✅ ACTIVO"


            texto += (

                f"{code}\n"
                f"{duracion_texto} — {estado}\n\n"

            )


        await query.message.reply_text(texto)

        return


    # =========================
    # CREAR CÓDIGO
    # =========================

    if data == "admin_create_code":

        if query.from_user.id != ADMIN_ID:
            return


        keyboard = [

            [InlineKeyboardButton("⏱️ 15 min", callback_data="gen_15")],
            [InlineKeyboardButton("📅 1 día", callback_data="gen_1440")],
            [InlineKeyboardButton("📅 7 días", callback_data="gen_10080")],
            [InlineKeyboardButton("📅 30 días", callback_data="gen_43200")],
            [InlineKeyboardButton("♾️ Permanente", callback_data="gen_perm")]

        ]


        await query.message.reply_text(

            "Selecciona duración:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # ELIMINAR CÓDIGO
    # =========================

    if data == "admin_delete_code":

        context.user_data["delete_code"] = True

        await query.message.reply_text(
            "❌ Envia el código a eliminar"
        )

        return


    # =========================
    # BUSCAR USUARIO
    # =========================

    if data == "admin_search_user":

        context.user_data["search_user"] = True

        await query.message.reply_text(
            "🔍 Envia el ID del usuario"
        )

        return


    # =========================
    # EXPULSAR USUARIO
    # =========================

    if data == "admin_kick_user":

        context.user_data["kick_user"] = True

        await query.message.reply_text(
            "🚫 Envia el ID del usuario"
        )

        return


    # =========================
    # BAN PERMANENTE
    # =========================

    if data == "admin_ban_user":

        context.user_data["ban_user"] = True

        await query.message.reply_text(
            "⛔ Envia el ID del usuario a BANEAR"
        )

        return


    # =========================
    # DESBANEAR USUARIO
    # =========================

    if data == "admin_unban_user":

        context.user_data["unban_user"] = True

        await query.message.reply_text(
            "♻️ Envia el ID del usuario a DESBANEAR"
        )

        return


    # =========================
    # ESTADÍSTICAS
    # =========================

    if data == "admin_stats":

        if query.from_user.id != ADMIN_ID:
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE expiration IS NULL
                    OR expiration > NOW()

                """)

                usuarios_activos = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE expiration IS NOT NULL
                    AND expiration < NOW()

                """)

                usuarios_expirados = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM users
                    WHERE expiration IS NULL

                """)

                usuarios_permanentes = cur.fetchone()[0]


                cur.execute("""

                    SELECT COUNT(*)
                    FROM payments

                """)

                total_pagos = cur.fetchone()[0]


            texto = (

                "📊 ESTADÍSTICAS\n\n"

                f"👥 Activos: {usuarios_activos}\n"
                f"⛔ Expirados: {usuarios_expirados}\n"
                f"♾️ Permanentes: {usuarios_permanentes}\n\n"

                f"💳 Pagos totales: {total_pagos}"

            )


            await query.message.reply_text(texto)

        except Exception as e:

            print("ERROR admin_stats:", e)

            await query.message.reply_text(
                "❌ Error mostrando estadísticas"
            )

        return


    # =========================
    # REVOCAR TODOS LOS LINKS
    # =========================

    if data == "admin_revoke_links":

        if query.from_user.id != ADMIN_ID:
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT invite_link
                    FROM invite_links

                """)

                links = cur.fetchall()


            total = 0

            for (link,) in links:

                try:

                    # =========================
                    # OBTENER GRUPO REAL DEL LINK
                    # =========================

                    with conn.cursor() as cur2:

                        cur2.execute("""

                            SELECT group_id
                            FROM invite_links
                            WHERE invite_link=%s

                        """, (link,))

                        group_row = cur2.fetchone()


                    if not group_row:
                        continue


                    telegram_group_id = group_row[0]


                    revoke_link(
                        telegram_group_id,
                        link
                    )

                    total += 1


                except Exception as e:

                    print(
                        "Error revocando link:",
                        e
                    )


            await query.message.reply_text(

                f"🔄 {total} links revocados correctamente."

            )

        except Exception as e:

            print("Error revocando todos:", e)

            await query.message.reply_text(
                "❌ Error revocando links"
            )

        return


    # =========================
    # REENVIAR LINKS NUEVOS
    # =========================

    if data == "admin_resend_links":

        if query.from_user.id != ADMIN_ID:
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id
                    FROM users

                    WHERE
                    (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    AND user_id NOT IN (

                        SELECT user_id
                        FROM banned_users

                    )

                """)

                users = cur.fetchall()


            enviados = 0

            for (user_id,) in users:

                try:

                    # =========================
                    # OBTENER TELEGRAM_GROUP_ID REAL
                    # =========================

                    with conn.cursor() as cur2:

                        cur2.execute("""

                            SELECT telegram_group_id

                            FROM groups

                            WHERE id=(

                                SELECT group_id
                                FROM users
                                WHERE user_id=%s
                                LIMIT 1

                            )

                        """, (user_id,))

                        group_row = cur2.fetchone()


                    if not group_row:
                        continue


                    telegram_group_id = group_row[0]


                    invite_link = requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

                        json={
                            "chat_id": telegram_group_id,
                            "member_limit": 1,
                            "expire_date": int(time.time()) + 60
                        }

                    ).json()


                    link = invite_link["result"]["invite_link"]


                    with conn.cursor() as cur:

                        cur.execute("""

                            DELETE FROM invite_links
                            WHERE user_id=%s

                        """, (user_id,))


                        cur.execute("""

                            INSERT INTO invite_links
                            (user_id, group_id, invite_link)

                            VALUES (%s, %s, %s)

                        """, (

                            user_id,
                            get_group_id(),
                            link

                        ))

                        conn.commit()


                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                        json={
                            "chat_id": user_id,
                            "text": f"🔗 Nuevo acceso VIP:\n{link}"
                        }

                    )

                    enviados += 1

                except Exception as e:

                    print("Error enviando link:", e)


            await query.message.reply_text(

                f"📩 {enviados} nuevos links enviados."

            )

        except Exception as e:

            print("Error reenviando:", e)

            await query.message.reply_text(
                "❌ Error reenviando links"
            )

        return





    # =========================
    # EDITAR PLAN — INICIO
    # =========================

    if data.startswith("edit_plan_"):

        plan_id = int(data.split("_")[2])

        context.user_data["editing_plan"] = True
        context.user_data["editing_plan_id"] = plan_id
        context.user_data["edit_plan_step"] = 1

        await query.message.reply_text(

            "✏️ EDITAR PLAN\n\n"

            "Paso 1️⃣\n"
            "Introduce el nuevo nombre del plan."

        )

        return


    # =========================
    # GENERAR CÓDIGOS
    # =========================

    if data.startswith("gen_"):

        await crear_codigo_callback(update, context)
        return


    # =========================
    # USAR CÓDIGO
    # =========================

    if data == "codigo":

        context.user_data["waiting_code"] = True

        await query.message.reply_text(
            "Introduce tu código:"
        )

        return


    # =========================
    # PAGOS STRIPE
    # =========================

    user_id = query.from_user.id

    group_id = context.user_data.get("selected_group")

    try:

        response = requests.post(

            f"{SERVER_URL}/create-checkout-session",

            json={

                "telegram_id": user_id,
                "plan": data,
                "group_id": group_id

            }

        )

        payment_url = response.json()["url"]


        await query.message.reply_text(

            f"💳 Paga aquí:\n{payment_url}"

        )

    except Exception as e:

        print(e)

        await query.message.reply_text(
            "❌ Error creando pago"
        )


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
        CommandHandler("codigos", ver_codigos)
    )

    telegram_app.add_handler(
        CommandHandler("usuarios", ver_usuarios)
    )

    # 🔧 NUEVO COMANDO DEBUG

    telegram_app.add_handler(
        CommandHandler("debugdb", debug_db)
    )

    telegram_app.add_handler(
        CommandHandler("debuglinks", debug_links)
    )

    telegram_app.add_handler(
        CommandHandler("debugcolumns", debug_columns)
    )

    telegram_app.add_handler(
        CommandHandler("fixdb", fixdb_group_column)
    )

    telegram_app.add_handler(
        CommandHandler("debuggroups", debug_groups)
    )

    telegram_app.add_handler(
        CommandHandler("admin", admin_panel)
    )

    telegram_app.add_handler(
        CallbackQueryHandler(button)
    )

    # =========================
    # ⚠️ ORDEN CORRECTO HANDLERS TEXTO
    # =========================

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_admin_inputs
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_code
        )
    )

    # =========================
    # DETECTAR BOT AÑADIDO
    # =========================

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            detect_bot_added
        ),
        group=0
    )

    # =========================
    # CONTROL PRINCIPAL ENTRADAS USUARIOS
    # =========================

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            detect_user_join
        ),
        group=1
    )

    threading.Thread(
        target=check_expirations,
        daemon=True
    ).start()

    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    print("Bot iniciado correctamente")

    telegram_app.run_polling()


if __name__ == "__main__":
    main()