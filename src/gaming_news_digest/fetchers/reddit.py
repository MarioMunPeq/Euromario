"""Lector del RSS (Atom) de subreddits: siempre marcados como comunidad.

Reddit rechaza user-agents genéricos y además suele doble-escapar el HTML
de sus entradas; por eso se aplica un ``html.unescape`` previo antes de
limpiar las etiquetas (no afecta al texto plano).
"""

import html as html_module
from datetime import datetime

import feedparser
import requests

from ..config import Limits, Subreddit
from ..models import FetchedItem, Source, SourceType
from .base import (
    FetchError,
    build_session,
    extract_author,
    extract_first_image_url,
    http_get,
    resolve_date,
    strip_html,
    struct_to_utc,
    utc_now,
)

_REDDIT_RSS_URL = "https://www.reddit.com/r/{name}/new/.rss"

#: Pausa entre subreddits para respetar el límite anónimo de Reddit
#: (≈1 petición por minuto por IP, observado en 2026-08).
REDDIT_REQUEST_INTERVAL_SECONDS = 60


def fetch_subreddit(
    subreddit: Subreddit,
    limits: Limits,
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> tuple[FetchedItem, ...]:
    """Rasca /r/<sub>/new/.rss; el contenido queda marcado como reddit."""
    now = now or utc_now()
    session = session or build_session()
    try:
        content = http_get(
            session,
            _REDDIT_RSS_URL.format(name=subreddit.name),
            limits.timeout_seconds,
        )
    except FetchError as exc:
        raise FetchError(f"Reddit r/{subreddit.name}: {exc}") from exc
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise FetchError(
            f"Reddit r/{subreddit.name}: feed inservible "
            f"({getattr(parsed, 'bozo_exception', 'desconocido')})"
        )
    if not parsed.entries:
        raise FetchError(
            f"Reddit r/{subreddit.name}: feed Atom válido pero sin entradas "
            "(subreddit privado/restringido o sin posts accesibles anónimamente)"
        )
    source = Source(
        name=f"Reddit · r/{subreddit.name}",
        type=SourceType.REDDIT,
        subreddit=subreddit.name,
    )
    items = []
    for entry in parsed.entries:
        item = _build_item(entry, source, now)
        if item is not None:
            items.append(item)
    
    # Reddit usa su propio límite (0 = sin límite, usa todo el RSS)
    reddit_limit = limits.max_items_per_source_reddit
    if reddit_limit > 0:
        return tuple(items[:reddit_limit])
    return tuple(items)


def _build_item(entry, source: Source, now: datetime) -> FetchedItem | None:
    title = str(entry.get("title") or "").strip()
    url = str(entry.get("link") or "").strip()
    if not title or not url.startswith(("http://", "https://")):
        return None
    published = struct_to_utc(entry.get("published_parsed"))
    updated = struct_to_utc(entry.get("updated_parsed"))
    summary = html_module.unescape(str(entry.get("summary") or ""))
    return FetchedItem(
        title=title,
        url=url,
        source=source,
        published_at=resolve_date(published, updated, now),
        fetched_at=now,
        body_text=strip_html(summary),
        language=None,
        image_url=_extract_image(entry, summary),
        author=extract_author(entry),
    )


def _extract_image(entry, raw_summary: str) -> str | None:
    """Extrae imagen destacada: media:thumbnail → media:content → <img>."""
    for thumb in getattr(entry, "media_thumbnail", []):
        url = thumb.get("url", "")
        if url.startswith(("http://", "https://")):
            return url
    for media in getattr(entry, "media_content", []):
        url = media.get("url", "")
        if url.startswith(("http://", "https://")):
            return url
    return extract_first_image_url(raw_summary)
