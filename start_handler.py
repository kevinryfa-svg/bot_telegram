from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import ContextTypes

from commercial_catalog import (
    PUBLIC_START_TEXT_ES,
    CALLBACK_MONETIZE_COMMUNITY,
    CALLBACK_SUPPORT,
    CALLBACK_AI_HELP,
    CALLBACK_ADMIN_PANEL
)
from bot_config import ADMIN_ID
from db import conn
from group_service import format_community_kind, format_community_kind_capitalized, normalize_community_type
from formatters import (
    format_tiempo_restante
)
from rbac_helpers import is_super_admin
from reengagement_service import fetch_offer_snapshot, format_price
from ui_menu_helpers import send_clean_message
from user_activity_logger import log_user_event
from wizard_state_helpers import clear_location_flow_state


# =========================
# BIENVENIDA CON DATOS REALES
# =========================

def build_public_start_message():
    """
    La bienvenida es la pantalla que ve todo el mundo, y era puramente
    genérica: no decía cuántas comunidades hay, ni desde qué precio, ni qué
    pasa al pagar. Aquí se compone con datos reales del catálogo. Si algo
    falla o no hay catálogo, se usa el texto original.
    """

    try:

        offer = fetch_offer_snapshot(limit=3)

    except Exception as e:

        print("Inicio: no se pudo leer el catálogo:", e)
        return PUBLIC_START_TEXT_ES


    total = offer.get("total") or 0


    if not total:

        return PUBLIC_START_TEXT_ES


    price = format_price(
        offer.get("cheapest_amount"),
        offer.get("cheapest_currency")
    )
    free_total = offer.get("free_total") or 0

    noun = "comunidad privada" if total == 1 else "comunidades privadas"
    plural = "" if total == 1 else "s"
    catalog_line = f"Hay {total} {noun} disponible{plural}"


    if price:

        catalog_line += f", desde {price}"


    lines = [
        "👋 Bienvenido",
        "",
        catalog_line + "."
    ]


    if free_total == 1:

        lines.append("1 de ellas es de acceso gratuito.")

    elif free_total > 1:

        lines.append(f"{free_total} de ellas son de acceso gratuito.")


    lines.extend([
        "",
        "Cómo funciona:",
        "1️⃣ Eliges la comunidad que te interesa.",
        "2️⃣ Pagas con tarjeta de forma segura.",
        "3️⃣ Recibes al instante tu enlace de acceso privado.",
        "",
        "🔒 Tu enlace es personal y de un solo uso.",
        "🛟 Tienes soporte directo aquí en el bot.",
        "",
        "Selecciona una opción:"
    ])

    return "\n".join(lines)




def build_expired_trial_recovery_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "💳 Reactivar pagando",
            callback_data=f"expired_trial_activate_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Reactivar con código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Ver configuración",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "🗑 Eliminar ahora definitivamente",
            callback_data=f"expired_trial_delete_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


def build_expired_trial_reminder_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "💳 Reactivar pagando",
            callback_data=f"expired_trial_activate_{request_id}"
        )],

        [InlineKeyboardButton(
            "🎟 Usar código promocional",
            callback_data=f"creator_promo_code_start_{request_id}"
        )],

        [InlineKeyboardButton(
            "📦 Ver configuración",
            callback_data=f"configure_community_{request_id}"
        )]

    ])


