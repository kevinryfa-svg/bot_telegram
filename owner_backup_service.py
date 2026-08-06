import json
import os
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from db import conn


OWNER_BACKUP_STORAGE_DIR = "/tmp/owner_backups"

OWNER_BACKUP_JOB_FIELDS = [
    "id",
    "owner_user_id",
    "group_id",
    "frequency",
    "is_active",
    "last_run_at",
    "next_run_at",
    "created_at",
    "updated_at"
]

OWNER_BACKUP_FILE_FIELDS = [
    "id",
    "owner_user_id",
    "group_id",
    "job_id",
    "backup_type",
    "status",
    "file_format",
    "file_path",
    "file_size_bytes",
    "summary",
    "created_at"
]


def row_to_owner_backup_job(row):

    return dict(zip(OWNER_BACKUP_JOB_FIELDS, row)) if row else None


def row_to_owner_backup_file(row):

    return dict(zip(OWNER_BACKUP_FILE_FIELDS, row)) if row else None


def ensure_backup_storage_dir():

    os.makedirs(OWNER_BACKUP_STORAGE_DIR, exist_ok=True)
    return OWNER_BACKUP_STORAGE_DIR


def sanitize_backup_value(value):

    if isinstance(value, (datetime, date)):

        return value.isoformat()

    if isinstance(value, Decimal):

        return float(value)

    if isinstance(value, dict):

        return {
            str(key): sanitize_backup_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):

        return [sanitize_backup_value(item) for item in value]

    return value


def mask_identifier(value, visible=4):

    if not value:

        return None

    text = str(value)

    if len(text) <= visible:

        return "***"

    return f"{text[:visible]}***"


def fetch_dict_rows(sql, params=None):

    with conn.cursor() as cur:

        cur.execute(sql, params or ())
        rows = cur.fetchall()
        columns = [column[0] for column in cur.description]

    return [
        dict(zip(columns, row))
        for row in rows
    ]


def backup_section(name, loader):

    try:

        data = loader()

        if isinstance(data, dict):

            data.setdefault("available", True)
            return sanitize_backup_value(data)

        return sanitize_backup_value({
            "available": True,
            "items": data
        })

    except Exception as e:

        try:

            conn.rollback()

        except Exception:

            pass

        return {
            "available": False,
            "error": str(e)[:300]
        }


def fetch_one_dict(sql, params=None):

    rows = fetch_dict_rows(sql, params=params)
    return rows[0] if rows else None


