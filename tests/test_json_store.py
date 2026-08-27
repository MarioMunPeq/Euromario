"""Tests de save_digest: escritura atómica, merge, retención y simulación de crash."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gaming_news_digest.models import NewsItem, Source
from gaming_news_digest.storage.json_store import (
    load_existing_digest,
    merge_and_retain,
    save_digest,
)


def make_item(title: str, hours_ago: int, game: str = "Persona") -> NewsItem:
    return NewsItem(
        title=title,
        url=f"https://example.com/{title}",
        source=Source(name="IGN", type="media"),
        game=game,
        language="en",
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        fetched_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        relevance=3,
        category="actualizacion",
        summary="Resumen de prueba.",
    )


def make_source(**overrides) -> Source:
    values = {"name": "IGN", "type": "media"}
    values.update(overrides)
    return Source(**values)


class TestLoadExistingDigest:
    def test_archivo_inexistente_devuelve_lista_vacia(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        import gaming_news_digest.storage.json_store as js
        original = js.DATA_PATH
        js.DATA_PATH = path
        try:
            assert load_existing_digest() == []
        finally:
            js.DATA_PATH = original

    def test_archivo_corrupto_devuelve_lista_vacia_y_log(self, tmp_path, caplog):
        path = tmp_path / "corrupt.json"
        path.write_text("no es json válido", encoding="utf-8")
        import gaming_news_digest.storage.json_store as js
        original = js.DATA_PATH
        js.DATA_PATH = path
        try:
            assert load_existing_digest() == []
            assert "corrupto" in caplog.text
        finally:
            js.DATA_PATH = original

    def test_carga_valida_reconstruye_items(self, tmp_path):
        items = [
            NewsItem(
                title="Test",
                url="https://example.com/test",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=datetime.now(timezone.utc) - timedelta(hours=1),
                fetched_at=datetime.now(timezone.utc) - timedelta(hours=1),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
        ]
        path = tmp_path / "news.json"
        data = {"generated_at": "2026-08-23T12:00:00Z", "total": 1, "news": [items[0].to_dict()]}
        path.write_text(json.dumps(data), encoding="utf-8")

        import gaming_news_digest.storage.json_store as js
        original = js.DATA_PATH
        js.DATA_PATH = path
        try:
            loaded = load_existing_digest()
            assert len(loaded) == 1
            assert loaded[0].title == "Test"
            assert loaded[0].id
        finally:
            js.DATA_PATH = original


class TestMergeAndRetain:
    def test_nuevo_gana_sobre_existente_mismo_id(self):
        existing = [
            NewsItem(
                title="Viejo",
                url="https://example.com/same",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=datetime.now(timezone.utc) - timedelta(hours=5),
                fetched_at=datetime.now(timezone.utc) - timedelta(hours=5),
                relevance=2,
                category="rumor",
                summary="Resumen de prueba.",
            )
        ]
        new = [
            NewsItem(
                title="Nuevo (mismo URL)",
                url="https://example.com/same",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=datetime.now(timezone.utc),
                fetched_at=datetime.now(timezone.utc),
                relevance=5,
                category="lanzamiento",
                summary="Resumen de prueba.",
            )
        ]
        merged = merge_and_retain(existing, new)
        assert len(merged) == 1
        assert merged[0].title == "Nuevo (mismo URL)"
        assert merged[0].relevance == 5

    def test_ordena_descendente_tras_merge(self):
        existing = [
            NewsItem(
                title="Viejo",
                url="https://example.com/old",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=datetime.now(timezone.utc) - timedelta(hours=10),
                fetched_at=datetime.now(timezone.utc) - timedelta(hours=10),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
        ]
        new = [
            NewsItem(
                title="Nuevo",
                url="https://example.com/new",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=datetime.now(timezone.utc),
                fetched_at=datetime.now(timezone.utc),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
        ]
        merged = merge_and_retain(existing, new)
        assert merged[0].title == "Nuevo"
        assert merged[1].title == "Viejo"

    def test_aplica_retencion_tras_merge(self):
        existing = [
            NewsItem(
                title=f"Old {i}",
                url=f"https://example.com/old{i}",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=datetime.now(timezone.utc) - timedelta(days=20 + i),
                fetched_at=datetime.now(timezone.utc) - timedelta(days=20 + i),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            for i in range(5)
        ]
        new = [
            NewsItem(
                title=f"New {i}",
                url=f"https://example.com/new{i}",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=datetime.now(timezone.utc) - timedelta(hours=i),
                fetched_at=datetime.now(timezone.utc) - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            for i in range(3)
        ]
        merged = merge_and_retain(existing, new)
        assert len(merged) == 3
        assert all("New" in it.title for it in merged)


class TestSaveDigest:
    def test_escritura_atomica_crea_archivo(self, tmp_path):
        import gaming_news_digest.storage.json_store as js
        original = js.DATA_PATH
        js.DATA_PATH = tmp_path / "news.json"
        try:
            save_digest([make_item("Test", 1)])
            assert js.DATA_PATH.exists()
            data = json.loads(js.DATA_PATH.read_text(encoding="utf-8"))
            assert data["total"] == 1
            assert data["news"][0]["title"] == "Test"
        finally:
            js.DATA_PATH = original

    def test_escritura_atomica_no_corrompe_si_crash_en_medio(self, tmp_path):
        """Simula crash a mitad de escritura: archivo original intacto."""
        import gaming_news_digest.storage.json_store as js
        path = tmp_path / "news.json"
        js.DATA_PATH = path

        # Escribir archivo inicial válido
        initial = {"generated_at": "2026-01-01T00:00:00Z", "total": 1, "news": [{"id": "1"}]}
        js.DATA_PATH.write_text(json.dumps(initial), encoding="utf-8")

        # Simular crash: monkeypatch os.replace para que falle a mitad
        original_replace = os.replace
        def failing_replace(src, dst):
            raise OSError("Simulated crash")
        os.replace = failing_replace
        try:
            with pytest.raises(OSError):
                save_digest([make_item("New", 1)])
            # Archivo original debe seguir intacto
            content = json.loads(Path(js.DATA_PATH).read_text(encoding="utf-8"))
            assert content["total"] == 1  # original intacto
        finally:
            os.replace = original_replace

    def test_merge_con_historico_existente(self, tmp_path):
        import gaming_news_digest.storage.json_store as js
        original = js.DATA_PATH
        path = tmp_path / "news.json"
        js.DATA_PATH = path
        try:
            # Histórico existente
            old = NewsItem(
                title="Old",
                url="https://example.com/old",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=datetime.now(timezone.utc) - timedelta(hours=5),
                fetched_at=datetime.now(timezone.utc) - timedelta(hours=5),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            path.write_text(json.dumps({
                "generated_at": "2026-01-01T00:00:00Z",
                "total": 1,
                "news": [old.to_dict()]
            }), encoding="utf-8")

            save_digest([make_item("New", 1)])
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["total"] == 2
            titles = {n["title"] for n in data["news"]}
            assert "Old" in titles and "New" in titles
        finally:
            js.DATA_PATH = original