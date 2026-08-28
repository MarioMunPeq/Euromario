"""Tests del pipeline con lógica de fallback Ollama→Groq."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from gaming_news_digest.ai.base import AIError, AISummary, Category, Language
from gaming_news_digest.models import FetchedItem, NewsItem, Source
from gaming_news_digest.pipeline import Pipeline


def make_item(title="Noticia", body="Cuerpo", game="Persona", lang="en", url_suffix=""):
    return FetchedItem(
        title=title,
        url=f"https://test.com/{url_suffix or title}",
        source=Source(name="Test", type="media"),
        published_at=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 8, 23, 12, 5, tzinfo=timezone.utc),
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
        published_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
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
    published = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc) - timedelta(hours=hours_ago)
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
        published = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc) - timedelta(hours=hours_ago)
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
    monkeypatch.setattr(pipeline, "_filter", lambda items: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run()

    assert len(seen_enriched) == 8  # solo los supervivientes pasan por la IA
    assert len(saved) == 1
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
    monkeypatch.setattr(pipeline, "_filter", lambda items: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game, relevance=3)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run()

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
    monkeypatch.setattr(pipeline, "_filter", lambda items: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game, relevance=3)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run()

    # Solo 8 items de medios deben llegar a la IA (pre-límite aplicado)
    assert len(seen_enriched) == 8, f"Esperados 8 items en IA, got {len(seen_enriched)}"
    assert len(saved) == 1
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
    monkeypatch.setattr(pipeline, "_filter", lambda items: items)
    monkeypatch.setattr(pipe, "cluster_and_select_representatives", lambda items: items)

    seen_enriched = []

    def fake_enrich(items):
        seen_enriched.extend(items)
        for it in items:
            yield make_news_item(it.title, it.game, relevance=3)

    monkeypatch.setattr(pipeline, "_enrich_with_ai", fake_enrich)

    saved = []
    monkeypatch.setattr(pipe, "save_digest", lambda items: saved.append(list(items)))
    monkeypatch.setattr(pipe, "apply_retention", lambda items, **kw: items)

    pipeline.run()

    # 10 items llegan a la IA (pre-límite saltado)
    assert len(seen_enriched) == 10
    # Pero post-límite reduce a 5
    assert len(saved) == 1
    assert len(saved[0]) == 5