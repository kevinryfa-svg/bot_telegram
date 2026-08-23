from db import conn


def normalize_community_type(value):

    return value if value in ("group", "channel") else "group"


def get_community_type(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT community_type
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            row = cur.fetchone()


        return normalize_community_type(row[0] if row else None)

    except Exception as e:

        print("Error obteniendo tipo de comunidad:", e)

        return "group"


def format_community_kind(group_or_type=None):

    community_type = group_or_type


    if isinstance(group_or_type, dict):

        community_type = group_or_type.get("community_type")


    if community_type == "channel":

        return "canal"


    if community_type == "group":

        return "grupo"


    return "comunidad"


def format_community_kind_capitalized(group_or_type=None):

    return format_community_kind(group_or_type).capitalize()


# =========================
# GROUP SERVICE — GET LATEST TELEGRAM GROUP ID
# =========================

def get_latest_telegram_group_id(fallback_group_id=0):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT telegram_group_id

                FROM groups

                WHERE telegram_group_id IS NOT NULL
                AND telegram_group_id != 0

                ORDER BY telegram_group_id DESC

                LIMIT 1

            """)

            row = cur.fetchone()

            if row and row[0]:

                return int(row[0])

    except Exception as e:

        print(
            "Error obteniendo telegram_group_id:",
            e
        )


    return int(fallback_group_id)


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


# =========================
# CÓMO SE LLAMA ESTA COMUNIDAD
# =========================
# Preguntar el nombre de un grupo estaba escrito tres veces —en el router de
# botones, en el expulsador y en el creador de precios de Stripe— y las tres
# resolvían cosas distintas cuando el nombre estaba vacío: una devolvía None,
# otra «la comunidad» y la tercera ni preguntaba. Se nota donde más duele: el
# producto que se crea en Stripe se queda sin el nombre de la comunidad y el
# comprador llega a la pantalla de pago sin saber qué está comprando.

def nombre_de_comunidad(group_id, por_defecto=None):
    """El nombre de una comunidad, o `por_defecto` si no lo hay.

    Nunca lanza: quedarse sin el nombre es un texto más pobre; quedarse sin la
    pantalla es una venta perdida.
    """

    if not group_id:
        return por_defecto

    try:

        with conn.cursor() as cur:

            cur.execute(
                "SELECT NULLIF(name, '') FROM groups WHERE id = %s",
                (group_id,),
            )

            fila = cur.fetchone()

        if fila and fila[0]:
            return fila[0]

    except Exception as e:

        print("No se pudo leer el nombre de la comunidad:", str(e)[:160])

    return por_defecto
