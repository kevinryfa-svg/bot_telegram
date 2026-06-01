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
    ChatMemberHandler,
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
    complete_expired_beta_cycles,
    create_audit_log,
    is_beta_monitor_enabled,
    log_event,
    summarize_beta_monitor_events
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
from group_registration_handler import (
    capture_group_preview_video,
    detect_bot_added,
    detect_bot_channel_admin_update,
    detect_bot_removed,
    handle_backup_destination_token_command,
    handle_group_backup_media,
    handle_group_backup_text
)
from user_join_handler import detect_user_join
from user_activity_logger import log_user_event
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
from callback_router import (
    button,
    capture_ad_promo_video,
    process_ad_promo_daily_reviews,
    process_due_owner_backups,
    process_due_ad_promo_campaigns,
    receive_ad_promo_admin_text,
    receive_commercial_request_chat_message,
    receive_customer_satisfaction_text,
    receive_user_tracking_search_text,
    receive_group_user_promo_code,
    receive_owner_payment_provider_text,
    receive_support_message,
    receive_location_manual_review_form,
    receive_location_gate
)
from code_flow_handler import receive_code
from admin_input_handler import receive_admin_inputs
from commercial_form_handler import (
    receive_commercial_form,
    receive_creator_setup,
    receive_marketplace_preview_media
)
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


def get_commercial_expiry_job_interval_seconds():

    raw_value = os.environ.get(
        "COMMERCIAL_EXPIRY_JOB_INTERVAL_SECONDS",
        str(6 * 60 * 60)
    )


    try:

        return max(int(raw_value), 60 * 60)

    except Exception:

        print(
            "Commercial expiry scheduler: intervalo inválido, usando 6 horas."
        )

        return 6 * 60 * 60


COMMERCIAL_EXPIRY_JOB_INTERVAL_SECONDS = (
    get_commercial_expiry_job_interval_seconds()
)

LOCATION_MANUAL_REVIEW_EXPIRY_JOB_INTERVAL_SECONDS = int(
    os.environ.get(
        "LOCATION_MANUAL_REVIEW_EXPIRY_JOB_INTERVAL_SECONDS",
        str(6 * 60 * 60)
    )
)

BETA_MONITOR_SUMMARY_INTERVAL_SECONDS = int(
    os.environ.get(
        "BETA_MONITOR_SUMMARY_INTERVAL_SECONDS",
        str(6 * 60 * 60)
    )
)

AD_PROMO_SCHEDULER_INTERVAL_SECONDS = int(
    os.environ.get(
        "AD_PROMO_SCHEDULER_INTERVAL_SECONDS",
        "300"
    )
)

AD_PROMO_DAILY_REVIEW_INTERVAL_SECONDS = int(
    os.environ.get(
        "AD_PROMO_DAILY_REVIEW_INTERVAL_SECONDS",
        str(60 * 60)
    )
)

OWNER_BACKUP_SCHEDULER_INTERVAL_SECONDS = int(
    os.environ.get(
        "OWNER_BACKUP_SCHEDULER_INTERVAL_SECONDS",
        str(60 * 60)
    )
)


def sanitize_error_text(value):

    text = str(value or "")


    for env_name in (
        "TOKEN",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "WEBHOOK_SECRET",
        "DATABASE_URL"
    ):

        secret_value = os.environ.get(env_name)

        if secret_value and len(secret_value) > 6:

            text = text.replace(secret_value, "[redacted]")


    if TOKEN and len(TOKEN) > 6:

        text = text.replace(TOKEN, "[redacted]")


    return text[:500]


def get_update_error_context(update):

    update_type = None
    user_id = None
    chat_id = None
    callback_data = None


    try:

        if update is None:

            return {
                "update_type": None,
                "user_id": None,
                "chat_id": None,
                "callback_data": None
            }


        if getattr(update, "callback_query", None):

            update_type = "callback_query"
            callback_data = update.callback_query.data

        elif getattr(update, "message", None):

            update_type = "message"

        elif getattr(update, "edited_message", None):

            update_type = "edited_message"

        else:

            update_type = update.__class__.__name__


        effective_user = getattr(update, "effective_user", None)
        effective_chat = getattr(update, "effective_chat", None)


        if effective_user:

            user_id = effective_user.id

        if effective_chat:

            chat_id = effective_chat.id

    except Exception:

        pass


    return {
        "update_type": update_type,
        "user_id": user_id,
        "chat_id": chat_id,
        "callback_data": callback_data
    }


