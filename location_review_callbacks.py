"""
location_review_callbacks: tramo extraído de callback_router.py.

Prefijos: location_review_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import log_event
from db import conn
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from user_activity_logger import log_user_event


# =========================
# CONSTANTES DE ESTE TRAMO
# =========================
# Viven aquí y las importa callback_router, no al revés: un envoltorio
# diferido no sirve para una constante, devolvería una función.

LOCATION_MANUAL_REVIEW_FIELDS = [
    "id",
    "user_id",
    "group_id",
    "telegram_group_id",
    "support_ticket_id",
    "requested_by_user_id",
    "approved_by_user_id",
    "status",
    "failed_latitude",
    "failed_longitude",
    "allowed_region",
    "allowed_region_type",
    "question_1_reason",
    "question_2_residence_proof",
    "question_3_valid_location_eta",
    "owner_note",
    "user_note",
    "expires_at",
    "completed_at",
    "created_at",
    "updated_at"
]



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_location_manual_review_admin_keyboard(*args, **kwargs):
    from callback_router import build_location_manual_review_admin_keyboard as impl
    return impl(*args, **kwargs)


def build_location_manual_review_metadata(*args, **kwargs):
    from callback_router import build_location_manual_review_metadata as impl
    return impl(*args, **kwargs)


def build_unknown_callback_keyboard(*args, **kwargs):
    from callback_router import build_unknown_callback_keyboard as impl
    return impl(*args, **kwargs)


def create_support_message(*args, **kwargs):
    from callback_router import create_support_message as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_group_location_review_details(*args, **kwargs):
    from callback_router import fetch_group_location_review_details as impl
    return impl(*args, **kwargs)


def fetch_location_manual_review(*args, **kwargs):
    from callback_router import fetch_location_manual_review as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)


def request_location_verification(*args, **kwargs):
    from callback_router import request_location_verification as impl
    return impl(*args, **kwargs)


def row_to_location_manual_review(*args, **kwargs):
    from callback_router import row_to_location_manual_review as impl
    return impl(*args, **kwargs)


def update_support_ticket_status(*args, **kwargs):
    from callback_router import update_support_ticket_status as impl
    return impl(*args, **kwargs)


def user_can_manage_location_manual_review(*args, **kwargs):
    from callback_router import user_can_manage_location_manual_review as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def approve_location_manual_review_temp(review_id, approver_user_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE location_manual_reviews
            SET status='approved_temp',
                approved_by_user_id=%s,
                expires_at=NOW() + INTERVAL '7 days',
                updated_at=NOW()
            WHERE id=%s
            AND status='pending'
            RETURNING {", ".join(LOCATION_MANUAL_REVIEW_FIELDS)}

        """, (
            approver_user_id,
            review_id
        ))

        row = cur.fetchone()


    return row_to_location_manual_review(row)


