from datetime import datetime, timedelta

import formatters


def test_format_tiempo_restante_permanent():
    assert formatters.format_tiempo_restante(None) == "♾️ Permanente"


def test_format_tiempo_restante_expired():
    past = datetime.now() - timedelta(days=1)
    assert formatters.format_tiempo_restante(past) == "Expirado"


def test_format_tiempo_restante_future():
    future = datetime.now() + timedelta(days=2, hours=3, minutes=30)
    result = formatters.format_tiempo_restante(future)
    assert result.startswith("2d ")
    assert result.endswith("m")
    assert result not in ("Expirado", "♾️ Permanente")


def test_format_user_display_unknown():
    assert formatters.format_user_display() == "Usuario desconocido"


def test_format_user_display_adds_at_to_username():
    result = formatters.format_user_display(
        user_id=5, username="pepe", first_name="Pepe"
    )
    assert "@pepe" in result
    assert "ID: 5" in result
    assert "Pepe" in result


def test_format_user_display_keeps_existing_at():
    result = formatters.format_user_display(username="@ana")
    assert "@ana" in result
    assert "@@" not in result


def test_format_datetime_none():
    assert formatters.format_datetime(None) == "Sin caducidad"


def test_format_datetime_passthrough_string():
    assert formatters.format_datetime("2026-01-01") == "2026-01-01"


def test_format_permission_value():
    assert formatters.format_permission_value(True) == "✅"
    assert formatters.format_permission_value(False) == "❌"
