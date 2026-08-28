"""Orquestador del pipeline con lógica de fallback Ollama→Groq."""

import logging
import re
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field

import requests

from gaming_news_digest.ai.base import AIClient, AIError
from gaming_news_digest.ai.groq_client import GroqClient
from gaming_news_digest.ai.ollama_client import OllamaClient
from gaming_news_digest.clustering import cluster_and_select_representatives
from gaming_news_digest.config import GamesConfig, Limits, SourcesConfig
from gaming_news_digest.fetchers.base import FetchError, build_session
from gaming_news_digest.fetchers.reddit import (
    REDDIT_REQUEST_INTERVAL_SECONDS,
    fetch_subreddit,
)
from gaming_news_digest.fetchers.rss import fetch_media_feed
from gaming_news_digest.fetchers.steam import fetch_steam_news
from gaming_news_digest.filtering.matcher import create_matcher
from gaming_news_digest.models import (
    Category,
    FetchedItem,
    ModelValidationError,
    NewsItem,
    SourceType,
)
from gaming_news_digest.storage.json_store import save_digest, save_games_config
from gaming_news_digest.storage.retention import apply_retention

logger = logging.getLogger(__name__)

# Fallback seguro para items que fallan la IA
_SAFE_FALLBACK = {
    "summary": None,
    "relevance": 1,
    "category": "rumor",
}


# ============================================================
# Diagnóstico: estadísticas por etapa (Reddit vs Media/Steam)
# ============================================================

@dataclass
class StageStats:
    """Estadísticas de una etapa del pipeline separadas por fuente."""
    total: int = 0
    reddit: int = 0
    media_steam: int = 0
    reddit_subs: dict[str, int] = field(default_factory=dict)
    reddit_titles: list[str] = field(default_factory=list)  # primeros N títulos para diagnóstico

    def add(self, item: FetchedItem | NewsItem) -> None:
        self.total += 1
        if getattr(item.source, "type", None) is SourceType.REDDIT:
            self.reddit += 1
            sub = getattr(item.source, "subreddit", "unknown")
            self.reddit_subs[sub] = self.reddit_subs.get(sub, 0) + 1
            if len(self.reddit_titles) < 10:
                self.reddit_titles.append(item.title)
        else:
            self.media_steam += 1

    def log(self, stage: str) -> None:
        logger.info(
            "=== %s === Total=%d | Reddit=%d | Media/Steam=%d",
            stage, self.total, self.reddit, self.media_steam
        )
        if self.reddit_subs:
            for sub, cnt in self.reddit_subs.items():
                logger.info("  Reddit r/%s: %d items", sub, cnt)
        if self.reddit_titles:
            for i, title in enumerate(self.reddit_titles):
                logger.info("  Reddit[%d]: %s", i + 1, title)

    @staticmethod
    def log_separator() -> None:
        logger.info("=" * 60)


def _split_by_source(items: list[FetchedItem | NewsItem]) -> tuple[list, list]:
    """Separa items en (reddit_items, media_steam_items)."""
    reddit = [it for it in items if getattr(it.source, "type", None) is SourceType.REDDIT]
    media = [it for it in items if getattr(it.source, "type", None) is not SourceType.REDDIT]
    return reddit, media


def _count_by_source(items: list[FetchedItem | NewsItem]) -> dict:
    """Devuelve conteo {'total': N, 'reddit': N, 'media_steam': N}."""
    reddit, media = _split_by_source(items)
    return {"total": len(items), "reddit": len(reddit), "media_steam": len(media)}


# Fallback seguro para items que fallan la IA
_SAFE_FALLBACK = {
    "summary": None,
    "relevance": 1,
    "category": "rumor",
}


