"""Interfaz común y excepciones para clientes de IA (Ollama / Groq)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Category, Language


@dataclass(frozen=True, slots=True)
class AISummary:
    """Salida validada de la IA para una noticia."""

    summary: str
    relevance: int          # 1-5
    category: Category
    language: Language

    def __post_init__(self):
        if not isinstance(self.relevance, int) or not (1 <= self.relevance <= 5):
            raise ValueError(f"relevance debe ser 1-5, no {self.relevance!r}")
        if not isinstance(self.category, Category):
            raise TypeError(f"category debe ser Category enum, no {type(self.category)}")
        if not isinstance(self.language, Language):
            raise TypeError(f"language debe ser Language enum, no {type(self.language)}")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("summary no puede estar vacío")


class AIError(Exception):
    """La IA no pudo producir salida válida tras reintentos."""

    def __init__(self, reason: str, raw_response: str | None = None):
        super().__init__(reason)
        self.raw_response = raw_response


class AIClient(ABC):
    """Interfaz común para Ollama y Groq — ambos cumplen este contrato."""

    MAX_RETRIES = 2
    MAX_CONSECUTIVE_ERRORS = 3

    @abstractmethod
    def summarize(
        self,
        title: str,
        body: str,
        source_language: str,          # "es" o "en"
        game: str,                     # juego canónico que matcheó
        source_type: str = "media",    # "media", "steam", "reddit"
    ) -> "AISummary":
        """Resume, clasifica y puntúa una noticia.

        Lanza AIError si no puede producir salida válida tras reintentos.
        Lanza ConnectionError / TimeoutError / requests.HTTPError
        para errores de infraestructura (manejados por el pipeline).
        
        Para source_type="reddit", la categoría se fuerza a "rumor" externamente
        y el cliente puede omitir pedirla al modelo.
        """
        ...

    def _validate_response(self, raw: str, source_type: str = "media") -> "AISummary":
        """Parsea y valida la respuesta JSON cruda del modelo."""
        import json
        import re

        # Strip think blocks (Qwen thinking mode)
        cleaned = re.sub(r"think.*?think", "", raw, flags=re.DOTALL).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise AIError(f"JSON inválido: {exc}", raw_response=raw) from exc

        # Campos obligatorios
        for field in ("summary", "relevance", "language"):
            if field not in data:
                raise AIError(f"Campo obligatorio ausente: {field}", raw_response=raw)

        # Category: obligatoria excepto para Reddit (se fuerza externamente)
        if source_type != "reddit":
            if "category" not in data:
                raise AIError("Campo obligatorio ausente: category", raw_response=raw)
        else:
            data["category"] = "rumor"  # valor por defecto para validación

        # Relevance 1-5
        rel = data["relevance"]
        if not isinstance(rel, int) or not (1 <= rel <= 5):
            raise AIError(f"relevance debe ser 1-5, no {rel!r}", raw_response=raw)

        # Category válida
        try:
            category = Category(data["category"])
        except ValueError:
            raise AIError(
                f"category inválida: {data['category']!r} (válidas: {[c.value for c in Category]})",
                raw_response=raw,
            ) from None

        # Language válida
        try:
            language = Language(data["language"])
        except ValueError:
            raise AIError(
                f"language inválida: {data['language']!r} (válidas: {[l.value for l in Language]})",
                raw_response=raw,
            ) from None

        # Summary: string no vacía
        summary = data["summary"]
        if not isinstance(summary, str) or not summary.strip():
            raise AIError("summary vacío o no textual", raw_response=raw)

        return AISummary(
            summary=summary.strip(),
            relevance=rel,
            category=category,
            language=language,
        )