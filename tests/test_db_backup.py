"""
Copia de seguridad de la base de datos.

La base de datos de producción se perdió una vez y no existía ninguna copia
propia. Aquí se comprueba lo que puede fallar en silencio: que el volcado
funcione sin pg_dump, que una copia que no llega a nadie no se registre como
correcta, y que un fichero demasiado grande dé un motivo entendible en vez de
un error opaco de Telegram.
"""

import io
import tarfile

import pytest

import db_backup_service as backup


# =========================
# FORMATO Y TEXTOS
# =========================

def test_size_is_readable():
    assert backup.format_size(0) == "0 B"
    assert backup.format_size(512) == "512 B"
    assert backup.format_size(2048) == "2.0 KB"
    assert backup.format_size(5 * 1024 * 1024) == "5.0 MB"


def test_caption_says_what_the_file_is():
    caption = backup.build_backup_caption(
        "backup-20260807.tar.gz", 2048, "CSV (12 tablas)", 12, 340
    )

    assert "backup-20260807.tar.gz" in caption
    assert "2.0 KB" in caption
    assert "12" in caption
    assert "340" in caption


def test_caption_fits_in_a_telegram_caption():
    caption = backup.build_backup_caption("f.tar.gz", 1, "x" * 5000, 1, 1)

    # send_document recorta a 1024; el texto base no debe consumirlo entero.
    assert len(caption[:1024]) <= 1024


# =========================
# CADENCIA
# =========================

