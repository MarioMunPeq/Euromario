"""Interfaz común y excepciones para clientes de IA (Ollama / Groq)."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Category, Language

# Respuestas que NO identifican un juego concreto: son el "no lo sé" del
# modelo y equivalen a "sin identificar" (→ nombre genérico).
_NON_GAME_ANSWERS = frozenset({
    "", "none", "null", "n/a", "na", "unknown", "desconocido", "no",
    "videojuegos", "videojuego", "gaming", "game", "games", "juego",
    "juegos", "video game", "video games", "generic", "varios", "various",
})

# Techo del nombre: los títulos legibles más largos del digest rondan los 40
# caracteres. Más largo = el modelo devolvió una frase, no un juego.
_MAX_GAME_NAME_LEN = 48
_MAX_GAME_NAME_WORDS = 6


def clean_game_name(value: object) -> str:
    """Normaliza el nombre de juego devuelto por la IA.

    Devuelve ``""`` (sin identificación) cuando la respuesta no parece un
    nombre de juego: no es texto, es una frase, o es un "no lo sé".
    El nombre se muestra al usuario en la tarjeta, así que se normaliza
    a un formato acotado y estable.
    """
    if not isinstance(value, str):
        return ""
    name = re.sub(r"\s+", " ", value).strip().strip("\"'“”«».,:;!?()[]-—_")
    if not name or len(name) > _MAX_GAME_NAME_LEN:
        return ""
    if len(name.split()) > _MAX_GAME_NAME_WORDS:
        return ""
    if name.casefold() in _NON_GAME_ANSWERS:
        return ""
    return name


# ---------------------------------------------------------------------------
# Parseo de la respuesta del modelo
#
# Distintos proveedores emiten el razonamiento de forma distinta. Con
# `openai/gpt-oss-20b` (modelo de razonamiento) llega un canal
# `<channel>analysis<|message|>` que el antiguo regex `<think>...` no
# quitaba, así que la respuesta llegaba al `json.loads` con el análisis
# pegado y TODAS las llamadas terminaban en AIError (0 de 22 con éxito en
# el run del 2026-10-14). Estas funciones cubren las variantes conocidas.
# ---------------------------------------------------------------------------


def _strip_reasoning(raw: str) -> str:
    """Quita el razonamiento del modelo y deja solo el JSON."""
    text = raw
    # Canal de razonamiento de gpt-oss: <channel>analysis<|message|>{...}
    text = re.sub(r"<channel>.*?<\|message\|>", " ", text, flags=re.DOTALL)
    # Bloques <think>...</think> / <thinking> / <reasoning>
    text = re.sub(r"<(think|thinking|reasoning)>.*?</\1>", " ", text, flags=re.DOTALL)
    # thinking sin cerrar: el modelo se corta por max_tokens
    text = re.sub(r"<(think|thinking|reasoning)>.*\Z", " ", text, flags=re.DOTALL)
    # Bloques cercados ```json ... ```
    text = re.sub(r"^\s*```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _extract_json_object(text: str) -> str | None:
    """Recorta el primer objeto JSON balanceado del texto.

    Localiza la primera llave y avanza contando llaves FUERA de comillas
    hasta emparejarla. Cubre que el modelo añada texto antes o después.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def parse_model_json(raw: str) -> dict:
    """Convierte la respuesta cruda del modelo en un dict.

    Dos pasadas: primero tal cual, y si no parsea, recortando el objeto JSON
    balanceado. Lanza AIError con la respuesta original adjunta para poder
    diagnosticar el fallo desde el log.
    """
    import json

    cleaned = _strip_reasoning(raw)
    data = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as first_exc:
        candidate = _extract_json_object(cleaned)
        if candidate is not None:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                data = None
        if data is None:
            raise AIError(f"JSON inválido: {first_exc}", raw_response=raw) from first_exc

    if not isinstance(data, dict):
        raise AIError(
            f"la respuesta no es un objeto JSON: {type(data).__name__}",
            raw_response=raw,
        )
    return data


@dataclass(frozen=True, slots=True)
class AISummary:
    """Salida validada de la IA para una noticia."""

    summary: str
    relevance: int          # 1-5
    category: Category
    language: Language
    # Juego/franquicia detectado por la IA. Vacío = no identifica ninguno.
    # El pipeline solo lo usa cuando el matcher determinista NO concluyo.
    game: str = ""

    def __post_init__(self):
        if not isinstance(self.relevance, int) or not (1 <= self.relevance <= 5):
            raise ValueError(f"relevance debe ser 1-5, no {self.relevance!r}")
        if not isinstance(self.category, Category):
            raise TypeError(f"category debe ser Category enum, no {type(self.category)}")
        if not isinstance(self.language, Language):
            raise TypeError(f"language debe ser Language enum, no {type(self.language)}")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("summary no puede estar vacío")
        if not isinstance(self.game, str):
            raise TypeError(f"game debe ser str, no {type(self.game)}")


class AIError(Exception):
    """La IA no pudo producir salida válida tras reintentos."""

    def __init__(self, reason: str, raw_response: str | None = None):
        super().__init__(reason)
        self.raw_response = raw_response


class AIClient(ABC):
    """Interfaz común para Ollama y Groq — ambos cumplen este contrato."""

    MAX_RETRIES = 2
    # Reintentos tras un 429. El backoff a ciegas (2^n) convertía un rate
    # limit en minutos de espera: 14 esperas de 5-20 s en un solo run.
    MAX_429_RETRIES = 1
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
        data = parse_model_json(raw)

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

        # Relevance 1-5. Se tolera el string numérico ("3"): es una salida
        # muy habitual de los modelos y no merece perder el resumen entero.
        rel = data["relevance"]
        if isinstance(rel, str) and rel.strip().isdigit():
            rel = int(rel.strip())
        if isinstance(rel, bool) or not isinstance(rel, int) or not (1 <= rel <= 5):
            raise AIError(f"relevance debe ser 1-5, no {rel!r}", raw_response=raw)

        # Category válida
        try:
            category = Category(data["category"])
        except ValueError:
            raise AIError(
                f"category inválida: {data['category']!r} "
                f"(válidas: {[c.value for c in Category]})",
                raw_response=raw,
            ) from None

        # Language válida
        try:
            language = Language(data["language"])
        except ValueError:
            raise AIError(
                f"language inválida: {data['language']!r} "
                f"(válidas: {[l.value for l in Language]})",
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
            # "game" es OPCIONAL: si el modelo no lo devuelve (o devuelve algo
            # que no es un nombre) el matcher determinista sigue mandando.
            game=clean_game_name(data.get("game")),
        )