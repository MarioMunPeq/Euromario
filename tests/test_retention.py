"""Tests de retención (apply_retention)."""

from datetime import datetime, timedelta

from gaming_news_digest.models import NewsItem, Source
from gaming_news_digest.storage.retention import apply_retention, utc_now


def make_item(title: str, hours_ago: int, game: str = "Persona", now: datetime | None = None) -> NewsItem:
    base = now or utc_now()
    return NewsItem(
        title=title,
        url=f"https://example.com/{title}",
        source=Source(name="IGN", type="media"),
        game=game,
        language="en",
        published_at=base - timedelta(hours=hours_ago),
        fetched_at=base - timedelta(hours=hours_ago),
        relevance=3,
        category="actualizacion",
        summary="Resumen de prueba.",
    )


class TestApplyRetention:
    def test_solo_antiguedad(self):
        """Items >14 días se eliminan, ≤14 días se conservan."""
        now = utc_now()
        items = [
            NewsItem(
                title=f"Item {i}",
                url=f"https://example.com/{i}",
                source=Source(name="IGN", type="media"),
                game="Persona",
                language="en",
                published_at=now - timedelta(days=d),
                fetched_at=now - timedelta(days=d),
                relevance=3,
                category="actualizacion",
                summary="Resumen de prueba.",
            )
            for i, d in enumerate([1, 13, 14, 15, 30])
        ]
        items.reverse()

        result = apply_retention(items, max_age_days=14, max_total=100, now=now)

        assert len(result) == 3
        assert all(it.published_at >= now - timedelta(days=14) for it in result)

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

        result = apply_retention(items, max_age_days=365, max_total=200, now=now)

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

        result = apply_retention(items, max_age_days=365, max_total=200, now=now)

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

        result = apply_retention(items, max_age_days=14, max_total=200, now=now)

        assert len(result) <= 200
        assert all(
            it.published_at >= now - timedelta(days=14)
            for it in result
        )

    def test_lista_vacia(self):
        assert apply_retention([]) == []

    def test_exactamente_max_total(self):
        now = utc_now()
        items = [make_item(f"Item {i}", i, now=now) for i in range(200)]
        items.reverse()
        result = apply_retention(items, max_total=200, now=now)
        assert len(result) == 200

    def test_exactamente_max_age(self):
        now = utc_now()
        cutoff = now - timedelta(days=14)
        item = NewsItem(
            title="Edge",
            url="https://example.com/edge",
            source=Source(name="IGN", type="media"),
            game="Persona",
            language="en",
            published_at=cutoff,
            fetched_at=cutoff,
            relevance=3,
            category="actualizacion",
            summary="Resumen de prueba.",
        )
        result = apply_retention([item], max_age_days=14, now=now)
        assert len(result) == 1


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
                published_at=now - timedelta(hours=50),  # más antiguo
                fetched_at=now - timedelta(hours=50),
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
        # 10 items GTA (recientes) + 10 items FIFA (antiguos >14 días)
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
                    published_at=now - timedelta(days=20 + i),  # >14 días
                    fetched_at=now - timedelta(days=20 + i),
                    relevance=3,
                    category="actualizacion",
                    summary="Resumen de prueba.",
                )
            )

        # max_age_days=14 elimina FIFA, max_total=15 limita total, max_per_game=5 limita GTA
        result = apply_retention(items, max_age_days=14, max_total=15, max_per_game=5, now=now)
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