async def notify_user_about_handler_error(update, context):

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    text = (
        "⚠️ Ha ocurrido un error. "
        "Vuelve a intentarlo o pulsa Inicio."
    )


    try:

        if not update:

            return


        effective_chat = getattr(update, "effective_chat", None)

        if (
            effective_chat
            and getattr(effective_chat, "type", None) != "private"
        ):

            return


        if getattr(update, "callback_query", None):

            query = update.callback_query

            try:

                await query.answer()

            except Exception:

                pass


            if query.message:

                await query.message.reply_text(
                    text,
                    reply_markup=keyboard
                )

                return


        if getattr(update, "effective_message", None):

            await update.effective_message.reply_text(
                text,
                reply_markup=keyboard
            )

            return


        if effective_chat:

            await context.bot.send_message(
                chat_id=effective_chat.id,
                text=text,
                reply_markup=keyboard
            )

    except Exception:

        pass


async def global_error_handler(update, context):

    error = getattr(context, "error", None)
    error_context = get_update_error_context(update)
    error_type = error.__class__.__name__ if error else "UnknownError"
    error_message = sanitize_error_text(error)
    severity = "critical"


    log_event(
        "telegram_handler_error",
        category="telegram",
        severity=severity,
        scope="global",
        actor_user_id=error_context.get("user_id"),
        target_user_id=error_context.get("user_id"),
        message=f"{error_type}: {error_message}",
        metadata={
            "update_type": error_context.get("update_type"),
            "user_id": error_context.get("user_id"),
            "chat_id": error_context.get("chat_id"),
            "callback_data": error_context.get("callback_data"),
            "error_type": error_type
        }
    )


    if severity == "critical":

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "🚨 Error controlado en handler de Telegram\n"
                    f"Tipo: {error_type}\n"
                    f"Usuario: {error_context.get('user_id')}\n"
                    f"Chat: {error_context.get('chat_id')}\n"
                    f"Callback: {error_context.get('callback_data')}"
                )
            )

        except Exception:

            pass


    await notify_user_about_handler_error(update, context)


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
# SCHEDULER EXPIRACIONES COMERCIALES
# =========================

async def commercial_expiry_job(context: ContextTypes.DEFAULT_TYPE):

    try:

        summary = await callback_router_module.process_expired_commercial_retention(
            context
        )

        active_count = sum(
            int(summary.get(key, 0) or 0)
            for key in (
                "newly_expired",
                "expiry_notices_sent",
                "reminders_due",
                "reminders_sent",
                "finalized",
                "admin_notices_sent",
                "send_errors"
            )
        )

        if active_count > 0:

            print(
                "Commercial expiry scheduler:",
                summary
            )

            log_event(
                "commercial_expiry_scheduler_activity",
                category="commercial",
                severity=(
                    "warning"
                    if int(summary.get("send_errors", 0) or 0) > 0
                    else "info"
                ),
                message="Revisión comercial periódica con actividad",
                metadata=summary
            )

    except Exception as e:

        print("Commercial expiry scheduler: error en revisión periódica:", e)

        log_event(
            "commercial_expiry_scheduler_error",
            category="commercial",
            severity="warning",
            message="Error en revisión comercial periódica",
            metadata={"error": str(e)}
        )


def schedule_commercial_expiry_job(application):

    job_queue = getattr(application, "job_queue", None)


    if not job_queue:

        print(
            "Commercial expiry scheduler: JobQueue no disponible. "
            "No se programó la revisión automática."
        )

        return False


    job_queue.run_repeating(
        commercial_expiry_job,
        interval=COMMERCIAL_EXPIRY_JOB_INTERVAL_SECONDS,
        first=60,
        name="commercial_expiry_scheduler"
    )

    print(
        "Commercial expiry scheduler programado cada",
        COMMERCIAL_EXPIRY_JOB_INTERVAL_SECONDS,
        "segundos"
    )

    return True


