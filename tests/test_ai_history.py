import ai_handler as ah


class FakeContext:
    def __init__(self):
        self.user_data = {}


def test_exchange_is_remembered_in_order():
    ctx = FakeContext()
    ah.remember_ai_exchange(ctx, "¿Qué hay?", "Hay 3 comunidades.")
    history = ah.get_ai_history(ctx)
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "¿Qué hay?"
    assert history[1]["content"] == "Hay 3 comunidades."


def test_history_keeps_only_the_most_recent_messages():
    ctx = FakeContext()
    for i in range(10):
        ah.remember_ai_exchange(ctx, f"p{i}", f"r{i}")
    history = ah.get_ai_history(ctx)
    assert len(history) == ah.AI_HISTORY_MAX_MESSAGES
    assert history[-1]["content"] == "r9"


def test_incomplete_exchanges_are_not_stored():
    ctx = FakeContext()
    ah.remember_ai_exchange(ctx, "pregunta", None)
    ah.remember_ai_exchange(ctx, None, "respuesta")
    ah.remember_ai_exchange(ctx, "", "")
    assert ah.get_ai_history(ctx) == []


def test_clear_history_empties_it():
    ctx = FakeContext()
    ah.remember_ai_exchange(ctx, "p", "r")
    ah.clear_ai_history(ctx)
    assert ah.get_ai_history(ctx) == []


def test_corrupt_history_is_ignored_instead_of_crashing():
    ctx = FakeContext()
    ctx.user_data["ai_history"] = "esto no es una lista"
    assert ah.get_ai_history(ctx) == []


def test_stored_messages_are_length_capped():
    ctx = FakeContext()
    ah.remember_ai_exchange(ctx, "A" * 9000, "B" * 9000)
    for message in ah.get_ai_history(ctx):
        assert len(message["content"]) <= 1500
