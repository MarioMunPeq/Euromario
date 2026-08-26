"""Orquestador del pipeline con lógica de fallback Ollama→Groq."""

import logging
import re
import time
from collections.abc import Iterator

import requests

from gaming_news_digest.ai.base import AIClient, AIError
from gaming_news_digest.ai.groq_client import GroqClient
from gaming_news_digest.ai.ollama_client import OllamaClient
from gaming_news_digest.config import GamesConfig, Limits, SourcesConfig
from gaming_news_digest.fetchers.base import FetchError, build_session
from gaming_news_digest.fetchers.reddit import fetch_subreddit
from gaming_news_digest.fetchers.rss import fetch_media_feed
from gaming_news_digest.fetchers.steam import fetch_steam_news
from gaming_news_digest.filtering.matcher import create_matcher
from gaming_news_digest.models import FetchedItem, NewsItem
from gaming_news_digest.storage.json_store import save_digest, save_games_config
from gaming_news_digest.storage.retention import apply_retention

logger = logging.getLogger(__name__)

# Fallback seguro para items que fallan la IA
_SAFE_FALLBACK = {
    "summary": None,
    "relevance": 1,
    "category": "rumor",
}


class Pipeline:
    """Orquesta fetch → filtro → IA → retención → guardado."""

    def __init__(self, sources: SourcesConfig, games: GamesConfig, limits: Limits):
        self.sources = sources
        self.limits = limits
        self.quality = sources.quality
        self.matcher = create_matcher(games.include, games.exclude)
        self._games = games
        self._title_re = [
            re.compile(p, re.IGNORECASE) for p in self.quality.exclude_title_patterns
        ]
        self._url_re = [
            re.compile(p, re.IGNORECASE) for p in self.quality.exclude_url_patterns
        ]
        self.ollama = OllamaClient()
        self.groq = GroqClient()  # puede lanzar ValueError si no hay API key
        self.current_client: AIClient = self.ollama
        self._consecutive_ai_errors = 0

    def run(self) -> None:
        """Ejecuta el pipeline completo y guarda el digest."""
        fetched = self._fetch_all()
        filtered = self._filter(fetched)
        enriched = list(self._enrich_with_ai(filtered))
        retained = apply_retention(enriched, max_age_days=14, max_total=200)
        save_digest(retained)
        self._save_games_config()

    def _fetch_all(self) -> list[FetchedItem]:
        """Recoge noticias de todas las fuentes configuradas."""
        session = build_session()
        items: list[FetchedItem] = []

        for feed in self.sources.media:
            try:
                items.extend(fetch_media_feed(feed, self.sources.limits, session))
            except FetchError as exc:
                logger.warning("RSS %s: %s", feed.name, exc)

        if self.sources.steam.enabled:
            try:
                items.extend(fetch_steam_news(self.sources.steam, self.sources.limits, session))
            except FetchError as exc:
                logger.warning("Steam: %s", exc)

        for sub in self.sources.reddit.subreddits:
            try:
                items.extend(fetch_subreddit(sub, self.sources.limits, session))
            except FetchError as exc:
                logger.warning("Reddit r/%s: %s", sub.name, exc)

        logger.info("Total fetched: %d items", len(items))
        return items

    def _filter(self, items: list[FetchedItem]) -> list[FetchedItem]:
        kept = []
        for item in items:
            if self._is_excluded(item):
                continue
            accepted, game = self.matcher.match(item.title, item.body_text or "")
            if accepted:
                # enriquece con el juego canónico que matcheó
                item = FetchedItem(
                    title=item.title,
                    url=item.url,
                    source=item.source,
                    published_at=item.published_at,
                    body_text=item.body_text,
                    language=item.language,
                    game=game,
                )
                kept.append(item)
        return kept

    def _is_excluded(self, item: FetchedItem) -> bool:
        for pat in self._title_re:
            if pat.search(item.title):
                return True
        for pat in self._url_re:
            if pat.search(item.url):
                return True
        return False

    def _enrich_with_ai(self, items: list[FetchedItem]) -> Iterator[NewsItem]:
        for i, item in enumerate(items):
            if self.current_client is self.groq and i > 0:
                time.sleep(1)  # rate limit: 1 req/s para Groq free tier
            ai_data = self._summarize_with_fallback(item)
            if ai_data is None:  # fallback seguro
                ai_data = _SAFE_FALLBACK
            yield NewsItem(
                title=item.title,
                url=item.url,
                source=item.source,
                game=item.game or "",
                language=item.language.value if item.language else "en",
                published_at=item.published_at,
                relevance=ai_data["relevance"],
                category=ai_data["category"],
                summary=ai_data["summary"],
                image_url=item.image_url,
            )

    def _summarize_with_fallback(self, item) -> dict | None:
        """
        Intenta resumir con cliente actual; maneja fallback y errores.
        Devuelve dict con summary/relevance/category o None (fallback seguro).
        """
        while True:
            try:
                result = self.current_client.summarize(
                    title=item.title,
                    body=item.body_text or "",
                    source_language=item.language.value if item.language else "en",
                    game=item.game or "",
                )
                self._consecutive_ai_errors = 0
                return {
                    "summary": result.summary,
                    "relevance": result.relevance,
                    "category": result.category.value,
                }
            except Exception as exc:
                if isinstance(exc, AIError):
                    if self.current_client is self.ollama:
                        self._consecutive_ai_errors += 1
                        if self._consecutive_ai_errors >= self.ollama.MAX_CONSECUTIVE_ERRORS:
                            logger.warning(
                                "Ollama: %d AIError consecutivos → switch a Groq y reintento",
                                self._consecutive_ai_errors,
                            )
                            self.current_client = self.groq
                            self._consecutive_ai_errors = 0
                            continue
                        logger.warning("AIError en %s: fallback seguro", item.title)
                        return None
                    logger.warning("AIError en %s: fallback seguro", item.title)
                    return None
                if isinstance(exc, (ConnectionError, TimeoutError, requests.HTTPError)):
                    if self.current_client is self.groq:
                        logger.critical("Fallo crítico en Groq: %s", exc)
                        raise
                    logger.warning("Ollama infra: %s → switch a Groq", exc)
                    self.current_client = self.groq
                    continue
                logger.exception("Error inesperado en IA")
                return None

    def _save_games_config(self) -> None:
        """Guarda el mapeo nombre→logo para el frontend."""
        games_data = []
        for rule in self._games.include:
            entry = {"name": rule.name, "logo": rule.logo}
            games_data.append(entry)
        save_games_config(games_data)


def create_pipeline(sources, games, limits) -> Pipeline:
    return Pipeline(sources, games, limits)