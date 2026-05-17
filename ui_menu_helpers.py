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
