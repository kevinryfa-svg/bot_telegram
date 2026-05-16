from telegram import Update
from telegram.ext import ContextTypes

from ai_service import (
    generate_ai_response,
    build_system_prompt_for_scope
)


# =========================
# AI HANDLER — HELPERS
# =========================

def extract_command_text(update: Update):

    if not update.message or not update.message.text:

        return ""


    parts = update.message.text.split(
        maxsplit=1
    )


    if len(parts) < 2:

        return ""


    return parts[1].strip()


async def send_ai_answer(update: Update, text):

    if not text:

        await update.message.reply_text(
            "❌ No se recibió respuesta de la IA."
        )

        return


    max_length = 3900


    if len(text) <= max_length:

        await update.message.reply_text(text)
        return


    for i in range(0, len(text), max_length):

        await update.message.reply_text(
            text[i:i + max_length]
        )


# =========================
# AI HANDLER — /ia
# =========================

async def ia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_text = extract_command_text(update)


    if not user_text:

        await update.message.reply_text(
            "🤖 Uso de IA:\n\n"
            "/ia escribe aquí tu pregunta\n\n"
            "Ejemplo:\n"
            "/ia redacta un mensaje profesional para avisar de una renovación"
        )

        return


    await update.message.reply_text(
        "🤖 Pensando..."
    )


    system_prompt = build_system_prompt_for_scope(
        "default"
    )


    ok, answer = generate_ai_response(
        user_text,
        system_prompt=system_prompt
    )


    if not ok:

        await update.message.reply_text(answer)
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

        await update.message.reply_text(
            "🤖 Asistente IA:\n\n"
            "/asistente escribe aquí lo que necesitas\n\n"
            "Ejemplo:\n"
            "/asistente ayúdame a responder a un usuario que no puede entrar al grupo"
        )

        return


    await update.message.reply_text(
        "🤖 Preparando respuesta..."
    )


    system_prompt = build_system_prompt_for_scope(
        "default"
    )


    ok, answer = generate_ai_response(
        user_text,
        system_prompt=system_prompt
    )


    if not ok:

        await update.message.reply_text(answer)
        return


    await send_ai_answer(
        update,
        answer
    )
