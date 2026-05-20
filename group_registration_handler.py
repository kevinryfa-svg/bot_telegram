import asyncio
import requests

from telegram import Update
from telegram.ext import ContextTypes

from bot_config import TOKEN, ADMIN_ID
from db import conn
from rbac_helpers import (
    GROUP_OWNER,
    assign_group_owner_permissions,
    can_user_claim_telegram_group,
    get_group_owner_user_id
)


APPROVED_COMMERCIAL_STATUSES = (
    "trial_active",
    "awaiting_creator_setup",
    "setup_in_progress",
    "setup_ready",
    "active"
)


def sanitize_preview_caption(caption):

    caption = (caption or "").strip()


    if len(caption) > 500:

        caption = caption[:497] + "..."


    return caption


def get_dynamic_preview_group(telegram_group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   COALESCE(preview_mode, 'manual')
            FROM groups
            WHERE telegram_group_id=%s
            AND is_active=TRUE
            AND COALESCE(preview_mode, 'manual') IN ('dynamic', 'hybrid')
            LIMIT 1

        """, (telegram_group_id,))

        row = cur.fetchone()


    if not row:

        return None


    return {
        "group_id": row[0],
        "preview_mode": row[1]
    }


def save_group_preview_video(
    group_id,
    telegram_group_id,
    message_id,
    video_file_id,
    caption
):

    if not group_id or not telegram_group_id or not message_id or not video_file_id:

        return False


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO group_preview_videos
            (
                group_id,
                telegram_group_id,
                message_id,
                video_file_id,
                caption
            )
            VALUES (%s, %s, %s, %s, %s)

        """, (
            group_id,
            telegram_group_id,
            message_id,
            video_file_id,
            sanitize_preview_caption(caption)
        ))

        cur.execute("""

            UPDATE group_preview_videos
            SET is_active=FALSE
            WHERE group_id=%s
            AND id NOT IN (
                SELECT id
                FROM group_preview_videos
                WHERE group_id=%s
                AND is_active=TRUE
                ORDER BY created_at DESC, id DESC
                LIMIT 10
            )

        """, (
            group_id,
            group_id
        ))


    return True


async def capture_group_preview_video(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:

        return


    if not update.message.video:

        return


    if not update.effective_chat or update.effective_chat.type == "private":

        return


    telegram_group_id = update.effective_chat.id
    group_row = get_dynamic_preview_group(telegram_group_id)


    if not group_row:

        return


    saved = save_group_preview_video(
        group_row["group_id"],
        telegram_group_id,
        update.message.message_id,
        update.message.video.file_id,
        update.message.caption
    )


    if saved:

        print(
            "Vídeo guardado para preview dinámico:",
            group_row["group_id"],
            update.message.message_id
        )


def get_approved_creator_request(user_id, telegram_group_id):

    if not user_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   approved_group_id,
                   approved_telegram_group_id,
                   requested_public_visibility,
                   COALESCE(max_groups_allowed, 1),
                   COALESCE(is_free_group, FALSE),
                   payment_mode
            FROM commercial_requests
            WHERE user_id=%s
            AND request_type='shared_trial'
            AND status = ANY(%s)
            ORDER BY
                CASE
                    WHEN approved_telegram_group_id=%s THEN 0
                    WHEN approved_group_id IS NULL THEN 1
                    ELSE 2
                END ASC,
                reviewed_at DESC NULLS LAST,
                created_at DESC
            LIMIT 1

        """, (
            user_id,
            list(APPROVED_COMMERCIAL_STATUSES),
            telegram_group_id
        ))

        row = cur.fetchone()


    if not row:

        return None


    return {
        "id": row[0],
        "approved_group_id": row[1],
        "approved_telegram_group_id": row[2],
        "requested_public_visibility": row[3],
        "max_groups_allowed": row[4] or 1,
        "is_free_group": row[5] is True or row[6] == "free"
    }


def get_existing_group(telegram_group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id
            FROM groups
            WHERE telegram_group_id=%s
            LIMIT 1

        """, (telegram_group_id,))

        row = cur.fetchone()


    return row[0] if row else None


