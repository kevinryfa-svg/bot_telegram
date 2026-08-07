"""
Migraciones numeradas.

create_tables() sabe asegurar que algo existe, pero no ejecutar un cambio
exactamente una vez. Estos tests comprueban lo que puede salir mal: que una
migración no se aplique dos veces, que una que falla no se marque como hecha,
y que dos instancias arrancando a la vez no se pisen.
"""

import pytest

import migrations_service as ms


# =========================
# EL CATÁLOGO DE MIGRACIONES
# =========================

def test_versions_are_unique_and_ordered():
    versions = [version for version, _, _ in ms.MIGRATIONS]

    assert len(versions) == len(set(versions)), "hay versiones repetidas"
    assert versions == sorted(versions), "las migraciones no están en orden"


def test_versions_start_at_one():
    assert min(version for version, _, _ in ms.MIGRATIONS) >= 1


def test_every_migration_has_a_name_and_statements():
    for version, name, statements in ms.MIGRATIONS:
        assert name and isinstance(name, str), f"la {version} no tiene nombre"
        assert statements, f"la {version} no tiene sentencias"

        for statement in statements:
            assert isinstance(statement, str) and statement.strip()


def test_index_migrations_are_written_to_be_rerunnable():
    """
    Aunque el registro impide repetirlas, escribirlas idempotentes evita que un
    índice creado a mano fuera del registro haga fallar el arranque.
    """

    for _, name, statements in ms.MIGRATIONS:
        for statement in statements:
            if statement.upper().startswith("CREATE INDEX"):
                assert "IF NOT EXISTS" in statement.upper(), (
                    f"{name}: CREATE INDEX sin IF NOT EXISTS"
                )


# =========================
# APLICACIÓN CONTRA BASE DE DATOS REAL
# =========================

@pytest.fixture
def fresh_migrations(db_module):
    """Registro de migraciones vacío, para probar un arranque desde cero."""

    with db_module.conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS schema_migrations")

    return ms


def test_migrations_apply_from_scratch(fresh_migrations):
    summary = ms.run_migrations()

    assert summary["failed"] is None, summary["failed"]
    assert [item["version"] for item in summary["applied"]] == [
        version for version, _, _ in ms.MIGRATIONS
    ]
    assert summary["version"] == max(v for v, _, _ in ms.MIGRATIONS)


def test_migrations_are_not_applied_twice(fresh_migrations):
    ms.run_migrations()

    second = ms.run_migrations()

    assert second["applied"] == [], "una migración se aplicó dos veces"
    assert second["failed"] is None


def test_money_path_indexes_exist_after_migrating(fresh_migrations, db_module):
    """
    Estos índices faltaban de verdad: payments solo tenía clave primaria por
    id, y la detección de pagos sin completar cruzaba payment_transactions
    consigo misma por una columna sin indexar.
    """

    ms.run_migrations()

    with db_module.conn.cursor() as cur:
        cur.execute("""
            SELECT i.relname
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
        """)
        names = {row[0] for row in cur.fetchall()}

    for expected in (
        "idx_payments_user_group",
        "idx_payment_transactions_checkout",
        "idx_payment_transactions_user_group",
        "idx_subscriptions_user_group",
    ):
        assert expected in names, f"falta el índice {expected}"


def test_a_failing_migration_is_not_recorded(fresh_migrations, monkeypatch):
    """Marcar como aplicada una migración que falló la haría irrecuperable."""

    monkeypatch.setattr(
        ms, "MIGRATIONS",
        [(9001, "migracion_imposible", ["SELECT * FROM tabla_que_no_existe"])]
    )

    summary = ms.run_migrations()

    assert summary["applied"] == []
    assert summary["failed"]
    assert summary["failed"]["version"] == 9001
    assert 9001 not in (ms.fetch_applied_versions() or set())


