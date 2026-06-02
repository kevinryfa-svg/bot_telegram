import json
import re
from datetime import datetime
from urllib.parse import urlparse

from bot_config import TOKEN
from db import conn
from notification_service import send_telegram_message
from owner_addon_service import owner_has_feature
from rbac_helpers import (
    get_group_owner_user_id,
    has_permission,
    is_super_admin
)


GUARDIAN_DEFAULT_ACTION_MODE = "log_only"
GUARDIAN_ANTI_LINK_ACTIONS = ("disabled", "log_only", "warn")
GUARDIAN_URL_RE = re.compile(
    r"(?i)\b((?:https?://|www\.|t\.me/|telegram\.me/)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+\S*)"
)

GUARDIAN_LOG_EVENT_CATEGORIES = [
    {
        "key": "entries",
        "label": "Entradas",
        "default_enabled": True
    },
    {
        "key": "exits",
        "label": "Salidas",
        "default_enabled": False
    },
    {
        "key": "payments",
        "label": "Pagos",
        "default_enabled": True
    },
    {
        "key": "renewals",
        "label": "Renovaciones",
        "default_enabled": True
    },
    {
        "key": "codes",
        "label": "Códigos canjeados",
        "default_enabled": True
    },
    {
        "key": "links",
        "label": "Links generados/recuperados",
        "default_enabled": True
    },
    {
        "key": "warnings",
        "label": "Warnings",
        "default_enabled": True
    },
    {
        "key": "kicks",
        "label": "Expiraciones/kicks",
        "default_enabled": True
    },
    {
        "key": "bans",
        "label": "Bans",
        "default_enabled": True
    },
    {
        "key": "errors",
        "label": "Errores importantes",
        "default_enabled": True
    },
    {
        "key": "guardian_config",
        "label": "Configuración Guardian",
        "default_enabled": True
    }
]

GUARDIAN_LOG_EVENT_CATEGORY_DEFAULTS = {
    category["key"]: category["default_enabled"]
    for category in GUARDIAN_LOG_EVENT_CATEGORIES
}


def guardian_log_event_category_keys():

    return [category["key"] for category in GUARDIAN_LOG_EVENT_CATEGORIES]


def map_guardian_event_type_to_category(event_type):

    event_type = (event_type or "").strip()

    if event_type in (
        "guardian_user_join_allowed",
        "guardian_user_join_blocked"
    ):

        return "entries"


    if event_type in (
        "guardian_payment_confirmed",
        "guardian_payment_invite_link_failed"
    ):

        return "payments"


    if "renewal" in event_type or "renovacion" in event_type:

        return "renewals"


    if event_type in ("guardian_group_code_redeemed",):

        return "codes"


    if event_type in (
        "guardian_access_link_recovered",
        "guardian_access_links_bulk_completed",
        "guardian_anti_link_detected"
    ):

        return "links"


    if event_type in (
        "guardian_warning_added",
        "guardian_warnings_reset"
    ):

        return "warnings"


    if event_type in ("guardian_access_expired",):

        return "kicks"


    if "ban" in event_type:

        return "bans"


    if "error" in event_type or "failed" in event_type:

        return "errors"


    if event_type in (
        "guardian_test_log_sent",
        "guardian_log_channel_connected",
        "guardian_design_placeholder_opened",
        "guardian_warnings_panel_opened",
        "guardian_log_event_settings_updated"
    ):

        return "guardian_config"


    return "guardian_config"


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


def is_guardian_log_available(group_id):

    settings = fetch_guardian_settings(group_id)

    return bool(
        settings
        and settings.get("is_enabled")
        and settings.get("log_channel_id")
    )


