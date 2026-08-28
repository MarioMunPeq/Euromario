"""Política de retención del histórico.

Se limpia cuando se cumple cualquiera de estas condiciones:
- la noticia más antigua almacenada supera las 48 horas, o
- el total de noticias almacenadas supera las 200
- un juego supera el máximo de historias permitidas
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ..models import NewsItem


def utc_now() -> datetime:
    """Reloj centralizado (facilita inyectar tiempo fijo en tests).

    Devuelve tiempo UTC sin microsegundos para comparaciones determinísticas
    en tests de retención (evita problemas de boundary por microsegundos).
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def apply_retention(
    items: list[NewsItem],
    max_age_hours: int = 48,
    max_total: int = 200,
    max_per_game: int | None = None,
    now: datetime | None = None,
) -> list[NewsItem]:
    """
    Aplica retención sobre lista ORDENADA DESCENDENTE (más nuevo primero).
    Devuelve lista recortada manteniendo orden descendente.

    1. Filtro por antigüedad (corte = ahora - max_age_hours):
       un item se elimina cuando supera las 48 horas (corte inclusivo, >=).
    2. Cap total: conserva los PRIMEROS max_total (los más nuevos)
    3. Cap por juego: si se especifica max_per_game, limita por juego
       priorizando por relevancia y luego por fecha.
    """
    if not items:
        return []

    if now is None:
        now = utc_now()

    cutoff = now - timedelta(hours=max_age_hours)
    items = [it for it in items if it.published_at >= cutoff]

    if len(items) > max_total:
        items = items[:max_total]

    # Límite por juego (aplicado después del límite global)
    if max_per_game is not None and max_per_game > 0:
        by_game: dict[str, list[NewsItem]] = defaultdict(list)
        for item in items:
            by_game[item.game].append(item)

        limited: list[NewsItem] = []
        for game_items in by_game.values():
            if len(game_items) <= max_per_game:
                limited.extend(game_items)
                continue
            # Ordenar por relevancia y fecha
            sorted_items = sorted(
                game_items,
                key=lambda x: (x.relevance, x.published_at),
                reverse=True,
            )
            limited.extend(sorted_items[:max_per_game])
        items = limited

    return items