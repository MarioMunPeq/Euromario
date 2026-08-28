"""Tests de retención (apply_retention)."""

from datetime import datetime, timedelta

from gaming_news_digest.models import Category, Language, NewsItem, Source
from gaming_news_digest.storage.retention import apply_retention, utc_now


def make_item(title: str, hours_ago: int, game: str = "Persona", now: datetime | None = None) -> NewsItem:
    base = now or utc_now()
    return NewsItem(
        title=title,
        url=f"https://example.com/{title}",
        source=Source(name="Test", type="media"),
        game=game,
        language=Language.ENGLISH,
        published_at=base - timedelta(hours=hours_ago),
        fetched_at=base - timedelta(hours=hours_ago),
        relevance=3,
        category=Category.UPDATE,
        summary="Resumen de prueba.",
    )


class TestApplyRetention:
    def test_solo_antiguedad(self):
        """Items >48 horas se eliminan, ≤48 horas se conservan."""
        now = utc_now()
        items = [
            NewsItem(
                title=f"Item {i}",
                url=f"https://example.com/{i}",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=now - timedelta(hours=h),
                fetched_at=now - timedelta(hours=h),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            for i, h in enumerate([1, 40, 47, 48, 49, 72])
        ]
        items.reverse()

        result = apply_retention(items, max_age_hours=48, max_total=100, now=now)

        assert len(result) == 4
        assert all(it.published_at >= now - timedelta(hours=48) for it in result)

    def test_solo_cap(self):
        """Si >max_total, recorta conservando los más nuevos."""
        now = utc_now()
        items = [
            NewsItem(
                title=f"Item {i}",
                url=f"https://example.com/{i}",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=now - timedelta(hours=204 - i),
                fetched_at=now - timedelta(hours=204 - i),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            for i in range(205)
        ]
        items.reverse()

        result = apply_retention(items, max_age_hours=8760, max_total=200, now=now)

        assert len(result) == 200
        assert result[0].title == "Item 204"
        assert result[-1].title == "Item 5"

    def test_cap_bug_slicing_descendente(self):
        """REGRESIÓN: items[:max_total] conserva los más NUEVOS en orden descendente."""
        now = utc_now()
        items = [
            NewsItem(
                title=f"Item {i}",
                url=f"https://example.com/{i}",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=now - timedelta(hours=200 - i),
                fetched_at=now - timedelta(hours=200 - i),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            for i in range(201)
        ]
        items.reverse()

        result = apply_retention(items, max_age_hours=8760, max_total=200, now=now)

        assert len(result) == 200
        assert result[0].title == "Item 200"
        assert result[-1].title == "Item 1"

    def test_ambos_limites(self):
        now = utc_now()
        items = []
        for i in range(250):
            days_ago = i / 10
            items.append(
                NewsItem(
                    title=f"Item {i}",
                    url=f"https://example.com/{i}",
                    source=Source(name="IGN", type="media"),
                    game="Persona",
                    language="en",
                    published_at=now - timedelta(days=days_ago),
                    fetched_at=now - timedelta(days=days_ago),
                    relevance=3,
                    category="actualizacion",
                    summary="Resumen de prueba.",
                )
            )
        items.reverse()

        result = apply_retention(items, max_age_hours=48, max_total=200, now=now)

        assert len(result) <= 200
        assert all(
            it.published_at >= now - timedelta(hours=48)
            for it in result
        )

    def test_lista_vacia(self):
        assert apply_retention([]) == []

    def test_exactamente_max_total(self):
        now = utc_now()
        items = []
        for i in range(200):
            when = now - timedelta(minutes=i)  # todos dentro de la ventana de 48 h
            items.append(
                NewsItem(
                    title=f"Item {i}",
                    url=f"https://example.com/exacto{i}",
                    source=Source(name="IGN", type="media"),
                    game="Persona",
                    language="en",
                    published_at=when,
                    fetched_at=when,
                    relevance=3,
                    category="actualizacion",
                    summary="Resumen de prueba.",
                )
            )
        items.reverse()
        result = apply_retention(items, max_total=200, now=now)
        assert len(result) == 200

    def test_item_de_47h59m_se_conserva(self):
        """Un item con 47 h 59 m de antigüedad queda dentro de la ventana
        de 48 horas y se conserva."""
        now = utc_now()
        item = NewsItem(
            title="Borde 47h59m",
            url="https://example.com/4759",
            source=Source(name="IGN", type="media"),
            game="Persona",
            language="en",
            published_at=now - timedelta(hours=47, minutes=59),
            fetched_at=now - timedelta(hours=47, minutes=59),
            relevance=3,
            category="actualizacion",
            summary="Resumen de prueba.",
        )
        result = apply_retention([item], now=now)
        assert result == [item]

    def test_item_exactamente_48h_sigue_convencion_boundary(self):
        """Convención existente: el corte es inclusivo (published_at >= cutoff);
        un item de exactamente 48 h se conserva."""
        now = utc_now()
        cutoff = now - timedelta(hours=48)
        item = NewsItem(
            title="Exactamente 48h",
            url="https://example.com/48h",
            source=Source(name="IGN", type="media"),
            game="Persona",
            language="en",
            published_at=cutoff,
            fetched_at=cutoff,
            relevance=3,
            category="actualizacion",
            summary="Resumen de prueba.",
        )
        result = apply_retention([item], now=now)
        assert result == [item]

    def test_item_mas_de_48h_se_elimina(self):
        """Un item con más de 48 h (48 h 1 m) supera la ventana y se elimina."""
        now = utc_now()
        item = NewsItem(
            title="Fuera de ventana",
            url="https://example.com/fuera",
            source=Source(name="IGN", type="media"),
            game="Persona",
            language="en",
            published_at=now - timedelta(hours=48, minutes=1),
            fetched_at=now - timedelta(hours=48, minutes=1),
            relevance=3,
            category="actualizacion",
            summary="Resumen de prueba.",
        )
        result = apply_retention([item], now=now)
        assert result == []

    def test_maximo_200_items_se_mantiene(self):
        """El máximo de 200 items no cambia: se mantiene el cap con la
        nueva ventana de 48 horas."""
        now = utc_now()
        items = []
        for i in range(250):
            when = now - timedelta(minutes=i)  # todos dentro de la ventana de 48 h
            items.append(
                NewsItem(
                    title=f"Item {i}",
                    url=f"https://example.com/max{i}",
                    source=Source(name="IGN", type="media"),
                    game="Persona",
                    language="en",
                    published_at=when,
                    fetched_at=when,
                    relevance=3,
                    category="actualizacion",
                    summary="Resumen de prueba.",
                )
            )
        items.reverse()

        result = apply_retention(items, now=now)

        assert len(result) == 200


class TestApplyRetentionPerGame:
    def test_limite_por_juego(self):
        """Limita el número de noticias por juego."""
        now = utc_now()
        items = [
            NewsItem(
                title=f"GTA {i}",
                url=f"https://example.com/gta{i}",
                source=Source(name="IGN", type="media"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            for i in range(10)
        ] + [
            NewsItem(
                title=f"FIFA {i}",
                url=f"https://example.com/fifa{i}",
                source=Source(name="IGN", type="media"),
                game="FIFA 24",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            for i in range(3)
        ]

        result = apply_retention(items, max_per_game=5, now=now)
        gta_count = sum(1 for r in result if r.game == "Grand Theft Auto")
        fifa_count = sum(1 for r in result if r.game == "FIFA 24")
        assert gta_count == 5  # límite de 5
        assert fifa_count == 3  # por debajo del límite, se conservan todas

    def test_varios_juegos_respetan_limite(self):
        """Cada juego respeta su límite independientemente."""
        now = utc_now()
        items = [
            NewsItem(
                title=f"GTA {i}",
                url=f"https://example.com/gta{i}",
                source=Source(name="IGN", type="media"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen.",
            )
            for i in range(10)
        ] + [
            NewsItem(
                title=f"FIFA {i}",
                url=f"https://example.com/fifa{i}",
                source=Source(name="IGN", type="media"),
                game="FIFA 24",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen.",
            )
            for i in range(8)
        ] + [
            NewsItem(
                title=f"Elden Ring {i}",
                url=f"https://example.com/elden{i}",
                source=Source(name="IGN", type="media"),
                game="Elden Ring",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen.",
            )
            for i in range(3)
        ]

        result = apply_retention(items, max_per_game=5, now=now)
        gta_count = sum(1 for r in result if r.game == "Grand Theft Auto")
        fifa_count = sum(1 for r in result if r.game == "FIFA 24")
        elden_count = sum(1 for r in result if r.game == "Elden Ring")
        assert gta_count == 5
        assert fifa_count == 5
        assert elden_count == 3

    def test_conserva_historias_mejor_puntuadas(self):
        """Prioriza por relevancia y luego por fecha."""
        now = utc_now()
        items = [
            NewsItem(
                title=f"GTA Low {i}",
                url=f"https://example.com/low{i}",
                source=Source(name="IGN", type="media"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=1,  # baja relevancia
                category="actualizacion",
                summary="Resumen.",
            )
            for i in range(3)
        ] + [
            NewsItem(
                title="GTA High Relevance",
                url="https://example.com/gta-high",
                source=Source(name="IGN", type="media"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=36),  # más antiguo (antes: 50h > ventana 48h)
                fetched_at=now - timedelta(hours=36),
                relevance=5,  # alta relevancia
                category="actualizacion",
                summary="Resumen.",
            )
        ]

        result = apply_retention(items, max_per_game=3, now=now)
        # Debe conservar el de alta relevancia aunque sea más antiguo
        titles = [r.title for r in result if r.game == "Grand Theft Auto"]
        assert "GTA High Relevance" in titles
        assert len([t for t in titles if t.startswith("GTA Low")]) == 2  # solo 2 de los 3 low

    def test_juegos_por_debajo_limite_no_afectados(self):
        """Juegos con menos items que el límite no se ven afectados."""
        now = utc_now()
        items = [
            NewsItem(
                title=f"FIFA {i}",
                url=f"https://example.com/fifa{i}",
                source=Source(name="IGN", type="media"),
                game="FIFA 24",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen.",
            )
            for i in range(3)
        ]

        result = apply_retention(items, max_per_game=5, now=now)
        assert len(result) == 3  # todos se conservan

    def test_retencion_global_y_por_juego_combinadas(self):
        """La retención global se aplica primero, luego la por juego."""
        now = utc_now()
        items = []
        # 10 items GTA (recientes) + 10 items FIFA (antiguos >48 horas)
        for i in range(10):
            items.append(
                NewsItem(
                    title=f"GTA {i}",
                    url=f"https://example.com/gta{i}",
                    source=Source(name="IGN", type="media"),
                    game="Grand Theft Auto",
                    language="en",
                    published_at=now - timedelta(hours=i),
                    fetched_at=now - timedelta(hours=i),
                    relevance=3,
                    category="actualizacion",
                    summary="Resumen de prueba.",
                )
            )
        for i in range(10):
            items.append(
                NewsItem(
                    title=f"FIFA {i}",
                    url=f"https://example.com/fifa{i}",
                    source=Source(name="IGN", type="media"),
                    game="FIFA 24",
                    language="en",
                    published_at=now - timedelta(days=20 + i),  # >48 horas
                    fetched_at=now - timedelta(days=20 + i),
                    relevance=3,
                    category="actualizacion",
                    summary="Resumen de prueba.",
                )
            )

        # max_age_hours=48 elimina FIFA, max_total=15 limita total, max_per_game=5 limita GTA
        result = apply_retention(items, max_age_hours=48, max_total=15, max_per_game=5, now=now)
        gta_count = sum(1 for r in result if r.game == "Grand Theft Auto")
        fifa_count = sum(1 for r in result if r.game == "FIFA 24")
        assert gta_count == 5  # limitado por max_per_game
        assert fifa_count == 0  # eliminado por antigüedad
        assert len(result) == 5  # total 5

    def test_urls_y_datos_conservados(self):
        """Verifica que URLs y datos del representante se conservan."""
        now = utc_now()
        items = [
            NewsItem(
                title="GTA 6 anunciado",
                url="https://example.com/gta6",
                source=Source(name="IGN", type="media"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=2),
                fetched_at=now - timedelta(hours=2),
                relevance=4,
                category="lanzamiento",
                summary="Resumen.",
                image_url="https://img.jpg",
            ),
            NewsItem(
                title="GTA 6 confirmado",
                url="https://example.com/gta6-v2",
                source=Source(name="IGN", type="media"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=1),
                fetched_at=now - timedelta(hours=1),
                relevance=5,
                category="lanzamiento",
                summary="Resumen 2.",
                image_url="https://img2.jpg",
            )
        ]

        result = apply_retention(items, max_per_game=1, now=now)
        assert len(result) == 1
        rep = result[0]
        # El de mayor relevancia (5) debe ganar aunque sea más antiguo
        assert rep.relevance == 5
        assert rep.image_url == "https://img2.jpg"


class TestApplyRetentionReddit:
    """Tests para el bloque independiente de Reddit (rumores)."""

    def test_reddit_bloque_independiente_no_compite_por_max_total(self):
        """Reddit items no cuentan para max_total y no se descartan por cap global."""
        now = utc_now()
        # 250 items Media distribuidos en 25 juegos (10 cada uno, todos < 48h) + 10 items Reddit
        # Usar horas 0-9 para cada juego (todos < 48h)
        media_items = [
            NewsItem(
                title=f"Media {game_idx}-{i}",
                url=f"https://example.com/media{game_idx}-{i}",
                source=Source(name="IGN", type="media"),
                game=f"Game{game_idx}",
                language="en",
                published_at=now - timedelta(hours=i),  # 0-9 horas para todos
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen.",
            )
            for game_idx in range(25)  # 25 juegos
            for i in range(10)  # 10 por juego = 250 total
        ]
        reddit_items = [
            NewsItem(
                title=f"Reddit Rumor {i}",
                url=f"https://reddit.com/r/gamingleaksandrumours/{i}",
                source=Source(name="Reddit · r/gamingleaksandrumours", type="reddit", subreddit="gamingleaksandrumours"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="rumor",
                summary="Rumor de prueba.",
            )
            for i in range(10)
        ]
        items = media_items + reddit_items
        items.reverse()

        # max_total=200, pero Reddit no cuenta para este límite
        result = apply_retention(items, max_age_hours=48, max_total=200, max_per_game=8, max_per_game_reddit=15, now=now)

        reddit_count = sum(1 for r in result if r.source.type.value == "reddit")
        media_count = sum(1 for r in result if r.source.type.value != "reddit")

        # Todos los 10 items Reddit deben sobrevivir (bloque independiente)
        assert reddit_count == 10, f"Esperados 10 Reddit, got {reddit_count}"
        # Media: max_total=200 mantiene 200, luego max_per_game=8 reduce a 20*8=160 (20 juegos)
        assert media_count == 160
        assert len(result) == 170  # 160 media + 10 reddit

    def test_reddit_limite_propio_por_juego_max_per_game_reddit(self):
        """Reddit respeta su propio límite por juego (max_per_game_reddit=15)."""
        now = utc_now()
        reddit_items = [
            NewsItem(
                title=f"GTA Rumor {i}",
                url=f"https://reddit.com/r/gamingleaksandrumours/{i}",
                source=Source(name="Reddit · r/gamingleaksandrumours", type="reddit", subreddit="gamingleaksandrumours"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="rumor",
                summary="Rumor de prueba.",
            )
            for i in range(20)
        ]
        items = reddit_items
        items.reverse()

        # max_per_game_reddit=5, así que solo 5 deben sobrevivir
        result = apply_retention(items, max_age_hours=48, max_total=200, max_per_game=8, max_per_game_reddit=5, now=now)

        reddit_count = sum(1 for r in result if r.source.type.value == "reddit")
        assert reddit_count == 5, f"Esperados 5 Reddit (límite 5), got {reddit_count}"

    def test_reddit_sin_limite_por_juego_si_max_per_game_reddit_none_o_cero(self):
        """Si max_per_game_reddit es None o <=0, no hay límite por juego para Reddit."""
        now = utc_now()
        reddit_items = [
            NewsItem(
                title=f"GTA Rumor {i}",
                url=f"https://reddit.com/r/gamingleaksandrumours/{i}",
                source=Source(name="Reddit · r/gamingleaksandrumours", type="reddit", subreddit="gamingleaksandrumours"),
                game=f"Game{i}",  # 49 juegos diferentes para evitar límite por juego
                language="en",
                published_at=now - timedelta(hours=i),  # 0-48 horas (49 items)
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="rumor",
                summary="Rumor de prueba.",
            )
            for i in range(49)
        ]
        items = reddit_items
        items.reverse()

        # max_per_game_reddit=0 -> no límite por juego para Reddit
        result = apply_retention(items, max_age_hours=48, max_total=200, max_per_game=8, max_per_game_reddit=0, now=now)

        reddit_count = sum(1 for r in result if r.source.type.value == "reddit")
        assert reddit_count == 49, f"Esperados 49 Reddit (0-48h), got {reddit_count}"

    def test_reddit_solo_filtro_edad(self):
        """Reddit items >48 horas se eliminan, ≤48 horas se conservan (solo filtro edad)."""
        now = utc_now()
        reddit_items = [
            NewsItem(
                title=f"Rumor {i}",
                url=f"https://reddit.com/r/gamingleaksandrumours/{i}",
                source=Source(name="Reddit · r/gamingleaksandrumours", type="reddit", subreddit="gamingleaksandrumours"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=h),
                fetched_at=now - timedelta(hours=h),
                relevance=3,
                category="rumor",
                summary="Rumor de prueba.",
            )
            for i, h in enumerate([1, 40, 47, 48, 49, 72])
        ]
        items = reddit_items
        items.reverse()

        result = apply_retention(items, max_age_hours=48, max_total=200, max_per_game=8, max_per_game_reddit=15, now=now)

        assert len(result) == 4  # 1, 40, 47, 48 horas se conservan
        assert all(it.published_at >= now - timedelta(hours=48) for it in result)

    def test_reddit_no_discardado_por_max_total_media_lleno(self):
        """Reddit items sobreviven aunque Media llene max_total=200."""
        now = utc_now()
        # 200 Media items distribuidos en 25 juegos (8 cada uno = 200) + 15 Reddit items
        media_items = [
            NewsItem(
                title=f"Media {game_idx}-{i}",
                url=f"https://example.com/media{game_idx}-{i}",
                source=Source(name="IGN", type="media"),
                game=f"Game{game_idx}",
                language="en",
                published_at=now - timedelta(hours=i),  # 0-7 horas para todos
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="actualizacion",
                summary="Resumen.",
            )
            for game_idx in range(25)  # 25 juegos
            for i in range(8)  # 8 por juego = 200 total
        ]
        reddit_items = [
            NewsItem(
                title=f"Reddit {i}",
                url=f"https://reddit.com/r/gamingleaksandrumours/{i}",
                source=Source(name="Reddit · r/gamingleaksandrumours", type="reddit", subreddit="gamingleaksandrumours"),
                game="Grand Theft Auto",
                language="en",
                published_at=now - timedelta(hours=i),
                fetched_at=now - timedelta(hours=i),
                relevance=3,
                category="rumor",
                summary="Rumor.",
            )
            for i in range(15)
        ]
        items = media_items + reddit_items
        items.reverse()

        result = apply_retention(items, max_age_hours=48, max_total=200, max_per_game=8, max_per_game_reddit=15, now=now)

        reddit_count = sum(1 for r in result if r.source.type.value == "reddit")
        media_count = sum(1 for r in result if r.source.type.value != "reddit")

        assert reddit_count == 15, f"Todos 15 Reddit deben sobrevivir, got {reddit_count}"
        assert media_count == 200, f"Media limitado a 200, got {media_count}"
        assert len(result) == 215