"""Tests exhaustivos para el clustering de historias (story clustering)."""

from datetime import datetime, timedelta, timezone

from gaming_news_digest.clustering.story_cluster import (
    cluster_and_select_representatives,
    cluster_items,
    extract_entities,
    extract_keywords,
    items_are_same_story,
    jaccard_similarity,
    normalize_title,
    select_representative,
    word_overlap_similarity,
)
from gaming_news_digest.models import FetchedItem, Source


def make_item(
    title: str,
    url: str,
    game: str = "Grand Theft Auto",
    hours_ago: int = 0,
    source_name: str = "Eurogamer",
    source_type: str = "media",
    body: str = "",
    image_url: str | None = None,
) -> FetchedItem:
    """Crea un FetchedItem de prueba."""
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=hours_ago)
    return FetchedItem(
        title=title,
        url=url,
        source=Source(name=source_name, type=source_type),
        published_at=published,
        fetched_at=now,
        body_text=body,
        language=None,
        game=game,
        image_url=image_url,
        author=None,
    )


class TestExtractKeywords:
    def test_extracts_event_keywords(self):
        text = "GTA 6 officially announced with launch date"
        kw = extract_keywords(text)
        assert "announced" in kw
        assert "launch" in kw
        assert "officially" in kw  # not a stop word

    def test_filters_stop_words(self):
        text = "The game of the week"
        kw = extract_keywords(text)
        assert "game" in kw
        assert "week" in kw
        assert "the" not in kw
        assert "of" not in kw
        assert "the" not in kw  # duplicate check

    def test_filters_noise_words(self):
        text = "Opinion: Analysis of the game"
        kw = extract_keywords(text)
        assert "opinion" not in kw
        assert "analysis" not in kw
        assert "game" in kw


class TestNormalizeTitle:
    def test_normaliza_basico(self):
        assert normalize_title("GTA 6: Nuevo Tráiler") == "gta 6 nuevo trailer"
        assert normalize_title("GTA 6 – Nuevo Tráiler") == "gta 6 nuevo trailer"

    def test_elimina_puntuacion(self):
        assert normalize_title("GTA 6: ¡Anunciado!") == "gta 6 anunciado"


class TestJaccardSimilarity:
    def test_conjuntos_identicos(self):
        assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_conjuntos_disjuntos(self):
        assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_conjuntos_parcial(self):
        assert jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"}) == 0.5


class TestWordOverlapSimilarity:
    def test_titulos_identicos(self):
        assert word_overlap_similarity("GTA 6 anunciado", "GTA 6 anunciado") == 1.0

    def test_titulos_parcialmente_similare(self):
        sim = word_overlap_similarity("GTA 6 anunciado", "GTA 6 confirmado")
        assert 0 < sim < 1

    def test_titulos_distintos(self):
        sim = word_overlap_similarity("GTA 6 anunciado", "FIFA 24 lanzado")
        assert sim == 0.0


class TestExtractEntities:
    def test_extrae_numeros_version(self):
        ents = extract_entities("GTA 6 anunciado", "GTA VI llegará pronto")
        assert "6" in ents or "VI" in ents

    def test_extrae_siglas(self):
        ents = extract_entities("GTA 6", "GTA VI")
        assert "GTA" in ents


class TestItemsAreSameStory:
    def test_same_url(self):
        item1 = make_item("GTA 6 announced", "https://eurogamer.net/gta6", hours_ago=1)
        item2 = make_item("GTA 6 confirmed", "https://eurogamer.net/gta6", hours_ago=2)
        assert items_are_same_story(item1, item2) is True

    def test_same_announcement_different_sources(self):
        item1 = make_item(
            "Rockstar announces GTA 6 for 2025",
            "https://eurogamer.net/gta6-announced",
            hours_ago=2,
            source_name="Eurogamer",
        )
        item2 = make_item(
            "Rockstar confirms GTA 6 for 2025",
            "https://ign.com/gta6-announced",
            hours_ago=3,
            source_name="IGN",
        )
        # Same game, similar keywords (announces/confirms, GTA 6), time window OK
        assert items_are_same_story(item1, item2) is True

    def test_different_events_same_game(self):
        item1 = make_item(
            "GTA 6 launches in 2025",
            "https://eurogamer.net/gta6-launch",
            hours_ago=24,
        )
        item2 = make_item(
            "GTA Online receives new update",
            "https://ign.com/gta-online-update",
            hours_ago=25,
        )
        # Same game, but different events (launch vs online update)
        assert items_are_same_story(item1, item2) is False

    def test_outside_time_window_no_group(self):
        item1 = make_item("GTA 6 announced", "https://a.com/1", hours_ago=1)
        item2 = make_item("GTA 6 confirmed", "https://b.com/2", hours_ago=72)  # 72h > 48h
        assert items_are_same_story(item1, item2) is False

    def test_different_games_no_group(self):
        item1 = make_item("GTA 6 announced", "https://a.com/1", game="Grand Theft Auto", hours_ago=1)
        item2 = make_item("GTA 6 confirmed", "https://b.com/2", game="Call of Duty", hours_ago=2)
        assert items_are_same_story(item1, item2) is False

    def test_partial_title_similarity_no_group(self):
        item1 = make_item("GTA 6 launches in 2025", "https://a.com/1", hours_ago=1)
        item2 = make_item("FIFA 24 launches in 2024", "https://b.com/2", game="FIFA 24", hours_ago=2)
        assert items_are_same_story(item1, item2) is False


