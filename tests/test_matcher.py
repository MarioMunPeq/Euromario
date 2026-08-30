"""Tests del matcher robusto de inclusión/exclusión de juegos."""

import pytest

from gaming_news_digest.config import GameRule
from gaming_news_digest.filtering.matcher import (
    _detect_game_name_with_reason,
    _detect_known_title_any,
    _detect_via_known_title,
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

    def test_recorta_descriptores_entre_nombre_y_ancla(self):
        assert detect_game_name("Red Dead Redemption 2 release date announced", "") == "Red Dead Redemption 2"

    def test_nombre_multipalabra_antes_de_beta(self):
        assert detect_game_name("Monstrum 2 beta test announced", "") == "Monstrum 2"

    def test_hint_steam_gana(self):
        assert detect_game_name("Patch notes", "", hint="Baldur's Gate 3") == "Baldur's Gate 3"

    def test_hint_steam_gana_incluso_con_titulo_generico(self):
        assert detect_game_name("Update 2.1 is here!", "", hint="Cyberpunk 2077") == "Cyberpunk 2077"

    def test_sin_conclusion_devuelve_none(self):
        assert detect_game_name("noticias del sector otra cosa", "") is None

    def test_mayuscula_generica_no_basta(self):
        """PROHIBIDO adivinar por capitalización: 'Nodusfall' no es concluyente."""
        assert detect_game_name("Nodusfall is something different", "") is None

    def test_modern_gamers_steam_no_detecta_modern(self):
        """Regresión: 'Modern gamers spoiled by Steam...' debe ser None (nunca 'Modern')."""
        assert detect_game_name(
            "Modern gamers spoiled by Steam will never understand the joy of a MegaPak", ""
        ) is None

    def test_ancla_con_candidato_generico_devuelve_none(self):
        assert detect_game_name("Modern update brings changes today", "") is None

    def test_titulo_generico_tras_ancla_inicial_devuelve_none(self):
        assert detect_game_name("Update 2.1 is here!", "") is None

    def test_juego_conocido_sin_ancla_via_lista_curada(self):
        """Nombre muy conocido sin ancla: la lista curada lo identifica."""
        assert detect_game_name("Mass Effect 4 development news", "") == "Mass Effect"

    def test_juego_conocido_sensible_a_mayusculas_y_acentos(self):
        assert detect_game_name("ASSASSIN'S CREED SHADOWS devblog post", "") == "Assassin's Creed"

    def test_conocido_exige_limites_de_palabra(self):
        assert detect_game_name("Masseth Effect game", "") is None

    def test_juego_excluido_no_interfiere_en_deteccion(self):
        """La detección solo se llama para artículos no excluidos; aún así,
        un título con puro ruido devuelve None y no inventa nombres."""
        assert detect_game_name("FIFA 24 new kit announced", "") is None


class TestFalsosPositivosProhibidos:
    """Casos que DEBEN devolver None (nunca inventar juego)."""

    def test_empresa_anuncia_iniciativa_gaming(self):
        assert detect_game_name("Sony announces new gaming initiative", "") is None

    def test_plataforma_anuncia_funcion(self):
        assert detect_game_name("Steam announces new feature", "") is None

    def test_hardware_anuncia_tecnologia(self):
        assert detect_game_name("NVIDIA announces DLSS update", "") is None

    def test_usuarios_steam_obtienen_funcion(self):
        assert detect_game_name("Steam users are getting a major new feature", "") is None

    def test_jugadores_reaccionan_actualizacion(self):
        assert detect_game_name("Players react to the latest update", "") is None

    def test_desarrolladores_discuten_futuro(self):
        assert detect_game_name("Developers discuss the future of gaming", "") is None

    def test_actualizacion_vaga_sin_juego(self):
        assert detect_game_name("New update coming soon", "") is None


class TestDeteccionNombreEnMitad:
    """Detección cuando el juego aparece en mitad del titular."""

    def test_gta_vi_gets_trailer(self):
        assert detect_game_name("Grand Theft Auto VI gets a new trailer", "") == "Grand Theft Auto VI"

    def test_persona_5_royal_is_coming(self):
        assert detect_game_name("Persona 5 Royal is coming to PlayStation", "") == "Persona 5 Royal"

    def test_nombre_en_mitad_titulo(self):
        assert detect_game_name("New gameplay trailer for Red Dead Redemption 2 released", "") == "Red Dead Redemption 2"

    def test_posesivo_en_medio(self):
        assert detect_game_name("Spider-Man 2's developer discusses the new update", "") == "Spider-Man"

    def test_marvel_rivals_anuncia_temporada(self):
        assert detect_game_name("Marvel Rivals announces new season", "") == "Marvel Rivals"


class TestReasonTracking:
    """Verifica que _detect_game_name_with_reason devuelve razón correcta."""

    def test_reason_hint(self):
        name, reason = _detect_game_name_with_reason("Patch notes", "", hint="Cyberpunk 2077")
        assert name == "Cyberpunk 2077"
        assert reason == "hint"

    def test_reason_anchor(self):
        name, reason = _detect_game_name_with_reason("Hollow Knight Silksong Patch 1.1 notes", "")
        assert name == "Hollow Knight Silksong"
        assert reason == "anchor"

    def test_reason_known_title(self):
        name, reason = _detect_game_name_with_reason("Mass Effect 4 development news", "")
        assert name == "Mass Effect"
        assert reason == "known_title"

    def test_reason_none(self):
        name, reason = _detect_game_name_with_reason("New update coming soon", "")
        assert name is None
        assert reason is None


class TestProblema3SujetoVsComparacion:
    """PROBLEMA 3: una mención comparativa NO es el nombre del artículo.

    El matcher (nombre) ignora las referencias; el filtro temático (topic)
    las usa como EVIDENCIA de contenido gaming (ahí es otra decisión).
    """

    def test_isnt_elden_ring_detecta_sujeto_nodusfall(self):
        name, reason = _detect_game_name_with_reason(
            "Nodusfall isn't Elden Ring, Monster Hunter or a typical "
            "HoYoverse game – it's a genre-mixing RPG"
        )
        assert name == "Nodusfall"
        assert reason == "subject"

    def test_hades_esque_detecta_sujeto_usual_june(self):
        name, reason = _detect_game_name_with_reason(
            "Usual June mixes Hades-esque action into a roguelite"
        )
        assert name == "Usual June"
        assert reason == "subject"

    def test_gta_no_thanks_detecta_volvys_por_playing(self):
        name, reason = _detect_game_name_with_reason(
            "GTA 6? No thanks, I'll be playing Volvy's Adventure"
        )
        assert name == "Volvy's Adventure"
        assert reason == "playing"

    def test_conocido_en_comparacion_no_devuelve_nombre(self):
        assert _detect_via_known_title(
            "Nodusfall isn't Elden Ring, Monster Hunter or a typical HoYoverse game"
        ) is None

    def test_conocido_en_comparacion_sigue_siendo_evidencia(self):
        """(PROBLEMA 1/3) La versión INGUARDADA sí detecta temática gaming:
        la mención en comparación ES evidencia de contenido."""
        assert _detect_known_title_any(
            "Nodusfall isn't Elden Ring, Monster Hunter or a typical HoYoverse game"
        ) == "Monster Hunter"

    def test_sujeto_conocido_sigue_detectandose(self):
        assert detect_game_name(
            "Monster Hunter Wilds details from the official blog", ""
        ) == "Monster Hunter"


class TestProblema3ConfigNoRobaPorContexto:
    """Un juego CONFIGURADO mencionado solo en comparación no roba la noticia."""

    def test_gta_no_thanks_no_matchea_config(self, matcher):
        ok, game = matcher.match(
            "GTA 6? No thanks, I'll be playing Volvy's Adventure", ""
        )
        assert ok is False
        assert game is None

    def test_gta_subject_sigue_matcheando(self, matcher):
        ok, game = matcher.match("GTA 6 gets a new trailer", "")
        assert ok is True
        assert game == "Grand Theft Auto"

    def test_unlike_x_no_matchea(self, matcher):
        ok, game = matcher.match(
            "Unlike Zelda, this indie won't be on Nintendo first", ""
        )
        assert ok is False
        assert game is None

    def test_context_matches_reporta_la_coincidencia_contextual(self, matcher):
        refused = matcher.context_matches(
            "GTA 6? No thanks, I'll be playing Volvy's Adventure"
        )
        assert refused == ["Grand Theft Auto"]