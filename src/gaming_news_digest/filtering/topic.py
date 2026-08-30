"""Filtro temático estricto: ¿es este artículo realmente sobre videojuegos?

Se aplica a las noticias de medios (RSS) ANTES del pre-ranking/IA. Su objetivo
es de precisión: preferimos descartar un artículo dudoso antes que publicar
películas, series, cómics o cultura que un medio como Polygon o IGN publica de
forma tangencial. El dominio de la fuente NO basta: cada artículo debe
demostrar individualmente que pertenece al ámbito de los videojuegos.

La decisión combina, por orden de prioridad:
A) Categorías/secciones/tags del propio feed: las incompatibles descartan; las
   "blandas" restan; las gaming NO aceptan por sí solas, actúan como señal de
   CONTEXTO (peso 1) que no puede compensar una señal negativa de texto.
B) Señales de texto en título + URL (+ cuerpo como apoyo), con señales
   POSITIVAS fuertes/débiles y NEGATIVAS fuertes/débiles, más la evidencia de
   que el artículo menciona un juego real (título conocido o rescatado por
   ancla), incluso en comparación ("isn't Elden Ring", "Hades-esque").
Modelo: pos_score (peso 2 por señal fuerte) frente a neg_score; la mención de
un juego real suma. Una negativa fuerte no se anula con contexto de feed.
El ancla: si dudamos de que sea videojuegos, se descarta (precisión > recall).
"""

from __future__ import annotations

import re

from gaming_news_digest.filtering.matcher import (
    _GENERIC_NAME_TOKENS,
    _LEADING_NOISE,
    _NON_GAME_ENTITIES,
    _detect_known_title_any,
    _detect_via_anchor,
    _normalize,
)

# ---------------------------------------------------------------------------
# Señales POSITIVAS de texto (título/cuerpo/URL)
# ---------------------------------------------------------------------------

# Señales FUERTES (peso 2): casi exclusivas de videojuegos. Incluyen géneros,
# mecánicas, plataformas, tiendas, editoriales y términos puramente gaming.
_STRONG_POSITIVE: frozenset[str] = frozenset((
    # Términos gaming inequívocos
    "gameplay", "video game", "video games", "videogame", "videogames",
    "gaming", "gamer", "gamers", "esports", "e-sports",
    # Plataformas/ecosistemas
    "steam", "steam deck", "playstation", "ps5", "ps4", "ps3", "psp",
    "ps vita", "xbox", "game boy", "gamecube", "wii", "wii u", "nintendo",
    "nintendo switch", "console", "consoles", "handheld", "game pass",
    "gamepad", "ps store", "playstation store",
    # Términos de ciclo de vida
    "dlc", "battle pass", "season pass", "early access", "game of the year",
    "goty", "crossplay", "cross-play", "microtransaction", "speedrun",
    "walkthrough", "console exclusive", "console port",
    # Géneros propios de videojuegos
    "rpg", "jrpg", "fps", "mmo", "mmorpg", "battle royale", "metroidvania",
    "soulslike", "roguelike", "roguelite", "survival horror",
    "first-person shooter", "third-person shooter", "open-world",
    "platformer", "tower defense", "shooter",
    # Editoriales/estudios (emitir noticia sobre publicador fuerte → gaming)
    "activision", "blizzard", "bethesda", "ubisoft", "rockstar", "capcom",
    "konami", "sega", "square enix", "from software", "valve", "riot",
    "epic games", "cd projekt", "paradox", "naughty dog", "insomniac",
    "guerrilla", "nintendo", "bandai", "hoyoverse", "total war",
))

# Señales DÉBILES (peso 1): también aparecen en cine/TV, necesitan apoyarse.
_WEAK_POSITIVE: frozenset[str] = frozenset((
    "trailer", "trailers", "update", "updates", "updated", "patch", "patches",
    "beta", "alpha", "demo", "preview", "previews", "remaster", "remasters",
    "remake", "remakes", "co-op", "coop", "cooperative", "multiplayer",
    "singleplayer", "launch", "released", "release", "release date",
    "announced", "announcement", "announces", "reveals", "revealed",
    # Señales de EXPERIENCIA de juego (solo los videojuegos se "juegan")
    "playing", "played", "playthrough", "adventure", "adventures",
    "tráiler", "tráilers", "parche", "parches", "actualización",
    "jugabilidad", "juego", "juegos", "videojuego", "videojuegos",
))

# ---------------------------------------------------------------------------
# Señales NEGATIVAS de texto (título/URL)
# ---------------------------------------------------------------------------

