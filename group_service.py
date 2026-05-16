from db import conn


# =========================
# GROUP SERVICE — GET BY INTERNAL ID
# =========================

def get_group_by_id(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       is_active

                FROM groups

                WHERE id=%s

                LIMIT 1

            """, (group_id,))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo grupo por id interno:",
            e
        )

        return None


# =========================
# GROUP SERVICE — GET BY TELEGRAM ID
# =========================

def get_group_by_telegram_id(telegram_group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       is_active

                FROM groups

                WHERE telegram_group_id=%s

                LIMIT 1

            """, (telegram_group_id,))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo grupo por telegram_group_id:",
            e
        )

        return None


# =========================
# GROUP SERVICE — RESOLVE TELEGRAM ID
# =========================

def resolve_telegram_group_id(group_id):

    group = get_group_by_id(group_id)


    if not group:

        return None


    return group[2]


# =========================
# GROUP SERVICE — RESOLVE INTERNAL ID
# =========================

def resolve_internal_group_id(telegram_group_id):

    group = get_group_by_telegram_id(
        telegram_group_id
    )


    if not group:

        return None


    return group[0]


# =========================
# GROUP SERVICE — LIST ACTIVE GROUPS
# =========================

def list_active_groups():

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id

                FROM groups

                WHERE is_active=TRUE
                AND telegram_group_id != 0

                ORDER BY id ASC

            """)

            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando grupos activos:",
            e
        )

        return []


# =========================
# GROUP SERVICE — UPSERT GROUP
# =========================

def upsert_group(name, telegram_group_id, is_active=True):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id
                FROM groups
                WHERE telegram_group_id=%s

                LIMIT 1

            """, (telegram_group_id,))

            row = cur.fetchone()


            if row:

                group_id = row[0]

                cur.execute("""

                    UPDATE groups

                    SET name=%s,
                        is_active=%s

                    WHERE id=%s

                """, (

                    name,
                    is_active,
                    group_id

                ))

            else:

                cur.execute("""

                    INSERT INTO groups
                    (name, telegram_group_id, is_active)

                    VALUES (%s, %s, %s)

                    RETURNING id

                """, (

                    name,
                    telegram_group_id,
                    is_active

                ))

                group_id = cur.fetchone()[0]


            conn.commit()

            return group_id

    except Exception as e:

        conn.rollback()

        print(
            "Error creando/actualizando grupo:",
            e
        )

        return None


# =========================
# GROUP SERVICE — DEACTIVATE GROUP
# =========================

def deactivate_group(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups

                SET is_active=FALSE

                WHERE id=%s

            """, (group_id,))

            affected = cur.rowcount

            conn.commit()

            return affected > 0

    except Exception as e:

        conn.rollback()

        print(
            "Error desactivando grupo:",
            e
        )

        return False


# =========================
# GROUP SERVICE — VALIDATE GROUP EXISTS
# =========================

def group_exists(group_id):

    group = get_group_by_id(group_id)


    return group is not None
