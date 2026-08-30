"""Tests del filtro temático: ¿es realmente un artículo de videojuegos?

El dominio de la fuente NO basta: Polygon/IGN publican cine, series, cómics
y cultura. Cada artículo debe demostrar que pertenece al ámbito gaming.
Precisión > recall: si dudamos, se descarta.
"""

from gaming_news_digest.filtering.topic import (
    classify_video_game_article,
    is_video_game_article,
)


class TestCasosUsuariosPolygon:
    """Los dos casos reales citados por el usuario deben DESCARTARSE."""

    def test_rdj_thriller_netflix_no_es_videojuego(self):
        assert is_video_game_article(
            "Robert Downey Jr's 98-Minute Cult Classic Psychological "
            "Thriller Is Officially Coming to Netflix"
        ) is False

    def test_serie_netflix_no_es_videojuego(self):
        assert is_video_game_article(
            "Netflix Is About to Lose a 10/10 Sci-Fi Series That's "
            "Perfect From Start to Finish"
        ) is False


class TestEjemplosExactosUsuario:
    """Los 4 ejemplos exactos de la ronda 4 como regresión."""

    def test_nintendo_hardware_acepta(self):
        ok, reason = classify_video_game_article(
            "Nintendo announces new hardware strategy"
        )
        assert ok is True
        assert reason == "senal_positiva_fuerte"

    def test_netflix_serie_descarta(self):
        assert is_video_game_article(
            "Netflix is about to lose a 10/10 sci-fi series"
        ) is False

    def test_rdj_cult_classic_netflix_descarta(self):
        assert is_video_game_article(
            "Robert Downey Jr's 98-Minute Cult Classic Psychological "
            "Thriller Is Officially Coming to Netflix"
        ) is False

    def test_nintendo_hardware_tiene_senal_de_juego(self):
        """Pasa el filtro temático pero el matcher debe quedar en None."""
        ok = is_video_game_article(
            "Nintendo announces new hardware strategy"
        )
        assert ok is True


class TestSeñalesFuertes:
    """Artículos claramente gaming → aceptar."""

    def test_nintendo_estrategia_hardware_sin_juego_concreto(self):
        """Sin nombre de juego pero señal clara de videojuegos."""
        ok, reason = classify_video_game_article(
            "Nintendo announces new hardware strategy"
        )
        assert ok is True
        assert reason == "senal_positiva_fuerte"

    def test_juego_de_plataforma_console(self):
        assert is_video_game_article(
            "The new Xbox controller review"
        ) is True

    def test_termino_juego_explicito(self):
        assert is_video_game_article("How gaming changed in 2026") is True

    def test_generos_videojuego(self):
        assert is_video_game_article("Best RPGs of the month") is True
        assert is_video_game_article("FPS games coming in 2027") is True

    def test_plataforma_steam(self):
        assert is_video_game_article(
            "Steam users are getting a major new feature"
        ) is True

    def test_nombre_juego_conocido_sin_ancla(self):
        assert is_video_game_article("Mass Effect 4 development news") is True

    def test_juego_detectado_por_ancla(self):
        assert is_video_game_article(
            "Monstrum 2 beta test announced"
        ) is True


class TestPalabrasGenericasNoBastan:
    """'trailer', 'update', 'release', 'review' SOLOS no prueban nada."""

    def test_trailer_solo_insuficiente(self):
        assert is_video_game_article("A brand new trailer is out") is False

    def test_update_solo_insuficiente(self):
        assert is_video_game_article("Update 2.1 is here!") is False

    def test_release_solo_insuficiente(self):
        assert is_video_game_article("The big release of the week") is False

    def test_review_solo_insuficiente(self):
        assert is_video_game_article("Our in-depth review") is False


class TestFalsosPositivosCinemaTV:
    """Contenido de cine/series que suena a gaming pero NO lo es."""

    def test_game_de_thrones(self):
        assert is_video_game_article(
            "Game of Thrones season finale review"
        ) is False

    def test_hunger_games(self):
        assert is_video_game_article(
            "The Hunger Games new prequel announced"
        ) is False

    def test_squid_game_serie(self):
        assert is_video_game_article(
            "Squid Game season 3 on Netflix"
        ) is False

    def test_tlo_series_hbo(self):
        """'The Last of Us' es juego, pero la noticia es de la serie de HBO."""
        assert is_video_game_article(
            "The Last of Us HBO series cast announced"
        ) is False

    def test_actor_aunque_mencione_gaming(self):
        """Un actor famoso + palabra gaming incidental → se descarta."""
        assert is_video_game_article(
            "Actor Tom Cruise discusses gaming habits on TV show"
        ) is False

    def test_movies_url(self):
        assert is_video_game_article(
            "The 10 best movies of 2026", url="theverge.com/movies"
        ) is False


class TestMencionIncidentalNoMata:
    """Negativas incidentales no deben hundir una noticia claramente gaming."""

    def test_juego_que_menciona_streaming(self):
        assert is_video_game_article(
            "New gaming streaming feature on PlayStation in 2026"
        ) is True

    def test_juego_con_pelicula_anunciada(self):
        """Noticia del JUEGO que menciona una película de pasada."""
        assert is_video_game_article(
            "Grand Theft Auto VI gets a new trailer"
        ) is True

    def test_cuerpo_con_netflix_incidental_no_descarta(self):
        """'Netflix' en el cuerpo (no en el título) no debe hundir un juego
        confirmado por nombre de juego en el título."""
        assert is_video_game_article(
            "Monstrum 2 beta test announced",
            body="Playable now. The studio also produced a documentary about "
                 "game development for Netflix.",
        ) is True

    def test_cuerpo_con_netflix_en_titulo_si_descarta(self):
        """Si la señal negativa está en el TÍTULO, sí descarta aunque el
        cuerpo hable de actualización de juego."""
        assert is_video_game_article(
            "New Netflix series out today",
            body="The game update adds new characters and patches.",
        ) is False


