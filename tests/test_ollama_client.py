"""Tests de OllamaClient con mocks (sin red real)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from gaming_news_digest.ai.base import AIError
from gaming_news_digest.ai.ollama_client import OllamaClient


class TestOllamaClient:
    @patch("gaming_news_digest.ai.ollama_client.requests.post")
    def test_respuesta_valida_primera_intento(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": '{"summary": "Persona 6 anunciado", "relevance": 5, "category": "lanzamiento", "language": "en"}'},
        )
        mock_post.return_value.raise_for_status = lambda: None

        client = OllamaClient(model="test-model", base_url="http://test")
        result = client.summarize(
            title="Persona 6 anunciado",
            body="Atlus muestra tráiler",
            source_language="en",
            game="Persona",
        )

        assert result.summary == "Persona 6 anunciado"
        assert result.relevance == 5

    @patch("gaming_news_digest.ai.ollama_client.requests.post")
    def test_json_invalido_reintenta_y_falla(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": "no es json"},
        )
        mock_post.return_value.raise_for_status = lambda: None

        client = OllamaClient(model="test", base_url="http://test")

        with pytest.raises(AIError, match="JSON inválido"):
            client.summarize("t", "b", "en", "game")

    @patch("gaming_news_digest.ai.ollama_client.requests.post")
    def test_timeout_lanza_timeout_error(self, mock_post):
        mock_post.side_effect = requests.Timeout()

        client = OllamaClient()

        with pytest.raises(TimeoutError):
            client.summarize("t", "b", "en", "game")

    @patch("gaming_news_digest.ai.ollama_client.requests.post")
    def test_connection_error_lanza_connection_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError()

        client = OllamaClient()

        with pytest.raises(ConnectionError):
            client.summarize("t", "b", "en", "game")

    @patch("gaming_news_digest.ai.ollama_client.requests.post")
    def test_http_500_lanza_http_error(self, mock_post):
        mock_resp = MagicMock(status_code=500)
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error", response=MagicMock(status_code=500))
        mock_post.return_value = mock_resp

        client = OllamaClient()

        with pytest.raises(requests.HTTPError):
            client.summarize("t", "b", "en", "game")