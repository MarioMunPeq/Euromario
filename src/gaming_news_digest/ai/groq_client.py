"""Cliente para Groq API (fallback cloud gratuito).

Por qué este cliente es como es
===============================
Groq desc commissioned TODOS los modelos Llama del tier gratuito, así que el
modelo NO se fija a mano: se descubre contra ``GET /openai/v1/models``.

Los otros dos problemas que aparecieron en produccion:

1. **Presupuesto de tokens.** El plan gratuito da 8K TPM para gpt-oss-20b, y
   cada petición se come ~1100 tokens de entrada: caben 7 por minuto y el
   pipeline lanza 50+. Antes cada petición repetía las instrucciones dos veces
   (system prompt + user prompt casi idénticos). Ahora va UN prompt compacto y
   además hay un cubo de tokens que respeta el TPM.
2. **El esquema estricto exige `category` siempre**, pero para Reddit los
   prompts lo omitían a propósito (el pipeline la sobrescribe): el modelo no
   la devolvía y Groq respondía 400 `json_validate_failed`, tumbando el run.
   Ahora se pide siempre y, si aun así falla, se degrada a modo best-effort en
   lugar de abortar.
"""

import logging
import os
import time
from collections import deque
from datetime import datetime, timezone

import requests

from .base import AIClient, AIError, AISummary

logger = logging.getLogger(__name__)


#: Modelo de referencia. Groq lo designa como reemplazo oficial de
#: ``llama-3.1-8b-instant``: el mas barato y el mas rapido de los que
#: soportan Structured Outputs.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"

#: Orden de preferencia al descubrir modelos.
MODEL_PREFERENCE: tuple[str, ...] = (
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
)

#: Modelos que aparecen en /models pero no sirven para resumir: voz,
#: moderación o guardas.
NON_CHAT_HINTS: tuple[str, ...] = (
    "whisper",
    "tts",
    "safeguard",
    "guard",
    "nemotron",
    "orpheus",
    "playai",
)

#: TPM del plan gratuito (docs de Groq). El cliente lo sustituye por el valor
#: real que llega en la cabecera ``x-ratelimit-limit-tokens``.
DEFAULT_TPM = 8_000

#: Fracción de la ventana que nos permitirnos gastar. El resto es margen para
#: que un 429 con cabecera ``x-ratelimit-reset-tokens`` pueda absorbir el hueco.
TPM_SAFETY = 0.8

#: Tokens de salida que reservamos por petición (razonamiento + JSON). Las
#: respuestas reales del panel rondan 155-310 tokens.
RESERVED_OUTPUT_TOKENS = 320

#: Estimación conservadora: ~3 caracteres por token. Sobreestimar soloduce a
#: esperar de mas, que es el lado seguro del cubo de tokens.
CHARS_PER_TOKEN = 3

#: Cuerpo del articulo que se manda al modelo. Con el TPM de 8K del plan
#: gratuito el cuerpo DOMINA el coste de la peticion, mucho mas que las
#: instrucciones: 800 chars cubren la noticia relevante y cuestan ~270 tokens
#: frente a los ~660 de los 2000 anteriores.
MAX_BODY_CHARS = 800

_SUMMARY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "relevance": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "category": {
            "type": "string",
            "enum": ["lanzamiento", "actualizacion", "rumor", "analisis"],
        },
        "game": {"type": "string"},
        "language": {"type": "string", "enum": ["en"]},
    },
    "required": ["summary", "relevance", "category", "game", "language"],
    "additionalProperties": False,
}


