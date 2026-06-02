from audit_log_service import log_event
from db import conn
from invite_link_service import (
    create_telegram_public_invite_link,
    mask_invite_link,
    revoke_telegram_invite_link
)


def row_to_publicity_invite_link(row):

    if not row:

        return None


    return {
        "id": row[0],
        "group_id": row[1],
        "telegram_group_id": row[2],
        "invite_link": row[3],
        "created_by": row[4],
        "is_active": row[5],
        "revoked_at": row[6],
        "revoked_by": row[7],
        "created_at": row[8],
        "source": row[9] if len(row) > 9 else "bot",
        "label": row[10] if len(row) > 10 else None
    }


def normalize_telegram_invite_url(value):

    link = (value or "").strip()


    if not link or any(char.isspace() for char in link):

        return None


    if link.startswith("t.me/"):

        link = f"https://{link}"

    elif link.startswith("http://t.me/"):

        link = link.replace("http://", "https://", 1)


    if not link.startswith("https://t.me/"):

        return None


    suffix = link.replace("https://t.me/", "", 1).strip()


    if not suffix:

        return None


    return link


def get_active_publicity_invite_link(group_id=None, telegram_group_id=None, source=None):

    if not group_id and not telegram_group_id:

        return None


    source_clause = ""
    source_params = ()


    if source:

        source_clause = "AND COALESCE(source, 'bot')=%s"
        source_params = (source,)


    with conn.cursor() as cur:

        if group_id and telegram_group_id:

            cur.execute("""

                SELECT id,
                       group_id,
                       telegram_group_id,
                       invite_link,
                       created_by,
                       COALESCE(is_active, TRUE),
                       revoked_at,
                       revoked_by,
                       created_at,
                       COALESCE(source, 'bot'),
                       label
                FROM publicity_group_invite_links
                WHERE group_id=%s
                AND telegram_group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                {source_clause}
                ORDER BY created_at DESC
                LIMIT 1

            """.format(source_clause=source_clause), (
                group_id,
                telegram_group_id,
                *source_params
            ))

        elif group_id:

            cur.execute("""

                SELECT id,
                       group_id,
                       telegram_group_id,
                       invite_link,
                       created_by,
                       COALESCE(is_active, TRUE),
                       revoked_at,
                       revoked_by,
                       created_at,
                       COALESCE(source, 'bot'),
                       label
                FROM publicity_group_invite_links
                WHERE group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                {source_clause}
                ORDER BY created_at DESC
                LIMIT 1

            """.format(source_clause=source_clause), (
                group_id,
                *source_params
            ))

        else:

            cur.execute("""

                SELECT id,
                       group_id,
                       telegram_group_id,
                       invite_link,
                       created_by,
                       COALESCE(is_active, TRUE),
                       revoked_at,
                       revoked_by,
                       created_at,
                       COALESCE(source, 'bot'),
                       label
                FROM publicity_group_invite_links
                WHERE telegram_group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                {source_clause}
                ORDER BY created_at DESC
                LIMIT 1

            """.format(source_clause=source_clause), (
                telegram_group_id,
                *source_params
            ))

        return row_to_publicity_invite_link(cur.fetchone())


def is_active_publicity_invite_link(invite_link, telegram_group_id):

    if not invite_link or not telegram_group_id:

        return False


    normalized_link = normalize_telegram_invite_url(invite_link)


    if not normalized_link:

        return False


    original_link = (invite_link or "").strip()
    candidate_links = [normalized_link]


    if original_link and original_link != normalized_link:

        candidate_links.append(original_link)


    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM publicity_group_invite_links
            WHERE invite_link = ANY(%s)
            AND telegram_group_id=%s
            AND COALESCE(is_active, TRUE)=TRUE
            LIMIT 1

        """, (
            candidate_links,
            telegram_group_id
        ))

        return cur.fetchone() is not None


def has_active_publicity_invite_links_for_group(group_id, telegram_group_id):

    if not group_id or not telegram_group_id:

        return False


    with conn.cursor() as cur:

        cur.execute("""

            SELECT 1
            FROM publicity_group_invite_links
            WHERE group_id=%s
            AND telegram_group_id=%s
            AND COALESCE(is_active, TRUE)=TRUE
            LIMIT 1

        """, (
            group_id,
            telegram_group_id
        ))

        return cur.fetchone() is not None


def save_publicity_invite_link(group_id, telegram_group_id, invite_link, created_by):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE publicity_group_invite_links
            SET is_active=FALSE,
                revoked_at=COALESCE(revoked_at, CURRENT_TIMESTAMP)
            WHERE group_id=%s
            AND COALESCE(is_active, TRUE)=TRUE
            AND COALESCE(source, 'bot')='bot'

        """, (group_id,))

        cur.execute("""

            INSERT INTO publicity_group_invite_links (
                group_id,
                telegram_group_id,
                invite_link,
                created_by,
                source,
                is_active
            )
            VALUES (%s, %s, %s, %s, 'bot', TRUE)
            ON CONFLICT (invite_link) DO UPDATE
            SET group_id=EXCLUDED.group_id,
                telegram_group_id=EXCLUDED.telegram_group_id,
                created_by=EXCLUDED.created_by,
                source='bot',
                is_active=TRUE,
                revoked_at=NULL,
                revoked_by=NULL
            RETURNING id,
                      group_id,
                      telegram_group_id,
                      invite_link,
                      created_by,
                      COALESCE(is_active, TRUE),
                      revoked_at,
                      revoked_by,
                      created_at,
                      COALESCE(source, 'bot'),
                      label

        """, (
            group_id,
            telegram_group_id,
            invite_link,
            created_by
        ))

        row = cur.fetchone()

    conn.commit()

    return row_to_publicity_invite_link(row)


