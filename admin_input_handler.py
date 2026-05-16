from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from db import conn
from bot_config import TOKEN
from code_flow_handler import (
    receive_code,
    get_group_id,
    format_tiempo_restante
)
from invite_link_service import (
    create_telegram_invite_link,
    revoke_telegram_invite_link
)


def revoke_link(chat_id, link):

    try:

        revoke_telegram_invite_link(
            TOKEN,
            chat_id,
            link
        )

    except Exception as e:

        print(
            "Error revoke_link:",
            e
        )


async def receive_admin_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # =========================
    # RECIBIR PREVIEW MEDIA
    # =========================

    if context.user_data.get("editing_preview"):

        file_id = None

        if update.message.photo:

            file_id = update.message.photo[-1].file_id

        elif update.message.video:

            file_id = update.message.video.file_id

        else:

            await update.message.reply_text(
                "❌ Debes enviar imagen o video."
            )

            return


        context.user_data["new_preview_file"] = file_id


        keyboard = [

            [InlineKeyboardButton(
                "💾 Guardar cambios",
                callback_data="save_preview"
            )],

            [InlineKeyboardButton(
                "❌ Descartar",
                callback_data="cancel_preview"
            )]

        ]


        await update.message.reply_text(

            "Preview recibido.\n\n"

            "¿Deseas guardar cambios?",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if context.user_data.get("editing_plan"):

        step = context.user_data.get("edit_plan_step")

        text = update.message.text.strip()


        # =========================
        # PASO 1 — NUEVO NOMBRE
        # =========================

        if step == 1:

            context.user_data["edit_plan_name"] = text
            context.user_data["edit_plan_step"] = 2

            await update.message.reply_text(

                "Paso 2️⃣\n\n"

                "Introduce el nuevo PRICE ID."

            )

            return


        # =========================
        # PASO 2 — NUEVO PRICE ID
        # =========================

        if step == 2:

            context.user_data["edit_plan_price"] = text
            context.user_data["edit_plan_step"] = 3

            await update.message.reply_text(

                "Paso 3️⃣\n\n"

                "Introduce la nueva duración en días."

            )

            return


        # =========================
        # PASO 3 — NUEVA DURACIÓN
        # =========================

        if step == 3:

            try:

                duration_days = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            context.user_data["edit_plan_duration"] = duration_days
            context.user_data["edit_plan_step"] = 4

            await update.message.reply_text(

                "Paso 4️⃣\n\n"

                "Introduce el nuevo PRECIO."

            )

            return


        # =========================
        # PASO 4 — NUEVO PRECIO
        # =========================

        if step == 4:

            try:

                amount = int(text)

            except:

                await update.message.reply_text(
                    "❌ Precio inválido."
                )

                return


            context.user_data["edit_plan_amount"] = amount
            context.user_data["edit_plan_step"] = 5

            await update.message.reply_text(

                "Paso 5️⃣\n\n"

                "Introduce la nueva MONEDA."

            )

            return


        # =========================
        # PASO 5 — NUEVA MONEDA
        # =========================

        if step == 5:

            currency = text.upper()

            plan_id = context.user_data.get("editing_plan_id")

            name = context.user_data.get("edit_plan_name")

            price_id = context.user_data.get("edit_plan_price")

            duration_days = context.user_data.get("edit_plan_duration")

            amount = context.user_data.get("edit_plan_amount")


            try:

                with conn.cursor() as cur:

                    cur.execute("""

                        UPDATE plans

                        SET
                            name=%s,
                            price_id=%s,
                            duration_days=%s,
                            amount=%s,
                            currency=%s

                        WHERE id=%s

                    """, (

                        name,
                        price_id,
                        duration_days,
                        amount,
                        currency,
                        plan_id

                    ))

                    conn.commit()

            except Exception as e:

                print("Error editando plan:", e)

                await update.message.reply_text(
                    "❌ Error editando plan."
                )

                return


            context.user_data["editing_plan"] = False

            await update.message.reply_text(

                "✅ Plan actualizado correctamente."

            )

            return


    # =========================
    # AÑADIR PLAN — WIZARD
    # =========================

    if context.user_data.get("adding_plan"):

        step = context.user_data.get("add_plan_step")

        text = update.message.text.strip()

        group_id = context.user_data.get("selected_group_admin")


        # =========================
        # PASO 1 — NOMBRE
        # =========================

        if step == 1:

            context.user_data.setdefault("new_plan", {})

            context.user_data["new_plan"]["name"] = text
            context.user_data["add_plan_step"] = 2

            await update.message.reply_text(

                "Paso 2️⃣\n\n"
                "Introduce el PRICE ID."

            )

            return


        # =========================
        # PASO 2 — PRICE ID
        # =========================

        if step == 2:

            context.user_data["new_plan"]["price_id"] = text
            context.user_data["add_plan_step"] = 3

            await update.message.reply_text(

                "Paso 3️⃣\n\n"
                "Introduce duración en días."

            )

            return


        # =========================
        # PASO 3 — DURACIÓN
        # =========================

        if step == 3:

            try:

                duration_days = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            context.user_data["new_plan"]["duration_days"] = duration_days
            context.user_data["add_plan_step"] = 4

            await update.message.reply_text(

                "Paso 4️⃣\n\n"
                "Introduce el PRECIO."

            )

            return


        # =========================
        # PASO 4 — PRECIO
        # =========================

        if step == 4:

            try:

                amount = int(text)

            except:

                await update.message.reply_text(
                    "❌ Precio inválido."
                )

                return


            context.user_data["new_plan"]["amount"] = amount
            context.user_data["add_plan_step"] = 5

            await update.message.reply_text(

                "Paso 5️⃣\n\n"
                "Introduce la MONEDA (EUR, USD...)."

            )

            return


        # =========================
        # PASO 5 — MONEDA Y GUARDAR
        # =========================

        if step == 5:

            currency = text.upper()

            plan = context.user_data["new_plan"]

            try:

                with conn.cursor() as cur:

                    cur.execute("""

                        INSERT INTO plans
                        (
                            group_id,
                            name,
                            price_id,
                            duration_days,
                            amount,
                            currency
                        )

                        VALUES (%s, %s, %s, %s, %s, %s)

                    """, (

                        group_id,
                        plan["name"],
                        plan["price_id"],
                        plan["duration_days"],
                        plan["amount"],
                        currency

                    ))

                    conn.commit()

            except Exception as e:

                print("Error guardando plan:", e)

                await update.message.reply_text(
                    "❌ Error guardando plan."
                )

                return


            context.user_data["adding_plan"] = False
            context.user_data.pop("new_plan", None)

            await update.message.reply_text(

                "✅ Plan creado correctamente."

            )

            return


    # =========================
    # USO NORMAL DE CÓDIGO
    # =========================

    if context.user_data.get("waiting_code"):

        await receive_code(update, context)

        return

    # ⚠️ IMPORTANTE:
    # Si no estamos esperando código → NO procesar

    if not context.user_data.get("waiting_code"):
        return

    user_code = update.message.text.strip().upper()

    with conn.cursor() as cur:

        cur.execute("""

            SELECT user_id
            FROM banned_users
            WHERE user_id=%s

        """, (update.effective_user.id,))

        banned = cur.fetchone()

        if banned:

            await update.message.reply_text(
                "⛔ Estás baneado permanentemente."
            )

            return


        cur.execute("""

        SELECT duration, used
        FROM invite_codes
        WHERE code=%s

        """, (user_code,))

        row = cur.fetchone()

        if not row:

            await update.message.reply_text(
                "❌ Código inválido"
            )
            return

        duration, used = row

        if used:

            await update.message.reply_text(
                "❌ Código ya usado"
            )
            return


        if duration == 0:

            expiration = None

        else:

            expiration = datetime.now() + timedelta(minutes=duration)


        cur.execute("""

            INSERT INTO users
            (user_id, username, first_name, expiration)

            VALUES (%s, %s, %s, %s)

            ON CONFLICT (user_id)
            DO UPDATE SET

                username=%s,
                first_name=%s,
                expiration=%s

        """, (

            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.first_name,
            expiration,
            update.effective_user.username,
            update.effective_user.first_name,
            expiration

        ))

        cur.execute("""

            UPDATE invite_codes
            SET used=TRUE
            WHERE code=%s

        """, (user_code,))


        cur.execute("""

            SELECT invite_link
            FROM invite_links
            WHERE user_id=%s
            AND group_id=%s

        """, (

            update.effective_user.id,
            get_group_id()

        ))


        old_links = cur.fetchall()

        for (old_link,) in old_links:

            try:

                revoke_link(
                    get_group_id(),
                    old_link
                )

                cur.execute("""

                    UPDATE invite_links

                    SET is_active=FALSE,
                        revoked_at=NOW()

                    WHERE invite_link=%s

                """, (old_link,))

            except Exception as e:

                print("Error revocando link:", e)


        # borrar antiguos

        cur.execute("""

            DELETE FROM invite_links
            WHERE user_id=%s
            AND group_id=%s

        """, (

            update.effective_user.id,
            get_group_id()

        ))

        conn.commit()


    link = create_telegram_invite_link(
        TOKEN,
        get_group_id(),
        expire_seconds=180,
        member_limit=1
    )


    if not link:

        await update.message.reply_text(
            "❌ Error creando link de acceso."
        )

        return


    try:

        with conn.cursor() as cur:

            cur.execute("""

    INSERT INTO invite_links
    (user_id, group_id, invite_link)

    VALUES (%s, %s, %s)

""", (

    update.effective_user.id,
    get_group_id(),
    link

))

            conn.commit()

    except Exception as e:

        print("Error guardando invite link:", e)


    # =========================
    # CALCULAR TIEMPO RESTANTE
    # =========================

    tiempo_texto = format_tiempo_restante(
        expiration
    )


    await update.message.reply_text(

        "🔗 Acceso concedido\n\n"

        f"⏳ Tiempo restante: {tiempo_texto}\n\n"

        f"{link}"

    )


    context.user_data["waiting_code"] = False
