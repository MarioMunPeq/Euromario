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
        "fetched_at": datetime(2026, 8, 20, 12, 5, tzinfo=timezone.utc),
        "relevance": 4,
        "category": "lanzamiento",
        "summary": "Resumen breve de prueba.",
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
    def test_texto_no_vacio_es_valido(self):
        assert make_item(summary="Un resumen.").summary == "Un resumen."

    def test_none_sin_fallback_es_invalido(self):
        with pytest.raises(ModelValidationError, match="fallback"):
            make_item(summary=None)

    def test_none_con_fallback_explicito_es_valido(self):
        item = make_item(summary=None, summary_is_fallback=True)
        assert item.summary is None
        assert item.summary_is_fallback is True

    def test_texto_con_flag_de_fallback_es_invalido(self):
        with pytest.raises(ModelValidationError, match="exige summary=None"):
            make_item(summary="x", summary_is_fallback=True)

    def test_flag_de_tipo_invalido_rechazado(self):
        with pytest.raises(ModelValidationError, match="booleano"):
            make_item(summary="x", summary_is_fallback="si")

    def test_cadena_vacia_rechazada(self):
        with pytest.raises(ModelValidationError, match="texto no vacío"):
            make_item(summary="")

    def test_solo_espacios_rechazado(self):
        with pytest.raises(ModelValidationError, match="texto no vacío"):
            make_item(summary="   ")

    def test_se_recorta(self):
        assert make_item(summary=" hola ").summary == "hola"


class TestFetchedAt:
    def test_none_rechazado(self):
        with pytest.raises(ModelValidationError, match="datetime"):
            make_item(fetched_at=None)

    def test_fecha_naive_rechazada(self):
        naive = datetime(2026, 8, 20, 12, 5)  # noqa: DTZ001 (naive es lo que se prueba)
        with pytest.raises(ModelValidationError, match="naive"):
            make_item(fetched_at=naive)

    def test_otra_zona_utc_se_normaliza(self):
        offset = timezone(timedelta(hours=-3))
        item = make_item(fetched_at=datetime(2026, 8, 20, 9, 5, tzinfo=offset))
        assert item.to_dict()["fetched_at"] == "2026-08-20T12:05:00Z"


class TestNuevosOpcionales:
    def test_author_none_y_texto(self):
        assert make_item(author=None).author is None
        assert make_item(author="  Editor  ").author == "Editor"

    def test_author_vacio_rechazado(self):
        with pytest.raises(ModelValidationError, match="autor"):
            make_item(author=" ")

    def test_is_verified_booleano(self):
        assert make_item(is_verified=False).is_verified is False
        assert make_item(is_verified=True).is_verified is True

    def test_is_verified_no_booleano_rechazado(self):
        with pytest.raises(ModelValidationError, match="booleano"):
            make_item(is_verified="true")

    def test_game_id_none_y_texto(self):
        assert make_item(game_id=None).game_id is None
        assert make_item(game_id="gta5").game_id == "gta5"

    def test_game_id_vacio_rechazado(self):
        with pytest.raises(ModelValidationError, match="game_id"):
            make_item(game_id="")


class TestImageUrl:
    def test_none_es_valido(self):
        assert make_item(image_url=None).image_url is None

    def test_url_valida_se_guarda(self):
        item = make_item(image_url="https://cdn.example.com/img.jpg")
        assert item.image_url == "https://cdn.example.com/img.jpg"

    def test_url_http_valida(self):
        item = make_item(image_url="http://cdn.example.com/img.jpg")
        assert item.image_url == "http://cdn.example.com/img.jpg"

    def test_url_invalida_se_descarta(self):
        assert make_item(image_url="ftp://example.com/img.jpg").image_url is None

    def test_url_relativa_se_descarta(self):
        assert make_item(image_url="/images/img.jpg").image_url is None

    def test_url_se_recorta(self):
        item = make_item(image_url="  https://cdn.example.com/img.jpg  ")
        assert item.image_url == "https://cdn.example.com/img.jpg"

    def test_cadena_vacia_se_descarta(self):
        assert make_item(image_url="").image_url is None

    def test_serializa_null(self):
        assert make_item(image_url=None).to_dict()["image_url"] is None

    def test_serializa_url(self):
        url = "https://cdn.example.com/img.jpg"
        assert make_item(image_url=url).to_dict()["image_url"] == url


class TestToDict:
    def test_claves_exactas_del_contrato(self):
        item = make_item(
            summary="Resumen breve.",
            image_url="https://cdn.example.com/img.jpg",
            author="R. Editor",
            is_verified=True,
        )
        data = item.to_dict()
        assert set(data) == {
            "id",
            "title",
            "summary",
            "url",
            "source",
            "game",
            "game_id",
            "language",
            "published_at",
            "fetched_at",
            "relevance",
            "category",
            "image_url",
            "author",
            "is_verified",
        }

    def test_valores_serializados(self):
        source = make_source(name="GaminLeaks", type="reddit", subreddit="gaming")
        item = make_item(
            source=source,
            summary="Rumor sin verificar.",
            fetched_at=datetime(2026, 8, 20, 12, 10, tzinfo=timezone.utc),
        )
        data = item.to_dict()
        assert data["source"]["subreddit"] == "gaming"
        assert data["source"]["type"] == "reddit"
        assert data["category"] == "lanzamiento"
        assert data["published_at"] == "2026-08-20T12:00:00Z"
        assert data["fetched_at"] == "2026-08-20T12:10:00Z"
        assert data["summary"] == "Rumor sin verificar."
        assert data["is_verified"] is False
        assert data["author"] is None
        assert data["game_id"] is None

    def test_summary_nulo_con_fallback_se_serializa_como_null(self):
        item = make_item(summary=None, summary_is_fallback=True)
        assert item.to_dict()["summary"] is None
        assert "summary_is_fallback" not in item.to_dict()


class TestFromDict:
    def test_desde_dict_valido_reconstruye_correctamente(self):
        item = make_item(summary="Test summary", image_url="https://cdn.example.com/img.jpg")
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
        assert restored.image_url == item.image_url
        assert restored.id == item.id

    def test_id_recalculado_coincide_con_guardado(self):
        item = make_item()
        data = item.to_dict()
        restored = NewsItem.from_dict(data)
        assert restored.id == item.id

    def test_image_url_ausente_en_dict_compatibilidad(self):
        item = make_item()
        data = item.to_dict()
        del data["image_url"]
        restored = NewsItem.from_dict(data)
        assert restored.image_url is None

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
