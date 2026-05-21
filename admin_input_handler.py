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
from rbac_helpers import get_admin_group_ids


GROUP_ADMIN_PERMISSION_OPTIONS = [
    ("view_users", "Ver usuarios", "can_view_users"),
    ("manage_users", "Gestionar usuarios", "can_manage_users"),
    ("kick_users", "Expulsar usuarios", "can_kick_users"),
    ("ban_users", "Banear usuarios", "can_ban_users"),
    ("unban_users", "Desbanear usuarios", "can_unban_users"),
    ("warn_users", "Dar warnings", "can_warn_users"),
    ("reset_warnings", "Resetear warnings", "can_reset_warnings"),
    ("manage_links", "Gestionar enlaces", "can_resend_links"),
    ("view_stats", "Ver estadísticas", "can_view_stats"),
    ("manage_plans", "Gestionar planes", "can_manage_plans"),
    ("edit_texts", "Editar textos del grupo", "can_edit_group_texts"),
    ("edit_preview", "Editar preview marketplace", "can_edit_marketplace_preview"),
    ("support", "Responder soporte del grupo", "can_respond_group_support"),
    ("view_logs", "Ver logs del grupo", "can_view_logs")
]


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


def lookup_group_admin_target_user(raw_text):

    raw_text = (raw_text or "").strip()


    if not raw_text:

        return None


    with conn.cursor() as cur:

        if raw_text.startswith("@"):

            username = raw_text[1:]

            cur.execute("""

                SELECT user_id,
                       username,
                       first_name
                FROM (
                    SELECT user_id, username, first_name
                    FROM users
                    WHERE username IS NOT NULL
                    UNION
                    SELECT user_id, username, first_name
                    FROM commercial_requests
                    WHERE username IS NOT NULL
                ) known_users
                WHERE LOWER(username)=LOWER(%s)
                LIMIT 1

            """, (username,))

        else:

            try:

                target_user_id = int(raw_text)

            except Exception:

                return None


            if target_user_id <= 0:

                return None


            cur.execute("""

                SELECT user_id,
                       username,
                       first_name
                FROM (
                    SELECT user_id, username, first_name
                    FROM users
                    WHERE user_id=%s
                    UNION
                    SELECT user_id, username, first_name
                    FROM commercial_requests
                    WHERE user_id=%s
                    UNION
                    SELECT user_id, NULL AS username, NULL AS first_name
                    FROM admins
                    WHERE user_id=%s
                ) known_users
                LIMIT 1

            """, (
                target_user_id,
                target_user_id,
                target_user_id
            ))


        row = cur.fetchone()


        if row:

            return row


        if not raw_text.startswith("@"):

            return target_user_id, None, None


        return None


def build_group_admin_back_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="group_admin_panel"
        )],
        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]
    ])


def fetch_manageable_admin_groups(user_id):

    group_ids = get_admin_group_ids(
        user_id,
        ["can_manage_admins"]
    )


    with conn.cursor() as cur:

        if group_ids is None:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id
                FROM groups
                WHERE telegram_group_id != 0
                ORDER BY id ASC

            """)

        elif not group_ids:

            return []

        else:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id
                FROM groups
                WHERE telegram_group_id != 0
                AND id = ANY(%s)
                ORDER BY id ASC

            """, (group_ids,))


        return cur.fetchall()


def fetch_context_manageable_admin_groups(context, user_id):

    groups = fetch_manageable_admin_groups(user_id)
    selected_owner_group = context.user_data.get("selected_owner_group")


    if selected_owner_group:

        for group in groups:

            if int(group[0]) == int(selected_owner_group):

                return [group]


    return groups


def format_pending_group_admin_permissions(selected_permissions):

    lines = []


    for _key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        marker = "✅" if selected_permissions.get(permission) is True else "▫️"
        lines.append(f"{marker} {label}")


    return "\n".join(lines)


def build_pending_group_admin_permissions_keyboard(group_id, target_user_id, permissions):

    keyboard = []


    for key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        marker = "✅" if permissions.get(permission) is True else "▫️"
        keyboard.append([InlineKeyboardButton(
            f"{marker} {label}",
            callback_data=f"gga_t_{group_id}_{target_user_id}_{key}"
        )])


    keyboard.append([InlineKeyboardButton(
        "💾 Guardar admin",
        callback_data=f"add_group_admin_save_{group_id}"
    )])
    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="group_admin_panel"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_group_admin_add_group_keyboard(groups):

    keyboard = []


    for group_id, name, _telegram_group_id in groups:

        keyboard.append([InlineKeyboardButton(
            name or f"Grupo {group_id}",
            callback_data=f"add_group_admin_select_group_{group_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="group_admin_panel"
    )])

    return InlineKeyboardMarkup(keyboard)


async def receive_admin_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if context.user_data.get("adding_group_admin"):

        text = update.message.text.strip()
        target = lookup_group_admin_target_user(text)


        if not target:

            await update.message.reply_text(
                "❌ Usuario no encontrado en la base de datos.\n\n"
                "Puedes enviar un user_id numérico válido o un @username que ya exista en la base.",
                reply_markup=build_group_admin_back_keyboard()
            )

            return


        target_user_id, username, first_name = target


        if int(target_user_id) == int(update.effective_user.id):

            await update.message.reply_text(
                "❌ No puedes añadirte a ti mismo como admin.",
                reply_markup=build_group_admin_back_keyboard()
            )

            return


        groups = fetch_context_manageable_admin_groups(
            context,
            update.effective_user.id
        )


        if not groups:

            context.user_data["adding_group_admin"] = False

            await update.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_group_admin_back_keyboard()
            )

            return


        context.user_data["group_admin_target_user_id"] = target_user_id
        context.user_data["group_admin_target_display"] = (
            f"@{username}" if username else first_name or str(target_user_id)
        )
        context.user_data["adding_group_admin"] = False


        if len(groups) > 1:

            await update.message.reply_text(
                "Selecciona la comunidad donde quieres añadir este admin.",
                reply_markup=build_group_admin_add_group_keyboard(groups)
            )

            return


        group_id = groups[0][0]
        context.user_data["group_admin_selected_group_id"] = group_id
        context.user_data["group_admin_permissions"] = {
            permission: False
            for _key, _label, permission in GROUP_ADMIN_PERMISSION_OPTIONS
        }

        await update.message.reply_text(
            "Permisos del nuevo admin:\n\n"
            + format_pending_group_admin_permissions(
                context.user_data["group_admin_permissions"]
            ),
            reply_markup=build_pending_group_admin_permissions_keyboard(
                group_id,
                target_user_id,
                context.user_data["group_admin_permissions"]
            )
        )

        return

    # =========================
    # RECIBIR PREVIEW MEDIA
    # =========================

    if context.user_data.get("editing_preview"):

        file_id = None
        file_type = None

        if update.message.photo:

            file_id = update.message.photo[-1].file_id
            file_type = "image"

        elif update.message.video:

            file_id = update.message.video.file_id
            file_type = "video"

        else:

            await update.message.reply_text(
                "❌ Debes enviar imagen o video."
            )

            return


        context.user_data["new_preview_file"] = file_id
        context.user_data["new_preview_file_type"] = file_type


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
            group_id = context.user_data.get("selected_group_admin")

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
                        AND group_id=%s

                    """, (

                        name,
                        price_id,
                        duration_days,
                        amount,
                        currency,
                        plan_id,
                        group_id

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
