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

            preview_image_file_id TEXT,

            preview_video_file_id TEXT,

            category TEXT,

            tags TEXT,

            marketplace_badge TEXT,

            preview_mode TEXT DEFAULT 'manual',

            stripe_secret_key TEXT,

            public_visibility TEXT DEFAULT 'start_home',

            is_free_group BOOLEAN DEFAULT FALSE,

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
        # TABLA ADMINS / RBAC
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS admins (

            id SERIAL PRIMARY KEY,

            user_id BIGINT,

            group_id INTEGER,

            role TEXT DEFAULT 'MODERATOR',

            is_super_admin BOOLEAN DEFAULT FALSE,

            can_manage_users BOOLEAN DEFAULT FALSE,

            can_kick_users BOOLEAN DEFAULT FALSE,

            can_ban_users BOOLEAN DEFAULT FALSE,

            can_unban_users BOOLEAN DEFAULT FALSE,

            can_warn_users BOOLEAN DEFAULT FALSE,

            can_reset_warnings BOOLEAN DEFAULT FALSE,

            can_resend_links BOOLEAN DEFAULT FALSE,

            can_recover_access BOOLEAN DEFAULT FALSE,

            can_manage_codes BOOLEAN DEFAULT FALSE,

            can_manage_groups BOOLEAN DEFAULT FALSE,

            can_manage_plans BOOLEAN DEFAULT FALSE,

            can_manage_payments BOOLEAN DEFAULT FALSE,

            can_manage_admins BOOLEAN DEFAULT FALSE,

            can_view_users BOOLEAN DEFAULT FALSE,

            can_view_payments BOOLEAN DEFAULT FALSE,

            can_view_stats BOOLEAN DEFAULT FALSE,

            can_view_logs BOOLEAN DEFAULT FALSE,

            is_active BOOLEAN DEFAULT TRUE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (user_id, group_id)

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
        # TABLAS SOPORTE INTERNO
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS support_tickets (

            id SERIAL PRIMARY KEY,

            user_id BIGINT NOT NULL,

            username TEXT,

            first_name TEXT,

            status TEXT DEFAULT 'open',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS support_messages (

            id SERIAL PRIMARY KEY,

            ticket_id INTEGER,

            sender_type TEXT,

            sender_id BIGINT,

            message_text TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA SOLICITUDES COMERCIALES
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS commercial_requests (

            id SERIAL PRIMARY KEY,

            user_id BIGINT,

            username TEXT,

            first_name TEXT,

            request_type TEXT,

            status TEXT DEFAULT 'pending',

            community_name TEXT,

            community_description TEXT,

            telegram_group_link TEXT,

            bot_name TEXT,

            bot_username TEXT,

            project_description TEXT,

            contact_text TEXT,

            reviewed_by BIGINT,

            reviewed_at TIMESTAMP,

            admin_notes TEXT,

            trial_starts_at TIMESTAMP,

            trial_ends_at TIMESTAMP,

            payment_mode TEXT DEFAULT 'pending',

            stripe_mode TEXT DEFAULT 'pending',

            is_free_group BOOLEAN DEFAULT FALSE,

            approved_group_id INTEGER,

            approved_telegram_group_id BIGINT,

            approved_bot_username TEXT,

            selected_commercial_plan_id INTEGER,

            commercial_subscription_status TEXT DEFAULT 'pending',

            commercial_subscription_until TIMESTAMP,

            requested_public_visibility TEXT DEFAULT 'hidden',

            max_groups_allowed INTEGER DEFAULT 1,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA PLANES COMERCIALES
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS commercial_plans (

            id SERIAL PRIMARY KEY,

            product_type TEXT,

            name TEXT,

            duration_days INTEGER,

            amount INTEGER,

            currency TEXT DEFAULT 'EUR',

            stripe_price_id TEXT,

            is_active BOOLEAN DEFAULT TRUE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA COBROS DEL CREADOR
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS group_payment_settings (

            id SERIAL PRIMARY KEY,

            group_id INTEGER,

            commercial_request_id INTEGER UNIQUE,

            owner_user_id BIGINT,

            stripe_mode TEXT DEFAULT 'owner_stripe',

            owner_stripe_secret_key TEXT,

            owner_stripe_webhook_secret TEXT,

            owner_stripe_publishable_key TEXT,

            is_configured BOOLEAN DEFAULT FALSE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

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

                ALTER TABLE groups
                ADD COLUMN public_visibility TEXT DEFAULT 'start_home'

            """)

        except Exception:
            pass


        group_columns = [

            ("is_free_group", "BOOLEAN DEFAULT FALSE"),
            ("bot_is_admin", "BOOLEAN DEFAULT FALSE"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("added_by", "BIGINT"),
            ("preview_text", "TEXT"),
            ("preview_image_file_id", "TEXT"),
            ("preview_video_file_id", "TEXT"),
            ("category", "TEXT"),
            ("tags", "TEXT"),
            ("marketplace_badge", "TEXT"),
            ("preview_mode", "TEXT DEFAULT 'manual'")

        ]


        for column_name, column_type in group_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE groups
                    ADD COLUMN IF NOT EXISTS {column_name} {column_type}

                """)

            except Exception:

                pass


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
        # MIGRACIÓN SOLICITUDES COMERCIALES
        # =========================

        commercial_request_columns = [

            ("reviewed_by", "BIGINT"),
            ("reviewed_at", "TIMESTAMP"),
            ("admin_notes", "TEXT"),
            ("trial_starts_at", "TIMESTAMP"),
            ("trial_ends_at", "TIMESTAMP"),
            ("payment_mode", "TEXT DEFAULT 'pending'"),
            ("stripe_mode", "TEXT DEFAULT 'pending'"),
            ("is_free_group", "BOOLEAN DEFAULT FALSE"),
            ("approved_group_id", "INTEGER"),
            ("approved_telegram_group_id", "BIGINT"),
            ("approved_bot_username", "TEXT"),
            ("selected_commercial_plan_id", "INTEGER"),
            ("commercial_subscription_status", "TEXT DEFAULT 'pending'"),
            ("commercial_subscription_until", "TIMESTAMP"),
            ("requested_public_visibility", "TEXT DEFAULT 'hidden'"),
            ("creator_setup_status", "TEXT DEFAULT 'awaiting_creator_setup'"),
            ("creator_preview_text", "TEXT"),
            ("max_groups_allowed", "INTEGER DEFAULT 1")

        ]


        for column_name, column_type in commercial_request_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE commercial_requests

                    ADD COLUMN {column_name} {column_type}

                """)

                print(f"Columna añadida en commercial_requests: {column_name}")

            except Exception:

                print(f"Columna ya existe en commercial_requests: {column_name}")


        # =========================
        # PLANES BASE COMERCIALES
        # =========================

        base_commercial_plans = [

            ("shared_bot_space", "1 mes", 30),
            ("shared_bot_space", "3 meses", 90),
            ("shared_bot_space", "6 meses", 180),
            ("shared_bot_space", "1 año", 365)

        ]


        for product_type, name, duration_days in base_commercial_plans:

            try:

                cur.execute("""

                    INSERT INTO commercial_plans (
                        product_type,
                        name,
                        duration_days,
                        amount,
                        stripe_price_id
                    )
                    SELECT %s, %s, %s, NULL, NULL
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM commercial_plans
                        WHERE product_type=%s
                        AND name=%s
                    )

                """, (

                    product_type,
                    name,
                    duration_days,
                    product_type,
                    name

                ))

            except Exception as e:

                print(
                    "Error asegurando plan comercial base:",
                    e
                )


        # =========================
        # MIGRACIÓN ADMINS / RBAC
        # =========================

        admin_columns = [

            ("role", "TEXT DEFAULT 'MODERATOR'"),
            ("can_kick_users", "BOOLEAN DEFAULT FALSE"),
            ("can_ban_users", "BOOLEAN DEFAULT FALSE"),
            ("can_unban_users", "BOOLEAN DEFAULT FALSE"),
            ("can_warn_users", "BOOLEAN DEFAULT FALSE"),
            ("can_reset_warnings", "BOOLEAN DEFAULT FALSE"),
            ("can_resend_links", "BOOLEAN DEFAULT FALSE"),
            ("can_recover_access", "BOOLEAN DEFAULT FALSE"),
            ("can_manage_plans", "BOOLEAN DEFAULT FALSE"),
            ("can_manage_admins", "BOOLEAN DEFAULT FALSE"),
            ("can_view_users", "BOOLEAN DEFAULT FALSE"),
            ("can_view_payments", "BOOLEAN DEFAULT FALSE"),
            ("can_view_logs", "BOOLEAN DEFAULT FALSE"),
            ("is_active", "BOOLEAN DEFAULT TRUE")

        ]


        for column_name, column_type in admin_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE admins

                    ADD COLUMN {column_name} {column_type}

                """)

                print(f"Columna añadida en admins: {column_name}")

            except Exception:

                print(f"Columna ya existe en admins: {column_name}")


        # =========================
        # ASEGURAR UNIQUE admins(user_id, group_id)
        # =========================

        try:

            cur.execute("""

                CREATE UNIQUE INDEX IF NOT EXISTS admins_user_group_unique
                ON admins (user_id, group_id)

            """)

            print("Índice único admins(user_id, group_id) asegurado")

        except Exception as e:

            print(
                "Error asegurando índice único admins:",
                e
            )


        # =========================
        # ASEGURAR SUPER ADMIN GLOBAL
        # =========================

        try:

            cur.execute("""

                INSERT INTO admins
                (
                    user_id,
                    group_id,
                    role,
                    is_super_admin,
                    can_manage_users,
                    can_kick_users,
                    can_ban_users,
                    can_unban_users,
                    can_warn_users,
                    can_reset_warnings,
                    can_resend_links,
                    can_recover_access,
                    can_manage_codes,
                    can_manage_groups,
                    can_manage_plans,
                    can_manage_payments,
                    can_manage_admins,
                    can_view_users,
                    can_view_payments,
                    can_view_stats,
                    can_view_logs,
                    is_active
                )

                VALUES
                (
                    8761243211,
                    0,
                    'SUPER_ADMIN',
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE,
                    TRUE
                )

                ON CONFLICT (user_id, group_id)
                DO UPDATE SET

                    role='SUPER_ADMIN',
                    is_super_admin=TRUE,
                    can_manage_users=TRUE,
                    can_kick_users=TRUE,
                    can_ban_users=TRUE,
                    can_unban_users=TRUE,
                    can_warn_users=TRUE,
                    can_reset_warnings=TRUE,
                    can_resend_links=TRUE,
                    can_recover_access=TRUE,
                    can_manage_codes=TRUE,
                    can_manage_groups=TRUE,
                    can_manage_plans=TRUE,
                    can_manage_payments=TRUE,
                    can_manage_admins=TRUE,
                    can_view_users=TRUE,
                    can_view_payments=TRUE,
                    can_view_stats=TRUE,
                    can_view_logs=TRUE,
                    is_active=TRUE

            """)

        except Exception as e:

            print(
                "Error asegurando super admin:",
                e
            )


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
