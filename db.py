import os
import psycopg2


# =========================
# CONEXIÓN DATABASE
# =========================

DATABASE_URL = os.environ.get("DATABASE_URL")
VERBOSE_DB_MIGRATIONS = os.environ.get(
    "VERBOSE_DB_MIGRATIONS",
    "false"
).lower() in ("1", "true", "yes", "on")

DB_MIGRATION_SUMMARY = {
    "checked": 0,
    "created": 0,
    "errors": 0
}


def migration_print(message, status="checked"):

    if status in DB_MIGRATION_SUMMARY:

        DB_MIGRATION_SUMMARY[status] += 1


    if VERBOSE_DB_MIGRATIONS:

        print(message)


def print_db_migration_summary():

    print(
        "Base de datos preparada:",
        f"{DB_MIGRATION_SUMMARY['checked']} columnas verificadas,",
        f"{DB_MIGRATION_SUMMARY['created']} creadas,",
        f"{DB_MIGRATION_SUMMARY['errors']} errores"
    )


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

    DB_MIGRATION_SUMMARY["checked"] = 0
    DB_MIGRATION_SUMMARY["created"] = 0
    DB_MIGRATION_SUMMARY["errors"] = 0

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

            community_type TEXT DEFAULT 'group',

            location_gate_enabled BOOLEAN DEFAULT FALSE,

            allowed_region TEXT,

            allowed_region_type TEXT,

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

            migration_print("PRIMARY KEY users corregida", "created")

        except Exception as e:

            migration_print(f"PK users ya correcta: {e}")


        # =========================
        # MIGRACIÓN USERS / ACCESOS
        # =========================

        user_columns = [

            ("subscription_active", "BOOLEAN DEFAULT FALSE"),
            ("last_invite_link", "TEXT")

        ]


        for column_name, column_type in user_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE users
                    ADD COLUMN {column_name} {column_type}

                """)

                migration_print(f"Columna añadida en users: {column_name}", "created")

            except Exception:

                migration_print(f"Columna ya existe en users: {column_name}")


        # =========================
        # FAVORITOS Y STATS MARKETPLACE
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS community_favorites (

            id SERIAL PRIMARY KEY,

            user_id BIGINT NOT NULL,

            group_id INTEGER NOT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(user_id, group_id)

        );

        """)

        cur.execute("""

        CREATE TABLE IF NOT EXISTS community_stats (

            group_id INTEGER PRIMARY KEY,

            preview_views INTEGER DEFAULT 0,

            access_clicks INTEGER DEFAULT 0,

            favorites_count INTEGER DEFAULT 0,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


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

            can_edit_group_texts BOOLEAN DEFAULT FALSE,

            can_edit_marketplace_preview BOOLEAN DEFAULT FALSE,

            can_respond_group_support BOOLEAN DEFAULT FALSE,

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

            payment_provider TEXT DEFAULT 'stripe',

            stripe_price_id TEXT,

            paypal_plan_id TEXT,

            provider_price_id TEXT,

            amount INTEGER,

            currency TEXT,

            duration_days INTEGER,

            is_active BOOLEAN DEFAULT TRUE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        for column_name, column_type in [
            ("payment_provider", "TEXT DEFAULT 'stripe'"),
            ("stripe_price_id", "TEXT"),
            ("paypal_plan_id", "TEXT"),
            ("provider_price_id", "TEXT")
        ]:

            try:

                cur.execute(f"""

                    ALTER TABLE plans
                    ADD COLUMN IF NOT EXISTS {column_name} {column_type}

                """)

            except Exception:

                pass


        try:

            cur.execute("""

                UPDATE plans
                SET payment_provider=COALESCE(payment_provider, 'stripe'),
                    stripe_price_id=COALESCE(stripe_price_id, price_id),
                    provider_price_id=COALESCE(provider_price_id, price_id)
                WHERE price_id IS NOT NULL
                AND (
                    payment_provider IS NULL
                    OR stripe_price_id IS NULL
                    OR provider_price_id IS NULL
                )

            """)

        except Exception:

            pass


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
        # TABLA TRANSACCIONES MULTIGATEWAY
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS payment_transactions (

            id SERIAL PRIMARY KEY,

            provider TEXT NOT NULL DEFAULT 'stripe',

            status TEXT NOT NULL DEFAULT 'pending',

            payment_scope TEXT DEFAULT 'platform',

            purchase_type TEXT,

            user_id BIGINT,

            owner_user_id BIGINT,

            group_id INTEGER,

            plan_id INTEGER,

            platform_product_key TEXT,

            provider_config_id INTEGER,

            provider_config_scope TEXT DEFAULT 'platform',

            destination_type TEXT DEFAULT 'platform_account',

            destination_ref TEXT,

            amount INTEGER,

            currency TEXT,

            external_payment_id TEXT,

            external_checkout_id TEXT,

            idempotency_key TEXT UNIQUE,

            metadata JSONB DEFAULT '{}'::jsonb,

            metadata_json JSONB DEFAULT '{}'::jsonb,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # AUDITORÍA DE ACTIVIDAD DE USUARIOS EN EL BOT
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS bot_user_events (

            id BIGSERIAL PRIMARY KEY,

            user_id BIGINT,

            username TEXT,

            first_name TEXT,

            last_name TEXT,

            event_type TEXT,

            event_key TEXT,

            group_id BIGINT,

            plan_id BIGINT,

            payment_provider TEXT,

            payment_scope TEXT,

            metadata_json JSONB DEFAULT '{}'::jsonb,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        for index_sql in (
            "CREATE INDEX IF NOT EXISTS idx_bot_user_events_user_id ON bot_user_events (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_bot_user_events_group_id ON bot_user_events (group_id)",
            "CREATE INDEX IF NOT EXISTS idx_bot_user_events_event_type ON bot_user_events (event_type)",
            "CREATE INDEX IF NOT EXISTS idx_bot_user_events_created_at ON bot_user_events (created_at)",
            "CREATE INDEX IF NOT EXISTS idx_bot_user_events_event_key ON bot_user_events (event_key)",
            "CREATE INDEX IF NOT EXISTS idx_bot_user_events_payment_provider ON bot_user_events (payment_provider)"
        ):

            try:

                cur.execute(index_sql)

            except Exception:

                pass


        # =========================
        # IA — INTERACCIONES Y FEEDBACK
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS ai_interactions (

            id BIGSERIAL PRIMARY KEY,

            user_id BIGINT,

            role TEXT,

            group_id BIGINT,

            intent TEXT,

            question TEXT,

            response_summary TEXT,

            source_context_summary TEXT,

            success BOOLEAN DEFAULT TRUE,

            feedback_rating TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        for index_sql in (
            "CREATE INDEX IF NOT EXISTS idx_ai_interactions_user_id ON ai_interactions (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_ai_interactions_group_id ON ai_interactions (group_id)",
            "CREATE INDEX IF NOT EXISTS idx_ai_interactions_intent ON ai_interactions (intent)",
            "CREATE INDEX IF NOT EXISTS idx_ai_interactions_created_at ON ai_interactions (created_at)"
        ):

            try:

                cur.execute(index_sql)

            except Exception:

                pass


        # =========================
        # TABLA BANEADOS (MULTI-GRUPO)
        # =========================

        payment_transaction_columns = [

            ("payment_scope", "TEXT DEFAULT 'platform'"),
            ("purchase_type", "TEXT"),
            ("owner_user_id", "BIGINT"),
            ("platform_product_key", "TEXT"),
            ("provider_config_id", "INTEGER"),
            ("provider_config_scope", "TEXT DEFAULT 'platform'"),
            ("destination_type", "TEXT DEFAULT 'platform_account'"),
            ("destination_ref", "TEXT"),
            ("metadata_json", "JSONB DEFAULT '{}'::jsonb")

        ]


        for column_name, column_type in payment_transaction_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE payment_transactions
                    ADD COLUMN IF NOT EXISTS {column_name} {column_type}

                """)

            except Exception:

                pass


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

            telegram_group_id BIGINT,

            invite_link TEXT,

            is_active BOOLEAN DEFAULT TRUE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            revoked_at TIMESTAMP,

            UNIQUE (user_id, group_id)

        );

        """)


        invite_link_columns = [

            ("telegram_group_id", "BIGINT"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("revoked_at", "TIMESTAMP")

        ]


        for column_name, column_type in invite_link_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE invite_links
                    ADD COLUMN {column_name} {column_type}

                """)

                migration_print(f"Columna añadida en invite_links: {column_name}", "created")

            except Exception:

                migration_print(f"Columna ya existe en invite_links: {column_name}")


        try:

            cur.execute("""

                UPDATE invite_links il
                SET telegram_group_id = g.telegram_group_id
                FROM groups g
                WHERE il.telegram_group_id IS NULL
                AND il.group_id = g.id

            """)

            cur.execute("""

                UPDATE invite_links il
                SET telegram_group_id = g.telegram_group_id
                FROM groups g
                WHERE il.telegram_group_id IS NULL
                AND il.group_id = g.telegram_group_id

            """)

        except Exception as e:

            print("Error normalizando telegram_group_id en invite_links:", e)



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
        # TABLA AUDIT LOGS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS audit_logs (

            id SERIAL PRIMARY KEY,

            scope TEXT DEFAULT 'global',

            group_id INTEGER,

            telegram_group_id BIGINT,

            actor_user_id BIGINT,

            target_user_id BIGINT,

            event_type TEXT,

            category TEXT,

            severity TEXT DEFAULT 'info',

            message TEXT,

            metadata JSONB,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # CLOSED BETA MONITOR
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS beta_monitor_events (

            id SERIAL PRIMARY KEY,

            event_type TEXT,

            severity TEXT DEFAULT 'info',

            user_id BIGINT,

            group_id INTEGER,

            telegram_group_id BIGINT,

            message TEXT,

            metadata JSONB,

            resolved BOOLEAN DEFAULT FALSE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # BETA SMOKE TEST RUNS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS beta_smoke_test_runs (

            id SERIAL PRIMARY KEY,

            started_by BIGINT,

            status TEXT,

            total_checks INTEGER DEFAULT 0,

            passed_checks INTEGER DEFAULT 0,

            failed_checks INTEGER DEFAULT 0,

            warning_checks INTEGER DEFAULT 0,

            report JSONB,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # BETA CYCLES
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS beta_cycles (

            id SERIAL PRIMARY KEY,

            name TEXT,

            status TEXT DEFAULT 'active',

            phase TEXT,

            starts_at TIMESTAMP,

            ends_at TIMESTAMP,

            created_by BIGINT,

            completed_at TIMESTAMP,

            notes TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # CUSTOMER SATISFACTION
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS customer_satisfaction_surveys (

            id SERIAL PRIMARY KEY,

            title TEXT,

            description TEXT,

            audience TEXT,

            status TEXT DEFAULT 'draft',

            created_by BIGINT,

            sent_at TIMESTAMP,

            closed_at TIMESTAMP,

            sent_count INTEGER DEFAULT 0,

            failed_count INTEGER DEFAULT 0,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS customer_satisfaction_questions (

            id SERIAL PRIMARY KEY,

            survey_id INTEGER,

            question_key TEXT,

            question_text TEXT,

            category TEXT,

            answer_type TEXT,

            is_active BOOLEAN DEFAULT TRUE,

            sort_order INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS customer_satisfaction_responses (

            id SERIAL PRIMARY KEY,

            survey_id INTEGER,

            user_id BIGINT,

            role TEXT,

            started_at TIMESTAMP,

            completed_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (survey_id, user_id)

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS customer_satisfaction_answers (

            id SERIAL PRIMARY KEY,

            response_id INTEGER,

            question_id INTEGER,

            rating INTEGER,

            text_answer TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (response_id, question_id)

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS customer_satisfaction_sent (

            id SERIAL PRIMARY KEY,

            survey_id INTEGER,

            group_id INTEGER,

            user_id BIGINT,

            campaign_id TEXT DEFAULT 'default',

            status TEXT DEFAULT 'sent',

            sent_at TIMESTAMP,

            completed_at TIMESTAMP,

            failed_at TIMESTAMP,

            failure_reason TEXT,

            created_by BIGINT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_satisfaction_sent_unique
        ON customer_satisfaction_sent (survey_id, COALESCE(group_id, 0), user_id, COALESCE(campaign_id, 'default'));

        """)


        cur.execute("""

        CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_satisfaction_sent_unique_plain
        ON customer_satisfaction_sent (survey_id, group_id, user_id, campaign_id);

        """)


        cur.execute("""

        CREATE INDEX IF NOT EXISTS idx_customer_satisfaction_sent_status
        ON customer_satisfaction_sent (status);

        """)


        cur.execute("""

        CREATE INDEX IF NOT EXISTS idx_customer_satisfaction_sent_group
        ON customer_satisfaction_sent (group_id);

        """)


        for column_sql in (
            "ALTER TABLE customer_satisfaction_surveys ADD COLUMN IF NOT EXISTS sent_count INTEGER DEFAULT 0",
            "ALTER TABLE customer_satisfaction_surveys ADD COLUMN IF NOT EXISTS failed_count INTEGER DEFAULT 0",
            "ALTER TABLE customer_satisfaction_surveys ADD COLUMN IF NOT EXISTS group_id INTEGER",
            "ALTER TABLE customer_satisfaction_surveys ADD COLUMN IF NOT EXISTS campaign_id TEXT DEFAULT 'default'",
            "ALTER TABLE customer_satisfaction_surveys ADD COLUMN IF NOT EXISTS send_mode TEXT DEFAULT 'pending'",
            "ALTER TABLE customer_satisfaction_surveys ADD COLUMN IF NOT EXISTS skipped_completed_count INTEGER DEFAULT 0",
            "ALTER TABLE customer_satisfaction_surveys ADD COLUMN IF NOT EXISTS skipped_already_sent_count INTEGER DEFAULT 0",
            "ALTER TABLE customer_satisfaction_responses ADD COLUMN IF NOT EXISTS role TEXT",
            "ALTER TABLE customer_satisfaction_responses ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
            "ALTER TABLE customer_satisfaction_responses ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
            "ALTER TABLE customer_satisfaction_answers ADD COLUMN IF NOT EXISTS rating INTEGER",
            "ALTER TABLE customer_satisfaction_answers ADD COLUMN IF NOT EXISTS text_answer TEXT"
        ):

            try:

                cur.execute(column_sql)

            except Exception as e:

                print("Error asegurando columna customer_satisfaction:", e)


        default_satisfaction_questions = [
            ("general_utility", "Utilidad general del bot", "general", "rating_1_5", 1),
            ("ease_of_use", "Facilidad de uso", "ux", "rating_1_5", 2),
            ("menu_clarity", "Claridad de los menús", "ux", "rating_1_5", 3),
            ("community_access", "Proceso de acceso a comunidades", "access", "rating_1_5", 4),
            ("payments_access", "Pagos y acceso premium", "payments", "rating_1_5", 5),
            ("promo_codes", "Códigos promocionales", "codes", "rating_1_5", 6),
            ("support", "Soporte", "support", "rating_1_5", 7),
            ("speed", "Velocidad/respuesta del bot", "performance", "rating_1_5", 8),
            ("trust_security", "Confianza/seguridad", "security", "rating_1_5", 9),
            ("recommendation", "¿Recomendarías este bot?", "recommendation", "rating_1_5", 10),
            ("improvements", "¿Qué mejorarías?", "feedback", "text", 11),
            ("final_comment", "Comentario final", "feedback", "text", 12)
        ]

        for question_key, question_text, category, answer_type, sort_order in default_satisfaction_questions:

            cur.execute("""

                INSERT INTO customer_satisfaction_questions
                (
                    survey_id,
                    question_key,
                    question_text,
                    category,
                    answer_type,
                    is_active,
                    sort_order
                )
                SELECT NULL, %s, %s, %s, %s, TRUE, %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM customer_satisfaction_questions
                    WHERE survey_id IS NULL
                    AND question_key=%s
                )

            """, (
                question_key,
                question_text,
                category,
                answer_type,
                sort_order,
                question_key
            ))


        # =========================
        # BACKUP PREMIUM — FASE 1
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS backup_subscriptions (

            id SERIAL PRIMARY KEY,

            owner_user_id BIGINT NOT NULL,

            status TEXT DEFAULT 'inactive',

            plan_type TEXT DEFAULT 'text',

            billing_provider TEXT DEFAULT 'manual',

            stripe_subscription_id TEXT,

            current_period_start TIMESTAMP,

            current_period_end TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS group_backup_configs (

            id SERIAL PRIMARY KEY,

            owner_user_id BIGINT NOT NULL,

            source_group_id INTEGER NOT NULL,

            source_telegram_group_id BIGINT NOT NULL,

            destination_group_id INTEGER NOT NULL,

            destination_telegram_group_id BIGINT NOT NULL,

            subscription_id INTEGER,

            mode TEXT DEFAULT 'text',

            status TEXT DEFAULT 'inactive',

            copy_topics BOOLEAN DEFAULT FALSE,

            last_checked_at TIMESTAMP,

            last_message_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (owner_user_id, source_group_id, destination_group_id)

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS backup_message_log (

            id SERIAL PRIMARY KEY,

            config_id INTEGER NOT NULL,

            source_group_id INTEGER,

            destination_group_id INTEGER,

            source_message_id INTEGER,

            destination_message_id INTEGER,

            source_topic_id INTEGER,

            destination_topic_id INTEGER,

            message_type TEXT,

            status TEXT,

            error_code TEXT,

            error_message TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS backup_errors (

            id SERIAL PRIMARY KEY,

            config_id INTEGER,

            owner_user_id BIGINT,

            severity TEXT DEFAULT 'warning',

            error_type TEXT,

            message TEXT,

            metadata JSONB,

            resolved BOOLEAN DEFAULT FALSE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS backup_destination_tokens (

            id SERIAL PRIMARY KEY,

            token TEXT UNIQUE NOT NULL,

            owner_user_id BIGINT NOT NULL,

            source_group_id INTEGER NOT NULL,

            source_telegram_group_id BIGINT NOT NULL,

            status TEXT DEFAULT 'pending',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            expires_at TIMESTAMP,

            destination_telegram_group_id BIGINT,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        try:

            cur.execute("""

                ALTER TABLE group_backup_configs
                ADD COLUMN IF NOT EXISTS show_original_author BOOLEAN DEFAULT FALSE

            """)

        except Exception:

            pass


        # =========================
        # SERVICIOS EXTRA PARA OWNERS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS owner_addon_products (

            id SERIAL PRIMARY KEY,

            code TEXT UNIQUE NOT NULL,

            name TEXT NOT NULL,

            description TEXT,

            monthly_price_cents INTEGER NOT NULL DEFAULT 0,

            currency TEXT NOT NULL DEFAULT 'eur',

            stripe_price_id TEXT,

            is_active BOOLEAN NOT NULL DEFAULT TRUE,

            created_at TIMESTAMP DEFAULT NOW(),

            updated_at TIMESTAMP DEFAULT NOW()

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS owner_addon_subscriptions (

            id SERIAL PRIMARY KEY,

            owner_user_id BIGINT NOT NULL,

            group_id INTEGER,

            addon_code TEXT NOT NULL,

            stripe_customer_id TEXT,

            stripe_subscription_id TEXT,

            stripe_price_id TEXT,

            status TEXT NOT NULL DEFAULT 'inactive',

            current_period_start TIMESTAMP,

            current_period_end TIMESTAMP,

            cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,

            created_at TIMESTAMP DEFAULT NOW(),

            updated_at TIMESTAMP DEFAULT NOW()

        );

        """)


        for column_name, column_sql in [
            ("code", "TEXT"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("monthly_price_cents", "INTEGER NOT NULL DEFAULT 0"),
            ("currency", "TEXT NOT NULL DEFAULT 'eur'"),
            ("stripe_price_id", "TEXT"),
            ("is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT NOW()"),
            ("updated_at", "TIMESTAMP DEFAULT NOW()")
        ]:

            try:

                cur.execute(
                    f"ALTER TABLE owner_addon_products ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"
                )

            except Exception as e:

                migration_print(
                    f"Error añadiendo columna owner_addon_products.{column_name}: {e}",
                    "errors"
                )


        for column_name, column_sql in [
            ("owner_user_id", "BIGINT"),
            ("group_id", "INTEGER"),
            ("addon_code", "TEXT"),
            ("stripe_customer_id", "TEXT"),
            ("stripe_subscription_id", "TEXT"),
            ("stripe_price_id", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'inactive'"),
            ("current_period_start", "TIMESTAMP"),
            ("current_period_end", "TIMESTAMP"),
            ("cancel_at_period_end", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("created_at", "TIMESTAMP DEFAULT NOW()"),
            ("updated_at", "TIMESTAMP DEFAULT NOW()")
        ]:

            try:

                cur.execute(
                    f"ALTER TABLE owner_addon_subscriptions ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"
                )

            except Exception as e:

                migration_print(
                    f"Error añadiendo columna owner_addon_subscriptions.{column_name}: {e}",
                    "errors"
                )


        for index_name, index_sql in [
            (
                "idx_owner_addon_products_code",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_owner_addon_products_code ON owner_addon_products(code)"
            ),
            (
                "idx_owner_addon_subscriptions_owner_user_id",
                "CREATE INDEX IF NOT EXISTS idx_owner_addon_subscriptions_owner_user_id ON owner_addon_subscriptions(owner_user_id)"
            ),
            (
                "idx_owner_addon_subscriptions_group_id",
                "CREATE INDEX IF NOT EXISTS idx_owner_addon_subscriptions_group_id ON owner_addon_subscriptions(group_id)"
            ),
            (
                "idx_owner_addon_subscriptions_addon_code",
                "CREATE INDEX IF NOT EXISTS idx_owner_addon_subscriptions_addon_code ON owner_addon_subscriptions(addon_code)"
            ),
            (
                "idx_owner_addon_subscriptions_status",
                "CREATE INDEX IF NOT EXISTS idx_owner_addon_subscriptions_status ON owner_addon_subscriptions(status)"
            ),
            (
                "idx_owner_addon_subscriptions_stripe_subscription_id",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_owner_addon_subscriptions_stripe_subscription_id ON owner_addon_subscriptions(stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL"
            )
        ]:

            try:

                cur.execute(index_sql)

            except Exception as e:

                migration_print(
                    f"Error creando índice {index_name}: {e}",
                    "errors"
                )


        for code, name, description, monthly_price_cents, currency in [
            (
                "ad_promo",
                "Publicidad automática",
                "Publica vídeos promocionales de tu comunidad en canales/grupos publicitarios.",
                1999,
                "eur"
            ),
            (
                "backups",
                "Backups automáticos",
                "Guarda copias de seguridad periódicas de la configuración y datos operativos de tu comunidad.",
                999,
                "eur"
            ),
            (
                "bundle_ads_backups",
                "Pack Publicidad + Backups",
                "Incluye publicidad automática y backups automáticos para tu comunidad.",
                2499,
                "eur"
            )
        ]:

            cur.execute("""

                INSERT INTO owner_addon_products
                (
                    code,
                    name,
                    description,
                    monthly_price_cents,
                    currency
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (code) DO NOTHING

            """, (
                code,
                name,
                description,
                monthly_price_cents,
                currency
            ))


        # =========================
        # BACKUPS AUTOMÁTICOS PARA OWNERS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS owner_backup_jobs (

            id SERIAL PRIMARY KEY,

            owner_user_id BIGINT NOT NULL,

            group_id INTEGER NOT NULL,

            frequency TEXT NOT NULL DEFAULT 'weekly',

            is_active BOOLEAN NOT NULL DEFAULT TRUE,

            last_run_at TIMESTAMP,

            next_run_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT NOW(),

            updated_at TIMESTAMP DEFAULT NOW()

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS owner_backup_files (

            id SERIAL PRIMARY KEY,

            owner_user_id BIGINT NOT NULL,

            group_id INTEGER NOT NULL,

            job_id INTEGER,

            backup_type TEXT NOT NULL DEFAULT 'manual',

            status TEXT NOT NULL DEFAULT 'created',

            file_format TEXT NOT NULL DEFAULT 'json',

            file_path TEXT,

            file_size_bytes INTEGER,

            summary TEXT,

            created_at TIMESTAMP DEFAULT NOW()

        );

        """)


        for column_name, column_sql in [
            ("owner_user_id", "BIGINT NOT NULL"),
            ("group_id", "INTEGER NOT NULL"),
            ("frequency", "TEXT NOT NULL DEFAULT 'weekly'"),
            ("is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("last_run_at", "TIMESTAMP"),
            ("next_run_at", "TIMESTAMP"),
            ("created_at", "TIMESTAMP DEFAULT NOW()"),
            ("updated_at", "TIMESTAMP DEFAULT NOW()")
        ]:

            try:

                cur.execute(
                    f"ALTER TABLE owner_backup_jobs ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"
                )

            except Exception as e:

                migration_print(
                    f"Error añadiendo columna owner_backup_jobs.{column_name}: {e}",
                    "errors"
                )


        for column_name, column_sql in [
            ("owner_user_id", "BIGINT NOT NULL"),
            ("group_id", "INTEGER NOT NULL"),
            ("job_id", "INTEGER"),
            ("backup_type", "TEXT NOT NULL DEFAULT 'manual'"),
            ("status", "TEXT NOT NULL DEFAULT 'created'"),
            ("file_format", "TEXT NOT NULL DEFAULT 'json'"),
            ("file_path", "TEXT"),
            ("file_size_bytes", "INTEGER"),
            ("summary", "TEXT"),
            ("created_at", "TIMESTAMP DEFAULT NOW()")
        ]:

            try:

                cur.execute(
                    f"ALTER TABLE owner_backup_files ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"
                )

            except Exception as e:

                migration_print(
                    f"Error añadiendo columna owner_backup_files.{column_name}: {e}",
                    "errors"
                )


        for index_name, index_sql in [
            (
                "idx_owner_backup_jobs_owner_user_id",
                "CREATE INDEX IF NOT EXISTS idx_owner_backup_jobs_owner_user_id ON owner_backup_jobs(owner_user_id)"
            ),
            (
                "idx_owner_backup_jobs_group_id",
                "CREATE INDEX IF NOT EXISTS idx_owner_backup_jobs_group_id ON owner_backup_jobs(group_id)"
            ),
            (
                "idx_owner_backup_jobs_is_active",
                "CREATE INDEX IF NOT EXISTS idx_owner_backup_jobs_is_active ON owner_backup_jobs(is_active)"
            ),
            (
                "idx_owner_backup_jobs_next_run_at",
                "CREATE INDEX IF NOT EXISTS idx_owner_backup_jobs_next_run_at ON owner_backup_jobs(next_run_at)"
            ),
            (
                "idx_owner_backup_jobs_owner_group_unique",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_owner_backup_jobs_owner_group_unique ON owner_backup_jobs(owner_user_id, group_id)"
            ),
            (
                "idx_owner_backup_files_owner_user_id",
                "CREATE INDEX IF NOT EXISTS idx_owner_backup_files_owner_user_id ON owner_backup_files(owner_user_id)"
            ),
            (
                "idx_owner_backup_files_group_id",
                "CREATE INDEX IF NOT EXISTS idx_owner_backup_files_group_id ON owner_backup_files(group_id)"
            ),
            (
                "idx_owner_backup_files_created_at",
                "CREATE INDEX IF NOT EXISTS idx_owner_backup_files_created_at ON owner_backup_files(created_at)"
            )
        ]:

            try:

                cur.execute(index_sql)

            except Exception as e:

                migration_print(
                    f"Error creando índice {index_name}: {e}",
                    "errors"
                )


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

            last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            group_id INTEGER

        );

        """)


        try:

            cur.execute("""

                ALTER TABLE support_tickets
                ADD COLUMN IF NOT EXISTS group_id INTEGER

            """)

        except Exception:

            pass


        try:

            cur.execute("""

                CREATE INDEX IF NOT EXISTS idx_support_tickets_group_id
                ON support_tickets(group_id)

            """)

        except Exception:

            pass


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
        # TABLA REVISIONES MANUALES DE UBICACIÓN
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS location_manual_reviews (

            id SERIAL PRIMARY KEY,

            user_id BIGINT NOT NULL,

            group_id INTEGER NOT NULL,

            telegram_group_id BIGINT,

            support_ticket_id INTEGER,

            requested_by_user_id BIGINT,

            approved_by_user_id BIGINT,

            status TEXT DEFAULT 'pending',

            failed_latitude DOUBLE PRECISION,

            failed_longitude DOUBLE PRECISION,

            allowed_region TEXT,

            allowed_region_type TEXT,

            question_1_reason TEXT,

            question_2_residence_proof TEXT,

            question_3_valid_location_eta TEXT,

            owner_note TEXT,

            user_note TEXT,

            expires_at TIMESTAMP,

            completed_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        for index_name, index_sql in [
            (
                "idx_location_manual_reviews_user_group",
                "CREATE INDEX IF NOT EXISTS idx_location_manual_reviews_user_group ON location_manual_reviews(user_id, group_id)"
            ),
            (
                "idx_location_manual_reviews_group_status",
                "CREATE INDEX IF NOT EXISTS idx_location_manual_reviews_group_status ON location_manual_reviews(group_id, status)"
            ),
            (
                "idx_location_manual_reviews_status_expires",
                "CREATE INDEX IF NOT EXISTS idx_location_manual_reviews_status_expires ON location_manual_reviews(status, expires_at)"
            ),
            (
                "idx_location_manual_reviews_support_ticket",
                "CREATE INDEX IF NOT EXISTS idx_location_manual_reviews_support_ticket ON location_manual_reviews(support_ticket_id)"
            )
        ]:

            try:

                cur.execute(index_sql)

            except Exception as e:

                migration_print(
                    f"Error creando índice {index_name}: {e}",
                    "errors"
                )


        # =========================
        # TABLAS PROMOCIÓN AUTOMÁTICA SUPERADMIN
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS ad_promo_campaigns (

            id SERIAL PRIMARY KEY,

            paid_group_id INTEGER NOT NULL,

            source_chat_id BIGINT,

            source_chat_title TEXT,

            source_chat_type TEXT,

            promo_group_telegram_id BIGINT NOT NULL,

            promo_group_title TEXT,

            promo_group_type TEXT DEFAULT 'group',

            is_active BOOLEAN DEFAULT TRUE,

            is_paused BOOLEAN DEFAULT FALSE,

            auto_capture_enabled BOOLEAN DEFAULT TRUE,

            randomize_media BOOLEAN DEFAULT TRUE,

            ai_copy_enabled BOOLEAN DEFAULT TRUE,

            batch_size INTEGER DEFAULT 5,

            interval_minutes INTEGER DEFAULT 60,

            max_posts INTEGER DEFAULT 50,

            delete_old_posts BOOLEAN DEFAULT TRUE,

            bot_link TEXT,

            marketplace_link TEXT,

            default_caption TEXT,

            offer_text TEXT,

            price_text TEXT,

            cta_text TEXT,

            tone TEXT DEFAULT 'conversion',

            watermark_mode TEXT DEFAULT 'caption',

            watermark_text TEXT,

            watermark_position TEXT DEFAULT 'bottom_right',

            watermark_max_file_size_mb INTEGER DEFAULT 50,

            watermark_max_duration_seconds INTEGER DEFAULT 180,

            watermark_opacity NUMERIC DEFAULT 0.65,

            last_offer_check_at TIMESTAMP,

            next_offer_check_at TIMESTAMP,

            last_run_at TIMESTAMP,

            next_run_at TIMESTAMP,

            created_by_user_id BIGINT,

            updated_by_user_id BIGINT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)

        for column_name, column_sql in [
            ("watermark_mode", "TEXT DEFAULT 'caption'"),
            ("watermark_text", "TEXT"),
            ("watermark_position", "TEXT DEFAULT 'bottom_right'"),
            ("watermark_max_file_size_mb", "INTEGER DEFAULT 50"),
            ("watermark_max_duration_seconds", "INTEGER DEFAULT 180"),
            ("watermark_opacity", "NUMERIC DEFAULT 0.65")
        ]:

            try:

                cur.execute(
                    f"ALTER TABLE ad_promo_campaigns ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"
                )

            except Exception as e:

                migration_print(
                    f"Error añadiendo columna ad_promo_campaigns.{column_name}: {e}",
                    "errors"
                )


        cur.execute("""

            UPDATE ad_promo_campaigns
            SET watermark_mode='caption'
            WHERE watermark_mode IS NULL
            OR watermark_mode NOT IN ('none', 'caption', 'video')

        """)

        cur.execute("""

            UPDATE ad_promo_campaigns
            SET watermark_position='bottom_right'
            WHERE watermark_position IS NULL
            OR watermark_position NOT IN ('bottom_right', 'bottom_left', 'top_right', 'top_left', 'center')

        """)

        cur.execute("""

        CREATE TABLE IF NOT EXISTS ad_promo_media (

            id SERIAL PRIMARY KEY,

            campaign_id INTEGER NOT NULL,

            paid_group_id INTEGER,

            source_chat_id BIGINT,

            source_message_id BIGINT,

            telegram_file_id TEXT NOT NULL,

            file_unique_id TEXT,

            media_type TEXT DEFAULT 'video',

            duration INTEGER,

            width INTEGER,

            height INTEGER,

            file_size BIGINT,

            original_caption TEXT,

            is_active BOOLEAN DEFAULT TRUE,

            usage_count INTEGER DEFAULT 0,

            last_sent_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)

        cur.execute("""

        CREATE TABLE IF NOT EXISTS ad_promo_sent_posts (

            id SERIAL PRIMARY KEY,

            campaign_id INTEGER NOT NULL,

            promo_group_telegram_id BIGINT NOT NULL,

            message_id BIGINT NOT NULL,

            media_id INTEGER,

            batch_id TEXT,

            caption_text TEXT,

            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            deleted_at TIMESTAMP,

            delete_error TEXT

        );

        """)

        cur.execute("""

        CREATE TABLE IF NOT EXISTS ad_promo_copy_variants (

            id SERIAL PRIMARY KEY,

            campaign_id INTEGER NOT NULL,

            text TEXT NOT NULL,

            source TEXT DEFAULT 'ai',

            is_active BOOLEAN DEFAULT TRUE,

            usage_count INTEGER DEFAULT 0,

            last_used_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)

        for index_name, index_sql in [
            (
                "idx_ad_promo_campaigns_active_next_run",
                "CREATE INDEX IF NOT EXISTS idx_ad_promo_campaigns_active_next_run ON ad_promo_campaigns(is_active, is_paused, next_run_at)"
            ),
            (
                "idx_ad_promo_campaigns_source_chat",
                "CREATE INDEX IF NOT EXISTS idx_ad_promo_campaigns_source_chat ON ad_promo_campaigns(source_chat_id)"
            ),
            (
                "idx_ad_promo_media_campaign_active",
                "CREATE INDEX IF NOT EXISTS idx_ad_promo_media_campaign_active ON ad_promo_media(campaign_id, is_active)"
            ),
            (
                "idx_ad_promo_sent_posts_campaign",
                "CREATE INDEX IF NOT EXISTS idx_ad_promo_sent_posts_campaign ON ad_promo_sent_posts(campaign_id, deleted_at, sent_at)"
            ),
            (
                "idx_ad_promo_copy_campaign_active",
                "CREATE INDEX IF NOT EXISTS idx_ad_promo_copy_campaign_active ON ad_promo_copy_variants(campaign_id, is_active)"
            ),
            (
                "idx_ad_promo_media_unique_file",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ad_promo_media_unique_file ON ad_promo_media(campaign_id, file_unique_id) WHERE file_unique_id IS NOT NULL"
            ),
            (
                "idx_ad_promo_media_unique_source_message",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ad_promo_media_unique_source_message ON ad_promo_media(campaign_id, source_chat_id, source_message_id) WHERE source_chat_id IS NOT NULL AND source_message_id IS NOT NULL"
            )
        ]:

            try:

                cur.execute(index_sql)

            except Exception as e:

                migration_print(
                    f"Error creando índice {index_name}: {e}",
                    "errors"
                )


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

            expired_at TIMESTAMP,

            delete_after TIMESTAMP,

            last_expiry_reminder_at TIMESTAMP,

            previous_public_visibility TEXT,

            last_interaction_user_id BIGINT,

            last_interaction_username TEXT,

            last_interaction_first_name TEXT,

            last_interaction_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # PERFIL COMERCIAL ESTABLE DEL CREATOR
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS commercial_creator_profiles (

            user_id BIGINT PRIMARY KEY,

            group_quota INTEGER DEFAULT 1,

            commercial_status TEXT,

            subscription_until TIMESTAMP NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # MENSAJES SOLICITUDES COMERCIALES
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS commercial_request_messages (

            id SERIAL PRIMARY KEY,

            commercial_request_id INTEGER NOT NULL,

            sender_type TEXT NOT NULL,

            sender_id BIGINT NOT NULL,

            message_text TEXT NOT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

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
        # TABLAS CÓDIGOS PROMOCIONALES COMERCIALES
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS commercial_promo_codes (

            id SERIAL PRIMARY KEY,

            code TEXT UNIQUE NOT NULL,

            duration_days INTEGER NOT NULL,

            max_uses INTEGER DEFAULT 1,

            uses_count INTEGER DEFAULT 0,

            is_active BOOLEAN DEFAULT TRUE,

            created_by BIGINT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS commercial_promo_code_redemptions (

            id SERIAL PRIMARY KEY,

            promo_code_id INTEGER,

            code TEXT,

            user_id BIGINT,

            commercial_request_id INTEGER,

            group_id INTEGER,

            duration_days INTEGER,

            redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLAS CÓDIGOS PROMOCIONALES POR GRUPO
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS group_user_promo_codes (

            id SERIAL PRIMARY KEY,

            group_id INTEGER NOT NULL,

            telegram_group_id BIGINT,

            owner_user_id BIGINT,

            code TEXT UNIQUE NOT NULL,

            duration_days INTEGER,

            is_permanent BOOLEAN DEFAULT FALSE,

            max_uses INTEGER DEFAULT 1,

            used_count INTEGER DEFAULT 0,

            is_active BOOLEAN DEFAULT TRUE,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            expires_at TIMESTAMP

        );

        """)


        cur.execute("""

        CREATE TABLE IF NOT EXISTS group_user_promo_redemptions (

            id SERIAL PRIMARY KEY,

            code_id INTEGER,

            group_id INTEGER,

            user_id BIGINT,

            redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            invite_link TEXT,

            expiration TIMESTAMP

        );

        """)


        # =========================
        # TABLA VINCULACIÓN PENDIENTE DE GRUPOS DE CREADORES
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS creator_group_link_requests (

            id SERIAL PRIMARY KEY,

            user_id BIGINT NOT NULL,

            commercial_request_id INTEGER NOT NULL,

            telegram_group_id BIGINT NOT NULL,

            community_type TEXT DEFAULT 'group',

            group_name TEXT,

            status TEXT DEFAULT 'pending',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            confirmed_at TIMESTAMP,

            cancelled_at TIMESTAMP

        );

        """)


        try:

            cur.execute("""

                ALTER TABLE creator_group_link_requests
                ADD COLUMN IF NOT EXISTS community_type TEXT DEFAULT 'group'

            """)

            cur.execute("""

                UPDATE creator_group_link_requests
                SET community_type='group'
                WHERE community_type IS NULL
                OR community_type NOT IN ('group', 'channel')

            """)

        except Exception:

            pass


        # =========================
        # TABLA PREVIEW DINÁMICO — VÍDEOS DE GRUPO
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS group_preview_videos (

            id SERIAL PRIMARY KEY,

            group_id INTEGER,

            telegram_group_id BIGINT,

            message_id BIGINT,

            video_file_id TEXT,

            caption TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            is_active BOOLEAN DEFAULT TRUE

        );

        """)


        # =========================
        # TABLA VERIFICACIONES DE UBICACIÓN
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS group_location_verifications (

            id SERIAL PRIMARY KEY,

            group_id INTEGER,

            user_id BIGINT,

            region_type TEXT,

            country TEXT,

            region TEXT,

            province TEXT,

            verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            status TEXT

        );

        """)


        location_verification_columns = [

            ("region_type", "TEXT"),
            ("country", "TEXT"),
            ("region", "TEXT"),
            ("province", "TEXT"),
            ("status", "TEXT"),
            ("verified_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

        ]


        for column_name, column_type in location_verification_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE group_location_verifications
                    ADD COLUMN IF NOT EXISTS {column_name} {column_type}

                """)

            except Exception:

                pass


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


        cur.execute("""

        CREATE TABLE IF NOT EXISTS platform_payment_provider_configs (

            id SERIAL PRIMARY KEY,

            provider TEXT NOT NULL UNIQUE,

            is_enabled BOOLEAN DEFAULT FALSE,

            status TEXT DEFAULT 'not_configured',

            provider_config_scope TEXT DEFAULT 'platform',

            destination_type TEXT DEFAULT 'platform_account',

            destination_ref TEXT,

            public_config_json JSONB DEFAULT '{}'::jsonb,

            metadata_json JSONB DEFAULT '{}'::jsonb,

            encrypted_config_json TEXT,

            secret_ref TEXT,

            secret_status TEXT DEFAULT 'not_configured',

            last_verified_at TIMESTAMP,

            verified_by BIGINT,

            verification_error TEXT,

            masked_public_summary TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        platform_payment_provider_columns = [

            ("provider_config_scope", "TEXT DEFAULT 'platform'"),
            ("destination_type", "TEXT DEFAULT 'platform_account'"),
            ("destination_ref", "TEXT"),
            ("metadata_json", "JSONB DEFAULT '{}'::jsonb"),
            ("encrypted_config_json", "TEXT"),
            ("secret_status", "TEXT DEFAULT 'not_configured'"),
            ("last_verified_at", "TIMESTAMP"),
            ("verified_by", "BIGINT"),
            ("verification_error", "TEXT"),
            ("masked_public_summary", "TEXT")

        ]


        for column_name, column_type in platform_payment_provider_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE platform_payment_provider_configs
                    ADD COLUMN IF NOT EXISTS {column_name} {column_type}

                """)

            except Exception:

                pass


        cur.execute("""

        CREATE TABLE IF NOT EXISTS group_payment_provider_configs (

            id SERIAL PRIMARY KEY,

            owner_user_id BIGINT NOT NULL,

            group_id INTEGER NOT NULL,

            provider TEXT NOT NULL,

            is_enabled BOOLEAN DEFAULT FALSE,

            status TEXT DEFAULT 'not_configured',

            provider_config_scope TEXT DEFAULT 'group',

            destination_type TEXT DEFAULT 'group_config',

            destination_ref TEXT,

            public_config_json JSONB DEFAULT '{}'::jsonb,

            metadata_json JSONB DEFAULT '{}'::jsonb,

            encrypted_config_json TEXT,

            secret_ref TEXT,

            secret_status TEXT DEFAULT 'not_configured',

            last_verified_at TIMESTAMP,

            verified_by BIGINT,

            verification_error TEXT,

            masked_public_summary TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(group_id, provider)

        );

        """)


        group_payment_provider_columns = [

            ("provider_config_scope", "TEXT DEFAULT 'group'"),
            ("destination_type", "TEXT DEFAULT 'group_config'"),
            ("destination_ref", "TEXT"),
            ("metadata_json", "JSONB DEFAULT '{}'::jsonb"),
            ("encrypted_config_json", "TEXT"),
            ("secret_status", "TEXT DEFAULT 'not_configured'"),
            ("last_verified_at", "TIMESTAMP"),
            ("verified_by", "BIGINT"),
            ("verification_error", "TEXT"),
            ("masked_public_summary", "TEXT")

        ]


        for column_name, column_type in group_payment_provider_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE group_payment_provider_configs
                    ADD COLUMN IF NOT EXISTS {column_name} {column_type}

                """)

            except Exception:

                pass


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
            ("community_type", "TEXT DEFAULT 'group'"),
            ("bot_is_admin", "BOOLEAN DEFAULT FALSE"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("added_by", "BIGINT"),
            ("preview_text", "TEXT"),
            ("preview_file_id", "TEXT"),
            ("preview_image_file_id", "TEXT"),
            ("preview_video_file_id", "TEXT"),
            ("category", "TEXT"),
            ("tags", "TEXT"),
            ("marketplace_badge", "TEXT"),
            ("preview_mode", "TEXT DEFAULT 'manual'"),
            ("location_gate_enabled", "BOOLEAN DEFAULT FALSE"),
            ("allowed_region", "TEXT"),
            ("allowed_region_type", "TEXT")

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

                UPDATE groups
                SET community_type='group'
                WHERE community_type IS NULL
                OR community_type NOT IN ('group', 'channel')

            """)

            cur.execute("""

                CREATE INDEX IF NOT EXISTS idx_groups_community_type
                ON groups(community_type)

            """)

        except Exception as e:

            print("Error normalizando community_type en groups:", e)


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
            ("max_groups_allowed", "INTEGER DEFAULT 1"),
            ("expired_at", "TIMESTAMP"),
            ("delete_after", "TIMESTAMP"),
            ("last_expiry_reminder_at", "TIMESTAMP"),
            ("previous_public_visibility", "TEXT"),
            ("last_interaction_user_id", "BIGINT"),
            ("last_interaction_username", "TEXT"),
            ("last_interaction_first_name", "TEXT"),
            ("last_interaction_at", "TIMESTAMP")

        ]


        for column_name, column_type in commercial_request_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE commercial_requests

                    ADD COLUMN {column_name} {column_type}

                """)

                migration_print(f"Columna añadida en commercial_requests: {column_name}", "created")

            except Exception:

                migration_print(f"Columna ya existe en commercial_requests: {column_name}")


        # =========================
        # MIGRACIÓN PERFIL COMERCIAL CREATOR
        # Mantener el mayor cupo ya asignado en solicitudes legacy.
        # =========================

        try:

            cur.execute("""

                INSERT INTO commercial_creator_profiles
                (
                    user_id,
                    group_quota,
                    commercial_status,
                    subscription_until,
                    updated_at
                )
                SELECT user_id,
                       GREATEST(COALESCE(MAX(max_groups_allowed), 1), 1),
                       MAX(status),
                       MAX(commercial_subscription_until),
                       NOW()
                FROM commercial_requests
                WHERE user_id IS NOT NULL
                GROUP BY user_id
                ON CONFLICT (user_id)
                DO UPDATE SET
                    group_quota=GREATEST(
                        commercial_creator_profiles.group_quota,
                        EXCLUDED.group_quota
                    ),
                    commercial_status=COALESCE(
                        commercial_creator_profiles.commercial_status,
                        EXCLUDED.commercial_status
                    ),
                    subscription_until=COALESCE(
                        commercial_creator_profiles.subscription_until,
                        EXCLUDED.subscription_until
                    ),
                    updated_at=NOW()

            """)

        except Exception as e:

            print("Error migrando commercial_creator_profiles:", e)


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
            ("can_edit_group_texts", "BOOLEAN DEFAULT FALSE"),
            ("can_edit_marketplace_preview", "BOOLEAN DEFAULT FALSE"),
            ("can_respond_group_support", "BOOLEAN DEFAULT FALSE"),
            ("is_active", "BOOLEAN DEFAULT TRUE")

        ]


        for column_name, column_type in admin_columns:

            try:

                cur.execute(f"""

                    ALTER TABLE admins

                    ADD COLUMN {column_name} {column_type}

                """)

                migration_print(f"Columna añadida en admins: {column_name}", "created")

            except Exception:

                migration_print(f"Columna ya existe en admins: {column_name}")


        try:

            cur.execute("""

                UPDATE admins
                SET can_manage_codes=TRUE
                WHERE role='GROUP_OWNER'
                AND COALESCE(can_manage_codes, FALSE)=FALSE

            """)

        except Exception as e:

            print(
                "Error asegurando can_manage_codes para GROUP_OWNER:",
                e
            )


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

                migration_print(f"Columna añadida en {tabla}: {columna}", "created")

            except Exception:

                migration_print(f"Columna ya existe en {tabla}")


    print_db_migration_summary()
