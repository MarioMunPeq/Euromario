"""Tests del lector de RSS de subreddits (fixtures locales, sin red real)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import FakeResponse

from gaming_news_digest.config import Limits, Subreddit
from gaming_news_digest.fetchers.base import FetchError
from gaming_news_digest.fetchers.reddit import fetch_subreddit
from gaming_news_digest.models import SourceType

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
SUBREDDIT = Subreddit(name="gamingleaks")
LIMITS = Limits(max_items_per_source=10, timeout_seconds=5)


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def items(fake_session):
    fake_session.route(
        "gamingleaks", FakeResponse(load_fixture("reddit_sample.rss"))
    )
    return fetch_subreddit(SUBREDDIT, LIMITS, session=fake_session, now=NOW)


class TestParseoDelAtom:
    def test_descarta_entradas_sin_link(self, items):
        assert [i.title for i in items] == [
            "[Rumor] Supuesto leak de Persona 6",
            "Hilo: ¿qué anuncios esperáis de la Gamescom?",
        ]

    def test_fuente_reddit_con_subreddit(self, items):
        source = items[0].source

        assert source.type is SourceType.REDDIT
        assert source.name == "Reddit · r/gamingleaks"
        assert source.subreddit == "gamingleaks"

    def test_idioma_queda_pendiente_para_la_ia(self, items):
        assert all(i.language is None for i in items)

    def test_limpia_el_html_del_contenido(self, items):
        assert items[0].body_text == "Supuesto leak de Persona 6"

    def test_contenido_plano_se_mantiene(self, items):
        assert items[1].body_text == "Texto sin tags"

    def test_updated_como_fallback_de_fecha(self, items):
        assert items[1].published_at == datetime(
            2026, 8, 23, 9, 0, tzinfo=timezone.utc
        )


class TestExtraccionDeImagen:
    def test_media_thumbnail_extrae_imagen(self, items):
        assert items[0].image_url == "https://preview.redd.it/persona6_leak.jpg"

    def test_sin_media_thumbnail_devuelve_none(self, items):
        assert items[1].image_url is None


class TestExtraccionDeUrl:
    def test_url_extraida_es_link_del_post_no_del_feed(self, items):
        """La URL debe ser el link individual del post (con /comments/<id>/...), no la URL genérica del feed."""
        assert items[0].url == "https://www.reddit.com/r/gamingleaks/comments/abc123/supuesto_leak/"
        assert items[1].url == "https://www.reddit.com/r/gamingleaks/comments/def456/hilo_gamescom/"
        # Verificar que NO es la URL del feed
        assert not items[0].url.endswith("/.rss")
        assert not items[0].url.endswith("/new/")
        # Verificar que contiene el ID del post (mismo que en <id> t3_abc123 -> abc123)
        assert "abc123" in items[0].url
        assert "def456" in items[1].url

    def test_descarta_entradas_sin_link_valido(self, items):
        """La entrada sin link (solo id t3_ghi789) debe ser descartada."""
        assert len(items) == 2  # solo 2 entradas tienen link válido


class TestPeticionHttp:
    def test_url_correcta(self, fake_session, items):
        esperada = "https://www.reddit.com/r/gamingleaks/new/.rss"

        assert fake_session.calls[0]["url"] == esperada

    def test_user_agent_identificativo(self, fake_session):
        assert fake_session.headers["User-Agent"].startswith("gpatch-notes")

    def test_trunca_al_limite_por_fuente(self, fake_session):
        fake_session.route(
            "gamingleaks", FakeResponse(load_fixture("reddit_sample.rss"))
        )
        limits = Limits(max_items_per_source=1, timeout_seconds=5)

        result = fetch_subreddit(SUBREDDIT, limits, session=fake_session, now=NOW)

        assert len(result) == 1

    def test_http_403_lanza_error_con_subreddit(self, fake_session):
        fake_session.route("gamingleaks", FakeResponse(status_code=403))

        with pytest.raises(FetchError, match="r/gamingleaks"):
            fetch_subreddit(SUBREDDIT, LIMITS, session=fake_session, now=NOW)

    def test_feed_200_sin_entradas_lanza_error(self, fake_session):
        # Réplica exacta del feed vacío que Reddit sirve para subreddits
        # privados/restringidos (observado con r/gamingleaks en 2026-08).
        vacio = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<feed xmlns="http://www.w3.org/2005/Atom">'
            b'<category term="GamingLeaks" label="r/GamingLeaks"/>'
            b"<title>newest submissions : GamingLeaks</title>"
            b"</feed>"
        )
        fake_session.route("gamingleaks", FakeResponse(vacio))

        with pytest.raises(FetchError, match="sin entradas"):
            fetch_subreddit(SUBREDDIT, LIMITS, session=fake_session, now=NOW)