def test_a_failing_migration_rolls_back_its_own_changes(fresh_migrations, db_module):
    """La marca va en la misma transacción que el cambio: o todo, o nada."""

    ok, detail = ms.apply_migration(
        9002,
        "crea_y_luego_falla",
        [
            "CREATE TABLE tabla_a_medias (id INTEGER)",
            "SELECT * FROM tabla_que_no_existe",
        ],
    )

    assert ok is False

    with db_module.conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name='tabla_a_medias'"
        )
        assert cur.fetchone()[0] == 0, "quedó una tabla a medio crear"


def test_later_migrations_are_skipped_after_a_failure(fresh_migrations):
    """Aplicarlas fuera de orden es peor que quedarse en la versión actual."""

    monkey = [
        (9101, "falla", ["SELECT * FROM tabla_que_no_existe"]),
        (9102, "no_deberia_aplicarse", ["SELECT 1"]),
    ]

    original = ms.MIGRATIONS
    ms.MIGRATIONS = monkey

    try:
        summary = ms.run_migrations()
    finally:
        ms.MIGRATIONS = original

    assert summary["failed"]["version"] == 9101
    assert 9102 not in (ms.fetch_applied_versions() or set())


def test_running_migrations_records_how_long_they_took(fresh_migrations, db_module):
    ms.run_migrations()

    with db_module.conn.cursor() as cur:
        cur.execute("SELECT version, name, duration_ms FROM schema_migrations")
        rows = cur.fetchall()

    assert rows
    for version, name, duration_ms in rows:
        assert name
        assert duration_ms is not None and duration_ms >= 0


# =========================
# DOS INSTANCIAS A LA VEZ
# =========================

def test_a_second_instance_does_not_migrate_at_the_same_time(fresh_migrations, monkeypatch):
    """
    En los despliegues han convivido dos contenedores un momento (se vio en
    los avisos de 'terminated by other getUpdates'). El que no consigue el
    lock debe apartarse, no migrar en paralelo.
    """

    monkeypatch.setattr(ms, "acquire_lock", lambda: False)

    summary = ms.run_migrations()

    assert summary["skipped"] is True
    assert summary["applied"] == []


def test_the_lock_is_released_even_if_a_migration_fails(fresh_migrations, monkeypatch):
    """Un lock retenido dejaría a las siguientes instancias sin poder migrar."""

    released = []

    monkeypatch.setattr(ms, "acquire_lock", lambda: True)
    monkeypatch.setattr(ms, "release_lock", lambda: released.append(True))
    monkeypatch.setattr(
        ms, "MIGRATIONS",
        [(9201, "falla", ["SELECT * FROM tabla_que_no_existe"])]
    )

    ms.run_migrations()

    assert released, "el lock no se liberó tras un fallo"


def test_the_real_lock_can_be_taken_and_released(db_module):
    assert ms.acquire_lock() is True

    ms.release_lock()

    # Si no se hubiese liberado, este segundo intento fallaría tras esperar.
    assert ms.acquire_lock() is True

    ms.release_lock()


# =========================
# ESTADO PARA EL PANEL
# =========================

def test_panel_text_reports_no_pending_migrations(fresh_migrations):
    ms.run_migrations()

    text = ms.describe_migrations()

    assert "No hay migraciones pendientes" in text
    assert str(max(v for v, _, _ in ms.MIGRATIONS)) in text


def test_panel_text_lists_pending_migrations(fresh_migrations):
    text = ms.describe_migrations()

    assert "Pendientes" in text

    for _, name, _ in ms.MIGRATIONS:
        assert name in text


def test_reading_state_survives_a_broken_database(monkeypatch):
    class BrokenConn:
        def cursor(self):
            raise RuntimeError("base de datos caída")

    monkeypatch.setattr(ms, "conn", BrokenConn())

    # El bot debe arrancar igual: sin migrar, pero sin caerse.
    assert ms.fetch_applied_versions() is None
    assert ms.run_migrations()["skipped"] is True
    assert "No se pudo leer" in ms.describe_migrations()
