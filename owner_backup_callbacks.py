"""
Backups del propietario: configuración, copias y envíos.

Tercera fase de partir callback_router.py. Aquí vive el panel de backups del
dueño de una comunidad: crear copias, listarlas, enviarlas, elegir frecuencia,
modo, origen y destino, y ver los últimos mensajes y errores.

Este tramo necesitaba un trato distinto a los dos anteriores. En Guardian y en
los métodos de pago todas las ramas terminaban en return, así que quien llamaba
podía retornar siempre justo después. Aquí no: en medio hay una PUERTA
(old_owner_backup_callbacks) que resuelve la comunidad y comprueba el extra de
pago, retorna si no hay permiso y, si lo hay, cae a propósito hacia las ramas
individuales de abajo. Esa caída intencionada es parte del comportamiento.

Y las condiciones son heterogéneas — hay `data ==`, `data in (...)` y varios
`startswith` —, así que tampoco se podía escribir un guardián que fuese la unión
exacta de unos prefijos, como se hizo con los métodos de pago.

De ahí el centinela NOT_HANDLED: cualquier camino que atienda el botón hace un
`return` normal (que devuelve None), y solo el final de la función —cuando no
encajó nada— devuelve el centinela. Así quien llama distingue los dos casos sin
que haya habido que tocar ni un `return` del código movido.
"""

import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from audit_log_service import log_event
from db import conn
from group_registration_handler import confirm_backup_destination_token
from owner_backup_service import (
    create_owner_backup,
    fetch_owner_backup_file,
    fetch_owner_backups,
    upsert_owner_backup_job
)
from rbac_helpers import get_group_owner_user_id, is_super_admin
from ui_menu_helpers import send_clean_message


# =========================
# CENTINELA DE "NO ATENDIDO"
# =========================
# Un objeto propio, no None ni False: los `return` del código movido devuelven
# None, así que None significa "atendido". Solo el final de la función devuelve
# esto, y solo entonces callback_router sigue evaluando sus ramas.

NOT_HANDLED = object()


# =========================
# AYUDANTES QUE SE QUEDAN EN callback_router
# =========================
# Se usan también fuera de los backups. Se llaman de forma diferida porque
# callback_router importa este módulo: importarlo de vuelta arriba sería una
# importación circular.

def build_owner_backup_addon_required_keyboard(*args, **kwargs):

    from callback_router import build_owner_backup_addon_required_keyboard as impl

    return impl(*args, **kwargs)


def build_owner_backup_addon_required_text(*args, **kwargs):

    from callback_router import build_owner_backup_addon_required_text as impl

    return impl(*args, **kwargs)


def build_owner_backup_panel_keyboard(*args, **kwargs):

    from callback_router import build_owner_backup_panel_keyboard as impl

    return impl(*args, **kwargs)


def build_owner_panel_nav_keyboard(*args, **kwargs):

    from callback_router import build_owner_panel_nav_keyboard as impl

    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):

    from callback_router import extract_commercial_request_id as impl

    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):

    from callback_router import fetch_group_basic_info as impl

    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):

    from callback_router import format_commercial_datetime as impl

    return impl(*args, **kwargs)


def format_owner_backup_file_size(*args, **kwargs):

    from callback_router import format_owner_backup_file_size as impl

    return impl(*args, **kwargs)


def format_owner_backup_frequency(*args, **kwargs):

    from callback_router import format_owner_backup_frequency as impl

    return impl(*args, **kwargs)


def generate_backup_destination_token(*args, **kwargs):

    from callback_router import generate_backup_destination_token as impl

    return impl(*args, **kwargs)


def get_selected_group_for_permissions(*args, **kwargs):

    from callback_router import get_selected_group_for_permissions as impl

    return impl(*args, **kwargs)


def log_owner_backup_addon_gate(*args, **kwargs):

    from callback_router import log_owner_backup_addon_gate as impl

    return impl(*args, **kwargs)


def owner_can_use_backups(*args, **kwargs):

    from callback_router import owner_can_use_backups as impl

    return impl(*args, **kwargs)



# =========================
# TEXTOS, TECLADOS Y CONSULTAS DE BACKUPS
# =========================

def backup_group_by_id(groups, group_id):

    for group in groups:

        if int(group[0]) == int(group_id):

            return group


    return None


