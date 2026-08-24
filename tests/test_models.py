"""Tests de los modelos de dominio (``Source`` y ``NewsItem``)."""

from datetime import datetime, timedelta, timezone

import pytest

from gaming_news_digest.models import (
    Category,
    Language,
    ModelValidationError,
    NewsItem,
    Source,
    SourceType,
)


def make_source(**overrides) -> Source:
    values = {"name": "IGN", "type": "media"}
    values.update(overrides)
    return Source(**values)


def make_item(**overrides) -> NewsItem:
    values = {
        "title": "Persona 6 muestra primer tráiler",
        "url": "https://www.eurogamer.net/persona-6",
        "source": make_source(),
        "game": "Persona",
        "language": "en",
        "published_at": datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        "relevance": 4,
        "category": "lanzamiento",
    }
    values.update(overrides)
    return NewsItem(**values)


class TestSource:
    def test_coacciona_el_tipo_desde_string(self):
        assert make_source(type="reddit", subreddit="gamingleaks").type is (
            SourceType.REDDIT
        )

    def test_acepta_instancias_de_enum(self):
        assert make_source(type=SourceType.MEDIA).type is SourceType.MEDIA

    def test_nombre_vacio_rechazado(self):
        with pytest.raises(ModelValidationError, match="nombre"):
            make_source(name="   ")

    def test_tipo_invalido_rechazado(self):
        with pytest.raises(ModelValidationError, match="tipo de fuente"):
            make_source(type="foro")

    @pytest.mark.parametrize("subreddit", [None, "   "])
    def test_reddit_exige_subreddit(self, subreddit):
        with pytest.raises(ModelValidationError, match="subreddit"):
            make_source(type="reddit", subreddit=subreddit)

    @pytest.mark.parametrize("kind", ["media", "steam"])
    def test_media_y_steam_prohiben_subreddit(self, kind):
        with pytest.raises(ModelValidationError, match="no admite subreddit"):
            make_source(type=kind, subreddit="gamingleaks")

    def test_to_dict_del_contrato(self):
        data = make_source(type="steam").to_dict()
        assert set(data) == {"name", "type", "subreddit"}
        assert data == {"name": "IGN", "type": "steam", "subreddit": None}


class TestIdDeterminista:
    def test_misma_url_mismo_id(self):
        assert make_item().id == make_item().id

    def test_distinta_url_distinto_id(self):
        other = make_item(url="https://www.eurogamer.net/otra-noticia")
        assert make_item().id != other.id

    def test_formato_hex_16(self):
        assert len(make_item().id) == 16
        int(make_item().id, 16)

    def test_urls_equivalentes_mismo_id(self):
        base = make_item(url="https://www.eurogamer.net/persona-6").id
        variants = [
            "https://WWW.EuroGamer.NET/persona-6/",
            "https://www.eurogamer.net/persona-6#comentarios",
            "  https://www.eurogamer.net/persona-6  ",
        ]
        for variant in variants:
            assert make_item(url=variant).id == base


