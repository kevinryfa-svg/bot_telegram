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
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
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
# OBTENER GROUP_ID DINÁMICO
# =========================

def get_group_id():

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT telegram_group_id
                FROM groups
                WHERE telegram_group_id IS NOT NULL
                ORDER BY id DESC
                LIMIT 1

            """)

            row = cur.fetchone()

            if row:

                return row[0]

    except Exception as e:

        print("Error obteniendo group_id:", e)


    return GROUP_ID
    

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
# DEBUG DATABASE
# =========================

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

            """, (user_id,))

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

            """, (user_id,))

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

                """, (user_id,))

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

                """, (user_id,))


                # borrar avisos

                cur.execute("""

                    DELETE FROM link_warnings
                    WHERE user_id=%s

                """, (user_id,))


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

                    if expiration is None:

                        tiempo_texto = "♾️ Permanente"

                    else:

                        tiempo_restante = expiration - datetime.now()

                        dias = tiempo_restante.days
                        horas = tiempo_restante.seconds // 3600

                        if dias > 0:

                            tiempo_texto = f"{dias} días"

                        elif horas > 0:

                            tiempo_texto = f"{horas} horas"

                        else:

                            tiempo_texto = "menos de 1 hora"


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
                        (user_id, invite_link)

                        VALUES (%s, %s)

                    """, (user_id, link))


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


        # =========================
        # PASO 1 — NOMBRE GRUPO
        # =========================

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


            plans = context.user_data["new_group_data"]["plans"]

            plans.append({

                "name": context.user_data["current_plan_name"],
                "price_id": context.user_data["current_price_id"],
                "duration_days": duration_days

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

                # buscar grupo

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


                # guardar planes

                for plan in group_data["plans"]:

                    cur.execute("""

                        INSERT INTO plans
                        (group_id, name, price_id, duration_days)

                        VALUES (%s, %s, %s, %s)

                    """, (

                        group_id,
                        plan["name"],
                        plan["price_id"],
                        plan["duration_days"]

                    ))


            await update.message.reply_text(

                "✅ Grupo y planes creados correctamente."

            )


            context.user_data["creating_group"] = False

            return
            
    # =========================
    # USO NORMAL DE CÓDIGO
    # =========================

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


        # 🔴 REVOCAR LINKS ANTIGUOS

        cur.execute("""

            SELECT invite_link
            FROM invite_links
            WHERE user_id=%s

        """, (update.effective_user.id,))

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

                print("Error revocando link:", e)


        # borrar antiguos

        cur.execute("""

            DELETE FROM invite_links
            WHERE user_id=%s

        """, (update.effective_user.id,))

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
                (user_id, invite_link)

                VALUES (%s, %s)

            """, (

                update.effective_user.id,
                link

            ))

            conn.commit()

    except Exception as e:

        print("Error guardando invite link:", e)


    # =========================
    # CALCULAR TIEMPO RESTANTE
    # =========================

    if expiration is None:

        tiempo_texto = "♾️ Permanente"

    else:

        tiempo_restante = expiration - datetime.now()

        dias = tiempo_restante.days
        horas = tiempo_restante.seconds // 3600
        minutos = (tiempo_restante.seconds % 3600) // 60

        if dias > 0:

            tiempo_texto = f"{dias} días"

        elif horas > 0:

            tiempo_texto = f"{horas} horas"

        else:

            tiempo_texto = f"{minutos} minutos"


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

    if plan == "1":
        price_id = PRICE_1_DIA

    elif plan == "7":
        price_id = PRICE_7_DIAS

    elif plan == "0":
        price_id = PRICE_PERMANENTE

    else:
        return jsonify({"error": "Plan inválido"}), 400


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


        # =========================
        # CALCULAR DURACIÓN
        # =========================

        if price_id == PRICE_1_DIA:

            expiration = datetime.now() + timedelta(days=1)
            plan_name = "1 día"

        elif price_id == PRICE_7_DIAS:

            expiration = datetime.now() + timedelta(days=7)
            plan_name = "7 días"

        elif price_id == PRICE_PERMANENTE:

            expiration = None
            plan_name = "Permanente"

        else:

            expiration = None
            plan_name = "Desconocido"


        # =========================
        # GUARDAR USUARIO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

            INSERT INTO users
            (user_id, expiration)

            VALUES (%s, %s)

            ON CONFLICT (user_id)
            DO UPDATE SET expiration=%s

            """, (

                user_id,
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

        invite_link = requests.post(

            f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

            json={
                "chat_id": get_group_id(),
                "member_limit": 1
            }

        ).json()


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

                """, (user_id,))


                # guardar nuevo

                cur.execute("""

                    INSERT INTO invite_links
                    (user_id, invite_link)

                    VALUES (%s, %s)

                """, (user_id, link))

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

        user_id = member.id

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
                            "chat_id": get_group_id(),
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


                    # buscar dueño del link

                    used_link = None

                    try:

                        used_link = update.message.invite_link.invite_link

                    except:

                        used_link = None


                    if used_link:

                        cur.execute("""

                        SELECT user_id
                        FROM invite_links
                        WHERE invite_link=%s

                        """, (used_link,))

                        owner = cur.fetchone()

                    else:

                        owner = None


                    if owner:

                        owner_id = owner[0]


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

                        """, (owner_id,))

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


                        cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s

                        """, (owner_id,))


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
                                    "chat_id": get_group_id(),
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

                            invite_link = requests.post(

                                f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

                                json={
                                    "chat_id": get_group_id(),
                                    "member_limit": 1
                                }

                            ).json()

                            new_link = invite_link["result"]["invite_link"]


                            # =========================
                            # GUARDAR LINK NUEVO
                            # =========================

                            cur.execute("""

                                INSERT INTO invite_links
                                (user_id, invite_link)

                                VALUES (%s, %s)

                            """, (owner_id, new_link))

                            conn.commit()


                            # =========================
                            # AVISO USUARIO + LINK
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


                else:

                    expiration = row[0]


                    if expiration and datetime.now() > expiration:

                        print("Usuario expirado:", user_id)


                        cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s

                        """, (user_id,))


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

                    else:

                        # =========================
                        # NUEVA BIENVENIDA CON TIEMPO RESTANTE
                        # =========================

                        try:

                            if expiration is None:

                                tiempo_texto = "♾️ Permanente"

                            else:

                                tiempo_restante = expiration - datetime.now()

                                dias = tiempo_restante.days
                                horas = tiempo_restante.seconds // 3600

                                if dias > 0:

                                    tiempo_texto = f"{dias} días"

                                elif horas > 0:

                                    tiempo_texto = f"{horas} horas"

                                else:

                                    tiempo_texto = "menos de 1 hora"


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

                                        "chat_id": get_group_id(),

                                        "message_id": message_id

                                    }

                                )

                        except Exception as e:

                            print("Error bienvenida:", e)


        except Exception as e:

            print("Error verificando miembro:", e)


