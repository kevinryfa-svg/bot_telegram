import json
from datetime import datetime

from db import conn


GUARDIAN_DEFAULT_ACTION_MODE = "log_only"


def row_to_guardian_settings(row):

    if not row:

        return None


    return {
        "id": row[0],
        "group_id": row[1],
        "owner_user_id": row[2],
        "telegram_group_id": row[3],
        "is_enabled": row[4],
        "log_channel_id": row[5],
        "log_channel_title": row[6],
        "anti_links_enabled": row[7],
        "forbidden_words_enabled": row[8],
        "night_mode_enabled": row[9],
        "warning_limit": row[10],
        "action_mode": row[11],
        "created_at": row[12],
        "updated_at": row[13]
    }


def guardian_settings_fields():

    return (
        "id, group_id, owner_user_id, telegram_group_id, is_enabled, "
        "log_channel_id, log_channel_title, anti_links_enabled, "
        "forbidden_words_enabled, night_mode_enabled, warning_limit, "
        "action_mode, created_at, updated_at"
    )


def ensure_guardian_settings(group_id, owner_user_id=None, telegram_group_id=None):

    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO guardian_group_settings
            (
                group_id,
                owner_user_id,
                telegram_group_id,
                is_enabled,
                action_mode
            )
            VALUES (%s, %s, %s, FALSE, %s)
            ON CONFLICT (group_id) DO UPDATE
            SET owner_user_id=COALESCE(EXCLUDED.owner_user_id, guardian_group_settings.owner_user_id),
                telegram_group_id=COALESCE(EXCLUDED.telegram_group_id, guardian_group_settings.telegram_group_id),
                updated_at=NOW()
            RETURNING {guardian_settings_fields()}

        """, (
            group_id,
            owner_user_id,
            telegram_group_id,
            GUARDIAN_DEFAULT_ACTION_MODE
        ))

        row = cur.fetchone()
        conn.commit()


    return row_to_guardian_settings(row)


def fetch_guardian_settings(group_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {guardian_settings_fields()}
            FROM guardian_group_settings
            WHERE group_id=%s
            LIMIT 1

        """, (group_id,))

        return row_to_guardian_settings(cur.fetchone())


def update_guardian_log_channel(group_id, channel_id, channel_title=None, actor_user_id=None):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE guardian_group_settings
            SET log_channel_id=%s,
                log_channel_title=%s,
                is_enabled=TRUE,
                updated_at=NOW()
            WHERE group_id=%s
            RETURNING {guardian_settings_fields()}

        """, (
            channel_id,
            channel_title,
            group_id
        ))

        row = cur.fetchone()

        if not row:

            cur.execute(f"""

                INSERT INTO guardian_group_settings
                (
                    group_id,
                    log_channel_id,
                    log_channel_title,
                    is_enabled,
                    action_mode
                )
                VALUES (%s, %s, %s, TRUE, %s)
                RETURNING {guardian_settings_fields()}

            """, (
                group_id,
                channel_id,
                channel_title,
                GUARDIAN_DEFAULT_ACTION_MODE
            ))

            row = cur.fetchone()


        conn.commit()


    record_guardian_log_event(
        group_id,
        "guardian_log_channel_connected",
        actor_user_id=actor_user_id,
        message="Canal de logs Guardian conectado.",
        metadata={
            "log_channel_id": channel_id,
            "log_channel_title": channel_title
        }
    )

    return row_to_guardian_settings(row)


def record_guardian_log_event(
    group_id,
    event_type,
    telegram_group_id=None,
    severity="info",
    actor_user_id=None,
    target_user_id=None,
    message=None,
    metadata=None
):

    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO guardian_log_events
            (
                group_id,
                telegram_group_id,
                event_type,
                severity,
                actor_user_id,
                target_user_id,
                message,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id

        """, (
            group_id,
            telegram_group_id,
            event_type,
            severity,
            actor_user_id,
            target_user_id,
            message,
            metadata_json
        ))

        event_id = cur.fetchone()[0]
        conn.commit()


    return event_id


def format_guardian_datetime(value):

    if not value:

        return "-"


    if isinstance(value, str):

        return value[:19]


    return value.strftime("%d/%m/%Y %H:%M")


def build_guardian_test_log_text(group_name, actor_user_id=None):

    return (
        "🛡 Guardian conectado\n\n"
        f"Comunidad: {group_name}\n"
        f"Modo actual: solo registro, sin acciones automáticas\n"
        f"Actor: {actor_user_id or '-'}\n"
        f"Fecha: {format_guardian_datetime(datetime.utcnow())}\n\n"
        "Este mensaje confirma que el canal de logs recibe eventos de Guardian."
    )


async def send_guardian_test_log(context, settings, group_name, actor_user_id=None):

    channel_id = settings.get("log_channel_id") if settings else None

    if not channel_id:

        return False, "missing_log_channel"


    try:

        await context.bot.send_message(
            chat_id=channel_id,
            text=build_guardian_test_log_text(group_name, actor_user_id=actor_user_id)
        )

        record_guardian_log_event(
            settings.get("group_id"),
            "guardian_test_log_sent",
            telegram_group_id=settings.get("telegram_group_id"),
            actor_user_id=actor_user_id,
            message="Log de prueba Guardian enviado.",
            metadata={
                "log_channel_id": channel_id
            }
        )

        return True, None

    except Exception as e:

        record_guardian_log_event(
            settings.get("group_id"),
            "guardian_test_log_failed",
            telegram_group_id=settings.get("telegram_group_id"),
            severity="warning",
            actor_user_id=actor_user_id,
            message="No se pudo enviar el log de prueba Guardian.",
            metadata={
                "error": str(e)[:500],
                "log_channel_id": channel_id
            }
        )

        return False, str(e)[:500]
