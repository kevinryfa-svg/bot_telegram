import os
import psycopg2


# =========================
# CONEXIÓN DATABASE
# =========================

DATABASE_URL = os.environ.get("DATABASE_URL")

conn = psycopg2.connect(
    DATABASE_URL,
    sslmode="require"
)

conn.autocommit = True


# =========================
# CREAR TABLAS
# =========================

def create_tables():

    with conn.cursor() as cur:

        # =========================
        # TABLA USERS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS users (

            user_id BIGINT PRIMARY KEY,

            username TEXT,

            first_name TEXT,

            expiration TIMESTAMP

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

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


        # =========================
        # TABLA LOG PAGOS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS payments (

            id SERIAL PRIMARY KEY,

            user_id BIGINT,

            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            plan TEXT

        );

        """)


        # =========================
        # TABLA USUARIOS BANEADOS
        # =========================

        cur.execute("""

        CREATE TABLE IF NOT EXISTS banned_users (

            user_id BIGINT PRIMARY KEY,

            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """)


    print("Tablas verificadas correctamente")