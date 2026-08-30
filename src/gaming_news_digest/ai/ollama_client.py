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
        source_type: str = "media",
    ) -> "AISummary":
        # Truncar body a 2000 chars para evitar prompts excesivamente largos
        max_body = 2000
        if len(body) > max_body:
            body = body[:max_body] + "..."
        
        prompt = self._build_prompt(title, body, source_language, game, source_type)

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
                return self._validate_response(raw, source_type)
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

    def _build_prompt(self, title: str, body: str, source_language: str, game: str, source_type: str) -> str:
        # Para Reddit no pedimos categoría (se fuerza a "rumor" externamente)
        if source_type == "reddit":
            category_instruction = ""
        else:
            category_instruction = '- "category": "lanzamiento" | "actualizacion" | "rumor" | "analisis"\n'
        
        # INSTRUCCIÓN CRÍTICA: El campo Game viene determinado por un matcher
        # determinista externo. NUNCA adivines/inventes/cambies el juego.
        # - Si Game = "Videojuegos" → significa que NO se identificó juego concreto.
        # - NO dejes que un juego adivinado influya en relevance/category/summary.
        # - El summary/relevance/category deben basarse SOLO en el contenido real.
        game_instruction = (
            "CRITICAL: The Game field is set by an external deterministic matcher.\n"
            "DO NOT guess, invent, or change the game name. If Game is \"Videojuegos\", "
            "it means no specific game was identified — treat it as a generic topic.\n"
            "Do NOT let any guessed game influence relevance, category, or summary.\n"
            "The pipeline only sends articles already classified as video game news. "
            "If an article seems off-topic (movies, TV, comics), still treat it as a "
            "video game story and base the summary ONLY on the article content. "
            "Never use off-topic ambiguity to change or filter the article.\n"
        )
        
        return f"""You are a video game news editor. Write a summary of the news in 1-2 short lines, ALWAYS IN ENGLISH.
Add value beyond the title: include ONE concrete, checkable detail found in the article body (a number, a date, a price, a version, a platform, a name, or a direct quote) that is NOT already in the title. Never merely rephrase the title with fewer words. Only use details actually present in the body — never invent facts. If the body has no usable extra detail, close with the most specific confirmed fact.
{game_instruction}
Return ONLY valid JSON with these exact keys:
- "summary": str (1-2 lines, always written in English, regardless of the article's original language)
- "relevance": int (1-5; 5 = major announcement of a followed saga)
{category_instruction}- "language": "en" (the summary must always be written in English)

Title: {title}
Body: {body}
Game: {game}
Source language: {source_language}"""