"""Cliente para Groq API (fallback cloud gratuito)."""

import os

import requests

from .base import AIClient, AIError, AISummary


class GroqClient(AIClient):
    """Cliente para Groq API (compatible OpenAI chat.completions)."""

    def __init__(
        self,
        model: str = "llama-3.1-8b-instant",
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
                        "response_format": {"type": "json_object"},
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
                raise requests.HTTPError(f"Groq HTTP {exc.response.status_code}") from exc
            except AIError:
                if attempt == self.MAX_RETRIES:
                    raise
                continue
        raise AIError("Agotados reintentos en Groq")

    def _build_prompt(self, title: str, body: str, source_language: str, game: str) -> str:
        lang_name = "español" if source_language == "es" else "inglés"
        return f"""Eres un editor de noticias de videojuegos. Resume la noticia en 1-2 líneas
(en {lang_name}), clasifícala y dale relevancia 1-5.
Devuelve SOLO JSON válido con estas claves exactas:
- "summary": str (1-2 líneas, en {lang_name})
- "relevance": int (1-5, 5 = anuncio mayor de saga seguida)
- "category": "lanzamiento" | "actualizacion" | "rumor" | "analisis"
- "language": "es" | "en" (idioma detectado del texto original)

Título: {title}
Texto: {body}
Juego: {game}
Idioma fuente: {source_language}"""

    def _system_prompt(self) -> str:
        return (
            "Eres un editor de noticias de videojuegos. Resume la noticia en 1-2 líneas "
            "(en el MISMO idioma del original), clasifícala y dale relevancia 1-5. "
            "Devuelve SOLO JSON válido con estas claves exactas: "
            '"summary" (str, 1-2 líneas, idioma original), '
            '"relevance" (int 1-5, 5=anuncio mayor), '
            '"category" ("lanzamiento"|"actualizacion"|"rumor"|"analisis"), '
            '"language" ("es"|"en").'
        )

    def _user_prompt(self, title: str, body: str, game: str) -> str:
        return f"Título: {title}\nTexto: {body}\nJuego: {game}"