def build_owner_backup_payload(owner_user_id, group_id):

    created_at = datetime.utcnow()

    payload = {
        "version": 1,
        "created_at": created_at.isoformat(),
        "owner_user_id": owner_user_id,
        "group_id": group_id
    }

    def load_community():

        community = fetch_one_dict("""

            SELECT id,
                   name,
                   description,
                   telegram_group_id,
                   COALESCE(community_type, 'group') AS community_type,
                   category,
                   COALESCE(is_active, TRUE) AS is_active,
                   added_by AS owner_user_id,
                   created_at
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,)) or {}

        telegram_group_id = community.pop("telegram_group_id", None)
        community["telegram_group_id_masked"] = mask_identifier(telegram_group_id)

        return community


    payload["community"] = backup_section("community", load_community)

    payload["plans"] = backup_section("plans", lambda: fetch_dict_rows("""

        SELECT id,
               name,
               amount,
               currency,
               duration_days,
               is_active,
               created_at
        FROM plans
        WHERE group_id=%s
        ORDER BY id ASC

    """, (group_id,)))

    payload["admins"] = backup_section("admins", lambda: fetch_dict_rows("""

        SELECT user_id,
               group_id,
               role,
               can_manage_users,
               can_manage_codes,
               can_manage_groups,
               can_manage_plans,
               can_manage_payments,
               can_manage_admins,
               can_view_users,
               can_view_payments,
               can_view_stats,
               can_view_logs,
               can_edit_group_texts,
               can_edit_marketplace_preview,
               can_respond_group_support,
               is_active,
               created_at
        FROM admins
        WHERE group_id=%s
        ORDER BY id ASC

    """, (group_id,)))

    def load_codes_summary():

        return fetch_one_dict("""

            SELECT COUNT(*) AS total_codes,
                   COUNT(*) FILTER (WHERE COALESCE(used, FALSE)=FALSE) AS active_count,
                   COUNT(*) FILTER (WHERE COALESCE(used, FALSE)=TRUE) AS redeemed_count
            FROM invite_codes
            WHERE group_id=%s

        """, (group_id,)) or {}

    payload["codes_summary"] = backup_section("codes_summary", load_codes_summary)

    def load_invite_links_summary():

        return fetch_one_dict("""

            SELECT COUNT(*) AS total_links,
                   COUNT(*) FILTER (WHERE COALESCE(is_active, FALSE)=TRUE) AS active_count,
                   COUNT(*) FILTER (WHERE revoked_at IS NOT NULL OR COALESCE(is_active, FALSE)=FALSE) AS revoked_or_inactive_count,
                   MIN(created_at) AS first_created_at,
                   MAX(created_at) AS last_created_at
            FROM invite_links
            WHERE group_id=%s

        """, (group_id,)) or {}

    payload["invite_links_summary"] = backup_section("invite_links_summary", load_invite_links_summary)

    def load_ad_promo():

        campaigns = fetch_dict_rows("""

            SELECT id,
                   paid_group_id,
                   source_chat_id,
                   source_chat_title,
                   source_chat_type,
                   promo_group_telegram_id,
                   promo_group_title,
                   promo_group_type,
                   is_active,
                   is_paused,
                   auto_capture_enabled,
                   randomize_media,
                   ai_copy_enabled,
                   batch_size,
                   interval_minutes,
                   max_posts,
                   delete_old_posts,
                   default_caption,
                   offer_text,
                   price_text,
                   cta_text,
                   tone,
                   last_run_at,
                   next_run_at,
                   created_at,
                   updated_at
            FROM ad_promo_campaigns
            WHERE paid_group_id=%s
            ORDER BY id ASC

        """, (group_id,))

        media = fetch_dict_rows("""

            SELECT id,
                   campaign_id,
                   paid_group_id,
                   source_chat_id,
                   source_message_id,
                   file_unique_id,
                   media_type,
                   duration,
                   width,
                   height,
                   file_size,
                   is_active,
                   usage_count,
                   last_sent_at,
                   created_at
            FROM ad_promo_media
            WHERE paid_group_id=%s
            ORDER BY id ASC

        """, (group_id,))

        return {
            "campaigns": campaigns,
            "media_metadata": media
        }

    payload["ad_promo"] = backup_section("ad_promo", load_ad_promo)

    def load_owner_addons():

        rows = fetch_dict_rows("""

            SELECT addon_code,
                   status,
                   stripe_customer_id,
                   stripe_subscription_id,
                   stripe_price_id,
                   current_period_start,
                   current_period_end,
                   cancel_at_period_end,
                   created_at,
                   updated_at
            FROM owner_addon_subscriptions
            WHERE group_id=%s
            ORDER BY updated_at DESC NULLS LAST,
                     id DESC

        """, (group_id,))

        for row in rows:

            row["stripe_customer_id"] = mask_identifier(row.get("stripe_customer_id"))
            row["stripe_subscription_id"] = mask_identifier(row.get("stripe_subscription_id"))
            row["stripe_price_id"] = mask_identifier(row.get("stripe_price_id"))

        return rows

    payload["owner_addons"] = backup_section("owner_addons", load_owner_addons)

    def load_satisfaction():

        surveys = fetch_one_dict("""

            SELECT COUNT(*) AS surveys_count,
                   COUNT(*) FILTER (WHERE COALESCE(status, 'draft') <> 'closed') AS active_surveys,
                   MIN(created_at) AS first_created_at,
                   MAX(created_at) AS last_created_at
            FROM customer_satisfaction_surveys
            WHERE group_id=%s

        """, (group_id,)) or {}

        sent = fetch_one_dict("""

            SELECT COUNT(*) AS total_sent,
                   COUNT(*) FILTER (WHERE status='failed') AS failed_count,
                   COUNT(*) FILTER (WHERE status='completed') AS completed_count
            FROM customer_satisfaction_sent
            WHERE group_id=%s

        """, (group_id,)) or {}

        responses = fetch_one_dict("""

            SELECT COUNT(DISTINCT r.id) AS responses_count,
                   AVG(a.rating)::FLOAT AS average_rating
            FROM customer_satisfaction_responses r
            JOIN customer_satisfaction_surveys s ON s.id = r.survey_id
            LEFT JOIN customer_satisfaction_answers a ON a.response_id = r.id
            WHERE s.group_id=%s

        """, (group_id,)) or {}

        return {
            "surveys": surveys,
            "sent": sent,
            "responses": responses
        }

    payload["satisfaction"] = backup_section("satisfaction", load_satisfaction)

    def load_support():

        return fetch_one_dict("""

            SELECT COUNT(*) AS total_tickets,
                   COUNT(*) FILTER (WHERE status='open') AS open_tickets,
                   COUNT(*) FILTER (WHERE status='closed') AS closed_tickets,
                   MIN(created_at) AS first_ticket_at,
                   MAX(updated_at) AS last_ticket_update_at
            FROM support_tickets
            WHERE group_id=%s

        """, (group_id,)) or {}

    payload["support"] = backup_section("support", load_support)

    def load_metrics():

        group_metrics = fetch_one_dict("""

            SELECT preview_views,
                   access_clicks,
                   favorites_count,
                   updated_at
            FROM community_stats
            WHERE group_id=%s
            LIMIT 1

        """, (group_id,)) or {}

        access_metrics = fetch_one_dict("""

            SELECT COUNT(*) AS subscriptions_count,
                   COUNT(*) FILTER (WHERE status='active') AS active_access_count
            FROM subscriptions
            WHERE group_id=%s

        """, (group_id,)) or {}

        payment_metrics = fetch_one_dict("""

            SELECT COUNT(*) AS payments_count,
                   COALESCE(SUM(amount), 0) AS total_payment_amount
            FROM payments
            WHERE group_id=%s

        """, (group_id,)) or {}

        return {
            "community_stats": group_metrics,
            "access": access_metrics,
            "payments_summary": payment_metrics,
            "generated_at": created_at.isoformat()
        }

    payload["metrics"] = backup_section("metrics", load_metrics)

    return sanitize_backup_value(payload)


def summarize_owner_backup_payload(payload):

    sections = [
        key
        for key, value in payload.items()
        if isinstance(value, dict) and value.get("available") is not False
    ]

    return f"Backup operativo JSON. Secciones incluidas: {', '.join(sections[:12])}."


def create_owner_backup(owner_user_id, group_id, backup_type="manual", job_id=None):

    storage_dir = ensure_backup_storage_dir()
    payload = build_owner_backup_payload(owner_user_id, group_id)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(4)
    filename = f"owner_backup_{group_id}_{timestamp}_{token}.json"
    file_path = os.path.join(storage_dir, filename)

    with open(file_path, "w", encoding="utf-8") as backup_file:

        json.dump(payload, backup_file, ensure_ascii=False, indent=2, sort_keys=True)

    file_size_bytes = os.path.getsize(file_path)
    summary = summarize_owner_backup_payload(payload)

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO owner_backup_files
            (
                owner_user_id,
                group_id,
                job_id,
                backup_type,
                status,
                file_format,
                file_path,
                file_size_bytes,
                summary,
                created_at
            )
            VALUES (%s, %s, %s, %s, 'created', 'json', %s, %s, %s, NOW())
            RETURNING id,
                      owner_user_id,
                      group_id,
                      job_id,
                      backup_type,
                      status,
                      file_format,
                      file_path,
                      file_size_bytes,
                      summary,
                      created_at

        """, (
            owner_user_id,
            group_id,
            job_id,
            backup_type,
            file_path,
            file_size_bytes,
            summary
        ))

        row = cur.fetchone()
        conn.commit()

    return row_to_owner_backup_file(row)


