"""
admin_satisfaction_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_satisfaction_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import (
    log_event,
    record_beta_event,
)
from datetime import datetime
from db import conn
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from ui_menu_helpers import send_clean_message
from user_activity_logger import log_user_event_by_ids


# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_customer_satisfaction_delivery_status_text(*args, **kwargs):
    from callback_router import build_customer_satisfaction_delivery_status_text as impl
    return impl(*args, **kwargs)


def build_customer_satisfaction_panel_keyboard(*args, **kwargs):
    from callback_router import build_customer_satisfaction_panel_keyboard as impl
    return impl(*args, **kwargs)


def build_customer_satisfaction_targeting(*args, **kwargs):
    from callback_router import build_customer_satisfaction_targeting as impl
    return impl(*args, **kwargs)


def create_customer_satisfaction_survey(*args, **kwargs):
    from callback_router import create_customer_satisfaction_survey as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_customer_satisfaction_survey(*args, **kwargs):
    from callback_router import fetch_customer_satisfaction_survey as impl
    return impl(*args, **kwargs)


def get_customer_satisfaction_audience_label(*args, **kwargs):
    from callback_router import get_customer_satisfaction_audience_label as impl
    return impl(*args, **kwargs)


def mark_customer_satisfaction_delivery_failed(*args, **kwargs):
    from callback_router import mark_customer_satisfaction_delivery_failed as impl
    return impl(*args, **kwargs)


def mark_customer_satisfaction_delivery_skipped(*args, **kwargs):
    from callback_router import mark_customer_satisfaction_delivery_skipped as impl
    return impl(*args, **kwargs)


def mark_customer_satisfaction_survey_sending(*args, **kwargs):
    from callback_router import mark_customer_satisfaction_survey_sending as impl
    return impl(*args, **kwargs)


def reserve_customer_satisfaction_delivery(*args, **kwargs):
    from callback_router import reserve_customer_satisfaction_delivery as impl
    return impl(*args, **kwargs)


def update_customer_satisfaction_sent_counts(*args, **kwargs):
    from callback_router import update_customer_satisfaction_sent_counts as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def fetch_customer_satisfaction_questions(active_only=True):

    with conn.cursor() as cur:

        if active_only:

            cur.execute("""

                SELECT id, question_key, question_text, category, answer_type, sort_order
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL
                AND COALESCE(is_active, TRUE)=TRUE
                ORDER BY sort_order ASC, id ASC

            """)

        else:

            cur.execute("""

                SELECT id, question_key, question_text, category, answer_type, sort_order, is_active
                FROM customer_satisfaction_questions
                WHERE survey_id IS NULL
                ORDER BY sort_order ASC, id ASC

            """)

        return cur.fetchall()


def build_customer_satisfaction_results_text():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*), COALESCE(SUM(sent_count), 0), COALESCE(SUM(failed_count), 0)
            FROM customer_satisfaction_surveys

        """)
        survey_count, sent_count, failed_count = cur.fetchone()

        cur.execute("""

            SELECT COUNT(*)
            FROM customer_satisfaction_responses
            WHERE completed_at IS NOT NULL

        """)
        completed_count = cur.fetchone()[0]

        cur.execute("""

            SELECT AVG(rating)
            FROM customer_satisfaction_answers
            WHERE rating IS NOT NULL

        """)
        average_rating = cur.fetchone()[0]

        cur.execute("""

            SELECT q.category, AVG(a.rating)
            FROM customer_satisfaction_answers a
            JOIN customer_satisfaction_questions q
            ON q.id=a.question_id
            WHERE a.rating IS NOT NULL
            GROUP BY q.category
            ORDER BY AVG(a.rating) ASC
            LIMIT 8

        """)
        category_rows = cur.fetchall()

        cur.execute("""

            SELECT q.question_text, a.text_answer
            FROM customer_satisfaction_answers a
            JOIN customer_satisfaction_questions q
            ON q.id=a.question_id
            WHERE a.text_answer IS NOT NULL
            AND LENGTH(TRIM(a.text_answer)) > 0
            ORDER BY a.created_at DESC
            LIMIT 5

        """)
        text_rows = cur.fetchall()

    response_rate = 0
    if sent_count:
        response_rate = round((completed_count / sent_count) * 100, 1)

    category_text = "\n".join(
        f"- {category}: {round(float(avg), 2)}/5"
        for category, avg in category_rows
    ) or "Sin puntuaciones todavía."

    latest_text = "\n".join(
        f"- {question}: {answer[:120]}"
        for question, answer in text_rows
    ) or "Sin respuestas de texto todavía."

    average_text = f"{round(float(average_rating), 2)}/5" if average_rating else "Sin datos"

    return (
        "📊 Resultados de satisfacción\n\n"
        f"Encuestas creadas: {survey_count}\n"
        f"Total enviados: {sent_count}\n"
        f"Fallidos: {failed_count}\n"
        f"Total respuestas: {completed_count}\n"
        f"Tasa respuesta: {response_rate}%\n"
        f"Media general: {average_text}\n\n"
        "Media por categoría:\n"
        f"{category_text}\n\n"
        "Últimas respuestas texto:\n"
        f"{latest_text}"
    )


