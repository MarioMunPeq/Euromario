"""Orquestador del pipeline con lógica de fallback Ollama→Groq."""

import logging
import re
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

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
from gaming_news_digest.filtering.matcher import (
    _EVENT_ANCHOR_WORDS as _NEWS_KEYWORDS,
)
from gaming_news_digest.filtering.matcher import (
    _detect_game_name_with_reason,
    _normalize,
    create_matcher,
)
from gaming_news_digest.filtering.topic import (
    classify_video_game_article as _classify_video_game_article,
)
from gaming_news_digest.models import (
    Category,
    FetchedItem,
    ModelValidationError,
    NewsItem,
    SourceType,
)
from gaming_news_digest.storage.json_store import save_digest, save_games_config
from gaming_news_digest.storage.retention import apply_retention, utc_now

logger = logging.getLogger(__name__)

# Nombre genérico para noticias de medios cuyo juego no se puede identificar
# (y no está excluido). Sin whitelist: la noticia se publica de todos modos.
_DEFAULT_GAME_NAME = "Videojuegos"

# Ventana temporal del digest DIARIO: ~24 horas + 2 horas de tolerancia.
# El cron de GitHub Actions no es puntilloso y los feeds publican tarde a
# veces; 26 horas cubre "lo de ayer" sin arrastrar más historia de la cuenta.
_DIGEST_WINDOW_HOURS = 26

# Pre-ranking ANTES de la IA: se recorta el total enviado al modelo a ~40-60
# items con señales baratas (nunca con la IA). No es una whitelist: los juegos
# no configurados compiten con las mismas señales. Los rumores de Reddit
# conservan un mínimo reservado para no vaciar la sección.
_PRE_RANK_TARGET_MAX = 60
_PRE_RANK_REDDIT_FLOOR = 8

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


def _is_reddit(item: FetchedItem | NewsItem) -> bool:
    return getattr(item.source, "type", None) is SourceType.REDDIT


def _pre_rank_score(
    item: FetchedItem | NewsItem,
    featured_names: set[str],
    now: datetime,
) -> float:
    """Puntuación barata y determinista para ordenar antes de llamar a la IA.

    Señales (nunca la IA, nunca el nombre del juego como criterio excluyente):
    - actualidad: los últimos ~24 h puntúan alto (decae en 48 h);
    - palabra clave de noticia en el titular (patch, update, announce...);
    - juego destacado en ``games.yaml`` (logo disponibles en el frontend);
    - fuente verificada (medios/Steam) sobre Reddit.
    """
    score = 0.0
    if item.published_at:
        age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600.0)
        score += min(1.0, max(0.0, 1.0 - age_hours / 48.0))
    title_words = set(_normalize(item.title or "").split())
    if title_words & _NEWS_KEYWORDS:
        score += 2.0
    if (item.game or "").casefold() in featured_names:
        score += 3.0
    if not _is_reddit(item):
        score += 1.0
    return score