def authorize_existing_publicity_invite_link(group_id, telegram_group_id, invite_link, created_by, label=None):

    normalized_link = normalize_telegram_invite_url(invite_link)


    if not normalized_link:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO publicity_group_invite_links (
                group_id,
                telegram_group_id,
                invite_link,
                created_by,
                is_active,
                source,
                label
            )
            VALUES (%s, %s, %s, %s, TRUE, 'manual', %s)
            ON CONFLICT (invite_link) DO UPDATE
            SET group_id=EXCLUDED.group_id,
                telegram_group_id=EXCLUDED.telegram_group_id,
                created_by=EXCLUDED.created_by,
                is_active=TRUE,
                revoked_at=NULL,
                revoked_by=NULL,
                source='manual',
                label=EXCLUDED.label
            RETURNING id,
                      group_id,
                      telegram_group_id,
                      invite_link,
                      created_by,
                      COALESCE(is_active, TRUE),
                      revoked_at,
                      revoked_by,
                      created_at,
                      COALESCE(source, 'bot'),
                      label

        """, (
            group_id,
            telegram_group_id,
            normalized_link,
            created_by,
            label
        ))

        row = cur.fetchone()

    conn.commit()
    saved = row_to_publicity_invite_link(row)

    log_event(
        "publicity_invite_existing_link_authorized",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=created_by,
        message="Link existente autorizado como link público de publicidad.",
        metadata={
            "invite_link": mask_invite_link(normalized_link),
            "label": label
        }
    )

    return saved


def list_publicity_invite_links(group_id, telegram_group_id=None, active_only=True):

    params = [group_id]
    telegram_clause = ""
    active_clause = ""


    if telegram_group_id:

        telegram_clause = "AND telegram_group_id=%s"
        params.append(telegram_group_id)


    if active_only:

        active_clause = "AND COALESCE(is_active, TRUE)=TRUE"


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT id,
                   group_id,
                   telegram_group_id,
                   invite_link,
                   created_by,
                   COALESCE(is_active, TRUE),
                   revoked_at,
                   revoked_by,
                   created_at,
                   COALESCE(source, 'bot'),
                   label
            FROM publicity_group_invite_links
            WHERE group_id=%s
            {telegram_clause}
            {active_clause}
            ORDER BY COALESCE(is_active, TRUE) DESC,
                     CASE WHEN COALESCE(source, 'bot')='bot' THEN 0 ELSE 1 END,
                     created_at DESC

        """, tuple(params))

        return [row_to_publicity_invite_link(row) for row in cur.fetchall()]


def get_publicity_invite_link_by_id(link_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   group_id,
                   telegram_group_id,
                   invite_link,
                   created_by,
                   COALESCE(is_active, TRUE),
                   revoked_at,
                   revoked_by,
                   created_at,
                   COALESCE(source, 'bot'),
                   label
            FROM publicity_group_invite_links
            WHERE id=%s
            LIMIT 1

        """, (link_id,))

        return row_to_publicity_invite_link(cur.fetchone())


def revoke_publicity_invite_link(token, group_id, telegram_group_id, invite_link, revoked_by):

    response = None


    if invite_link and telegram_group_id:

        response = revoke_telegram_invite_link(
            token,
            telegram_group_id,
            invite_link
        )


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE publicity_group_invite_links
            SET is_active=FALSE,
                revoked_at=CURRENT_TIMESTAMP,
                revoked_by=%s
            WHERE group_id=%s
            AND invite_link=%s

        """, (
            revoked_by,
            group_id,
            invite_link
        ))

    conn.commit()

    log_event(
        "publicity_invite_link_revoked",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=revoked_by,
        message="Link público de publicidad revocado.",
        metadata={
            "invite_link": mask_invite_link(invite_link),
            "telegram_response_ok": response.get("ok") if isinstance(response, dict) else None
        }
    )

    return response


def revoke_publicity_invite_link_by_id(token, link_id, revoked_by):

    link = get_publicity_invite_link_by_id(link_id)


    if not link:

        return None


    response = revoke_publicity_invite_link(
        token,
        link.get("group_id"),
        link.get("telegram_group_id"),
        link.get("invite_link"),
        revoked_by
    )

    log_event(
        "publicity_invite_link_revoked_by_id",
        category="access",
        severity="info",
        scope="group",
        group_id=link.get("group_id"),
        telegram_group_id=link.get("telegram_group_id"),
        actor_user_id=revoked_by,
        message="Link público de publicidad revocado por ID.",
        metadata={
            "link_id": link_id,
            "source": link.get("source"),
            "invite_link": mask_invite_link(link.get("invite_link"))
        }
    )

    return response


def create_publicity_invite_link(token, group_id, telegram_group_id, created_by, community_type=None):

    current = get_active_publicity_invite_link(
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        source="bot"
    )


    if current:

        revoke_publicity_invite_link(
            token,
            group_id,
            telegram_group_id,
            current.get("invite_link"),
            created_by
        )


    invite_link = create_telegram_public_invite_link(
        token,
        telegram_group_id,
        name="Publicidad pública",
        community_type=community_type
    )


    if not invite_link:

        return None


    saved = save_publicity_invite_link(
        group_id,
        telegram_group_id,
        invite_link,
        created_by
    )

    log_event(
        "publicity_invite_link_created",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=created_by,
        message="Link público de publicidad creado.",
        metadata={
            "invite_link": mask_invite_link(invite_link)
        }
    )

    return saved
