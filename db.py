


import psycopg2

import os



conn = psycopg2.connect("postgresql://postgres:PHhoNqjunRfgGjnkqMYeZkrEQUuFMoqR@metro.proxy.rlwy.net:16800/railway")



def create_tables():

    with conn.cursor() as cur:

        cur.execute("""

        CREATE TABLE IF NOT EXISTS users (

            user_id BIGINT PRIMARY KEY,

            expiration TIMESTAMP

        );

        """)

        conn.commit()