async def location_manual_review_expiry_job(context: ContextTypes.DEFAULT_TYPE):

    try:

        summary = await callback_router_module.process_expired_location_manual_reviews(
            context
        )


        if int(summary.get("expired", 0) or 0) > 0:

            print(
                "Location manual review expiry scheduler:",
                summary
            )

            log_event(
                "location_manual_review_expiry_scheduler_activity",
                category="access",
                severity="info",
                message="Revisión periódica de caducidad de revisiones manuales de ubicación.",
                metadata=summary
            )

    except Exception as e:

        print("Location manual review expiry scheduler: error:", e)

        log_event(
            "location_manual_review_expiry_scheduler_error",
            category="access",
            severity="warning",
            message="Error en revisión periódica de revisiones manuales de ubicación.",
            metadata={"error": str(e)}
        )


def schedule_location_manual_review_expiry_job(application):

    job_queue = getattr(application, "job_queue", None)


    if not job_queue:

        print(
            "Location manual review expiry scheduler: JobQueue no disponible. "
            "No se programó la revisión automática."
        )

        return False


    job_queue.run_repeating(
        location_manual_review_expiry_job,
        interval=LOCATION_MANUAL_REVIEW_EXPIRY_JOB_INTERVAL_SECONDS,
        first=120,
        name="location_manual_review_expiry_scheduler"
    )

    print(
        "Location manual review expiry scheduler programado cada",
        LOCATION_MANUAL_REVIEW_EXPIRY_JOB_INTERVAL_SECONDS,
        "segundos"
    )

    return True


async def ad_promo_scheduler_job(context: ContextTypes.DEFAULT_TYPE):

    try:

        summary = await process_due_ad_promo_campaigns(context)

        if int(summary.get("sent", 0) or 0) > 0 or int(summary.get("failed", 0) or 0) > 0:

            print("Ad promo scheduler:", summary)

            log_event(
                "ad_promo_scheduler_activity",
                category="marketing",
                severity="info",
                message="Scheduler de promoción automática ejecutado.",
                metadata=summary
            )

    except Exception as e:

        print("Ad promo scheduler: error:", e)

        log_event(
            "ad_promo_scheduler_error",
            category="marketing",
            severity="warning",
            message="Error en scheduler de promoción automática.",
            metadata={"error": sanitize_error_text(e)}
        )


async def ad_promo_daily_review_job(context: ContextTypes.DEFAULT_TYPE):

    try:

        summary = await process_ad_promo_daily_reviews(context)

        if int(summary.get("sent", 0) or 0) > 0:

            print("Ad promo daily review:", summary)

    except Exception as e:

        print("Ad promo daily review: error:", e)


def schedule_ad_promo_jobs(application):

    job_queue = getattr(application, "job_queue", None)


    if not job_queue:

        print(
            "Ad promo scheduler: JobQueue no disponible. "
            "No se programó la promoción automática."
        )

        return False


    job_queue.run_repeating(
        ad_promo_scheduler_job,
        interval=max(AD_PROMO_SCHEDULER_INTERVAL_SECONDS, 60),
        first=180,
        name="ad_promo_scheduler"
    )

    job_queue.run_repeating(
        ad_promo_daily_review_job,
        interval=max(AD_PROMO_DAILY_REVIEW_INTERVAL_SECONDS, 60 * 30),
        first=300,
        name="ad_promo_daily_review"
    )

    print("Ad promo scheduler programado.")

    return True


async def owner_backup_scheduler_job(context: ContextTypes.DEFAULT_TYPE):

    try:

        summary = await process_due_owner_backups(context)

        if int(summary.get("created", 0) or 0) > 0 or int(summary.get("failed", 0) or 0) > 0:

            print("Owner backup scheduler:", summary)

            log_event(
                "owner_backup_scheduler_activity",
                category="backup",
                severity="info",
                message="Scheduler de backups automáticos ejecutado.",
                metadata=summary
            )

    except Exception as e:

        print("Owner backup scheduler: error:", e)

        log_event(
            "owner_backup_scheduler_error",
            category="backup",
            severity="warning",
            message="Error en scheduler de backups automáticos.",
            metadata={"error": str(e)[:300]}
        )


