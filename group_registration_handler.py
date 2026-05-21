import asyncio
import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from bot_config import TOKEN, ADMIN_ID
from db import conn
from rbac_helpers import (
    GROUP_OWNER,
    assign_group_owner_permissions,
    can_user_claim_telegram_group,
    get_group_owner_user_id,
    is_super_admin
)


APPROVED_COMMERCIAL_STATUSES = (
    "approved",
    "trial_active",
    "awaiting_creator_setup",
    "awaiting_payment_setup",
    "setup_in_progress",
    "setup_ready",
    "active",
    "expired_pending_reactivation"
)


AUTHORIZED_CREATOR_SETUP_STATUSES = (
    "awaiting_creator_setup",
    "setup_in_progress",
    "setup_ready"
)


BLOCKED_CREATOR_STATUSES = (
    "pending",
    "rejected",
    "archived",
    "closed",
    "trial_expired",
    "deleted_irreversible"
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

        conn.commit()


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

    if is_super_admin(user_id):

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   approved_group_id,
                   approved_telegram_group_id,
                   requested_public_visibility,
                   COALESCE(max_groups_allowed, 1),
                   COALESCE(is_free_group, FALSE),
                   payment_mode,
                   creator_setup_status
            FROM commercial_requests
            WHERE user_id=%s
            AND request_type='shared_trial'
            AND (
                status = ANY(%s)
                OR (
                    creator_setup_status = ANY(%s)
                    AND COALESCE(status, 'pending') != ALL(%s)
                )
                OR approved_telegram_group_id=%s
            )
            ORDER BY
                CASE
                    WHEN approved_telegram_group_id=%s THEN 0
                    WHEN approved_group_id IS NULL THEN 1
                    ELSE 2
                END ASC,
                COALESCE(max_groups_allowed, 1) DESC,
                reviewed_at DESC NULLS LAST,
                created_at DESC
            LIMIT 1

        """, (
            user_id,
            list(APPROVED_COMMERCIAL_STATUSES),
            list(AUTHORIZED_CREATOR_SETUP_STATUSES),
            list(BLOCKED_CREATOR_STATUSES),
            telegram_group_id,
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


def get_commercial_request_identity_summary(user_id):

    if not user_id:

        return "sin user_id"


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   status,
                   creator_setup_status,
                   approved_group_id,
                   approved_telegram_group_id,
                   username,
                   first_name,
                   created_at
            FROM commercial_requests
            WHERE user_id=%s
            ORDER BY created_at DESC
            LIMIT 3

        """, (user_id,))

        rows = cur.fetchall()


    if not rows:

        return "sin solicitudes comerciales para este user_id"


    parts = []

    for row in rows:

        parts.append(
            "#{} status={} setup={} group={} telegram_group={} username={} first_name={} created_at={}".format(
                row[0],
                row[1] or "-",
                row[2] or "-",
                row[3] or "-",
                row[4] or "-",
                row[5] or "-",
                row[6] or "-",
                row[7] or "-"
            )
        )


    return " | ".join(parts)


