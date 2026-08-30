"""Tests de save_digest: escritura atómica, merge, retención y simulación de crash."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gaming_news_digest.models import NewsItem, Source, normalize_url
from gaming_news_digest.storage.json_store import (
    _migrate_legacy_item,
    _repair_cp850_mojibake,
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


class TestMigracionMojibake:
    def test_mojibake_cp850_reparado_en_title_y_summary(self):
        # Construir el mojibake real: bytes UTF-8 de acentos decodificados CP850
        mojibake_title = "Pokémon se lanza".encode().decode("cp850")
        mojibake_summary = "se lanzará con una única versión".encode().decode("cp850")
        assert "Pokémon" not in mojibake_title  # sanity: era corrupta

        raw = {
            "id": "abc",
            "title": mojibake_title,
            "summary": mojibake_summary,
            "url": "https://example.com/x",
            "source": "IGN",
            "source_type": "media",
            "game": "Pokemon",
            "language": "es",
            "published_at": "2026-08-25T10:00:00Z",
            "fetched_at": "2026-08-25T10:05:00Z",
            "relevance": 3,
            "category": "actualizacion",
        }
        migrated = _migrate_legacy_item(raw)

        assert migrated["title"] == "Pokémon se lanza"
        assert migrated["summary"] == "se lanzará con una única versión"

    def test_reparacion_no_toca_texto_limpio(self):
        assert _repair_cp850_mojibake("Texto sin mojibake") == "Texto sin mojibake"
        assert _repair_cp850_mojibake("INGRESAR") == "INGRESAR"

    def test_reparacion_intacta_si_falla_roundtrip(self):
        # "├" (U+251C) codifica a 0xC3, un byte UTF-8 truncado: el decode
        # falla y la migración devuelve el original (no inventa nada).
        assert _repair_cp850_mojibake("├") == "├"

    def test_migracion_tambien_repara_source_plano(self):
        mojibake_source = "Thómas".encode().decode("cp850")
        raw = {
            "id": "abc",
            "title": "Titulo",
            "summary": "Resumen",
            "url": "https://example.com/x",
            "source": mojibake_source,
            "source_type": "media",
            "game": "Persona",
            "language": "es",
            "published_at": "2026-08-25T10:00:00Z",
            "fetched_at": "2026-08-25T10:05:00Z",
            "relevance": 3,
            "category": "actualizacion",
        }
        migrated = _migrate_legacy_item(raw)
        assert migrated["source"] == "Thómas"

    def test_reddit_plano_sin_subreddit_recupera_subreddit_del_nombre(self):
        # Las fuentes reddit planas antiguas nunca serializaron source_subreddit;
        # la migración debe volver a derivarlo para que Source no se descarte.
        raw = {
            "id": "abc",
            "title": "Titulo",
            "summary": "Resumen",
            "url": "https://example.com/x",
            "source": "Reddit · r/gamingleaksandrumours",
            "source_type": "reddit",
            "game": "Persona",
            "language": "en",
            "published_at": "2026-08-25T10:00:00Z",
            "fetched_at": "2026-08-25T10:05:00Z",
            "relevance": 3,
            "category": "lanzamiento",
        }

        migrated = _migrate_legacy_item(raw)

        assert migrated["source_subreddit"] == "gamingleaksandrumours"

    def test_reddit_anidado_sin_subreddit_recupera_subreddit_y_no_se_descarta(self):
        # Histórico con source ANIDADO {name, type: reddit} sin el campo
        # subreddit: la migración también debe derivarlo; sin ello la fuente
        # viola el contrato y el item se descartaría en el load.
        url = "https://example.com/x"
        raw = {
            "id": hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16],
            "title": "Titulo",
            "summary": "Resumen",
            "url": url,
            "source": {"name": "Reddit · r/gamingleaksandrumours", "type": "reddit"},
            "game": "Persona",
            "language": "en",
            "published_at": "2026-08-25T10:00:00Z",
            "fetched_at": "2026-08-25T10:05:00Z",
            "relevance": 3,
            "category": "lanzamiento",
        }

        migrated = _migrate_legacy_item(raw)
        loaded = NewsItem.from_dict(migrated)

        assert migrated["source_subreddit"] == "gamingleaksandrumours"
        assert loaded.source.subreddit == "gamingleaksandrumours"

    def test_reddit_anidado_con_subreddit_conserva_el_explicito(self):
        # Si el subreddit explícito existe en el source anidado, se conserva
        # (aunque difiera del derivable por el nombre).
        raw = {
            "id": "abc",
            "title": "Titulo",
            "summary": "Resumen",
            "url": "https://example.com/x",
            "source": {
                "name": "Reddit · r/gamingleaksandrumours",
                "type": "reddit",
                "subreddit": "gamingleaksandrumours",
            },
            "game": "Persona",
            "language": "en",
            "published_at": "2026-08-25T10:00:00Z",
            "fetched_at": "2026-08-25T10:05:00Z",
            "relevance": 3,
            "category": "lanzamiento",
        }

        migrated = _migrate_legacy_item(raw)

        assert migrated["source_subreddit"] == "gamingleaksandrumours"

    def test_roundtrip_reddit_conserva_subreddit_y_no_se_descarta(self):
        # El contrato debe serializar source_subreddit para reddit: sin él el
        # item se descartaría en el merge (Source de reddit exige subreddit).
        item = NewsItem(
            title="GTA VI leak",
            url="https://reddit.com/r/gamingleaksandrumours/comments/1",
            source=Source(
                name="Reddit · r/gamingleaksandrumours",
                type="reddit",
                subreddit="gamingleaksandrumours",
            ),
            game="Grand Theft Auto",
            language="en",
            published_at=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            relevance=3,
            category="rumor",
            summary="Leak reportado.",
        )

        data = item.to_dict()

        assert data["source_subreddit"] == "gamingleaksandrumours"
        loaded = NewsItem.from_dict(data)
        assert loaded.source.subreddit == "gamingleaksandrumours"
    def _pin_paths(self, tmp_path):
        """Aísla DATA_PATH y HISTORY_PATH del repo en un tmp_path."""
        import gaming_news_digest.storage.json_store as js
        (self._orig_data, self._orig_history) = (js.DATA_PATH, js.HISTORY_PATH)
        js.DATA_PATH = tmp_path / "news.json"
        js.HISTORY_PATH = tmp_path / "history.json"
        return js

    def _restore_paths(self):
        import gaming_news_digest.storage.json_store as js
        js.DATA_PATH, js.HISTORY_PATH = self._orig_data, self._orig_history

    def test_escritura_atomica_crea_archivo(self, tmp_path):
        js = self._pin_paths(tmp_path)
        try:
            save_digest([make_item("Test", 1)])
            assert js.DATA_PATH.exists()
            data = json.loads(js.DATA_PATH.read_text(encoding="utf-8"))
            assert data["total"] == 1
            assert data["news"][0]["title"] == "Test"
            # El histórico de caché también se escribe (separación PROBLEMA 7)
            assert js.HISTORY_PATH.exists()
        finally:
            self._restore_paths()

    def test_escritura_atomica_no_corrompe_si_crash_en_medio(self, tmp_path):
        """Simula crash a mitad de escritura: archivo original intacto."""
        js = self._pin_paths(tmp_path)
        try:
            js.DATA_PATH.write_text(
                json.dumps({"generated_at": "2026-01-01T00:00:00Z", "total": 1, "news": [{"id": "1"}]}),
                encoding="utf-8",
            )

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
        finally:
            self._restore_paths()

    def test_merge_con_historico_existente(self, tmp_path):
        js = self._pin_paths(tmp_path)
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
            js.DATA_PATH.write_text(json.dumps({
                "generated_at": "2026-01-01T00:00:00Z",
                "total": 1,
                "news": [old.to_dict()]
            }), encoding="utf-8")

            save_digest([make_item("New", 1)])
            data = json.loads(js.DATA_PATH.read_text(encoding="utf-8"))
            assert data["total"] == 2
            titles = {n["title"] for n in data["news"]}
            assert "Old" in titles and "New" in titles
        finally:
            self._restore_paths()


class TestProblema7SeparacionHistoricoPublicado:
    """PROBLEMA 7: la ventana de 24 h decide el PUBLICADO; el histórico de
    caché conserva lo antiguo para reutilizar resúmenes de IA."""

    def test_publica_solo_la_ventana_y_conserva_historico(self, tmp_path):
        import gaming_news_digest.storage.json_store as js
        js.DATA_PATH, js.HISTORY_PATH = tmp_path / "news.json", tmp_path / "history.json"
        old = make_item("Vieja de hace 30h", 30)
        new = make_item("Nueva de hace 3h", 3)
        save_digest([old])
        save_digest([new])

        # PUBLICADO: solo la ventana (la de 30 h queda fuera del digest).
        data = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))
        assert data["total"] == 1
        assert [n["title"] for n in data["news"]] == ["Nueva de hace 3h"]

        # HISTÓRICO: conserva ambas (ventana larga = caché de IA).
        history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
        titles = {n["title"] for n in history["news"]}
        assert titles == {"Vieja de hace 30h", "Nueva de hace 3h"}

    def test_ventana_borde_exacto(self, tmp_path):
        """maximos en el borde: 23h59m pasa, 24h01m no."""
        import gaming_news_digest.storage.json_store as js
        js.DATA_PATH, js.HISTORY_PATH = tmp_path / "news.json", tmp_path / "history.json"
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        dentro = NewsItem(
            title="Dentro de ventana", url="https://example.com/dentro",
            source=Source(name="IGN", type="media"), game="Persona", language="en",
            published_at=now - timedelta(hours=23, minutes=59),
            fetched_at=now - timedelta(hours=23, minutes=59),
            relevance=3, category="actualizacion", summary="Resumen de prueba.",
        )
        fuera = NewsItem(
            title="Fuera de ventana", url="https://example.com/fuera",
            source=Source(name="IGN", type="media"), game="Persona", language="en",
            published_at=now - timedelta(hours=24, minutes=1),
            fetched_at=now - timedelta(hours=24, minutes=1),
            relevance=3, category="actualizacion", summary="Resumen de prueba.",
        )
        save_digest([dentro, fuera])
        data = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))
        assert data["total"] == 1
        assert data["news"][0]["title"] == "Dentro de ventana"

    def test_noticia_vieja_no_reaparece_al_reposicionarse(self, tmp_path):
        """Una noticia de hace 2 días que siga en el histórico NO vuelve al
        digest publicado aunque se guarde de nuevo el histórico completo."""
        import gaming_news_digest.storage.json_store as js
        js.DATA_PATH, js.HISTORY_PATH = tmp_path / "news.json", tmp_path / "history.json"
        vieja = make_item("Vieja", 48)
        save_digest([vieja])           # entra en histórico, no publicada
        save_digest([vieja])           # segunda ejecución del pipeline
        data = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))
        assert data["total"] == 0
        history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
        assert {n["title"] for n in history["news"]} == {"Vieja"}