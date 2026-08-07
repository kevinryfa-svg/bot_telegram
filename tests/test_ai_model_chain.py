"""
Cadena de modelos de IA.

Un nombre de modelo mal escrito, o un modelo al que la cuenta no tiene acceso,
dejaba al asistente contestando "❌ Error generando respuesta con IA" a todo el
mundo. Con la cadena de reserva eso se convierte en una respuesta correcta con
el modelo anterior.
"""

import ai_service


class FakeCompletions:
    """Cliente de OpenAI simulado: falla con unos modelos y responde con otros."""

    def __init__(self, working_model, error):
        self.working_model = working_model
        self.error = error
        self.calls = []

    def create(self, model=None, **kwargs):
        self.calls.append(model)

        if model != self.working_model:
            raise self.error

        return FakeResponse("respuesta buena")


class FakeResponse:
    def __init__(self, text):
        self.choices = [
            type("Choice", (), {"message": type("Msg", (), {"content": text})()})()
        ]


def install_fake_openai(monkeypatch, working_model, error):
    """Sustituye el cliente real de OpenAI por uno controlado en el test."""

    completions = FakeCompletions(working_model, error)

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": completions})()

    import sys
    import types

    module = types.ModuleType("openai")
    module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", module)

    monkeypatch.setattr(ai_service, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(ai_service, "AI_MAX_ATTEMPTS", 1)
    ai_service._UNAVAILABLE_MODELS.clear()

    return completions


class ModelNotFound(Exception):
    pass


MODEL_NOT_FOUND = ModelNotFound(
    "The model `gpt-inexistente` does not exist or you do not have access to it."
)


def test_chain_puts_the_preferred_model_first(monkeypatch):
    monkeypatch.setattr(ai_service, "AI_MODEL", "modelo-bueno")
    monkeypatch.setattr(ai_service, "AI_FALLBACK_MODELS", ["modelo-reserva"])
    ai_service._UNAVAILABLE_MODELS.clear()

    assert ai_service.resolve_model_chain() == ["modelo-bueno", "modelo-reserva"]


def test_chain_does_not_repeat_a_model(monkeypatch):
    monkeypatch.setattr(ai_service, "AI_MODEL", "mismo")
    monkeypatch.setattr(ai_service, "AI_FALLBACK_MODELS", ["mismo", "otro"])
    ai_service._UNAVAILABLE_MODELS.clear()

    assert ai_service.resolve_model_chain() == ["mismo", "otro"]


def test_missing_model_error_is_recognised():
    assert ai_service.is_model_unavailable_error(MODEL_NOT_FOUND)


def test_network_error_is_not_treated_as_a_missing_model():
    # Un fallo de red debe reintentarse con el mismo modelo, no descartarlo.
    assert not ai_service.is_model_unavailable_error(
        TimeoutError("connection timed out")
    )


def test_unavailable_model_falls_back_and_answers(monkeypatch):
    monkeypatch.setattr(ai_service, "AI_MODEL", "gpt-inexistente")
    monkeypatch.setattr(ai_service, "AI_FALLBACK_MODELS", ["modelo-reserva"])

    calls = install_fake_openai(monkeypatch, "modelo-reserva", MODEL_NOT_FOUND)

    ok, text = ai_service.generate_ai_response("¿cuánto cuesta el acceso?")

    assert ok is True, "la reserva debía contestar en lugar de devolver error"
    assert text == "respuesta buena"
    assert calls.calls == ["gpt-inexistente", "modelo-reserva"]


def test_a_dead_model_is_not_retried_on_the_next_question(monkeypatch):
    monkeypatch.setattr(ai_service, "AI_MODEL", "gpt-inexistente")
    monkeypatch.setattr(ai_service, "AI_FALLBACK_MODELS", ["modelo-reserva"])

    calls = install_fake_openai(monkeypatch, "modelo-reserva", MODEL_NOT_FOUND)

    ai_service.generate_ai_response("primera")
    ai_service.generate_ai_response("segunda")

    # La segunda pregunta no debe pagar otra llamada fallida.
    assert calls.calls == ["gpt-inexistente", "modelo-reserva", "modelo-reserva"]


def test_all_models_failing_returns_an_error_and_does_not_crash(monkeypatch):
    monkeypatch.setattr(ai_service, "AI_MODEL", "a")
    monkeypatch.setattr(ai_service, "AI_FALLBACK_MODELS", ["b"])

    install_fake_openai(monkeypatch, "ninguno", MODEL_NOT_FOUND)

    ok, text = ai_service.generate_ai_response("hola")

    assert ok is False
    assert "❌" in text


def test_chain_recovers_when_every_model_was_marked_dead(monkeypatch):
    monkeypatch.setattr(ai_service, "AI_MODEL", "a")
    monkeypatch.setattr(ai_service, "AI_FALLBACK_MODELS", ["b"])
    ai_service._UNAVAILABLE_MODELS.clear()
    ai_service._UNAVAILABLE_MODELS.update({"a", "b"})

    # Si no quedase ninguno usable, el bot se quedaría sin IA para siempre.
    assert ai_service.resolve_model_chain() == ["a", "b"]


def test_description_names_the_active_model(monkeypatch):
    monkeypatch.setattr(ai_service, "AI_MODEL", "modelo-bueno")
    monkeypatch.setattr(ai_service, "AI_FALLBACK_MODELS", ["modelo-reserva"])
    ai_service._UNAVAILABLE_MODELS.clear()

    description = ai_service.describe_ai_model()

    assert "modelo-bueno" in description
    assert "modelo-reserva" in description