def find_unlinked_owner_request_for_confirmation():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   user_id,
                   approved_group_id,
                   approved_telegram_group_id,
                   requested_public_visibility,
                   COALESCE(max_groups_allowed, 1),
                   COALESCE(is_free_group, FALSE),
                   payment_mode,
                   username,
                   first_name,
                   status,
                   creator_setup_status,
                   created_at
            FROM commercial_requests
            WHERE request_type='shared_trial'
            AND approved_group_id IS NULL
            AND approved_telegram_group_id IS NULL
            AND (
                status = ANY(%s)
                OR (
                    creator_setup_status = ANY(%s)
                    AND COALESCE(status, 'pending') != ALL(%s)
                )
            )
            ORDER BY reviewed_at DESC NULLS LAST,
                     updated_at DESC NULLS LAST,
                     created_at DESC
            LIMIT 2

        """, (
            list(APPROVED_COMMERCIAL_STATUSES),
            list(AUTHORIZED_CREATOR_SETUP_STATUSES),
            list(BLOCKED_CREATOR_STATUSES)
        ))

        rows = cur.fetchall()


    if len(rows) != 1:

        return None, len(rows)


    row = rows[0]

    return {
        "id": row[0],
        "user_id": row[1],
        "approved_group_id": row[2],
        "approved_telegram_group_id": row[3],
        "requested_public_visibility": row[4],
        "max_groups_allowed": row[5] or 1,
        "is_free_group": row[6] is True or row[7] == "free",
        "username": row[8],
        "first_name": row[9],
        "status": row[10],
        "creator_setup_status": row[11],
        "created_at": row[12]
    }, 1


def get_creator_request_by_id(user_id, request_id):

    if not user_id or not request_id:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   approved_group_id,
                   approved_telegram_group_id,
                   requested_public_visibility,
                   COALESCE(max_groups_allowed, 1),
                   COALESCE(is_free_group, FALSE),
                   payment_mode,
                   creator_setup_status
            FROM commercial_requests
            WHERE id=%s
            AND user_id=%s
            AND request_type='shared_trial'
            AND (
                status = ANY(%s)
                OR (
                    creator_setup_status = ANY(%s)
                    AND COALESCE(status, 'pending') != ALL(%s)
                )
            )
            LIMIT 1

        """, (
            request_id,
            user_id,
            list(APPROVED_COMMERCIAL_STATUSES),
            list(AUTHORIZED_CREATOR_SETUP_STATUSES),
            list(BLOCKED_CREATOR_STATUSES)
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


def is_authorized_creator(user_id):

    if not user_id:

        return False


    if is_super_admin(user_id):

        return True


    return get_creator_group_quota(user_id) > 0


def get_creator_group_quota(user_id):

    if not user_id:

        return 0


    if is_super_admin(user_id):

        return 999999


    with conn.cursor() as cur:

        cur.execute("""

            SELECT COALESCE(MAX(COALESCE(max_groups_allowed, 1)), 0)
            FROM commercial_requests
            WHERE user_id=%s
            AND request_type='shared_trial'
            AND (
                status = ANY(%s)
                OR (
                    creator_setup_status = ANY(%s)
                    AND COALESCE(status, 'pending') != ALL(%s)
                )
            )

        """, (
            user_id,
            list(APPROVED_COMMERCIAL_STATUSES),
            list(AUTHORIZED_CREATOR_SETUP_STATUSES),
            list(BLOCKED_CREATOR_STATUSES)
        ))

        row = cur.fetchone()


    return row[0] or 0


def get_creator_registered_group_count(user_id, exclude_group_id=None):

    return count_group_owner_groups(
        user_id,
        exclude_group_id=exclude_group_id
    )


def can_creator_add_group(user_id, group_id=None):

    if is_super_admin(user_id):

        return True


    quota = get_creator_group_quota(user_id)


    if quota <= 0:

        return False


    return get_creator_registered_group_count(
        user_id,
        exclude_group_id=group_id
    ) < quota


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

    if is_super_admin(user_id):

        return True


    current_groups = get_creator_registered_group_count(
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


async def safe_send_confirmation(context, chat_id, text, pending_id):

    if not chat_id:

        return False


    try:

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Sí, vincular este grupo",
                    callback_data=f"confirm_creator_group_link_{pending_id}"
                )],
                [InlineKeyboardButton(
                    "❌ No, cancelar",
                    callback_data=f"cancel_creator_group_link_{pending_id}"
                )]
            ])
        )

        return True

    except Exception as e:

        print("Error enviando confirmación de grupo:", e)

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


