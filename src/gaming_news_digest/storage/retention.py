"""Política de retención del histórico.

Se limpia cuando se cumple cualquiera de estas condiciones:
- la noticia más antigua almacenada supera los 14 días, o
- el total de noticias almacenadas supera las 200
"""

from datetime import datetime, timedelta, timezone

from ..models import NewsItem


def utc_now() -> datetime:
    """Reloj centralizado (facilita inyectar tiempo fijo en tests).

    Devuelve tiempo UTC sin microsegundos para comparaciones determinísticas
    en tests de retención (evita problemas de boundary por microsegundos).
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def apply_retention(
    items: list["NewsItem"],
    max_age_days: int = 14,
    max_total: int = 200,
    now: datetime | None = None,
) -> list["NewsItem"]:
    """
    Aplica retención sobre lista ORDENADA DESCENDENTE (más nuevo primero).
    Devuelve lista recortada manteniendo orden descendente.

    1. Filtro por antigüedad (corte = ahora - max_age_days)
    2. Cap total: conserva los PRIMEROS max_total (los más nuevos)
    """
    if not items:
        return []

    if now is None:
        now = utc_now()

    cutoff = now - timedelta(days=max_age_days)
    items = [it for it in items if it.published_at >= cutoff]

    if len(items) > max_total:
        items = items[:max_total]

    return items