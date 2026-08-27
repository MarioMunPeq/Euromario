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
    ) -> "AISummary":

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
                            {"role": "system", "content": self._system_prompt()},
                            {"role": "user", "content": self._user_prompt(title, body, game)},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 300,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                raw = payload["choices"][0]["message"]["content"]
                return self._validate_response(raw)
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

    def _build_prompt(self, title: str, body: str, source_language: str, game: str) -> str:
        return f"""Eres un editor de noticias de videojuegos. Resume la noticia en 1-2 líneas
(en inglés), clasifícala y dale relevancia 1-5.
Devuelve SOLO JSON válido con estas claves exactas:
- "summary": str (1-2 líneas, en inglés)
- "relevance": int (1-5, 5 = anuncio mayor de saga seguida)
- "category": "lanzamiento" | "actualizacion" | "rumor" | "analisis"
- "language": "en" (el resumen siempre se genera en inglés)

Título: {title}
Texto: {body}
Juego: {game}
Idioma fuente: {source_language}"""

    def _system_prompt(self) -> str:
        return (
            "Eres un editor de noticias de videojuegos. Resume la noticia en 1-2 líneas "
            "(en INGLÉS), clasifícala y dale relevancia 1-5. "
            "Devuelve SOLO JSON válido con estas claves exactas: "
            '"summary" (str, 1-2 líneas, en inglés), '
            '"relevance" (int 1-5, 5=anuncio mayor), '
            '"category" ("lanzamiento"|"actualizacion"|"rumor"|"analisis"), '
            '"language" ("en").'
        )

    def _user_prompt(self, title: str, body: str, game: str) -> str:
        return f"Título: {title}\nTexto: {body}\nJuego: {game}"