def get_guardian_log_event_settings(group_id):

    defaults = {
        category["key"]: {
            **category,
            "is_enabled": category["default_enabled"]
        }
        for category in GUARDIAN_LOG_EVENT_CATEGORIES
    }

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT event_category,
                       COALESCE(is_enabled, TRUE)
                FROM guardian_log_event_settings
                WHERE group_id=%s

            """, (group_id,))

            for event_category, is_enabled in cur.fetchall():

                if event_category in defaults:

                    defaults[event_category]["is_enabled"] = bool(is_enabled)

    except Exception:

        try:

            conn.rollback()

        except Exception:

            pass


    return defaults


def is_guardian_event_enabled(group_id, event_type):

    category = map_guardian_event_type_to_category(event_type)
    settings = get_guardian_log_event_settings(group_id)

    return bool(
        settings.get(category, {}).get(
            "is_enabled",
            GUARDIAN_LOG_EVENT_CATEGORY_DEFAULTS.get(category, True)
        )
    )


def set_guardian_log_event_enabled(group_id, category, enabled):

    if category not in guardian_log_event_category_keys():

        return False


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO guardian_log_event_settings
            (
                group_id,
                event_category,
                is_enabled,
                updated_at
            )
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (group_id, event_category) DO UPDATE
            SET is_enabled=EXCLUDED.is_enabled,
                updated_at=NOW()

        """, (
            group_id,
            category,
            bool(enabled)
        ))

        conn.commit()


    return True


def extract_urls_from_text(text):

    if not text:

        return []


    urls = []

    for match in GUARDIAN_URL_RE.findall(text):

        candidate = (match or "").strip(".,;:!?)>]}")

        if candidate and "." in candidate:

            urls.append(candidate)


    return urls


def normalize_domain_from_url(url):

    if not url:

        return None


    value = str(url).strip().lower()

    if value.startswith("www."):

        value = "https://" + value

    elif value.startswith(("t.me/", "telegram.me/")):

        value = "https://" + value

    elif "://" not in value:

        value = "https://" + value


    try:

        parsed = urlparse(value)
        domain = (parsed.netloc or parsed.path.split("/", 1)[0]).lower()

    except Exception:

        return None


    if domain.startswith("www."):

        domain = domain[4:]


    return domain or None


def resolve_guardian_group_id_from_telegram_group(telegram_group_id):

    if not telegram_group_id:

        return None


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id
                FROM groups
                WHERE telegram_group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                LIMIT 1

            """, (telegram_group_id,))

            row = cur.fetchone()

            return row[0] if row else None

    except Exception:

        try:

            conn.rollback()

        except Exception:

            pass

        return None


def is_guardian_link_allowed(group_id, url):

    domain = normalize_domain_from_url(url)

    if not domain:

        return True


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT domain
                FROM guardian_link_whitelist
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE

            """, (group_id,))

            allowed_domains = [
                (row[0] or "").strip().lower()
                for row in cur.fetchall()
                if row and row[0]
            ]

    except Exception:

        try:

            conn.rollback()

        except Exception:

            pass

        return False


    for allowed_domain in allowed_domains:

        if allowed_domain.startswith("www."):

            allowed_domain = allowed_domain[4:]


        if domain == allowed_domain or domain.endswith("." + allowed_domain):

            return True


    return False


def count_guardian_link_whitelist_domains(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM guardian_link_whitelist
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE

            """, (group_id,))

            return cur.fetchone()[0]

    except Exception:

        try:

            conn.rollback()

        except Exception:

            pass

        return 0


def list_guardian_link_whitelist_domains(group_id, limit=50):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT domain
                FROM guardian_link_whitelist
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                ORDER BY domain ASC
                LIMIT %s

            """, (
                group_id,
                limit
            ))

            return [row[0] for row in cur.fetchall() if row and row[0]]

    except Exception:

        try:

            conn.rollback()

        except Exception:

            pass

        return []