def schedule_owner_backup_jobs(application):

    job_queue = getattr(application, "job_queue", None)


    if not job_queue:

        print(
            "Owner backup scheduler: JobQueue no disponible. "
            "No se programaron backups automáticos."
        )

        return False


    job_queue.run_repeating(
        owner_backup_scheduler_job,
        interval=max(OWNER_BACKUP_SCHEDULER_INTERVAL_SECONDS, 60 * 15),
        first=420,
        name="owner_backup_scheduler"
    )

    print("Owner backup scheduler programado.")

    return True


async def beta_monitor_summary_job(context: ContextTypes.DEFAULT_TYPE):

    if not is_beta_monitor_enabled():

        return


    try:

        summary_text = summarize_beta_monitor_events(hours=6)

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=summary_text
        )

    except Exception as e:

        print("Beta monitor: error enviando resumen:", e)


def schedule_beta_monitor_job(application):

    if not is_beta_monitor_enabled():

        print("Beta monitor desactivado por configuración.")

        return False


    job_queue = getattr(application, "job_queue", None)


    if not job_queue:

        print(
            "Beta monitor: JobQueue no disponible. "
            "No se programó el resumen automático."
        )

        return False


    job_queue.run_repeating(
        beta_monitor_summary_job,
        interval=max(BETA_MONITOR_SUMMARY_INTERVAL_SECONDS, 60 * 60),
        first=5 * 60,
        name="closed_beta_monitor_summary"
    )

    print("Beta monitor programado.")

    return True


async def beta_cycle_reminder_job(context: ContextTypes.DEFAULT_TYPE):

    if not is_beta_monitor_enabled():

        return


    try:

        completed_cycles = complete_expired_beta_cycles()

        for cycle in completed_cycles:

            log_event(
                "beta_cycle_completed",
                category="beta",
                severity="warning",
                message="Ciclo beta finalizado automáticamente",
                actor_user_id=ADMIN_ID,
                metadata={
                    "cycle_id": cycle[0],
                    "phase": cycle[3],
                    "ends_at": str(cycle[5])
                }
            )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⏰ Ha terminado la beta cerrada.\n\n"
                    "Revisa resultados, prepara beta 2.0 o lanzamiento final."
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📊 Ver monitor beta",
                        callback_data="admin_beta_monitor"
                    )],
                    [InlineKeyboardButton(
                        "🔁 Iniciar beta 2.0",
                        callback_data="admin_beta_cycle_start_beta_2"
                    )],
                    [InlineKeyboardButton(
                        "🚀 Preparar lanzamiento final",
                        callback_data="admin_beta_cycle_final_review"
                    )]
                ])
            )

    except Exception as e:

        print("Beta cycle: error revisando ciclos:", e)


def schedule_beta_cycle_job(application):

    if not is_beta_monitor_enabled():

        print("Beta cycle: monitor desactivado por configuración.")

        return False


    job_queue = getattr(application, "job_queue", None)


    if not job_queue:

        print(
            "Beta cycle: JobQueue no disponible. "
            "No se programó la revisión automática."
        )

        return False


    job_queue.run_repeating(
        beta_cycle_reminder_job,
        interval=max(BETA_MONITOR_SUMMARY_INTERVAL_SECONDS, 60 * 60),
        first=10 * 60,
        name="closed_beta_cycle_reminders"
    )

    print("Beta cycle reminders programados.")

    return True


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
    