# =========================
# DETECTAR BOT AÑADIDO A GRUPO
# =========================

async def detect_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    if not update.message.new_chat_members:
        return


    bot_id = int(TOKEN.split(":")[0])


    for member in update.message.new_chat_members:


        # =========================
        # SI EL MIEMBRO ES EL BOT
        # =========================

        if member.id == bot_id:

            group_id = update.message.chat.id
            group_name = update.message.chat.title

            print("Bot añadido a grupo:", group_name, group_id)


            try:

                # =========================
                # VERIFICAR PERMISOS ADMIN
                # =========================

                r = requests.get(

                    f"https://api.telegram.org/bot{TOKEN}/getChatMember",

                    params={

                        "chat_id": group_id,
                        "user_id": bot_id

                    }

                ).json()


                status = r["result"]["status"]


                if status not in ["administrator", "creator"]:

                    await context.bot.send_message(

                        chat_id=ADMIN_ID,

                        text=

                        "⚠️ BOT AÑADIDO A GRUPO\n\n"

                        f"Grupo: {group_name}\n"

                        f"ID: {group_id}\n\n"

                        "❌ El bot NO es administrador.\n"

                        "Debes darle permisos completos."

                    )

                    return


                # =========================
                # GUARDAR GRUPO EN DATABASE
                # =========================

                with conn.cursor() as cur:

                    cur.execute("""

                        INSERT INTO groups
                        (name, telegram_group_id)

                        VALUES (%s, %s)

                        ON CONFLICT DO NOTHING

                    """, (

                        group_name,
                        group_id

                    ))


                await context.bot.send_message(

                    chat_id=ADMIN_ID,

                    text=

                    "✅ NUEVO GRUPO DETECTADO\n\n"

                    f"Nombre: {group_name}\n"

                    f"ID: {group_id}\n\n"

                    "El grupo ha sido registrado correctamente."

                )


            except Exception as e:

                print("Error detectando grupo:", e)

                await context.bot.send_message(

                    chat_id=ADMIN_ID,

                    text="❌ Error verificando grupo nuevo."

                )


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

                        print("Expulsando expirado:", user_id)

                        # =========================
                        # REVOCAR LINKS DEL USUARIO
                        # =========================

                        cur.execute("""

                        SELECT invite_link
                        FROM invite_links
                        WHERE user_id=%s

                        """, (user_id,))

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

                                print("Error revocando link expirado:", e)


                        # =========================
                        # BORRAR LINKS GUARDADOS
                        # =========================

                        cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s

                        """, (user_id,))


                        # =========================
                        # EXPULSAR USUARIO
                        # =========================

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


                        # =========================
                        # ELIMINAR DE USERS
                        # =========================

                        cur.execute("""

                        DELETE FROM users
                        WHERE user_id=%s

                        """, (user_id,))


                        conn.commit()


                        # =========================
                        # AVISAR AL ADMIN
                        # =========================

                        requests.post(

                            f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                            json={
                                "chat_id": ADMIN_ID,
                                "text":
                                f"⛔ Usuario expirado eliminado\n\n"
                                f"User ID: {user_id}"
                            }

                        )


                    except Exception as e:

                        print("Error procesando expiración:", e)

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
    # MENSAJE BIENVENIDA
    # =========================

    mensaje = (

        "👋 Bienvenido\n\n"

        "Nos alegra que estés aquí.\n\n"

        "A continuación puedes ver los grupos disponibles.\n\n"

        "Selecciona uno para ver sus planes."

    )


    await update.message.reply_text(

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

                    SELECT name, price_id

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


        for name, price_id in plans:

            keyboard.append([

                InlineKeyboardButton(

                    name,

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
                ORDER BY created_at DESC
                LIMIT 1

            """, (user_id,))

            link_row = cur.fetchone()


        if link_row:

            link = link_row[0]

        else:

            invite_link = requests.post(

                f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

                json={
                    "chat_id": get_group_id(),
                    "member_limit": 1
                }

            ).json()

            link = invite_link["result"]["invite_link"]

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO invite_links
                    (user_id, invite_link)

                    VALUES (%s, %s)

                """, (user_id, link))

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

            [InlineKeyboardButton("📋 Ver grupos", callback_data="admin_view_groups")],

            [InlineKeyboardButton("✏️ Editar grupo", callback_data="admin_edit_group")],

            [InlineKeyboardButton("❌ Eliminar grupo", callback_data="admin_delete_group")],

            [InlineKeyboardButton("👑 Gestionar admins", callback_data="admin_manage_admins")],

            [InlineKeyboardButton("🎬 Configurar preview", callback_data="admin_preview_group")],

            [InlineKeyboardButton("💳 Configurar planes", callback_data="admin_group_plans")],

            [InlineKeyboardButton("🔗 Vincular Stripe", callback_data="admin_link_stripe")],

            [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]

        ]

        await query.message.reply_text(

            "📦 GESTIÓN GRUPOS",

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

        await query.message.reply_text(

            "📦 CREAR NUEVO GRUPO\n\n"

            "Paso 1️⃣\n"
            "Introduce el nombre del grupo."

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

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/revokeChatInviteLink",

                        json={
                            "chat_id": get_group_id(),
                            "invite_link": link
                        }

                    )

                    total += 1

                except Exception as e:

                    print("Error revocando link:", e)


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

                    invite_link = requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

                        json={
                            "chat_id": get_group_id(),
                            "member_limit": 1
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
                            (user_id, invite_link)

                            VALUES (%s, %s)

                        """, (user_id, link))

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

        print(e)

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

    # 🔧 NUEVO COMANDO DEBUG

    telegram_app.add_handler(
        CommandHandler("debugdb", debug_db)
    )

    telegram_app.add_handler(
        CommandHandler("debuglinks", debug_links)
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

    # =========================
    # DETECTAR BOT Y USUARIOS NUEVOS
    # =========================

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            detect_bot_added
        ),
        group=0
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            check_new_member
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