def format_retention_days_left(delete_after):

    if not delete_after:

        return 0


    try:

        remaining_seconds = (delete_after - datetime.now()).total_seconds()
        remaining_days = int((remaining_seconds + 86399) // 86400)

        return max(remaining_days, 0)

    except Exception:

        return 0


def expired_community_message(days_left=None):

    text = (
        "Tu comunidad ha caducado.\n"
        "Tus datos se conservarán durante 15 días.\n"
        "Puedes reactivarla pagando o usando un código promocional."
    )


    if days_left is not None:

        text += f"\n\nTe quedan {days_left} días antes del borrado definitivo."


    return text


RECOVERABLE_CREATOR_STATUSES = (
    "approved",
    "trial_active",
    "awaiting_creator_setup",
    "setup_in_progress",
    "setup_ready",
    "active",
    "expired_pending_reactivation"
)


RECOVERABLE_CREATOR_SETUP_STATUSES = (
    "awaiting_creator_setup",
    "pending_group_link",
    "setup_in_progress",
    "setup_ready"
)


def fetch_pending_creator_group_link(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   commercial_request_id,
                   telegram_group_id,
                   COALESCE(community_type, 'group'),
                   group_name
            FROM creator_group_link_requests
            WHERE user_id=%s
            AND status='pending'
            ORDER BY updated_at DESC NULLS LAST,
                     created_at DESC
            LIMIT 1

        """, (user_id,))

        row = cur.fetchone()


    if not row:

        return None


    return {
        "id": row[0],
        "request_id": row[1],
        "telegram_group_id": row[2],
        "community_type": normalize_community_type(row[3]),
        "group_name": row[4]
    }


def fetch_recoverable_creator_request(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   status,
                   creator_setup_status,
                   approved_group_id,
                   approved_telegram_group_id,
                   trial_ends_at
            FROM commercial_requests
            WHERE user_id=%s
            AND request_type='shared_trial'
            AND COALESCE(status, 'pending') NOT IN (
                'pending',
                'rejected',
                'archived',
                'closed',
                'deleted_irreversible'
            )
            AND (
                status = ANY(%s)
                OR creator_setup_status = ANY(%s)
                OR approved_group_id IS NOT NULL
                OR approved_telegram_group_id IS NOT NULL
            )
            ORDER BY reviewed_at DESC NULLS LAST,
                     updated_at DESC NULLS LAST,
                     created_at DESC
            LIMIT 1

        """, (
            user_id,
            list(RECOVERABLE_CREATOR_STATUSES),
            list(RECOVERABLE_CREATOR_SETUP_STATUSES)
        ))

        row = cur.fetchone()


    if not row:

        return None


    return {
        "id": row[0],
        "status": row[1],
        "creator_setup_status": row[2],
        "approved_group_id": row[3],
        "approved_telegram_group_id": row[4],
        "trial_ends_at": row[5]
    }


def hide_group_for_expired_request(cur, approved_group_id, approved_telegram_group_id):

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


def finalize_expired_group(cur, approved_group_id, approved_telegram_group_id):

    if approved_group_id:

        cur.execute("""

            UPDATE groups
            SET is_active=FALSE,
                public_visibility='hidden',
                preview_text=NULL,
                preview_image_file_id=NULL,
                preview_video_file_id=NULL,
                category=NULL,
                tags=NULL,
                marketplace_badge=NULL
            WHERE id=%s

        """, (approved_group_id,))

    elif approved_telegram_group_id:

        cur.execute("""

            UPDATE groups
            SET is_active=FALSE,
                public_visibility='hidden',
                preview_text=NULL,
                preview_image_file_id=NULL,
                preview_video_file_id=NULL,
                category=NULL,
                tags=NULL,
                marketplace_badge=NULL
            WHERE telegram_group_id=%s

        """, (approved_telegram_group_id,))


async def send_expiry_message(context, user_id, request_id, delete_after):

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=expired_community_message(
                format_retention_days_left(delete_after)
            ),
            reply_markup=build_expired_trial_recovery_keyboard(request_id)
        )

    except Exception as e:

        print("Error avisando comunidad caducada:", e)


async def send_expiry_reminder(context, user_id, request_id, delete_after):

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "Te quedan "
                f"{format_retention_days_left(delete_after)} días "
                "para reactivar tu comunidad antes del borrado definitivo."
            ),
            reply_markup=build_expired_trial_reminder_keyboard(request_id)
        )

    except Exception as e:

        print("Error enviando recordatorio de comunidad caducada:", e)


async def notify_final_deletion_admin(context, request_id, user_id):

    try:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🗑 Comunidad marcada con borrado definitivo\n\n"
                f"Solicitud #{request_id}\n"
                f"Usuario: {user_id}\n"
                "Se ocultó definitivamente y se limpió la configuración marketplace."
            )
        )

    except Exception as e:

        print("Error avisando borrado definitivo comercial:", e)