class TestFeedCategories:
    """La metadata del feed aporta CONTEXTO, no decides sola (PROBLEMA 1)."""

    def test_categoria_juegos_no_acepta_sola(self):
        """Un feed gaming publica trailers de cine y mercancía: la categoría
        'Games' sin ninguna señal de texto ya NO acepta."""
        ok, reason = classify_video_game_article(
            "Some vague title", feed_categories=("Games",)
        )
        assert ok is False
        assert reason == "sin_senal_suficiente"

    def test_categoria_juegos_con_una_senal_debil_acepta(self):
        """Feed gaming + una señal débil (un trailer genérico) sí basta."""
        ok, reason = classify_video_game_article(
            "A brand new trailer is out", feed_categories=("Games",)
        )
        assert ok is True
        assert reason == "feed_contexto_videojuegos"

    def test_categoria_juegos_con_negativa_fuerte_descarta(self):
        """El contexto de feed NUNCA compensa una señal negativa de texto."""
        ok, reason = classify_video_game_article(
            "New Netflix series out today", feed_categories=("Games",)
        )
        assert ok is False
        assert reason.startswith("senal_negativa:")

    def test_categoria_peliculas_descarta_incluso_con_texto_dudoso(self):
        ok, reason = classify_video_game_article(
            "New trailer coming soon", feed_categories=("Movies",)
        )
        assert ok is False
        assert reason == "feed_seccion_incompatible"

    def test_categoria_series_descarta(self):
        assert is_video_game_article(
            "What to watch this weekend", feed_categories=("TV Shows",)
        ) is False

    def test_categoria_gaming_vs_entretenimiento(self):
        """Categoría 'Entertainment' (blanda) sin señal positiva → texto."""
        ok = is_video_game_article(
            "Vague article title", feed_categories=("Entertainment",)
        )
        assert ok is False

    def test_categoria_gaming_con_entretenimiento_texto_fuerte(self):
        ok = is_video_game_article(
            "Nintendo Switch 2 sales numbers",
            feed_categories=("Entertainment",),
        )
        assert ok is True

    def test_sin_categorias_usa_texto(self):
        assert is_video_game_article("Steam sale is live") is True


class TestProblema3ComparacionesSon_EVIDENCIA_NoNombre:
    """Las menciones comparativas demuestran TEMÁTICA gaming (aquí) aunque el
    matcher no deba usarlas como NOMBRE del artículo (allí)."""

    def test_isnt_elden_ring_es_contenido_gaming(self):
        ok, reason = classify_video_game_article(
            "Nodusfall isn't Elden Ring, Monster Hunter or a typical "
            "HoYoverse game – it's a genre-mixing RPG"
        )
        assert ok is True
        # "HoYoverse" aporta señal positiva fuerte; la mención en comparación
        # de Elden Ring/Monster Hunter también cuenta (PROBLEMA 3).
        assert reason in ("juego_reconocible", "senal_positiva_fuerte")

    def test_hades_esque_es_contenido_gaming(self):
        assert is_video_game_article(
            "Usual June mixes Hades-esque action into a roguelite"
        ) is True

    def test_playing_adventure_volvys_es_contenido_gaming(self):
        assert is_video_game_article(
            "GTA 6? No thanks, I'll be playing Volvy's Adventure"
        ) is True


class TestProblema2CompartirFranquiciaNoEsGaming:
    """Contenido de cine/TV/merch que comparte franquicia con videojuegos."""

    def test_juego_gano_un_juego_de_verdad(self):
        """'Resident Evil' + señal gaming → el artículo ES del juego."""
        ok, reason = classify_video_game_article(
            "Resident Evil game gets new trailer for upcoming title"
        )
        assert ok is True
        assert reason == "juego_reconocible"

    def test_juego_vs_pelicula_gana_pelicula(self):
        assert is_video_game_article(
            "Resident Evil movie opens to record box office"
        ) is False

    def test_merch_no_es_videojuego(self):
        ok, reason = classify_video_game_article(
            "Capcom unveils Collector's Edition statues and souvenirs"
        )
        assert ok is False
        assert reason.startswith("senal_negativa:")

    def test_alien_romulus_de_ridley_scott_no_es_gaming(self):
        """El ejemplo real de la ronda 5: cita de cine sobre la película. Se
        descarta antes de llegar al matcher (sin evidencia positiva alguna;
        además el candidato-ancla del titular es prosa, no un juego)."""
        ok, _ = classify_video_game_article(
            "Ridley Scott Says Alien Romulus Was OK, So He's Returning to the "
            "Franchise Because It 'Needs Some Help'"
        )
        assert ok is False

    def test_alien_romulus_con_feed_gaming_tampoco_se_cuela(self):
        ok = is_video_game_article(
            "Ridley Scott Says Alien Romulus Was OK, So He's Returning to the Franchise",
            feed_categories=("Games",),
        )
        assert ok is False