def fetch_owner_backups(owner_user_id, group_id, limit=10):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   owner_user_id,
                   group_id,
                   job_id,
                   backup_type,
                   status,
                   file_format,
                   file_path,
                   file_size_bytes,
                   summary,
                   created_at
            FROM owner_backup_files
            WHERE owner_user_id=%s
            AND group_id=%s
            ORDER BY created_at DESC,
                     id DESC
            LIMIT %s

        """, (
            owner_user_id,
            group_id,
            limit
        ))

        rows = cur.fetchall()

    return [row_to_owner_backup_file(row) for row in rows]


def fetch_owner_backup_file(backup_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   owner_user_id,
                   group_id,
                   job_id,
                   backup_type,
                   status,
                   file_format,
                   file_path,
                   file_size_bytes,
                   summary,
                   created_at
            FROM owner_backup_files
            WHERE id=%s
            LIMIT 1

        """, (backup_id,))

        row = cur.fetchone()

    return row_to_owner_backup_file(row)


def compute_next_backup_run(frequency, base=None):

    base = base or datetime.utcnow()
    frequency = (frequency or "manual").lower()

    if frequency == "daily":

        return base + timedelta(days=1)

    if frequency == "weekly":

        return base + timedelta(days=7)

    if frequency == "monthly":

        return base + timedelta(days=30)

    return None