def get_guardian_anti_links_settings(group_id):

    settings = fetch_guardian_settings(group_id)

    if not settings:

        return {
            "enabled": False,
            "action": "disabled"
        }


    action = "log_only"

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(anti_links_enabled, FALSE),
                       COALESCE(anti_links_action, 'log_only')
                FROM guardian_group_settings
                WHERE group_id=%s
                LIMIT 1

            """, (group_id,))

            row = cur.fetchone()

            if row:

                action = row[1] if row[1] in GUARDIAN_ANTI_LINK_ACTIONS else "log_only"

                return {
                    "enabled": bool(row[0]) and action != "disabled",
                    "action": action
                }

    except Exception:

        try:

            conn.rollback()

        except Exception:

            pass


    return {
        "enabled": bool(settings.get("anti_links_enabled")),
        "action": action
    }


def update_guardian_anti_links_settings(group_id, enabled=None, action=None):

    if action and action not in GUARDIAN_ANTI_LINK_ACTIONS:

        return False


    updates = []
    params = []

    if enabled is not None:

        updates.append("anti_links_enabled=%s")
        params.append(bool(enabled))

    if action is not None:

        updates.append("anti_links_action=%s")
        params.append(action)

    if not updates:

        return False


    params.append(group_id)

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE guardian_group_settings
            SET {", ".join(updates)},
                updated_at=NOW()
            WHERE group_id=%s

        """, params)

        conn.commit()


    return True


def should_guardian_ignore_user(group_id, user_id):

    if not group_id or not user_id:

        return True


    try:

        if is_super_admin(user_id):

            return True


        owner_user_id = get_group_owner_user_id(group_id)

        if owner_user_id and int(owner_user_id) == int(user_id):

            return True


        return (
            has_permission(user_id, group_id, "can_manage_groups")
            or has_permission(user_id, group_id, "can_manage_users")
        )

    except Exception:

        return False


async def process_guardian_anti_links_message(update, context):

    try:

        message = update.message or update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if not message or not chat or not user or chat.type not in ("group", "supergroup"):

            return False


        text = message.text or message.caption
        urls = extract_urls_from_text(text)

        if not urls:

            return False


        telegram_group_id = chat.id
        group_id = resolve_guardian_group_id_from_telegram_group(telegram_group_id)

        if not group_id:

            return False


        settings = fetch_guardian_settings(group_id)
        owner_user_id = get_group_owner_user_id(group_id)

        if (
            not settings
            or not settings.get("is_enabled")
            or not owner_user_id
            or not owner_has_feature(owner_user_id, "guardian", group_id=group_id)
        ):

            return False


        anti_links_settings = get_guardian_anti_links_settings(group_id)

        if not anti_links_settings.get("enabled"):

            return False


        if should_guardian_ignore_user(group_id, user.id):

            return False


        forbidden_urls = [
            url
            for url in urls
            if not is_guardian_link_allowed(group_id, url)
        ]

        if not forbidden_urls:

            return False


        detected_domains = sorted({
            domain
            for domain in (
                normalize_domain_from_url(url)
                for url in forbidden_urls
            )
            if domain
        })
        action = anti_links_settings.get("action") or "log_only"
        warning_added = False

        if action == "warn":

            add_guardian_warning(
                group_id,
                user.id,
                getattr(context.bot, "id", None),
                reason="Link no permitido",
                source="anti_links"
            )
            warning_added = True


        await send_guardian_event_log(
            context,
            group_id,
            "guardian_anti_link_detected",
            "Guardian detectó un link no permitido.",
            telegram_group_id=telegram_group_id,
            severity="warning",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={
                "group_id": group_id,
                "telegram_group_id": telegram_group_id,
                "user_id": user.id,
                "username": user.username,
                "detected_domains": detected_domains,
                "action": action,
                "warning_added": warning_added
            }
        )

        return True

    except Exception as e:

        try:

            await send_guardian_event_log(
                context,
                group_id if "group_id" in locals() else None,
                "guardian_anti_link_error",
                "Error procesando anti-links Guardian.",
                severity="warning",
                metadata={
                    "error": str(e)[:500]
                }
            )

        except Exception:

            pass

        return False


def truncate_guardian_value(value, limit=500):

    if value is None:

        return None


    text = str(value)

    if len(text) <= limit:

        return text


    return text[:limit] + "..."


