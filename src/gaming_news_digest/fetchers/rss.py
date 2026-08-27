"""Descarga y normalización de feeds de medios especializados.

Acepta RSS clásico y Atom vía feedparser. Las fechas aplican la política
de ``resolve_date`` (nunca abortan el item) y el HTML de las descripciones
se reduce a texto plano.
"""

from datetime import datetime

import feedparser
import requests

from ..config import Limits, MediaFeed
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


def fetch_media_feed(
    feed: MediaFeed,
    limits: Limits,
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> tuple[FetchedItem, ...]:
    """Rastrea un feed de ``sources.yaml`` y devuelve sus items válidos.

    Los items sin título o sin link se descartan individualmente; solo
    se eleva ``FetchError`` si el propio feed no está disponible.
    """
    now = now or utc_now()
    session = session or build_session()
    try:
        content = http_get(session, feed.feed_url, limits.timeout_seconds)
    except FetchError as exc:
        raise FetchError(f"{feed.name}: {exc}") from exc
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise FetchError(
            f"{feed.name}: feed inservible "
            f"({getattr(parsed, 'bozo_exception', 'desconocido')})"
        )
    source = Source(name=feed.name, type=SourceType.MEDIA)
    items = []
    for entry in parsed.entries:
        item = _build_item(entry, source, feed.language, now)
        if item is not None:
            items.append(item)
    return tuple(items[: limits.max_items_per_source])


def _build_item(
    entry, source: Source, language, now: datetime
) -> FetchedItem | None:
    title = str(entry.get("title") or "").strip()
    url = str(entry.get("link") or "").strip()
    if not title or not url.startswith(("http://", "https://")):
        return None
    published = struct_to_utc(entry.get("published_parsed"))
    updated = struct_to_utc(entry.get("updated_parsed"))
    return FetchedItem(
        title=title,
        url=url,
        source=source,
        published_at=resolve_date(published, updated, now),
        fetched_at=now,
        body_text=strip_html(str(entry.get("summary") or "")),
        language=language,
        image_url=_extract_image(entry),
        author=extract_author(entry),
    )


def _extract_image(entry) -> str | None:
    """Extrae imagen destacada: enclosure → media_content → <img> del HTML."""
    for enc in getattr(entry, "enclosures", []):
        if enc.get("type", "").startswith("image/"):
            url = enc.get("url", "")
            if url.startswith(("http://", "https://")):
                return url
    for media in getattr(entry, "media_content", []):
        url = media.get("url", "")
        if url.startswith(("http://", "https://")):
            return url
    return extract_first_image_url(str(entry.get("summary") or ""))
