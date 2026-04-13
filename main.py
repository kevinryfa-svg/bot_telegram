import os
import stripe
import threading
import random
import string
import requests
import time

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
# HOME TEST
# =========================

@app.route("/")
def home():
    return "Bot funcionando"


# =========================
# RUN FLASK (🔴 IMPORTANTE)
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


# =========================
# CALLBACK CREAR CÓDIGO
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

        INSERT INTO invite_codes
        (code, duration, used)

        VALUES (%s, %s, FALSE)

        """, (code, duration))

        conn.commit()

    await query.message.reply_text(

        f"✅ Código creado:\n\n{code}"

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

        LIMIT 50

        """)

        rows = cur.fetchall()

    texto = "🎟️ Códigos:\n\n"

    for code, duration, used in rows:

        estado = "❌ usado" if used else "✅ activo"

        texto += f"{code}\n{duration} min — {estado}\n\n"

    await update.message.reply_text(texto)


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

        requests.post(

            f"https://api.telegram.org/bot{TOKEN}/banChatMember",

            json={
                "chat_id": GROUP_ID,
                "user_id": user_id
            }

        )

        requests.post(

            f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

            json={
                "chat_id": GROUP_ID,
                "user_id": user_id
            }

        )

        await update.message.reply_text(
            f"🚫 Usuario expulsado:\n{user_id}"
        )

        context.user_data["kick_user"] = False

        return

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
# STRIPE CHECKOUT
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

        # 🔴 OBTENER PLAN PAGADO

        line_items = stripe.checkout.Session.list_line_items(
            session["id"]
        )

        price_id = line_items["data"][0]["price"]["id"]

        # 🔴 CALCULAR DURACIÓN

        if price_id == PRICE_1_DIA:

            expiration = datetime.now() + timedelta(days=1)

        elif price_id == PRICE_7_DIAS:

            expiration = datetime.now() + timedelta(days=7)

        elif price_id == PRICE_PERMANENTE:

            expiration = None

        else:

            expiration = None

        # 🔴 GUARDAR USUARIO EN DB

        with conn.cursor() as cur:

            cur.execute("""

            INSERT INTO users
            (user_id, expiration)

            VALUES (%s, %s)

            ON CONFLICT (user_id)
            DO UPDATE SET expiration=%s

            """, (user_id, expiration, expiration))

            conn.commit()

        print("Usuario guardado:", user_id)

        # 🔴 CREAR LINK (NO member_limit)

        invite_link = requests.post(

            f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

            json={
                "chat_id": GROUP_ID,
                "expire_date": int(time.time()) + 300
            }

        ).json()

        link = invite_link["result"]["invite_link"]

        # 🔴 ENVIAR LINK

        requests.post(

            f"https://api.telegram.org/bot{TOKEN}/sendMessage",

            json={
                "chat_id": user_id,
                "text": f"🔗 Tu acceso VIP:\n{link}"
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

        user_id = member.id

        try:

            with conn.cursor() as cur:

                cur.execute("""

                SELECT user_id
                FROM users
                WHERE user_id=%s

                """, (user_id,))

                user = cur.fetchone()

            if not user:

                print("Expulsando usuario no autorizado:", user_id)

                requests.post(

                    f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                    json={
                        "chat_id": GROUP_ID,
                        "user_id": user_id
                    }

                )

                requests.post(

                    f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                    json={
                        "chat_id": GROUP_ID,
                        "user_id": user_id
                    }

                )

            else:

                print("Usuario autorizado:", user_id)

        except Exception as e:

            print("Error verificando miembro:", e)

# =========================
# EXPIRACIONES
# =========================

def check_expirations():

    while True:

        with conn.cursor() as cur:

            cur.execute("""

            SELECT user_id, expiration
            FROM users

            WHERE expiration IS NOT NULL

            """)

            rows = cur.fetchall()

            now = datetime.now()

            for user_id, expiration in rows:

                if expiration and now > expiration:

                    try:

                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                            json={
                                "chat_id": GROUP_ID,
                                "user_id": user_id
                            }

                        )

                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                            json={
                                "chat_id": GROUP_ID,
                                "user_id": user_id
                            }

                        )

                        cur.execute("""

                        DELETE FROM users
                        WHERE user_id=%s

                        """, (user_id,))

                        conn.commit()

                    except:
                        pass

        time.sleep(60)


# =========================
# START BOT
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
# PANEL ADMIN
# =========================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [

        [InlineKeyboardButton("👥 Usuarios", callback_data="admin_users")],

        [InlineKeyboardButton("🎟️ Ver códigos", callback_data="admin_codes")],

        [InlineKeyboardButton("📤 Crear código", callback_data="admin_create_code")],

        [InlineKeyboardButton("❌ Eliminar código", callback_data="admin_delete_code")],

        [InlineKeyboardButton("🔍 Buscar usuario", callback_data="admin_search_user")],

        [InlineKeyboardButton("🚫 Expulsar usuario", callback_data="admin_kick_user")],

        [InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats")]

    ]

    await update.message.reply_text(

        "🔐 PANEL ADMIN",

        reply_markup=InlineKeyboardMarkup(keyboard)

    )

# =========================
# BUSCAR USUARIO
# =========================

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["search_user"] = True

    await update.message.reply_text(
        "🔍 Envia el ID del usuario"
    )


# =========================
# EXPULSAR USUARIO
# =========================

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["kick_user"] = True

    await update.message.reply_text(
        "🚫 Envia el ID del usuario a expulsar"
    )

# =========================
# BOTONES
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data


    # =========================
    # CREAR CÓDIGO DESDE PANEL
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
    # CREAR CÓDIGO DESDE PANEL
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

            "Selecciona duración del código:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    # =========================
    # PANEL ADMIN BOTONES
    # =========================

    if data == "admin_users":

    if query.from_user.id != ADMIN_ID:
        return

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

    return

        if query.from_user.id != ADMIN_ID:
            return

        with conn.cursor() as cur:

            cur.execute("""
                SELECT COUNT(*)
                FROM users
            """)

            total = cur.fetchone()[0]

        await query.message.reply_text(
            f"👥 Usuarios activos: {total}"
        )

        return


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


    if data == "admin_stats":

        if query.from_user.id != ADMIN_ID:
            return

        with conn.cursor() as cur:

            cur.execute("""
                SELECT COUNT(*)
                FROM users
            """)

            users_total = cur.fetchone()[0]

        await query.message.reply_text(
            f"📊 Estadísticas:\n\nUsuarios activos: {users_total}"
        )

        return


    if data == "admin_security":

        if query.from_user.id != ADMIN_ID:
            return

        await query.message.reply_text(
            "🛡️ Seguridad activa\n\nSistema anti-intrusos funcionando."
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

    try:

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

    except Exception as e:

        await query.message.reply_text(
            "❌ Error creando pago"
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

    telegram_app.add_handler(
        CommandHandler("admin", admin_panel)
    )

    telegram_app.add_handler(
        CallbackQueryHandler(button)
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_code
        )
    )

    # 🔴 CONTROLAR NUEVOS MIEMBROS

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            check_new_member
        )
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