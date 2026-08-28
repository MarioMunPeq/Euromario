"""Cliente para Groq API (fallback cloud gratuito)."""

import logging
import os
import time

import requests

from .base import AIClient, AIError, AISummary

logger = logging.getLogger(__name__)


class GroqClient(AIClient):
    """Cliente para Groq API (compatible OpenAI chat.completions)."""

    def __init__(
        self,
        model: str = "openai/gpt-oss-20b",
        api_key: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
    ):
        self.model = model
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no configurada")
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/chat/completions"

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
                response = requests.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self._system_prompt(source_type)},
                            {"role": "user", "content": self._user_prompt(title, body, game, source_language, source_type)},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 300,
                    },
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
                if status == 429:
                    wait = min(2 ** attempt * 5, 30)
                    logger.warning("Groq 429 rate limited, esperando %ds", wait)
                    time.sleep(wait)
                    continue
                raise requests.HTTPError(f"Groq HTTP {status}") from exc
            except AIError:
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
            "Return ONLY valid JSON with these exact keys: "
            '"summary" (str, 1-2 lines, always in English), '
            '"relevance" (int 1-5; 5 = major announcement of a followed saga), '
            f'{category_instruction}'
            '"language" ("en").'
        )

    def _user_prompt(self, title: str, body: str, game: str, source_language: str, source_type: str) -> str:
        if source_type == "reddit":
            category_key = ""
        else:
            category_key = '"category": str, '
        return f"""You are a video game news editor. Write a summary of the news in 1-2 short lines, ALWAYS IN ENGLISH.
Add value beyond the title: include ONE concrete, checkable detail found in the article body (a number, a date, a price, a version, a platform, a name, or a direct quote) that is NOT already in the title. Never merely rephrase the title with fewer words. Only use details actually present in the body — never invent facts. If the body has no usable extra detail, close with the most specific confirmed fact.
Return ONLY valid JSON with these exact keys:
- "summary": str (1-2 lines, always written in English, regardless of the article's original language)
- "relevance": int (1-5; 5 = major announcement of a followed saga)
{category_key}- "language": "en" (the summary must always be written in English)

Title: {title}
Body: {body}
Game: {game}
Source language: {source_language}"""