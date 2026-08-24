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
        relevance=3,
        category="actualizacion",
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
                relevance=3,
                category="actualizacion",
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
                relevance=3,
                category="actualizacion",
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
                relevance=3,
                category="actualizacion",
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
                    relevance=3,
                    category="actualizacion",
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
            relevance=3,
            category="actualizacion",
        )
        result = apply_retention([item], max_age_days=14, now=now)
        assert len(result) == 1


