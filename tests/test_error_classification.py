"""
Regresión: un Conflict transitorio (dos instancias durante un redespliegue)
generaba una alarma crítica y un aviso al propietario por cada aparición.
Once alarmas en seis horas para un problema que se resuelve solo.
"""

import main


def test_conflict_is_transient():
    assert main.is_transient_telegram_error(
        "Conflict",
        "Conflict: terminated by other getUpdates request; "
        "make sure that only one bot instance is running",
    ) is True


def test_network_and_timeout_errors_are_transient():
    for error_type in ("NetworkError", "TimedOut", "RetryAfter", "ReadTimeout"):
        assert main.is_transient_telegram_error(error_type, "") is True


def test_message_wording_alone_is_enough():
    # Aunque el tipo cambie de nombre, el texto delata el mismo problema.
    assert main.is_transient_telegram_error(
        "SomeNewError", "terminated by other getUpdates request"
    ) is True
    assert main.is_transient_telegram_error("Whatever", "Timed out") is True


def test_real_bugs_stay_critical():
    for error_type in ("KeyError", "AttributeError", "TypeError", "BadRequest"):
        assert main.is_transient_telegram_error(error_type, "boom") is False


def test_unknown_error_defaults_to_critical():
    # Ante la duda se avisa: es peor silenciar un fallo real.
    assert main.is_transient_telegram_error("UnknownError", "") is False
    assert main.is_transient_telegram_error("", None) is False


def test_home_reports_telegram_state():
    main.TELEGRAM_STATUS.update(
        {"checked": True, "ok": True, "username": "MiBot", "detail": None}
    )
    assert "MiBot" in main.home()

    main.TELEGRAM_STATUS.update(
        {"checked": True, "ok": False, "username": None, "detail": "Unauthorized"}
    )
    body = main.home()
    assert "SIN conexión a Telegram" in body
    assert "Unauthorized" in body

    main.TELEGRAM_STATUS.update(
        {"checked": False, "ok": None, "username": None, "detail": None}
    )
    assert "sin comprobar" in main.home()


def test_token_check_records_invalid_token(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"ok": False, "error_code": 401, "description": "Unauthorized"}

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: FakeResponse())
    assert main.verify_telegram_token() is False
    assert main.TELEGRAM_STATUS["ok"] is False
    assert main.TELEGRAM_STATUS["detail"] == "Unauthorized"


def test_token_check_records_valid_token(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"ok": True, "result": {"username": "MiBot"}}

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: FakeResponse())
    assert main.verify_telegram_token() is True
    assert main.TELEGRAM_STATUS["username"] == "MiBot"


def test_token_check_survives_network_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("sin red")

    monkeypatch.setattr(main.requests, "get", boom)
    # No debe romper el arranque: estado desconocido, no "roto".
    assert main.verify_telegram_token() is None
    assert main.TELEGRAM_STATUS["ok"] is None
