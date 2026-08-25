"""Carga y validación de la configuración YAML del proyecto.

Lee ``config/games.yaml`` y ``config/sources.yaml`` y los convierte en
estructuras tipadas e inmutables. Cualquier problema (archivo ausente,
YAML malformado, campo obligatorio ausente, tipo incorrecto) se reporta
como ``ConfigError`` con un mensaje que indica archivo y campo concreto.
Las claves desconocidas se ignoran para permitir evolucionar el formato.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import Language

DEFAULT_MAX_ITEMS_PER_SOURCE = 20
DEFAULT_TIMEOUT_SECONDS = 15


class ConfigError(Exception):
    """La configuración es inválida o no se pudo cargar."""


@dataclass(frozen=True, slots=True)
class GameRule:
    """Juego o saga seguido, con sus aliases para el matcher."""

    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GamesConfig:
    """Listas de inclusión/exclusión ya validadas.

    La exclusión tiene prioridad sobre la inclusión (regla del filtro);
    aquí solo se guarda la estructura.
    """

    include: tuple[GameRule, ...]
    exclude: tuple[GameRule, ...] = ()


@dataclass(frozen=True, slots=True)
class MediaFeed:
    """Feed RSS de un medio especializado."""

    name: str
    feed_url: str
    language: Language


@dataclass(frozen=True, slots=True)
class Subreddit:
    """Subreddit vigilado vía RSS."""

    name: str
    tag: str = "rumores"


@dataclass(frozen=True, slots=True)
class SteamGame:
    """Juego seguido en Steam: app_id y nombre canónico (para el filtro)."""

    app_id: int
    nombre: str


@dataclass(frozen=True, slots=True)
class SteamConfig:
    """Configuración de Steam News API."""

    enabled: bool = False
    games: tuple[SteamGame, ...] = ()


@dataclass(frozen=True, slots=True)
class RedditConfig:
    """Configuración de los subreddits vigilados."""

    enabled: bool = False
    subreddits: tuple[Subreddit, ...] = ()


@dataclass(frozen=True, slots=True)
class Limits:
    """Límites de descarga por ejecución."""

    max_items_per_source: int = DEFAULT_MAX_ITEMS_PER_SOURCE
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class QualityConfig:
    """Filtros de calidad editorial (exclusiones por título y URL)."""

    exclude_title_patterns: tuple[str, ...] = ()
    exclude_url_patterns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourcesConfig:
    """Todas las fuentes declaradas, ya validadas."""

    media: tuple[MediaFeed, ...] = ()
    steam: SteamConfig = SteamConfig()
    reddit: RedditConfig = RedditConfig()
    limits: Limits = Limits()
    quality: QualityConfig = QualityConfig()


def load_games(path: str | Path) -> GamesConfig:
    """Carga y valida ``config/games.yaml``."""
    path = Path(path)
    data = _load_yaml(path)
    include = _parse_game_rules(_require(data, "incluir", "la raíz", path),
                                "incluir", path)
    if not include:
        raise ConfigError(f"{path}: la sección 'incluir' no puede estar vacía")
    exclude = _parse_game_rules(data.get("excluir") or [], "excluir", path)
    _reject_overlap(include, exclude, path)
    return GamesConfig(include=include, exclude=exclude)


def load_sources(path: str | Path) -> SourcesConfig:
    """Carga y valida ``config/sources.yaml``."""
    path = Path(path)
    data = _load_yaml(path)
    return SourcesConfig(
        media=_parse_media(data.get("medios") or [], path),
        steam=_parse_steam(data.get("steam") or {}, path),
        reddit=_parse_reddit(data.get("reddit") or {}, path),
        limits=_parse_limits(data.get("limites") or {}, path),
        quality=_parse_quality(data.get("calidad") or {}, path),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"{path}: el archivo de configuración no existe")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML malformado ({exc})") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: el documento raíz debe ser un mapa YAML")
    return raw


def _require(mapping: dict, key: str, ctx: str, path: Path) -> Any:
    value = mapping.get(key)
    if value is None:
        raise ConfigError(f"{path}: campo obligatorio '{key}' ausente en {ctx}")
    return value


def _parse_game_rules(raw: Any, section: str, path: Path) -> tuple[GameRule, ...]:
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: la sección '{section}' debe ser una lista")
    rules: list[GameRule] = []
    for index, entry in enumerate(raw):
        ctx = f"la entrada {index} de '{section}'"
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: {ctx} debe ser un mapa")
        name = _require(entry, "nombre", ctx, path)
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{path}: {ctx} tiene un 'nombre' vacío o no textual")
        aliases = _parse_aliases(entry.get("aliases") or [], ctx, path)
        rules.append(GameRule(name=name.strip(), aliases=aliases))
    return tuple(rules)


def _parse_aliases(raw: Any, ctx: str, path: Path) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: {ctx} tiene 'aliases' que no son una lista")
    aliases = []
    for alias in raw:
        if not isinstance(alias, str) or not alias.strip():
            raise ConfigError(f"{path}: {ctx} tiene un alias vacío o no textual")
        aliases.append(alias.strip())
    return tuple(aliases)


def _reject_overlap(include: tuple, exclude: tuple, path: Path):
    included = {rule.name.casefold() for rule in include}
    for rule in exclude:
        if rule.name.casefold() in included:
            raise ConfigError(
                f"{path}: '{rule.name}' no puede estar en 'incluir' y en "
                "'excluir' a la vez"
            )


def _parse_media(raw: Any, path: Path) -> tuple[MediaFeed, ...]:
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: la sección 'medios' debe ser una lista")
    feeds: list[MediaFeed] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: la entrada {index} de 'medios' debe ser un mapa")
        name = _required_name(entry, f"la entrada {index} de 'medios'", path)
        ctx = f"la fuente '{name}'"
        feed_url = _require(entry, "feed", ctx, path)
        _validate_http(feed_url, ctx, path)
        feeds.append(
            MediaFeed(
                name=name,
                feed_url=feed_url.strip(),
                language=_parse_language(_require(entry, "idioma", ctx, path), ctx, path),
            )
        )
    return tuple(feeds)


def _required_name(entry: dict, ctx: str, path: Path) -> str:
    name = _require(entry, "nombre", ctx, path)
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{path}: {ctx} tiene un 'nombre' vacío o no textual")
    return name.strip()


def _validate_http(url: Any, ctx: str, path: Path):
    if not isinstance(url, str) or not url.strip().startswith(("http://", "https://")):
        raise ConfigError(
            f"{path}: {ctx} tiene una URL inválida (debe empezar por http/https)"
        )


def _parse_language(value: Any, ctx: str, path: Path) -> Language:
    if isinstance(value, Language):
        return value
    try:
        return Language(str(value).strip())
    except ValueError:
        raise ConfigError(
            f"{path}: {ctx} tiene un idioma inválido: {value!r} (válidos: es, en)"
        ) from None


def _parse_bool(value: Any, key: str, path: Path) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{path}: '{key}' debe ser un booleano, no {value!r}")
    return value


def _parse_steam(raw: Any, path: Path) -> SteamConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: la sección 'steam' debe ser un mapa")
    return SteamConfig(
        enabled=_parse_bool(raw.get("habilitado", False), "steam.habilitado", path),
        games=_parse_steam_games(raw.get("juegos") or [], path),
    )


def _parse_steam_games(raw: Any, path: Path) -> tuple[SteamGame, ...]:
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: 'steam.juegos' debe ser una lista")
    games = []
    for index, entry in enumerate(raw):
        ctx = f"la entrada {index} de 'steam.juegos'"
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: {ctx} debe ser un mapa")
        app_id = _require(entry, "app_id", ctx, path)
        if isinstance(app_id, bool) or not isinstance(app_id, int) or app_id <= 0:
            raise ConfigError(
                f"{path}: {ctx} tiene un 'app_id' no entero positivo: {app_id!r}"
            )
        games.append(SteamGame(app_id=app_id, nombre=_required_name(entry, ctx, path)))
    return tuple(games)


def _parse_reddit(raw: Any, path: Path) -> RedditConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: la sección 'reddit' debe ser un mapa")
    subs_raw = raw.get("subreddits") or []
    if not isinstance(subs_raw, list):
        raise ConfigError(f"{path}: 'reddit.subreddits' debe ser una lista")
    subreddits = []
    for index, entry in enumerate(subs_raw):
        ctx = f"el subreddit {index} de 'reddit.subreddits'"
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: {ctx} debe ser un mapa")
        name = _required_name(entry, ctx, path)
        tag = entry.get("etiqueta") or "rumores"
        if not isinstance(tag, str) or not tag.strip():
            raise ConfigError(f"{path}: {ctx} tiene una 'etiqueta' vacía o no textual")
        subreddits.append(Subreddit(name=name, tag=tag.strip()))
    return RedditConfig(
        enabled=_parse_bool(raw.get("habilitado", False), "reddit.habilitado", path),
        subreddits=tuple(subreddits),
    )


def _parse_limits(raw: Any, path: Path) -> Limits:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: la sección 'limites' debe ser un mapa")
    return Limits(
        max_items_per_source=_positive_int(
            raw, "max_items_por_fuente", DEFAULT_MAX_ITEMS_PER_SOURCE, path
        ),
        timeout_seconds=_positive_int(
            raw, "timeout_segundos", DEFAULT_TIMEOUT_SECONDS, path
        ),
    )


def _positive_int(raw: dict, key: str, default: int, path: Path) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(
            f"{path}: 'limites.{key}' debe ser un entero positivo, no {value!r}"
        )
    return value


def _parse_quality(raw: Any, path: Path) -> QualityConfig:
    if not isinstance(raw, dict):
        return QualityConfig()
    title_patterns = _parse_string_list(raw.get("excluir_titulos"), "excluir_titulos", path)
    url_patterns = _parse_string_list(raw.get("excluir_urls"), "excluir_urls", path)
    import re
    for pat in title_patterns + url_patterns:
        try:
            re.compile(pat)
        except re.error as exc:
            raise ConfigError(
                f"{path}: patrón de exclusión inválido {pat!r}: {exc}"
            ) from exc
    return QualityConfig(
        exclude_title_patterns=tuple(title_patterns),
        exclude_url_patterns=tuple(url_patterns),
    )


def _parse_string_list(raw: Any, key: str, path: Path) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: '{key}' debe ser una lista")
    result = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{path}: '{key}' contiene un elemento vacío o no textual")
        result.append(item.strip())
    return result