def build_backup_config_select_keyboard(configs, prefix, back_callback="owner_backup_panel"):

    keyboard = []


    for config in configs:

        (
            config_id,
            status,
            mode,
            source_name,
            destination_name,
            _last_message_at,
            _source_group_id,
            _destination_group_id,
            _show_original_author
        ) = config

        keyboard.append([
            InlineKeyboardButton(
                f"#{config_id} · {source_name or '-'} → {destination_name or '-'} · {format_backup_mode(mode)} · {status or 'inactive'}",
                callback_data=f"{prefix}{config_id}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)


def build_backup_group_select_keyboard(groups, prefix, back_callback="owner_backup_panel"):

    keyboard = []


    for group_id, name, _telegram_group_id, bot_is_admin in groups:

        label = name or f"Grupo {group_id}"


        if not bot_is_admin:

            label += " · bot sin admin"


        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"{prefix}{group_id}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=back_callback)])

    return InlineKeyboardMarkup(keyboard)


def build_backup_mode_keyboard(config_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Solo texto", callback_data=f"owner_backup_set_mode_{config_id}_text")],
        [InlineKeyboardButton("Texto + fotos", callback_data=f"owner_backup_set_mode_{config_id}_text_photos")],
        [InlineKeyboardButton("Texto + fotos + vídeos", callback_data=f"owner_backup_set_mode_{config_id}_text_photos_videos")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="owner_backup_panel")]
    ])


def build_backup_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Activar backup", callback_data="owner_backup_activate")],
        [InlineKeyboardButton("⏸ Pausar backup", callback_data="owner_backup_pause")],
        [InlineKeyboardButton("⚙️ Cambiar modo", callback_data="owner_backup_change_mode")],
        [InlineKeyboardButton("🔗 Vincular grupo destino con código", callback_data="owner_backup_destination_token")],
        [InlineKeyboardButton("👤 Mostrar autor original", callback_data="owner_backup_toggle_author")],
        [InlineKeyboardButton("🔁 Cambiar destino", callback_data="owner_backup_change_destination")],
        [InlineKeyboardButton("⚠️ Últimos errores", callback_data="owner_backup_errors")],
        [InlineKeyboardButton("📜 Últimos mensajes copiados", callback_data="owner_backup_messages")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


def build_owner_backup_created_text(backup):

    return (
        "✅ Backup creado correctamente.\n\n"
        f"ID: #{backup.get('id')}\n"
        f"Tipo: {backup.get('backup_type') or '-'}\n"
        f"Tamaño: {format_owner_backup_file_size(backup.get('file_size_bytes'))}\n"
        f"Fecha: {format_commercial_datetime(backup.get('created_at'))}\n\n"
        f"{backup.get('summary') or ''}"
    )


def build_owner_backup_frequency_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Manual", callback_data="owner_backup_freq_manual")],
        [InlineKeyboardButton("Diario", callback_data="owner_backup_freq_daily")],
        [InlineKeyboardButton("Semanal", callback_data="owner_backup_freq_weekly")],
        [InlineKeyboardButton("Mensual", callback_data="owner_backup_freq_monthly")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="owner_panel_backup")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_backup_list_keyboard(owner_user_id, group_id):

    rows = fetch_owner_backups(owner_user_id, group_id, limit=10)
    keyboard = []

    for backup in rows:

        keyboard.append([
            InlineKeyboardButton(
                f"Ver backup #{backup.get('id')}",
                callback_data=f"owner_backup_view_{backup.get('id')}"
            )
        ])

    keyboard.extend([
        [InlineKeyboardButton("📥 Crear backup ahora", callback_data="owner_backup_create")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="owner_panel_backup")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_owner_backup_list_text(owner_user_id, group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    rows = fetch_owner_backups(owner_user_id, group_id, limit=10)

    if not rows:

        return (
            "📚 Últimos backups\n\n"
            f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
            "Todavía no hay backups creados para esta comunidad."
        )

    lines = [
        "📚 Últimos backups",
        "",
        f"Comunidad: {group_name or f'Grupo {group_id}'}",
        ""
    ]

    for backup in rows:

        lines.append(
            f"#{backup.get('id')} · {backup.get('backup_type') or '-'} · "
            f"{backup.get('status') or '-'} · "
            f"{format_owner_backup_file_size(backup.get('file_size_bytes'))} · "
            f"{format_commercial_datetime(backup.get('created_at'))}"
        )

    return "\n".join(lines)


def build_owner_backup_view_keyboard(backup_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📎 Enviar archivo", callback_data=f"owner_backup_send_{backup_id}")],
        [InlineKeyboardButton("⬅️ Backups", callback_data="owner_backup_list")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_backup_view_text(backup):

    return (
        "📦 Detalle de backup\n\n"
        f"ID: #{backup.get('id')}\n"
        f"Grupo: {backup.get('group_id')}\n"
        f"Tipo: {backup.get('backup_type') or '-'}\n"
        f"Estado: {backup.get('status') or '-'}\n"
        f"Formato: {backup.get('file_format') or '-'}\n"
        f"Tamaño: {format_owner_backup_file_size(backup.get('file_size_bytes'))}\n"
        f"Creado: {format_commercial_datetime(backup.get('created_at'))}\n\n"
        f"{backup.get('summary') or ''}"
    )


def create_backup_destination_token(owner_user_id, source_group_id, source_telegram_group_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE backup_destination_tokens
            SET status='expired',
                updated_at=NOW()
            WHERE owner_user_id=%s
            AND source_group_id=%s
            AND status='pending'

        """, (
            owner_user_id,
            source_group_id
        ))


        for _attempt in range(5):

            token = generate_backup_destination_token()

            try:

                cur.execute("""

                    INSERT INTO backup_destination_tokens
                    (
                        token,
                        owner_user_id,
                        source_group_id,
                        source_telegram_group_id,
                        status,
                        expires_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, 'pending', NOW() + INTERVAL '24 hours', NOW())
                    RETURNING id, token, expires_at

                """, (
                    token,
                    owner_user_id,
                    source_group_id,
                    source_telegram_group_id
                ))

                row = cur.fetchone()
                conn.commit()

                return row

            except Exception:

                conn.rollback()


    return None


def fetch_backup_config(config_id, user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   owner_user_id,
                   source_group_id,
                   source_telegram_group_id,
                   destination_group_id,
                   destination_telegram_group_id,
                   mode,
                   status,
                   COALESCE(show_original_author, FALSE)
            FROM group_backup_configs
            WHERE id=%s
            AND owner_user_id=%s
            LIMIT 1

        """, (
            config_id,
            user_id
        ))

        return cur.fetchone()


def fetch_backup_owner_groups(user_id):

    with conn.cursor() as cur:

        if is_super_admin(user_id):

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       COALESCE(bot_is_admin, FALSE)
                FROM groups
                WHERE telegram_group_id IS NOT NULL
                AND telegram_group_id != 0
                AND COALESCE(is_active, TRUE)=TRUE
                ORDER BY name ASC NULLS LAST,
                         id ASC

            """)

        else:

            cur.execute("""

                SELECT g.id,
                       g.name,
                       g.telegram_group_id,
                       COALESCE(g.bot_is_admin, FALSE)
                FROM admins a
                JOIN groups g
                ON g.id = a.group_id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                AND g.telegram_group_id IS NOT NULL
                AND g.telegram_group_id != 0
                AND COALESCE(g.is_active, TRUE)=TRUE
                ORDER BY g.name ASC NULLS LAST,
                         g.id ASC

            """, (user_id,))


        return cur.fetchall()


def fetch_backup_recent_errors(user_id, limit=20):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT e.created_at,
                   e.severity,
                   e.error_type,
                   e.message
            FROM backup_errors e
            WHERE e.owner_user_id=%s
            ORDER BY e.created_at DESC
            LIMIT %s

        """, (
            user_id,
            limit
        ))

        return cur.fetchall()


def fetch_backup_recent_messages(user_id, limit=20):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT l.created_at,
                   sg.name,
                   dg.name,
                   l.source_message_id,
                   l.destination_message_id,
                   l.message_type,
                   l.status
            FROM backup_message_log l
            JOIN group_backup_configs c
            ON c.id = l.config_id
            LEFT JOIN groups sg
            ON sg.id = l.source_group_id
            LEFT JOIN groups dg
            ON dg.id = l.destination_group_id
            WHERE c.owner_user_id=%s
            ORDER BY l.created_at DESC
            LIMIT %s

        """, (
            user_id,
            limit
        ))

        return cur.fetchall()


def fetch_owner_backup_configs(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT c.id,
                   c.status,
                   c.mode,
                   sg.name,
                   dg.name,
                   c.last_message_at,
                   c.source_group_id,
                   c.destination_group_id,
                   COALESCE(c.show_original_author, FALSE)
            FROM group_backup_configs c
            LEFT JOIN groups sg
            ON sg.id = c.source_group_id
            LEFT JOIN groups dg
            ON dg.id = c.destination_group_id
            WHERE c.owner_user_id=%s
            ORDER BY c.updated_at DESC,
                     c.created_at DESC

        """, (user_id,))

        return cur.fetchall()


def format_backup_mode(mode):

    if mode == "text_photos":

        return "Texto + fotos"


    if mode == "text_photos_videos":

        return "Texto + fotos + vídeos"


    return "Solo texto"


def format_backup_panel_text(user_id):

    configs = fetch_owner_backup_configs(user_id)


    if not configs:

        return (
            "🛡 Backup premium\n\n"
            "Estado: sin configurar\n"
            "Modo disponible: texto\n\n"
            "Selecciona un grupo origen y un grupo destino para copiar "
            "mensajes de texto nuevos que el bot reciba."
        )


    text = "🛡 Backup premium\n\n"


    for config in configs[:3]:

        (
            config_id,
            status,
            mode,
            source_name,
            destination_name,
            last_message_at,
            _source_group_id,
            _destination_group_id,
            show_original_author
        ) = config

        text += (
            f"Config #{config_id}\n"
            f"Estado: {status or 'inactive'}\n"
            f"Origen: {source_name or '-'}\n"
            f"Destino: {destination_name or '-'}\n"
            f"Modo: {format_backup_mode(mode)}\n"
            f"Mostrar autor original: {'Activado' if show_original_author else 'Desactivado'}\n"
            f"Último mensaje copiado: {last_message_at or '-'}\n\n"
        )


    return text


def resolve_owner_backup_context(context, user_id):

    group_id = get_selected_group_for_permissions(
        context,
        user_id,
        ["can_manage_groups"]
    )

    if not group_id:

        return None, None

    owner_user_id = get_group_owner_user_id(group_id) or user_id

    return owner_user_id, group_id


async def send_owner_backup_document(context, chat_id, backup):

    file_path = backup.get("file_path") if backup else None

    if not file_path or not os.path.exists(file_path):

        return False

    try:

        with open(file_path, "rb") as backup_file:

            await context.bot.send_document(
                chat_id=chat_id,
                document=backup_file,
                filename=os.path.basename(file_path),
                caption=f"📎 Backup #{backup.get('id')} · {format_owner_backup_file_size(backup.get('file_size_bytes'))}"
            )

    except Exception:

        return False

    return True


# =========================
# DESPACHO
# =========================

async def handle_owner_backup_callbacks(update, context, query, user_id, data):
    """
    Atiende los botones de backups del propietario.

    Devuelve NOT_HANDLED si ningún caso encajó; en cualquier otro caso el botón
    quedó atendido y quien llama debe retornar.
    """

    if data in (
        "owner_backup_create",
        "owner_backup_list",
        "owner_backup_frequency"
    ) or data.startswith("owner_backup_freq_"):

        owner_user_id, group_id = resolve_owner_backup_context(context, user_id)

        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido resolver la comunidad para gestionar backups.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        allowed, owner_user_id = owner_can_use_backups(user_id, group_id)

        if not allowed:

            log_owner_backup_addon_gate(
                "owner_backup_addon_required",
                user_id,
                owner_user_id,
                group_id,
                data
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_backup_addon_required_text(group_id),
                reply_markup=build_owner_backup_addon_required_keyboard()
            )

            return


        if data == "owner_backup_create":

            log_owner_backup_addon_gate(
                "owner_backup_addon_allowed",
                user_id,
                owner_user_id,
                group_id,
                data
            )

            try:

                backup = create_owner_backup(
                    owner_user_id,
                    group_id,
                    backup_type="manual"
                )

                log_event(
                    "owner_backup_created",
                    category="backup",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Backup manual creado.",
                    metadata={
                        "owner_user_id": owner_user_id,
                        "group_id": group_id,
                        "backup_id": backup.get("id"),
                        "file_size_bytes": backup.get("file_size_bytes")
                    }
                )

            except Exception as e:

                try:

                    conn.rollback()

                except Exception:

                    pass

                log_event(
                    "owner_backup_failed",
                    category="backup",
                    severity="error",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Error creando backup manual.",
                    metadata={
                        "owner_user_id": owner_user_id,
                        "group_id": group_id,
                        "error": str(e)[:300]
                    }
                )

                await query.message.reply_text(
                    f"❌ No he podido crear el backup: {str(e)[:300]}",
                    reply_markup=build_owner_backup_panel_keyboard(group_id)
                )

                return


            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_backup_created_text(backup),
                reply_markup=build_owner_backup_view_keyboard(backup.get("id"))
            )

            if await send_owner_backup_document(context, query.message.chat_id, backup):

                log_event(
                    "owner_backup_file_sent",
                    category="backup",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Archivo de backup enviado.",
                    metadata={
                        "owner_user_id": owner_user_id,
                        "group_id": group_id,
                        "backup_id": backup.get("id"),
                        "file_size_bytes": backup.get("file_size_bytes")
                    }
                )

            return


        if data == "owner_backup_list":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_backup_list_text(owner_user_id, group_id),
                reply_markup=build_owner_backup_list_keyboard(owner_user_id, group_id)
            )

            return


        if data == "owner_backup_frequency":

            await send_clean_message(
                context,
                query.message.chat_id,
                "⚙️ Configurar frecuencia de backup\n\nElige cada cuánto quieres crear backups automáticos para esta comunidad.",
                reply_markup=build_owner_backup_frequency_keyboard()
            )

            return


        if data.startswith("owner_backup_freq_"):

            frequency = data.replace("owner_backup_freq_", "", 1)

            if frequency not in ("manual", "daily", "weekly", "monthly"):

                await query.message.reply_text("❌ Frecuencia de backup no válida.")
                return


            # Sin propietario resuelto la inserción rompe la restricción NOT NULL
            # y el usuario solo veía un error genérico al elegir frecuencia.
            if not owner_user_id:

                await query.message.reply_text(
                    "⚠️ Esta comunidad no tiene un propietario registrado, "
                    "así que todavía no puedo programar sus backups.\n\n"
                    "Asigna el propietario del grupo y vuelve a intentarlo.",
                    reply_markup=build_owner_panel_nav_keyboard()
                )

                return


            job = upsert_owner_backup_job(owner_user_id, group_id, frequency)

            log_owner_backup_addon_gate(
                "owner_backup_addon_allowed",
                user_id,
                owner_user_id,
                group_id,
                data
            )

            log_event(
                "owner_backup_frequency_updated",
                category="backup",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                target_user_id=owner_user_id,
                message="Frecuencia de backup actualizada.",
                metadata={
                    "owner_user_id": owner_user_id,
                    "group_id": group_id,
                    "job_id": job.get("id"),
                    "frequency": job.get("frequency"),
                    "is_active": job.get("is_active")
                }
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                "✅ Frecuencia actualizada.\n\n"
                f"Frecuencia: {format_owner_backup_frequency(job.get('frequency'))}\n"
                f"Automático: {'Sí' if job.get('is_active') else 'No'}\n"
                f"Próximo backup: {format_commercial_datetime(job.get('next_run_at'))}",
                reply_markup=build_owner_backup_panel_keyboard(group_id)
            )

            return


    if data.startswith("owner_backup_view_") or data.startswith("owner_backup_send_"):

        is_send = data.startswith("owner_backup_send_")
        prefix = "owner_backup_send_" if is_send else "owner_backup_view_"
        backup_id = extract_commercial_request_id(data, prefix)
        backup = fetch_owner_backup_file(backup_id)

        if not backup:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver este backup.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = backup.get("group_id")
        context.user_data["selected_owner_group"] = backup.get("group_id")

        allowed, owner_user_id = owner_can_use_backups(user_id, backup.get("group_id"))

        if not allowed:

            log_owner_backup_addon_gate(
                "owner_backup_addon_required",
                user_id,
                owner_user_id,
                backup.get("group_id"),
                data
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_backup_addon_required_text(backup.get("group_id")),
                reply_markup=build_owner_backup_addon_required_keyboard()
            )

            return


        if not is_send:

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_backup_view_text(backup),
                reply_markup=build_owner_backup_view_keyboard(backup_id)
            )

            return


        if not await send_owner_backup_document(context, query.message.chat_id, backup):

            await query.message.reply_text(
                "⚠️ El archivo ya no está disponible en almacenamiento temporal.",
                reply_markup=build_owner_backup_view_keyboard(backup_id)
            )

            return


        log_owner_backup_addon_gate(
            "owner_backup_addon_allowed",
            user_id,
            owner_user_id,
            backup.get("group_id"),
            data
        )

        log_event(
            "owner_backup_file_sent",
            category="backup",
            severity="info",
            scope="group",
            group_id=backup.get("group_id"),
            actor_user_id=user_id,
            target_user_id=backup.get("owner_user_id"),
            message="Archivo de backup enviado.",
            metadata={
                "owner_user_id": backup.get("owner_user_id"),
                "group_id": backup.get("group_id"),
                "backup_id": backup.get("id"),
                "file_size_bytes": backup.get("file_size_bytes")
            }
        )

        return


    old_owner_backup_callbacks = (
        data == "owner_backup_panel"
        or data in (
            "owner_backup_activate",
            "owner_backup_change_destination",
            "owner_backup_destination_token",
            "owner_backup_change_mode",
            "owner_backup_toggle_author",
            "owner_backup_pause",
            "owner_backup_messages",
            "owner_backup_errors"
        )
        or data.startswith("owner_backup_mode_config_")
        or data.startswith("owner_backup_set_mode_")
        or data.startswith("owner_backup_author_config_")
        or data.startswith("owner_backup_confirm_destination_")
        or data.startswith("owner_backup_source_")
        or data.startswith("owner_backup_dest_")
    )

    if old_owner_backup_callbacks:

        _backup_owner_user_id, backup_group_id = resolve_owner_backup_context(context, user_id)

        if not backup_group_id:

            await query.message.reply_text(
                "⚠️ No he podido resolver la comunidad para gestionar backups.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        allowed, backup_owner_user_id = owner_can_use_backups(user_id, backup_group_id)

        if not allowed:

            log_owner_backup_addon_gate(
                "owner_backup_addon_required",
                user_id,
                backup_owner_user_id,
                backup_group_id,
                data
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_backup_addon_required_text(backup_group_id),
                reply_markup=build_owner_backup_addon_required_keyboard()
            )

            return


        if data in (
            "owner_backup_panel",
            "owner_backup_activate",
            "owner_backup_destination_token",
            "owner_backup_change_mode",
            "owner_backup_pause"
        ):

            log_owner_backup_addon_gate(
                "owner_backup_addon_allowed",
                user_id,
                backup_owner_user_id,
                backup_group_id,
                data
            )


    if data == "owner_backup_panel":

        groups = fetch_backup_owner_groups(user_id)


        if not groups:

            await query.message.reply_text(
                "⛔ No tienes grupos propios con permisos para configurar backup."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            format_backup_panel_text(user_id),
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data in (
        "owner_backup_activate",
        "owner_backup_change_destination",
        "owner_backup_destination_token"
    ):

        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]


        if not groups:

            await query.message.reply_text(
                "⚠️ Necesitas al menos un grupo origen propio con el bot añadido como administrador.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🛡 Backup premium\n\nSelecciona el grupo origen. Después generaré un código para vincular el grupo destino.",
            reply_markup=build_backup_group_select_keyboard(
                groups,
                "owner_backup_source_"
            )
        )

        return


    if data == "owner_backup_change_mode":

        configs = fetch_owner_backup_configs(user_id)


        if not configs:

            await query.message.reply_text(
                "⚠️ No tienes ninguna configuración de backup activa para cambiar el modo.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚙️ Cambiar modo de backup\n\n"
            "Solo texto copia mensajes de texto.\n"
            "Texto + fotos copia texto, captions y fotos nuevas sin descargar archivos.\n"
            "Texto + fotos + vídeos añade vídeos nuevos usando Telegram, sin descargar archivos.",
            reply_markup=build_backup_config_select_keyboard(
                configs,
                "owner_backup_mode_config_"
            )
        )

        return


    if data.startswith("owner_backup_mode_config_"):

        try:

            config_id = int(
                data.replace("owner_backup_mode_config_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚙️ Elige el modo de backup\n\n"
            "Solo texto: copia únicamente mensajes de texto.\n"
            "Texto + fotos: copia mensajes de texto, captions y fotos nuevas usando Telegram, sin descargar imágenes.\n"
            "Texto + fotos + vídeos: también copia vídeos nuevos con copy_message, sin guardar binarios.",
            reply_markup=build_backup_mode_keyboard(config_id)
        )

        return


    if data.startswith("owner_backup_set_mode_"):

        try:

            payload = data.replace("owner_backup_set_mode_", "", 1)
            config_id_text, selected_mode = payload.split("_", 1)
            config_id = int(config_id_text)

        except Exception:

            await query.message.reply_text("❌ Modo de backup no válido.")

            return


        if selected_mode not in (
            "text",
            "text_photos",
            "text_photos_videos"
        ):

            await query.message.reply_text("❌ Modo de backup no válido.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET mode=%s,
                    updated_at=NOW()
                WHERE id=%s
                AND owner_user_id=%s

            """, (
                selected_mode,
                config_id,
                user_id
            ))

            conn.commit()


        log_event(
            "backup_mode_changed",
            category="backup",
            severity="info",
            scope="group",
            group_id=config[2],
            telegram_group_id=config[3],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Modo de backup premium actualizado.",
            metadata={
                "config_id": config_id,
                "mode": selected_mode
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Modo de backup actualizado.\n\n"
            f"Modo activo: {format_backup_mode(selected_mode)}",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_toggle_author":

        configs = fetch_owner_backup_configs(user_id)


        if not configs:

            await query.message.reply_text(
                "⚠️ No tienes ninguna configuración de backup para cambiar esta opción.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "👤 Mostrar autor original\n\n"
            "Elige la configuración donde quieres activar o desactivar la atribución.",
            reply_markup=build_backup_config_select_keyboard(
                configs,
                "owner_backup_author_config_"
            )
        )

        return


    if data.startswith("owner_backup_author_config_"):

        try:

            config_id = int(
                data.replace("owner_backup_author_config_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        config = fetch_backup_config(config_id, user_id)


        if not config:

            await query.message.reply_text(
                "⛔ Esta configuración de backup no pertenece a tu panel.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET show_original_author=NOT COALESCE(show_original_author, FALSE),
                    updated_at=NOW()
                WHERE id=%s
                AND owner_user_id=%s
                RETURNING COALESCE(show_original_author, FALSE)

            """, (
                config_id,
                user_id
            ))

            show_original_author = cur.fetchone()[0]
            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Preferencia actualizada.\n\n"
            f"Mostrar autor original: {'Activado' if show_original_author else 'Desactivado'}",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_confirm_destination_"):

        try:

            token_id = int(
                data.replace("owner_backup_confirm_destination_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Código de backup no válido.")

            return


        result = await confirm_backup_destination_token(
            token_id,
            user_id,
            context
        )


        await send_clean_message(
            context,
            query.message.chat_id,
            result["message"],
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_source_"):

        try:

            source_group_id = int(
                data.replace("owner_backup_source_", "", 1)
            )

        except Exception:

            await query.message.reply_text("❌ Grupo origen no válido.")

            return


        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]
        source_group = backup_group_by_id(groups, source_group_id)


        if not source_group:

            await query.message.reply_text(
                "⛔ Este grupo no pertenece a tu panel o el bot no está como administrador."
            )

            return


        token_row = create_backup_destination_token(
            user_id,
            source_group[0],
            source_group[2]
        )


        if not token_row:

            await query.message.reply_text(
                "❌ No pude generar el código de vinculación del backup.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        token_id, token, expires_at = token_row
        command = f"/backup_{token}"


        log_event(
            "backup_destination_token_created",
            category="backup",
            severity="info",
            scope="group",
            group_id=source_group[0],
            telegram_group_id=source_group[2],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Token de destino backup creado.",
            metadata={
                "token_id": token_id,
                "expires_at": expires_at
            }
        )


        await send_clean_message(
            context,
            query.message.chat_id,
            "🛡 Backup premium\n\n"
            f"Origen: {source_group[1] or source_group_id}\n\n"
            "Crea un grupo nuevo o usa un grupo vacío como destino.\n"
            "Añade este bot como administrador.\n"
            "Dentro del grupo destino escribe este comando:\n\n"
            f"{command}\n\n"
            "El código caduca en 24 horas y solo puede usarse una vez.",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data.startswith("owner_backup_dest_"):

        try:

            payload = data.replace("owner_backup_dest_", "", 1)
            source_group_text, destination_group_text = payload.split("_", 1)
            source_group_id = int(source_group_text)
            destination_group_id = int(destination_group_text)

        except Exception:

            await query.message.reply_text("❌ Configuración de backup no válida.")

            return


        if source_group_id == destination_group_id:

            await query.message.reply_text(
                "⚠️ El origen y el destino no pueden ser el mismo grupo."
            )

            return


        groups = [
            group
            for group in fetch_backup_owner_groups(user_id)
            if group[3] is True
        ]
        source_group = backup_group_by_id(groups, source_group_id)
        destination_group = backup_group_by_id(groups, destination_group_id)


        if not source_group or not destination_group:

            await query.message.reply_text(
                "⛔ Solo puedes configurar backup entre grupos propios donde el bot esté como administrador."
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO backup_subscriptions
                (
                    owner_user_id,
                    status,
                    plan_type,
                    updated_at
                )
                VALUES (%s, 'active', 'text', NOW())
                RETURNING id

            """, (user_id,))

            subscription_id = cur.fetchone()[0]

            cur.execute("""

                INSERT INTO group_backup_configs
                (
                    owner_user_id,
                    source_group_id,
                    source_telegram_group_id,
                    destination_group_id,
                    destination_telegram_group_id,
                    subscription_id,
                    mode,
                    status,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'text', 'active', NOW())
                ON CONFLICT (owner_user_id, source_group_id, destination_group_id)
                DO UPDATE SET
                    source_telegram_group_id=EXCLUDED.source_telegram_group_id,
                    destination_telegram_group_id=EXCLUDED.destination_telegram_group_id,
                    subscription_id=EXCLUDED.subscription_id,
                    mode='text',
                    status='active',
                    updated_at=NOW()
                RETURNING id

            """, (
                user_id,
                source_group[0],
                source_group[2],
                destination_group[0],
                destination_group[2],
                subscription_id
            ))

            config_id = cur.fetchone()[0]

            conn.commit()


        log_event(
            "backup_activated",
            category="backup",
            severity="info",
            scope="group",
            group_id=source_group_id,
            telegram_group_id=source_group[2],
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Backup premium texto activado.",
            metadata={
                "config_id": config_id,
                "destination_group_id": destination_group_id,
                "destination_telegram_group_id": destination_group[2],
                "mode": "text"
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Backup premium activado.\n\n"
            f"Origen: {source_group[1] or source_group_id}\n"
            f"Destino: {destination_group[1] or destination_group_id}\n"
            "Modo: texto",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_pause":

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_backup_configs
                SET status='paused',
                    updated_at=NOW()
                WHERE owner_user_id=%s
                AND status='active'

            """, (user_id,))

            affected = cur.rowcount
            conn.commit()


        log_event(
            "backup_paused",
            category="backup",
            severity="info",
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Backup premium pausado por owner.",
            metadata={
                "configs_paused": affected
            }
        )

        await query.message.reply_text(
            f"⏸ Backup pausado en {affected} configuración(es).",
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_messages":

        rows = fetch_backup_recent_messages(user_id)


        if not rows:

            await query.message.reply_text(
                "📜 Todavía no hay mensajes copiados.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        text = "📜 Últimos mensajes copiados\n\n"


        for created_at, source_name, destination_name, source_message_id, destination_message_id, message_type, status in rows[:20]:

            text += (
                f"Origen: {source_name or '-'}\n"
                f"Destino: {destination_name or '-'}\n"
                f"Tipo: {message_type or '-'}\n"
                f"Mensaje origen: {source_message_id or '-'}\n"
                f"Mensaje destino: {destination_message_id or '-'}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_backup_panel_keyboard()
        )

        return


    if data == "owner_backup_errors":

        rows = fetch_backup_recent_errors(user_id)


        if not rows:

            await query.message.reply_text(
                "✅ No hay errores recientes de backup.",
                reply_markup=build_backup_panel_keyboard()
            )

            return


        text = "⚠️ Últimos errores de backup\n\n"


        for created_at, severity, error_type, message in rows[:20]:

            text += (
                f"Tipo: {error_type or '-'}\n"
                f"Severidad: {severity or '-'}\n"
                f"Detalle: {message or '-'}\n"
                f"Fecha: {created_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_backup_panel_keyboard()
        )

        return


    # Nada encajó: que callback_router siga con sus ramas, igual que antes.
    return NOT_HANDLED
