from telegram import Update
from telegram.ext import ContextTypes

from bot_config import ADMIN_ID
from db import conn


def create_commercial_request(user, request_type, form_data=None):

    form_data = form_data or {}

    username = user.username if user else None
    first_name = user.first_name if user else None
    user_id = user.id if user else None

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO commercial_requests
            (
                user_id,
                username,
                first_name,
                request_type,
                community_name,
                community_description,
                telegram_group_link,
                bot_name,
                bot_username,
                project_description,
                contact_text
            )

            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

            RETURNING id

        """, (

            user_id,
            username,
            first_name,
            request_type,
            form_data.get("community_name"),
            form_data.get("community_description"),
            form_data.get("telegram_group_link"),
            form_data.get("bot_name"),
            form_data.get("bot_username"),
            form_data.get("project_description"),
            form_data.get("contact_text")

        ))

        request_id = cur.fetchone()[0]

        conn.commit()

    return request_id


async def notify_commercial_request(context, request_id, request_type, user, form_data=None):

    form_data = form_data or {}

    username = user.username if user and user.username else "sin username"
    first_name = user.first_name if user and user.first_name else "sin nombre"
    user_id = user.id if user else "desconocido"

    text = (

        "📩 Nueva solicitud comercial\n\n"
        f"ID solicitud: {request_id}\n"
        f"Tipo: {request_type}\n"
        f"Usuario: {user_id}\n"
        f"Username: @{username}\n"
        f"Nombre: {first_name}\n\n"
        f"Comunidad/proyecto: {form_data.get('community_name') or '-'}\n"
        f"Descripción comunidad: {form_data.get('community_description') or '-'}\n"
        f"Link grupo/canal: {form_data.get('telegram_group_link') or '-'}\n"
        f"Nombre bot: {form_data.get('bot_name') or '-'}\n"
        f"Username bot: {form_data.get('bot_username') or '-'}\n"
        f"Descripción proyecto: {form_data.get('project_description') or '-'}\n"
        f"Contacto: {form_data.get('contact_text') or '-'}"

    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=text
    )


def clear_commercial_form(context):

    context.user_data.pop("commercial_form", None)
    context.user_data.pop("commercial_form_type", None)
    context.user_data.pop("commercial_form_step", None)
    context.user_data.pop("commercial_form_data", None)


async def finish_commercial_form(update, context, request_type, form_data):

    user = update.effective_user

    request_id = create_commercial_request(
        user,
        request_type,
        form_data
    )

    await notify_commercial_request(
        context,
        request_id,
        request_type,
        user,
        form_data
    )

    clear_commercial_form(context)

    if request_type == "shared_trial":

        await update.message.reply_text(
            "✅ Solicitud enviada. Revisaremos tu comunidad y te contactaremos para activar la prueba de 1 día."
        )

        return


    await update.message.reply_text(
        "✅ Solicitud enviada. Revisaremos la configuración y te indicaremos el siguiente paso. El bot personalizado no tiene prueba gratuita; se configura primero y se activa tras el pago."
    )


async def receive_commercial_form(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:

        return


    text = update.message.text.strip()
    form_type = context.user_data.get("commercial_form_type")
    step = context.user_data.get("commercial_form_step", 1)
    form_data = context.user_data.setdefault("commercial_form_data", {})


    if form_type == "shared_trial":

        if step == 1:

            form_data["community_name"] = text
            context.user_data["commercial_form_step"] = 2

            await update.message.reply_text(
                "Describe brevemente tu comunidad."
            )

            return


        if step == 2:

            form_data["community_description"] = text
            context.user_data["commercial_form_step"] = 3

            await update.message.reply_text(
                "Envía el link o @usuario del grupo/canal si lo tienes. Si no lo tienes, escribe \"no tengo\"."
            )

            return


        if step == 3:

            form_data["telegram_group_link"] = text
            context.user_data["commercial_form_step"] = 4

            await update.message.reply_text(
                "Indica tu contacto: teléfono, email, Telegram o cómo quieres que te contacten."
            )

            return


        if step == 4:

            form_data["contact_text"] = text

            await finish_commercial_form(
                update,
                context,
                "shared_trial",
                form_data
            )

            return


    if form_type == "custom_bot":

        if step == 1:

            form_data["community_name"] = text
            context.user_data["commercial_form_step"] = 2

            await update.message.reply_text(
                "Indica el nombre deseado del bot."
            )

            return


        if step == 2:

            form_data["bot_name"] = text
            context.user_data["commercial_form_step"] = 3

            await update.message.reply_text(
                "Envía el @username del bot si ya lo creaste en BotFather. Si no lo tienes, escribe \"no tengo\"."
            )

            return


        if step == 3:

            form_data["bot_username"] = text
            context.user_data["commercial_form_step"] = 4

            await update.message.reply_text(
                "Describe lo que quieres vender o gestionar."
            )

            return


        if step == 4:

            form_data["project_description"] = text
            context.user_data["commercial_form_step"] = 5

            await update.message.reply_text(
                "Indica tu contacto: teléfono, email, Telegram o cómo quieres que te contacten."
            )

            return


        if step == 5:

            form_data["contact_text"] = text

            await finish_commercial_form(
                update,
                context,
                "custom_bot",
                form_data
            )

            return


    clear_commercial_form(context)

    await update.message.reply_text(
        "❌ No se pudo continuar el formulario. Vuelve a iniciar la solicitud."
    )