def create_creator_group_link_request(user_id, request_id, telegram_group_id, group_name):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE creator_group_link_requests
            SET status='cancelled',
                cancelled_at=NOW(),
                updated_at=NOW()
            WHERE user_id=%s
            AND commercial_request_id=%s
            AND telegram_group_id=%s
            AND status='pending'

        """, (
            user_id,
            request_id,
            telegram_group_id
        ))

        cur.execute("""

            INSERT INTO creator_group_link_requests
            (
                user_id,
                commercial_request_id,
                telegram_group_id,
                group_name,
                status
            )
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING id

        """, (
            user_id,
            request_id,
            telegram_group_id,
            group_name
        ))

        pending_id = cur.fetchone()[0]


    return pending_id


def fetch_creator_group_link_request(pending_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   user_id,
                   commercial_request_id,
                   telegram_group_id,
                   group_name,
                   status
            FROM creator_group_link_requests
            WHERE id=%s
            LIMIT 1

        """, (pending_id,))

        row = cur.fetchone()


    if not row:

        return None


    return {
        "id": row[0],
        "user_id": row[1],
        "commercial_request_id": row[2],
        "telegram_group_id": row[3],
        "group_name": row[4],
        "status": row[5]
    }


def mark_creator_group_link_request(pending_id, status):

    status_column = "confirmed_at" if status == "confirmed" else "cancelled_at"


    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE creator_group_link_requests
            SET status=%s,
                {status_column}=NOW(),
                updated_at=NOW()
            WHERE id=%s

        """, (
            status,
            pending_id
        ))


def confirm_creator_group_link_request(pending_id, user_id):

    pending_row = fetch_creator_group_link_request(pending_id)


    if not pending_row:

        return {"status": "not_found"}


    if int(pending_row["user_id"]) != int(user_id):

        return {"status": "not_owner"}


    if pending_row["status"] != "pending":

        return {
            "status": "not_pending",
            "pending_status": pending_row["status"]
        }


    telegram_group_id = pending_row["telegram_group_id"]
    internal_group_id = get_existing_group(telegram_group_id)
    existing_owner_id = get_group_owner_user_id(internal_group_id)


    if existing_owner_id and int(existing_owner_id) != int(user_id):

        return {"status": "owned_by_other"}


    request_row = get_creator_request_by_id(
        user_id,
        pending_row["commercial_request_id"]
    )


    if not request_row:

        return {"status": "no_request"}


    if not can_user_claim_telegram_group(
        user_id,
        telegram_group_id,
        request_row["id"]
    ):

        return {"status": "owned_by_other"}


    if not can_creator_add_group(
        user_id,
        internal_group_id
    ):

        return {"status": "no_capacity"}


    linked_group_id = upsert_group_for_creator(
        pending_row["group_name"],
        telegram_group_id,
        user_id,
        request_row
    )

    mark_creator_group_link_request(
        pending_id,
        "confirmed"
    )

    return {
        "status": "confirmed",
        "group_id": linked_group_id,
        "telegram_group_id": telegram_group_id,
        "group_name": pending_row["group_name"],
        "request_id": request_row["id"]
    }


def cancel_creator_group_link_request(pending_id, user_id):

    pending_row = fetch_creator_group_link_request(pending_id)


    if not pending_row:

        return {"status": "not_found"}


    if int(pending_row["user_id"]) != int(user_id):

        return {"status": "not_owner"}


    if pending_row["status"] != "pending":

        return {
            "status": "not_pending",
            "pending_status": pending_row["status"]
        }


    mark_creator_group_link_request(
        pending_id,
        "cancelled"
    )

    return {
        "status": "cancelled",
        "telegram_group_id": pending_row["telegram_group_id"],
        "group_name": pending_row["group_name"]
    }


async def reject_group_registration(
    context,
    group_id,
    group_name,
    added_by,
    group_message,
    user_message,
    admin_message,
    added_by_username=None,
    added_by_first_name=None
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
            + f"Usuario: {added_by or '-'}\n"
            + f"Username: {('@' + added_by_username) if added_by_username else '-'}\n"
            + f"Nombre: {added_by_first_name or '-'}\n"
            + f"Solicitudes del user_id: {get_commercial_request_identity_summary(added_by)}"
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


    if not can_creator_add_group(
        added_by,
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


async def register_existing_owned_group(group_id, group_name, added_by, context, internal_group_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE groups
            SET name=%s,
                bot_is_admin=TRUE,
                is_active=TRUE,
                added_by=%s
            WHERE id=%s

        """, (
            group_name,
            added_by,
            internal_group_id
        ))


    await safe_send(
        context,
        added_by,
        (
            "✅ Este grupo ya está vinculado a tu comunidad.\n\n"
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
            "✅ GRUPO COMERCIAL EXISTENTE VERIFICADO\n\n"
            f"Grupo: {group_name}\n"
            f"Telegram ID: {group_id}\n"
            f"ID interno: {internal_group_id}\n"
            f"Owner: {added_by}"
        )
    )


