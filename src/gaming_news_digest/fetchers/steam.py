"""Cliente de Steam News API: noticias oficiales de los juegos seguidos.

Un fallo por app no aborta el resto; solo si fallan todas se eleva
``FetchError``. El idioma queda ``None``: lo determinará la fase de IA.
"""

import json
import logging
from datetime import datetime, timezone

import requests

from ..config import Limits, SteamConfig, SteamGame
from ..models import FetchedItem, Source, SourceType
from .base import (
    FetchError,
    build_session,
    extract_first_image_url,
    http_get,
    resolve_date,
    strip_html,
    utc_now,
)

logger = logging.getLogger(__name__)

_API_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
_MAX_CONTENT_CHARS = 1200


def fetch_steam_news(
    steam: SteamConfig,
    limits: Limits,
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> tuple[FetchedItem, ...]:
    """Rasca las noticias de cada juego dado de alta en la configuración."""
    now = now or utc_now()
    session = session or build_session()
    items: list[FetchedItem] = []
    failures: list[str] = []
    for game in steam.games:
        try:
            items.extend(_fetch_app(game, limits, session, now))
        except FetchError as exc:
            logger.warning("%s", exc)
            failures.append(str(exc))
    if steam.games and len(failures) == len(steam.games):
        raise FetchError(f"Steam: todas las apps fallaron ({failures[0]})")
    return tuple(items[: limits.max_items_per_source])


def _fetch_app(
    game: SteamGame,
    limits: Limits,
    session: requests.Session,
    now: datetime,
) -> tuple[FetchedItem, ...]:
    url = (
        f"{_API_URL}?appid={game.app_id}"
        f"&count={limits.max_items_per_source}"
        f"&maxlength={_MAX_CONTENT_CHARS}"
    )
    try:
        content = http_get(session, url, limits.timeout_seconds)
        payload = json.loads(content)
    except FetchError as exc:
        raise FetchError(f"{game.nombre}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FetchError(f"{game.nombre}: respuesta JSON inválida") from exc
    if not isinstance(payload, dict) or "appnews" not in payload:
        raise FetchError(f"{game.nombre}: respuesta sin 'appnews'")
    newsitems = (payload.get("appnews") or {}).get("newsitems") or []
    if not isinstance(newsitems, list):
        raise FetchError(f"{game.nombre}: 'newsitems' no es una lista")
    items = [
        item
        for entry in newsitems
        if (item := _build_item(entry, game, now)) is not None
    ]
    return tuple(items[: limits.max_items_per_source])


def _build_item(entry: dict, game: SteamGame, now: datetime) -> FetchedItem | None:
    title = str(entry.get("title") or "").strip()
    url = str(entry.get("url") or "").strip()
    if not title or not url.startswith(("http://", "https://")):
        return None
    raw_date = entry.get("date")
    moment = None
    if isinstance(raw_date, int) and not isinstance(raw_date, bool) and raw_date > 0:
        moment = datetime.fromtimestamp(raw_date, tz=timezone.utc)
    contents = str(entry.get("contents") or "")
    return FetchedItem(
        title=title,
        url=url,
        source=Source(name=f"Steam · {game.nombre}", type=SourceType.STEAM),
        published_at=resolve_date(moment, None, now),
        body_text=strip_html(contents),
        language=None,
        image_url=extract_first_image_url(contents),
    )
