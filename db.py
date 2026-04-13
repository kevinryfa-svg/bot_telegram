import os
import psycopg2


DATABASE_URL = os.environ.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)


def create_tables():

    with conn.cursor() as cur:

        # USERS

        cur.execute("""

        CREATE TABLE IF NOT EXISTS users (

            user_id BIGINT PRIMARY KEY,
            expiration TIMESTAMP

        )

        """)

        # CODES

        cur.execute("""

        CREATE TABLE IF NOT EXISTS invite_codes (

            code TEXT PRIMARY KEY,
            duration INTEGER,
            used BOOLEAN DEFAULT FALSE

        )

        """)

        conn.commit()