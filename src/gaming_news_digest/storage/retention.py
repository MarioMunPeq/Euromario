"""Política de retención del histórico.

Se limpia cuando se cumple cualquiera de estas condiciones:
- la noticia más antigua almacenada supera la ventana de tiempo, o
- el total de noticias almacenadas supera las 200
- un juego supera el máximo de historias permitidas

El pipeline diario (pipeline.py) pasa su propia ventana (~24 h con tolerancia,
_DIGEST_WINDOW_HOURS = 26) en max_age_hours; el valor por defecto de 48 horas
se mantiene solo como tope conservador para usos aislados.
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
    max_per_game_reddit: int | None = None,
    now: datetime | None = None,
) -> list[NewsItem]:
    """
    Aplica retención sobre lista ORDENADA DESCENDENTE (más nuevo primero).
    Devuelve lista recortada manteniendo orden descendente.

    1. Filtro por antigüedad (corte = ahora - max_age_hours):
       un item se elimina cuando supera la ventana (corte inclusivo, >=).
    2. Cap total: conserva los PRIMEROS max_total (los más nuevos)
    3. Cap por juego: si se especifica max_per_game, limita por juego
       priorizando por relevancia y luego por fecha.
    
    Reddit items (rumores) se tratan como bloque independiente:
    - No cuentan para max_total
    - Tienen su propio límite por juego (max_per_game_reddit, default 50)
    - Solo se aplica filtro de antigüedad
    """
    if not items:
        return []

    if now is None:
        now = utc_now()

    cutoff = now - timedelta(hours=max_age_hours)
    items = [it for it in items if it.published_at >= cutoff]

    # Separar Reddit y Media/Steam
    reddit_items = [it for it in items if it.source.type.value == "reddit"]
    media_items = [it for it in items if it.source.type.value != "reddit"]

    # Media/Steam: aplicar límites en orden correcto
    # 1. Cap total global (max_total)
    if len(media_items) > max_total:
        media_items = media_items[:max_total]

    # 2. Cap por juego (max_per_game)
    if max_per_game is not None and max_per_game > 0:
        by_game: dict[str, list[NewsItem]] = defaultdict(list)
        for item in media_items:
            by_game[item.game].append(item)

        limited: list[NewsItem] = []
        for game_items in by_game.values():
            if len(game_items) <= max_per_game:
                limited.extend(game_items)
                continue
            sorted_items = sorted(
                game_items,
                key=lambda x: (x.relevance, x.published_at),
                reverse=True,
            )
            limited.extend(sorted_items[:max_per_game])
        media_items = limited

    # Reddit: bloque independiente - solo filtro de edad + límite propio por juego
    reddit_limit = max_per_game_reddit if max_per_game_reddit is not None and max_per_game_reddit > 0 else 50
    if max_per_game_reddit is not None and max_per_game_reddit > 0:
        by_game: dict[str, list[NewsItem]] = defaultdict(list)
        for item in reddit_items:
            by_game[item.game].append(item)

        limited: list[NewsItem] = []
        for game_items in by_game.values():
            if len(game_items) <= reddit_limit:
                limited.extend(game_items)
                continue
            sorted_items = sorted(
                game_items,
                key=lambda x: (x.relevance, x.published_at),
                reverse=True,
            )
            limited.extend(sorted_items[:reddit_limit])
        reddit_items = limited
    # Si max_per_game_reddit es None o <=0, no aplicar límite por juego a Reddit

    # Combinar: Reddit + Media/Steam (ordenados por fecha descendente)
    all_items = reddit_items + media_items
    all_items.sort(key=lambda x: x.published_at, reverse=True)

    return all_items