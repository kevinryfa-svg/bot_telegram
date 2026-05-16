from db import conn
from admin_permissions import PERMISSION_COLUMNS, normalize_role, permissions_for_role


# =========================
# ADMIN SERVICE — CREAR / ACTUALIZAR ADMIN
# =========================

def upsert_group_admin(user_id, group_id, role):

    role = normalize_role(role)
    permissions = permissions_for_role(role)


    columns = [
        "user_id",
        "group_id",
        "role",
        "is_super_admin",
        "is_active"
    ] + PERMISSION_COLUMNS


    values = [
        user_id,
        group_id,
        role,
        False,
        True
    ] + [
        permissions[column]
        for column in PERMISSION_COLUMNS
    ]


    placeholders = ", ".join(
        ["%s"] * len(columns)
    )

    column_sql = ", ".join(columns)

    update_sql = ",\n                    ".join([
        f"{column}=EXCLUDED.{column}"
        for column in columns
        if column not in ["user_id", "group_id"]
    ])


    try:

        with conn.cursor() as cur:

            cur.execute(f"""

                INSERT INTO admins
                ({column_sql})

                VALUES ({placeholders})

                ON CONFLICT (user_id, group_id)
                DO UPDATE SET
                    {update_sql}

                RETURNING id

            """, values)

            admin_id = cur.fetchone()[0]

            conn.commit()

            return admin_id

    except Exception as e:

        conn.rollback()

        print(
            "Error creando/actualizando admin:",
            e
        )

        return None


# =========================
# ADMIN SERVICE — LISTAR ADMINS GRUPO
# =========================

def list_group_admins(group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       user_id,
                       role,
                       is_active,
                       created_at

                FROM admins

                WHERE group_id=%s
                AND is_super_admin=FALSE

                ORDER BY created_at DESC

            """, (group_id,))

            return cur.fetchall()

    except Exception as e:

        print(
            "Error listando admins de grupo:",
            e
        )

        return []


# =========================
# ADMIN SERVICE — DESACTIVAR ADMIN
# =========================

def deactivate_group_admin(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE admins

                SET is_active=FALSE

                WHERE user_id=%s
                AND group_id=%s
                AND is_super_admin=FALSE

            """, (

                user_id,
                group_id

            ))

            affected = cur.rowcount

            conn.commit()

            return affected > 0

    except Exception as e:

        conn.rollback()

        print(
            "Error desactivando admin de grupo:",
            e
        )

        return False


# =========================
# ADMIN SERVICE — OBTENER ADMIN
# =========================

def get_group_admin(user_id, group_id):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       user_id,
                       group_id,
                       role,
                       is_active

                FROM admins

                WHERE user_id=%s
                AND group_id=%s

                LIMIT 1

            """, (

                user_id,
                group_id

            ))

            return cur.fetchone()

    except Exception as e:

        print(
            "Error obteniendo admin de grupo:",
            e
        )

        return None


# =========================
# ADMIN SERVICE — CAMBIAR ROL
# =========================

def update_group_admin_role(user_id, group_id, role):

    return upsert_group_admin(
        user_id,
        group_id,
        role
    )
