"""Story clustering for semantic deduplication at story level.

Groups articles covering the same event/happening, not just the same game.
Uses a deterministic, lightweight approach without heavy dependencies:

1. Exact URL (layer 0 - exact deduplication)
2. Game + key title entities (layer 1)
3. Relevant keyword similarity (layer 2)
4. Title similarity (Jaccard/overlap) (layer 3)
4. Temporal window 24-48h (layer 4)

Result: StoryClusters with one representative article per cluster.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from ..models import FetchedItem

# English stop words that don't contribute to semantic similarity
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "from", "up", "about", "into", "through", "during", "before", "after", "above", "below", "between", "among", "around", "against", "along", "across", "behind", "beyond", "beneath", "beside", "despite", "except", "inside", "outside", "within", "without",
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
    "what", "which", "who", "whom", "this", "that", "these", "those", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "having", "do", "does", "did", "doing", "will", "would", "should", "could", "ought", "can", "may", "might", "must", "shall", "if", "because", "as", "until", "while", "down", "out", "off", "over", "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", "how", "all", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "s", "t", "just", "don", "now", "d", "ll", "m", "o", "re", "ve", "y", "ain", "aren", "couldn", "didn", "doesn", "hadn", "hasn", "haven", "isn", "ma", "mightn", "mustn", "needn", "shan", "shouldn", "wasn", "weren", "won", "wouldn",
}

# Keywords indicating event/news type (high weight for clustering)
EVENT_KEYWORDS = {
    "announcement", "announced", "announces", "announcing",
    "launch", "launches", "launching", "release", "released", "releases", "releasing",
    "arrival", "arrives", "arriving", "debut", "debuts",
    "confirmation", "confirmed", "confirms", "confirming",
    "reveal", "revealed", "reveals", "revealing", "leak", "leaks", "leaked", "leaking",
    "delay", "delayed", "delays", "delaying", "postponed", "postpones",
    "cancelled", "cancels", "cancellation",
    "beta", "demo", "early access", "early-access",
    "patch", "patches", "patched", "update", "updates", "updated",
    "dlc", "expansion", "content",
    "event", "season",
    "trailer", "trailers", "gameplay", "images", "screenshots", "screenshot",
    "interview", "statement", "said", "says", "comment", "comments",
    "response", "responds", "responded", "rumor", "rumors", "speculation",
    "price", "pricing", "preorder", "pre-order", "date", "when",
}

# Words indicating noise/non-news content in titles
NOISE_WORDS = {
    "opinion", "analysis", "review", "impressions", "impression", "hands-on", "played", "tested",
    "guide", "guides", "tips", "tricks", "advice", "strategy",
    "best", "worst", "ranking", "top", "list", "comparison", "roundup",
    "versus", "vs", "compare",
    "preview", "first look", "first impressions",
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


def jaccard_similarity(set1: set, set2: set) -> float:
    """Similitud de Jaccard entre dos conjuntos.

    Dos conjuntos VACÍOS significan "no hay información comparable", no
    "idénticos". Devolver 1.0 hacía que dos noticias sin keywords
    extraíbles (título en otro idioma, o solo palabras cortas) se
    declarasen la MISMA historia y una se perdiera.
    """
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


# Game name normalization map - maps variations to canonical form
GAME_ALIASES = {
    "grand theft auto": "gta",
    "gta": "gta",
    "call of duty": "cod",
    "cod": "cod",
    "red dead redemption": "rdr",
    "rdr": "rdr",
    "final fantasy": "ff",
    "ff": "ff",
    "the legend of zelda": "zelda",
    "zelda": "zelda",
    "elden ring": "eldenring",
    "eldenring": "eldenring",
    "baldur's gate": "bg",
    "baldurs gate": "bg",
    "bg3": "bg",
    "cyberpunk": "cyberpunk",
    "cp2077": "cyberpunk",
    "witcher": "witcher",
    "the witcher": "witcher",
    "assassin's creed": "ac",
    "assassins creed": "ac",
    "ac": "ac",
    "far cry": "farcry",
    "farcry": "farcry",
    "battlefield": "bf",
    "bf": "bf",
    "halo": "halo",
    "destiny": "destiny",
    "destiny2": "destiny2",
    "destiny 2": "destiny2",
    "minecraft": "minecraft",
    "roblox": "roblox",
    "fortnite": "fortnite",
    "apex legends": "apex",
    "apex": "apex",
    "overwatch": "overwatch",
    "ow": "overwatch",
    "valorant": "valorant",
    "league of legends": "lol",
    "lol": "lol",
    "dota": "dota",
    "dota2": "dota",
    "counter-strike": "cs",
    "counterstrike": "cs",
    "cs2": "cs",
    "csgo": "cs",
    "pubg": "pubg",
    "playerunknown": "pubg",
    "fifa": "fifa",
    "ea sports fc": "fifa",
    "ea fc": "fifa",
    "madden": "madden",
    "nba 2k": "nba2k",
    "nba2k": "nba2k",
    "elder scrolls": "tes",
    "skyrim": "tes",
    "fallout": "fallout",
    "mass effect": "me",
    "dragon age": "da",
    "dragonage": "da",
    "divinity": "dos",
    "divinity original sin": "dos",
    "xenoblade": "xenoblade",
    "xenogears": "xenogears",
    "chron trigger": "chronotrigger",
    "chronotrigger": "chronotrigger",
    "final fantasy vii": "ff7",
    "ff7": "ff7",
    "final fantasy xiv": "ff14",
    "ffxiv": "ff14",
    "ff14": "ff14",
    "kingdom hearts": "kh",
    "kh": "kh",
    "persona": "persona",
    "persona 5": "p5",
    "p5": "p5",
    "persona 3": "p3",
    "p3": "p3",
    "persona 4": "p4",
    "p4": "p4",
    "metroid": "metroid",
    "metroid prime": "metroidprime",
    "metroidprime": "metroidprime",
    "pikmin": "pikmin",
    "splatoon": "splatoon",
    "animal crossing": "ac",
    "new horizons": "ac",
    "starfield": "starfield",
    "baldur's gate 3": "bg3",
    "sea of thieves": "sot",
    "sot": "sot",
    "hell divers": "helldivers",
    "helldivers": "helldivers",
    "hell divers 2": "helldivers2",
    "helldivers 2": "helldivers2",
}

def normalize_game_name(game: str) -> str:
    """Normaliza un nombre de juego a su forma canónica.

    Los alias se comprueban de MÁS ESPECÍFICO a MÁS GENÉRICO y con límites
    de palabra. Antes se iteraba el dict en orden de inserción y se hacía
    ``alias in normalized`` a pelo: "final fantasy vii" casaba con
    "final fantasy" (ff) antes que con "ff7", y un alias corto como "ac"
    o "cs" saltaba dentro de palabras cualesquiera.
    """
    if not game:
        return ""
    normalized = game.lower().strip()
    best: tuple[int, str] | None = None
    for alias, canonical in GAME_ALIASES.items():
        if not re.search(rf"\b{re.escape(alias)}\b", normalized):
            continue
        # A igualdad de coincidencia, gana el alias más largo (el más
        # específico): "final fantasy vii" debe ganar a "final fantasy".
        if best is None or len(alias) > best[0]:
            best = (len(alias), canonical)
    return best[1] if best else normalized


#: Palabras vacías en inglés que NO deben contar como "entidad" aunque
#: aparezcan en mayúsculas. Sin esta lista, el .upper() de abajo convertía
#: THE/AND/NEW/THIS/WEEK en entidades y la similitud de entidades la
#: dominaba, fusionando noticias distintas del mismo juego.
_ENTITY_STOPWORDS = frozenset({
    "the", "and", "for", "with", "new", "this", "that", "you", "not", "but",
    "are", "was", "were", "has", "have", "had", "its", "his", "her", "our",
    "out", "off", "own", "too", "can", "will", "all", "any", "how", "why",
    "now", "one", "two", "get", "got", "say", "says", "see", "seen",
    "day", "week", "year", "first", "last", "next", "more", "most", "much",
    "adds", "added", "adding", "gets", "makes", "make", "made",
    "what", "when", "where", "who", "into", "onto", "from", "just", "like",
    "may", "could", "would", "should", "must", "than", "then", "them",
    "they", "some", "both", "each", "other", "been", "being", "over",
})


def extract_entities(title: str, body: str, game: str | None = None) -> set[str]:
    """Extrae entidades clave: personajes, lugares, versiones.

    Deliberadamente NO incluye el nombre canónico del juego: ``items_are_same_story``
    ya exige que ambos items sean del mismo juego, así que el nombre del juego
    estaba en ambos sets y ``ent_sim`` valía ~1.0 para CUALQUIER par del mismo
    juego. Eso convertía la similitud de entidades en ruido: no distinguía dos
    noticias distintas porque ambas contenían "Halo Infinite".

    Además se corrigieron dos fallos reales de la versión anterior:
    (a) ``re.findall`` con grupo de captura devolvía TUPLAS, no strings, así que
    el set se llenaba de ('1.16', '.16'); (b) el ``.upper()`` previo al
    ``findall`` de acrónimos convertía cualquier palabra corriente en entidad.
    """
    entities: set[str] = set()
    text = f"{title} {body}"

    # Números de versión (v1.0, 2.0, 3b…). SIN grupo de captura.
    entities.update(re.findall(r"\b(?:v\d+(?:\.\d+)*|\d+(?:\.\d+)*[a-z]?)\b", text.lower()))

    # Acrónimos: mayúsculas YA presentes en el original (sin .upper() global).
    entities.update(re.findall(r"\b[A-Z]{2,5}\b", text))

    # Nombres propios del titular, sin palabras vacías y sin los que ya son
    # parte del nombre del juego (redundantes con la puerta de juego).
    # Se comparan contra el NOMBRE CRUDO y contra el canónico: con solo el
    # canónico, "Halo Infinite" (canónico "halo") no se excluía y quedaba
    # como única entidad, dejando ent_sim = 1.0 para cualquier par del juego.
    game_words: set[str] = set()
    if game:
        game_words |= set(re.sub(r"[^a-z0-9\s]", " ", game.lower()).split())
        game_words |= set(normalize_game_name(game).split())
    for word in re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b", title):
        if word.lower() in _ENTITY_STOPWORDS:
            continue
        if set(word.lower().split()) <= game_words:
            continue
        entities.add(word)

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
    entities = extract_entities(item.title, body, item.game)
    game = item.game or ""

    return {
        "game": game,
        "keywords": frozenset(keywords),
        "entities": frozenset(entities),
        "title_words": normalize_title(item.title),
    }


#: Gamas de similitud para decidir si dos artículos cubren la misma historia.
#: Calibradas contra pares reales: duplicados legítimos puntúan 0.28-0.42 y
#: noticias distintas 0.19-0.50, es decir, AMBOS conjuntos se solapaban con
#: el antiguo corte combinado `>= 0.2` (que fusionaba de todo y, al conservar
#: un solo representante, hacía desaparecer noticias del digest).
#:
#: La regla es ahora CONJUNTIVA: una señal fuerte de texto basta; una señal
#: débil (entidades) necesita corroboración del título. Sin esta exigencia,
#: `ent_sim` vale ~1.0 para cualquier par del mismo juego, porque el nombre
#: canónico estaba dentro del set de entidades y ya lo comprueba la puerta de
#: juego: no aportaba ninguna información discriminante.
KW_SIMILARITY_STRONG = 0.40
TITLE_SIMILARITY_STRONG = 0.45
ENTITY_SIMILARITY_WEAK = 0.50
TITLE_SIMILARITY_CORROBORATION = 0.25


def items_are_same_story(item1: FetchedItem, item2: FetchedItem, time_window_hours: int = 48) -> bool:
    """Determina si dos artículos pertenecen a la misma historia.

    Fusión EXIGE señal: se fusionan solo con coincidencia fuerte de
    palabras clave o de título, o con entidades coincidentes Y título
    corroborando. Ante la duda se conserva el artículo como noticia propia:
    publicarlo de más es un problema menor que perderlo.
    """
    # Capa 0: URL exacta
    if item1.url == item2.url:
        return True

    # Deben ser del mismo juego (comparación normalizada: "Elden Ring" y
    # "elden ring" son el mismo juego y antes no se agrupaban nunca)
    if normalize_game_name(item1.game or "") != normalize_game_name(item2.game or ""):
        return False

    # Ventana temporal
    time_diff = abs((item1.published_at - item2.published_at).total_seconds() / 3600)
    if time_diff > time_window_hours:
        return False

    sig1 = compute_story_signature(item1)
    sig2 = compute_story_signature(item2)

    kw_sim = jaccard_similarity(sig1["keywords"], sig2["keywords"])
    if kw_sim >= KW_SIMILARITY_STRONG:
        return True

    title_sim = word_overlap_similarity(sig1["title_words"], sig2["title_words"])
    if title_sim >= TITLE_SIMILARITY_STRONG:
        return True

    ent_sim = jaccard_similarity(sig1["entities"], sig2["entities"])
    return (
        ent_sim >= ENTITY_SIMILARITY_WEAK
        and title_sim >= TITLE_SIMILARITY_CORROBORATION
    )


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