# Señales NEGATIVAS FUERTES (peso 2): temática claramente no-gaming.
_STRONG_NEGATIVE: frozenset[str] = frozenset((
    # Servicios de streaming / cine
    "netflix", "hbo", "hbo max", "disney+", "disney", "prime video",
    "apple tv", "apple tv+", "hulu", "paramount+", "peacock",
    "movie", "movies", "film", "films", "cinema", "box office",
    "film festival", "theatrical", "television",
    # Industria del espectáculo
    "actor", "actress", "actors", "actresses", "director", "directors",
    "directed", "hollywood", "oscars", "oscar", "emmys", "academy award",
    "celebrity", "celebrities", "celebs",
    # Cómics/novelas/música
    "comic", "comics", "graphic novel", "manga", "anime",
    "novel", "novels", "book", "books", "author", "bestseller",
    "musician", "musicians", "singer", "singers", "album", "concerts",
    # Merchandising físico (figuras, ediciones coleccionistas no-gaming)
    "statues", "statue", "figurines", "figurine",
    "merch", "merchandise", "souvenirs", "souvenir",
))

# Señales NEGATIVAS DÉBILES (peso 1): pueden aparecer en contexto gaming.
_WEAK_NEGATIVE: frozenset[str] = frozenset((
    "series", "show", "streaming", "episode", "episodes", "cartoon",
    "documentary", "film adaptation", "live-action", "live action", "tv",
))

# Frases que contienen "game(s)" pero NO son videojuegos (suprimir la señal).
_SUPPRESS_PHRASES: tuple[str, ...] = (
    "game of thrones", "hunger games", "squid game", "squid games",
    "game show", "gameshow", "game night",
)

# ---------------------------------------------------------------------------
# Categorías del feed (señal A)
# ---------------------------------------------------------------------------

# Incompatibles de forma inequívoca: un artículo marcado así en el feed se
# descarta directamente, venga lo que venga en el texto.
_HARD_NEG_FEED: frozenset[str] = frozenset((
    "movies", "movie", "film", "films", "television", "tvs", "tv shows",
    "tv & film", "film & television", "film and television", "comics",
    "comic",  "manga", "anime", "music", "books", "novels", "celebrity",
    "sports", "politics", "business", "lifestyle", "food", "travel",
    "health", "fashion", "science",
))

# Incompatibles "blandas": solo descartan si falta señal positiva de texto.
_SOFT_NEG_FEED: frozenset[str] = frozenset((
    "entertainment", "culture", "pop culture", "features",
))

# Categorías inequívocamente gaming: ya NO aceptan solas (un feed gaming
# publica trailers de cine y mercancía). Actúan como señal de CONTEXTO
# (peso 1) que apoya a las señales de texto, igual que una señal débil.
_POS_FEED: frozenset[str] = frozenset((
    "video games", "video game", "video-games", "gaming", "games", "game",
    "videojuegos", "videojuego", "juegos", "pc gaming", "playstation",
    "xbox", "nintendo", "switch", "pc", "steam",
))

# ---------------------------------------------------------------------------
# Implementación
# ---------------------------------------------------------------------------

_COMPILED_SUPPRESS: tuple[re.Pattern, ...] = (
    re.compile(rf"\b{re.escape(p)}\b") for p in _SUPPRESS_PHRASES
)

# Palabras que, solas, NUNCA demuestran que el candidato a "juego" lo sea de
# verdad (artículos, genéricos de portada, términos de evento, audiencia,
# hardware, estudios, géneros/descriptores débiles...). Se usan para vigilar
# el rescate por ancla: un candidato compuesto SOLO por ruido ("A brand",
# "New trailer") no confirma temática gaming.
_TOPIC_NOISE_WORDS: frozenset[str] = frozenset(
    _GENERIC_NAME_TOKENS
    | _NON_GAME_ENTITIES
    | _LEADING_NOISE
    | _WEAK_POSITIVE
    | {
        "a", "an", "brand", "brands", "newest", "soon", "today", "tonight",
        "week", "month", "episode", "director", "show",
    }
)


def _clean(text: str) -> str:
    return _normalize(text)


def _mask_suppressed(text: str) -> str:
    """Neutraliza frases tipo "Game of Thrones" para que "game" no puntúe."""
    masked = text
    for pattern in _COMPILED_SUPPRESS:
        masked = pattern.sub(" ", masked)
    return masked


def _matched(signals: frozenset[str], text: str) -> set[str]:
    return {
        signal
        for signal in signals
        if re.search(rf"\b{re.escape(signal)}s?\b", text)
    }


def _anchor_rescue(title_n: str) -> str | None:
    """Rescate por ancla: detecta un posible nombre de juego en el titular,
    pero lo rechaza si está compuesto SOLO de ruido ("A brand", "New trailer")
    o es un candidato-chorizo poco fiable ("Ridley Scott Says Alien Romulus Was
    OK So He s Returning..."): más de 5 palabras no es un nombre, es prosa.
    Cosa que la heurística del matcher no distingue (no es su papel).
    """
    cand = _detect_via_anchor(title_n)
    if not cand:
        return None
    if len(cand.split()) > 5:
        return None
    if any(t.lower() not in _TOPIC_NOISE_WORDS for t in cand.split()):
        return cand
    return None


