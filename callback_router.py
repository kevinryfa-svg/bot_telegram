import os
import requests
import time

from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from ai_handler import activate_ai_help_context
from code_admin_handler import crear_codigo_callback
from commercial_catalog import (
    COMMERCIAL_MENU_TEXT_ES,
    COMMERCIAL_PRODUCTS,
    PRODUCT_SHARED_BOT_SPACE,
    PRODUCT_CUSTOM_BOT,
    CALLBACK_SHARED_BOT_SPACE,
    CALLBACK_CUSTOM_BOT,
    CALLBACK_COMMERCIAL_CONTACT,
    CALLBACK_COMMERCIAL_BACK
)
from db import conn
from formatters import format_tiempo_restante
from invite_link_service import (
    create_telegram_invite_link,
    revoke_telegram_invite_link
)
from rbac_helpers import is_super_admin
from start_handler import start
from telegram_group_actions import kick_chat_member


TOKEN = os.environ.get("TOKEN")
SERVER_URL = os.environ.get("SERVER_URL")
ADMIN_ID = 8761243211

revoke_link = None
get_group_id = None


# =========================
# BOTONES
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    user_id = query.from_user.id


    if data == "start_explore_groups":

        await query.message.reply_text(
            "Debajo aparecen las comunidades privadas disponibles. "
            "Selecciona una para ver sus planes."
        )

        return


    if data == "start_no_groups":

        await query.message.reply_text(
            "Todavía no hay comunidades disponibles. "
            "Puedes contactar con soporte o volver más tarde."
        )

        return


    if data == "public_monetize_community":

        keyboard = [

            [InlineKeyboardButton(
                COMMERCIAL_PRODUCTS[PRODUCT_SHARED_BOT_SPACE]["title_es"],
                callback_data=CALLBACK_SHARED_BOT_SPACE
            )],

            [InlineKeyboardButton(
                COMMERCIAL_PRODUCTS[PRODUCT_CUSTOM_BOT]["title_es"],
                callback_data=CALLBACK_CUSTOM_BOT
            )],

            [InlineKeyboardButton(
                "📩 Hablar con un asesor",
                callback_data=CALLBACK_COMMERCIAL_CONTACT
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK
            )]

        ]

        await query.message.reply_text(

            COMMERCIAL_MENU_TEXT_ES,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if data == "public_support":

        await query.message.reply_text(
            "🛟 Soporte\n\n"
            "Puedes escribir tu incidencia y un administrador podrá ayudarte."
        )

        return


    if data == "public_ai_help":

        await activate_ai_help_context(
            update,
            context
        )

        return


    if data == "commercial_shared_bot_space":

        keyboard = [

            [InlineKeyboardButton(
                "📩 Quiero probar 1 día",
                callback_data=CALLBACK_COMMERCIAL_CONTACT
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK
            )]

        ]

        await query.message.reply_text(
            "📌 Publicar mi comunidad en este bot\n\n"
            "Esta opción es para creadores que quieren empezar rápido sin crear un bot propio.\n\n"
            "Tu comunidad aparecerá dentro de nuestro bot principal. "
            "Los usuarios podrán verla, elegir un plan y comprar acceso desde aquí.\n\n"
            "✅ Incluye:\n"
            "• Publicación de tu comunidad dentro del bot.\n"
            "• Planes de acceso configurables.\n"
            "• Pagos y accesos automatizados.\n"
            "• Links seguros para entrar al grupo.\n"
            "• Gestión básica desde el sistema.\n\n"
            "🎁 Prueba inicial:\n"
            "Puedes probar esta opción durante 1 día para publicar tu comunidad y comprobar cómo funciona.\n\n"
            "Después de la prueba, si quieres continuar, tendrás que activar una suscripción.\n\n"
            "Si una suscripción activa se detiene o no se renueva, la comunidad podrá dejar de mostrarse para nuevas compras. "
            "Aun así, guardaremos la configuración durante 15 días para que puedas reactivarla sin tener que empezar desde cero.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_custom_bot":

        keyboard = [

            [InlineKeyboardButton(
                "📩 Quiero configurar mi bot",
                callback_data=CALLBACK_COMMERCIAL_CONTACT
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK
            )]

        ]

        await query.message.reply_text(
            "🤖 Crear mi bot personalizado\n\n"
            "Esta opción es para quien quiere una experiencia más profesional con su propio bot de Telegram.\n\n"
            "El cliente crea su bot en BotFather y configura su información, marca, textos, grupos y planes. "
            "Después de completar la configuración, realiza el pago y el sistema se activa.\n\n"
            "✅ Incluye:\n"
            "• Bot propio con nombre y marca del cliente.\n"
            "• Configuración de comunidades, grupos y planes.\n"
            "• Pagos y accesos automatizados.\n"
            "• Gestión de usuarios, links y permisos.\n"
            "• Posibilidad de usar IA y soporte dentro del sistema.\n\n"
            "⚠️ Importante:\n"
            "El bot personalizado no tiene prueba gratuita. "
            "Primero se prepara la configuración completa y, una vez pagado, el bot empieza a funcionar.\n\n"
            "Si la suscripción se detiene o no se renueva, el bot podrá quedar bloqueado o desactivado. "
            "Guardaremos la configuración durante 15 días para que puedas reactivar el servicio sin perder lo preparado.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_contact":

        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=CALLBACK_COMMERCIAL_BACK
            )]

        ]

        await query.message.reply_text(
            "📩 Solicitud recibida\n\n"
            "Hemos registrado tu interés.\n\n"
            "Un administrador revisará tu solicitud y podrá ayudarte con la mejor opción según lo que necesites:\n\n"
            "• publicar tu comunidad dentro de nuestro bot;\n"
            "• crear un bot personalizado con tu marca;\n"
            "• resolver dudas sobre pagos, accesos o configuración.\n\n"
            "Más adelante añadiremos un formulario completo para recoger automáticamente todos los datos del proyecto.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "commercial_back":

        try:
            await query.message.delete()
        except:
            pass

        await start(update, context)

        return


    # =========================
    # RBAC — BLOQUEAR CALLBACKS ADMIN
    # =========================

    admin_prefixes = (

        "menu_",
        "admin_",
        "edit_group",
        "view_group_plans",
        "add_group_plan",
        "edit_plan_",
        "delete_group",
        "delete_plan_",
        "save_preview",
        "cancel_preview",
        "skip_preview",
        "allow_user_",
        "deny_user_",
        "gen_"

    )


    if data.startswith(admin_prefixes):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ No tienes permisos para usar esta acción."
            )

            return


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

        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=expire_seconds,
            member_limit=1
        )


        if not link:

            await query.message.reply_text(
                "❌ Error creando acceso."
            )

            return


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

                revoke_telegram_invite_link(
                    TOKEN,
                    get_group_id(),
                    old_link
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

        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            get_group_id(),
            expire_seconds=expire_seconds,
            member_limit=1
        )


        if not link:

            await query.message.reply_text(
                "❌ Error creando acceso."
            )

            return


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


                kick_chat_member(
                    TOKEN,
                    telegram_group_id,
                    user_id
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


                    link = create_telegram_invite_link(
                        TOKEN,
                        telegram_group_id,
                        expire_seconds=60,
                        member_limit=1
                    )


                    if not link:

                        print(
                            "Error creando link para usuario:",
                            user_id
                        )

                        continue


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
