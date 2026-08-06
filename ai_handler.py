from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from ai_response_service import (
    build_ai_feedback_keyboard_rows,
    build_contextual_ai_answer
)

from help_catalog import (
    HELP_SECTION_CONTENT
)

from ai_role_context import (
    build_ai_user_context_text
)

from commercial_catalog import (
    build_commercial_ai_context
)

from start_handler import start


# =========================
# AI HANDLER — HELPERS
# =========================

def get_effective_text(update: Update):

    message = update.effective_message

    if not message or not message.text:

        return ""

    return message.text


def extract_command_text(update: Update):

    text = get_effective_text(update)

    if not text:

        return ""


    parts = text.split(
        maxsplit=1
    )


    if len(parts) < 2:

        return ""


    return parts[1].strip()


async def reply_ai(update: Update, text):

    message = update.effective_message

    if not message:

        return


    await message.reply_text(text)


# =========================
# AI HANDLER — MEMORIA DE CONVERSACIÓN
# =========================
# Sin memoria, cada mensaje se responde aislado y el asistente no entiende
# preguntas de seguimiento ("¿y el de 30 días?"). Se guarda en la conversación
# del usuario y se limita para no crecer sin control ni encarecer la llamada.

AI_HISTORY_KEY = "ai_history"
AI_HISTORY_MAX_MESSAGES = 6


def get_ai_history(context):

    history = context.user_data.get(AI_HISTORY_KEY)

    if not isinstance(history, list):

        return []


    return history


def remember_ai_exchange(context, question, answer):

    if not question or not answer:

        return


    history = list(
        get_ai_history(context)
    )

    history.append({"role": "user", "content": str(question)[:1500]})
    history.append({"role": "assistant", "content": str(answer)[:1500]})

    context.user_data[AI_HISTORY_KEY] = history[-AI_HISTORY_MAX_MESSAGES:]


def clear_ai_history(context):

    context.user_data.pop(AI_HISTORY_KEY, None)


def build_ai_feedback_markup(interaction_id):

    rows = [
        [InlineKeyboardButton(label, callback_data=callback_data)]
        for label, callback_data in build_ai_feedback_keyboard_rows(interaction_id)
    ]

    return InlineKeyboardMarkup(rows) if rows else None


async def send_ai_answer(update: Update, text, interaction_id=None):

    if not text:

        await reply_ai(
            update,
            "❌ No se recibió respuesta de la IA."
        )

        return


    max_length = 3900


    if len(text) <= max_length:

        message = update.effective_message

        if message:
            await message.reply_text(
                text,
                reply_markup=build_ai_feedback_markup(interaction_id)
            )

        return


    for i in range(0, len(text), max_length):

        await reply_ai(
            update,
            text[i:i + max_length]
        )


def build_ai_manual_context():

    lines = [
        "MANUAL OFICIAL DEL BOT:",
        "",
        "Regla obligatoria:",
        "Solo se pueden mencionar comandos que aparezcan en este manual.",
        "Si un comando no aparece aquí, no debe inventarse.",
        ""
    ]


    for section_key, section_data in HELP_SECTION_CONTENT.items():

        title = section_data.get("title", {}).get("es", section_key)
        body = section_data.get("body", {}).get("es", "")

        lines.append(f"SECCIÓN: {title}")
        lines.append(str(body))
        lines.append("")


    return "\n".join(lines)


def resolve_ai_context_key(help_context):

    mapping = {
        "general": "public_marketplace",
        "plans": "owner_payments",
        "users": "owner_users",
        "payments": "checkout_help",
        "groups": "owner_dashboard",
        "admin": "superadmin_dashboard",
        "access": "subscription_help",
        "commercial": "group_setup",
        "subscriptions": "subscription_help",
        "group_plans": "group_detail",
        "support": "support_ticket",
        "creator_setup": "group_setup",
        "admin_users": "user_tracking",
        "admin_groups": "superadmin_dashboard",
        "admin_payments": "payment_diagnostics",
        "admin_logs": "superadmin_dashboard",
        "buyer": "public_marketplace",
        "owner": "owner_dashboard",
        "superadmin": "superadmin_dashboard"
    }

    return mapping.get(help_context, "public_marketplace")


