"""
owner_support_callbacks: tramo extraído de callback_router.py.

Prefijos: owner_support_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from ai_policy import AI_ROLE_OWNER
from ai_response_service import build_ai_feedback_keyboard_rows
from audit_log_service import log_event
from rbac_helpers import is_super_admin
from support_ai_service import build_support_reply_suggestion
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

def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def build_support_ticket_detail_text(*args, **kwargs):
    from callback_router import build_support_ticket_detail_text as impl
    return impl(*args, **kwargs)


def build_support_tickets_text(*args, **kwargs):
    from callback_router import build_support_tickets_text as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_recent_support_tickets(*args, **kwargs):
    from callback_router import fetch_recent_support_tickets as impl
    return impl(*args, **kwargs)


def fetch_support_ticket(*args, **kwargs):
    from callback_router import fetch_support_ticket as impl
    return impl(*args, **kwargs)


def format_support_username(*args, **kwargs):
    from callback_router import format_support_username as impl
    return impl(*args, **kwargs)


def get_selected_group_for_permissions(*args, **kwargs):
    from callback_router import get_selected_group_for_permissions as impl
    return impl(*args, **kwargs)


def should_show_owner_location_reviews_button(*args, **kwargs):
    from callback_router import should_show_owner_location_reviews_button as impl
    return impl(*args, **kwargs)


def update_support_ticket_status(*args, **kwargs):
    from callback_router import update_support_ticket_status as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_owner_support_ticket_keyboard(ticket):

    ticket_id = ticket.get("id") if isinstance(ticket, dict) else ticket
    ticket_status = ticket.get("status") if isinstance(ticket, dict) else None
    keyboard = []


    if ticket_status != "closed":

        keyboard.append([InlineKeyboardButton("✍️ Responder", callback_data=f"owner_support_reply_{ticket_id}")])
        keyboard.append([InlineKeyboardButton("🤖 Sugerir respuesta", callback_data=f"owner_support_ai_{ticket_id}")])
        keyboard.append([InlineKeyboardButton("✅ Cerrar ticket", callback_data=f"owner_support_close_{ticket_id}")])


    keyboard.append([InlineKeyboardButton("⬅️ Volver a soporte de comunidad", callback_data="owner_support_tickets")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return keyboard



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_owner_support_callbacks(update, context, query, user_id, data):

    if data == "owner_support_tickets":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_respond_group_support"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver soporte de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id
        tickets = fetch_recent_support_tickets(group_id=group_id)
        keyboard = []


        if should_show_owner_location_reviews_button(group_id):

            keyboard.append([InlineKeyboardButton(
                "📍 Revisiones de ubicación",
                callback_data=f"owner_location_reviews_{group_id}"
            )])


        for ticket in tickets:

            username = format_support_username(ticket)
            label_name = username if username != "-" else ticket.get("first_name") or ticket.get("user_id")

            keyboard.append([
                InlineKeyboardButton(
                    f"📨 Ticket #{ticket.get('id')} - {label_name}",
                    callback_data=f"owner_support_ticket_{ticket.get('id')}"
                )
            ])


        if is_super_admin(user_id):

            keyboard.append([InlineKeyboardButton("🛟 Abrir bandeja global", callback_data="admin_support_tickets")])


        keyboard.extend([
            [InlineKeyboardButton("⬅️ Volver al apartado soporte", callback_data="owner_panel_support")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            build_support_tickets_text(tickets).replace("🛟 Tickets de soporte", "🛟 Tickets de soporte de esta comunidad"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if data.startswith("owner_support_ai_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_ai_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket or not ticket.get("group_id"):

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_has_group_permission_any(user_id, ticket.get("group_id"), ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para usar IA en este ticket.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        result = build_support_reply_suggestion(
            user_id,
            AI_ROLE_OWNER,
            ticket_id,
            group_id=ticket.get("group_id")
        )
        keyboard = [
            [InlineKeyboardButton("✍️ Usar como base", callback_data=f"owner_support_use_ai_{ticket_id}")],
            [InlineKeyboardButton("⬅️ Volver al ticket", callback_data=f"owner_support_ticket_{ticket_id}")]
        ]


        if result.get("interaction_id"):

            for label, callback_data in build_ai_feedback_keyboard_rows(result.get("interaction_id")):

                keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])


        await query.message.reply_text(
            "🤖 Borrador sugerido para soporte\n\n"
            f"{result.get('answer') or 'No tengo suficiente información para preparar un borrador.'}\n\n"
            "No se enviará automáticamente. Puedes usarlo como base y editarlo antes de responder.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if data.startswith("owner_support_use_ai_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_use_ai_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket or not ticket.get("group_id"):

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_has_group_permission_any(user_id, ticket.get("group_id"), ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para responder este ticket.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = ticket.get("group_id")
        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Usa el borrador anterior como base, edítalo si hace falta y escribe ahora la respuesta final para el usuario.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Cancelar", callback_data=f"owner_support_ticket_{ticket_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("owner_support_ticket_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_ticket_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        ticket_group_id = ticket.get("group_id")


        if not ticket_group_id or not user_has_group_permission_any(user_id, ticket_group_id, ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver este ticket de soporte.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = ticket_group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            build_support_ticket_detail_text(ticket),
            reply_markup=InlineKeyboardMarkup(build_owner_support_ticket_keyboard(ticket))
        )

        return

    if data.startswith("owner_support_reply_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_reply_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket or not ticket.get("group_id"):

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_has_group_permission_any(user_id, ticket.get("group_id"), ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para responder este ticket.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if ticket.get("status") == "closed":

            await query.message.reply_text(
                "📁 Este ticket está cerrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver a soporte de comunidad", callback_data="owner_support_tickets")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        context.user_data["selected_owner_group"] = ticket.get("group_id")
        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Escribe ahora la respuesta para el usuario.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Cancelar", callback_data=f"owner_support_ticket_{ticket_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("owner_support_close_"):

        ticket_id = extract_commercial_request_id(
            data,
            "owner_support_close_"
        )
        ticket = fetch_support_ticket(ticket_id)


        if not ticket or not ticket.get("group_id"):

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not user_has_group_permission_any(user_id, ticket.get("group_id"), ["can_respond_group_support"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cerrar este ticket.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        update_support_ticket_status(ticket_id, "closed")
        context.user_data["selected_owner_group"] = ticket.get("group_id")

        log_event(
            "owner_support_ticket_closed",
            category="support",
            severity="info",
            scope="group",
            group_id=ticket.get("group_id"),
            actor_user_id=user_id,
            target_user_id=ticket.get("user_id"),
            message="Owner cerró un ticket de soporte de comunidad.",
            metadata={"ticket_id": ticket_id}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Ticket cerrado.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a soporte de comunidad", callback_data="owner_support_tickets")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    return NOT_HANDLED
