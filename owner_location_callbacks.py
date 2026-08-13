"""
owner_location_callbacks: tramo extraído de callback_router.py.

Prefijos: owner_location_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import log_event
from creator_location_callbacks import (
    LOCATION_REGION_TYPE_COUNTRY,
    LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
    SPANISH_AUTONOMOUS_COMMUNITIES,
    SPANISH_AUTONOMOUS_COMMUNITY_LABELS,
)
from db import conn
from location_review_callbacks import LOCATION_MANUAL_REVIEW_FIELDS
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from ui_menu_helpers import send_clean_message


# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_owner_location_management_keyboard(*args, **kwargs):
    from callback_router import build_owner_location_management_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_location_management_text(*args, **kwargs):
    from callback_router import build_owner_location_management_text as impl
    return impl(*args, **kwargs)


def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
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


def fetch_support_ticket(*args, **kwargs):
    from callback_router import fetch_support_ticket as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)


def format_location_manual_review_detail(*args, **kwargs):
    from callback_router import format_location_manual_review_detail as impl
    return impl(*args, **kwargs)


def format_location_review_reason_preview(*args, **kwargs):
    from callback_router import format_location_review_reason_preview as impl
    return impl(*args, **kwargs)


def row_to_location_manual_review(*args, **kwargs):
    from callback_router import row_to_location_manual_review as impl
    return impl(*args, **kwargs)


def user_can_manage_location_manual_review(*args, **kwargs):
    from callback_router import user_can_manage_location_manual_review as impl
    return impl(*args, **kwargs)


def user_can_view_group_panel(*args, **kwargs):
    from callback_router import user_can_view_group_panel as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def fetch_location_manual_review_status_counts(group_id):

    counts = {
        "pending": 0,
        "approved_temp": 0,
        "completed": 0,
        "rejected": 0,
        "expired": 0
    }

    with conn.cursor() as cur:

        cur.execute("""

            SELECT status,
                   COUNT(*)
            FROM location_manual_reviews
            WHERE group_id=%s
            GROUP BY status

        """, (group_id,))

        rows = cur.fetchall()


    for status, total in rows:

        if status in counts:

            counts[status] = total or 0


    return counts


def fetch_owner_location_manual_reviews(group_id, limit=10):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(LOCATION_MANUAL_REVIEW_FIELDS)}
            FROM location_manual_reviews
            WHERE group_id=%s
            ORDER BY
                CASE status
                    WHEN 'pending' THEN 0
                    WHEN 'approved_temp' THEN 1
                    WHEN 'rejected' THEN 2
                    WHEN 'completed' THEN 3
                    WHEN 'expired' THEN 4
                    ELSE 5
                END,
                updated_at DESC NULLS LAST,
                created_at DESC NULLS LAST
            LIMIT %s

        """, (
            group_id,
            limit
        ))

        rows = cur.fetchall()


    return [
        row_to_location_manual_review(row)
        for row in rows
    ]


def format_location_review_status_label(status):

    labels = {
        "pending": "pendiente",
        "approved_temp": "aprobada temporal",
        "completed": "completada",
        "expired": "caducada",
        "rejected": "rechazada",
        "cancelled": "cancelada"
    }

    return labels.get(status, status or "-")


def build_owner_location_reviews_text(group_id, reviews, counts):

    group_details = fetch_group_location_review_details(group_id) or {}
    group_name = group_details.get("name") or group_id
    lines = [
        "📍 Revisiones manuales de ubicación",
        f"Comunidad: {group_name}",
        "",
        f"Pendientes: {counts.get('pending', 0)}",
        f"Aprobadas temporales: {counts.get('approved_temp', 0)}",
        f"Completadas: {counts.get('completed', 0)}",
        f"Rechazadas: {counts.get('rejected', 0)}",
        f"Caducadas: {counts.get('expired', 0)}"
    ]


    if not reviews:

        lines.extend([
            "",
            "Todavía no hay solicitudes de revisión manual de ubicación para esta comunidad."
        ])

        return "\n".join(lines)


    lines.append("")


    for review in reviews:

        lines.extend([
            f"#{review.get('id')}",
            f"Usuario: {review.get('user_id') or '-'}",
            f"Estado: {format_location_review_status_label(review.get('status'))}",
            f"Creada: {format_commercial_datetime(review.get('created_at'))}",
            f"Caduca: {format_commercial_datetime(review.get('expires_at')) if review.get('expires_at') else '-'}",
            f"Motivo: {format_location_review_reason_preview(review.get('question_1_reason'))}",
            ""
        ])


    return "\n".join(lines)[:3900]