def upsert_owner_backup_job(owner_user_id, group_id, frequency):

    # owner_user_id y group_id son NOT NULL en la tabla: sin ellos la inserción
    # rompe y el fallo llegaba al usuario como un error genérico.
    if not owner_user_id or not group_id:

        print(
            "Backup: no se puede programar sin propietario y comunidad "
            f"(owner={owner_user_id}, group={group_id})."
        )

        return None


    frequency = (frequency or "manual").lower()
    is_active = frequency in ("daily", "weekly", "monthly")
    next_run_at = compute_next_backup_run(frequency) if is_active else None

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO owner_backup_jobs
            (
                owner_user_id,
                group_id,
                frequency,
                is_active,
                next_run_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (owner_user_id, group_id)
            DO UPDATE SET
                frequency=EXCLUDED.frequency,
                is_active=EXCLUDED.is_active,
                next_run_at=EXCLUDED.next_run_at,
                updated_at=NOW()
            RETURNING id,
                      owner_user_id,
                      group_id,
                      frequency,
                      is_active,
                      last_run_at,
                      next_run_at,
                      created_at,
                      updated_at

        """, (
            owner_user_id,
            group_id,
            frequency,
            is_active,
            next_run_at
        ))

        row = cur.fetchone()
        conn.commit()

    return row_to_owner_backup_job(row)


def fetch_owner_backup_job(owner_user_id, group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   owner_user_id,
                   group_id,
                   frequency,
                   is_active,
                   last_run_at,
                   next_run_at,
                   created_at,
                   updated_at
            FROM owner_backup_jobs
            WHERE owner_user_id=%s
            AND group_id=%s
            LIMIT 1

        """, (
            owner_user_id,
            group_id
        ))

        row = cur.fetchone()

    return row_to_owner_backup_job(row)


def fetch_due_owner_backup_jobs(limit=10):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   owner_user_id,
                   group_id,
                   frequency,
                   is_active,
                   last_run_at,
                   next_run_at,
                   created_at,
                   updated_at
            FROM owner_backup_jobs
            WHERE is_active=TRUE
            AND next_run_at IS NOT NULL
            AND next_run_at <= NOW()
            ORDER BY next_run_at ASC,
                     id ASC
            LIMIT %s

        """, (limit,))

        rows = cur.fetchall()

    return [row_to_owner_backup_job(row) for row in rows]


def mark_owner_backup_job_run(job_id, frequency, success=True):

    now = datetime.utcnow()
    next_run_at = compute_next_backup_run(frequency, base=now) if success else now + timedelta(hours=1)

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE owner_backup_jobs
            SET last_run_at=NOW(),
                next_run_at=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING id,
                      owner_user_id,
                      group_id,
                      frequency,
                      is_active,
                      last_run_at,
                      next_run_at,
                      created_at,
                      updated_at

        """, (
            next_run_at,
            job_id
        ))

        row = cur.fetchone()
        conn.commit()

    return row_to_owner_backup_job(row)
