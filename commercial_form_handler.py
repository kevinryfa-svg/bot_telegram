from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from bot_config import ADMIN_ID
from db import conn
from rbac_helpers import assign_group_owner_permissions


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

    keyboard = [

        [InlineKeyboardButton(
            "🔎 Revisar solicitud #" + str(request_id),
            callback_data=f"admin_commercial_review_{request_id}"
        )],

        [InlineKeyboardButton(
            "📩 Ver solicitudes comerciales",
            callback_data="admin_commercial_requests"
        )]

    ]

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def clear_commercial_form(context):

    context.user_data.pop("commercial_form", None)
    context.user_data.pop("commercial_form_type", None)
    context.user_data.pop("commercial_form_step", None)
    context.user_data.pop("commercial_form_data", None)


def clear_creator_setup(context):

    context.user_data.pop("creator_setup", None)
    context.user_data.pop("creator_setup_request_id", None)
    context.user_data.pop("creator_setup_action", None)
    context.user_data.pop("creator_setup_step", None)
    context.user_data.pop("creator_setup_data", None)


def mask_secret(value):

    if not value:

        return "pendiente"


    if len(value) <= 8:

        return "configurado"


    return f"{value[:4]}...{value[-4:]}"


def fetch_creator_request(request_id, user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   user_id,
                   payment_mode,
                   requested_public_visibility,
                   approved_group_id,
                   approved_telegram_group_id
            FROM commercial_requests
            WHERE id=%s
            LIMIT 1

        """, (request_id,))

        row = cur.fetchone()


    if not row:

        return None


    if int(row[1] or 0) != int(user_id):

        return None


    return {
        "id": row[0],
        "user_id": row[1],
        "payment_mode": row[2],
        "requested_public_visibility": row[3],
        "approved_group_id": row[4],
        "approved_telegram_group_id": row[5]
    }


def find_group_by_telegram_id(text):

    try:

        telegram_group_id = int(text)

    except Exception:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   telegram_group_id,
                   is_active,
                   COALESCE(public_visibility, 'hidden')
            FROM groups
            WHERE telegram_group_id=%s
            LIMIT 1

        """, (telegram_group_id,))

        return cur.fetchone()


def max_groups_allowed(_user_id):

    return 1


def creator_group_count(user_id, exclude_request_id=None):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(DISTINCT approved_group_id)
            FROM commercial_requests
            WHERE user_id=%s
            AND approved_group_id IS NOT NULL
            AND (%s IS NULL OR id != %s)

        """, (
            user_id,
            exclude_request_id,
            exclude_request_id
        ))

        return cur.fetchone()[0] or 0


def creator_reached_group_limit(user_id, request_id):

    allowed = max_groups_allowed(user_id)

    return creator_group_count(user_id, request_id) >= allowed


def get_request_group_id(request_row):

    approved_group_id = request_row.get("approved_group_id")
    approved_telegram_group_id = request_row.get("approved_telegram_group_id")


    with conn.cursor() as cur:

        if approved_group_id:

            cur.execute("""

                SELECT id
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (approved_group_id,))

            row = cur.fetchone()


            if row:

                return row[0]


        if approved_telegram_group_id:

            cur.execute("""

                SELECT id
                FROM groups
                WHERE telegram_group_id=%s
                LIMIT 1

            """, (approved_telegram_group_id,))

            row = cur.fetchone()


            if row:

                return row[0]


    return None


def get_back_to_setup_keyboard(request_id):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton(
            "📦 Configurar comunidad",
            callback_data=f"configure_community_{request_id}"
        )],

        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]

    ])


