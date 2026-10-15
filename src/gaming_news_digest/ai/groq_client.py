"""Cliente para Groq API (fallback cloud gratuito).

Contexto de por qué este cliente es como es
-------------------------------------------
Groq desc commissioned TODOS los modelos Llama para el tier gratuito:

* ``llama3-8b-8192``  -> apagado 2025-08-30 (replacement: llama-3.1-8b-instant)
* ``llama-3.1-8b-instant`` y ``llama-3.3-70b-versatile`` -> apagados 2026-08-16
  (replacement oficial: ``openai/gpt-oss-20b`` / ``openai/gpt-oss-120b``)

Los tres dames 404 ``model_not_found`` y tumbaban el pipeline entero. De ahí las
dos decisiones que hacen que esto no vuelva a romperse:

1. **Descubrimiento del modelo en tiempo de ejecución** contra
   ``GET /openai/v1/models``. No hay nombres hardcodeados que se queden viejos.
2. **Structured Outputs en modo estricto** (``response_format`` con
   ``json_schema`` + ``strict: true``). Groq decodifica de forma restringida, así
   que la salida es JSON válido POR CONSTRUCCIÓN: se elimina de raíz toda la
   familia de fallos de parseo, que era el otro modo de fallo histórico del
   pipeline (0 de 22 llamadas con éxito el 2026-10-14).
"""

import logging
import os
import time
from datetime import datetime, timezone

import requests

from .base import AIClient, AIError, AISummary

logger = logging.getLogger(__name__)


#: Modelo de referencia. Groq lo designa como reemplazo oficial de
#: ``llama-3.1-8b-instant``. Es el mas barato ($0.075/$0.30 por millon de
#: tokens) y el mas rapido (1000 tps) de los que soportan Structured Outputs.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"

#: Orden de preferencia al descubrir modelos. El primero que exista y admita
#: chat gana. Se recorre en orden porque la calidad baja a medida que avanzamos.
MODEL_PREFERENCE: tuple[str, ...] = (
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
)

#: Modelos que aparecen en /models pero NO sirven para resumir: son de voz,
#: moderación o guardas. Si se agota MODEL_PREFERENCE se elige "cualquier otro
#: de chat" y hay que filtrar estos.
NON_CHAT_HINTS: tuple[str, ...] = (
    "whisper",
    "tts",
    "safeguard",
    "guard",
    "nemotron",
    "orpheus",
    "playai",
)

#: Esquema de la salida. En modo estricto TODAS las propiedades deben estar en
#: ``required`` y los objetos deben declarar ``additionalProperties: false``;
#: si no, Groq responde 400.
_SUMMARY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        # Enum en vez de "integer": el modelo no puede devolver 6 ni un string
        # tipo "3", que era una fuente de reintentos.
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


def _rate_limit_detail(response) -> str:
    """Texto de la cabecera de rate limit, para diagnostics."""
    headers = getattr(response, "headers", None) or {}
    for key in ("x-ratelimit-remaining-tokens", "retry-after"):
        value = headers.get(key)
        if value:
            return f"{key}={value}"
    return "sin detalle"


