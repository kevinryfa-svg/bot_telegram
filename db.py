import os
import psycopg2


# =========================
# CONEXIÓN DATABASE
# =========================

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():

    conn = psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )

    conn.autocommit = True

    return conn


def get_conn():

    conn = psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )

    conn.autocommit = True

    return conn


# Mantener compatibilidad temporal

conn = get_conn()


# =========================
# CREAR TABLAS
# =========================

def create_tables():

    with conn.cursor() as cur:

        # =========================
        # TABLA GROUPS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS groups (

            id SERIAL PRIMARY KEY,

            name TEXT,

            telegram_group_id BIGINT UNIQUE,

            invite_link TEXT,

            preview_text TEXT,

            preview_file_id TEXT,

            stripe_secret_key TEXT,

            bot_is_admin BOOLEAN DEFAULT FALSE,

            is_active BOOLEAN DEFAULT TRUE,

            added_by BIGINT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA USERS (MULTI-GRUPO)
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS users (

            user_id BIGINT,

            group_id INTEGER,

            username TEXT,

            first_name TEXT,

            expiration TIMESTAMP,

            stripe_customer_id TEXT,

            stripe_subscription_id TEXT,

            subscription_active BOOLEAN DEFAULT FALSE,

            last_invite_link TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (user_id, group_id)

        );

        """)


        # =========================
        # ASEGURAR PRIMARY KEY MULTI-GRUPO
        # =========================

        try:

            cur.execute("""

            ALTER TABLE users
            DROP CONSTRAINT IF EXISTS users_pkey;

            """)

            cur.execute("""

            ALTER TABLE users
            ADD PRIMARY KEY (user_id, group_id);

            """)

            print("PRIMARY KEY users corregida")

        except Exception as e:

            print("PK users ya correcta:", e)


        # =========================
        # TABLA ADMINS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS admins (

            id SERIAL PRIMARY KEY,

            user_id BIGINT,

            group_id INTEGER,

            is_super_admin BOOLEAN DEFAULT FALSE,

            can_manage_users BOOLEAN DEFAULT FALSE,

            can_manage_codes BOOLEAN DEFAULT FALSE,

            can_manage_groups BOOLEAN DEFAULT FALSE,

            can_manage_payments BOOLEAN DEFAULT FALSE,

            can_view_stats BOOLEAN DEFAULT FALSE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA PLANES
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS plans (

            id SERIAL PRIMARY KEY,

            group_id INTEGER,

            name TEXT,

            price_id TEXT,

            amount INTEGER,

            currency TEXT,

            duration_days INTEGER,

            is_active BOOLEAN DEFAULT TRUE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA SUSCRIPCIONES
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS subscriptions (

            id SERIAL PRIMARY KEY,

            user_id BIGINT,

            group_id INTEGER,

            stripe_subscription_id TEXT,

            price_id TEXT,

            status TEXT,

            start_date TIMESTAMP,

            end_date TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA CÓDIGOS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS invite_codes (

            id SERIAL PRIMARY KEY,

            code TEXT UNIQUE,

            duration INTEGER,

            used BOOLEAN DEFAULT FALSE,

            group_id INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA PAGOS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS payments (

            id SERIAL PRIMARY KEY,

            user_id BIGINT,

            group_id INTEGER,

            stripe_payment_id TEXT,

            amount INTEGER,

            currency TEXT,

            status TEXT,

            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            plan TEXT

        );

        """)


        # =========================
        # TABLA BANEADOS (MULTI-GRUPO)
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS banned_users (

            user_id BIGINT,

            group_id INTEGER,

            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (user_id, group_id)

        );

        """)


        # =========================
        # TABLA LINKS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS invite_links (

            id SERIAL PRIMARY KEY,

            user_id BIGINT,

            group_id INTEGER,

            invite_link TEXT,

            is_active BOOLEAN DEFAULT TRUE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            revoked_at TIMESTAMP,

            UNIQUE (user_id, group_id)

        );

        """)


        # =========================
        # TABLA WARNINGS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS link_warnings (

            user_id BIGINT,

            group_id INTEGER,

            warnings INTEGER DEFAULT 0,

            PRIMARY KEY (user_id, group_id)

        );

        """)


        # =========================
        # TABLA LOGS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS logs (

            id SERIAL PRIMARY KEY,

            user_id BIGINT,

            group_id INTEGER,

            action TEXT,

            details TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA CONFIG
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS admin_settings (

            id SERIAL PRIMARY KEY,

            key TEXT UNIQUE,

            value TEXT,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # GRUPO DEFAULT
        # =========================

        cur.execute("""

        INSERT INTO groups (

            name,
            telegram_group_id

        )

        VALUES (

            'Grupo Principal',
            0

        )

        ON CONFLICT (telegram_group_id) DO NOTHING;

        """)


        # =========================
        # MIGRACIÓN TABLAS ANTIGUAS
        # =========================

        try:

            cur.execute("""

                ALTER TABLE users
                ADD COLUMN group_id INTEGER DEFAULT 1

            """)

        except Exception:
            pass


        try:

            cur.execute("""

                ALTER TABLE payments
                ADD COLUMN group_id INTEGER DEFAULT 1

            """)

        except Exception:
            pass


        try:

            cur.execute("""

                ALTER TABLE banned_users
                ADD COLUMN group_id INTEGER DEFAULT 1

            """)

        except Exception:
            pass


        try:

            cur.execute("""

                ALTER TABLE link_warnings
                ADD COLUMN group_id INTEGER DEFAULT 1

            """)

        except Exception:
            pass


        # =========================
        # MIGRACIÓN COLUMNAS group_id
        # =========================

        tablas_migracion = [

            ("users", "group_id"),
            ("payments", "group_id"),
            ("banned_users", "group_id"),
            ("link_warnings", "group_id")

        ]

        for tabla, columna in tablas_migracion:

            try:

                cur.execute(f"""

                    ALTER TABLE {tabla}

                    ADD COLUMN {columna} INTEGER DEFAULT 1

                """)

                print(f"Columna añadida en {tabla}: {columna}")

            except Exception:

                print(f"Columna ya existe en {tabla}")


    print("Base de datos FULL preparada 🚀")