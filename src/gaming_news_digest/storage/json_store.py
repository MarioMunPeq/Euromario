"""Lectura/escritura atómica del JSON que consume el frontend (`frontend/data/news.json`)."""

from gaming_news_digest.models import NewsItem


def save_digest(items: list[NewsItem]) -> None:
    """Stub: guarda el digest en frontend/data/news.json."""


def load_digest() -> list[NewsItem]:
    """Stub: carga el digest existente."""
    return []
