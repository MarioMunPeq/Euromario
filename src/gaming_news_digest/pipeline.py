"""Orquestador del pipeline con lógica de fallback Ollama→Groq."""

import logging
import re
import time
from collections import defaultdict
from collections.abc import Iterator

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
        # Clustering: agrupar por historia y seleccionar representante
        clustered = cluster_and_select_representatives(filtered)
        logger.info("Clustering: %d items -> %d historias", len(filtered), len(clustered))

        # Límite por juego ANTES de la IA: los candidatos que exceden el cap por
        # juego jamás se publicarían; se descartan primero (orden determinista por
        # actualidad; la relevancia aún no existe) y la IA solo se gasta en las
        # historias supervivientes (p. ej. 62 -> ~9 llamadas).
        # Reddit (rumores/leaks) se salta este pre-límite para que no se pierda
        # contenido antes de la IA.
        prelimited = _limit_stories_per_game(
            clustered, self.limits.max_stories_per_game, skip_reddit_before_ai=True
        )
        logger.info(
            "Pre-límite por juego (%d) antes de IA (Reddit sin límite): %d -> %d historias",
            self.limits.max_stories_per_game,
            len(clustered),
            len(prelimited),
        )

        enriched = list(self._enrich_with_ai(prelimited))

        # Re-aplicar el límite por juego TRAS la IA (relevancia + fecha): conserva
        # el ranking relevancia→fecha exacto y garantiza el cap sobre los supervivientes.
        limited = _limit_stories_per_game(enriched, self.limits.max_stories_per_game)
        logger.info(
            "Límite por juego (%d) tras IA: %d -> %d historias",
            self.limits.max_stories_per_game,
            len(enriched),
            len(limited),
        )

        retained = apply_retention(limited, max_age_hours=48, max_total=200, max_per_game=self.limits.max_stories_per_game)
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
                    fetched_at=item.fetched_at,
                    body_text=item.body_text,
                    language=item.language,
                    game=game,
                    image_url=item.image_url,
                    author=item.author,
                    game_id=item.game_id,
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

            # Verificar caché: si ya tenemos resultado de IA para esta URL, reutilizarlo
            from gaming_news_digest.models import normalize_url
            cache_key = normalize_url(item.url)
            cached = self._ai_cache.get(cache_key)
            if cached is not None:
                logger.info(
                    "Item '%s' (fuente=%s): reutilizando resultado de IA caché",
                    item.title, item.source.name
                )
                ai_data = cached
                is_fallback = cached["is_fallback"]
            else:
                ai_data = self._summarize_with_fallback(item)
                is_fallback = ai_data is None
                if is_fallback:  # fallback seguro documentado
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

            # is_verified = True para medios oficiales y Steam, False para Reddit
            is_verified = item.source.type != SourceType.REDDIT
            # Regla determinista aprobada: todo item de subreddit es un rumor;
            # sobreescribe lo que haya devuelto el modelo (fix RUMORS/Reddit).
            category = ai_data["category"]
            if item.source.type is SourceType.REDDIT:
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