class TestSelectRepresentative:
    def test_prefers_with_image(self):
        item1 = make_item("GTA 6", "https://a.com/1", hours_ago=2, image_url=None)
        item2 = make_item("GTA 6", "https://a.com/2", hours_ago=1, image_url="https://img.com/img.jpg")
        rep = select_representative([item1, item2])
        assert rep.image_url is not None

    def test_without_images_most_recent(self):
        item1 = make_item("GTA 6", "https://a.com/1", hours_ago=3)
        item2 = make_item("GTA 6", "https://a.com/2", hours_ago=1)
        rep = select_representative([item1, item2])
        assert rep.url == "https://a.com/2"

    def test_single_item(self):
        item = make_item("GTA 6", "https://a.com/1", hours_ago=1)
        rep = select_representative([item])
        assert rep == item


class TestClusterItems:
    def test_groups_same_announcement_different_sources(self):
        items = [
            make_item("Rockstar announces GTA 6", "https://eurogamer.net/1", hours_ago=1, source_name="Eurogamer"),
            make_item("Rockstar confirms GTA 6", "https://ign.com/1", hours_ago=2, source_name="IGN"),
            make_item("Rockstar reveals GTA 6", "https://pcgamer.com/1", hours_ago=2, source_name="PC Gamer"),
        ]
        clusters = cluster_items(items)
        assert len(clusters) == 1
        assert clusters[0].count == 3

    def test_does_not_group_different_events(self):
        items = [
            make_item("GTA 6 launches in 2025", "https://a.com/1", hours_ago=1),
            make_item("GTA Online receives new update", "https://b.com/1", hours_ago=2),
            make_item("GTA 6 trailer tomorrow", "https://c.com/1", hours_ago=3),
        ]
        clusters = cluster_items(items)
        # Should be at least 2 clusters (launch, online update, trailer)
        assert len(clusters) >= 2

    def test_no_group_outside_time_window(self):
        items = [
            make_item("GTA 6 announced", "https://a.com/1", hours_ago=1),
            make_item("GTA 6 confirmed", "https://b.com/1", hours_ago=72),  # 72h > 48h
        ]
        clusters = cluster_items(items)
        assert len(clusters) == 2

    def test_different_games_no_group(self):
        items = [
            make_item("GTA 6 announced", "https://a.com/1", game="Grand Theft Auto", hours_ago=1),
            make_item("GTA 6 confirmed", "https://b.com/2", game="Call of Duty", hours_ago=2),
        ]
        clusters = cluster_items(items)
        assert len(clusters) == 2

    def test_preserves_individual_urls(self):
        items = [
            make_item("GTA 6 announced", "https://eurogamer.net/1", hours_ago=1),
            make_item("GTA 6 confirmed", "https://ign.com/1", hours_ago=2),
        ]
        clusters = cluster_items(items)
        assert len(clusters) == 1
        urls = {item.url for item in clusters[0].items}
        assert "https://eurogamer.net/1" in urls
        assert "https://ign.com/1" in urls

    def test_cluster_has_single_representative(self):
        items = [
            make_item("GTA 6 announced", "https://a.com/1", hours_ago=1, image_url=None),
            make_item("GTA 6 confirmed", "https://b.com/1", hours_ago=2, image_url="https://img.jpg"),
        ]
        clusters = cluster_items(items)
        assert len(clusters) == 1
        assert clusters[0].representative.image_url is not None

    def test_no_lost_news(self):
        items = [
            make_item("GTA 6 announced", "https://a.com/1", hours_ago=1),
            make_item("FIFA 24 launched", "https://b.com/1", game="FIFA 24", hours_ago=2),
            make_item("Call of Duty new", "https://c.com/1", game="Call of Duty", hours_ago=3),
        ]
        clusters = cluster_items(items)
        total_items = sum(c.count for c in clusters)
        assert total_items == 3

    def test_cluster_preserves_metadata(self):
        items = [
            make_item("GTA 6 announced", "https://a.com/1", hours_ago=1, source_name="Eurogamer"),
            make_item("GTA 6 confirmed", "https://b.com/1", hours_ago=2, source_name="IGN"),
        ]
        clusters = cluster_items(items)
        cluster = clusters[0]
        assert cluster.game == "Grand Theft Auto"
        assert "Eurogamer" in cluster.sources
        assert "IGN" in cluster.sources
        assert cluster.count == 2


class TestClusterAndSelectRepresentatives:
    def test_returns_only_representatives(self):
        items = [
            make_item("GTA 6 announced", "https://a.com/1", hours_ago=1, image_url=None),
            make_item("GTA 6 confirmed", "https://b.com/1", hours_ago=2, image_url="https://img.jpg"),
            make_item("FIFA 24 launched", "https://c.com/1", game="FIFA 24", hours_ago=1),
        ]
        reps = cluster_and_select_representatives(items)
        assert len(reps) == 2  # 1 cluster GTA 6 + 1 FIFA 24
        assert any(r.image_url for r in reps)

    def test_ungrouped_item_preserved(self):
        items = [
            make_item("Unique news", "https://a.com/1", game="Unique Game", hours_ago=1),
        ]
        reps = cluster_and_select_representatives(items)
        assert len(reps) == 1
        assert reps[0].title == "Unique news"