def build_owner_location_reviews_keyboard(group_id, reviews):

    keyboard = []


    for review in reviews:

        keyboard.append([InlineKeyboardButton(
            f"📍 Ver detalle #{review.get('id')}",
            callback_data=f"owner_location_review_detail_{review.get('id')}"
        )])


    keyboard.extend([
        [InlineKeyboardButton("⬅️ Volver al soporte", callback_data="owner_support_tickets")],
        [InlineKeyboardButton("🔙 Volver al panel de comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_owner_location_review_detail_text(review, ticket=None):

    base_text = format_location_manual_review_detail(review, ticket)

    return (
        f"{base_text}\n"
        f"Creada: {format_commercial_datetime(review.get('created_at'))}\n"
        f"Caduca: {format_commercial_datetime(review.get('expires_at')) if review.get('expires_at') else '-'}\n"
        f"Completada: {format_commercial_datetime(review.get('completed_at')) if review.get('completed_at') else '-'}"
    )


def build_owner_location_review_detail_keyboard(review):

    review_id = review.get("id")
    group_id = review.get("group_id")
    ticket_id = review.get("support_ticket_id")
    keyboard = []


    if review.get("status") == "pending":

        keyboard.append([InlineKeyboardButton(
            "✅ Aprobar revisión temporal 7 días",
            callback_data=f"location_review_approve7_{review_id}"
        )])
        keyboard.append([InlineKeyboardButton(
            "❌ Rechazar revisión",
            callback_data=f"location_review_reject_{review_id}"
        )])


    if ticket_id:

        keyboard.append([InlineKeyboardButton(
            "💬 Responder ticket",
            callback_data=f"owner_support_reply_{ticket_id}"
        )])


    keyboard.extend([
        [InlineKeyboardButton("🔙 Volver a revisiones", callback_data=f"owner_location_reviews_{group_id}")],
        [InlineKeyboardButton("🔙 Volver al panel de comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_owner_location_regions_keyboard(group_id):

    keyboard = []


    for slug, label in SPANISH_AUTONOMOUS_COMMUNITIES:

        if slug == "all_spain":

            continue


        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"owner_location_region_set_{group_id}_{slug}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="owner_panel_location_info")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def set_group_location_rule(group_id, enabled=None, region_type=None, allowed_region=None):

    updates = []
    params = []


    if enabled is not None:

        updates.append("location_gate_enabled=%s")
        params.append(enabled)


    if region_type is not None:

        updates.append("allowed_region_type=%s")
        params.append(region_type)


    if allowed_region is not None:

        updates.append("allowed_region=%s")
        params.append(allowed_region)


    if not updates:

        return False


    params.append(group_id)

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE groups
            SET {", ".join(updates)}
            WHERE id=%s

        """, params)

        conn.commit()

    return True



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_owner_location_callbacks(update, context, query, user_id, data):

    if data.startswith("owner_location_reviews_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_location_reviews_"
        )


        if not group_id or not user_can_manage_location_manual_review(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver estas revisiones.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id
        reviews = fetch_owner_location_manual_reviews(group_id)
        counts = fetch_location_manual_review_status_counts(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_location_reviews_text(group_id, reviews, counts),
            reply_markup=build_owner_location_reviews_keyboard(group_id, reviews)
        )

        return

    if data.startswith("owner_location_review_detail_"):

        review_id = extract_commercial_request_id(
            data,
            "owner_location_review_detail_"
        )
        review = fetch_location_manual_review(review_id)


        if not review:

            await query.message.reply_text(
                "❌ Revisión de ubicación no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = review.get("group_id")


        if not user_can_manage_location_manual_review(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver estas revisiones.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id
        ticket = fetch_support_ticket(review.get("support_ticket_id")) if review.get("support_ticket_id") else None

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_location_review_detail_text(review, ticket=ticket),
            reply_markup=build_owner_location_review_detail_keyboard(review)
        )

        return

    if data.startswith("owner_location_regions_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_location_regions_"
        )


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            "📂 Elegir comunidad autónoma\n\nSelecciona la región permitida para esta comunidad.",
            reply_markup=build_owner_location_regions_keyboard(group_id)
        )

        return

    if data.startswith("owner_location_enable_") or data.startswith("owner_location_disable_"):

        enabled = data.startswith("owner_location_enable_")
        prefix = "owner_location_enable_" if enabled else "owner_location_disable_"
        group_id = extract_commercial_request_id(data, prefix)


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        set_group_location_rule(group_id, enabled=enabled)
        context.user_data["selected_owner_group"] = group_id

        log_event(
            "owner_location_gate_updated",
            category="security",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Owner actualizó el estado de restricción por ubicación.",
            metadata={"enabled": enabled}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Restricción por ubicación actualizada.\n\n" + build_owner_location_management_text(group_id),
            reply_markup=build_owner_location_management_keyboard(group_id)
        )

        return

    if data.startswith("owner_location_country_set_"):

        payload = data.replace("owner_location_country_set_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        country_code = parts[1]


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        set_group_location_rule(
            group_id,
            enabled=True,
            region_type=LOCATION_REGION_TYPE_COUNTRY,
            allowed_region=country_code
        )
        context.user_data["selected_owner_group"] = group_id

        log_event(
            "owner_location_gate_updated",
            category="security",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Owner actualizó país permitido por ubicación.",
            metadata={"allowed_region": country_code, "region_type": LOCATION_REGION_TYPE_COUNTRY}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n" + build_owner_location_management_text(group_id),
            reply_markup=build_owner_location_management_keyboard(group_id)
        )

        return

    if data.startswith("owner_location_region_set_"):

        payload = data.replace("owner_location_region_set_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        region_slug = parts[1]


        if region_slug not in SPANISH_AUTONOMOUS_COMMUNITY_LABELS:

            await query.message.reply_text(
                "⚠️ Región no válida.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        set_group_location_rule(
            group_id,
            enabled=True,
            region_type=LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
            allowed_region=region_slug
        )
        context.user_data["selected_owner_group"] = group_id

        log_event(
            "owner_location_gate_updated",
            category="security",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Owner actualizó comunidad autónoma permitida por ubicación.",
            metadata={"allowed_region": region_slug, "region_type": LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n" + build_owner_location_management_text(group_id),
            reply_markup=build_owner_location_management_keyboard(group_id)
        )

        return

    return NOT_HANDLED
