"""Tests de carga y validación de la configuración YAML."""

from pathlib import Path

import pytest

from gaming_news_digest.config import (
    DEFAULT_MAX_ITEMS_PER_SOURCE,
    DEFAULT_TIMEOUT_SECONDS,
    ConfigError,
    SteamGame,
    load_games,
    load_sources,
)

FIXTURES = Path(__file__).parent / "fixtures"


def write_yaml(tmp_path: Path, content: str, name: str = "config.yaml") -> Path:
    target = tmp_path / name
    target.write_text(content, encoding="utf-8")
    return target


class TestLoadGames:
    def test_carga_valida(self):
        config = load_games(FIXTURES / "games_valid.yaml")

        assert [rule.name for rule in config.include] == [
            "Grand Theft Auto",
            "Persona",
        ]
        assert config.include[0].aliases == ("GTA", "GTA VI")
        assert config.include[1].aliases == ()
        assert [rule.name for rule in config.exclude] == ["EA Sports FC"]
        assert config.exclude[0].aliases == ("FIFA",)

    def test_logo_opcional_se_carga(self, tmp_path):
        content = (
            "incluir:\n"
            "  - nombre: GTA\n"
            "    logo: gta.svg\n"
        )
        path = write_yaml(tmp_path, content)
        config = load_games(path)
        assert config.include[0].logo == "gta.svg"

    def test_logo_ausente_es_none(self, tmp_path):
        content = "incluir:\n  - nombre: Persona\n"
        path = write_yaml(tmp_path, content)
        config = load_games(path)
        assert config.include[0].logo is None

    def test_logo_vacio_rechazado(self, tmp_path):
        content = "incluir:\n  - nombre: GTA\n    logo: ''\n"
        path = write_yaml(tmp_path, content)
        with pytest.raises(ConfigError, match="logo"):
            load_games(path)

    def test_excluir_faltante_es_valido(self, tmp_path):
        path = write_yaml(tmp_path, "incluir:\n  - nombre: Persona\n")

        config = load_games(path)

        assert config.exclude == ()

    def test_incluir_vacio_rechazado(self, tmp_path):
        path = write_yaml(tmp_path, "incluir: []\n")

        with pytest.raises(ConfigError, match="no puede estar vacía"):
            load_games(path)

    def test_mismo_juego_en_ambas_listas_rechazado(self, tmp_path):
        content = (
            "incluir:\n"
            "  - nombre: GTA\n"
            "excluir:\n"
            "  - nombre: gta\n"
        )
        path = write_yaml(tmp_path, content)

        with pytest.raises(ConfigError, match="a la vez"):
            load_games(path)

    def test_campo_nombre_ausente(self, tmp_path):
        path = write_yaml(tmp_path, "incluir:\n  - aliases: [X]\n")

        with pytest.raises(ConfigError, match="'nombre'"):
            load_games(path)

    def test_alias_no_textual_rechazado(self, tmp_path):
        path = write_yaml(tmp_path, "incluir:\n  - nombre: GTA\n    aliases: [42]\n")

        with pytest.raises(ConfigError, match="alias"):
            load_games(path)

    def test_seccion_que_no_es_lista_rechazada(self, tmp_path):
        path = write_yaml(tmp_path, "incluir: {nombre: GTA}\n")

        with pytest.raises(ConfigError, match="debe ser una lista"):
            load_games(path)


class TestLoadSources:
    def test_carga_valida(self):
        config = load_sources(FIXTURES / "sources_valid.yaml")

        assert [feed.name for feed in config.media] == ["IGN", "Vandal"]
        assert config.media[0].language.value == "en"
        assert config.media[1].language.value == "es"
        assert config.media[1].feed_url.startswith("https://vandal.")
        assert config.steam.enabled is True
        assert config.steam.games == (
            SteamGame(app_id=271590, nombre="Grand Theft Auto"),
            SteamGame(app_id=1174180, nombre="Red Dead Redemption 2"),
        )
        assert config.reddit.subreddits[0].name == "gamingleaks"
        assert config.reddit.subreddits[0].tag == "rumores"
        assert config.limits.max_items_per_source == 10
        assert config.limits.timeout_seconds == 5

    def test_defaults_de_limites_cuando_falta_la_seccion(self, tmp_path):
        path = write_yaml(tmp_path, "medios: []\n")

        config = load_sources(path)

        assert config.limits.max_items_per_source == DEFAULT_MAX_ITEMS_PER_SOURCE
        assert config.limits.timeout_seconds == DEFAULT_TIMEOUT_SECONDS

    def test_medios_ausentes_es_valido(self, tmp_path):
        path = write_yaml(tmp_path, "steam:\n  habilitado: false\n")

        config = load_sources(path)

        assert config.media == ()
        assert config.steam.enabled is False

    def test_campo_feed_ausente(self, tmp_path):
        content = "medios:\n  - nombre: IGN\n    idioma: en\n"
        path = write_yaml(tmp_path, content)

        with pytest.raises(ConfigError, match="'feed'"):
            load_sources(path)

    def test_idioma_invalido(self, tmp_path):
        content = (
            "medios:\n  - nombre: IGN\n    feed: https://x.com/rss\n"
            "    idioma: fr\n"
        )
        path = write_yaml(tmp_path, content)

        with pytest.raises(ConfigError, match="idioma inválido"):
            load_sources(path)

    def test_feed_sin_http(self, tmp_path):
        content = (
            "medios:\n  - nombre: IGN\n    feed: www.ign.com/rss\n"
            "    idioma: en\n"
        )
        path = write_yaml(tmp_path, content)

        with pytest.raises(ConfigError, match="http"):
            load_sources(path)

    def test_app_id_no_entero_positivo(self, tmp_path):
        content = (
            "steam:\n"
            "  juegos:\n"
            "    - app_id: abc\n"
            "      nombre: Grand Theft Auto\n"
        )
        path = write_yaml(tmp_path, content)

        with pytest.raises(ConfigError, match="app_id"):
            load_sources(path)

    def test_juego_de_steam_sin_app_id(self, tmp_path):
        content = (
            "steam:\n"
            "  juegos:\n"
            "    - nombre: Grand Theft Auto\n"
        )
        path = write_yaml(tmp_path, content)

        with pytest.raises(ConfigError, match="'app_id'"):
            load_sources(path)

    def test_habilitado_no_booleano(self, tmp_path):
        path = write_yaml(tmp_path, "steam:\n  habilitado: sí\n")

        with pytest.raises(ConfigError, match="booleano"):
            load_sources(path)

    def test_limite_no_positivo(self, tmp_path):
        content = "limites:\n  max_items_por_fuente: 0\n"
        path = write_yaml(tmp_path, content)

        with pytest.raises(ConfigError, match="entero positivo"):
            load_sources(path)

    def test_subreddit_sin_nombre(self, tmp_path):
        content = "reddit:\n  subreddits:\n    - etiqueta: rumores\n"
        path = write_yaml(tmp_path, content)

        with pytest.raises(ConfigError, match="'nombre'"):
            load_sources(path)


class TestErroresDeArchivo:
    def test_yaml_malformado(self, tmp_path):
        path = write_yaml(tmp_path, "medios: [:::")

        with pytest.raises(ConfigError, match="malformado"):
            load_sources(path)

    def test_raiz_que_no_es_mapa(self, tmp_path):
        path = write_yaml(tmp_path, "- uno\n- dos\n")

        with pytest.raises(ConfigError, match="mapa"):
            load_games(path)

    def test_archivo_inexistente(self, tmp_path):
        with pytest.raises(ConfigError, match="no existe"):
            load_games(tmp_path / "nope.yaml")