def _feed_signals(categories: tuple[str, ...]) -> tuple[bool, bool, bool]:
    """Señales del feed: (hard_neg, soft_neg, pos). Ninguna es definitiva por
    sí sola: hard_neg descarta (el feed lo afirma inequívocamente), pos solo
    otorga contexto de texto (+1)."""
    if not categories:
        return False, False, False
    clean_cats = {_clean(c) for c in categories}
    hard_neg = bool(clean_cats & _HARD_NEG_FEED)
    soft_neg = bool(clean_cats & _SOFT_NEG_FEED)
    pos = bool(clean_cats & _POS_FEED)
    return hard_neg, soft_neg, pos


def _text_verdict(
    title: str, body: str, url: str, *, feed_boost: int = 0
) -> tuple[bool, str]:
    """Decide con las señales de texto (título + URL + cuerpo de apoyo)."""
    title_n = _mask_suppressed(_clean(title))
    url_n = _clean(url)
    # Negativas SOLO de título+URL (el cuerpo de un artículo gaming puede
    # mencionar Netflix/cine de forma incidental y no debe anularlo).
    neg_text = f"{title_n} {url_n}"
    # Positivas de título+URL+cuerpo (recortado para no desbalancear).
    body_n = _mask_suppressed(_clean(body))[:400]
    pos_text = f"{title_n} {url_n} {body_n}"

    strong_pos = _matched(_STRONG_POSITIVE, pos_text)
    weak_pos = _matched(_WEAK_POSITIVE, pos_text)
    strong_neg = _matched(_STRONG_NEGATIVE, neg_text)
    weak_neg = _matched(_WEAK_NEGATIVE, neg_text)
    has_strong_neg = bool(strong_neg)

    # Evidencia de que se MENCIONA un juego real, aunque sea en comparación
    # ("isn't Elden Ring", "Hades-esque action" también son contenido gaming).
    # La versión INGUARDADA de la detección (sin filtro de contexto) se usa a
    # propósito: decidir la TEMÁTICA no es decidir el NOMBRE de la noticia.
    rescued_known = _detect_known_title_any(title_n)
    # - Rescate por ancla: solo cuenta si no hay negativas fuertes, porque es
    #   una heurística y un titular de cine puede "parecer" un juego
    #   ("...Cult Classic... coming to Netflix").
    rescued_anchor = _anchor_rescue(title_n) if not has_strong_neg else None

    pos_score = (
        len(strong_pos) * 2
        + len(weak_pos)
        + (2 if rescued_known else 0)
        + (2 if rescued_anchor else 0)
        + feed_boost
    )
    neg_score = len(strong_neg) * 2 + len(weak_neg)

    if neg_score > 0:
        if pos_score - neg_score >= 2:
            return True, "senal_positiva_supera_negativa"
        first_neg = next(iter(strong_neg or weak_neg), "")
        return False, f"senal_negativa:{first_neg}"
    if pos_score >= 2:
        if strong_pos:
            return True, "senal_positiva_fuerte"
        if rescued_known:
            return True, "juego_reconocible"
        if rescued_anchor:
            return True, "nombre_juego_detectado"
        if feed_boost:
            # feed gaming + una señal débil (un trailer genérico) sí basta
            return True, "feed_contexto_videojuegos"
        return True, "senal_positiva_doble"
    return False, "sin_senal_suficiente"


def classify_video_game_article(
    title: str,
    body: str = "",
    url: str = "",
    feed_categories: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """Clasifica un artículo como videojuego/No-videojuego.

    Devuelve (es_videojuego, motivo). Se ejecuta ANTES del matcher de nombres:
    un artículo puede ser de videojuegos sin mencionar ningún juego concreto
    ("Nintendo announces new hardware strategy" → True, name="Videojuegos") y
    un artículo de cine puede compartir franquicia con un juego ("The Last of
    Us HBO series…" → False) aunque el matcher reconocería el título.

    El feed nunca decide solo: una categoría gaming suma contexto (+1), una
    negativa fuerte de texto siempre gana y una categoría incompatibles
    descarta de forma inequívoca.
    """
    hard_neg_feed, soft_neg_feed, pos_feed = _feed_signals(tuple(feed_categories))
    if hard_neg_feed:
        return False, "feed_seccion_incompatible"
    # La categoría gaming aporta +1 al puntaje de positivas del texto; una
    # categoría "blanda" (entertainment/culture) no resta por sí sola (eso lo
    # hace una señal negativa de texto). El contexto de feed jamás compensa una
    # señal negativa de texto: se marca para que la resta sea simétrica abajo.
    feed_boost = 1 if (pos_feed and not soft_neg_feed) else 0
    return _text_verdict(title, body, url, feed_boost=feed_boost)


def is_video_game_article(
    title: str,
    body: str = "",
    url: str = "",
    feed_categories: tuple[str, ...] = (),
) -> bool:
    """True si el artículo es claramente de videojuegos; False si es dudoso."""
    ok, _reason = classify_video_game_article(title, body, url, feed_categories)
    return ok