"""Tests del pipeline con lógica de fallback Ollama→Groq."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from gaming_news_digest.ai.base import AIError, AISummary, Category, Language
from gaming_news_digest.models import FetchedItem, Source
from gaming_news_digest.pipeline import Pipeline


def make_item(title="Noticia", body="Cuerpo", game="Persona", lang="en"):
    return FetchedItem(
        title=title,
        url="https://test.com",
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


def test_ollama_ok_groq_no_usado():
    ollama = Mock()
    ollama.summarize.side_effect = [
        make_ai_summary("ok1", 3, Category.UPDATE),
        make_ai_summary("ok2", 2, Category.RUMOR),
    ]
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.ollama = ollama
    pipeline.groq = Mock()
    pipeline.current_client = ollama
    pipeline._consecutive_ai_errors = 0

    items = [make_item(f"N{i}", f"c{i}") for i in range(2)]
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
    pipeline.ollama = Mock()
    pipeline.groq = groq
    pipeline.current_client = groq
    pipeline._consecutive_ai_errors = 0

    items = [make_item("ok1"), make_item("falla groq"), make_item("ok3")]
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
    pipeline.ollama = Mock()
    pipeline.groq = groq
    pipeline.current_client = groq
    pipeline._consecutive_ai_errors = 0

    items = [make_item("ok1"), make_item("fallará")]
    with pytest.raises(ConnectionError):
        list(pipeline._enrich_with_ai(items))