def _retry_after_seconds(response, default: int) -> int:
    """Segundos a esperar tras un 429, respetando ``Retry-After``.

    Acepta la forma entera (segundos) y la forma HTTP-date de RFC 9110, que
    antes se ignoraba y hacía que el único reintento cayera de nuevo en 429.
    """
    raw = (response.headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        return min(int(raw), 60)
    if raw:
        try:
            from email.utils import parsedate_to_datetime

            delta = parsedate_to_datetime(raw) - datetime.now(timezone.utc)
            return max(1, min(int(delta.total_seconds()), 60))
        except (TypeError, ValueError):
            pass
    return default


class GroqClient(AIClient):
    """Cliente para Groq API (compatible OpenAI chat.completions)."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
    ):
        # Override por entorno: cambiar de modelo sin tocar código ni desplegar.
        self._configured_model = model or os.getenv("GROQ_MODEL") or None
        self.model = self._configured_model or DEFAULT_GROQ_MODEL
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no configurada")
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/chat/completions"
        self._model_resolved = self._configured_model is not None
        logger.info(
            "GroqClient inicializado (modelo configurado=%s)",
            self._configured_model or "(auto-descubrimiento)",
        )

    # ── Descubrimiento de modelos ───────────────────────────────────

    def _resolve_model(self) -> str:
        """Elige un modelo que la cuenta puede usar de verdad.

        Groq retira modelos sin previo aviso y el ID hardcodeado se convierte en
        un 404 que tumba el pipeline. Preguntando a la API qué modelos tiene
        la cuenta, el cliente sobrevive a los cambios de catálogo.

        Se cachea el resultado: solo cuesta una llamada por ejecución.
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
            # Descubrimiento es una optimización, no un requisito: si falla,
            # seguimos con el modelo configurado y que el error real de la
            # llamada de chat sea el que hable.
            logger.warning(
                "No se pudo listar modelos de Groq (%s); uso %s por defecto",
                exc,
                self.model,
            )
            self._model_resolved = True
            return self.model

        available.discard(None)
        logger.info("Modelos disponibles en Groq: %s", sorted(available))

        # 1) Primer nombre de la lista de preferencias que exista.
        for candidate in MODEL_PREFERENCE:
            if candidate in available:
                self.model = candidate
                self._model_resolved = True
                logger.info("Modelo Groq seleccionado: %s", candidate)
                return self.model

        # 2) Cualquier otro modelo de chat (catalogo nuevo que no conocemos).
        chat_models = sorted(
            m
            for m in available
            if m and not any(hint in m.lower() for hint in NON_CHAT_HINTS)
        )
        if chat_models:
            self.model = chat_models[0]
            logger.warning(
                "Ningún modelo preferido disponible; uso el primero de chat: %s",
                self.model,
            )
        else:
            logger.error(
                "Ningún modelo de chat disponible en Groq. Disponibles: %s",
                sorted(available),
            )

        self._model_resolved = True
        return self.model

    # ── Llamada principal ───────────────────────────────────────────

    def summarize(
        self,
        title: str,
        body: str,
        source_language: str,
        game: str,
        source_type: str = "media",
    ) -> "AISummary":
        # Truncar body a 2000 chars para evitar prompts excesivamente largos
        max_body = 2000
        if len(body) > max_body:
            body = body[:max_body] + "..."

        model = self._resolve_model()

        # Los modelos de razonamiento (gpt-oss, qwen) rindieron mejor con TODAS
        # las instrucciones en el mensaje de usuario: es lo que recomienda la
        # propia guía de prompting de Groq para estos modelos.
        user_prompt = (
            self._system_prompt(source_type)
            + "\n\n"
            + self._user_prompt(title, body, game, source_language, source_type)
        )

        for attempt in range(self.MAX_RETRIES + 1):
            payload = self._build_payload(model, user_prompt)
            try:
                response = requests.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30,
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                # El razonamiento de gpt-oss viene en message.reasoning, fuera de
                # `content`. include_reasoning=False lo evita, pero lo leemos
                # solo como diagnóstico si el parseo falla.
                raw = message.get("content") or ""
                try:
                    return self._validate_response(raw, source_type)
                except AIError as exc:
                    if not raw and message.get("reasoning"):
                        exc.raw_response = message["reasoning"]
                    raise
            except requests.Timeout as exc:
                raise TimeoutError("Groq timeout") from exc
            except requests.ConnectionError as exc:
                raise ConnectionError("Groq no disponible") from exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status == 429:
                    # Solo UN reintento tras 429 y el tiempo que nos digan: el
                    # backoff a ciegas (2^n) convertía un rate limit en minutos
                    # de espera acumulada en el runner.
                    if attempt >= self.MAX_429_RETRIES:
                        raise AIError(
                            "Groq 429 persistente: "
                            f"{_rate_limit_detail(exc.response)}"
                        ) from exc
                    wait = _retry_after_seconds(exc.response, default=15)
                    logger.warning(
                        "Groq 429 (%s), reintento en %ds [%d/%d]",
                        _rate_limit_detail(exc.response),
                        wait,
                        attempt + 1,
                        self.MAX_429_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                logger.error(
                    "Groq HTTP %s | modelo=%s | respuesta=%s",
                    status,
                    model,
                    _excerpt(exc.response.text if exc.response is not None else None),
                )
                raise requests.HTTPError(f"Groq HTTP {status}") from exc
            except AIError as exc:
                # Se registra el motivo REAL y la respuesta cruda: sin esto un
                # fallo de parseo es indistinguible de un problema de red, y
                # obliga a adivinar el motivo en el siguiente run.
                logger.warning("Groq %s | respuesta: %s", exc, _excerpt(exc.raw_response))
                if attempt == self.MAX_RETRIES:
                    raise
                continue
        raise AIError("Agotados reintentos en Groq")

    def _build_payload(self, model: str, user_prompt: str) -> dict:
        """Cuerpo de la petición.

        ``max_completion_tokens`` (y no ``max_tokens``) porque en los modelos de
        razonamiento los tokens de razonamiento se contabilizan aparte: con
        ``max_tokens`` el modelo puede gastarlos todos pensando y devolver el
        contenido vacío.
        """
        return {
            "model": model,
            "messages": [{"role": "user", "content": user_prompt}],
            # Rango recomendado por Groq para gpt-oss (0.5-0.7); con 0.1 el
            # modelo entraba en bucles de repetición.
            "temperature": 0.6,
            "max_completion_tokens": 1024,
            # Structured Outputs estricto: JSON válido garantizado por
            # decodificación restringida, sin regex ni parseos frágiles.
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "resumen_noticia",
                    "strict": True,
                    "schema": _SUMMARY_SCHEMA,
                },
            },
            # No necesitamos el razonamiento: solo el JSON final.
            "include_reasoning": False,
            "reasoning_effort": "low",
        }

    def _system_prompt(self, source_type: str) -> str:
        if source_type == "reddit":
            category_instruction = ""
        else:
            category_instruction = (
                '"category" ("lanzamiento"|"actualizacion"|"rumor"|"analisis"), '
            )
        game_instruction = (
            "You must also identify WHICH GAME the article is about. "
            "If the Game field is already a real title (not \"Videojuegos\"), repeat it "
            "EXACTLY as given — never correct it. "
            "If Game is \"Videojuegos\", the external matcher failed to identify the "
            "game: read the title and body and name the specific game, franchise or "
            "series the article is about. Use the name a player would recognise "
            "(\"Arc Raiders\", \"The Witcher\", \"EA Sports College Football\"), not a "
            "publisher, platform, studio or industry topic. "
            "If the article is about the industry, business or hardware rather than one "
            "game, return \"\" (empty string) — do not invent a game. "
            "The pipeline only sends articles already classified as video game news. "
            "If an article seems off-topic (movies, TV, comics), still treat it as a "
            "video game story and base the summary ONLY on the article content. "
            "Never use off-topic ambiguity to change or filter the article."
        )
        return (
            "You are a video game news editor. Summarize the news in 1-2 short lines, "
            "ALWAYS WRITTEN IN ENGLISH. The summary must be in English regardless of "
            "the article's original language. "
            "Add value beyond the title: include ONE concrete, checkable detail found in "
            "the article body (a number, a date, a price, a version, a platform, a name, "
            "or a direct quote) that is NOT already in the title. Never merely rephrase "
            "the title with fewer words. Only use details actually present in the body — "
            "never invent facts. If the body has no usable extra detail, close with the "
            "most specific confirmed fact. "
            f"{game_instruction} "
            "Return ONLY valid JSON with these exact keys: "
            '"summary" (str, 1-2 lines, always in English), '
            '"relevance" (int 1-5; 5 = major announcement of a followed saga), '
            f'{category_instruction}'
            '"game" (str; the game/franchise this article is about, or "" if none), '
            '"language" ("en").'
        )

    def _user_prompt(self, title: str, body: str, game: str, source_language: str, source_type: str) -> str:
        if source_type == "reddit":
            category_key = ""
        else:
            category_key = '"category": str, '
        game_instruction = (
            "Identify WHICH GAME the article is about.\n"
            "If the Game field is already a real title (not \"Videojuegos\"), repeat it "
            "EXACTLY as given — never correct it.\n"
            "If Game is \"Videojuegos\", the external matcher failed to identify the "
            "game: read the title and body and name the specific game, franchise or "
            "series the article is about. Use the name a player would recognise "
            "(\"Arc Raiders\", \"The Witcher\", \"EA Sports College Football\"), not a "
            "publisher, platform, studio or industry topic.\n"
            "If the article is about the industry, business or hardware rather than one "
            "game, return \"\" (empty string) — do not invent a game.\n"
        )
        return f"""You are a video game news editor. Write a summary of the news in 1-2 short lines, ALWAYS IN ENGLISH.
Add value beyond the title: include ONE concrete, checkable detail found in the article body (a number, a date, a price, a version, a platform, a name, or a direct quote) that is NOT already in the title. Never merely rephrase the title with fewer words. Only use details actually present in the body — never invent facts. If the body has no usable extra detail, close with the most specific confirmed fact.
{game_instruction}
Return ONLY valid JSON with these exact keys:
- "summary": str (1-2 lines, always written in English, regardless of the article's original language)
- "relevance": int (1-5; 5 = major announcement of a followed saga)
{category_key}- "game": str (the specific game, franchise or series this article is about; "" if the article is about the industry, a publisher, or hardware instead of one game)
- "language": "en" (the summary must always be written in English)

Title: {title}
Body: {body}
Game: {game}
Source language: {source_language}"""