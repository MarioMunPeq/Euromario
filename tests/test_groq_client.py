"""Tests de GroqClient con mocks (sin red real)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from gaming_news_digest.ai.base import AIError
from gaming_news_digest.ai.groq_client import GroqClient


def _ok_response(content):
    """Respuesta 200 de chat.completions con el JSON en message.content."""
    resp = MagicMock(status_code=200)
    resp.json = lambda: {"choices": [{"message": {"content": content}}]}
    resp.raise_for_status = lambda: None
    resp.text = content
    return resp


VALID_JSON = (
    '{"summary": "ok", "relevance": 3, "category": "actualizacion", '
    '"game": "GTA", "language": "en"}'
)


class TestGroqClient:
    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_respuesta_valida(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.return_value = _ok_response(VALID_JSON)

        client = GroqClient(api_key="test-key", model="openai/gpt-oss-20b")
        result = client.summarize("t", "b", "en", "game")

        assert result.summary == "ok"
        assert result.relevance == 3

    def test_sin_api_key_lanza_value_error(self):
        import os

        if "GROQ_API_KEY" in os.environ:
            del os.environ["GROQ_API_KEY"]
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            GroqClient()

    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_json_invalido_reintenta_y_falla(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.return_value = _ok_response("no json")

        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")

        with pytest.raises(AIError):
            client.summarize("t", "b", "en", "game")

    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_timeout_lanza_timeout_error(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.side_effect = requests.Timeout()

        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")

        with pytest.raises(TimeoutError):
            client.summarize("t", "b", "en", "game")

    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_connection_error_lanza_connection_error(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.side_effect = requests.ConnectionError()

        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")

        with pytest.raises(ConnectionError):
            client.summarize("t", "b", "en", "game")

    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_http_error_404_aborta(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        err_response = MagicMock(status_code=404)
        err_response.text = '{"error": {"code": "model_not_found"}}'
        err_response.headers = {}
        http_error = requests.HTTPError("404")
        http_error.response = err_response
        mock_post.side_effect = http_error

        client = GroqClient(api_key="test", model="model-inexistente")

        with pytest.raises(requests.HTTPError):
            client.summarize("t", "b", "en", "game")


class TestDescubrimientoDeModelo:
    """El cliente pregunta a /models para no depender de un ID hardcodeado."""

    def test_elige_el_preferido_disponible(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        listing = MagicMock(status_code=200)
        listing.json = lambda: {
            "data": [{"id": "whisper-large-v3"}, {"id": "openai/gpt-oss-20b"}]
        }
        listing.raise_for_status = lambda: None

        with patch("gaming_news_digest.ai.groq_client.requests.get", return_value=listing):
            client = GroqClient(api_key="test")
            assert client._resolve_model() == "openai/gpt-oss-20b"

    def test_fallback_a_cualquier_modelo_de_chat(self, monkeypatch):
        """Si los preferidos desaparecen, usa otro de chat antes que romperse."""
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        listing = MagicMock(status_code=200)
        listing.json = lambda: {
            "data": [{"id": "whisper-large-v3"}, {"id": "openai/modelo-nuevo-9b"}]
        }
        listing.raise_for_status = lambda: None

        with patch("gaming_news_digest.ai.groq_client.requests.get", return_value=listing):
            client = GroqClient(api_key="test")
            assert client._resolve_model() == "openai/modelo-nuevo-9b"

    def test_si_el_listado_falla_usa_el_default(self, monkeypatch):
        """Un fallo de red al listar no puede tumbar el pipeline."""
        monkeypatch.setenv("GROQ_API_KEY", "test-key")

        with patch(
            "gaming_news_digest.ai.groq_client.requests.get",
            side_effect=requests.ConnectionError(),
        ):
            client = GroqClient(api_key="test")
            assert client._resolve_model() == "openai/gpt-oss-20b"

    def test_modelo_configurado_no_se_sobrescribe(self, monkeypatch):
        """GROQ_MODEL en el entorno manda sobre el descubrimiento."""
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")

        listing = MagicMock(status_code=200)
        listing.json = lambda: {"data": [{"id": "openai/gpt-oss-20b"}]}
        listing.raise_for_status = lambda: None

        with patch("gaming_news_digest.ai.groq_client.requests.get", return_value=listing):
            client = GroqClient(api_key="test")
            assert client._resolve_model() == "qwen/qwen3.8-27b"


class TestPayload:
    def test_usa_structured_outputs_estricto(self):
        """El modo estricto garantiza JSON valido por construccion."""
        client = GroqClient(api_key="k", model="openai/gpt-oss-20b")
        payload = client._build_payload("openai/gpt-oss-20b", "prompt")

        fmt = payload["response_format"]
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["strict"] is True

        schema = fmt["json_schema"]["schema"]
        # El modo estricto exige TODAS las propiedades en required.
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False
        # Sin 'system' en messages: los modelos de razonamiento rindieron mejor
        # con todas las instrucciones en el mensaje de usuario.
        assert [m["role"] for m in payload["messages"]] == ["user"]
        # include_reasoning False evita que el razonamiento contamine content.
        assert payload["include_reasoning"] is False