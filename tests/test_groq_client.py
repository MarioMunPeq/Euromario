"""Tests de GroqClient con mocks (sin red real)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from gaming_news_digest.ai.base import AIError
from gaming_news_digest.ai.groq_client import GroqClient


class TestGroqClient:
    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_respuesta_valida(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": '{"summary": "ok", "relevance": 3, "category": "actualizacion", "language": "en"}'}}]
            },
        )
        mock_post.return_value.raise_for_status = lambda: None

        client = GroqClient(api_key="test-key")
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
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "no json"}}]},
        )
        mock_post.return_value.raise_for_status = lambda: None

        client = GroqClient(api_key="test")

        with pytest.raises(AIError):
            client.summarize("t", "b", "en", "game")

    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_timeout_lanza_timeout_error(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.side_effect = requests.Timeout()

        client = GroqClient(api_key="test")

        with pytest.raises(TimeoutError):
            client.summarize("t", "b", "en", "game")

    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_connection_error_lanza_connection_error(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.side_effect = requests.ConnectionError()

        client = GroqClient(api_key="test")

        with pytest.raises(ConnectionError):
            client.summarize("t", "b", "en", "game")