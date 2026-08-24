"""Modelos de dominio compartidos: fuente de noticias e ítem de noticia.

Los modelos son inmutables y se autovalidan al construirse, de modo que
nunca puede existir una instancia inválida. Donde se espera un enum se
acepta también su valor como string y se coacciona automáticamente;
ante cualquier dato incorrecto se eleva ``ModelValidationError``.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

_HTTP_PREFIX = re.compile(r"^https?://", re.IGNORECASE)


class ModelValidationError(ValueError):
    """Datos inválidos al construir un modelo de dominio."""


class SourceType(StrEnum):
    """Procedencia de la noticia."""

    MEDIA = "media"
    STEAM = "steam"
    REDDIT = "reddit"


class Language(StrEnum):
    """Idiomas admitidos para fuentes y resúmenes."""

    SPANISH = "es"
    ENGLISH = "en"


class Category(StrEnum):
    """Categorías de una noticia (valores del contrato JSON, español ASCII)."""

    LAUNCH = "lanzamiento"
    UPDATE = "actualizacion"
    RUMOR = "rumor"
    ANALYSIS = "analisis"


def _coerce_enum(value: object, enum_type: type, label: str):
    """Acepta un miembro del enum o su valor como string; rechaza lo demás."""
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        for member in enum_type:
            if member.value == value.strip():
                return member
    valid = ", ".join(member.value for member in enum_type)
    raise ModelValidationError(
        f"valor inválido para {label}: {value!r} (válidos: {valid})"
    )


def _required_text(value: object, label: str) -> str:
    text = value.strip()
    if not text:
        raise ModelValidationError(f"{label} no puede estar vacío")
    return text


def _optional_text(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        raise ModelValidationError(f"{label}: usa None en vez de una cadena vacía")
    return text


def _ensure_utc(value: object) -> datetime:
    """Valida que la fecha sea un datetime tz-aware y la normaliza a UTC."""
    if not isinstance(value, datetime):
        raise ModelValidationError(
            "la fecha debe ser un datetime con zona horaria explícita"
        )
    if value.tzinfo is None:
        raise ModelValidationError("la fecha es naive: necesita zona horaria")
    return value.astimezone(timezone.utc)


def normalize_url(url: str) -> str:
    """Devuelve la forma canónica de una URL para derivar ids estables.

    Elimina espacios y fragmento (`#...`), pasa esquema y host a
    minúsculas y quita las barras finales del path. El resto del path se
    respeta tal cual (puede distinguir mayúsculas por diseño del sitio).
    """
    cleaned = url.strip().split("#", 1)[0]
    scheme, sep, remainder = cleaned.partition("://")
    if not sep:
        return cleaned.rstrip("/")
    host, _, path = remainder.partition("/")
    base = f"{scheme.lower()}://{host.lower()}"
    return f"{base}/{path.rstrip('/')}" if path else base


@dataclass(frozen=True, slots=True)
class Source:
    """Origen de una noticia: medio oficial, Steam o un subreddit.

    Invariante: solo las fuentes de tipo ``reddit`` pueden llevar
    ``subreddit``; para ``media`` y ``steam`` debe ser ``None``.
    """

    name: str
    type: SourceType
    subreddit: str | None = None

    def __post_init__(self):
        object.__setattr__(
            self, "name", _required_text(self.name, "el nombre de la fuente")
        )
        kind = _coerce_enum(self.type, SourceType, "el tipo de fuente")
        object.__setattr__(self, "type", kind)
        if kind is SourceType.REDDIT:
            if self.subreddit is None or not self.subreddit.strip():
                raise ModelValidationError(
                    "una fuente de tipo 'reddit' exige indicar el subreddit"
                )
            object.__setattr__(self, "subreddit", self.subreddit.strip())
        elif self.subreddit is not None:
            raise ModelValidationError(
                f"una fuente de tipo '{kind.value}' no admite subreddit"
            )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "subreddit": self.subreddit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        """Reconstruye Source desde dict (como viene del JSON)."""
        return cls(
            name=data["name"],
            type=data["type"],
            subreddit=data.get("subreddit"),
        )


@dataclass(frozen=True, slots=True)
class NewsItem:
    """Noticia ya filtrada y enriquecida, lista para el JSON público.

    El ``id`` no se pasa al constructor: se deriva siempre de la URL
    normalizada (sha256, 16 primeros caracteres hex) para que sea
    determinista y estable entre ejecuciones.
    """

    title: str
    url: str
    source: Source
    game: str
    language: Language
    published_at: datetime
    relevance: int
    category: Category
    summary: str | None = None
    id: str = field(init=False)

    def __post_init__(self):
        if not isinstance(self.source, Source):
            raise ModelValidationError("source debe ser una instancia de Source")
        object.__setattr__(self, "title", _required_text(self.title, "el título"))
        url = self.url.strip()
        if not _HTTP_PREFIX.match(url):
            raise ModelValidationError(f"url inválida (solo http/https): {url!r}")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "game", _required_text(self.game, "el juego"))
        object.__setattr__(
            self, "language", _coerce_enum(self.language, Language, "el idioma")
        )
        object.__setattr__(
            self, "category", _coerce_enum(self.category, Category, "la categoría")
        )
        self._validate_relevance()
        object.__setattr__(self, "published_at", _ensure_utc(self.published_at))
        object.__setattr__(self, "summary", _optional_text(self.summary, "el resumen"))
        digest = hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()
        object.__setattr__(self, "id", digest[:16])

    def _validate_relevance(self):
        score = self.relevance
        if isinstance(score, bool) or not isinstance(score, int):
            raise ModelValidationError(
                f"la relevancia debe ser un entero entre 1 y 5, no {score!r}"
            )
        if not 1 <= score <= 5:
            raise ModelValidationError(f"la relevancia debe estar entre 1 y 5, no {score}")

    def to_dict(self) -> dict:
        """Serializa según el contrato JSON documentado en CONTRIBUTING.md."""
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source.to_dict(),
            "game": self.game,
            "language": self.language.value,
            "published_at": self.published_at.isoformat().replace("+00:00", "Z"),
            "relevance": self.relevance,
            "category": self.category.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NewsItem":
        """Reconstruye NewsItem desde dict (como viene del JSON).
        
        Reutiliza la validación de __post_init__ para garantizar integridad.
        El id se recalcula desde la URL y debe coincidir con el guardado.
        """
        source = Source.from_dict(data["source"])
        # Parsear datetime ISO con Z
        published_at = datetime.fromisoformat(
            data["published_at"].replace("Z", "+00:00")
        )
        return cls(
            title=data["title"],
            url=data["url"],
            source=source,
            game=data["game"],
            language=data["language"],
            published_at=published_at,
            relevance=data["relevance"],
            category=data["category"],
            summary=data.get("summary"),
        )


@dataclass(frozen=True, slots=True)
class FetchedItem:
    """Noticia recién rastreada, pendiente de filtrar y enriquecer.

    La producen los fetchers; ``game``, ``category``, ``relevance`` y
    ``summary`` los completan más adelante el filtro y la IA. Las fechas
    llegan siempre tz-aware en UTC (ver ``fetchers/base.py``).
    """

    title: str
    url: str
    source: Source
    published_at: datetime
    body_text: str | None = None
    language: Language | None = None
    game: str | None = None

    def __post_init__(self):
        if not isinstance(self.source, Source):
            raise ModelValidationError("source debe ser una instancia de Source")
        object.__setattr__(self, "title", _required_text(self.title, "el título"))
        url = self.url.strip()
        if not _HTTP_PREFIX.match(url):
            raise ModelValidationError(f"url inválida (solo http/https): {url!r}")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "published_at", _ensure_utc(self.published_at))
        if self.body_text is not None and not isinstance(self.body_text, str):
            raise ModelValidationError("body_text debe ser texto o None")
        body = self.body_text.strip() if self.body_text else None
        object.__setattr__(self, "body_text", body or None)
        language = self.language
        if language is not None:
            language = _coerce_enum(language, Language, "el idioma")
        object.__setattr__(self, "language", language)