def _excerpt(raw: str | None, limit: int = 300) -> str:
    """Recorta la respuesta cruda del modelo para poder diagnosticar."""
    if not raw:
        return "(vacia)"
    flat = " ".join(raw.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _retry_after_seconds(response, default: int = 5) -> float:
    """Segundos a esperar tras un 429.

    Prioriza ``x-ratelimit-reset-tokens`` (cuanto falta para que se llene la
    ventana de tokens) por encima de ``Retry-After``: es la cabecera que
    realmente explica el 429 cuando lo que se agota son los TPM, no los RPM.
    """
    headers = getattr(response, "headers", None) or {}
    reset = headers.get("x-ratelimit-reset-tokens")
    if reset:
        try:
            return max(1.0, min(float(reset) + 1.0, 60.0))
        except ValueError:
            pass

    raw = (headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        return min(float(raw), 60.0)
    if raw:
        try:
            from email.utils import parsedate_to_datetime

            delta = parsedate_to_datetime(raw) - datetime.now(timezone.utc)
            return max(1.0, min(float(delta.total_seconds()), 60.0))
        except (TypeError, ValueError):
            pass
    return float(default)


def _header_float(response, name: str) -> float | None:
    raw = (getattr(response, "headers", None) or {}).get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class GroqClient(AIClient):
    """Cliente para Groq API (compatible OpenAI chat.completions)."""

    #: Los 429 son esperables con el TPM del plan gratuito: 5 intentos cubren
    #: de sobra la espera hasta el reset de la ventana.
    MAX_429_RETRIES = 5

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
    ):
        self._configured_model = model or os.getenv("GROQ_MODEL") or None
        self.model = self._configured_model or DEFAULT_GROQ_MODEL
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no configurada")
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/chat/completions"

        self._model_resolved = self._configured_model is not None
        self._tpm_limit = float(DEFAULT_TPM)
        # Ventana deslizante de (timestamp, tokens) de los ultimos 60 s.
        self._spend = deque()
        self._waited_ms = 0.0
        logger.info(
            "GroqClient inicializado (modelo configurado=%s)",
            self._configured_model or "(auto-descubrimiento)",
        )

    # ── Descubrimiento de modelos ───────────────────────────────────

    def _resolve_model(self) -> str:
        """Elige un modelo que la cuenta puede usar de verdad.

        Groq retira modelos sin previo aviso y un ID fijo se convierte en un
        404 que tumba el pipeline. Preguntando a la API, el cliente sobrevive
        a los cambios de catálogo.
        """
        if self._model_resolved:
            return self.model

        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15,
            )
            response.raise_for_status()
            available = {m.get("id") for m in response.json().get("data", [])}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning(
                "No se pudo listar modelos de Groq (%s); uso %s por defecto",
                exc,
                self.model,
            )
            self._model_resolved = True
            return self.model

        available.discard(None)
        logger.info("Modelos disponibles en Groq: %s", sorted(available))

        for candidate in MODEL_PREFERENCE:
            if candidate in available:
                self.model = candidate
                self._model_resolved = True
                logger.info("Modelo Groq seleccionado: %s", candidate)
                return self.model

        chat_models = sorted(
            m
            for m in available
            if m and not any(hint in m.lower() for hint in NON_CHAT_HINTS)
        )
        if chat_models:
            self.model = chat_models[0]
            logger.warning(
                "Ningun modelo preferido disponible; uso el primero de chat: %s",
                self.model,
            )
        else:
            logger.error(
                "Ningun modelo de chat disponible en Groq. Disponibles: %s",
                sorted(available),
            )

        self._model_resolved = True
        return self.model

    # ── Cubo de tokens (respeta el TPM) ─────────────────────────────

    def _record_usage(self, response, fallback: int) -> None:
        """Aprende el TPM real y anota lo gastado en la ventana deslizante."""
        limit = _header_float(response, "x-ratelimit-limit-tokens")
        if limit and limit > 0:
            self._tpm_limit = limit

        spent = fallback
        usage = None
        try:
            usage = response.json().get("usage")
        except (ValueError, AttributeError):
            usage = None
        if isinstance(usage, dict):
            total = usage.get("total_tokens")
            if isinstance(total, (int, float)) and total > 0:
                spent = int(total)

        now = time.monotonic()
        self._spend.append((now, spent))
        self._prune(now)

    def _prune(self, now: float) -> None:
        while self._spend and (now - self._spend[0][0]) > 60.0:
            self._spend.popleft()

    def _budget_used(self, now: float) -> int:
        return sum(tokens for _, tokens in self._spend if now - _ <= 60.0)

    def _wait_for_budget(self, estimated: int) -> None:
        """Duerme lo justo para no reventar el limite de tokens por minuto.

        Sin esto el pipeline dispara las peticiones todas seguidas, agota los
        8K TPM y spends el resto del run acumulando 429.
        """
        now = time.monotonic()
        self._prune(now)
        ceiling = self._tpm_limit * TPM_SAFETY
        if self._budget_used(now) + estimated <= ceiling:
            return

        # Hay que esperar a que caduque la peticion mas antigua de la ventana.
        if not self._spend:
            return
        oldest = self._spend[0][0]
        wait = max(0.5, (oldest + 60.0) - now)
        logger.info(
            "Presupuesto TPM al %.0f%% (%.0f/%.0f): espero %.1fs",
            100 * self._budget_used(now) / self._tpm_limit,
            self._budget_used(now),
            self._tpm_limit,
            wait,
        )
        time.sleep(wait)
        self._waited_ms += wait * 1000

    # ── Llamada principal ───────────────────────────────────────────

    def summarize(
        self,
        title: str,
        body: str,
        source_language: str,
        game: str,
        source_type: str = "media",
    ) -> "AISummary":
        model = self._resolve_model()
        prompt = self._build_prompt(title, body, game, source_language)
        estimated = len(prompt) // CHARS_PER_TOKEN + RESERVED_OUTPUT_TOKENS

        degraded = False   # response_format caido a texto plano
        rate_hits = 0
        parse_hits = 0
        attempts = 0
        # El presupuesto de intentos tiene que COBRAR los reintentos de 429:
        # si no, los 3 reintentos normales se consumen antes y un pico de
        # rate limit acaba en "Agotados reintentos" en vez de esperar al reset.
        max_attempts = self.MAX_RETRIES + 1 + self.MAX_429_RETRIES

        while attempts < max_attempts:
            attempts += 1
            self._wait_for_budget(estimated)
            payload = self._build_payload(model, prompt, structured=not degraded)
            try:
                response = requests.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=60,
                )
            except requests.Timeout as exc:
                raise TimeoutError("Groq timeout") from exc
            except requests.ConnectionError as exc:
                raise ConnectionError("Groq no disponible") from exc

            if response.status_code == 429:
                if rate_hits >= self.MAX_429_RETRIES:
                    raise AIError(
                        "Groq 429 persistente tras "
                        f"{rate_hits} reintentos (TPM {self._tpm_limit:.0f})"
                    )
                wait = _retry_after_seconds(response)
                rate_hits += 1
                logger.warning(
                    "Groq 429 (quedan %s tokens), reintento %d/%d en %.1fs",
                    (response.headers or {}).get("x-ratelimit-remaining-tokens", "?"),
                    rate_hits,
                    self.MAX_429_RETRIES,
                    wait,
                )
                time.sleep(wait)
                self._waited_ms += wait * 1000
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                detail = exc.response.text if exc.response is not None else ""
                schema_problem = (
                    response.status_code == 400 and "json_validate_failed" in detail
                )
                if schema_problem and not degraded:
                    # El modelo genero JSON que no encaja con el esquema. Con
                    # strict:true Groq responde 400 y la unica salida es
                    # reintentar sin esquema: parse_model_json rescata el
                    # objeto del texto.
                    degraded = True
                    logger.warning(
                        "Groq 400 json_validate_failed; reintento sin esquema estricto"
                    )
                    continue
                if schema_problem:
                    # Ya reintentamos sin esquema y tampoco cuadra. Es un fallo
                    # DE ESTA NOTICIA, no de la infraestructura: se devuelve
                    # AIError para que el pipeline siga con el resto. Antes
                    # salia un HTTPError que abortaba el run y se perdian las
                    # ~50 noticias ya resumidas.
                    raise AIError(
                        "Groq no logro generar JSON valido para el esquema "
                        "(tampoco en modo best-effort)",
                        raw_response=detail,
                    ) from exc
                logger.error(
                    "Groq HTTP %s | modelo=%s | respuesta=%s",
                    response.status_code,
                    model,
                    _excerpt(detail),
                )
                raise requests.HTTPError(
                    f"Groq HTTP {response.status_code}"
                ) from exc

            self._record_usage(response, estimated)

            message = response.json()["choices"][0]["message"]
            raw = message.get("content") or ""
            try:
                return self._validate_response(raw, source_type)
            except AIError as exc:
                if not raw and message.get("reasoning"):
                    exc.raw_response = message["reasoning"]
                if parse_hits >= 1:
                    raise
                parse_hits += 1
                logger.warning(
                    "Groq %s | respuesta: %s | reintento",
                    exc,
                    _excerpt(exc.raw_response or raw),
                )
                continue

        raise AIError("Agotados reintentos en Groq")

    # ── Petición ────────────────────────────────────────────────────

    def _build_payload(self, model: str, prompt: str, structured: bool = True) -> dict:
        """Cuerpo de la petición.

        ``max_completion_tokens`` (y no ``max_tokens``) porque en los modelos de
        razonamiento los tokens de pensamiento se contabilizan aparte: con
        ``max_tokens`` el modelo puede gastarlos todos pensando y devolver el
        contenido vacío.
        """
        payload = {
            "model": model,
            # Un solo mensaje de usuario, sin system prompt: es lo que recomienda
            # la guia de Groq para modelos de razonamiento.
            "messages": [{"role": "user", "content": prompt}],
            # Rango recomendado por Groq para gpt-oss (0.5-0.7).
            "temperature": 0.6,
            "max_completion_tokens": 1024,
            "include_reasoning": False,
            "reasoning_effort": "low",
        }
        if structured:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "resumen_noticia",
                    "strict": True,
                    "schema": _SUMMARY_SCHEMA,
                },
            }
        return payload

    def _build_prompt(
        self, title: str, body: str, game: str, source_language: str
    ) -> str:
        """Instrucciones en un único bloque compacto.

        Antes se enviaban ``_system_prompt`` + ``_user_prompt``, dos textos casi
        identicos que duplicaban las reglas y casi triplicaban el coste en
        tokens por peticion. Con el TPM de 8K eso era lo que disparaba los 429.
        """
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS] + "..."

        return (
            "You are a video game news editor. Return ONLY a JSON object with "
            'exactly these keys: "summary" (string), "relevance" (integer 1-5, '
            '5 = major news for a followed saga), "category" (one of '
            '"lanzamiento", "actualizacion", "rumor", "analisis"), "game" '
            '(string) and "language" (must be "en").\n\n'
            "summary: 1-2 short lines, ALWAYS in English even if the article is "
            "not. Add value beyond the title by including ONE concrete, "
            "checkable detail from the body (a number, date, price, version, "
            "platform, name or quote) that is not already in the title. Never "
            "merely rephrase the title. Never invent facts; use only details "
            "present in the body.\n"
            "game: the specific game, franchise or series, using a name players "
            "recognise. If the given Game field is already a real title, repeat "
            'it EXACTLY. If it is "Videojuegos" or empty, infer it from the '
            "article. If the article is about the industry, a publisher, "
            'business or hardware rather than one game, return "".\n\n'
            f"Title: {title}\n"
            f"Body: {body}\n"
            f"Game: {game or 'Videojuegos'}\n"
            f"Article language: {source_language}"
        )