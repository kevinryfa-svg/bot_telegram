import os
import stripe
import threading
import requests
import time
import asyncio

from flask import Flask

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

from invite_link_service import (
    create_telegram_invite_link,
    create_fresh_user_group_link,
    revoke_and_delete_user_group_links,
    revoke_telegram_invite_link
)

from telegram_group_actions import (
    ban_chat_member,
    unban_chat_member,
    kick_chat_member
)

from notification_service import (
    notify_super_admins,
    notify_group_admins
)

from warning_service import (
    add_user_warning,
    reset_user_warnings,
    get_user_warnings
)

from audit_log_service import (
    create_audit_log
)

from formatters import (
    format_tiempo_restante
)


from db import conn, create_tables
from rbac_helpers import (
    has_permission,
    is_super_admin
)
from debug_handlers import (
    debug_db,
    debug_links,
    debug_columns,
    debug_groups,
    fixdb_group_column
)
from admin_view_handlers import (
    ver_codigos,
    ver_usuarios
)
from expiration_worker import check_expirations
from group_registration_handler import detect_bot_added
from user_join_handler import detect_user_join
from ai_handler import (
    ia_command,
    asistente_command,
    salir_command,
    handle_ai_context_text
)
from start_handler import start
from code_admin_handler import (
    generar_codigo,
    crear_codigo_callback
)
from admin_panel_handler import admin_panel
import callback_router as callback_router_module
from callback_router import button
from code_flow_handler import receive_code
from admin_input_handler import receive_admin_inputs
from stripe_handler import stripe_webhook
from checkout_routes import register_checkout_routes
from web_server import run_flask_app
from group_service import (
    get_latest_telegram_group_id
)


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

register_checkout_routes(app)


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

    run_flask_app(app)


# =========================
# REVOCAR LINK SEGURO
# =========================

def revoke_link(chat_id, link):

    try:

        revoke_telegram_invite_link(
            TOKEN,
            chat_id,
            link
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

    return get_latest_telegram_group_id(
        GROUP_ID
    )


callback_router_module.revoke_link = revoke_link
callback_router_module.get_group_id = get_group_id


# =========================
# RBAC — GRUPOS ADMINISTRABLES
# =========================

def get_admin_groups(user_id):

    try:

        if is_super_admin(user_id):

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id, name, telegram_group_id
                    FROM groups
                    WHERE telegram_group_id != 0
                    AND is_active=TRUE

                    ORDER BY id ASC

                """)

                return cur.fetchall()


        with conn.cursor() as cur:

            cur.execute("""

                SELECT g.id,
                       g.name,
                       g.telegram_group_id

                FROM admins a

                JOIN groups g
                ON a.group_id = g.id

                WHERE a.user_id=%s
                AND a.is_active=TRUE
                AND g.is_active=TRUE
                AND g.telegram_group_id != 0

                ORDER BY g.id ASC

            """, (user_id,))

            return cur.fetchall()

    except Exception as e:

        print(
            "Error obteniendo grupos admin:",
            e
        )


    return []
    

async def handle_text(update, context):

    if context.user_data.get("editing_preview"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("editing_plan"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("adding_plan"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("waiting_code"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("ai_chat_mode"):
        await handle_ai_context_text(update, context)
        return

    await receive_code(update, context)


# =========================
# WEBHOOK STRIPE
# =========================

app.route("/webhook", methods=["POST"])(stripe_webhook)


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

                    ban_chat_member(
                        TOKEN,
                        telegram_group_id,
                        user_id
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

                    kick_chat_member(
                        TOKEN,
                        telegram_group_id,
                        user_id
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

                                kick_chat_member(
                                    TOKEN,
                                    telegram_group_id,
                                    user_id
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

                                    revoke_telegram_invite_link(
                                        TOKEN,
                                        telegram_group_id,
                                        link
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


                            expire_seconds = max(
                                60,
                                expire_timestamp - int(time.time())
                            )


                            new_link = create_telegram_invite_link(
                                TOKEN,
                                telegram_group_id,
                                expire_seconds=expire_seconds,
                                member_limit=1
                            )


                            if not new_link:

                                print(
                                    "Error creando nuevo link"
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

                        kick_chat_member(
                            TOKEN,
                            telegram_group_id,
                            user_id
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

                                    revoke_telegram_invite_link(
                                        TOKEN,
                                        telegram_group_id,
                                        link
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

                            new_link = create_telegram_invite_link(
                                TOKEN,
                                telegram_group_id,
                                expire_seconds=60,
                                member_limit=1
                            )

                            if new_link:

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

                                kick_chat_member(
                                    TOKEN,
                                    telegram_group_id,
                                    user_id
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


                        kick_chat_member(
                            TOKEN,
                            telegram_group_id,
                            user_id
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
        CommandHandler("ia", ia_command)
    )

    telegram_app.add_handler(
        CommandHandler("asistente", asistente_command)
    )

    telegram_app.add_handler(
        CommandHandler("salir", salir_command)
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
            handle_text
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
