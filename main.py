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
                            "chat_id": GROUP_ID,
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
                                "chat_id": GROUP_ID,
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


                # eliminar usuario

                cur.execute("""

                    DELETE FROM users
                    WHERE user_id=%s

                """, (user_id,))


                conn.commit()


            requests.post(

                f"https://api.telegram.org/bot{TOKEN}/banChatMember",

                json={
                    "chat_id": GROUP_ID,
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

        user_id = update.message.text.strip()

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


                # permitir volver a entrar

                requests.post(

                    f"https://api.telegram.org/bot{TOKEN}/unbanChatMember",

                    json={
                        "chat_id": GROUP_ID,
                        "user_id": user_id
                    }

                )


                # =========================
                # SI TIENE SUSCRIPCIÓN ACTIVA
                # =========================

                if expiration and expiration > datetime.now():

                    # borrar links antiguos

                    cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s

                    """, (user_id,))


                    # crear link nuevo

                    invite_link = requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink",

                        json={
                            "chat_id": GROUP_ID,
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


                    # enviar link nuevo

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                        json={

                            "chat_id": user_id,

                            "text":

                            "♻️ Has sido desbaneado.\n\n"

                            "Tu suscripción sigue activa.\n"

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
                        "chat_id": GROUP_ID,
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
            "chat_id": GROUP_ID,
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
                "chat_id": GROUP_ID,
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
                            "chat_id": GROUP_ID,
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


                    # buscar dueño del link

                    cur.execute("""

                    SELECT user_id
                    FROM invite_links
                    ORDER BY created_at DESC
                    LIMIT 1

                    """)

                    owner = cur.fetchone()

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
                                        "chat_id": GROUP_ID,
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
                                    "chat_id": GROUP_ID,
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
                                    "chat_id": GROUP_ID,
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
                                        "chat_id": GROUP_ID,
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
# START BOT
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    with conn.cursor() as cur:

        cur.execute("""

            SELECT expiration
            FROM users
            WHERE user_id=%s

        """, (user_id,))

        row = cur.fetchone()

    # =========================
    # USUARIO EXISTENTE
    # =========================

    if row:

        expiration = row[0]

        if expiration and datetime.now() > expiration:

            keyboard = [

                [InlineKeyboardButton("🟢 1 día — 5€", callback_data="1")],
                [InlineKeyboardButton("🟡 7 días — 10€", callback_data="7")],
                [InlineKeyboardButton("🔵 Permanente — 25€", callback_data="0")]

            ]

            await update.message.reply_text(

                "⛔ Tu suscripción ha expirado.\n\nSelecciona un plan:",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )

            return


        keyboard = [

            [InlineKeyboardButton("🔄 Recuperar acceso", callback_data="recover_access")],

            [InlineKeyboardButton("🎟️ Usar código", callback_data="codigo")]

        ]

        await update.message.reply_text(

            "👋 Bienvenido de nuevo.\n\nPuedes recuperar tu acceso:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


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

        [InlineKeyboardButton("⛔ Banear usuario", callback_data="admin_ban_user")],

        [InlineKeyboardButton("♻️ Desbanear usuario", callback_data="admin_unban_user")],

        [InlineKeyboardButton("🔄 Revocar todos los links", callback_data="admin_revoke_links")],

        [InlineKeyboardButton("📩 Reenviar links nuevos", callback_data="admin_resend_links")],

        [InlineKeyboardButton("📜 Logs incidentes", callback_data="admin_logs")],

        [InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats")]

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
                    "chat_id": GROUP_ID,
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
                            "chat_id": GROUP_ID,
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
                            "chat_id": GROUP_ID,
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