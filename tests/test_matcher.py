"""Tests del matcher robusto de inclusión/exclusión de juegos."""

import pytest

from gaming_news_digest.config import GameRule
from gaming_news_digest.filtering.matcher import (
    _normalize,
    create_matcher,
    detect_game_name,
)


@pytest.fixture
def matcher():
    """Matcher con reglas de prueba estándar."""
    include = [
        GameRule(name="Grand Theft Auto", aliases=["GTA", "GTA 6", "GTA VI"]),
        GameRule(name="Persona", aliases=["P5", "Persona 5"]),
        GameRule(name="Call of Duty", aliases=["CoD"]),
        GameRule(name="The Legend of Zelda", aliases=["Zelda"]),
    ]
    exclude = [
        GameRule(name="EA Sports FC", aliases=["FIFA"]),
    ]
    return create_matcher(include, exclude)


class TestNormalizacion:
    def test_nfkc_y_lowercase(self):
        assert _normalize("GTA VI") == "gta vi"
        assert _normalize("PERSONA 6") == "persona 6"
        assert _normalize("Café") == "cafe"
        assert _normalize("GTA VI") == "gta vi"

    def test_puntuacion_a_espacio(self):
        assert _normalize("GTA-VI") == "gta vi"
        assert _normalize("GTA/VI") == "gta vi"


class TestInclusionTemaPrincipal:
    def test_match_por_nombre_canonico_en_titulo(self, matcher):
        assert matcher.is_main_topic(
            "Persona 6 anunciado", "Cuerpo irrelevante", matcher.include[1][0]
        ) is True

    def test_match_por_alias_en_titulo(self, matcher):
        assert matcher.is_main_topic(
            "GTA VI anunciado", "Cuerpo", matcher.include[0][0]
        ) is True

    def test_match_por_alias_numerico_en_titulo(self, matcher):
        assert matcher.is_main_topic(
            "Persona 5 Royal rebajado", "Cuerpo", matcher.include[1][0]
        ) is True

    def test_match_por_alias_corto_en_titulo(self, matcher):
        assert matcher.is_main_topic(
            "CoD nuevo mapa", "Cuerpo", matcher.include[2][0]
        ) is True

    def test_dos_menciones_en_body_sin_titulo(self, matcher):
        title = "Novedades del sector"
        body = "GTA VI anuncia DLC. GTA VI sale en 2025."
        assert matcher.is_main_topic(title, body, matcher.include[0][0]) is True

    def test_una_sola_mencion_en_body_no_basta(self, matcher):
        title = "Novedades del sector"
        body = "GTA VI anuncia DLC."
        assert matcher.is_main_topic(title, body, matcher.include[0][0]) is False

    def test_insensible_a_mayusculas_y_acentos(self, matcher):
        assert matcher.is_main_topic(
            "PERSONA 6 ANUNCIADO", "Cuerpo", matcher.include[1][0]
        ) is True
        assert matcher.is_main_topic(
            "Gta vi sale", "Cuerpo", matcher.include[0][0]
        ) is True


class TestWordBoundariesSinFalsosPositivos:
    def test_gta_dentro_de_otra_palabra_no_matchea(self, matcher):
        assert matcher.is_main_topic("OGTAX", "Cuerpo", matcher.include[0][0]) is False

    def test_gta_v_sin_espacio_no_matchea(self, matcher):
        assert matcher.is_main_topic("GTAV sale", "Cuerpo", matcher.include[0][0]) is False


class TestExclusionCualquierMencion:
    def test_exclusion_por_titulo(self, matcher):
        assert matcher.is_mentioned("FIFA 24 sale mañana", "", matcher.exclude[0]) is True

    def test_exclusion_por_mencion_unica_en_body(self, matcher):
        assert matcher.is_mentioned("Novedades varias", "FIFA 24 tiene actualización", matcher.exclude[0]) is True


class TestPrioridadExclusionSobreInclusion:
    def test_exclusion_gana_sobre_inclusion_mismo_articulo(self, matcher):
        title = "CoD y FIFA en la misma noticia"
        body = "Ambos tienen novedades."
        # incluir: CoD; excluir: FIFA
        accept, game = matcher.match(title, body)
        assert accept is False
        assert game is None

    def test_inclusion_sin_exclusion_aceptada(self, matcher):
        accept, game = matcher.match("CoD nuevo mapa", "Detalles aquí.")
        assert accept is True
        assert game == "Call of Duty"


class TestPoisonPillExclusionGlobal:
    def test_exclusion_antes_que_inclusion_mismo_articulo(self, matcher):
        """Juego excluido (mención única en body) + incluido (tema principal en título) → descartado."""
        title = "GTA VI anuncia expansión"
        body = "FIFA 24 también tiene actualización menor."
        # incluir: GTA; excluir: FIFA
        accept, game = matcher.match(title, body)
        assert accept is False
        assert game is None

    def test_exclusion_en_titulo_tambien_descarta(self, matcher):
        title = "FIFA 24 sale mañana"
        body = "GTA VI también tiene noticias."
        accept, game = matcher.match(title, body)
        assert accept is False
        assert game is None


class TestSinMatchEnInclusion:
    def test_ningun_juego_incluido_descarta(self, matcher):
        accept, game = matcher.match("Novedades de Minecraft", "Actualización 1.20.")
        assert accept is False
        assert game is None


class TestIsExcludedDirecto:
    def test_exclusion_por_titulo(self, matcher):
        assert matcher.is_excluded("FIFA 24 sale mañana", "Cuerpo") is True

    def test_exclusion_por_mención_unica_en_body(self, matcher):
        assert matcher.is_excluded("Novedades varias", "FIFA 24 tiene actualización") is True

    def test_sin_exclusion_false(self, matcher):
        assert matcher.is_excluded("Noticias de Persona", "Solo noticias de la saga.") is False


class TestDeteccionJuegosNoConfigurados:
    def test_nombre_antes_de_palabra_ancla(self):
        assert detect_game_name("Hollow Knight Silksong Patch 1.1 notes", "") == "Hollow Knight Silksong"

    def test_recorta_ruido_inicial(self):
        assert detect_game_name("New Hades 2 gameplay trailer released", "") == "Hades 2"

    def test_secuencia_capitalizada_como_fallback(self):
        assert detect_game_name("Nodusfall is something different", "") == "Nodusfall"

    def test_hint_steam_gana(self):
        assert detect_game_name("Patch notes", "", hint="Baldur's Gate 3") == "Baldur's Gate 3"

    def test_sin_conclusion_devuelve_none(self):
        assert detect_game_name("noticias del sector otra cosa", "") is None