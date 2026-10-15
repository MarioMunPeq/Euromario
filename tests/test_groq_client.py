"""Tests de GroqClient con mocks (sin red real)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from gaming_news_digest.ai.base import AIError
from gaming_news_digest.ai.groq_client import GroqClient

VALID_JSON = (
    '{"summary": "ok", "relevance": 3, "category": "actualizacion", '
    '"game": "GTA", "language": "en"}'
)


def _ok_response(content, headers=None):
    """Respuesta 200 de chat.completions con el JSON en message.content."""
    resp = MagicMock(status_code=200)
    resp.json = lambda: {
        "choices": [{"message": {"content": content}}],
        "usage": {"total_tokens": 500},
    }
    resp.raise_for_status = MagicMock()
    resp.text = content
    resp.headers = headers or {}
    return resp


def _error_response(status, body, headers=None):
    resp = MagicMock(status_code=status)
    resp.text = body
    resp.headers = headers or {}

    def _raise():
        raise requests.HTTPError(f"{status} error", response=resp)

    resp.raise_for_status = _raise
    return resp


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
    def test_http_error_fatal_propaga(self, mock_post, monkeypatch):
        """Un 400 que no es de esquema debe seguir abortando."""
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.return_value = _error_response(404, '{"code": "model_not_found"}')

        client = GroqClient(api_key="test", model="model-inexistente")

        with pytest.raises(requests.HTTPError, match="404"):
            client.summarize("t", "b", "en", "game")


class TestDegradacionDeEsquema:
    """El 400 json_validate_failed tumbaba el run entero."""

    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_reintenta_sin_esquema_y_no_aborta(self, mock_post, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        schema_error = _error_response(
            400,
            '{"error":{"code":"json_validate_failed","message":'
            '"missing properties: \'category\'"}}',
        )
        mock_post.side_effect = [schema_error, _ok_response(VALID_JSON)]

        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")
        result = client.summarize("t", "b", "en", "game")

        assert result.summary == "ok"
        # 1er intento con esquema, 2do sin el.
        assert "response_format" in mock_post.call_args_list[0].kwargs["json"]
        assert "response_format" not in mock_post.call_args_list[1].kwargs["json"]

    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_esquema_siempre_pide_category(self, mock_post, monkeypatch):
        """El modo estricto exige TODAS las claves: no se puede omitir category
        para Reddit aunque el prompt la omita (bug que daba 400)."""
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.return_value = _ok_response(VALID_JSON)

        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")
        client.summarize("t", "b", "en", "Videojuegos", source_type="reddit")

        schema = mock_post.call_args.kwargs["json"]["response_format"]["json_schema"][
            "schema"
        ]
        assert "category" in schema["required"]
        assert "category" in schema["properties"]


class TestCuboDeTokens:
    """El plan gratuito da 8K TPM; hay que repartir el gasto."""

    def test_espera_cuando_se_pasa_el_techo(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")
        client._tpm_limit = 1000

        # 900 tokens ya gastados en la ventana actual.
        client._spend.append((monotonic_stub(), 900))

        slept = []
        with patch("gaming_news_digest.ai.groq_client.time.sleep", side_effect=slept.append):
            client._wait_for_budget(500)

        assert slept, "deberia haber esperado antes de reventar el TPM"
        assert slept[0] > 0

    def test_no_espera_si_hay_presupuesto(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")
        client._tpm_limit = 8000
        client._spend.append((monotonic_stub(), 100))

        with patch("gaming_news_digest.ai.groq_client.time.sleep") as m:
            client._wait_for_budget(500)

        m.assert_not_called()

    def test_aprende_el_tpm_real_de_la_cabecera(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")

        client._record_usage(
            _ok_response(VALID_JSON, headers={"x-ratelimit-limit-tokens": "50000"}),
            fallback=400,
        )

        assert client._tpm_limit == 50000

    def test_purga_la_ventana_tras_un_minuto(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")

        import time as _time

        client._spend.append((_time.monotonic() - 120, 9999))
        client._prune(_time.monotonic())

        assert client._budget_used(_time.monotonic()) == 0


class TestRateLimit:
    @patch("gaming_news_digest.ai.groq_client.time.sleep")
    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_429_reintenta_y_se_recupera(self, mock_post, mock_sleep, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        too_many = _error_response(
            429,
            '{"error":{"code":"rate_limit_exceeded"}}',
            headers={"x-ratelimit-reset-tokens": "7.5", "Retry-After": "2"},
        )
        mock_post.side_effect = [too_many, too_many, _ok_response(VALID_JSON)]

        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")
        result = client.summarize("t", "b", "en", "game")

        assert result.summary == "ok"
        # Prioriza x-ratelimit-reset-tokens sobre Retry-After.
        assert mock_sleep.call_args_list[0].args[0] == pytest.approx(8.5)

    @patch("gaming_news_digest.ai.groq_client.time.sleep")
    @patch("gaming_news_digest.ai.groq_client.requests.post")
    def test_429_persistente_da_aierror(self, mock_post, mock_sleep, monkeypatch):
        """Agotar los reintentos de 429 debe ser AIError (recuperable por el
        pipeline), no un HTTPError que aborta toda la ejecucion."""
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_post.return_value = _error_response(
            429, '{"code":"rate_limit_exceeded"}', headers={"Retry-After": "1"}
        )

        client = GroqClient(api_key="test", model="openai/gpt-oss-20b")

        with pytest.raises(AIError, match="429"):
            client.summarize("t", "b", "en", "game")


class TestDescubrimientoDeModelo:
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
        monkeypatch.setenv("GROQ_API_KEY", "test-key")

        with patch(
            "gaming_news_digest.ai.groq_client.requests.get",
            side_effect=requests.ConnectionError(),
        ):
            client = GroqClient(api_key="test")
            assert client._resolve_model() == "openai/gpt-oss-20b"

    def test_modelo_configurado_no_se_sobrescribe(self, monkeypatch):
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
        client = GroqClient(api_key="k", model="openai/gpt-oss-20b")
        payload = client._build_payload("openai/gpt-oss-20b", "prompt")

        fmt = payload["response_format"]
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["strict"] is True

        schema = fmt["json_schema"]["schema"]
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False
        assert [m["role"] for m in payload["messages"]] == ["user"]
        assert payload["include_reasoning"] is False
        # Los tokens de razonamiento se contabilizan aparte.
        assert "max_tokens" not in payload
        assert payload["max_completion_tokens"] > 0

    def test_prompt_compacto_para_no_reventar_el_tpm(self):
        """Las instrucciones no pueden duplicarse: cada token cuenta contra 8K
        TPM. Antes se enviaban dos bloques casi identicos (~1200 chars cada
        uno) y por eso cada peticion iba de ~1100 tokens."""
        client = GroqClient(api_key="k", model="openai/gpt-oss-20b")

        vacio = client._build_prompt("T", "", "GTA", "en")
        # Con cuerpo y titulo minimos, lo que queda son las instrucciones.
        assert len(vacio) < 1100, "las instrucciones deben caber en ~300 tokens"
        assert vacio.count("You are a video game news editor") == 1
        # Y el total con un articulo real debe quedar por debajo de ~650 tokens.
        full = client._build_prompt("T" * 200, "B" * 5000, "GTA", "en")
        assert len(full) // 3 < 800

    def test_cuerpo_del_articulo_truncado(self):
        client = GroqClient(api_key="k", model="openai/gpt-oss-20b")
        prompt = client._build_prompt("t", "x" * 5000, "GTA", "en")

        assert "x" * 2000 not in prompt
        assert "..." in prompt


def monotonic_stub():
    import time as _time

    return _time.monotonic()