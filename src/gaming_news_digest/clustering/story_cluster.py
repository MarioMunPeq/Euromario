"""Clustering de historias para deduplicación semántica a nivel de historia.

Agrupa artículos que cubren el mismo acontecimiento/evento, no solo el mismo juego.
Usa un enfoque determinista y ligero sin dependencias pesadas:

1. URL exacta (capa 0 - deduplicación exacta)
2. Juego + entidades clave del título (capa 1)
3. Similitud de palabras clave relevantes (capa 2)
4. Similitud de títulos (Jaccard/overlap) (capa 3)
4. Ventana temporal 24-48h (capa 4)

El resultado son StoryClusters con un artículo representativo por cluster.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from ..models import FetchedItem

# Palabras vacías que no aportan a la similitud semántica
STOP_WORDS = {
    "a", "al", "ante", "bajo", "cabe", "con", "contra", "de", "desde", "durante",
    "en", "entre", "hacia", "hasta", "mediante", "para", "por", "según", "sin",
    "so", "sobre", "tras", "versus", "vía", "y", "e", "ni", "o", "u", "que",
    "el", "la", "lo", "los", "las", "un", "una", "unos", "unas", "del", "se", "su", "sus", "le", "les", "me", "te", "nos", "os", "mi", "tu", "nuestro",
    "vuestro", "suyo", "este", "esta", "estos", "estas", "ese", "esa", "esos",
    "esas", "aquel", "aquella", "aquellos", "aquellas", "cual", "cuales", "quien", "quienes", "cuando", "donde", "como", "porque", "si", "sí", "no",
    "también", "más", "menos", "muy", "mucho", "poco", "todo", "toda", "todos",
    "todas", "otro", "otra", "otros", "otras", "mismo", "misma", "mismos",
    "mismas", "tal", "tales", "tanto", "tanta", "tantos", "tantas", "nuevo",
    "nueva", "nuevos", "nuevas", "gran", "grande", "grandes", "buen",
    "buena", "buenos", "buenas", "mal", "mala", "malos", "malas", "primer",
    "primera", "primeros", "primeras", "último", "última", "últimos", "últimas"
}

# Palabras clave que indican el tipo de noticia (peso alto para clustering)
EVENT_KEYWORDS = {
    "anuncio", "anunciado", "anuncia", "anuncian",
    "lanzamiento", "lanzan", "release", "released",
    "llegada", "llega", "llegará",
    "confirmado", "confirma", "confirman", "confirmación",
    "revelado", "revela", "revelan", "revelación",
    "filtrado", "filtra", "filtran", "filtración", "leak", "leaks",
    "retrasado", "retrasa", "retrasan", "retraso", "delay", "delayed",
    "cancelado", "cancela", "cancelan", "cancelación",
    "beta", "demo", "acceso anticipado", "early access",
    "parche", "patch", "actualización", "update", "actualizan",
    "dlc", "expansión", "expansion", "contenido",
    "evento", "temporada", "season",
    "tráiler", "trailer", "gameplay", "imagenes", "capturas",
    "entrevista", "declaraciones", "dice", "dijo", "comenta",
    "respuesta", "responde", "responden", "rumor", "rumores", "especulación",
    "precio", "preorden", "preorder", "reserva",
    "fecha", "cuando", "sale", "saldrá",
}

# Palabras que indican ruido/ruido en el título
NOISE_WORDS = {
    "opinión", "opinion", "análisis", "analisis", "review", "reseña",
    "impresiones", "impresion", "probamos", "probado", "manos a",
    "guía", "guia", "guías", "guias", "trucos", "tips", "consejos",
    "mejores", "peores", "ranking", "top", "lista", "comparativa",
    "versus", "vs", "comparación", "comparacion",
}


def extract_keywords(text: str | None, max_keywords: int = 10) -> set[str]:
    """Extrae palabras clave relevantes de un texto (título + body)."""
    if not text:
        return set()

    # Normalizar: lowercase, quitar puntuación, split
    words = re.findall(r"[a-záéíóúñü0-9]+", text.lower())

    # Filtrar stop words, ruido, y palabras muy cortas
    keywords = {
        w for w in words
        if len(w) > 2
        and w not in STOP_WORDS
        and w not in NOISE_WORDS
    }

    # Priorizar palabras de evento
    event_words = {w for w in keywords if w in EVENT_KEYWORDS}
    other_words = keywords - event_words

    # Combinar: primero eventos, luego otros
    result = list(event_words) + list(other_words)
    return set(result[:max_keywords])


def normalize_title(text: str) -> str:
    """Normaliza un título para comparación."""
    if not text:
        return ""
    # Lowercase, quitar acentos aproximados, quitar puntuación
    text = text.lower()
    # Reemplazos comunes
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n",
        "“": '"', "”": '"', "'": "", "’": "", "‘": "", "–": "-", "—": "-",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Solo alfanumérico y espacios
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Colapsar espacios
    text = re.sub(r"\s+", " ", text).strip()
    return text


def jaccard_similarity(set1: set[str], set2: set[str]) -> float:
    """Calcula similitud de Jaccard entre dos conjuntos."""
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union


def word_overlap_similarity(text1: str, text2: str) -> float:
    """Similitud por overlap de palabras normalizadas."""
    words1 = set(normalize_title(text1).split())
    words2 = set(normalize_title(text2).split())
    return jaccard_similarity(words1, words2)


def extract_entities(title: str, body: str) -> set[str]:
    """Extrae entidades clave: nombres de juegos, personajes, eventos."""
    entities = set()
    text = f"{title} {body}".lower()

    # Patrones comunes de entidades en videojuegos
    # Números romanos y números de versión
    entities.update(re.findall(r"\b(v?\d+(\.\d+)?)\b", text))
    # Siglas comunes
    entities.update(re.findall(r"\b[A-Z]{2,5}\b", text.upper()))
    # Palabras capitalizadas (posibles nombres propios)
    entities.update(re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b", title))

    return entities


@dataclass(frozen=True, slots=True)
class StoryCluster:
    """Representa un cluster de artículos que cubren la misma historia."""
    items: list[FetchedItem]
    game: str
    representative: FetchedItem
    story_id: str
    keywords: frozenset[str]
    time_range: tuple[datetime, datetime]
    sources: frozenset[str]

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def sources_list(self) -> list[str]:
        return sorted(self.sources)

    @property
    def date_range_str(self) -> str:
        start, end = self.time_range
        if start.date() == end.date():
            return start.strftime("%Y-%m-%d")
        return f"{start.strftime('%Y-%m-%d')} a {end.strftime('%Y-%m-%d')}"


def compute_story_signature(item: FetchedItem) -> dict:
    """Genera una firma de historia para un artículo."""
    body = item.body_text or ""
    keywords = extract_keywords(f"{item.title} {body}")
    entities = extract_entities(item.title, body)
    game = item.game or ""

    return {
        "game": game,
        "keywords": frozenset(keywords),
        "entities": frozenset(entities),
        "title_words": normalize_title(item.title),
    }


def items_are_same_story(item1: FetchedItem, item2: FetchedItem, time_window_hours: int = 48) -> bool:
    """Determina si dos artículos pertenecen a la misma historia."""
    # Capa 0: URL exacta
    if item1.url == item2.url:
        return True

    # Deben ser del mismo juego
    if item1.game != item2.game:
        return False

    # Ventana temporal
    time_diff = abs((item1.published_at - item2.published_at).total_seconds() / 3600)
    if time_diff > time_window_hours:
        return False

    # Firmas
    sig1 = compute_story_signature(item1)
    sig2 = compute_story_signature(item2)

    # Similitud de palabras clave (peso alto)
    kw_sim = jaccard_similarity(sig1["keywords"], sig2["keywords"])
    if kw_sim >= 0.4:
        return True

    # Similitud de entidades
    ent_sim = jaccard_similarity(sig1["entities"], sig2["entities"])
    if ent_sim >= 0.5:
        return True

    # Similitud de título (Jaccard de palabras)
    title_sim = word_overlap_similarity(sig1["title_words"], sig2["title_words"])
    if title_sim >= 0.5:
        return True

    # Similitud combinada
    combined = (kw_sim * 0.5 + ent_sim * 0.3 + title_sim * 0.2)
    return combined >= 0.45


def cluster_items(items: list[FetchedItem], time_window_hours: int = 48) -> list[StoryCluster]:
    """Agrupa items en clusters de historia usando clustering aglomerativo simple."""
    if not items:
        return []

    # Ordenar por fecha (más recientes primero)
    sorted_items = sorted(items, key=lambda x: x.published_at, reverse=True)

    clusters: list[StoryCluster] = []
    unclustered = list(sorted_items)

    while unclustered:
        # Tomar el primer item no agrupado como semilla
        seed = unclustered.pop(0)
        cluster_items = [seed]
        to_check = list(unclustered)

        for item in to_check:
            if items_are_same_story(seed, item):
                cluster_items.append(item)
                unclustered.remove(item)

        # Seleccionar representante: el más reciente con imagen, o el más reciente
        representative = select_representative(cluster_items)

        # Calcular firma del cluster
        all_keywords = set()
        all_sources = set()
        times = []
        for item in cluster_items:
            kw = extract_keywords(f"{item.title} {item.body_text or ''}")
            all_keywords.update(kw)
            all_sources.add(item.source.name)
            times.append(item.published_at)

        cluster = StoryCluster(
            items=cluster_items,
            game=cluster_items[0].game or "",
            representative=representative,
            story_id=f"{cluster_items[0].game or 'unknown'}_{cluster_items[0].published_at.strftime('%Y%m%d_%H%M')}_{hash(cluster_items[0].url) % 10000}",
            keywords=frozenset(all_keywords),
            time_range=(min(times), max(times)),
            sources=frozenset(all_sources),
        )
        clusters.append(cluster)

    return clusters


def select_representative(items: list[FetchedItem]) -> FetchedItem:
    """Selecciona el artículo representativo del cluster.

    Prioridad:
    1. Más reciente con imagen
    2. Más reciente
    3. Mayor relevancia (si disponible)
    """
    # Priorizar los que tienen imagen
    with_image = [i for i in items if i.image_url]
    if with_image:
        return max(with_image, key=lambda x: x.published_at)

    # Si no hay imágenes, el más reciente
    return max(items, key=lambda x: x.published_at)


def cluster_and_select_representatives(
    items: list[FetchedItem],
    time_window_hours: int = 48
) -> list[FetchedItem]:
    """Función de conveniencia: clusteriza y devuelve solo los representantes."""
    clusters = cluster_items(items, time_window_hours)
    return [cluster.representative for cluster in clusters]