"""
admin_support_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_support_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from ai_policy import AI_ROLE_SUPERADMIN
from ai_response_service import build_ai_feedback_keyboard_rows
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

def build_support_ticket_detail_text(*args, **kwargs):
    from callback_router import build_support_ticket_detail_text as impl
    return impl(*args, **kwargs)


def build_support_tickets_keyboard(*args, **kwargs):
    from callback_router import build_support_tickets_keyboard as impl
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


def update_support_ticket_status(*args, **kwargs):
    from callback_router import update_support_ticket_status as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_support_ticket_keyboard(ticket):

    if isinstance(ticket, dict):

        ticket_id = ticket.get("id")
        ticket_status = ticket.get("status")

    else:

        ticket_id = ticket
        ticket_status = None


    if ticket_status == "closed":

        return [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="admin_support_tickets"
            )]

        ]


    return [

        [InlineKeyboardButton(
            "✍️ Responder",
            callback_data=f"admin_support_reply_{ticket_id}"
        )],

        [InlineKeyboardButton(
            "🤖 Sugerir respuesta",
            callback_data=f"admin_support_ai_{ticket_id}"
        )],

        [InlineKeyboardButton(
            "✅ Cerrar ticket",
            callback_data=f"admin_support_close_{ticket_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_support_tickets"
        )]

    ]



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_support_callbacks(update, context, query, user_id, data):

    if data == "admin_support_tickets":

        tickets = fetch_recent_support_tickets()

        await send_clean_message(
            context,
            query.message.chat_id,
            build_support_tickets_text(tickets),
            reply_markup=InlineKeyboardMarkup(
                build_support_tickets_keyboard(tickets)
            )
        )

        return

    if data.startswith("admin_support_ai_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_ai_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        result = build_support_reply_suggestion(
            user_id,
            AI_ROLE_SUPERADMIN,
            ticket_id,
            group_id=ticket.get("group_id")
        )
        keyboard = [
            [InlineKeyboardButton("✍️ Usar como base", callback_data=f"admin_support_use_ai_{ticket_id}")],
            [InlineKeyboardButton("⬅️ Volver al ticket", callback_data=f"admin_support_ticket_{ticket_id}")]
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

    if data.startswith("admin_support_use_ai_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_use_ai_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Usa el borrador anterior como base, edítalo si hace falta y escribe ahora la respuesta final para el usuario.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Cancelar", callback_data=f"admin_support_ticket_{ticket_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("admin_support_ticket_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_ticket_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        await query.message.reply_text(
            build_support_ticket_detail_text(ticket),
            reply_markup=InlineKeyboardMarkup(
                build_support_ticket_keyboard(ticket)
            )
        )

        return

    if data.startswith("admin_support_reply_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_reply_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        if ticket.get("status") == "closed":

            await query.message.reply_text(
                "📁 Este ticket está cerrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🛟 Tickets abiertos",
                        callback_data="admin_support_tickets"
                    )]
                ])
            )

            return


        context.user_data["replying_support_ticket"] = ticket_id

        await query.message.reply_text(
            f"✍️ Responder ticket #{ticket_id}\n\n"
            "Escribe ahora la respuesta para el usuario."
        )

        return

    if data.startswith("admin_support_close_"):

        ticket_id = extract_commercial_request_id(
            data,
            "admin_support_close_"
        )

        ticket = fetch_support_ticket(ticket_id)


        if not ticket:

            await query.message.reply_text(
                "❌ Ticket de soporte no encontrado."
            )

            return


        update_support_ticket_status(
            ticket_id,
            "closed"
        )

        try:

            await context.bot.send_message(
                chat_id=ticket.get("user_id"),
                text=f"✅ Tu ticket #{ticket_id} ha sido cerrado."
            )

        except Exception as e:

            print("Error avisando cierre soporte:", e)


        await query.message.reply_text(
            f"✅ Ticket #{ticket_id} cerrado.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🛟 Tickets abiertos",
                    callback_data="admin_support_tickets"
                )]
            ])
        )

        return

    return NOT_HANDLED
