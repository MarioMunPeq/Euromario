"""Tests de la interfaz común de IA (base)."""

import pytest

from gaming_news_digest.ai.base import AIClient, AIError, AISummary, Category, Language


class TestAISummary:
    def test_crea_desde_enum_valido(self):
        summary = AISummary(
            summary="Persona 6 anunciado",
            relevance=5,
            category=Category.LAUNCH,
            language=Language.ENGLISH,
        )
        assert summary.summary == "Persona 6 anunciado"
        assert summary.relevance == 5
        assert summary.category == Category.LAUNCH
        assert summary.language == Language.ENGLISH

    def test_relevance_fuera_de_rango(self):
        with pytest.raises(ValueError):
            AISummary(summary="x", relevance=0, category=Category.LAUNCH, language=Language.ENGLISH)

    def test_category_debe_ser_enum(self):
        with pytest.raises(TypeError):
            AISummary(summary="x", relevance=3, category="lanzamiento", language=Language.ENGLISH)

    def test_language_debe_ser_enum(self):
        with pytest.raises(TypeError):
            AISummary(summary="x", relevance=3, category=Category.LAUNCH, language="en")


class TestAIError:
    def test_guarda_raw_response(self):
        err = AIError("fallo", raw_response='{"bad"}')
        assert err.raw_response == '{"bad"}'

    def test_sin_raw_response(self):
        err = AIError("fallo")
        assert err.raw_response is None


class DummyClient(AIClient):
    def summarize(self, title, body, source_language, game):
        pass


def test_cliente_base_instanciable():
    client = DummyClient()
    assert hasattr(client, "MAX_RETRIES")
    assert hasattr(client, "MAX_CONSECUTIVE_ERRORS")