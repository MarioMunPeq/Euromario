"""Política de retención del histórico.

Se limpia cuando se cumple cualquiera de estas condiciones:
- la noticia más antigua almacenada supera los 14 días, o
- el total de noticias supera las 200 (recortando primero las más antiguas).
"""

from gaming_news_digest.models import NewsItem


def apply_retention(items: list[NewsItem], max_age_days: int = 14, max_total: int = 200) -> list[NewsItem]:
    """Stub: aplica retención y devuelve la lista filtrada."""
    return items
