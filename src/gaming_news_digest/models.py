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


def _parse_iso(value: object, label: str) -> datetime:
    """Parsea una fecha ISO-8601 (con ``Z``) del JSON y la normaliza a UTC.

    Es la puerta de entrada del contrato público: cualquier formato no
    ISO-8601 se rechaza con ``ModelValidationError`` nombrando el campo.
    """
    if not isinstance(value, str):
        raise ModelValidationError(
            f"{label} debe ser un string ISO-8601 UTC, no {value!r}"
        )
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        return _ensure_utc(datetime.fromisoformat(cleaned))
    except (ValueError, TypeError):
        raise ModelValidationError(
            f"{label} no es una fecha ISO-8601 válida: {value!r}"
        ) from None


def to_iso_utc(value: datetime) -> str:
    """Serializa un datetime UTC como ISO-8601 con sufijo ``Z``."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    fetched_at: datetime
    summary: str | None = None
    image_url: str | None = None
    author: str | None = None
    is_verified: bool = False
    game_id: str | None = None
    summary_is_fallback: bool = False
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
        object.__setattr__(self, "fetched_at", _ensure_utc(self.fetched_at))
        self._validate_summary()
        image = self.image_url
        if image is not None:
            image = image.strip()
            if not _HTTP_PREFIX.match(image):
                image = None
        object.__setattr__(self, "image_url", image or None)
        object.__setattr__(self, "author", _optional_text(self.author, "el autor"))
        if not isinstance(self.is_verified, bool):
            raise ModelValidationError(
                f"is_verified debe ser un booleano, no {self.is_verified!r}"
            )
        object.__setattr__(self, "is_verified", self.is_verified)
        object.__setattr__(
            self, "game_id", _optional_text(self.game_id, "el game_id")
        )
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

    def _validate_summary(self):
        """Regla explícita del contrato sobre ``summary``.

        - Si la IA generó resumen: string no vacío (nunca una cadena vacía).
        - ``None`` SOLO se admite cuando se activó el fallback documentado
          por fallo de IA (``summary_is_fallback=True``). Nada silencioso:
          una instancia con ``summary=None`` sin el flag es inválida.
        """
        is_fallback = self.summary_is_fallback
        if not isinstance(is_fallback, bool):
            raise ModelValidationError(
                f"summary_is_fallback debe ser un booleano, no {is_fallback!r}"
            )
        object.__setattr__(self, "summary_is_fallback", is_fallback)
        summary = self.summary
        if summary is None:
            if is_fallback:
                object.__setattr__(self, "summary", None)
                return
            raise ModelValidationError(
                "summary=null solo se admite tras el fallback IA documentado "
                "(summary_is_fallback=True)"
            )
        if not isinstance(summary, str) or not summary.strip():
            raise ModelValidationError(
                f"summary debe ser un texto no vacío o None (fallback IA), no {summary!r}"
            )
        if is_fallback:
            raise ModelValidationError(
                "summary_is_fallback=True exige summary=None "
                "(no puede venir del fallback si hay resumen real)"
            )
        object.__setattr__(self, "summary", summary.strip())

    def to_dict(self) -> dict:
        """Serializa según el contrato JSON documentado en CONTRIBUTING.md.

        Formato plano: source (string) + source_type (enum) en vez de objeto
        anidado. ``source_subreddit`` solo aparece para fuentes reddit (sin
        él no se podría reconstruir una ``Source`` de tipo reddit al recargar,
        y el item se descartaría en el merge).
        """
        serialized = {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source.name,
            "source_type": self.source.type.value,
            "game": self.game,
            "game_id": self.game_id,
            "language": self.language.value,
            "published_at": to_iso_utc(self.published_at),
            "fetched_at": to_iso_utc(self.fetched_at),
            "relevance": self.relevance,
            "category": self.category.value,
            "image": self.image_url,
            "author": self.author,
            "is_verified": self.is_verified,
        }
        if self.source.subreddit is not None:
            serialized["source_subreddit"] = self.source.subreddit
        return serialized

    @classmethod
    def from_dict(cls, data: dict) -> "NewsItem":
        """Reconstruye NewsItem desde dict (como viene del JSON).

        Valida TODO el contrato: campos obligatorios ausentes, tipos,
        enums, fechas ISO-8601 y coherencia del ``id`` (derivado de la URL
        debe coincidir con el almacenado). Reutiliza la validación de
        ``__post_init__`` para garantizar integridad.

        Soporta tanto el formato nuevo (source + source_type plano)
        como el histórico (source anidado con name/type/subreddit).
        """
        missing = [
            f for f in ("title", "url", "game", "language",
                        "published_at", "fetched_at", "relevance", "category")
            if f not in data
        ]
        # source puede venir como string (nuevo) u objeto (histórico)
        if "source" not in data:
            missing.append("source")
        if missing:
            raise ModelValidationError(
                f"campo(s) obligatorio(s) ausente(s): {', '.join(sorted(missing))}"
            )
        summary = data.get("summary")

        # Reconstruir Source: formato nuevo (plano) o histórico (anidado)
        if isinstance(data["source"], dict):
            # Histórico: source anidado {name, type, subreddit}
            source = Source.from_dict(data["source"])
        else:
            # Nuevo: source (string) + source_type (string) + opcional source_subreddit
            source = Source(
                name=data["source"],
                type=data.get("source_type", "media"),
                subreddit=data.get("source_subreddit"),
            )

        item = cls(
            title=data["title"],
            url=data["url"],
            source=source,
            game=data["game"],
            language=data["language"],
            published_at=_parse_iso(data["published_at"], "published_at"),
            fetched_at=_parse_iso(data["fetched_at"], "fetched_at"),
            relevance=data["relevance"],
            category=data["category"],
            summary=summary,
            image_url=data.get("image") or data.get("image_url"),  # compat
            author=data.get("author"),
            is_verified=data.get("is_verified", False),
            game_id=data.get("game_id"),
            summary_is_fallback=summary is None,
        )
        stored_id = data.get("id")
        if stored_id != item.id:
            raise ModelValidationError(
                f"id almacenado {stored_id!r} no coincide con el derivado "
                f"de la URL {item.id!r}"
            )
        return item


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
    fetched_at: datetime
    body_text: str | None = None
    language: Language | None = None
    game: str | None = None
    image_url: str | None = None
    author: str | None = None
    game_id: str | None = None
    feed_categories: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.source, Source):
            raise ModelValidationError("source debe ser una instancia de Source")
        object.__setattr__(self, "title", _required_text(self.title, "el título"))
        url = self.url.strip()
        if not _HTTP_PREFIX.match(url):
            raise ModelValidationError(f"url inválida (solo http/https): {url!r}")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "published_at", _ensure_utc(self.published_at))
        object.__setattr__(self, "fetched_at", _ensure_utc(self.fetched_at))
        if self.body_text is not None and not isinstance(self.body_text, str):
            raise ModelValidationError("body_text debe ser texto o None")
        body = self.body_text.strip() if self.body_text else None
        object.__setattr__(self, "body_text", body or None)
        language = self.language
        if language is not None:
            language = _coerce_enum(language, Language, "el idioma")
        object.__setattr__(self, "language", language)
        image = self.image_url
        if image is not None:
            image = image.strip()
            if not _HTTP_PREFIX.match(image):
                image = None
        object.__setattr__(self, "image_url", image or None)
        object.__setattr__(self, "author", _optional_text(self.author, "el autor"))
        object.__setattr__(self, "game_id", _optional_text(self.game_id, "el game_id"))
        categories = self.feed_categories
        if not isinstance(categories, tuple):
            raise ModelValidationError("feed_categories debe ser una tupla")
        normalized = tuple(str(c) for c in categories)
        object.__setattr__(self, "feed_categories", normalized)