def _limit_stories_per_game(
    items: list[FetchedItem | NewsItem], max_per_game: int, *, skip_reddit_before_ai: bool = False
) -> list[FetchedItem | NewsItem]:
    """Limita el número de historias por juego por relevancia y actualidad.

    Se usa tanto ANTES de la IA (sobre ``FetchedItem``, que aún no tiene
    ``relevance``) como DESPUÉS (sobre ``NewsItem``). Con
    ``getattr(item, "relevance", 0)`` ordena solo por fecha mientras la
    relevancia no existe y conserva el ranking exacto relevancia→fecha una
    vez la IA la asignó.

    Si ``skip_reddit_before_ai`` es True, los items de SourceType.REDDIT
    no se limitan en la fase ANTES de la IA (sí en la posterior).
    """
    if max_per_game <= 0:
        return items

    # Agrupar por juego
    by_game: dict[str, list[FetchedItem | NewsItem]] = defaultdict(list)
    for item in items:
        by_game[item.game].append(item)

    # Para cada juego, ordenar por relevancia (desc) y luego por fecha (más reciente primero)
    # y quedarse con los max_per_game primeros
    limited: list[NewsItem] = []
    for game_items in by_game.values():
        # Separar items de Reddit si se debe saltar el pre-límite
        if skip_reddit_before_ai:
            reddit_items = [it for it in game_items if getattr(it.source, "type", None) is SourceType.REDDIT]
            other_items = [it for it in game_items if getattr(it.source, "type", None) is not SourceType.REDDIT]
        else:
            reddit_items = []
            other_items = game_items

        # Aplicar límite solo a los items no-Reddit (o a todos si no se salta)
        if len(other_items) <= max_per_game:
            limited.extend(other_items)
        else:
            sorted_items = sorted(
                other_items,
                key=lambda x: (getattr(x, "relevance", 0), x.published_at),
                reverse=True,
            )
            limited.extend(sorted_items[:max_per_game])

        # Los items de Reddit siempre pasan (en pre-límite) o se limitan (en post-límite)
        limited.extend(reddit_items)

    return limited


def _limit_stories_per_game_separate(
    items: list[FetchedItem | NewsItem],
    media_limit: int,
    reddit_limit: int,
) -> list[FetchedItem | NewsItem]:
    """Aplica límites separados por juego para medios y Reddit (post-IA).

    - Medios/Steam: límite media_limit
    - Reddit: límite reddit_limit (típicamente más alto para rumores)
    """
    if media_limit <= 0 and reddit_limit <= 0:
        return items

    # Agrupar por juego
    by_game: dict[str, list[FetchedItem | NewsItem]] = defaultdict(list)
    for item in items:
        by_game[item.game].append(item)

    limited: list[NewsItem] = []
    for game_items in by_game.values():
        reddit_items = [it for it in game_items if getattr(it.source, "type", None) is SourceType.REDDIT]
        other_items = [it for it in game_items if getattr(it.source, "type", None) is not SourceType.REDDIT]

        # Aplicar límite a medios
        if other_items:
            if len(other_items) <= media_limit:
                limited.extend(other_items)
            else:
                sorted_items = sorted(
                    other_items,
                    key=lambda x: (getattr(x, "relevance", 0), x.published_at),
                    reverse=True,
                )
                limited.extend(sorted_items[:media_limit])

        # Aplicar límite a Reddit
        if reddit_items:
            if len(reddit_items) <= reddit_limit:
                limited.extend(reddit_items)
            else:
                sorted_items = sorted(
                    reddit_items,
                    key=lambda x: (getattr(x, "relevance", 0), x.published_at),
                    reverse=True,
                )
                limited.extend(sorted_items[:reddit_limit])

    return limited


