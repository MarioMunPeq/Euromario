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

#: Reintentos ante HTTP 429 (rate limit) y espera base entre ellos.
HTTP_MAX_ATTEMPTS = 2
HTTP_RETRY_BACKOFF_SECONDS = 2


class FetchError(Exception):
    """Una fuente no se pudo rastrear (red, HTTP o contenido inservible)."""


def build_session() -> requests.Session:
    """Crea la sesión HTTP estándar del proyecto."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _retry_delay(response: requests.Response) -> int:
    """Segundos a esperar antes de reintentar un ``429``.

    Prioriza la cabecera ``Retry-After``; si no viene (o no es un número),
    usa ``HTTP_RETRY_BACKOFF_SECONDS``. Tolerante con respuestas falsas en
    tests que no exponen ``headers``.
    """
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After")
    if raw:
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            pass
    return HTTP_RETRY_BACKOFF_SECONDS


def http_get(
    session: requests.Session, url: str, timeout_seconds: int
) -> bytes:
    """Descarga ``url`` elevando ``FetchError`` ante cualquier fallo.

    Un ``HTTP 429`` (rate limit) se reintenta una vez tras ``Retry-After``
    (o ``HTTP_RETRY_BACKOFF_SECONDS``); el resto de estados eleva error
    directamente. Reddit anónimo limita a ≈1 petición/minuto, así que el
    429 puntual no debe tumbar una fuente.
    """
    for attempt in range(1, HTTP_MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=timeout_seconds)
        except requests.RequestException as exc:
            raise FetchError(f"fallo de red en {url}: {exc}") from exc
        if response.status_code == 200:
            return response.content
        if response.status_code == 429 and attempt < HTTP_MAX_ATTEMPTS:
            time.sleep(_retry_delay(response))
            continue
        raise FetchError(f"HTTP {response.status_code} en {url}")


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