def sanitize_guardian_metadata(metadata):

    safe = {}

    for key, value in (metadata or {}).items():

        key_text = str(key)
        lowered = key_text.lower()

        sensitive_fragments = (
            "token",
            "secret",
            "password",
            "invite",
            "link",
            "url",
            "checkout",
            "payment",
            "authorization",
            "approval"
        )

        if any(fragment in lowered for fragment in sensitive_fragments):

            safe[key_text] = "[hidden]"
            continue


        if isinstance(value, dict):

            safe[key_text] = sanitize_guardian_metadata(value)

        elif isinstance(value, (list, tuple)):

            safe[key_text] = [
                sanitize_guardian_metadata(item)
                if isinstance(item, dict)
                else truncate_guardian_value(item, limit=200)
                for item in value[:20]
            ]

        elif isinstance(value, (datetime,)):

            safe[key_text] = value.isoformat()

        else:

            safe[key_text] = truncate_guardian_value(value)


    return safe


def build_guardian_event_log_text(event_type, message, metadata=None):

    lines = [
        "🛡 Guardian",
        "",
        f"Evento: {event_type}",
        f"Detalle: {message or '-'}"
    ]

    safe_metadata = sanitize_guardian_metadata(metadata)

    if safe_metadata:

        lines.append("")
        lines.append("Datos:")

        for key, value in safe_metadata.items():

            lines.append(f"- {key}: {value}")


    return "\n".join(lines)[:3500]


def record_guardian_delivery_failure(group_id, event_type, error, metadata=None):

    try:

        record_guardian_log_event(
            group_id,
            "guardian_channel_delivery_failed",
            severity="warning",
            message="No se pudo enviar un evento Guardian al canal configurado.",
            metadata={
                "source_event_type": event_type,
                "error": str(error)[:500],
                **sanitize_guardian_metadata(metadata or {})
            }
        )

    except Exception:

        pass


async def send_guardian_event_log(
    context_or_bot,
    group_id,
    event_type,
    message,
    metadata=None,
    telegram_group_id=None,
    severity="info",
    actor_user_id=None,
    target_user_id=None
):

    try:

        settings = fetch_guardian_settings(group_id)
        safe_metadata = sanitize_guardian_metadata(metadata)
        event_category = map_guardian_event_type_to_category(event_type)
        channel_event_enabled = is_guardian_event_enabled(group_id, event_type)

        record_guardian_log_event(
            group_id,
            event_type,
            telegram_group_id=telegram_group_id or (settings or {}).get("telegram_group_id"),
            severity=severity,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            message=message,
            metadata={
                **safe_metadata,
                "guardian_event_category": event_category,
                "guardian_channel_skipped_by_settings": not channel_event_enabled
            }
        )

        if (
            not settings
            or not settings.get("is_enabled")
            or not settings.get("log_channel_id")
            or not channel_event_enabled
        ):

            return False


        bot = getattr(context_or_bot, "bot", context_or_bot)

        await bot.send_message(
            chat_id=settings.get("log_channel_id"),
            text=build_guardian_event_log_text(event_type, message, safe_metadata)
        )

        return True

    except Exception as e:

        record_guardian_delivery_failure(
            group_id,
            event_type,
            e,
            metadata=metadata
        )

        return False


def send_guardian_event_log_sync(
    group_id,
    event_type,
    message,
    metadata=None,
    telegram_group_id=None,
    severity="info",
    actor_user_id=None,
    target_user_id=None
):

    try:

        settings = fetch_guardian_settings(group_id)
        safe_metadata = sanitize_guardian_metadata(metadata)
        event_category = map_guardian_event_type_to_category(event_type)
        channel_event_enabled = is_guardian_event_enabled(group_id, event_type)

        record_guardian_log_event(
            group_id,
            event_type,
            telegram_group_id=telegram_group_id or (settings or {}).get("telegram_group_id"),
            severity=severity,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            message=message,
            metadata={
                **safe_metadata,
                "guardian_event_category": event_category,
                "guardian_channel_skipped_by_settings": not channel_event_enabled
            }
        )

        if (
            not settings
            or not settings.get("is_enabled")
            or not settings.get("log_channel_id")
            or not channel_event_enabled
        ):

            return False


        response = send_telegram_message(
            TOKEN,
            settings.get("log_channel_id"),
            build_guardian_event_log_text(event_type, message, safe_metadata)
        )

        if not response or not response.get("ok"):

            record_guardian_delivery_failure(
                group_id,
                event_type,
                (response or {}).get("description") or response,
                metadata=metadata
            )

            return False


        return True

    except Exception as e:

        record_guardian_delivery_failure(
            group_id,
            event_type,
            e,
            metadata=metadata
        )

        return False


