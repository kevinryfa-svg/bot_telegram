import invite_link_service as ils


def test_extract_migrated_chat_id_from_telegram_response():
    # Respuesta real de Telegram cuando un grupo pasa a supergrupo.
    response = {
        "ok": False,
        "error_code": 400,
        "description": "Bad Request: group chat was upgraded to a supergroup chat",
        "parameters": {"migrate_to_chat_id": -1003954636998},
    }
    assert ils.extract_migrated_chat_id(response) == -1003954636998


def test_extract_migrated_chat_id_accepts_string_value():
    response = {"parameters": {"migrate_to_chat_id": "-1003954636998"}}
    assert ils.extract_migrated_chat_id(response) == -1003954636998


def test_extract_migrated_chat_id_returns_none_without_migration():
    assert ils.extract_migrated_chat_id({"ok": False, "description": "Chat_restricted"}) is None
    assert ils.extract_migrated_chat_id({"parameters": {}}) is None
    assert ils.extract_migrated_chat_id({"parameters": {"retry_after": 5}}) is None
    assert ils.extract_migrated_chat_id({}) is None
    assert ils.extract_migrated_chat_id(None) is None
    assert ils.extract_migrated_chat_id("texto") is None


def test_extract_migrated_chat_id_ignores_unparseable_value():
    assert ils.extract_migrated_chat_id({"parameters": {"migrate_to_chat_id": "abc"}}) is None
    assert ils.extract_migrated_chat_id({"parameters": {"migrate_to_chat_id": ""}}) is None
