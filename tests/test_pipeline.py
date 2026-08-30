"""Tests del pipeline con lógica de fallback Ollama→Groq."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from gaming_news_digest.ai.base import AIError, AISummary, Category, Language
from gaming_news_digest.models import FetchedItem, NewsItem, Source
from gaming_news_digest.pipeline import Pipeline

# Reloj fijo para todos los filtros temporales del pipeline (PROBLEMA 7):
# hoy = 2026-08-30. Las fixtures publican relativo a NOW, así que pasan la
# ventana de 24 h; los tests de edad inyectan fechas explícitas a propósito.
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def make_item(title="Noticia", body="Cuerpo", game="Persona", lang="en", url_suffix=""):
    return FetchedItem(
        title=title,
        url=f"https://test.com/{url_suffix or title}",
        source=Source(name="Test", type="media"),
        published_at=NOW - timedelta(hours=1),
        fetched_at=NOW,
        body_text=body,
        language=lang,
        game=game,
    )


def make_reddit_item(title="GTA VI leak", game="Grand Theft Auto"):
    return FetchedItem(
        title=title,
        url="https://reddit.com/r/gamingleaksandrumours/comments/1",
        source=Source(
            name="Reddit · r/gamingleaksandrumours",
            type="reddit",
            subreddit="gamingleaksandrumours",
        ),
        published_at=NOW - timedelta(hours=1),
        fetched_at=NOW,
        body_text="Cuerpo del leak",
        language="en",
        game=game,
    )


def make_ai_summary(summary="ok", relevance=3, category=Category.UPDATE, language=Language.ENGLISH):
    return AISummary(
        summary=summary,
        relevance=relevance,
        category=category,
        language=language,
    )


def make_news_item(title="Noticia", game="Persona", relevance=3, hours_ago=1):
    published = NOW - timedelta(hours=hours_ago)
    return NewsItem(
        title=title,
        url=f"https://test.com/{title}",
        source=Source(name="Test", type="media"),
        game=game,
        language="en",
        published_at=published,
        fetched_at=published,
        relevance=relevance,
        category="actualizacion",
        summary="Resumen de prueba.",
    )


def make_fetched(title="Noticia", game="Persona", hours_ago=1, is_reddit=False):
    published = NOW - timedelta(hours=hours_ago)
    if is_reddit:
        source = Source(
            name="Reddit · r/gamingleaksandrumours",
            type="reddit",
            subreddit="gamingleaksandrumours",
        )
    else:
        source = Source(name="Test", type="media")
    return FetchedItem(
        title=title,
        url=f"https://test.com/{title}-{game}-{hours_ago}-{int(is_reddit)}",
        source=source,
        published_at=published,
        fetched_at=published,
        body_text="Cuerpo",
        language="en",
        game=game,
    )


def test_ollama_ok_groq_no_usado():
    ollama = Mock()
    ollama.summarize.side_effect = [
        make_ai_summary("ok1", 3, Category.UPDATE),
        make_ai_summary("ok2", 2, Category.RUMOR),
    ]
    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.ollama = ollama
    pipeline.groq = Mock()
    pipeline.current_client = ollama
    pipeline._consecutive_ai_errors = 0

    items = [make_item(f"N{i}", f"c{i}", url_suffix=f"item{i}") for i in range(2)]
    results = list(pipeline._enrich_with_ai(items))

    assert len(results) == 2
    assert results[0].summary == "ok1"
    assert results[1].summary == "ok2"
    assert ollama.summarize.call_count == 2


def test_reddit_siempre_rumor_sobreescribe_a_la_ia():
    """La regla determinista fuerza rumor para cualquier item de subreddit,
    aunque el modelo lo haya clasificado como lanzamiento."""
    ollama = Mock()
    ollama.summarize.return_value = make_ai_summary(
        "El reveal puede estar en camino", 4, Category.LAUNCH
    )
    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.ollama = ollama
    pipeline.groq = Mock()
    pipeline.current_client = ollama
    pipeline._consecutive_ai_errors = 0

    results = list(pipeline._enrich_with_ai([make_reddit_item()]))

    assert len(results) == 1
    assert ollama.summarize.call_count == 1  # la IA se consulta igualmente
    assert results[0].category == "rumor"
    assert results[0].is_verified is False


def test_media_no_se_sobreescribe_por_regla_reddit():
    """Un item de medio conserva la categoría devuelta por la IA."""
    ollama = Mock()
    ollama.summarize.return_value = make_ai_summary(
        "Lanzamiento confirmado", 5, Category.LAUNCH
    )
    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.ollama = ollama
    pipeline.groq = Mock()
    pipeline.current_client = ollama
    pipeline._consecutive_ai_errors = 0

    results = list(pipeline._enrich_with_ai([make_item("Anuncio oficial")]))

    assert len(results) == 1
    assert results[0].category == "lanzamiento"


def test_ai_error_item_fallback_seguro_continua():
    ollama = Mock()
    ollama.MAX_CONSECUTIVE_ERRORS = 3
    ollama.summarize.side_effect = [
        AIError("json inválido"),
        make_ai_summary("ok", 3, Category.UPDATE),
    ]
    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.ollama = ollama
    pipeline.groq = Mock()
    pipeline.current_client = ollama
    pipeline._consecutive_ai_errors = 0

    items = [make_item("falla"), make_item("ok")]
    results = list(pipeline._enrich_with_ai(items))

    assert len(results) == 2
    assert results[0].summary is None
    assert results[0].relevance == 1
    assert results[0].category == "rumor"
    assert results[1].summary == "ok"  # el segundo item usa el resumen real


def test_tres_ai_error_consecutivos_switch_a_groq():
    ollama = Mock()
    ollama.MAX_CONSECUTIVE_ERRORS = 3
    ollama.summarize.side_effect = [
        AIError("fail1"),
        AIError("fail2"),
        AIError("fail3"),  # 3er fallo → switch y reintenta MISMO item con Groq
        AIError("fail4"),  # este no debería llamarse porque ya se cambió a Groq
    ]
    groq = Mock()
    groq.summarize.return_value = make_ai_summary("groq ok", 5, Category.LAUNCH)

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.ollama = ollama
    pipeline.groq = groq
    pipeline.current_client = ollama
    pipeline._consecutive_ai_errors = 0

    items = [make_item(f"N{i}") for i in range(4)]
    results = list(pipeline._enrich_with_ai(items))

    # Item 0: fallback, Item 1: fallback, Item 2: switch→reintenta con Groq→éxito, Item 3: Groq ok
    assert results[0].summary is None
    assert results[1].summary is None
    assert results[2].summary == "groq ok"  # el 3er item (índice 2) se reintenta con Groq
    assert results[3].summary == "groq ok"  # el 4to item usa Groq directamente


def test_groq_ai_error_no_aborta_pipeline():
    groq = Mock()
    groq.summarize.side_effect = [
        make_ai_summary("ok1", 3, Category.UPDATE),
        AIError("groq validation fail"),
        make_ai_summary("ok3", 2, Category.RUMOR),
        make_ai_summary("ok4", 1, Category.RUMOR),  # extra por si acaso
    ]
    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.ollama = Mock()
    pipeline.groq = groq
    pipeline.current_client = groq
    pipeline._consecutive_ai_errors = 0

    items = [make_item("ok1", url_suffix="ok1"), make_item("falla groq", url_suffix="fail"), make_item("ok3", url_suffix="ok3")]
    results = list(pipeline._enrich_with_ai(items))

    assert len(results) == 3
    assert results[0].summary == "ok1"
    assert results[1].summary is None  # fallback seguro
    assert results[1].relevance == 1
    assert results[1].category == "rumor"
    assert results[2].summary == "ok3"


def test_groq_infra_critico_aborta_con_parcial(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq = Mock()
    groq.summarize.side_effect = [
        make_ai_summary("ok1", 3, Category.UPDATE),
        ConnectionError("Groq down"),
    ]

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.ollama = Mock()
    pipeline.groq = groq
    pipeline.current_client = groq
    pipeline._consecutive_ai_errors = 0

    items = [make_item("ok1", url_suffix="ok1"), make_item("fallará", url_suffix="fail")]
    with pytest.raises(ConnectionError):
        list(pipeline._enrich_with_ai(items))


def test_limit_por_juego_sin_relevancia_prioriza_lo_mas_reciente():
    """Antes de la IA (FetchedItem) el cap por juego ordena por fecha; la
    fila más reciente sobrevive aunque llegue la primera."""
    from gaming_news_digest.models import FetchedItem
    from gaming_news_digest.pipeline import _limit_stories_per_game

    def fetched(hours_ago):
        published = NOW - timedelta(hours=hours_ago)
        return FetchedItem(
            title=f"historia-{hours_ago}",
            url=f"https://test.com/{hours_ago}",
            source=Source(name="Test", type="media"),
            published_at=published,
            fetched_at=published,
            body_text="Cuerpo",
            language="en",
            game="Persona",
        )

    older_histories = [fetched(h) for h in range(8, 0, -1)]  # 8 viejas
    newer = fetched(0)  # la más reciente
    limited = _limit_stories_per_game(older_histories + [newer], max_per_game=8)

    assert len(limited) == 8
    assert limited[0].published_at == newer.published_at
    assert newer in limited


def test_limit_por_juego_con_relevancia_prioriza_relevancia():
    """Tras la IA (NewsItem) el cap conserva la semántica exacta:
    relevancia desc, luego fecha desc (rank 9 > 8 > 7)."""
    from gaming_news_digest.pipeline import _limit_stories_per_game

    items = [make_news_item(f"historia-{r}", relevance=r, hours_ago=r) for r in range(5, 0, -1)]
    limited = _limit_stories_per_game(items, max_per_game=3)

    assert [it.relevance for it in limited] == [5, 4, 3]


def test_limite_por_juego_se_aplica_antes_de_la_ia(monkeypatch):
    """La IA solo se consulta para las historias que superan el pre-límite
    por juego: las descartadas jamás generan resumen (el gasto de la IA baja
    de 'todo lo agrupado' a 'solo los supervivientes')."""
    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import GamesConfig, Limits, SourcesConfig

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()

    fetched = [make_item(f"N{i}", game="Persona") for i in range(20)]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipeline, "_filter", lambda items, **kw: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    # Pre-límite ahora es 12 (8 + 4), así que 12 items pasan a IA
    assert len(seen_enriched) == 12
    assert len(saved) == 1
    # Post-límite sigue siendo 8
    assert len(saved[0]) == 8


def test_reddit_salta_pre_limite_antes_de_ia(monkeypatch):
    """Los items de Reddit NO se limitan en el pre-límite por juego antes de la IA.
    Deben pasar todos los items de Reddit aunque excedan max_stories_per_game."""
    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import GamesConfig, Limits, SourcesConfig

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()

    # 15 items de Reddit del mismo juego (exceden el límite de 8)
    fetched = [make_reddit_item(f"GTA leak {i}", game="Grand Theft Auto") for i in range(15)]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipeline, "_filter", lambda items, **kw: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game, relevance=3)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    # Todos los 15 items de Reddit deben llegar a la IA (pre-límite saltado)
    assert len(seen_enriched) == 15, f"Esperados 15 items en IA, got {len(seen_enriched)}"
    # Pero post-límite tras IA debe reducir a 8
    assert len(saved) == 1
    assert len(saved[0]) == 8, f"Post-límite debe reducir a 8, got {len(saved[0])}"


def test_media_respeta_pre_limite_antes_de_ia(monkeypatch):
    """Los items de medios SÍ se limitan en el pre-límite por juego antes de la IA."""
    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import GamesConfig, Limits, SourcesConfig

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()

    # 15 items de MEDIOS del mismo juego (exceden el límite de 8)
    fetched = [make_item(f"N{i}", game="Persona") for i in range(15)]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipeline, "_filter", lambda items, **kw: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game, relevance=3)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    # Pre-límite ahora es 12 (8 + 4), así que 12 items pasan a IA
    assert len(seen_enriched) == 12, f"Esperados 12 items en IA, got {len(seen_enriched)}"
    assert len(saved) == 1
    # Post-límite sigue siendo 8
    assert len(saved[0]) == 8


def test_reddit_post_limite_despues_de_ia_funciona(monkeypatch):
    """El post-límite tras la IA SÍ se aplica a Reddit (reduce a max_stories_per_game)."""
    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import GamesConfig, Limits, SourcesConfig

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=5)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()

    # 10 items de Reddit del mismo juego
    fetched = [make_reddit_item(f"Leak {i}", game="Starfield") for i in range(10)]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipeline, "_filter", lambda items, **kw: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game, relevance=3)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    # 10 items llegan a la IA (pre-límite saltado)
    assert len(seen_enriched) == 10
    # Pero post-límite reduce a 5
    assert len(saved) == 1
    assert len(saved[0]) == 5


def test_reddit_filtro_salta_game_matching(monkeypatch):
    """Reddit pasa el filtro sin game matching; los items de medios se
    conservan aunque su juego no esté configurado (sin whitelist) siempre
    que pasen el filtro temático de videojuegos."""
    import re

    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import (
        GamesConfig,
        Limits,
        QualityConfig,
        SourcesConfig,
    )
    
    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()
    pipeline._consecutive_ai_errors = 0
    # Initialize regex patterns for _is_excluded
    pipeline._title_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline._url_re = [re.compile(p, re.IGNORECASE) for p in []]
    # Create a minimal quality config and matcher
    pipeline.quality = QualityConfig()
    pipeline.matcher = pipe.create_matcher((), ())

    # 5 Reddit items + 5 Media items sin game matching válido
    reddit_items = [make_reddit_item(f"Leak {i}", game="Starfield") for i in range(5)]
    # Media items con títulos de videojuegos que NO matchean ningún juego
    # conocido (pasan el filtro temático pero sin nombre de juego).
    media_items = [make_item(f"New Gaming News Item {i}", url_suffix=f"random{i}") for i in range(5)]
    
    fetched = reddit_items + media_items
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    
    # Don't mock _filter - use real filter to test the behavior
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game, relevance=3)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    # Reddit items pasan el filtro sin game matching (5 items)
    # Media items también se conservan aunque su juego no esté configurado
    assert len(seen_enriched) == 10, f"Esperados 10 items en IA (5 reddit + 5 media), got {len(seen_enriched)}"
    reddit_in_ai = sum(1 for it in seen_enriched if it.source.type.value == "reddit")
    assert reddit_in_ai == 5, f"Esperados 5 items Reddit en IA, got {reddit_in_ai}"
    media_in_ai = sum(1 for it in seen_enriched if it.source.type.value != "reddit")
    assert media_in_ai == 5, f"Esperados 5 items Media en IA, got {media_in_ai}"


def test_media_juego_no_configurado_llega_al_digest(monkeypatch):
    """Una noticia de medios sobre un juego que NO está en games.yaml se
    publica igualmente: el pipeline detecta el nombre y no la descarta."""
    import re

    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import (
        GamesConfig,
        Limits,
        QualityConfig,
        SourcesConfig,
    )

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()
    pipeline._consecutive_ai_errors = 0
    pipeline._title_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline._url_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline.quality = QualityConfig()
    pipeline.matcher = pipe.create_matcher((), ())

    fetched = [make_item("Hollow Knight Silksong Patch 1.1 notes", url_suffix="hks")]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    assert len(seen_enriched) == 1
    assert seen_enriched[0].game == "Hollow Knight Silksong"
    assert len(saved) == 1
    assert len(saved[0]) == 1
    assert saved[0][0].game == "Hollow Knight Silksong"


def test_steam_juego_no_configurado_asigna_nombre_de_la_app(monkeypatch):
    """Un juego seguido en Steam pero ausente de games.yaml conserva el
    nombre de la app en vez de descartarse."""
    import re

    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import (
        GamesConfig,
        Limits,
        QualityConfig,
        SourcesConfig,
    )
    from gaming_news_digest.models import Source, SourceType

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()
    pipeline._consecutive_ai_errors = 0
    pipeline._title_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline._url_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline.quality = QualityConfig()
    pipeline.matcher = pipe.create_matcher((), ())

    fetched = [
        FetchedItem(
            title="Major update notes now available",
            url="https://store.steampowered.com/news/app/1086940",
            source=Source(name="Steam · Baldur's Gate 3", type="steam"),
            published_at=NOW - timedelta(hours=1),
            fetched_at=NOW,
            body_text="Cuerpo",
            language="en",
            game=None,
        )
    ]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    assert seen_enriched[0].source.type is SourceType.STEAM
    assert seen_enriched[0].game == "Baldur's Gate 3"
    assert saved[0][0].game == "Baldur's Gate 3"


def test_media_excluido_sigue_descartado(monkeypatch):
    """La exclusión global (poison pill) sigue descartando aunque el juego
    no esté en 'incluir': games.yaml no es whitelist pero sí blacklist."""
    import re

    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import (
        GameRule,
        GamesConfig,
        Limits,
        QualityConfig,
        SourcesConfig,
    )

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()
    pipeline._consecutive_ai_errors = 0
    pipeline._title_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline._url_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline.quality = QualityConfig()
    pipeline.matcher = pipe.create_matcher(
        (), (GameRule(name="EA Sports FC", aliases=["FIFA"]),)
    )

    fetched = [make_item("FIFA 24 new kit announced", url_suffix="fifa-excluido")]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    assert len(seen_enriched) == 0
    assert len(saved[0]) == 0


def test_media_sin_juego_identificable_usa_nombre_generico(monkeypatch):
    """Sin whitelist: una noticia cuyo juego no se puede identificar NO se
    descarta; entra bajo el nombre genérico."""
    import re

    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import (
        GamesConfig,
        Limits,
        QualityConfig,
        SourcesConfig,
    )
    from gaming_news_digest.pipeline import _DEFAULT_GAME_NAME

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()
    pipeline._consecutive_ai_errors = 0
    pipeline._title_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline._url_re = [re.compile(p, re.IGNORECASE) for p in []]
    pipeline.quality = QualityConfig()
    pipeline.matcher = pipe.create_matcher((), ())

    fetched = [make_item("Gaming news of the day no specific title", url_suffix="generico")]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run(now=NOW)

    assert len(seen_enriched) == 1
    assert seen_enriched[0].game == _DEFAULT_GAME_NAME
    assert len(saved) == 1
    assert len(saved[0]) == 1
    assert saved[0][0].game == _DEFAULT_GAME_NAME


class TestPreRankingAntesDeIA:
    """Pre-ranking: señales baratas que acotan el trabajo de la IA (~40-60)."""

    def _noise_title(self, i):
        # Sin palabras-ancla para que la señal de "noticia" no puntúe
        return f"item {i} about nothing in particular"

    def test_dentro_del_maximo_no_actua(self):
        from gaming_news_digest.pipeline import _pre_rank_for_ai
        from gaming_news_digest.storage.retention import utc_now

        items = [make_fetched(self._noise_title(i), "Persona", hours_ago=1) for i in range(50)]
        out = _pre_rank_for_ai(items, {"persona"}, now=utc_now())
        assert out is items

    def test_exceso_recorta_a_target_max(self):
        from gaming_news_digest.pipeline import _PRE_RANK_TARGET_MAX, _pre_rank_for_ai
        from gaming_news_digest.storage.retention import utc_now

        items = [make_fetched(self._noise_title(i), "Persona", hours_ago=1) for i in range(100)]
        out = _pre_rank_for_ai(items, {"persona"}, now=utc_now())
        assert len(out) == _PRE_RANK_TARGET_MAX
        assert len({id(it) for it in out}) == len(out)

    def test_prioriza_actualidad_y_juego_destacado(self):
        from gaming_news_digest.pipeline import _pre_rank_for_ai
        from gaming_news_digest.storage.retention import utc_now

        bland = [make_fetched(self._noise_title(i), "OtroJuego", hours_ago=48) for i in range(60)]
        fresh_featured = make_fetched("Cyberpunk 2077 patch notes released", "Cyberpunk 2077", hours_ago=1)
        out = _pre_rank_for_ai(bland + [fresh_featured], {"cyberpunk 2077"}, now=utc_now())
        assert len(out) == 60
        assert fresh_featured in out

    def test_no_excluye_juegos_no_configurados(self):
        """Un juego ausente de games.yaml compite con las mismas señales:
        nunca se descarta solo por no estar configurado."""
        from gaming_news_digest.pipeline import _pre_rank_for_ai
        from gaming_news_digest.storage.retention import utc_now

        bland = [make_fetched(self._noise_title(i), "Videojuegos", hours_ago=48) for i in range(60)]
        unconfigured = make_fetched("Some new leak about unlisted sequel", "Unlisted Game", hours_ago=1)
        out = _pre_rank_for_ai(bland + [unconfigured], {"cyberpunk 2077"}, now=utc_now())
        assert unconfigured in out

    def test_piso_reddit_preserva_rumores(self):
        """Aunque 80 noticias de medios puntúen más, los rumores de Reddit
        conservan su mínimo reservado."""
        from gaming_news_digest.pipeline import _pre_rank_for_ai
        from gaming_news_digest.storage.retention import utc_now

        media = [make_fetched(f"patch {i} announced", "Persona", hours_ago=1) for i in range(76)]
        reddit = [
            make_fetched(self._noise_title(i), "Reddit Rumors", hours_ago=48, is_reddit=True)
            for i in range(5)
        ]
        out = _pre_rank_for_ai(media + reddit, set(), now=utc_now(), reddit_floor=8)
        reddit_out = [it for it in out if it.source.type.value == "reddit"]
        assert len(out) == 60
        assert len(reddit_out) == 5


def test_pipeline_pasa_ventana_diaria_a_retencion(monkeypatch):
    """La retención usa la ventana ~24 h (+2 de tolerancia) del digest diario."""
    import gaming_news_digest.pipeline as pipe
    from gaming_news_digest.config import GamesConfig, Limits, SourcesConfig
    from gaming_news_digest.pipeline import _DIGEST_WINDOW_HOURS

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._ai_cache = {}
    pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
    pipeline.sources = SourcesConfig()
    pipeline._games = GamesConfig(include=())
    pipeline._save_games_config = Mock()

    fetched = [make_item()]
    monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
    monkeypatch.setattr(pipeline, "_filter", lambda items, **kw: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    def fake_enrich(items):
        for it in items:
            yield make_news_item(it.title, it.game)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    window_kwargs = {}

    def fake_retention(items, **kw):
        window_kwargs.update(kw)
        return items

    monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", fake_retention)

    pipeline.run(now=NOW)

    assert window_kwargs["max_age_hours"] == _DIGEST_WINDOW_HOURS


class TestGameNamePassthrough:
    """El nombre del juego (configurado o detectado) NO se cambia por la IA."""

    def test_game_intact_through_ai_enrich(self, monkeypatch):
        import re

        import gaming_news_digest.pipeline as pipe
        from gaming_news_digest.config import (
            GamesConfig,
            Limits,
            QualityConfig,
            SourcesConfig,
        )
        from gaming_news_digest.filtering.matcher import create_matcher

        pipeline = Pipeline.__new__(Pipeline)
        pipeline._ai_cache = {}
        pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
        pipeline.sources = SourcesConfig()
        pipeline._games = GamesConfig(include=())
        pipeline._save_games_config = Mock()
        # Atributos que __init__ inicializa y _filter/_is_excluded usan
        pipeline.quality = QualityConfig()
        pipeline.matcher = create_matcher((), ())
        pipeline._title_re = [re.compile(p, re.IGNORECASE) for p in pipeline.quality.exclude_title_patterns]
        pipeline._url_re = [re.compile(p, re.IGNORECASE) for p in pipeline.quality.exclude_url_patterns]

        # Artículo con juego detectado (no configurado)
        fetched = [make_item("Persona 5 Royal new trailer released", game="Persona 5 Royal")]
        monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
        monkeypatch.setattr(pipeline, "_filter", lambda items, **kw: items)
        monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

        seen_games = []

        def fake_enrich(items):
            for it in items:
                seen_games.append(it.game)
                # IA devuelve summary pero NO debe tocar game
                yield make_news_item(it.title, it.game)

        monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

        saved = []
        monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
        monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

        pipeline.run(now=NOW)

        # El juego original llega intacto a la IA
        assert seen_games == ["Persona 5 Royal"]
        # El juego original se guarda intacto
        assert saved[0][0].game == "Persona 5 Royal"


class TestGameMatchLogging:
    """Verifica logging GAME MATCH y contadores DIAGNÓSTICO JUEGOS."""

    def test_game_match_logs_per_item(self, monkeypatch, caplog):
        import logging
        import re

        import gaming_news_digest.pipeline as pipe
        from gaming_news_digest.config import (
            GamesConfig,
            Limits,
            QualityConfig,
            SourcesConfig,
        )
        from gaming_news_digest.filtering.matcher import create_matcher

        pipeline = Pipeline.__new__(Pipeline)
        pipeline._ai_cache = {}
        pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
        pipeline.sources = SourcesConfig()
        pipeline._games = GamesConfig(include=())
        pipeline._save_games_config = Mock()
        pipeline.quality = QualityConfig()
        pipeline.matcher = create_matcher((), ())
        pipeline._title_re = [re.compile(p, re.IGNORECASE) for p in pipeline.quality.exclude_title_patterns]
        pipeline._url_re = [re.compile(p, re.IGNORECASE) for p in pipeline.quality.exclude_url_patterns]

        # 1 configurado (match en games.yaml), 1 detectado por anchor, 1 None -> Videojuegos
        fetched = [
            make_item("Persona 6 announced", game="Persona"),  # se configura en games.yaml del test? no -> lo matchea el matcher
            make_item("Hollow Knight Silksong Patch 1.1 notes", game="Videojuegos"),  # detectado por anchor
            make_item("Nintendo announces new hardware strategy", game="Videojuegos"),  # juegos pero sin juego concreto -> Videojuegos
        ]
        monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
        monkeypatch.setattr(pipeline, "_filter", pipeline._filter)  # usar filtro real
        monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

        def fake_enrich(items):
            for it in items:
                yield make_news_item(it.title, it.game)

        monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

        saved = []
        monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
        monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

        with caplog.at_level(logging.INFO):
            pipeline.run(now=NOW)

        # Verifica líneas GAME MATCH por ítem
        game_match_lines = [r.message for r in caplog.records if r.message.startswith("GAME MATCH:")]
        assert len(game_match_lines) == 3
        any_none = any("-> None [no_confident_match]" in line for line in game_match_lines)
        assert any_none, "Debería haber al menos un '-> None [no_confident_match]'"

    def test_diagnostico_juegos_counter_line(self, monkeypatch, caplog):
        import logging
        import re

        import gaming_news_digest.pipeline as pipe
        from gaming_news_digest.config import (
            GamesConfig,
            Limits,
            QualityConfig,
            SourcesConfig,
        )
        from gaming_news_digest.filtering.matcher import create_matcher

        pipeline = Pipeline.__new__(Pipeline)
        pipeline._ai_cache = {}
        pipeline.limits = Limits(max_items_per_source=20, max_stories_per_game=8)
        pipeline.sources = SourcesConfig()
        pipeline._games = GamesConfig(include=())
        pipeline._save_games_config = Mock()
        pipeline.quality = QualityConfig()
        pipeline.matcher = create_matcher((), ())
        pipeline._title_re = [re.compile(p, re.IGNORECASE) for p in pipeline.quality.exclude_title_patterns]
        pipeline._url_re = [re.compile(p, re.IGNORECASE) for p in pipeline.quality.exclude_url_patterns]

        fetched = [
            make_item("Persona 6 announced", game="Persona"),      # known_title -> Persona
            make_item("Hollow Knight Silksong Patch notes", game="Videojuegos"),  # anchor -> Hollow Knight Silksong
            make_item("Nintendo announces new hardware strategy", game="Videojuegos"),  # juegos, sin juego concreto -> Videojuegos
            make_item("Red Dead Redemption 2 trailer", game="Videojuegos"),  # known_title -> Red Dead
        ]
        monkeypatch.setattr(pipeline, "_fetch_all", lambda: fetched)
        monkeypatch.setattr(pipeline, "_filter", pipeline._filter)
        monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

        def fake_enrich(items):
            for it in items:
                yield make_news_item(it.title, it.game)

        monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

        saved = []
        monkeypatch.setattr(pipe, "save_digest", lambda items, **kw: saved.append(list(items)))
        monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

        with caplog.at_level(logging.INFO):
            pipeline.run(now=NOW)

        # Busca la línea DIAGNÓSTICO JUEGOS
        diag_lines = [r.message for r in caplog.records if r.message.startswith("DIAGNÓSTICO JUEGOS:")]
        assert len(diag_lines) == 1
        diag = diag_lines[0]
        # Debe contener los 4 campos
        assert "identificado=" in diag
        assert "sin_identificar(Videojuegos)=" in diag
        assert "reddit=" in diag
        assert "media/steam total=" in diag
        # Verifica números (ajusta según detección real)
        import re
        m = re.search(r"identificado=(\d+)", diag)
        assert m and int(m.group(1)) >= 2
        m = re.search(r"sin_identificar\(Videojuegos\)=(\d+)", diag)
        assert m and int(m.group(1)) >= 1
