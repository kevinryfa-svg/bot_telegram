"""
Entorno mínimo para los tests.

Algunos módulos del bot hacen trabajo al importarse (por ejemplo main.py crea
el objeto Bot de Telegram), así que sin estas variables la recogida de tests
falla antes de ejecutar nada. Definirlas aquí hace que la suite funcione igual
en local y en CI, sin depender de que quien la lance recuerde exportarlas.

Se usa setdefault: si el entorno ya trae un valor, se respeta.
"""

import os

import pytest

os.environ.setdefault("TOKEN", "0000000000:test-token-for-tests")
os.environ.setdefault("GROUP_ID", "0")
os.environ.setdefault("ADMIN_ID", "8761243211")

# Cadena válida en forma, pero a una base de datos inexistente: la conexión es
# perezosa, así que importar módulos no intenta conectarse.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://tests:tests@127.0.0.1:5432/tests_no_conectar"
)

# Los tests no deben llamar a servicios externos.
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("STRIPE_SECRET_KEY", "")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("REENGAGEMENT_ENABLED", "false")


# =========================
# BASE DE DATOS PARA TESTS DE INTEGRACIÓN
# =========================
# TEST_DATABASE_URL apunta a una base de datos real y desechable. Si no está
# definida (o no se puede conectar), los tests que la necesitan se omiten en
# lugar de fallar: así la suite sigue siendo ejecutable sin infraestructura.

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def db_module():
    """Módulo db conectado a la base de datos de pruebas, con esquema creado."""

    if not TEST_DATABASE_URL:

        # Comodidad en local: sin base de datos, estos tests se omiten.
        pytest.skip("TEST_DATABASE_URL no definida: se omiten tests con BD real")


    import psycopg2

    try:

        psycopg2.connect(TEST_DATABASE_URL, sslmode="disable").close()

    except Exception as e:

        # Si se pidió una base de datos y no responde, es un fallo: omitir en
        # silencio dejaría el camino del dinero sin probar y CI en verde.
        pytest.fail(
            f"TEST_DATABASE_URL está definida pero no se puede conectar: {e}"
        )


    import db as db_mod

    def open_test_conn():
        connection = psycopg2.connect(TEST_DATABASE_URL, sslmode="disable")
        connection.autocommit = True
        return connection

    # El bot exige sslmode=require; en pruebas locales no hay TLS.
    db_mod._open_conn = open_test_conn
    db_mod.conn._conn = None

    db_mod.create_tables()

    return db_mod


@pytest.fixture
def clean_db(db_module):
    """Deja las tablas del flujo de compra vacías antes de cada test."""

    tables = (
        "invite_links",
        "payments",
        "payment_transactions",
        "abandoned_checkout_reminders",
        "abandoned_discount_reminders",
        "access_renewal_reminders",
        "user_reengagement",
        "group_delivery_health",
        "payment_incidents",
        "interest_followups",
        "group_payment_provider_configs",
        "group_stripe_coupons",
        "creator_connect_accounts",
        "retention_offers",
        "owner_weekly_digests",
        "business_alerts",
        "upsell_offers",
        "admins",
        "users",
        "plans",
        "banned_users",
        "groups"
    )

    with db_module.conn.cursor() as cur:

        for table in tables:

            try:

                cur.execute(f"DELETE FROM {table}")

            except Exception:

                pass


    return db_module