class Pipeline:
    """Orquesta fetch -> filtro -> límite por juego -> IA -> límite -> retención -> guardado."""

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
        self._ai_cache: dict[str, dict] = {}  # url -> {summary, relevance, category, is_fallback}

    def _load_ai_cache(self) -> None:
        """Carga el digest existente y construye caché de resultados de IA por URL.
        
        Solo cachea items con summary no-None (procesados exitosamente por IA).
        """
        from gaming_news_digest.storage.json_store import load_existing_digest
        existing = load_existing_digest()
        cached = 0
        for item in existing:
            if item.summary is not None and item.summary.strip():
                # Usar la URL normalizada como clave de caché
                from gaming_news_digest.models import normalize_url
                key = normalize_url(item.url)
                self._ai_cache[key] = {
                    "summary": item.summary,
                    "relevance": item.relevance,
                    "category": item.category,
                    "is_fallback": item.summary_is_fallback,
                }
                cached += 1
        if cached:
            logger.info("Caché de IA cargado: %d items con summary reutilizable", cached)

    def run(self) -> None:
        """Ejecuta el pipeline completo y guarda el digest."""
        # Cargar caché de IA ANTES de fetch/filtrado para reutilizar resultados previos
        self._load_ai_cache()
        
        fetched = self._fetch_all()
        filtered = self._filter(fetched)
        
        # Diagnóstico CLUSTERING
        StageStats.log_separator()
        clustered = cluster_and_select_representatives(filtered)
        stats_filtered = _count_by_source(filtered)
        stats_clustered = _count_by_source(clustered)
        logger.info(
            "DIAGNÓSTICO CLUSTERING: in=%d (reddit=%d, media=%d) -> out=%d (reddit=%d, media=%d) | grupos reducidos: %d",
            stats_filtered["total"], stats_filtered["reddit"], stats_filtered["media_steam"],
            stats_clustered["total"], stats_clustered["reddit"], stats_clustered["media_steam"],
            stats_filtered["total"] - stats_clustered["total"]
        )
        StageStats.log_separator()

        # Límite por juego ANTES de la IA
        media_prelimit = self.limits.max_stories_per_game + 4
        prelimited = _limit_stories_per_game(
            clustered, media_prelimit, skip_reddit_before_ai=True
        )
        
        # Diagnóstico PRE-LÍMITE
        stats_pre = _count_by_source(prelimited)
        logger.info(
            "DIAGNÓSTICO PRE-LÍMITE: total=%d (reddit=%d, media=%d) | Reddit bypassed: SÍ | Media limit: %d",
            stats_pre["total"], stats_pre["reddit"], stats_pre["media_steam"], media_prelimit
        )
        StageStats.log_separator()

        # IA
        enriched = list(self._enrich_with_ai(prelimited))
        
        # Diagnóstico IA
        stats_enriched = _count_by_source(enriched)
        logger.info(
            "DIAGNÓSTICO IA: total=%d (reddit=%d, media=%d)",
            stats_enriched["total"], stats_enriched["reddit"], stats_enriched["media_steam"]
        )
        StageStats.log_separator()

        # Post-límite
        limited = _limit_stories_per_game_separate(
            enriched,
            media_limit=self.limits.max_stories_per_game,
            reddit_limit=self.limits.max_stories_per_game_reddit,
        )
        
        # Diagnóstico POST-LÍMITE
        stats_limited = _count_by_source(limited)
        logger.info(
            "DIAGNÓSTICO POST-LÍMITE: total=%d (reddit=%d, media=%d) | pre-límite reddit=%d -> post-límite reddit=%d | límite reddit: %d",
            stats_limited["total"], stats_limited["reddit"], stats_limited["media_steam"],
            stats_pre["reddit"], stats_limited["reddit"], self.limits.max_stories_per_game_reddit
        )
        StageStats.log_separator()

        # Retención
        retained = apply_retention(limited, max_age_hours=48, max_total=200, max_per_game=self.limits.max_stories_per_game)
        
        # Diagnóstico FINAL
        stats_final = _count_by_source(retained)
        logger.info("=" * 60)
        logger.info("=== DIAGNÓSTICO FINAL REDDIT ===")
        logger.info("  Fetched: %d", _count_by_source(fetched)["reddit"])
        logger.info("  After clustering: %d", _count_by_source(clustered)["reddit"])
        logger.info("  Before AI: %d", stats_pre["reddit"])
        logger.info("  AI processed: %d", stats_enriched["reddit"])
        logger.info("  After post-limit: %d", stats_limited["reddit"])
        logger.info("  Final digest: %d", stats_final["reddit"])
        logger.info("=== DIAGNÓSTICO FINAL MEDIA/STEAM ===")
        logger.info("  Fetched: %d", _count_by_source(fetched)["media_steam"])
        logger.info("  After clustering: %d", _count_by_source(clustered)["media_steam"])
        logger.info("  Before AI: %d", stats_pre["media_steam"])
        logger.info("  AI processed: %d", stats_enriched["media_steam"])
        logger.info("  After post-limit: %d", stats_limited["media_steam"])
        logger.info("  Final digest: %d", stats_final["media_steam"])
        logger.info("=" * 60)

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

        reddit_subs = list(self.sources.reddit.subreddits)
        for index, sub in enumerate(reddit_subs):
            try:
                items.extend(fetch_subreddit(sub, self.sources.limits, session))
            except FetchError as exc:
                logger.warning("Reddit r/%s: %s", sub.name, exc)
            if index < len(reddit_subs) - 1:
                time.sleep(REDDIT_REQUEST_INTERVAL_SECONDS)

        # Diagnóstico FETCH
        stats = StageStats()
        for item in items:
            stats.add(item)
        stats.log("DIAGNÓSTICO FETCH")
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
                    fetched_at=item.fetched_at,
                    body_text=item.body_text,
                    language=item.language,
                    game=game,
                    image_url=item.image_url,
                    author=item.author,
                    game_id=item.game_id,
                )
                kept.append(item)
        
        # Diagnóstico FILTRADO
        stats_in = StageStats()
        for item in items:
            stats_in.add(item)
        stats_out = StageStats()
        for item in kept:
            stats_out.add(item)
        logger.info(
            "DIAGNÓSTICO FILTRO: in=%d (reddit=%d, media=%d) -> out=%d (reddit=%d, media=%d) | rechazados: total=%d, reddit=%d, media=%d",
            stats_in.total, stats_in.reddit, stats_in.media_steam,
            stats_out.total, stats_out.reddit, stats_out.media_steam,
            stats_in.total - stats_out.total,
            stats_in.reddit - stats_out.reddit,
            stats_in.media_steam - stats_out.media_steam
        )
        if stats_out.reddit_titles:
            for i, title in enumerate(stats_out.reddit_titles):
                logger.info("  Filtro Reddit[%d]: %s", i + 1, title)
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
        # Contadores para diagnóstico IA
        ai_stats = {
            "total": 0,
            "reddit_total": 0,
            "media_total": 0,
            "reddit_cache": 0,
            "media_cache": 0,
            "reddit_new": 0,
            "media_new": 0,
            "reddit_fallback": 0,
            "media_fallback": 0,
        }
        
        for i, item in enumerate(items):
            if self.current_client is self.groq and i > 0:
                time.sleep(1)  # rate limit: 1 req/s para Groq free tier

            # Verificar caché: si ya tenemos resultado de IA para esta URL, reutilizarlo
            from gaming_news_digest.models import normalize_url
            cache_key = normalize_url(item.url)
            is_reddit = getattr(item.source, "type", None) is SourceType.REDDIT
            ai_stats["total"] += 1
            if is_reddit:
                ai_stats["reddit_total"] += 1
            else:
                ai_stats["media_total"] += 1

            cached = self._ai_cache.get(cache_key)
            if cached is not None:
                if is_reddit:
                    ai_stats["reddit_cache"] += 1
                else:
                    ai_stats["media_cache"] += 1
                ai_data = cached
                is_fallback = cached["is_fallback"]
            else:
                ai_data = self._summarize_with_fallback(item)
                is_fallback = ai_data is None
                if is_fallback:
                    if is_reddit:
                        ai_stats["reddit_fallback"] += 1
                    else:
                        ai_stats["media_fallback"] += 1
                    logger.info(
                        "Item '%s' (fuente=%s): summary=null por fallback IA",
                        item.title,
                        item.source.name,
                    )
                    ai_data = _SAFE_FALLBACK
                # Guardar en caché para futuras ejecuciones (solo si no es fallback)
                elif not is_fallback:
                    self._ai_cache[cache_key] = {
                        "summary": ai_data["summary"],
                        "relevance": ai_data["relevance"],
                        "category": ai_data["category"],
                        "is_fallback": False,
                    }
                    if is_reddit:
                        ai_stats["reddit_new"] += 1
                    else:
                        ai_stats["media_new"] += 1

            # is_verified = True para medios oficiales y Steam, False para Reddit
            is_verified = not is_reddit
            # Regla determinista aprobada: todo item de subreddit es un rumor;
            # sobreescribe lo que haya devuelto el modelo (fix RUMORS/Reddit).
            category = ai_data["category"]
            if is_reddit:
                category = Category.RUMOR.value
            try:
                yield NewsItem(
                    title=item.title,
                    url=item.url,
                    source=item.source,
                    game=item.game or "",
                    language=item.language.value if item.language else "en",
                    published_at=item.published_at,
                    fetched_at=item.fetched_at,
                    relevance=ai_data["relevance"],
                    category=category,
                    summary=ai_data["summary"],
                    image_url=item.image_url,
                    author=item.author,
                    summary_is_fallback=is_fallback,
                    game_id=item.game_id,
                    is_verified=is_verified,
                )
            except ModelValidationError as exc:
                # regla P0: un item inválido se descarta; nunca tumba el resto
                logger.warning(
                    "Noticia inválida descartada (fuente=%s título=%r motivo=%s)",
                    item.source.name,
                    item.title,
                    exc,
                )
                continue
        
        # Log diagnóstico IA al final
        logger.info(
            "DIAGNÓSTICO IA PROCESAMIENTO: total=%d (reddit=%d, media=%d) | cache: reddit=%d, media=%d | new IA: reddit=%d, media=%d | fallback: reddit=%d, media=%d",
            ai_stats["total"],
            ai_stats["reddit_total"],
            ai_stats["media_total"],
            ai_stats["reddit_cache"],
            ai_stats["media_cache"],
            ai_stats["reddit_new"],
            ai_stats["media_new"],
            ai_stats["reddit_fallback"],
            ai_stats["media_fallback"],
        )
        StageStats.log_separator()

    def _summarize_with_fallback(self, item) -> dict | None:
        """
        Intenta resumir con cliente actual; maneja fallback y errores.
        Devuelve dict con summary/relevance/category o None (fallback seguro).
        """
        while True:
            try:
                source_type = item.source.type.value
                result = self.current_client.summarize(
                    title=item.title,
                    body=item.body_text or "",
                    source_language=item.language.value if item.language else "en",
                    game=item.game or "",
                    source_type=source_type,
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
                                "Ollama: %d AIError consecutivos -> switch a Groq y reintento",
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
                    logger.warning("Ollama infra: %s -> switch a Groq", exc)
                    self.current_client = self.groq
                    continue
                logger.exception("Error inesperado en IA")
                return None

    def _save_games_config(self) -> None:
        """Guarda el mapeo nombre->logo->platform para el frontend."""
        games_data = []
        for rule in self._games.include:
            entry: dict = {"name": rule.name, "logo": rule.logo}
            if rule.platform:
                entry["platform"] = list(rule.platform)
            games_data.append(entry)
        save_games_config(games_data)


def create_pipeline(sources, games, limits) -> Pipeline:
    return Pipeline(sources, games, limits)