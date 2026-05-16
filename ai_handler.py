from telegram import Update
from telegram.ext import ContextTypes

from ai_service import (
    generate_ai_response,
    build_system_prompt_for_scope
)

from help_catalog import (
    HELP_SECTION_CONTENT
)


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

        await reply_ai(
            update,
            "🤖 Uso de IA:\n\n"
            "/ia escribe aquí tu pregunta\n\n"
            "Ejemplo:\n"
            "/ia redacta un mensaje profesional para avisar de una renovación"
        )

        return


    await reply_ai(
        update,
        "🤖 Pensando..."
    )


    system_prompt = build_system_prompt_for_scope(
        "default"
    )


    ok, answer = generate_ai_response(
        user_text,
        system_prompt=system_prompt,
        context_text=build_ai_manual_context()
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

        await reply_ai(
            update,
            "🤖 Asistente IA:\n\n"
            "/asistente escribe aquí lo que necesitas\n\n"
            "Ejemplo:\n"
            "/asistente ayúdame a responder a un usuario que no puede entrar al grupo"
        )

        return


    await reply_ai(
        update,
        "🤖 Preparando respuesta..."
    )


    system_prompt = build_system_prompt_for_scope(
        "default"
    )


    ok, answer = generate_ai_response(
        user_text,
        system_prompt=system_prompt,
        context_text=build_ai_manual_context()
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