async def expire_expired_start_trials(context):

    newly_expired = []
    reminders = []
    finalized = []


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   user_id,
                   approved_group_id,
                   approved_telegram_group_id
            FROM commercial_requests
            WHERE (
                (
                    status='trial_active'
                    AND trial_ends_at IS NOT NULL
                    AND trial_ends_at < NOW()
                    AND COALESCE(commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
                )
                OR (
                    status='active'
                    AND commercial_subscription_until IS NOT NULL
                    AND commercial_subscription_until < NOW()
                )
            )
            AND (
                approved_group_id IS NOT NULL
                OR approved_telegram_group_id IS NOT NULL
            )

        """)

        rows = cur.fetchall()


        for request_id, owner_user_id, approved_group_id, approved_telegram_group_id in rows:

            cur.execute("""

                UPDATE commercial_requests cr
                SET status='expired_pending_reactivation',
                    commercial_subscription_status='expired',
                    previous_public_visibility=COALESCE(
                        NULLIF(cr.previous_public_visibility, 'hidden'),
                        NULLIF(cr.requested_public_visibility, 'hidden'),
                        NULLIF(g.public_visibility, 'hidden'),
                        'explore_only'
                    ),
                    requested_public_visibility='hidden',
                    expired_at=NOW(),
                    delete_after=NOW() + INTERVAL '15 days',
                    last_expiry_reminder_at=NOW(),
                    updated_at=NOW()
                FROM groups g
                WHERE cr.id=%s
                AND (
                    cr.approved_group_id = g.id
                    OR cr.approved_telegram_group_id = g.telegram_group_id
                )
                RETURNING cr.delete_after

            """, (request_id,))

            row = cur.fetchone()


            if not row:

                cur.execute("""

                    UPDATE commercial_requests
                    SET status='expired_pending_reactivation',
                        commercial_subscription_status='expired',
                        previous_public_visibility=COALESCE(
                            NULLIF(previous_public_visibility, 'hidden'),
                            NULLIF(requested_public_visibility, 'hidden'),
                            'explore_only'
                        ),
                        requested_public_visibility='hidden',
                        expired_at=NOW(),
                        delete_after=NOW() + INTERVAL '15 days',
                        last_expiry_reminder_at=NOW(),
                        updated_at=NOW()
                    WHERE id=%s
                    RETURNING delete_after

                """, (request_id,))

                row = cur.fetchone()


            hide_group_for_expired_request(
                cur,
                approved_group_id,
                approved_telegram_group_id
            )

            newly_expired.append((
                request_id,
                owner_user_id,
                row[0] if row else None
            ))


        cur.execute("""

            SELECT id,
                   user_id,
                   delete_after
            FROM commercial_requests
            WHERE status='expired_pending_reactivation'
            AND delete_after IS NOT NULL
            AND delete_after > NOW()
            AND (
                last_expiry_reminder_at IS NULL
                OR last_expiry_reminder_at < NOW() - INTERVAL '1 day'
            )

        """)

        rows = cur.fetchall()


        for request_id, owner_user_id, delete_after in rows:

            cur.execute("""

                UPDATE commercial_requests
                SET last_expiry_reminder_at=NOW(),
                    updated_at=NOW()
                WHERE id=%s

            """, (request_id,))

            reminders.append((
                request_id,
                owner_user_id,
                delete_after
            ))


        cur.execute("""

            SELECT id,
                   user_id,
                   approved_group_id,
                   approved_telegram_group_id
            FROM commercial_requests
            WHERE status='expired_pending_reactivation'
            AND delete_after IS NOT NULL
            AND delete_after <= NOW()

        """)

        rows = cur.fetchall()


        for request_id, owner_user_id, approved_group_id, approved_telegram_group_id in rows:

            cur.execute("""

                UPDATE commercial_requests
                SET status='deleted_irreversible',
                    commercial_subscription_status='cancelled',
                    requested_public_visibility='hidden',
                    updated_at=NOW()
                WHERE id=%s

            """, (request_id,))

            finalize_expired_group(
                cur,
                approved_group_id,
                approved_telegram_group_id
            )

            finalized.append((
                request_id,
                owner_user_id
            ))


    for request_id, owner_user_id, delete_after in newly_expired:

        await send_expiry_message(
            context,
            owner_user_id,
            request_id,
            delete_after
        )


    for request_id, owner_user_id, delete_after in reminders:

        await send_expiry_reminder(
            context,
            owner_user_id,
            request_id,
            delete_after
        )


    for request_id, owner_user_id in finalized:

        await notify_final_deletion_admin(
            context,
            request_id,
            owner_user_id
        )


def active_marketplace_trial_filter():

    return """
        NOT EXISTS (
            SELECT 1
            FROM commercial_requests cr
            WHERE (
                cr.approved_group_id = groups.id
                OR cr.approved_telegram_group_id = groups.telegram_group_id
            )
            AND (
                (
                    cr.status='trial_active'
                    AND cr.trial_ends_at IS NOT NULL
                    AND cr.trial_ends_at < NOW()
                    AND COALESCE(cr.commercial_subscription_status, 'pending') NOT IN ('active', 'paid')
                )
                OR cr.status='expired_pending_reactivation'
            )
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
                AND (
                    COALESCE(is_main_menu_visible, FALSE)=TRUE
                    OR COALESCE(public_visibility, 'start_home') IN ('start_home', 'both')
                )
                AND """ + active_marketplace_trial_filter() + """

                ORDER BY id ASC

            """)

            home_groups = cur.fetchall()

            cur.execute("""

                SELECT id, name

                FROM groups

                WHERE is_active=TRUE
                AND telegram_group_id != 0
                AND (
                    COALESCE(is_marketplace_visible, FALSE)=TRUE
                    OR COALESCE(public_visibility, 'start_home') IN ('explore_only', 'both')
                )
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
    creator_recovery_text = ""


    try:

        pending_group_link = fetch_pending_creator_group_link(user_id)
        recoverable_request = fetch_recoverable_creator_request(user_id)

    except Exception as e:

        print("Error cargando recuperación creator:", e)
        pending_group_link = None
        recoverable_request = None


    if pending_group_link:

        pending_kind = format_community_kind(
            pending_group_link.get("community_type")
        )
        pending_kind_cap = format_community_kind_capitalized(
            pending_group_link.get("community_type")
        )
        creator_recovery_text = (
            f"He detectado un {pending_kind} pendiente de confirmar.\n\n"
            f"{pending_kind_cap}: {pending_group_link.get('group_name') or '-'}\n"
            f"ID: {pending_group_link.get('telegram_group_id') or '-'}"
        )

        keyboard.append([
            InlineKeyboardButton(
                f"✅ Confirmar {pending_kind}",
                callback_data=f"confirm_creator_group_link_{pending_group_link['id']}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "❌ Cancelar vinculación",
                callback_data=f"cancel_creator_group_link_{pending_group_link['id']}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "📦 Ver estado",
                callback_data=f"configure_community_{pending_group_link['request_id']}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "🛟 Soporte",
                callback_data=CALLBACK_SUPPORT
            ),
            InlineKeyboardButton(
                "🏠 Inicio",
                callback_data="public_back_start"
            )
        ])

    elif recoverable_request:

        request_id = recoverable_request["id"]
        creator_recovery_text = "Ya tienes una prueba/configuración pendiente."

        keyboard.append([
            InlineKeyboardButton(
                "🔄 Recuperar configuración",
                callback_data=f"configure_community_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "📡 Añadir grupo/canal",
                callback_data=f"creator_setup_group_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "🎟 Tengo código promocional",
                callback_data=f"creator_promo_code_start_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "🧹 Reiniciar configuración",
                callback_data=f"creator_setup_reset_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "🛟 Soporte",
                callback_data=CALLBACK_SUPPORT
            ),
            InlineKeyboardButton(
                "🏠 Inicio",
                callback_data="public_back_start"
            )
        ])


    # "Explorar comunidades" solo si de verdad hay algo que explorar que no esté
    # ya como botón directo aquí abajo. Si el catálogo de explorar está vacío,
    # este botón llevaba a "Todavía no hay comunidades publicadas": un callejón
    # sin salida en la primera pantalla. Y si muestra lo mismo que los botones
    # de abajo, es un toque de más para llegar al mismo sitio.
    ya_visibles = {group_id for group_id, _ in home_groups}
    hay_algo_mas = any(
        group_id not in ya_visibles
        for group_id, _ in explore_groups
    )

    if hay_algo_mas:

        keyboard.append([

            InlineKeyboardButton(

                "🔎 Explorar comunidades",

                callback_data="start_explore_groups"

            )

        ])


    for group_id, group_name in home_groups:

        keyboard.append([

            InlineKeyboardButton(

                f"➡️ Ver comunidad — {group_name}",

                callback_data=f"marketplace_group_{group_id}"

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


    # "Mis accesos" solo si tiene alguno. A quien llega sin nada, el botón
    # prometía "recuperar" y le llevaba a "No tienes suscripciones activas": un
    # toque perdido justo en la pantalla donde hay que decidir si comprar.
    if has_subscriptions:

        keyboard.append([

            InlineKeyboardButton(

                "🎟 Mis accesos",

                callback_data="mis_subs"

            )

        ])


    # =========================
    # AYUDA Y SOPORTE
    # =========================
    # Antes había DOS botones de ayuda con IA en esta misma pantalla:
    # "💬 Ayuda sobre este menú" y "🤖 Ayuda inteligente". El primero solo
    # activaba el modo de texto libre y dejaba al usuario sin ningún botón; el
    # segundo lleva a un panel que resuelve justo las dudas que frenan una
    # compra ("Pagué y no tengo link", "Cómo puedo pagar"). Se queda el bueno, y
    # el modo de texto libre sigue estando dentro, en "✍️ Preguntar a la IA".

    keyboard.append([

        InlineKeyboardButton(

            "🤖 Resolver una duda",

            callback_data="ai_buyer_panel"

        ),

        InlineKeyboardButton(

            "🛟 Soporte",

            callback_data=CALLBACK_SUPPORT

        )

    ])


    # =========================
    # BOTONES COMERCIALES PÚBLICOS
    # =========================
    # Al final a propósito: va dirigido a otro público (quien quiere vender), y
    # en medio de las acciones del comprador competía con la compra.

    keyboard.append([

        InlineKeyboardButton(

            "🚀 Publicar mi comunidad",

            callback_data=CALLBACK_MONETIZE_COMMUNITY

        )

    ])


    # =========================
    # PANEL SEGÚN JERARQUÍA REAL
    # =========================

    try:

        if is_super_admin(user_id):

            keyboard.append([

                InlineKeyboardButton(

                    "👑 Panel global del bot",

                    callback_data=CALLBACK_ADMIN_PANEL

                )

            ])

        else:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT role

                    FROM admins

                    WHERE user_id=%s
                    AND is_active=TRUE

                    ORDER BY
                        CASE WHEN role='GROUP_OWNER' THEN 0 ELSE 1 END

                    LIMIT 1

                """, (user_id,))

                admin_row = cur.fetchone()


            if admin_row:

                keyboard.append([

                    InlineKeyboardButton(

                        (
                            "🏪 Mis comunidades"
                            if admin_row[0] == "GROUP_OWNER"
                            else "👮 Panel admin de grupo"
                        ),

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

    start_text = build_public_start_message()


    if suscripciones_texto:

        mensaje = (

            f"{start_text}\n\n"

            f"{suscripciones_texto}"

        )

    else:

        mensaje = start_text


    if creator_recovery_text:

        mensaje = f"{creator_recovery_text}\n\n{mensaje}"


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

    cleared_location_keys = clear_location_flow_state(context)

    if cleared_location_keys and update.effective_chat:

        try:

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="📍 Verificación de ubicación cancelada.",
                reply_markup=ReplyKeyboardRemove()
            )

        except Exception as e:

            print("Error quitando teclado de ubicación en /start:", e)


    # DEEP LINK POST-PAGO: el checkout de Stripe vuelve al bot con carga
    # (?start=pagado_<grupo> / cancelado_<grupo>). El que acaba de pagar
    # aterriza con su acceso a un toque en vez de buscar el mensaje del
    # webhook entre el historial; el que canceló, con el camino de vuelta.
    # Cualquier carga rara cae al menú de siempre: nunca un callejón.
    carga = (context.args[0] if getattr(context, "args", None) else "") or ""

    if carga.startswith(("pagado_", "cancelado_")):

        try:

            from i18n_service import load_user_language, t

            ref = int(carga.split("_", 1)[1])
            language = load_user_language(update.effective_user.id)

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id, name, telegram_group_id
                    FROM groups
                    WHERE id=%s OR telegram_group_id=%s
                    LIMIT 1

                """, (ref, ref))

                grupo = cur.fetchone()

            if grupo:

                log_user_event(
                    update,
                    "start",
                    event_key=f"/start {carga.split('_', 1)[0]}"
                )

                if carga.startswith("pagado_"):

                    await update.message.reply_text(
                        t("start.paid_landing", language, group=grupo[1] or ""),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                t("start.paid_button", language),
                                callback_data=f"mysub_{grupo[2]}"
                            )
                        ]])
                    )

                else:

                    await update.message.reply_text(
                        t("start.cancelled_landing", language,
                          group=grupo[1] or ""),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                t("start.retry_button", language),
                                callback_data=f"marketplace_group_{grupo[0]}"
                            )],
                            [InlineKeyboardButton(
                                t("start.problem_button", language),
                                callback_data="public_support"
                            )],
                        ])
                    )

                return

        except Exception as e:

            print("Deep link de pago: error, cayendo al menú:", str(e)[:200])


    log_user_event(
        update,
        "start",
        event_key="/start"
    )

    await send_start_menu(update, context)