async def receive_creator_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:

        return


    text = update.message.text.strip()
    request_id = context.user_data.get("creator_setup_request_id")
    action = context.user_data.get("creator_setup_action")
    step = context.user_data.get("creator_setup_step", 1)
    setup_data = context.user_data.setdefault("creator_setup_data", {})
    request_row = fetch_creator_request(
        request_id,
        update.effective_user.id
    )


    if not request_row:

        clear_creator_setup(context)

        await update.message.reply_text(
            "⛔ Esta solicitud no pertenece a tu usuario."
        )

        return


    if action == "group":

        group_row = find_group_by_telegram_id(text)

        if group_row:

            group_id, telegram_group_id, is_active, _public_visibility = group_row


            if not is_active:

                with conn.cursor() as cur:

                    cur.execute("""

                        UPDATE commercial_requests
                        SET telegram_group_link=%s,
                            creator_setup_status='setup_in_progress',
                            updated_at=NOW()
                        WHERE id=%s

                    """, (
                        text,
                        request_id
                    ))

                clear_creator_setup(context)

                await update.message.reply_text(
                    "📡 Grupo/canal guardado como pendiente de verificación.\n\n"
                    "El grupo existe en el sistema, pero está no activo/no publicado. "
                    "Esto ocurre cuando el bot fue añadido por un usuario no autorizado o falta revisión manual.\n\n"
                    "Para resolverlo, el propietario principal debe revisar el grupo, activarlo y asociarlo a esta solicitud.",
                    reply_markup=get_back_to_setup_keyboard(request_id)
                )

                return


            if creator_reached_group_limit(
                request_row["user_id"],
                request_id
            ):

                clear_creator_setup(context)

                await update.message.reply_text(
                    "Has alcanzado el máximo de comunidades permitidas para tu plan actual.",
                    reply_markup=get_back_to_setup_keyboard(request_id)
                )

                return

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE commercial_requests
                    SET telegram_group_link=%s,
                        approved_group_id=%s,
                        approved_telegram_group_id=%s,
                        creator_setup_status='setup_in_progress',
                        updated_at=NOW()
                    WHERE id=%s

                """, (
                    text,
                    group_id,
                    telegram_group_id,
                    request_id
                ))

                cur.execute("""

                    UPDATE group_payment_settings
                    SET group_id=%s,
                        updated_at=NOW()
                    WHERE commercial_request_id=%s

                """, (
                    group_id,
                    request_id
                ))

                public_visibility = request_row.get("requested_public_visibility")


                if public_visibility:

                    cur.execute("""

                        UPDATE groups
                        SET public_visibility=%s,
                            is_free_group=%s
                        WHERE id=%s

                    """, (
                        public_visibility,
                        request_row.get("payment_mode") == "free",
                        group_id
                    ))


                if not public_visibility:

                    cur.execute("""

                        UPDATE groups
                        SET is_free_group=%s
                        WHERE id=%s

                    """, (
                        request_row.get("payment_mode") == "free",
                        group_id
                    ))


                assign_group_owner_permissions(
                    request_row["user_id"],
                    group_id
                )

        else:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE commercial_requests
                    SET telegram_group_link=%s,
                        creator_setup_status='setup_in_progress',
                        updated_at=NOW()
                    WHERE id=%s

                """, (
                    text,
                    request_id
                ))


        clear_creator_setup(context)


        if group_row:

            await update.message.reply_text(
                "✅ Grupo/canal vinculado correctamente.\n\n"
                "El panel de gestión se activó para esta comunidad.",
                reply_markup=get_back_to_setup_keyboard(request_id)
            )

            return


        await update.message.reply_text(
            "📡 Grupo/canal guardado como pendiente de verificación.\n\n"
            "Está pendiente porque todavía no se pudo asociar con un grupo real registrado y activo en el bot.\n\n"
            "Qué falta:\n"
            "1. Añade el bot al grupo/canal.\n"
            "2. Dale permisos de administrador.\n"
            "3. Asegúrate de que el grupo quede detectado por el bot.\n"
            "4. Vuelve a introducir el ID cuando esté registrado.\n\n"
            "Cuando el grupo exista en el sistema, se podrá activar el panel de gestión.",
            reply_markup=get_back_to_setup_keyboard(request_id)
        )

        return


    if action == "texts":

        if step == 1:

            setup_data["community_name"] = text
            context.user_data["creator_setup_step"] = 2

            await update.message.reply_text(
                "Describe tu comunidad en una frase clara."
            )

            return


        if step == 2:

            setup_data["community_description"] = text
            context.user_data["creator_setup_step"] = 3

            await update.message.reply_text(
                "Escribe el texto breve que quieres usar como preview o presentación."
            )

            return


        if step == 3:

            setup_data["creator_preview_text"] = text
            group_id = get_request_group_id(request_row)

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE commercial_requests
                    SET community_name=%s,
                        community_description=%s,
                        creator_preview_text=%s,
                        creator_setup_status='setup_in_progress',
                        updated_at=NOW()
                    WHERE id=%s

                """, (
                    setup_data.get("community_name"),
                    setup_data.get("community_description"),
                    setup_data.get("creator_preview_text"),
                    request_id
                ))


                if group_id:

                    cur.execute("""

                        UPDATE groups
                        SET name=%s,
                            preview_text=%s
                        WHERE id=%s

                    """, (
                        setup_data.get("community_name"),
                        setup_data.get("creator_preview_text"),
                        group_id
                    ))


            clear_creator_setup(context)

            await update.message.reply_text(
                "✅ Textos guardados correctamente.",
                reply_markup=get_back_to_setup_keyboard(request_id)
            )

            return


    if action == "stripe":

        if step == 1:

            setup_data["owner_stripe_secret_key"] = text
            context.user_data["creator_setup_step"] = 2

            await update.message.reply_text(
                "Envía ahora el STRIPE_WEBHOOK_SECRET de tu Stripe."
            )

            return


        if step == 2:

            setup_data["owner_stripe_webhook_secret"] = text
            context.user_data["creator_setup_step"] = 3

            await update.message.reply_text(
                "Envía tu STRIPE_PUBLISHABLE_KEY si la tienes. Si no, escribe \"no tengo\"."
            )

            return


        if step == 3:

            publishable_key = None


            if text.lower() not in ("no tengo", "no", "-", "ninguna"):

                publishable_key = text


            group_id = get_request_group_id(request_row)
            secret_key = setup_data.get("owner_stripe_secret_key")
            webhook_secret = setup_data.get("owner_stripe_webhook_secret")

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO group_payment_settings
                    (
                        group_id,
                        commercial_request_id,
                        owner_user_id,
                        stripe_mode,
                        owner_stripe_secret_key,
                        owner_stripe_webhook_secret,
                        owner_stripe_publishable_key,
                        is_configured,
                        updated_at
                    )
                    VALUES (%s, %s, %s, 'owner_stripe', %s, %s, %s, %s, NOW())
                    ON CONFLICT (commercial_request_id)
                    DO UPDATE SET
                        group_id=EXCLUDED.group_id,
                        owner_user_id=EXCLUDED.owner_user_id,
                        stripe_mode='owner_stripe',
                        owner_stripe_secret_key=EXCLUDED.owner_stripe_secret_key,
                        owner_stripe_webhook_secret=EXCLUDED.owner_stripe_webhook_secret,
                        owner_stripe_publishable_key=EXCLUDED.owner_stripe_publishable_key,
                        is_configured=EXCLUDED.is_configured,
                        updated_at=NOW()

                """, (
                    group_id,
                    request_id,
                    request_row["user_id"],
                    secret_key,
                    webhook_secret,
                    publishable_key,
                    bool(secret_key and webhook_secret)
                ))

                cur.execute("""

                    UPDATE commercial_requests
                    SET stripe_mode='owner_stripe',
                        creator_setup_status='setup_in_progress',
                        updated_at=NOW()
                    WHERE id=%s

                """, (request_id,))


            clear_creator_setup(context)

            await update.message.reply_text(
                "✅ Cobros / Stripe propio guardado.\n\n"
                f"STRIPE_SECRET_KEY: {mask_secret(secret_key)}\n"
                f"STRIPE_WEBHOOK_SECRET: {mask_secret(webhook_secret)}\n"
                f"STRIPE_PUBLISHABLE_KEY: {mask_secret(publishable_key)}\n\n"
                "El checkout real con Stripe del creador queda pendiente de conectar en una fase posterior.",
                reply_markup=get_back_to_setup_keyboard(request_id)
            )

            return


    if action == "plan":

        group_id = get_request_group_id(request_row)


        if not group_id:

            clear_creator_setup(context)

            await update.message.reply_text(
                "⚠️ No se puede guardar un plan todavía.\n\n"
                "Falta un groups.id real asociado a tu solicitud. "
                "La tabla actual de planes necesita group_id y no existe estructura segura de planes pendientes por solicitud.",
                reply_markup=get_back_to_setup_keyboard(request_id)
            )

            return


        if step == 1:

            setup_data["name"] = text
            context.user_data["creator_setup_step"] = 2

            await update.message.reply_text(
                "Introduce la duración del plan en días."
            )

            return


        if step == 2:

            try:

                setup_data["duration_days"] = int(text)

            except Exception:

                await update.message.reply_text(
                    "❌ Número inválido. Introduce la duración en días."
                )

                return


            context.user_data["creator_setup_step"] = 3

            await update.message.reply_text(
                "Introduce el precio en céntimos. Ejemplo: 999 para 9,99."
            )

            return


        if step == 3:

            try:

                setup_data["amount"] = int(text)

            except Exception:

                await update.message.reply_text(
                    "❌ Precio inválido. Introduce el importe en céntimos."
                )

                return


            context.user_data["creator_setup_step"] = 4

            await update.message.reply_text(
                "Introduce la moneda. Ejemplo: EUR."
            )

            return


        if step == 4:

            setup_data["currency"] = text.upper()
            context.user_data["creator_setup_step"] = 5

            await update.message.reply_text(
                "Introduce el price_id de Stripe para este plan."
            )

            return


        if step == 5:

            setup_data["price_id"] = text

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO plans
                    (
                        group_id,
                        name,
                        price_id,
                        duration_days,
                        amount,
                        currency,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE)

                """, (
                    group_id,
                    setup_data.get("name"),
                    setup_data.get("price_id"),
                    setup_data.get("duration_days"),
                    setup_data.get("amount"),
                    setup_data.get("currency")
                ))

                cur.execute("""

                    UPDATE commercial_requests
                    SET creator_setup_status='setup_in_progress',
                        updated_at=NOW()
                    WHERE id=%s

                """, (request_id,))


            clear_creator_setup(context)

            await update.message.reply_text(
                "✅ Plan guardado correctamente.\n\n"
                "Este price_id pertenece al Stripe propio del creador. "
                "El cobro automático real queda pendiente de conectar en una fase posterior.",
                reply_markup=get_back_to_setup_keyboard(request_id)
            )

            return


    clear_creator_setup(context)

    await update.message.reply_text(
        "⚠️ No se reconoció el paso de configuración.",
        reply_markup=get_back_to_setup_keyboard(request_id)
    )


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

    keyboard = [

        [InlineKeyboardButton(
            "⬅️ Volver al inicio",
            callback_data="public_back_start"
        )],

        [InlineKeyboardButton(
            "🚀 Soluciones para mi comunidad",
            callback_data="public_monetize_community"
        )]

    ]

    if request_type == "shared_trial":

        await update.message.reply_text(
            "✅ Solicitud enviada. Revisaremos tu comunidad y te contactaremos para activar la prueba de 1 día.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return


    await update.message.reply_text(
        "✅ Solicitud enviada. Revisaremos la configuración y te indicaremos el siguiente paso. El bot personalizado no tiene prueba gratuita; se configura primero y se activa tras el pago.",
        reply_markup=InlineKeyboardMarkup(keyboard)
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
