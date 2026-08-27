"""Cliente para Ollama (modelo local)."""

import requests

from .base import AIClient, AIError, AISummary


class OllamaClient(AIClient):
    """Cliente para modelo local vía Ollama (HTTP API)."""

    def __init__(self, model: str = "llama3.2:3b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api/generate"

    def summarize(
        self,
        title: str,
        body: str,
        source_language: str,
        game: str,
    ) -> "AISummary":
        prompt = self._build_prompt(title, body, source_language, game)

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = requests.post(
                    self.api_url,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                    timeout=60,
                )
                response.raise_for_status()
                payload = response.json()
                raw = payload.get("response", "")
                return self._validate_response(raw)
            except requests.Timeout as exc:
                raise TimeoutError("Ollama timeout") from exc
            except requests.ConnectionError as exc:
                raise ConnectionError("Ollama no disponible") from exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response else "unknown"
                raise requests.HTTPError(f"Ollama HTTP {status}") from exc
            except AIError:
                if attempt == self.MAX_RETRIES:
                    raise
                # siguiente intento con prompt de corrección
                continue
        raise AIError("Agotados reintentos en Ollama")

    def _build_prompt(self, title: str, body: str, source_language: str, game: str) -> str:
        return f"""Eres un editor de noticias de videojuegos. Resume la noticia en 1-2 líneas (en inglés), clasifícala y dale relevancia 1-5.
Devuelve SOLO JSON válido con estas claves exactas:
- "summary": str (1-2 líneas, en inglés)
- "relevance": int (1-5, 5 = anuncio mayor de saga seguida)
- "category": "lanzamiento" | "actualizacion" | "rumor" | "analisis"
- "language": "en" (el resumen siempre se genera en inglés)

Título: {title}
Texto: {body}
Juego: {game}
Idioma fuente: {source_language}"""