def test_backup_is_due_when_there_is_none(monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_ENABLED", True)
    monkeypatch.setattr(backup, "hours_since_last_success", lambda: None)

    assert backup.backup_is_due() is True


def test_backup_is_not_due_right_after_one(monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_ENABLED", True)
    monkeypatch.setattr(backup, "BACKUP_INTERVAL_HOURS", 24)
    monkeypatch.setattr(backup, "hours_since_last_success", lambda: 2.0)

    assert backup.backup_is_due() is False


def test_backup_is_due_once_the_interval_passed(monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_ENABLED", True)
    monkeypatch.setattr(backup, "BACKUP_INTERVAL_HOURS", 24)
    monkeypatch.setattr(backup, "hours_since_last_success", lambda: 30.0)

    assert backup.backup_is_due() is True


def test_disabled_means_never_due(monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_ENABLED", False)

    assert backup.backup_is_due() is False


# =========================
# ENVÍO
# =========================

def test_oversized_backup_explains_itself_instead_of_calling_telegram(monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_MAX_BYTES", 10)

    def explode(*a, **k):
        raise AssertionError("no debe llamarse a Telegram con un fichero enorme")

    monkeypatch.setattr(backup.requests, "post", explode)

    ok, detail = backup.send_backup_document(
        "token", 1, b"x" * 100, "f.gz", "caption"
    )

    assert ok is False
    assert "Telegram" in detail


def test_send_reports_the_api_error(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"ok": False, "description": "chat not found"}

    monkeypatch.setattr(backup.requests, "post", lambda *a, **k: FakeResponse())

    ok, detail = backup.send_backup_document("token", 1, b"x", "f.gz", "c")

    assert ok is False
    assert "chat not found" in detail


def test_send_survives_a_network_failure(monkeypatch):
    def explode(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr(backup.requests, "post", explode)

    ok, detail = backup.send_backup_document("token", 1, b"x", "f.gz", "c")

    assert ok is False
    assert "ConnectionError" in detail


# =========================
# PROCESO COMPLETO (sin base de datos)
# =========================

def stub_backup(monkeypatch, payload=b"datos", filename="backup.tar.gz",
                detail="CSV (3 tablas)"):

    monkeypatch.setattr(backup, "BACKUP_ENABLED", True)
    monkeypatch.setattr(backup, "backup_is_due", lambda: True)
    monkeypatch.setattr(backup, "list_backup_tables", lambda: ["users", "payments"])
    monkeypatch.setattr(backup, "count_rows", lambda table: 5)
    monkeypatch.setattr(
        backup, "build_backup", lambda: (payload, filename, detail)
    )

    recorded = {}

    def fake_record(status, **kwargs):
        recorded["status"] = status
        recorded.update(kwargs)
        return True

    monkeypatch.setattr(backup, "record_backup", fake_record)

    return recorded


def test_successful_run_sends_and_records_ok(monkeypatch):
    recorded = stub_backup(monkeypatch)
    monkeypatch.setattr(
        backup, "send_backup_document", lambda *a, **k: (True, "enviado")
    )

    summary = backup.run_database_backup("token", [111, 222])

    assert summary["created"] is True
    assert summary["sent"] == 2
    assert summary["failed"] == 0
    assert recorded["status"] == "ok"


def test_a_backup_nobody_receives_is_recorded_as_error(monkeypatch):
    """Una copia que no sale de la máquina no protege de nada."""

    recorded = stub_backup(monkeypatch)
    monkeypatch.setattr(
        backup, "send_backup_document", lambda *a, **k: (False, "chat not found")
    )

    summary = backup.run_database_backup("token", [111])

    assert summary["created"] is True
    assert summary["sent"] == 0
    assert recorded["status"] == "error"
    assert "chat not found" in summary["detail"]


def test_failed_dump_is_recorded_and_does_not_raise(monkeypatch):
    recorded = stub_backup(monkeypatch)
    monkeypatch.setattr(backup, "build_backup", lambda: (None, None, "sin pg_dump"))

    summary = backup.run_database_backup("token", [111])

    assert summary["created"] is False
    assert summary["sent"] == 0
    assert recorded["status"] == "error"


def test_run_respects_the_schedule(monkeypatch):
    stub_backup(monkeypatch)
    monkeypatch.setattr(backup, "backup_is_due", lambda: False)
    monkeypatch.setattr(
        backup, "build_backup",
        lambda: pytest.fail("no debía crear copia fuera de horario")
    )

    summary = backup.run_database_backup("token", [111])

    assert summary["skipped"] is True


def test_force_ignores_the_schedule(monkeypatch):
    """El botón "hacer copia ahora" debe funcionar aunque no toque."""

    stub_backup(monkeypatch)
    monkeypatch.setattr(backup, "backup_is_due", lambda: False)
    monkeypatch.setattr(
        backup, "send_backup_document", lambda *a, **k: (True, "enviado")
    )

    summary = backup.run_database_backup("token", [111], force=True)

    assert summary["skipped"] is False
    assert summary["sent"] == 1


def test_disabled_backups_are_skipped(monkeypatch):
    stub_backup(monkeypatch)
    monkeypatch.setattr(backup, "BACKUP_ENABLED", False)

    summary = backup.run_database_backup("token", [111])

    assert summary["skipped"] is True
    assert "DB_BACKUP_ENABLED" in summary["detail"]


# =========================
# CONTRA BASE DE DATOS REAL
# =========================

def test_csv_backup_contains_the_real_tables(clean_db):
    """Sin pg_dump en la imagen, este es el camino que se usa de verdad."""

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (901, 'Comunidad copia', -100999, TRUE)"
        )

    payload, detail = backup.build_csv_backup()

    assert payload, f"no se generó la copia: {detail}"

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        names = tar.getnames()
        groups_csv = tar.extractfile("groups.csv").read().decode("utf-8")

    assert "users.csv" in names
    assert "payments.csv" in names
    assert "invite_links.csv" in names

    # Los datos deben estar dentro, no solo la cabecera.
    assert "Comunidad copia" in groups_csv


def test_backup_skips_the_noisy_activity_tables(clean_db):
    tables = backup.list_backup_tables()

    for skipped in backup.BACKUP_SKIP_TABLES:
        assert skipped not in tables


def test_backup_history_is_stored_and_read_back(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute("DELETE FROM database_backups")

    backup.record_backup(
        "ok",
        method="CSV",
        filename="backup-test.tar.gz",
        size_bytes=1234,
        table_count=7,
        row_count=42,
        detail="prueba"
    )

    last = backup.fetch_last_backup()

    assert last is not None, "la copia no quedó registrada"
    assert last["status"] == "ok"
    assert last["filename"] == "backup-test.tar.gz"
    assert last["size_bytes"] == 1234
    assert last["row_count"] == 42


def test_panel_text_reports_the_last_backup(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute("DELETE FROM database_backups")

    backup.record_backup(
        "ok", method="CSV", filename="backup-panel.tar.gz",
        size_bytes=2048, table_count=7, row_count=42
    )

    text = backup.describe_last_backup()

    assert "backup-panel.tar.gz" in text
    assert "2.0 KB" in text
    assert "✅" in text


def test_panel_text_when_there_are_no_backups_yet(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute("DELETE FROM database_backups")

    text = backup.describe_last_backup()

    assert "Todavía no" in text


def test_failed_backup_shows_the_reason_in_the_panel(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute("DELETE FROM database_backups")

    backup.record_backup("error", detail="pg_dump no está instalado")

    text = backup.describe_last_backup()

    assert "⚠️" in text
    assert "pg_dump no está instalado" in text
