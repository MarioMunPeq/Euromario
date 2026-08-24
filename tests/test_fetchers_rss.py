"""Tests del fetcher de medios RSS (fixtures locales, sin red real)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from conftest import FakeResponse

from gaming_news_digest.config import Limits, MediaFeed
from gaming_news_digest.fetchers.base import FetchError
from gaming_news_digest.fetchers.rss import fetch_media_feed
from gaming_news_digest.models import Language, SourceType

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)

FEED = MediaFeed(
    name="IGN", feed_url="https://www.ign.com/rss", language=Language.ENGLISH
)
LIMITS = Limits(max_items_per_source=10, timeout_seconds=5)


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestParseoDelFeed:
    @pytest.fixture
    def items(self, fake_session):
        fake_session.route("ign.com", FakeResponse(load_fixture("rss_sample.xml")))
        return fetch_media_feed(FEED, LIMITS, session=fake_session, now=NOW)

    def test_descarta_items_sin_link_y_conserva_el_resto(self, items):
        assert [i.title for i in items] == [
            "Persona 6 muestra su primer tráiler",
            "Parche de Cyberpunk 2077",
            "Anuncio en la Gamescom",
        ]

    def test_fuente_de_tipo_medio_con_idioma_del_feed(self, items):
        assert {i.source.type for i in items} == {SourceType.MEDIA}
        assert {i.source.name for i in items} == {"IGN"}
        assert all(i.language is Language.ENGLISH for i in items)

    def test_limpia_el_html_de_las_descripciones(self, items):
        assert items[0].body_text == "Atlus confirma novedades para 2027."

    def test_descripcion_plana_se_mantiene(self, items):
        assert items[1].body_text == "CD Projekt detalla todos los cambios."

    def test_fechas_en_utc(self, items):
        assert items[0].published_at == datetime(
            2026, 8, 22, 9, 15, tzinfo=timezone.utc
        )


class TestPeticionHttp:
    def test_timeout_configurado(self, fake_session):
        fake_session.route("ign.com", FakeResponse(load_fixture("rss_sample.xml")))
        fetch_media_feed(FEED, LIMITS, session=fake_session, now=NOW)

        assert fake_session.calls[0]["timeout"] == LIMITS.timeout_seconds

    def test_user_agent_identificativo(self, fake_session):
        assert fake_session.headers["User-Agent"].startswith("gpatch-notes")

    def test_trunca_al_limite_por_fuente(self, fake_session):
        fake_session.route("ign.com", FakeResponse(load_fixture("rss_sample.xml")))
        limits = Limits(max_items_per_source=2, timeout_seconds=5)

        result = fetch_media_feed(FEED, limits, session=fake_session, now=NOW)

        assert len(result) == 2

    def test_http_500_lanza_error_con_nombre_de_fuente(self, fake_session):
        fake_session.route("ign.com", FakeResponse(status_code=500))

        with pytest.raises(FetchError, match="IGN"):
            fetch_media_feed(FEED, LIMITS, session=fake_session, now=NOW)

    def test_fallo_de_red_lanza_fetch_error(self, fake_session):
        fake_session.route("ign.com", requests.exceptions.ConnectTimeout())

        with pytest.raises(FetchError, match="IGN"):
            fetch_media_feed(FEED, LIMITS, session=fake_session, now=NOW)


class TestCadenaDeFechas:
    """published → updated → ahora, con clamp de futuro (CONTRIBUTING §5)."""

    @pytest.fixture
    def fechas_por_url(self, fake_session):
        feed = MediaFeed(
            name="Medio Test",
            feed_url="https://medio.test/rss",
            language=Language.SPANISH,
        )
        fake_session.route(
            "medio.test", FakeResponse(load_fixture("rss_dates_atom.xml"))
        )
        result = fetch_media_feed(feed, LIMITS, session=fake_session, now=NOW)
        return {i.url: i.published_at for i in result}

    def test_published_tiene_prioridad(self, fechas_por_url):
        assert fechas_por_url["https://medio.test/solo-published"] == datetime(
            2026, 8, 22, 8, 0, tzinfo=timezone.utc
        )

    def test_updated_como_fallback(self, fechas_por_url):
        assert fechas_por_url["https://medio.test/solo-updated"] == datetime(
            2026, 8, 21, 10, 0, tzinfo=timezone.utc
        )

    def test_fecha_muy_futura_se_recorta_a_ahora(self, fechas_por_url):
        assert fechas_por_url["https://medio.test/futuro"] == NOW

    def test_fecha_inservible_asume_ahora(self, fechas_por_url):
        assert fechas_por_url["https://medio.test/sin-fecha"] == NOW

    def test_sin_fecha_asume_ahora(self, fechas_por_url):
        assert fechas_por_url["https://medio.test/nada"] == NOW