def count_group_owner_groups(user_id, exclude_group_id=None):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(DISTINCT group_id)
            FROM admins
            WHERE user_id=%s
            AND role=%s
            AND group_id IS NOT NULL
            AND group_id != 0
            AND is_active=TRUE
            AND (%s IS NULL OR group_id != %s)

        """, (
            user_id,
            GROUP_OWNER,
            exclude_group_id,
            exclude_group_id
        ))

        return cur.fetchone()[0] or 0


def creator_has_capacity(user_id, max_groups_allowed, group_id=None):

    current_groups = count_group_owner_groups(
        user_id,
        exclude_group_id=group_id
    )

    return current_groups < max_groups_allowed


async def safe_send(context, chat_id, text):

    if not chat_id:

        return False


    try:

        await context.bot.send_message(
            chat_id=chat_id,
            text=text
        )

        return True

    except Exception as e:

        print("Error enviando mensaje:", e)

        return False


async def leave_chat_safely(context, telegram_group_id):

    try:

        left_group = await context.bot.leave_chat(telegram_group_id)


        if left_group is False:

            raise RuntimeError("Telegram devolvió False en leave_chat")


        print("Bot salió del grupo por validación comercial.")

        return True

    except Exception as e:

        print("Error saliendo del grupo con context.bot.leave_chat:", e)


    try:

        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/leaveChat",
            params={"chat_id": telegram_group_id},
            timeout=10
        ).json()

        print("Respuesta fallback leaveChat:", response)

        return response.get("ok") is True

    except Exception as e:

        print("Error saliendo del grupo con fallback leaveChat:", e)


    return False


async def reject_group_registration(
    context,
    group_id,
    group_name,
    added_by,
    group_message,
    user_message,
    admin_message
):

    await safe_send(
        context,
        group_id,
        group_message
    )

    await safe_send(
        context,
        added_by,
        user_message
    )

    await safe_send(
        context,
        ADMIN_ID,
        (
            admin_message
            + "\n\n"
            + f"Grupo: {group_name}\n"
            + f"ID: {group_id}\n"
            + f"Usuario: {added_by or '-'}"
        )
    )


    left_group = await leave_chat_safely(
        context,
        group_id
    )


    if not left_group:

        await safe_send(
            context,
            ADMIN_ID,
            "⚠️ No se pudo confirmar la salida automática del bot del grupo."
        )


def upsert_group_for_creator(group_name, telegram_group_id, added_by, request_row):

    public_visibility = request_row.get("requested_public_visibility") or "hidden"


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO groups
            (
                name,
                telegram_group_id,
                public_visibility,
                is_free_group,
                bot_is_admin,
                is_active,
                added_by
            )
            VALUES (%s, %s, %s, %s, TRUE, TRUE, %s)
            ON CONFLICT (telegram_group_id)
            DO UPDATE SET
                name=EXCLUDED.name,
                public_visibility=EXCLUDED.public_visibility,
                is_free_group=EXCLUDED.is_free_group,
                bot_is_admin=TRUE,
                is_active=TRUE,
                added_by=EXCLUDED.added_by
            RETURNING id

        """, (
            group_name,
            telegram_group_id,
            public_visibility,
            request_row.get("is_free_group") is True,
            added_by
        ))

        group_id = cur.fetchone()[0]

        cur.execute("""

            UPDATE commercial_requests
            SET approved_group_id=%s,
                approved_telegram_group_id=%s,
                telegram_group_link=%s,
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s

        """, (
            group_id,
            telegram_group_id,
            str(telegram_group_id),
            request_row["id"]
        ))

        cur.execute("""

            UPDATE group_payment_settings
            SET group_id=%s,
                updated_at=NOW()
            WHERE commercial_request_id=%s

        """, (
            group_id,
            request_row["id"]
        ))


    assign_group_owner_permissions(
        added_by,
        group_id
    )

    return group_id


async def register_authorized_group(group_id, group_name, added_by, context, request_row):

    existing_group_id = get_existing_group(group_id)


    if not creator_has_capacity(
        added_by,
        request_row["max_groups_allowed"],
        existing_group_id
    ):

        await reject_group_registration(
            context,
            group_id,
            group_name,
            added_by,
            "⚠️ Has superado el máximo de comunidades permitidas para tu plan actual. El bot saldrá del grupo.",
            "⛔ Has alcanzado el máximo de comunidades permitidas. Para añadir otra comunidad necesitas ampliar tu suscripción o comprar un extra.",
            "⚠️ Bot añadido por creador que superó su cupo de comunidades."
        )

        return


    internal_group_id = upsert_group_for_creator(
        group_name,
        group_id,
        added_by,
        request_row
    )

    await safe_send(
        context,
        added_by,
        (
            "✅ Grupo detectado correctamente.\n\n"
            "ID del grupo:\n"
            f"{group_id}\n\n"
            "Guarda este ID. También puedes usarlo en el panel de configuración de tu comunidad."
        )
    )

    await safe_send(
        context,
        group_id,
        "✅ Bot configurado correctamente para esta comunidad."
    )

    await safe_send(
        context,
        ADMIN_ID,
        (
            "✅ GRUPO COMERCIAL AUTORIZADO\n\n"
            f"Grupo: {group_name}\n"
            f"Telegram ID: {group_id}\n"
            f"ID interno: {internal_group_id}\n"
            f"Owner: {added_by}\n"
            f"Solicitud: #{request_row['id']}"
        )
    )


# =========================
# VERIFICAR ADMIN DESPUÉS DE 30s
# =========================

