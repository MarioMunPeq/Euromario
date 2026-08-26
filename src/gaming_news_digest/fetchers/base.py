"""Utilidades compartidas por los fetchers.

Aquí viven la excepción ``FetchError``, la sesión HTTP con User-Agent
propio y la política de fechas documentada en CONTRIBUTING.md:
published → updated → ahora, con clamp anti-relojes adelantados.
"""

import calendar
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

#: Identificación ante las fuentes (Reddit rechaza user-agents genéricos).
USER_AGENT = "gpatch-notes/0.1 (digest automatico de noticias gaming)"

#: Margen tolerado hacia el futuro antes de dar una fecha por corrupta.
FUTURE_TOLERANCE = timedelta(hours=24)


class FetchError(Exception):
    """Una fuente no se pudo rastrear (red, HTTP o contenido inservible)."""


def build_session() -> requests.Session:
    """Crea la sesión HTTP estándar del proyecto."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def http_get(
    session: requests.Session, url: str, timeout_seconds: int
) -> bytes:
    """Descarga ``url`` elevando ``FetchError`` ante cualquier fallo."""
    try:
        response = session.get(url, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise FetchError(f"fallo de red en {url}: {exc}") from exc
    if response.status_code != 200:
        raise FetchError(f"HTTP {response.status_code} en {url}")
    return response.content


def struct_to_utc(value: time.struct_time | None) -> datetime | None:
    """Convierte el ``struct_time`` de feedparser (ya en UTC) en aware."""
    if value is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)


def resolve_date(
    published: datetime | None,
    updated: datetime | None,
    now: datetime,
) -> datetime:
    """Aplica la cadena published → updated → ahora (nunca ``None``).

    Sin ninguna candidata utilizable se devuelve ``now``. Una fecha más
    futura que ``FUTURE_TOLERANCE`` se recorta a ``now`` para que un
    reloj adelantado de la fuente no rompa el orden del digest.
    """
    chosen = next((date for date in (published, updated) if date is not None), now)
    return now if chosen - now > FUTURE_TOLERANCE else chosen


#: Saltos de bloque que actúan como separadores al extraer texto.
_BLOCK_BREAK = re.compile(
    r"(</?(?:p|div|li|tr|table|ul|ol|h[1-6])\b[^>]*>|<br\s*/?>)",
    re.IGNORECASE,
)


def strip_html(raw: str | None) -> str | None:
    """Reduce un fragmento HTML a texto plano colapsando espacios.

    Las etiquetas de bloque (``<p>``, ``<br>``, listas...) actúan como
    separadores para que palabras de párrafos distintos no se peguen; las
    etiquetas en línea (``<b>``, ``<i>``, ``<a>``...) desaparecen sin
    introducir espacios espurios junto a la puntuación.
    """
    if not raw:
        return None
    prepared = _BLOCK_BREAK.sub("\n", raw)
    text = BeautifulSoup(prepared, "html.parser").get_text()
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def utc_now() -> datetime:
    """Reloj centralizado (facilita inyectar tiempo fijo en tests).
    
    Devuelve tiempo UTC sin microsegundos para comparaciones determinísticas
    en tests de retención (evita problemas de boundary por microsegundos).
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


_IMG_SRC = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def extract_first_image_url(html: str) -> str | None:
    """Extrae la primera URL de imagen válida de un fragmento HTML."""
    match = _IMG_SRC.search(html)
    if match:
        url = match.group(1).strip()
        if url.startswith(("http://", "https://")):
            return url
    return None