# =========================
# AI HANDLER — /ia
# =========================

async def ia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_text = extract_command_text(update)


    if not user_text:

        await activate_ai_help_context(
            update,
            context,
            help_context="general"
        )

        return


    await reply_ai(
        update,
        "🤖 Pensando..."
    )


    result = build_contextual_ai_answer(
        user_id=update.effective_user.id,
        question=user_text,
        context_key="public_marketplace"
    )


    await send_ai_answer(
        update,
        result.get("answer"),
        interaction_id=result.get("interaction_id")
    )


# =========================
# AI HANDLER — /asistente
# =========================

async def asistente_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_text = extract_command_text(update)


    if not user_text:

        await activate_ai_help_context(
            update,
            context,
            help_context="general"
        )

        return


    await reply_ai(
        update,
        "🤖 Preparando respuesta..."
    )


    result = build_contextual_ai_answer(
        user_id=update.effective_user.id,
        question=user_text,
        context_key="public_marketplace"
    )


    await send_ai_answer(
        update,
        result.get("answer"),
        interaction_id=result.get("interaction_id")
    )


# =========================
# AI HANDLER — CONTEXT MODE
# =========================

def get_ai_context_label(context):

    value = context.user_data.get("ai_help_context")

    labels = {
        "general": "Ayuda general del bot",
        "plans": "Gestión de planes",
        "users": "Gestión de usuarios",
        "payments": "Pagos y suscripciones",
        "groups": "Gestión de grupos",
        "admin": "Panel de administración",
        "access": "Accesos y links",
        "commercial": "Soluciones comerciales",
        "subscriptions": "Suscripciones",
        "group_plans": "Planes de grupo",
        "support": "Soporte",
        "creator_setup": "Configuración de comunidad y Stripe",
        "admin_users": "Gestión de usuarios",
        "admin_groups": "Gestión de grupos",
        "admin_payments": "Gestión de pagos",
        "admin_logs": "Logs"
    }

    return labels.get(
        value,
        "Ayuda general del bot"
    )


async def activate_ai_help_context(update: Update, context: ContextTypes.DEFAULT_TYPE, help_context="general"):

    previous_context = context.user_data.get("ai_help_context")

    context.user_data["ai_chat_mode"] = True
    context.user_data["ai_help_context"] = help_context


    # Al cambiar de tema se empieza conversación nueva: arrastrar el hilo
    # anterior confundiría al asistente.
    if previous_context != help_context:

        clear_ai_history(context)


    label = get_ai_context_label(context)

    await reply_ai(
        update,
        "🤖 Ayuda IA activada.\n\n"
        f"Contexto: {label}\n\n"
        "Ahora puedes escribirme directamente sin usar /ia.\n"
        "Para salir, escribe /salir."
    )


async def salir_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["ai_chat_mode"] = False
    context.user_data.pop("ai_help_context", None)
    clear_ai_history(context)

    await reply_ai(
        update,
        "Has salido de la ayuda IA."
    )

    await start(update, context)


async def handle_ai_context_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_text = get_effective_text(update).strip()

    if not user_text:

        return


    help_context = context.user_data.get("ai_help_context")

    await reply_ai(
        update,
        "🤖 Pensando..."
    )


    result = build_contextual_ai_answer(
        user_id=update.effective_user.id,
        question=user_text,
        context_key=resolve_ai_context_key(help_context),
        group_id=context.user_data.get("selected_owner_group") or context.user_data.get("selected_group_admin"),
        history=get_ai_history(context)
    )

    answer = result.get("answer")

    # Solo se recuerda cuando el modelo respondió: guardar un mensaje de error
    # ensuciaría la conversación siguiente.
    if result.get("ok"):

        remember_ai_exchange(context, user_text, answer)


    await send_ai_answer(
        update,
        answer,
        interaction_id=result.get("interaction_id")
    )