def build_customer_satisfaction_questions_text():

    rows = fetch_customer_satisfaction_questions(active_only=False)

    if not rows:
        return "📝 Gestionar preguntas\n\nNo hay preguntas configuradas."

    lines = ["📝 Gestionar preguntas"]

    for row in rows:
        question_id, _key, text, category, answer_type, sort_order, is_active = row
        status = "activa" if is_active else "desactivada"
        lines.append(
            f"\n{sort_order or question_id}. {text}\n"
            f"Tipo: {answer_type} · Categoría: {category} · Estado: {status}"
        )

    return "\n".join(lines)


def build_customer_satisfaction_deactivate_keyboard():

    rows = fetch_customer_satisfaction_questions(active_only=True)
    keyboard = []

    for question_id, _key, text, _category, _answer_type, _sort_order in rows[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"🚫 {text[:35]}",
                callback_data=f"admin_satisfaction_deactivate_{question_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_customer_satisfaction")])

    return InlineKeyboardMarkup(keyboard)


def build_customer_satisfaction_edit_keyboard():

    rows = fetch_customer_satisfaction_questions(active_only=False)
    keyboard = []

    for question_id, _key, text, _category, _answer_type, _sort_order, _is_active in rows[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"✏️ {text[:35]}",
                callback_data=f"admin_satisfaction_edit_{question_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="admin_customer_satisfaction")])

    return InlineKeyboardMarkup(keyboard)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_satisfaction_callbacks(update, context, query, user_id, data):

    if data in (
        "admin_satisfaction_send_pending",
        "admin_satisfaction_resend_incomplete",
        "admin_satisfaction_send_never_sent",
        "admin_satisfaction_force_new_cycle"
    ):

        mode_by_callback = {
            "admin_satisfaction_send_pending": "pending",
            "admin_satisfaction_resend_incomplete": "resend_incomplete",
            "admin_satisfaction_send_never_sent": "never_sent",
            "admin_satisfaction_force_new_cycle": "pending"
        }
        mode = mode_by_callback[data]
        campaign_id = "default"

        if data == "admin_satisfaction_force_new_cycle":
            campaign_id = f"cycle_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        survey_id = create_customer_satisfaction_survey(
            user_id,
            "global",
            send_mode=mode,
            campaign_id=campaign_id
        )
        targeting = build_customer_satisfaction_targeting(
            "global",
            mode,
            campaign_id=campaign_id
        )

        mode_text = {
            "pending": "Enviar a pendientes",
            "resend_incomplete": "Reenviar a no completados",
            "never_sent": "Enviar solo a nunca enviados"
        }.get(mode, mode)

        await send_clean_message(
            context,
            query.message.chat_id,
            "📤 Confirmar envío de encuesta\n\n"
            f"Modo: {mode_text}\n"
            f"Audiencia: {get_customer_satisfaction_audience_label('global')}\n"
            f"Campaña: {campaign_id}\n\n"
            f"Se enviará la encuesta a {targeting['target_count']} usuarios.\n"
            f"Se omitirán {targeting['skipped_completed']} usuarios que ya la completaron.\n"
            f"Se omitirán {targeting['skipped_already_sent']} usuarios que ya la recibieron en este ciclo.\n\n"
            "Para que sea justo, el bot nunca reenvía por defecto a usuarios que ya respondieron.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar envío", callback_data=f"admin_satisfaction_confirm_{survey_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="admin_customer_satisfaction")]
            ])
        )

        return


    if data.startswith("admin_satisfaction_send_"):

        audience_slug = data.replace("admin_satisfaction_send_", "", 1)
        audience = {
            "global": "global",
            "users": "users",
            "owners": "owners",
            "group_admins": "group_admins"
        }.get(audience_slug)

        if not audience:
            await query.message.reply_text(
                "❌ Audiencia no válida.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        survey_id = create_customer_satisfaction_survey(
            user_id,
            audience,
            send_mode="pending",
            campaign_id="default"
        )
        targeting = build_customer_satisfaction_targeting(
            audience,
            "pending",
            campaign_id="default"
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "📤 Confirmar envío de encuesta\n\n"
            f"Audiencia: {get_customer_satisfaction_audience_label(audience)}\n"
            f"Usuarios elegibles: {targeting['total']}\n\n"
            f"Se enviará la encuesta a {targeting['target_count']} usuarios.\n"
            f"Se omitirán {targeting['skipped_completed']} usuarios que ya la completaron.\n"
            f"Se omitirán {targeting['skipped_already_sent']} usuarios que ya la recibieron en este ciclo.\n\n"
            "¿Confirmas?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar envío", callback_data=f"admin_satisfaction_confirm_{survey_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="admin_customer_satisfaction")]
            ])
        )

        return


    if data == "admin_satisfaction_delivery_status":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_delivery_status_text("global"),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_confirm_"):

        survey_id = extract_commercial_request_id(
            data,
            "admin_satisfaction_confirm_"
        )

        if survey_id is None:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        survey = fetch_customer_satisfaction_survey(survey_id)

        if not survey:
            await query.message.reply_text(
                "❌ Encuesta no encontrada.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        if survey["status"] != "draft":
            await query.message.reply_text(
                "⚠️ Esta encuesta ya fue enviada o está en proceso. No se duplicará.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        if not mark_customer_satisfaction_survey_sending(survey_id):
            await query.message.reply_text(
                "⚠️ Esta encuesta ya se está enviando o ya fue enviada. No se duplicará.",
                reply_markup=build_customer_satisfaction_panel_keyboard()
            )
            return

        targeting = build_customer_satisfaction_targeting(
            survey["audience"],
            survey["send_mode"],
            group_id=survey["group_id"],
            campaign_id=survey["campaign_id"]
        )
        sent_count = 0
        failed_count = 0

        for skipped_user_id in targeting["completed_users"]:
            mark_customer_satisfaction_delivery_skipped(
                survey_id,
                skipped_user_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                "skipped_completed"
            )

        already_sent_users = set(targeting["sent_current_cycle"]) - set(targeting["targets"])
        already_sent_users -= set(targeting["completed_users"])

        for skipped_user_id in sorted(already_sent_users):
            mark_customer_satisfaction_delivery_skipped(
                survey_id,
                skipped_user_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                "skipped_already_sent"
            )

        for recipient_id in targeting["targets"]:
            reserved = reserve_customer_satisfaction_delivery(
                survey_id,
                recipient_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                allow_existing=survey["send_mode"] == "resend_incomplete"
            )

            if not reserved:
                continue

            try:
                await context.bot.send_message(
                    chat_id=recipient_id,
                    text=(
                        "Queremos mejorar el bot. Responde esta encuesta rápida de 1 a 5.\n\n"
                        "Tus respuestas ayudan a mejorar menús, acceso, pagos, soporte y seguridad."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📝 Responder encuesta", callback_data=f"satisfaction_start_{survey_id}")]
                    ])
                )
                sent_count += 1
                log_user_event_by_ids(
                    recipient_id,
                    "survey_sent",
                    event_key="customer_satisfaction",
                    group_id=survey["group_id"],
                    metadata={
                        "survey_id": survey_id,
                        "campaign_id": survey["campaign_id"],
                        "send_mode": survey["send_mode"]
                    }
                )
            except Exception as e:
                failed_count += 1
                mark_customer_satisfaction_delivery_failed(
                    survey_id,
                    recipient_id,
                    survey["group_id"],
                    survey["campaign_id"],
                    e
                )
                log_event(
                    "survey_send_failed",
                    category="satisfaction",
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=recipient_id,
                    group_id=survey["group_id"],
                    message="No se pudo entregar una encuesta de satisfacción.",
                    metadata={
                        "survey_id": survey_id,
                        "audience": survey["audience"],
                        "error": str(e)[:200]
                    }
                )

        update_customer_satisfaction_sent_counts(
            survey_id,
            sent_count,
            failed_count,
            targeting["skipped_completed"],
            targeting["skipped_already_sent"]
        )

        log_event(
            "survey_sent",
            category="satisfaction",
            severity="info",
            actor_user_id=user_id,
            group_id=survey["group_id"],
            message="Encuesta de satisfacción enviada.",
            metadata={
                "survey_id": survey_id,
                "audience": survey["audience"],
                "campaign_id": survey["campaign_id"],
                "send_mode": survey["send_mode"],
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_completed": targeting["skipped_completed"],
                "skipped_already_sent": targeting["skipped_already_sent"]
            }
        )
        record_beta_event(
            "survey_sent",
            severity="info",
            user_id=user_id,
            group_id=survey["group_id"],
            message="Encuesta de satisfacción enviada.",
            metadata={
                "survey_id": survey_id,
                "audience": survey["audience"],
                "campaign_id": survey["campaign_id"],
                "send_mode": survey["send_mode"],
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_completed": targeting["skipped_completed"],
                "skipped_already_sent": targeting["skipped_already_sent"]
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Encuesta enviada\n\n"
            f"Enviados: {sent_count}\n"
            f"Fallidos: {failed_count}\n"
            f"Omitidos por completada: {targeting['skipped_completed']}\n"
            f"Omitidos por ya enviada: {targeting['skipped_already_sent']}",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_results":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_results_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_questions":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_questions_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_deactivate_menu":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🚫 Desactivar pregunta\n\nElige una pregunta activa para ocultarla en próximas encuestas.",
            reply_markup=build_customer_satisfaction_deactivate_keyboard()
        )

        return


    if data == "admin_satisfaction_edit_menu":

        await send_clean_message(
            context,
            query.message.chat_id,
            "✏️ Editar preguntas\n\nElige la pregunta cuyo texto quieres actualizar.",
            reply_markup=build_customer_satisfaction_edit_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_edit_"):

        question_id = extract_commercial_request_id(
            data,
            "admin_satisfaction_edit_"
        )

        if question_id is None:
            await query.message.reply_text("❌ Pregunta no válida.")
            return

        context.user_data["customer_satisfaction_admin_edit_question_id"] = question_id

        await query.message.reply_text(
            "✏️ Editar pregunta\n\nEscribe el nuevo texto de la pregunta.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("admin_satisfaction_deactivate_"):

        question_id = extract_commercial_request_id(
            data,
            "admin_satisfaction_deactivate_"
        )

        if question_id is None:
            await query.message.reply_text("❌ Pregunta no válida.")
            return

        with conn.cursor() as cur:
            cur.execute("""

                UPDATE customer_satisfaction_questions
                SET is_active=FALSE
                WHERE id=%s

            """, (question_id,))

        await query.message.reply_text(
            "✅ Pregunta desactivada.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_add_rating":

        context.user_data["customer_satisfaction_admin_add_question"] = "rating_1_5"
        await query.message.reply_text(
            "➕ Añadir pregunta\n\nEscribe el texto de la pregunta. Se guardará como valoración 1-5.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_add_text":

        context.user_data["customer_satisfaction_admin_add_question"] = "text"
        await query.message.reply_text(
            "➕ Añadir pregunta texto\n\nEscribe el texto de la pregunta. El usuario responderá con texto libre.",
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return


    if data == "admin_satisfaction_latest":

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_results_text(),
            reply_markup=build_customer_satisfaction_panel_keyboard()
        )

        return

    return NOT_HANDLED
