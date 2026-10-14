"""Tests de la interfaz común de IA (base)."""

import pytest

from gaming_news_digest.ai.base import (
    AIClient,
    AIError,
    AISummary,
    Category,
    Language,
    clean_game_name,
)


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

    def test_game_por_defecto_vacio(self):
        summary = AISummary(
            summary="x", relevance=3, category=Category.UPDATE, language=Language.ENGLISH
        )
        assert summary.game == ""

    def test_game_debe_ser_str(self):
        with pytest.raises(TypeError):
            AISummary(
                summary="x", relevance=3, category=Category.UPDATE,
                language=Language.ENGLISH, game=None,
            )


class TestCleanGameName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Arc Raiders", "Arc Raiders"),
            ('"The Witcher"', "The Witcher"),
            ("  Red   Dead  Redemption 2  ", "Red Dead Redemption 2"),
            ("EA Sports College Football.", "EA Sports College Football"),
        ],
    )
    def test_normaliza_nombres_validos(self, raw, expected):
        assert clean_game_name(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "none",
            "N/A",
            "unknown",
            "Videojuegos",
            "video game",
            "gaming",
            None,
            42,
            ["Arc Raiders"],
            # Frase en vez de nombre
            "the game that the article is about is Arc Raiders",
            # Excesivamente largo
            "A" * 60,
        ],
    )
    def test_rechaza_entradas_no_identificables(self, raw):
        assert clean_game_name(raw) == ""


class TestValidateResponseGame:
    def _validate(self, payload):
        import json

        client = DummyClient()
        return client._validate_response(json.dumps(payload), "media")

    def _base_payload(self, **extra):
        payload = {
            "summary": "Resumen.",
            "relevance": 3,
            "category": "actualizacion",
            "language": "en",
        }
        payload.update(extra)
        return payload

    def test_extrae_juego(self):
        result = self._validate(self._base_payload(game="Arc Raiders"))
        assert result.game == "Arc Raiders"

    def test_juego_ausente_no_es_error(self):
        """El campo es opcional: si falta, el matcher determinista sigue mandando."""
        assert self._validate(self._base_payload()).game == ""

    def test_juego_basura_se_descarta(self):
        assert self._validate(self._base_payload(game="unknown")).game == ""


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