async def verificar_admin_despues(group_id, group_name, bot_id, context, added_by):

    print("Esperando 30 segundos antes de verificar permisos...")

    await asyncio.sleep(30)

    try:

        print("Verificando permisos del bot...")

        r = requests.get(

            f"https://api.telegram.org/bot{TOKEN}/getChatMember",

            params={

                "chat_id": group_id,
                "user_id": bot_id

            }

        ).json()

        print("Respuesta completa getChatMember:", r)

        status = r["result"]["status"]

        print("Status del bot en grupo:", status)


        if status not in ["administrator", "creator"]:

            print("Bot NO es administrador después de 30s.")

            await reject_group_registration(
                context,
                group_id,
                group_name,
                added_by,
                "⚠️ No tengo permisos de administrador.\n\nSaldré del grupo en este momento.",
                "⚠️ El bot no quedó como administrador del grupo. Añádelo de nuevo con permisos de administrador.",
                "⚠️ BOT SALIENDO DEL GRUPO\n\nNo fue asignado como administrador."
            )

            return

        print(f"Bot ES administrador en grupo: {group_name} ({group_id})")


        if added_by == ADMIN_ID:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO groups
                    (
                        name,
                        telegram_group_id,
                        public_visibility,
                        bot_is_admin,
                        is_active,
                        added_by
                    )
                    VALUES (%s, %s, 'hidden', TRUE, TRUE, %s)
                    ON CONFLICT (telegram_group_id)
                    DO UPDATE SET
                        name=EXCLUDED.name,
                        bot_is_admin=TRUE,
                        is_active=TRUE,
                        added_by=EXCLUDED.added_by

                """, (
                    group_name,
                    group_id,
                    added_by
                ))

            await safe_send(
                context,
                ADMIN_ID,
                (
                    "✅ NUEVO GRUPO DETECTADO\n\n"
                    f"Nombre: {group_name}\n"
                    f"ID: {group_id}\n\n"
                    "Grupo registrado correctamente por el propietario principal."
                )
            )

            return


        request_row = get_approved_creator_request(
            added_by,
            group_id
        )


        if not request_row:

            await reject_group_registration(
                context,
                group_id,
                group_name,
                added_by,
                "⚠️ No tienes una solicitud aprobada para añadir este bot a esta comunidad. El bot saldrá del grupo.",
                "⛔ No tienes aprobado añadir el bot a un grupo. Solicita aprobación desde /start.",
                "⚠️ Bot añadido por usuario no autorizado."
            )

            return


        existing_group_id = get_existing_group(group_id)
        existing_owner_id = get_group_owner_user_id(existing_group_id)


        if existing_owner_id and int(existing_owner_id) != int(added_by):

            await reject_group_registration(
                context,
                group_id,
                group_name,
                added_by,
                "⚠️ Este grupo ya está asociado a otro creador. El bot saldrá del grupo.",
                "⛔ Este grupo ya está asociado a otro creador. Contacta con soporte si crees que es un error.",
                "⚠️ Bot añadido a un grupo ya asociado a otro owner."
            )

            return


        if not can_user_claim_telegram_group(
            added_by,
            group_id,
            request_row["id"]
        ):

            await reject_group_registration(
                context,
                group_id,
                group_name,
                added_by,
                "⚠️ Este grupo ya está vinculado a otra comunidad. El bot saldrá del grupo.",
                "⛔ Este grupo ya está vinculado a otra comunidad. Si crees que es un error, contacta con soporte.",
                "⚠️ Bot añadido a un grupo vinculado a otra comunidad."
            )

            return


        if not creator_has_capacity(
            added_by,
            request_row["max_groups_allowed"],
            existing_group_id
        ):

            await reject_group_registration(
                context,
                group_id,
                group_name,
                added_by,
                "⚠️ Has superado el máximo de comunidades permitidas para tu plan actual. El bot saldrá del grupo.",
                "⛔ Has alcanzado el máximo de comunidades permitidas. Para añadir otra comunidad necesitas ampliar tu suscripción o comprar un extra.",
                "⚠️ Bot añadido por creador que superó su cupo de comunidades."
            )

            return


        await register_authorized_group(
            group_id,
            group_name,
            added_by,
            context,
            request_row
        )


    except Exception as e:

        print("Error verificando grupo:", e)


# =========================
# DETECTAR BOT AÑADIDO A GRUPO
# =========================

async def detect_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("detect_bot_added ejecutado")

    if not update.message:
        return

    if not update.message.new_chat_members:
        return


    bot_id = context.bot.id


    for member in update.message.new_chat_members:


        # =========================
        # SI EL MIEMBRO ES EL BOT
        # =========================

        if member.id == bot_id:

            group_id = update.message.chat.id
            group_name = update.message.chat.title

            print(
                "Bot añadido a grupo:",
                group_name,
                group_id
            )


            try:

                added_by = update.message.from_user.id

            except Exception:

                added_by = None


            print(
                "Bot añadido por usuario:",
                added_by
            )


            # =========================
            # AVISO AL GRUPO
            # =========================

            try:

                await context.bot.send_message(

                    chat_id=group_id,

                    text=

                    "⚠️ Necesito permisos de administrador.\n\n"

                    "Por favor asígnamelos en los próximos 30 segundos.\n\n"

                    "Si no, abandonaré el grupo automáticamente."

                )

            except Exception as e:

                print(
                    "Error enviando aviso al grupo:",
                    e
                )


            # =========================
            # VERIFICAR ADMIN DESPUÉS
            # =========================

            asyncio.create_task(

                verificar_admin_despues(

                    group_id,

                    group_name,

                    bot_id,

                    context,

                    added_by

                )

            )

            return