class TestValidacionCampos:
    def test_titulo_vacio_rechazado(self):
        with pytest.raises(ModelValidationError, match="título"):
            make_item(title="   ")

    @pytest.mark.parametrize("url", ["ftp://x.com/a", "eurogamer.net/a"])
    def test_url_sin_http_rechazada(self, url):
        with pytest.raises(ModelValidationError, match="http"):
            make_item(url=url)

    def test_juego_vacio_rechazado(self):
        with pytest.raises(ModelValidationError, match="juego"):
            make_item(game="")

    def test_categoria_invalida_rechazada(self):
        with pytest.raises(ModelValidationError, match="categoría"):
            make_item(category="estreno")

    def test_idioma_invalido_rechazado(self):
        with pytest.raises(ModelValidationError, match="idioma"):
            make_item(language="fr")

    def test_acepta_enums_y_strings(self):
        item = make_item(category=Category.RUMOR, language=Language.SPANISH)
        assert item.category.value == "rumor"
        assert item.language.value == "es"

    @pytest.mark.parametrize("score", [0, 6])
    def test_relevancia_fuera_de_rango(self, score):
        with pytest.raises(ModelValidationError, match="entre 1 y 5"):
            make_item(relevance=score)

    @pytest.mark.parametrize("score", ["3", True, 3.5])
    def test_relevancia_de_tipo_invalido(self, score):
        with pytest.raises(ModelValidationError, match="entero entre 1 y 5"):
            make_item(relevance=score)

    @pytest.mark.parametrize("score", [1, 5])
    def test_relevancia_en_los_limites_es_valida(self, score):
        assert make_item(relevance=score).relevance == score

    def test_fecha_naive_rechazada(self):
        naive = datetime(2026, 8, 20, 12, 0)  # noqa: DTZ001 (naive es lo que se prueba)
        with pytest.raises(ModelValidationError, match="naive"):
            make_item(published_at=naive)

    def test_no_datetime_rechazado(self):
        with pytest.raises(ModelValidationError, match="datetime"):
            make_item(published_at="2026-08-20T12:00:00Z")

    def test_otra_zona_horaria_se_normaliza_a_utc(self):
        offset = timezone(timedelta(hours=-3))
        item = make_item(
            published_at=datetime(2026, 8, 20, 9, 0, tzinfo=offset)
        )
        assert item.published_at.utcoffset() == timedelta(0)
        assert item.to_dict()["published_at"] == "2026-08-20T12:00:00Z"


class TestSummary:
    def test_none_es_valido(self):
        assert make_item(summary=None).summary is None

    def test_cadena_vacia_rechazada(self):
        with pytest.raises(ModelValidationError, match="None"):
            make_item(summary="")

    def test_solo_espacios_rechazado(self):
        with pytest.raises(ModelValidationError, match="None"):
            make_item(summary="   ")

    def test_se_recorta(self):
        assert make_item(summary=" hola ").summary == "hola"


class TestToDict:
    def test_claves_exactas_del_contrato(self):
        item = make_item(summary="Resumen breve.")
        data = item.to_dict()
        assert set(data) == {
            "id",
            "title",
            "summary",
            "url",
            "source",
            "game",
            "language",
            "published_at",
            "relevance",
            "category",
        }

    def test_valores_serializados(self):
        source = make_source(name="GaminLeaks", type="reddit", subreddit="gaming")
        item = make_item(source=source, summary="Rumor sin verificar.")
        data = item.to_dict()
        assert data["source"]["subreddit"] == "gaming"
        assert data["source"]["type"] == "reddit"
        assert data["category"] == "lanzamiento"
        assert data["published_at"] == "2026-08-20T12:00:00Z"
        assert data["summary"] == "Rumor sin verificar."

    def test_summary_nulo_se_serializa_como_null(self):
        assert make_item(summary=None).to_dict()["summary"] is None


class TestFromDict:
    def test_desde_dict_valido_reconstruye_correctamente(self):
        item = make_item(summary="Test summary")
        data = item.to_dict()
        restored = NewsItem.from_dict(data)

        assert restored.title == item.title
        assert restored.url == item.url
        assert restored.source.name == item.source.name
        assert restored.source.type == item.source.type
        assert restored.game == item.game
        assert restored.language == item.language
        assert restored.published_at == item.published_at
        assert restored.relevance == item.relevance
        assert restored.category == item.category
        assert restored.summary == item.summary
        assert restored.id == item.id

    def test_id_recalculado_coincide_con_guardado(self):
        item = make_item()
        data = item.to_dict()
        restored = NewsItem.from_dict(data)
        assert restored.id == item.id

    def test_source_from_dict_reconstruye(self):
        src = Source(name="IGN", type="media")
        data = src.to_dict()
        restored = Source.from_dict(data)
        assert restored.name == src.name
        assert restored.type == src.type
        assert restored.subreddit is None

    def test_source_reddit_from_dict_con_subreddit(self):
        src = Source(name="Reddit", type="reddit", subreddit="gamingleaks")
        data = src.to_dict()
        restored = Source.from_dict(data)
        assert restored.subreddit == "gamingleaks"