def _pre_rank_for_ai(
    items: list[FetchedItem | NewsItem],
    featured_names: set[str] | frozenset[str] | None = None,
    *,
    target_max: int = _PRE_RANK_TARGET_MAX,
    reddit_floor: int = _PRE_RANK_REDDIT_FLOOR,
    now: datetime | None = None,
) -> list[FetchedItem | NewsItem]:
    """Recorta el total de items ANTES de la IA a ``target_max`` (~40-60).

    Solo actúa si sobran; si no, devuelve la misma lista sin tocar. Los juegos
    no configurados en ``games.yaml`` compiten con las mismas señales baratas
    (está PROHIBIDO descartar solo por no estar configurado). Los rumores de
    Reddit mantienen un mínimo (``reddit_floor``) para no vaciar la sección.
    Devuelve los supervivientes en el orden original de entrada.
    """
    if len(items) <= target_max:
        return items

    featured = {name.casefold() for name in (featured_names or ())}
    if now is None:
        now = utc_now()

    scored = sorted(
        items,
        key=lambda it: (_pre_rank_score(it, featured, now), it.published_at, it.url),
        reverse=True,
    )
    picked = scored[:target_max]
    dropped = scored[target_max:]

    # Piso de Reddit: sustituir los peores no-reddit elegidos por los mejores
    # reddit descartados (los picked están en orden descendente de puntuación).
    if reddit_floor > 0:
        reddit_picked = [it for it in picked if _is_reddit(it)]
        reddit_dropped = [it for it in dropped if _is_reddit(it)]
        missing = reddit_floor - len(reddit_picked)
        non_reddit_indices = [i for i, it in enumerate(picked) if not _is_reddit(it)]
        for _ in range(min(missing, len(reddit_dropped), len(non_reddit_indices))):
            picked[non_reddit_indices.pop()] = reddit_dropped.pop(0)

    picked_ids = {id(it) for it in picked}
    return [it for it in items if id(it) in picked_ids]


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

        # Diagnóstico JUEGOS (tras filtro): identificado, sin_identificar (Videojuegos),
        # reddit. Permite ver calidad del matcher al vuelo.
        identificado = 0
        videojuegos = 0
        reddit_cnt = 0
        for item in filtered:
            if getattr(item.source, "type", None) is SourceType.REDDIT:
                reddit_cnt += 1
            elif item.game == _DEFAULT_GAME_NAME:
                videojuegos += 1
            else:
                identificado += 1
        logger.info(
            "DIAGNÓSTICO JUEGOS: identificado=%d | sin_identificar(Videojuegos)=%d | reddit=%d | media/steam total=%d",
            identificado, videojuegos, reddit_cnt, identificado + videojuegos
        )

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

        # Pre-ranking ANTES de la IA: señales baratas (actualidad, tipo de
        # noticia, juego destacado, fuente verificada) sin coste de inferencia.
        # NO es una whitelist: los juegos no configurados compiten igual.
        featured_names = {rule.name for rule in self._games.include}
        preranked = _pre_rank_for_ai(prelimited, featured_names)

        # Diagnóstico PRE-RANK
        stats_prerank = _count_by_source(preranked)
        logger.info(
            "DIAGNÓSTICO PRE-RANK: total=%d (reddit=%d, media=%d) | target_max=%d | recortados: %d",
            stats_prerank["total"], stats_prerank["reddit"], stats_prerank["media_steam"],
            _PRE_RANK_TARGET_MAX, stats_pre["total"] - stats_prerank["total"],
        )
        StageStats.log_separator()

        # IA
        enriched = list(self._enrich_with_ai(preranked))
        
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

        # Retención: Reddit tiene bloque independiente con su propio límite por juego.
        # Ventana del digest DIARIO: ~24 h + tolerancia (26 h) para cubrir "lo de ayer".
        retained = apply_retention(
            limited,
            max_age_hours=_DIGEST_WINDOW_HOURS,
            max_total=200,
            max_per_game=self.limits.max_stories_per_game,
            max_per_game_reddit=self.limits.max_stories_per_game_reddit,
        )
        
        # Diagnóstico FINAL
        stats_final = _count_by_source(retained)
        logger.info("=" * 60)
        logger.info("=== DIAGNÓSTICO FINAL REDDIT ===")
        logger.info("  Fetched: %d", _count_by_source(fetched)["reddit"])
        logger.info("  After clustering: %d", _count_by_source(clustered)["reddit"])
        logger.info("  Before AI (pre-rank): %d", _count_by_source(preranked)["reddit"])
        logger.info("  AI processed: %d", stats_enriched["reddit"])
        logger.info("  After post-limit: %d", stats_limited["reddit"])
        logger.info("  Final digest: %d", stats_final["reddit"])
        logger.info("=== DIAGNÓSTICO FINAL MEDIA/STEAM ===")
        logger.info("  Fetched: %d", _count_by_source(fetched)["media_steam"])
        logger.info("  After clustering: %d", _count_by_source(clustered)["media_steam"])
        logger.info("  Before AI (pre-rank): %d", _count_by_source(preranked)["media_steam"])
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
        # Contadores GAME MATCH por motivo (solo medios/Steam: Reddit no
        # pasa por detección). Permiten detectar falsos positivos del matcher.
        game_stats: dict[str, int] = {
            "config": 0,
            "hint": 0,
            "anchor": 0,
            "known_title": 0,
            "no_confident_match": 0,
            "videojuegos": 0,
        }
        # Contadores del FILTRO TEMÁTICO (solo medios RSS): señalan cuántos
        # artículos se descartan por NO ser de videojuegos y con qué motivo.
        topic_stats: dict[str, int] = {
            "total_media": 0,
            "aceptados": 0,
            "descartados": 0,
        }
        for item in items:
            if self._is_excluded(item):
                continue
            
            is_reddit = getattr(item.source, "type", None) is SourceType.REDDIT
            
            if is_reddit:
                # Reddit: bypass game matching, keep all items that pass technical checks
                # Assign a generic game name for Reddit items (they'll be properly categorized by AI)
                item = FetchedItem(
                    title=item.title,
                    url=item.url,
                    source=item.source,
                    published_at=item.published_at,
                    fetched_at=item.fetched_at,
                    body_text=item.body_text,
                    language=item.language,
                    game="Reddit Rumors",  # Generic game for Reddit rumors
                    image_url=item.image_url,
                    author=item.author,
                    game_id=item.game_id,
                )
                kept.append(item)
            else:
                # Media/Steam:
                # 1. Exclusión GLOBAL (poison pill): cualquier mención de un
                #    juego excluido descarta el artículo completo.
                body = item.body_text or ""
                if self.matcher.is_excluded(item.title, body):
                    continue

                # 1b. FILTRO TEMÁTICO (solo medios RSS): el dominio de la
                #     fuente NO basta. Cada artículo debe demostrar que es
                #     videojuegos (Polygon/IGN publican cine, series, cómics).
                #     Steam se salta el filtro: es un feed del propio juego.
                if item.source.type is SourceType.MEDIA:
                    ok_topic, topic_reason = _classify_video_game_article(
                        item.title, body, item.url, item.feed_categories
                    )
                    topic_stats["total_media"] += 1
                    topic_stats.setdefault(topic_reason, 0)
                    if not ok_topic:
                        topic_stats["descartados"] += 1
                        topic_stats[topic_reason] += 1
                        logger.info(
                            'TEMÁTICA: DESCARTADO "%s" [%s]', item.title, topic_reason
                        )
                        continue
                    topic_stats["aceptados"] += 1
                    topic_stats[topic_reason] += 1
                    logger.info(
                        'TEMÁTICA: OK "%s" [%s]', item.title, topic_reason
                    )

                # 2. Juego configurado (games.yaml): entra con nombre canónico
                #    si es tema principal.
                accepted, game = self.matcher.match(item.title, body)
                if accepted:
                    reason = "config"
                    game_stats["config"] += 1
                else:
                    # 3. Juego NO configurado: la noticia se publica igual.
                    #    Se detecta su nombre (Steam: el de la app seguida;
                    #    medios: heurística sobre el titular), o se usa un
                    #    nombre genérico si no se puede concluir nada.
                    hint = None
                    if item.source.type is SourceType.STEAM:
                        name = item.source.name
                        prefix = "Steam · "
                        if name.startswith(prefix):
                            hint = name[len(prefix):]
                    detected, reason = _detect_game_name_with_reason(item.title, body, hint=hint)
                    if detected:
                        game = detected
                        reason = reason or "anchor"
                        game_stats[reason] = game_stats.get(reason, 0) + 1
                    else:
                        # Sin conclusión fiable -> None -> nombre genérico.
                        reason = "no_confident_match"
                        game = None
                        game_stats[reason] += 1
                # Log por noticia: permite rastrear falsos positivos
                # (GAME MATCH: "título" -> juego o None [motivo]).
                shown = game or "None"
                if game is None:
                    logger.info('GAME MATCH: "%s" -> None [%s]', item.title, reason)
                    game = _DEFAULT_GAME_NAME
                    game_stats["videojuegos"] += 1
                else:
                    logger.info('GAME MATCH: "%s" -> %s [%s]', item.title, shown, reason)
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
        logger.info(
            "GAME MATCH (resumen): config=%d, hint=%d, anchor=%d, known_title=%d, no_confident_match=%d, videojuegos=%d",
            game_stats["config"], game_stats["hint"], game_stats["anchor"],
            game_stats["known_title"], game_stats["no_confident_match"],
            game_stats["videojuegos"],
        )
        topic_reasons = ", ".join(
            f"{k}={v}" for k, v in sorted(topic_stats.items())
            if k not in ("total_media", "aceptados", "descartados") and v
        )
        logger.info(
            "DIAGNÓSTICO TEMÁTICA: media_total=%d -> aceptados=%d, descartados=%d (%s)",
            topic_stats["total_media"],
            topic_stats["aceptados"],
            topic_stats["descartados"],
            topic_reasons or "sin_motivos",
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