# =========================
# VERIFICAR ADMIN DESPUÉS DE 30s
# =========================

async def verificar_admin_despues(
    group_id,
    group_name,
    bot_id,
    context,
    added_by,
    added_by_username=None,
    added_by_first_name=None
):

    print(
        "group_registration_verify_start:",
        f"chat.id={group_id}",
        f"chat.title={group_name or '-'}",
        f"added_by={added_by or '-'}",
        f"username={added_by_username or '-'}",
        f"first_name={added_by_first_name or '-'}"
    )

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


        if added_by and is_super_admin(added_by):

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


        existing_group_id = get_existing_group(group_id)
        existing_owner_id = get_group_owner_user_id(existing_group_id)


        if added_by and existing_owner_id and int(existing_owner_id) == int(added_by):

            await register_existing_owned_group(
                group_id,
                group_name,
                added_by,
                context,
                existing_group_id
            )

            return


        if added_by and existing_owner_id and int(existing_owner_id) != int(added_by):

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


        if not is_authorized_creator(added_by):

            owner_request, candidate_count = find_unlinked_owner_request_for_confirmation()


            if owner_request and can_user_claim_telegram_group(
                owner_request["user_id"],
                group_id,
                owner_request["id"]
            ) and can_creator_add_group(
                owner_request["user_id"],
                existing_group_id
            ):

                pending_id = create_creator_group_link_request(
                    owner_request["user_id"],
                    owner_request["id"],
                    group_id,
                    group_name
                )

                confirmation_sent = await safe_send_confirmation(
                    context,
                    owner_request["user_id"],
                    (
                        "✅ He detectado un grupo pendiente de vinculación:\n\n"
                        f"Nombre: {group_name}\n"
                        f"ID: {group_id}\n\n"
                        "Lo añadió otra cuenta o Telegram reportó otro user_id:\n"
                        f"Usuario detectado: {added_by or '-'}\n"
                        f"Username detectado: {('@' + added_by_username) if added_by_username else '-'}\n"
                        f"Nombre detectado: {added_by_first_name or '-'}\n\n"
                        "¿Quieres vincular este grupo a tu comunidad?"
                    ),
                    pending_id
                )

                await safe_send(
                    context,
                    group_id,
                    (
                        "✅ Bot detectado correctamente.\n\n"
                        "El propietario aprobado debe confirmar la vinculación por privado."
                    )
                )

                await safe_send(
                    context,
                    ADMIN_ID,
                    (
                        "📡 GRUPO COMERCIAL PENDIENTE DE CONFIRMACIÓN POR OWNER\n\n"
                        f"Grupo: {group_name}\n"
                        f"Telegram ID: {group_id}\n"
                        f"Usuario que añadió el bot: {added_by or '-'}\n"
                        f"Username: {('@' + added_by_username) if added_by_username else '-'}\n"
                        f"Nombre: {added_by_first_name or '-'}\n"
                        f"Solicitud owner: #{owner_request['id']}\n"
                        f"Owner user_id: {owner_request['user_id']}\n"
                        f"Owner username: {owner_request.get('username') or '-'}\n"
                        f"Owner first_name: {owner_request.get('first_name') or '-'}\n"
                        f"Solicitudes del added_by: {get_commercial_request_identity_summary(added_by)}\n"
                        f"Confirmación enviada: {'sí' if confirmation_sent else 'no'}"
                    )
                )

                print(
                    "group_registration_owner_confirmation_fallback:",
                    f"chat.id={group_id}",
                    f"added_by={added_by or '-'}",
                    f"owner_user_id={owner_request['user_id']}",
                    f"request_id={owner_request['id']}",
                    f"confirmation_sent={confirmation_sent}"
                )

                return


            print(
                "group_registration_unauthorized:",
                f"chat.id={group_id}",
                f"chat.title={group_name or '-'}",
                f"added_by={added_by or '-'}",
                f"username={added_by_username or '-'}",
                f"first_name={added_by_first_name or '-'}",
                f"commercial_requests.user_id={get_commercial_request_identity_summary(added_by)}",
                f"unlinked_owner_candidate_count={candidate_count}"
            )

            await reject_group_registration(
                context,
                group_id,
                group_name,
                added_by,
                "⚠️ No tienes una solicitud aprobada para añadir este bot a esta comunidad. El bot saldrá del grupo.",
                "⛔ No tienes aprobado añadir el bot a un grupo. Solicita aprobación desde /start.",
                (
                    "⚠️ Bot añadido por usuario no autorizado.\n"
                    f"Solicitudes pendientes/vinculables de otro user_id: {candidate_count}"
                ),
                added_by_username,
                added_by_first_name
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
                "⚠️ No se encontró una solicitud comercial vigente para vincular este grupo. El bot saldrá del grupo.",
                "⛔ No he encontrado una solicitud comercial vigente para vincular este grupo. Revisa tu solicitud desde /start.",
                "⚠️ Bot añadido por creador sin solicitud vinculable."
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


        if not can_creator_add_group(
            added_by,
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


        pending_id = create_creator_group_link_request(
            added_by,
            request_row["id"],
            group_id,
            group_name
        )

        confirmation_sent = await safe_send_confirmation(
            context,
            added_by,
            (
                "✅ He detectado tu grupo:\n\n"
                f"Nombre: {group_name}\n"
                f"ID: {group_id}\n\n"
                "¿Quieres vincular este grupo a tu comunidad?"
            ),
            pending_id
        )

        await safe_send(
            context,
            group_id,
            (
                "✅ Bot detectado correctamente.\n\n"
                "El creador autorizado debe confirmar la vinculación por privado."
            )
        )

        await safe_send(
            context,
            ADMIN_ID,
            (
                "📡 GRUPO COMERCIAL PENDIENTE DE CONFIRMACIÓN\n\n"
                f"Grupo: {group_name}\n"
                f"Telegram ID: {group_id}\n"
                f"Creator: {added_by}\n"
                f"Solicitud: #{request_row['id']}\n"
                f"Confirmación enviada: {'sí' if confirmation_sent else 'no'}"
            )
        )


    except Exception as e:

        print("Error verificando grupo:", e)


# =========================
# DETECTAR BOT AÑADIDO A GRUPO
# =========================

async def detect_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):

    effective_user = update.effective_user

    print(
        "detect_bot_added ejecutado",
        f"effective_user.id={effective_user.id if effective_user else '-'}",
        f"username={effective_user.username if effective_user and effective_user.username else '-'}",
        f"first_name={effective_user.first_name if effective_user and effective_user.first_name else '-'}",
        f"chat.id={update.effective_chat.id if update.effective_chat else '-'}",
        f"chat.type={update.effective_chat.type if update.effective_chat else '-'}",
        f"chat.title={update.effective_chat.title if update.effective_chat else '-'}"
    )

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

                added_by_user = update.message.from_user
                added_by = added_by_user.id
                added_by_username = added_by_user.username
                added_by_first_name = added_by_user.first_name

            except Exception:

                added_by = None
                added_by_username = None
                added_by_first_name = None


            print(
                "Bot añadido por usuario:",
                f"update.effective_user.id={effective_user.id if effective_user else '-'}",
                f"update.message.from_user.id={added_by or '-'}",
                f"username={added_by_username or '-'}",
                f"first_name={added_by_first_name or '-'}",
                f"chat.id={group_id}",
                f"chat.title={group_name or '-'}"
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

                    added_by,

                    added_by_username,

                    added_by_first_name

                )

            )

            return