async def handle_media(update, context):

    if update.effective_chat and update.effective_chat.type != "private":
        await capture_ad_promo_video(update, context)
        await capture_group_preview_video(update, context)
        await handle_group_backup_media(update, context)
        return

    if context.user_data.get("ad_promo_wizard"):
        await receive_ad_promo_admin_text(update, context)
        return

    if context.user_data.get("marketplace_preview_media"):
        await receive_marketplace_preview_media(update, context)
        return

    if context.user_data.get("editing_preview"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("support_mode"):
        await receive_support_message(update, context)
        return

    return


async def track_command_event(update, context):

    command_text = None

    if update.message and update.message.text:

        command_text = update.message.text.split()[0]


    log_user_event(
        update,
        "command",
        event_key=command_text
    )


async def handle_text(update, context):

    if (
        context.user_data.get("ad_promo_wizard")
        or context.user_data.get("ad_promo_edit")
    ):
        await receive_ad_promo_admin_text(update, context)
        return

    if context.user_data.get("location_review_step"):
        await receive_location_manual_review_form(update, context)
        return

    if (
        context.user_data.get("group_user_promo_waiting")
        and update.message
        and update.message.text
    ):
        await receive_group_user_promo_code(update, context)
        return

    if context.user_data.get("location_gate_pending"):
        await receive_location_gate(update, context)
        return

    if context.user_data.get("creator_setup"):
        await receive_creator_setup(update, context)
        return

    if context.user_data.get("commercial_form"):
        await receive_commercial_form(update, context)
        return

    if context.user_data.get("editing_preview"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("publicity_authorize_existing_group_id"):
        await receive_admin_inputs(update, context)
        return

    if (
        context.user_data.get("configuring_owner_payment_provider")
        or context.user_data.get("configuring_platform_payment_provider")
    ):
        await receive_owner_payment_provider_text(update, context)
        return

    if context.user_data.get("editing_plan"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("adding_plan"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("adding_group_admin"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("group_user_promo_waiting"):
        await receive_group_user_promo_code(update, context)
        return

    if (
        context.user_data.get("admin_user_tracking_search")
    ):
        await receive_user_tracking_search_text(update, context)
        return

    if (
        context.user_data.get("customer_satisfaction_response_id")
        or context.user_data.get("customer_satisfaction_admin_add_question")
        or context.user_data.get("customer_satisfaction_admin_edit_question_id")
    ):
        await receive_customer_satisfaction_text(update, context)
        return

    if context.user_data.get("waiting_code"):
        await receive_admin_inputs(update, context)
        return

    if context.user_data.get("replying_commercial_request"):
        await receive_commercial_request_chat_message(update, context)
        return

    if (
        context.user_data.get("support_mode")
        or context.user_data.get("support_lookup_mode")
        or context.user_data.get("replying_support_ticket")
    ):
        await receive_support_message(update, context)
        return

    if context.user_data.get("ai_chat_mode"):
        await handle_ai_context_text(update, context)
        return

    await receive_code(update, context)


async def handle_private_ad_promo_forward(update, context):

    if context.user_data.get("ad_promo_wizard"):
        await receive_ad_promo_admin_text(update, context)
        return


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

    telegram_app.add_error_handler(global_error_handler)

    telegram_app.add_handler(
        MessageHandler(filters.COMMAND, track_command_event),
        group=-1
    )

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
            filters.PHOTO | filters.VIDEO,
            handle_media
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST & filters.VIDEO,
            capture_ad_promo_video
        ),
        group=0
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.LOCATION,
            receive_location_gate
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & filters.Regex(r"^/backup_"),
            handle_backup_destination_token_command
        ),
        group=0
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            handle_group_backup_text
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_private_ad_promo_forward
        )
    )

    # =========================
    # DETECTAR BOT AÑADIDO
    # =========================

    telegram_app.add_handler(
        ChatMemberHandler(
            detect_bot_channel_admin_update,
            ChatMemberHandler.MY_CHAT_MEMBER
        ),
        group=0
    )

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

    telegram_app.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            detect_bot_removed
        ),
        group=0
    )

    schedule_commercial_expiry_job(telegram_app)
    schedule_location_manual_review_expiry_job(telegram_app)
    schedule_ad_promo_jobs(telegram_app)
    schedule_owner_backup_jobs(telegram_app)
    schedule_beta_monitor_job(telegram_app)
    schedule_beta_cycle_job(telegram_app)

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
