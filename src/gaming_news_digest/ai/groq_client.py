"""Cliente para Groq API (fallback cloud gratuito)."""

import logging
import os
import time
from datetime import datetime, timezone

import requests

from .base import AIClient, AIError, AISummary

logger = logging.getLogger(__name__)


#: Modelo por defecto. `openai/gpt-oss-20b` es un modelo de RAZONAMIENTO:
#: emite su análisis en un canal aparte que no encaja con el bloque `<think>`
#: que se limpia en `base.py`, así que la respuesta llegaba al `json.loads`
#: con el razonamiento pegado y TODAS las llamadas terminaban en AIError.
#: Los modelos instruct de Llama respetan `response_format: json_object`.
# llama3-8b-8192: nombre estable, siempre disponible en free tier, rápido, soporta json_object.
# Los nombres "3.1-instant" a veces cambian; este es el alias clásico que no falla.
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"


def _excerpt(raw: str | None, limit: int = 300) -> str:
    """Recorta la respuesta cruda del modelo para poder diagnosticar."""
    if not raw:
        return "(vacia)"
    flat = " ".join(raw.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


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


def _rate_limit_detail(response) -> str:
    """Qué límite se agotó: peticiones por minuto o tokens por minuto.

    Sin esto el log decía solo "429 rate limited" y no había forma de saber
    cuál de los dos límites era el culpable.
    """
    headers = getattr(response, "headers", {}) or {}
    limit = headers.get("x-ratelimit-limit-requests") or headers.get("x-ratelimit-limit-tokens")
    remaining = headers.get("x-ratelimit-remaining-requests")
    unit = "requests"
    if not remaining or headers.get("x-ratelimit-remaining-tokens") == "0":
        unit = "tokens"
    return f"limite={limit} {unit}, restante={remaining}" if limit else unit


class GroqClient(AIClient):
    """Cliente para Groq API (compatible OpenAI chat.completions)."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
    ):
        # Override por entorno: cambiar de modelo sin tocar código ni desplegar.
        self.model = model or os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no configurada")
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/chat/completions"
        logger.info("GroqClient inicializado con modelo=%s", self.model)

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

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": self._system_prompt(source_type)},
                        {"role": "user", "content": self._user_prompt(title, body, game, source_language, source_type)},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 300,
                }
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
                payload = response.json()
                raw = payload["choices"][0]["message"]["content"]
                return self._validate_response(raw, source_type)
            except requests.Timeout as exc:
                raise TimeoutError("Groq timeout") from exc
            except requests.ConnectionError as exc:
                raise ConnectionError("Groq no disponible") from exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                # Log del cuerpo de la respuesta para diagnosticar 400/404
                if exc.response is not None:
                    logger.error("Groq HTTP %s response: %s", status, exc.response.text[:500])
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
            "ALWAYS WRITTEN IN ENGLISH. The summary must be in English regardless of the "
            "article's original language. "
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