def reject_location_manual_review(review_id, rejected_by_user_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE location_manual_reviews
            SET status='rejected',
                approved_by_user_id=%s,
                updated_at=NOW()
            WHERE id=%s
            AND status='pending'
            RETURNING {", ".join(LOCATION_MANUAL_REVIEW_FIELDS)}

        """, (
            rejected_by_user_id,
            review_id
        ))

        row = cur.fetchone()


    return row_to_location_manual_review(row)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_location_review_callbacks(update, context, query, user_id, data):

    if data.startswith("location_review_request_"):

        group_id = extract_commercial_request_id(
            data,
            "location_review_request_"
        )
        group_details = fetch_group_location_review_details(group_id)


        if not group_details:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        context.user_data["location_review_group_id"] = group_id
        context.user_data["location_review_step"] = "reason"
        context.user_data["location_review_answers"] = {}

        log_user_event(
            update,
            "location_manual_review_form_started",
            event_key="location_review_request",
            group_id=group_id,
            metadata={
                "group_id": group_id,
                "allowed_region": group_details.get("allowed_region"),
                "allowed_region_type": group_details.get("allowed_region_type")
            }
        )

        log_event(
            "location_manual_review_form_started",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Usuario inició formulario de revisión manual de ubicación.",
            metadata={
                "group_id": group_id,
                "allowed_region": group_details.get("allowed_region"),
                "allowed_region_type": group_details.get("allowed_region_type")
            }
        )

        await query.message.reply_text(
            "1/3 ¿Por qué solicitas una revisión manual de ubicación?\n\n"
            "Puedes explicar, por ejemplo, si estás temporalmente fuera por trabajo o estudios, "
            "si la ubicación del móvil no se detectó correctamente, o si resides en la zona permitida "
            "pero ahora estás fuera."
        )

        return


    if data.startswith("location_review_send_location_"):

        group_id = extract_commercial_request_id(
            data,
            "location_review_send_location_"
        )

        if not group_id:

            await query.message.reply_text(
                "⚠️ Comunidad no válida.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        await request_location_verification(
            context,
            query.message.chat_id,
            group_id,
            context.user_data.get("location_review_action") or "location_only",
            price_id=context.user_data.get("location_review_price_id"),
            telegram_user=query.from_user,
            allow_manual_review_bypass=False
        )

        return


    if data.startswith("location_review_approve7_"):

        review_id = extract_commercial_request_id(
            data,
            "location_review_approve7_"
        )
        review = fetch_location_manual_review(review_id)


        if not review:

            await query.message.reply_text(
                "❌ Revisión no encontrada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        if not user_can_manage_location_manual_review(user_id, review.get("group_id")):

            await query.message.reply_text(
                "⛔ No tienes permiso para aprobar esta revisión."
            )

            return


        approved_review = approve_location_manual_review_temp(
            review_id,
            user_id
        )


        if not approved_review:

            await query.message.reply_text(
                "⚠️ Esta revisión ya no está pendiente.",
                reply_markup=build_location_manual_review_admin_keyboard(review)
            )

            return


        expires_text = format_commercial_datetime(
            approved_review.get("expires_at")
        )
        ticket_id = approved_review.get("support_ticket_id")


        if ticket_id:

            create_support_message(
                ticket_id,
                "admin",
                user_id,
                "📍 Revisión temporal de ubicación aprobada."
            )
            update_support_ticket_status(
                ticket_id,
                "answered"
            )


        log_event(
            "location_manual_review_approved_temp",
            category="access",
            severity="info",
            scope="group",
            group_id=approved_review.get("group_id"),
            actor_user_id=user_id,
            target_user_id=approved_review.get("user_id"),
            message="Owner/admin aprobó revisión temporal de ubicación.",
            metadata=build_location_manual_review_metadata(approved_review)
        )

        try:

            await context.bot.send_message(
                chat_id=approved_review.get("user_id"),
                text=(
                    "📍 Revisión temporal aprobada\n\n"
                    f"Tu caso ha sido aprobado temporalmente hasta {expires_text}.\n"
                    "Durante este plazo podrás continuar el acceso a esta comunidad aunque tu ubicación actual no coincida.\n\n"
                    "Esta revisión no es permanente.\n"
                    "Cuando caduque, tendrás que enviar una ubicación válida o solicitar una nueva revisión."
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📍 Enviar ubicación ahora",
                        callback_data=f"location_review_send_location_{approved_review.get('group_id')}"
                    )],
                    [InlineKeyboardButton(
                        "🏠 Inicio",
                        callback_data="public_back_start"
                    )]
                ])
            )

        except Exception as e:

            print("Error notificando aprobación de revisión manual:", e)


        await query.message.reply_text(
            "✅ Revisión temporal aprobada y usuario notificado.",
            reply_markup=build_location_manual_review_admin_keyboard(approved_review)
        )

        return


    if data.startswith("location_review_reject_"):

        review_id = extract_commercial_request_id(
            data,
            "location_review_reject_"
        )
        review = fetch_location_manual_review(review_id)


        if not review:

            await query.message.reply_text(
                "❌ Revisión no encontrada.",
                reply_markup=build_unknown_callback_keyboard()
            )

            return


        if not user_can_manage_location_manual_review(user_id, review.get("group_id")):

            await query.message.reply_text(
                "⛔ No tienes permiso para rechazar esta revisión."
            )

            return


        rejected_review = reject_location_manual_review(
            review_id,
            user_id
        )


        if not rejected_review:

            await query.message.reply_text(
                "⚠️ Esta revisión ya no está pendiente.",
                reply_markup=build_location_manual_review_admin_keyboard(review)
            )

            return


        ticket_id = rejected_review.get("support_ticket_id")


        if ticket_id:

            create_support_message(
                ticket_id,
                "admin",
                user_id,
                "❌ Revisión manual de ubicación rechazada."
            )
            update_support_ticket_status(
                ticket_id,
                "answered"
            )


        log_event(
            "location_manual_review_rejected",
            category="access",
            severity="info",
            scope="group",
            group_id=rejected_review.get("group_id"),
            actor_user_id=user_id,
            target_user_id=rejected_review.get("user_id"),
            message="Owner/admin rechazó revisión manual de ubicación.",
            metadata=build_location_manual_review_metadata(rejected_review)
        )

        user_keyboard = [
            [InlineKeyboardButton(
                "📍 Enviar ubicación de nuevo",
                callback_data=f"location_review_send_location_{rejected_review.get('group_id')}"
            )],
            [InlineKeyboardButton(
                "🏠 Inicio",
                callback_data="public_back_start"
            )]
        ]


        if ticket_id:

            user_keyboard.insert(1, [InlineKeyboardButton(
                "💬 Responder ticket",
                callback_data="user_support_lookup_start"
            )])


        try:

            await context.bot.send_message(
                chat_id=rejected_review.get("user_id"),
                text=(
                    "❌ Revisión manual rechazada\n\n"
                    "No se ha podido aprobar tu caso con la información enviada.\n"
                    "Puedes responder al ticket si necesitas aportar más detalles o enviar una nueva ubicación válida."
                ),
                reply_markup=InlineKeyboardMarkup(user_keyboard)
            )

        except Exception as e:

            print("Error notificando rechazo de revisión manual:", e)


        await query.message.reply_text(
            "❌ Revisión rechazada y usuario notificado.",
            reply_markup=build_location_manual_review_admin_keyboard(rejected_review)
        )

        return

    return NOT_HANDLED