def row_to_guardian_warning(row):

    if not row:

        return None


    return {
        "id": row[0],
        "group_id": row[1],
        "user_id": row[2],
        "reason": row[3],
        "source": row[4],
        "is_active": row[5],
        "created_by": row[6],
        "created_at": row[7]
    }


def guardian_warning_fields():

    return "id, group_id, user_id, reason, source, is_active, created_by, created_at"


def add_guardian_warning(group_id, target_user_id, warned_by_user_id, reason=None, source="manual"):

    reason_text = reason or "Warning manual desde panel"

    with conn.cursor() as cur:

        cur.execute(f"""

            INSERT INTO guardian_warnings
            (
                group_id,
                user_id,
                reason,
                source,
                is_active,
                created_by
            )
            VALUES (%s, %s, %s, %s, TRUE, %s)
            RETURNING {guardian_warning_fields()}

        """, (
            group_id,
            target_user_id,
            reason_text,
            source,
            warned_by_user_id
        ))

        row = cur.fetchone()
        conn.commit()


    active_count = count_guardian_warnings(group_id, target_user_id)

    send_guardian_event_log_sync(
        group_id,
        "guardian_warning_added",
        "Warning manual añadido.",
        severity="warning",
        actor_user_id=warned_by_user_id,
        target_user_id=target_user_id,
        metadata={
            "group_id": group_id,
            "target_user_id": target_user_id,
            "warned_by_user_id": warned_by_user_id,
            "reason": reason_text,
            "active_warning_count": active_count
        }
    )

    return row_to_guardian_warning(row)


def list_guardian_warnings(group_id, target_user_id=None, limit=20):

    filters = ["group_id=%s"]
    params = [group_id]

    if target_user_id is not None:

        filters.append("user_id=%s")
        params.append(target_user_id)


    params.append(limit)

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {guardian_warning_fields()}
            FROM guardian_warnings
            WHERE {" AND ".join(filters)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s

        """, params)

        return [
            row_to_guardian_warning(row)
            for row in cur.fetchall()
        ]


def count_guardian_warnings(group_id, target_user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*)
            FROM guardian_warnings
            WHERE group_id=%s
            AND user_id=%s
            AND COALESCE(is_active, TRUE)=TRUE

        """, (
            group_id,
            target_user_id
        ))

        return cur.fetchone()[0]


def reset_guardian_warnings(group_id, target_user_id, reset_by_user_id, reason=None):

    reason_text = reason or "Reset manual desde panel"

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE guardian_warnings
            SET is_active=FALSE
            WHERE group_id=%s
            AND user_id=%s
            AND COALESCE(is_active, TRUE)=TRUE

        """, (
            group_id,
            target_user_id
        ))

        reset_count = cur.rowcount
        conn.commit()


    send_guardian_event_log_sync(
        group_id,
        "guardian_warnings_reset",
        "Warnings manuales reseteados.",
        severity="warning",
        actor_user_id=reset_by_user_id,
        target_user_id=target_user_id,
        metadata={
            "group_id": group_id,
            "target_user_id": target_user_id,
            "reset_by_user_id": reset_by_user_id,
            "reset_count": reset_count,
            "reason": reason_text
        }
    )

    return reset_count


def list_guardian_warning_summary(group_id, limit=20):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT user_id,
                   COUNT(*) AS active_warnings,
                   MAX(created_at) AS last_warning_at
            FROM guardian_warnings
            WHERE group_id=%s
            AND COALESCE(is_active, TRUE)=TRUE
            GROUP BY user_id
            ORDER BY active_warnings DESC, last_warning_at DESC
            LIMIT %s

        """, (
            group_id,
            limit
        ))

        return [
            {
                "user_id": row[0],
                "active_warnings": row[1],
                "last_warning_at": row[2]
            }
            for row in cur.fetchall()
        ]


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

    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, default=str)

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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
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
