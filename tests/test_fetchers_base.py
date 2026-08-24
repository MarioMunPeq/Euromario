"""Tests unitarios de las utilidades compartidas de los fetchers."""

import time
from datetime import datetime, timedelta, timezone

import pytest

from gaming_news_digest.fetchers.base import (
    FUTURE_TOLERANCE,
    resolve_date,
    strip_html,
    struct_to_utc,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


class TestResolveDate:
    def test_published_tiene_prioridad(self):
        published = NOW - timedelta(days=1)
        updated = NOW - timedelta(days=2)
        assert resolve_date(published, updated, NOW) == published

    def test_fallback_a_updated(self):
        updated = NOW - timedelta(days=1)
        assert resolve_date(None, updated, NOW) == updated

    def test_sin_fechas_devuelve_ahora(self):
        assert resolve_date(None, None, NOW) == NOW

    def test_fecha_muy_futura_se_recorta_a_ahora(self):
        future = NOW + FUTURE_TOLERANCE + timedelta(minutes=1)
        assert resolve_date(future, None, NOW) == NOW

    def test_skew_pequeno_dentro_de_tolerancia(self):
        near_future = NOW + timedelta(hours=2)
        assert resolve_date(near_future, None, NOW) == near_future


class TestStructToUtc:
    def test_none_devuelve_none(self):
        assert struct_to_utc(None) is None

    def test_convierte_respetando_utc(self):
        moment = time.struct_time((2026, 7, 1, 10, 30, 0, 0, 0, 0))
        expected = datetime(2026, 7, 1, 10, 30, tzinfo=timezone.utc)
        assert struct_to_utc(moment) == expected


class TestStripHtml:
    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_vacios_devuelven_none(self, raw):
        assert strip_html(raw) is None

    def test_elimina_tags(self):
        assert strip_html("<p>Atlus confirma <b>novedades</b>.</p>") == (
            "Atlus confirma novedades."
        )

    def test_decodifica_entidades_y_colapsa_espacios(self):
        raw = "<p>A &amp; B</p>  <p>C</p>\n<p>D</p>"
        assert strip_html(raw) == "A & B C D"
