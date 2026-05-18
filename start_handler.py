from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from commercial_catalog import (
    PUBLIC_START_TEXT_ES,
    CALLBACK_MONETIZE_COMMUNITY,
    CALLBACK_SUPPORT,
    CALLBACK_AI_HELP,
    CALLBACK_ADMIN_PANEL
)
from db import conn
from formatters import (
    format_tiempo_restante
)
from rbac_helpers import is_super_admin
from ui_menu_helpers import send_clean_message




def build_expired_trial_recovery_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "🎟 Tengo un código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "💳 Activar suscripción",
            callback_data=f"expired_trial_activate_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Ver configuración de mi comunidad",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "🗑 Eliminar comunidad definitivamente",
            callback_data=f"expired_trial_delete_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏠 Volver al inicio",
            callback_data="public_back_start"
        )]

    ])


async def expire_expired_start_trials(context):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   user_id,
                   approved_group_id,
                   approved_telegram_group_id
            FROM commercial_requests
            WHERE status='trial_active'
            AND trial_ends_at IS NOT NULL
            AND trial_ends_at < NOW()
            AND COALESCE(commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
            AND (
                approved_group_id IS NOT NULL
                OR approved_telegram_group_id IS NOT NULL
            )

        """)

        rows = cur.fetchall()


        for request_id, owner_user_id, approved_group_id, approved_telegram_group_id in rows:

            cur.execute("""

                UPDATE commercial_requests
                SET status='trial_expired',
                    requested_public_visibility='hidden',
                    updated_at=NOW()
                WHERE id=%s
                AND status='trial_active'

            """, (request_id,))


            if approved_group_id:

                cur.execute("""

                    UPDATE groups
                    SET public_visibility='hidden'
                    WHERE id=%s

                """, (approved_group_id,))


            elif approved_telegram_group_id:

                cur.execute("""

                    UPDATE groups
                    SET public_visibility='hidden'
                    WHERE telegram_group_id=%s

                """, (approved_telegram_group_id,))


            try:

                await context.bot.send_message(
                    chat_id=owner_user_id,
                    text=(
                        "Tu prueba ha finalizado. Para volver a publicar tu comunidad, "
                        "activa una suscripción."
                    ),
                    reply_markup=build_expired_trial_recovery_keyboard(request_id)
                )

            except Exception as e:

                print("Error avisando fin de trial comercial:", e)


def active_marketplace_trial_filter():

    return """
        NOT EXISTS (
            SELECT 1
            FROM commercial_requests cr
            WHERE (
                cr.approved_group_id = groups.id
                OR cr.approved_telegram_group_id = groups.telegram_group_id
            )
            AND cr.status='trial_active'
            AND cr.trial_ends_at IS NOT NULL
            AND cr.trial_ends_at < NOW()
            AND COALESCE(cr.commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
        )
    """

# =========================
# START BOT — MENÚ COMERCIAL
# =========================

async def send_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id=None):

    user_id = update.effective_user.id

    await expire_expired_start_trials(context)


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
                AND COALESCE(public_visibility, 'start_home')='start_home'
                AND """ + active_marketplace_trial_filter() + """

                ORDER BY id ASC

            """)

            home_groups = cur.fetchall()

            cur.execute("""

                SELECT id, name

                FROM groups

                WHERE is_active=TRUE
                AND telegram_group_id != 0
                AND COALESCE(public_visibility, 'start_home')='explore_only'
                AND """ + active_marketplace_trial_filter() + """

                ORDER BY id ASC

            """)

            explore_groups = cur.fetchall()

    except Exception as e:

        print("Error cargando grupos:", e)

        message = update.message or (
            update.callback_query.message
            if update.callback_query
            else None
        )

        if chat_id:

            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Error cargando comunidades disponibles."
            )

        elif message:

            await message.reply_text(
                "❌ Error cargando comunidades disponibles."
            )

        return


    # =========================
    # CREAR BOTONES PRINCIPALES
    # =========================

    keyboard = []


    keyboard.append([

        InlineKeyboardButton(

            "🔥 Explorar comunidades privadas",

            callback_data="start_explore_groups"

        )

    ])


    for group_id, group_name in home_groups:

        keyboard.append([

            InlineKeyboardButton(

                group_name,

                callback_data=f"group_{group_id}"

            )

        ])


    # =========================
    # BOTÓN MIS SUSCRIPCIONES
    # =========================

    has_subscriptions = False

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1

                FROM users

                WHERE user_id=%s
                AND COALESCE(subscription_active, FALSE)=TRUE
                AND (
                    expiration IS NULL
                    OR expiration > %s
                )

                LIMIT 1

            """, (user_id, datetime.now()))

            has_subscriptions = cur.fetchone() is not None

    except Exception as e:

        print("Error verificando suscripciones:", e)


    if has_subscriptions:

        keyboard.append([

            InlineKeyboardButton(

                "🎟 Gestionar mi acceso",

                callback_data="mis_subs"

            )

        ])

    else:

        keyboard.append([

            InlineKeyboardButton(

                "🎟 Ya tengo acceso / recuperar enlace",

                callback_data="mis_subs"

            )

        ])


    # =========================
    # BOTONES COMERCIALES PÚBLICOS
    # =========================

    keyboard.append([

        InlineKeyboardButton(

            "🚀 Soluciones para mi comunidad",

            callback_data=CALLBACK_MONETIZE_COMMUNITY

        )

    ])


    keyboard.append([

        InlineKeyboardButton(

            "🛟 Soporte",

            callback_data=CALLBACK_SUPPORT

        ),

        InlineKeyboardButton(

            "💬 Ayuda sobre este menú",

            callback_data=CALLBACK_AI_HELP

        )

    ])


    # =========================
    # PANEL SEGÚN JERARQUÍA REAL
    # =========================

    try:

        if is_super_admin(user_id):

            keyboard.append([

                InlineKeyboardButton(

                    "⚙️ Panel global",

                    callback_data=CALLBACK_ADMIN_PANEL

                )

            ])

        else:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT 1

                    FROM admins

                    WHERE user_id=%s
                    AND is_active=TRUE

                    LIMIT 1

                """, (user_id,))

                admin_row = cur.fetchone()


            if admin_row:

                keyboard.append([

                    InlineKeyboardButton(

                        "⚙️ Mi panel de gestión",

                        callback_data=CALLBACK_ADMIN_PANEL

                    )

                ])

    except Exception as e:

        print("Error verificando panel admin:", e)


    # =========================
    # COMPROBAR SUSCRIPCIONES ACTIVAS
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
                AND COALESCE(u.subscription_active, FALSE)=TRUE
                AND (
                    u.expiration IS NULL
                    OR u.expiration > %s
                )

                ORDER BY g.name ASC

            """, (user_id, datetime.now()))

            subs = cur.fetchall()


        if subs:

            for group_name, expiration in subs:

                if expiration is None or expiration > datetime.now():

                    tiempo_texto = format_tiempo_restante(
                        expiration
                    )

                    suscripciones_texto += (

                        f"⏳ Tu acceso actual a "
                        f"{group_name}:\n"

                        f"{tiempo_texto}\n\n"

                    )

    except Exception as e:

        print(
            "Error cargando suscripciones:",
            e
        )


    # =========================
    # MENSAJE BIENVENIDA
    # =========================

    if suscripciones_texto:

        mensaje = (

            f"{PUBLIC_START_TEXT_ES}\n\n"

            f"{suscripciones_texto}"

        )

    else:

        mensaje = PUBLIC_START_TEXT_ES


    message = update.message or (
        update.callback_query.message
        if update.callback_query
        else None
    )


    target_chat_id = chat_id or message.chat_id


    await send_clean_message(

        context,

        target_chat_id,

        mensaje,

        reply_markup=InlineKeyboardMarkup(keyboard)

    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await send_start_menu(update, context)
