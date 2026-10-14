"""Tests del cliente de Steam News API (fixtures locales, sin red real)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from conftest import FakeResponse

from gaming_news_digest.config import Limits, SteamConfig, SteamGame
from gaming_news_digest.fetchers.base import FetchError
from gaming_news_digest.fetchers.steam import fetch_steam_news
from gaming_news_digest.models import SourceType

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
LIMITS = Limits(max_items_per_source=10, timeout_seconds=5)

STEAM = SteamConfig(
    enabled=True,
    games=(
        SteamGame(app_id=271590, nombre="Grand Theft Auto"),
        SteamGame(app_id=1687950, nombre="Persona"),
    ),
)

PERSONA_JSON = (
    b'{"appnews":{"appid":1687950,"newsitems":[{"gid":"9",'
    b'"title":"Rebaja de Persona 5 Royal",'
    b'"url":"https://store.steampowered.com/news/app/1687950/view/9",'
    b'"contents":"<i>Oferta</i> del 50%","date":1776000000}]}}'
)

PERSONA_JSON_CON_IMAGEN = (
    b'{"appnews":{"appid":1687950,"newsitems":[{"gid":"10",'
    b'"title":"Nuevo trailer de Persona 6",'
    b'"url":"https://store.steampowered.com/news/app/1687950/view/10",'
    b'"contents":"<p>Trailer increible</p><img src=\\"https://cdn.akamai.steamstatic.com/persona6_trailer.jpg\\" alt=\\"Trailer\\"/>",'
    b'"date":1776000001}]}}'
)


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def items(fake_session):
    fake_session.route("appid=271590", FakeResponse(load_fixture("steam_news.json")))
    fake_session.route("appid=1687950", FakeResponse(PERSONA_JSON))
    return fetch_steam_news(STEAM, LIMITS, session=fake_session, now=NOW)


class TestParseoDeLaRespuesta:
    def test_cada_app_mappea_a_su_juego(self, items):
        by_url = {i.url: i for i in items}

        gta = by_url["https://store.steampowered.com/news/app/271590/view/1"]
        assert gta.source.name == "Steam · Grand Theft Auto"
        assert gta.source.type is SourceType.STEAM
        assert gta.source.subreddit is None
        assert gta.language is None

        persona = by_url["https://store.steampowered.com/news/app/1687950/view/9"]
        assert persona.source.name == "Steam · Persona"

    def test_epoch_se_convierte_a_utc_exacto(self, items):
        by_url = {i.url: i for i in items}
        gta = by_url["https://store.steampowered.com/news/app/271590/view/1"]

        esperada = datetime.fromtimestamp(1777000000, tz=timezone.utc)
        assert gta.published_at == esperada

    def test_fecha_nula_asume_ahora(self, items):
        by_url = {i.url: i for i in items}
        evento = by_url["https://store.steampowered.com/news/app/271590/view/2"]

        assert evento.published_at == NOW

    def test_item_sin_titulo_descartado(self, items):
        urls_gta = [i.url for i in items if "/271590/" in i.url]

        assert urls_gta == [
            "https://store.steampowered.com/news/app/271590/view/1",
            "https://store.steampowered.com/news/app/271590/view/2",
        ]

    def test_contents_se_limpian_de_html(self, items):
        by_url = {i.url: i for i in items}
        gta = by_url["https://store.steampowered.com/news/app/271590/view/1"]

        assert gta.body_text == "Novedades del parche."


class TestExtraccionDeImagen:
    def test_contenido_con_img_extrae_imagen(self, fake_session):
        fake_session.route("appid=271590", FakeResponse(load_fixture("steam_news.json")))
        fake_session.route("appid=1687950", FakeResponse(PERSONA_JSON))
        items = fetch_steam_news(STEAM, LIMITS, session=fake_session, now=NOW)
        by_url = {i.url: i for i in items}
        gta = by_url["https://store.steampowered.com/news/app/271590/view/1"]
        assert gta.image_url == "https://cdn.akamai.steamstatic.com/gta5_cover.jpg"

    def test_contenido_sin_img_devuelve_none(self, fake_session):
        fake_session.route("appid=271590", FakeResponse(load_fixture("steam_news.json")))
        fake_session.route("appid=1687950", FakeResponse(PERSONA_JSON))
        items = fetch_steam_news(STEAM, LIMITS, session=fake_session, now=NOW)
        by_url = {i.url: i for i in items}
        evento = by_url["https://store.steampowered.com/news/app/271590/view/2"]
        assert evento.image_url is None

    def test_steam_con_imagen_en_contenido(self, fake_session):
        fake_session.route("appid=271590", FakeResponse(b'{"appnews":{"appid":271590,"newsitems":[]}}'))
        fake_session.route("appid=1687950", FakeResponse(PERSONA_JSON_CON_IMAGEN))
        items = fetch_steam_news(STEAM, LIMITS, session=fake_session, now=NOW)
        by_url = {i.url: i for i in items}
        assert by_url["https://store.steampowered.com/news/app/1687950/view/10"].image_url == "https://cdn.akamai.steamstatic.com/persona6_trailer.jpg"


class TestPeticionHttp:
    def test_parametros_de_la_peticion(self, fake_session, items):
        primera = fake_session.calls[0]["url"]

        assert "appid=271590" in primera
        assert "count=10" in primera
        assert "maxlength=1200" in primera


class TestResiliencia:
    def test_un_app_caido_no_aborta_el_resto(self, fake_session):
        fake_session.route("appid=271590", requests.exceptions.ConnectTimeout())
        fake_session.route("appid=1687950", FakeResponse(PERSONA_JSON))

        result = fetch_steam_news(STEAM, LIMITS, session=fake_session, now=NOW)

        assert [i.source.name for i in result] == ["Steam · Persona"]

    def test_si_fallan_todas_lanza_fetch_error(self, fake_session):
        fake_session.route("appid=271590", requests.exceptions.ConnectTimeout())
        fake_session.route("appid=1687950", FakeResponse(status_code=503))

        with pytest.raises(FetchError, match="todas las apps"):
            fetch_steam_news(STEAM, LIMITS, session=fake_session, now=NOW)

    def test_http_500_incluye_el_nombre_del_juego(self, fake_session):
        solo_gta = SteamConfig(games=(STEAM.games[0],))
        fake_session.route("appid=271590", FakeResponse(status_code=500))

        with pytest.raises(FetchError, match="Grand Theft Auto"):
            fetch_steam_news(solo_gta, LIMITS, session=fake_session, now=NOW)

    def test_json_invalido_lanza_error_claro(self, fake_session):
        solo_gta = SteamConfig(games=(STEAM.games[0],))
        fake_session.route(
            "appid=271590", FakeResponse(content=b"<html>gateway error</html>")
        )

        with pytest.raises(FetchError, match="JSON"):
            fetch_steam_news(solo_gta, LIMITS, session=fake_session, now=NOW)

    def test_respuesta_no_utf8_no_tumba_la_ejecucion(self, fake_session):
        """`json.loads` sobre bytes no-UTF-8 lanza UnicodeDecodeError, que es
        ValueError pero NO JSONDecodeError: se escapaba y abortaba el run."""
        solo_gta = SteamConfig(games=(STEAM.games[0],))
        fake_session.route(
            "appid=271590", FakeResponse(content=b"<html>\xff\xfe error</html>")
        )

        with pytest.raises(FetchError, match="JSON"):
            fetch_steam_news(solo_gta, LIMITS, session=fake_session, now=NOW)

    def test_appnews_no_es_objeto_da_error_limpio(self, fake_session):
        """`appnews: []` provocaba AttributeError en `.get()`, que escapaba
        hasta el pipeline y mataba la ejecución."""
        solo_gta = SteamConfig(games=(STEAM.games[0],))
        fake_session.route(
            "appid=271590", FakeResponse(content=b'{"appnews":[1,2,3]}')
        )

        with pytest.raises(FetchError, match="appnews"):
            fetch_steam_news(solo_gta, LIMITS, session=fake_session, now=NOW)


class TestTopePorJuego:
    """El corte se hacía sobre la lista ACUMULADA de todas las apps, así que
    con `max_items_por_fuente: 20` el segundo juego se descargaba entero y se
    tiraba a la basura: la primera app llenaba la cuota."""

    def test_el_tope_se_aplica_por_app(self, fake_session):
        many = {
            "appnews": {
                "appid": 271590,
                "newsitems": [
                    {"gid": str(i),
                     "title": f"GTA noticia {i}",
                     "url": f"https://store.steampowered.com/news/app/271590/view/{i}",
                     "contents": "<p>Contenido</p>",
                     "date": 1776000000 + i}
                    for i in range(30)
                ],
            }
        }
        fake_session.route(
            "appid=271590", FakeResponse(content=json.dumps(many).encode("utf-8"))
        )
        fake_session.route("appid=1687950", FakeResponse(content=PERSONA_JSON))

        items = fetch_steam_news(STEAM, LIMITS, session=fake_session, now=NOW)

        gta = [i for i in items if "Grand Theft Auto" in i.source.name]
        persona = [i for i in items if "Persona" in i.source.name]
        assert len(gta) == LIMITS.max_items_per_source
        assert len(persona) == 1, "las noticias del segundo juego se perdían"
