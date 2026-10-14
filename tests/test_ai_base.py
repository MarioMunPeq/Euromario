"""Tests de la interfaz común de IA (base)."""

import json

import pytest

from gaming_news_digest.ai.base import (
    AIClient,
    AIError,
    AISummary,
    Category,
    Language,
    clean_game_name,
    parse_model_json,
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
    assert hasattr(client, "MAX_429_RETRIES")


VALID = {
    "summary": "LaExpansion trae una nueva zona jugable.",
    "relevance": 4,
    "category": "actualizacion",
    "language": "en",
    "game": "Arc Raiders",
}


class TestParseModelJson:
    """Regresión del fallo que dejó la IA a 0 de 22 llamadas.

    `openai/gpt-oss-20b` es un modelo de razonamiento: devuelve su análisis en
    un canal `<channel>analysis<|message|>` que el regex `<think>` no quitaba,
    así que el JSON llegaba corrupto y TODAS las llamadas acababan en
    AIError. El digest publicado llegó a tener 22 de 66 tarjetas sin resumen.
    """

    def test_json_limpio(self):
        assert parse_model_json(json.dumps(VALID)) == VALID

    def test_canal_de_razonamiento_de_gpt_oss(self):
        raw = (
            "<channel>analysis<|message|>Primero identifico el juego, "
            "despues resumo.<|end|>"
            + json.dumps(VALID)
        )
        assert parse_model_json(raw) == VALID

    def test_bloque_think(self):
        raw = "<think>El articulo habla de una expansion.</think>\n" + json.dumps(VALID)
        assert parse_model_json(raw) == VALID

    def test_bloque_think_sin_cerrar(self):
        raw = "<think>me quedo sin tokens a media respuesta"
        with pytest.raises(AIError):
            parse_model_json(raw)

    def test_bloque_cercado(self):
        raw = "```json\n" + json.dumps(VALID) + "\n```"
        assert parse_model_json(raw) == VALID

    def test_texto_antes_y_despues(self):
        raw = "Claro! Aquí tienes el resumen:\n" + json.dumps(VALID) + "\nEspero sirva."
        assert parse_model_json(raw) == VALID

    def test_texto_sin_json_falla_con_motivo_y_respuesta(self):
        with pytest.raises(AIError) as exc:
            parse_model_json("lo siento, no puedo")
        assert "JSON" in str(exc.value)
        assert exc.value.raw_response == "lo siento, no puedo"

    def test_lista_json_no_es_objeto(self):
        with pytest.raises(AIError, match="no es un objeto"):
            parse_model_json("[1, 2, 3]")

    def test_llave_dentro_de_un_string_no_rompe_el_balanceo(self):
        tricky = dict(VALID, summary='Dice "}" y sigue')
        assert parse_model_json("x " + json.dumps(tricky) + " y") == tricky


class TestValidateResponseTolerante:
    def test_relevance_como_string_se_acepta(self):
        """`"relevance": "3"` es salida habitual; no debe perder el resumen."""
        client = DummyClient()
        raw = json.dumps({**VALID, "relevance": "3"})
        assert client._validate_response(raw).relevance == 3

    def test_relevance_booleano_se_rechaza(self):
        client = DummyClient()
        with pytest.raises(AIError):
            client._validate_response(json.dumps({**VALID, "relevance": True}))

    def test_relevance_fuera_de_rango_se_rechaza(self):
        client = DummyClient()
        with pytest.raises(AIError):
            client._validate_response(json.dumps({**VALID, "relevance": 9}))

    def test_game_ausente_no_es_error(self):
        client = DummyClient()
        payload = {k: v for k, v in VALID.items() if k != "game"}
        assert client._validate_response(json.dumps(payload)).game == ""