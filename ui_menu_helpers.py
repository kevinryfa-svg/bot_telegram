from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup
)


# =========================
# UI MENU HELPERS
# =========================

# These helpers keep Telegram keyboard construction consistent across modules.
# They do not depend on database state and can be used safely by start_handler,
# callback_router or future menu modules.


def make_button(text, callback_data):

    return InlineKeyboardButton(
        text,
        callback_data=callback_data
    )



def make_url_button(text, url):

    return InlineKeyboardButton(
        text,
        url=url
    )



def make_row(*buttons):

    return list(buttons)



def make_single_button_row(text, callback_data):

    return [
        make_button(
            text,
            callback_data
        )
    ]



def make_keyboard(rows):

    return InlineKeyboardMarkup(rows)



def make_keyboard_from_specs(rows):

    keyboard = []


    for row in rows:

        keyboard_row = []


        for button in row:

            if button.get("url"):

                keyboard_row.append(
                    make_url_button(
                        button["text"],
                        button["url"]
                    )
                )

            else:

                keyboard_row.append(
                    make_button(
                        button["text"],
                        button["callback_data"]
                    )
                )


        keyboard.append(keyboard_row)


    return InlineKeyboardMarkup(keyboard)



def add_help_button(rows, callback_data, text="💬 Ayuda sobre este menú"):

    rows.append([
        make_button(
            text,
            callback_data
        )
    ])

    return rows



def add_back_button(rows, callback_data, text="⬅️ Volver"):

    rows.append([
        make_button(
            text,
            callback_data
        )
    ])

    return rows



def add_help_and_back_buttons(
    rows,
    help_callback_data,
    back_callback_data,
    help_text="💬 Ayuda sobre este menú",
    back_text="⬅️ Volver"
):

    add_help_button(
        rows,
        help_callback_data,
        help_text
    )

    add_back_button(
        rows,
        back_callback_data,
        back_text
    )

    return rows



def chunk_buttons(buttons, size=1):

    if size <= 0:

        size = 1


    return [
        buttons[index:index + size]
        for index in range(0, len(buttons), size)
    ]



def make_keyboard_from_flat_specs(buttons, row_size=1):

    rows = chunk_buttons(
        buttons,
        row_size
    )

    return make_keyboard_from_specs(rows)

def is_private_chat(chat_id):

    try:

        return int(chat_id) > 0

    except Exception:

        return True


async def delete_message_safely(context, chat_id, message_id):

    if not chat_id or not message_id:

        return False


    if not is_private_chat(chat_id):

        return False


    try:

        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )

        return True

    except Exception:

        return False


PREVIEW_MESSAGE_IDS_KEY = "pending_preview_message_ids"
PREVIEW_CHAT_ID_KEY = "pending_preview_chat_id"


def remember_preview_message(context, chat_id, message):

    if not message or not is_private_chat(chat_id):

        return


    message_id = getattr(message, "message_id", None)


    if not message_id:

        return


    preview_message_ids = context.user_data.setdefault(
        PREVIEW_MESSAGE_IDS_KEY,
        []
    )


    if message_id not in preview_message_ids:

        preview_message_ids.append(message_id)


    context.user_data[PREVIEW_CHAT_ID_KEY] = chat_id


async def delete_pending_preview_messages(context, chat_id=None):

    preview_message_ids = list(
        context.user_data.get(PREVIEW_MESSAGE_IDS_KEY) or []
    )


    if not preview_message_ids:

        context.user_data.pop(PREVIEW_CHAT_ID_KEY, None)

        return False


    preview_chat_id = chat_id or context.user_data.get(PREVIEW_CHAT_ID_KEY)


    if not preview_chat_id or not is_private_chat(preview_chat_id):

        context.user_data.pop(PREVIEW_MESSAGE_IDS_KEY, None)
        context.user_data.pop(PREVIEW_CHAT_ID_KEY, None)

        return False


    deleted_any = False


    for message_id in preview_message_ids:

        deleted = await delete_message_safely(
            context,
            preview_chat_id,
            message_id
        )


        if deleted:

            deleted_any = True


    context.user_data.pop(PREVIEW_MESSAGE_IDS_KEY, None)
    context.user_data.pop(PREVIEW_CHAT_ID_KEY, None)

    return deleted_any


async def delete_active_bot_message(context, chat_id):

    if not is_private_chat(chat_id):

        return False


    message_id = context.user_data.get("active_bot_message_id")


    if not message_id:

        return False


    deleted = await delete_message_safely(
        context,
        chat_id,
        message_id
    )

    context.user_data.pop("active_bot_message_id", None)

    return deleted


async def send_clean_message(
    context,
    chat_id,
    text,
    reply_markup=None,
    **kwargs
):

    if is_private_chat(chat_id):

        await delete_pending_preview_messages(
            context,
            chat_id
        )

        await delete_active_bot_message(
            context,
            chat_id
        )


    message = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        **kwargs
    )


    if is_private_chat(chat_id):

        context.user_data["active_bot_message_id"] = message.message_id


    return message
