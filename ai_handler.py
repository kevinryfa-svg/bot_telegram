from telegram import Update
from telegram.ext import ContextTypes

from ai_service import (
    generate_ai_response,
    build_system_prompt_for_scope
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


async def send_ai_answer(update: Update, text):

    if not text:

        await reply_ai(
            update,
            "❌ No se recibió respuesta de la IA."
        )

        return


    max_length = 3900


    if len(text) <= max_length:

        await reply_ai(
            update,
            text
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


    system_prompt = build_system_prompt_for_scope(
        "default"
    )


    user_context = build_ai_user_context_text(
        update.effective_user.id
    )

    ok, answer = generate_ai_response(
        user_text,
        system_prompt=system_prompt,
        context_text=build_ai_manual_context() + "\n\n" + user_context
    )


    if not ok:

        await reply_ai(
            update,
            answer
        )

        return


    await send_ai_answer(
        update,
        answer
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


    system_prompt = build_system_prompt_for_scope(
        "default"
    )


    user_context = build_ai_user_context_text(
        update.effective_user.id
    )

    ok, answer = generate_ai_response(
        user_text,
        system_prompt=system_prompt,
        context_text=build_ai_manual_context() + "\n\n" + user_context
    )


    if not ok:

        await reply_ai(
            update,
            answer
        )

        return


    await send_ai_answer(
        update,
        answer
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

    context.user_data["ai_chat_mode"] = True
    context.user_data["ai_help_context"] = help_context

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

    await reply_ai(
        update,
        "Has salido de la ayuda IA."
    )

    await start(update, context)


async def handle_ai_context_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_text = get_effective_text(update).strip()

    if not user_text:

        return


    label = get_ai_context_label(context)
    help_context = context.user_data.get("ai_help_context")

    await reply_ai(
        update,
        "🤖 Pensando..."
    )


    system_prompt = build_system_prompt_for_scope(
        "default"
    )


    user_context = build_ai_user_context_text(
        update.effective_user.id
    )

    context_text = (
        build_ai_manual_context()
        + "\n\n"
        + user_context
        + "\n\n"
        + f"CONTEXTO ACTUAL DEL USUARIO: {label}\n"
        + "Responde únicamente dentro de este contexto, el rol real del usuario y el manual oficial."
    )


    if help_context in ("commercial", "creator_setup"):

        context_text += (
            "\n\n"
            + build_commercial_ai_context()
        )


    ok, answer = generate_ai_response(
        user_text,
        system_prompt=system_prompt,
        context_text=context_text
    )


    if not ok:

        await reply_ai(
            update,
            answer
        )

        return


    await send_ai_answer(
        update,
        answer
    )
