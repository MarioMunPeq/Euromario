"""Filtro temático estricto: ¿es este artículo realmente sobre videojuegos?

Se aplica a las noticias de medios (RSS) ANTES del pre-ranking/IA. Su objetivo
es de precisión: preferimos descartar un artículo dudoso antes que publicar
películas, series, cómics o cultura que un medio como Polygon o IGN publica de
forma tangencial. El dominio de la fuente NO basta: cada artículo debe
demostrar individualmente que pertenece al ámbito de los videojuegos.

La decisión combina, por orden de prioridad:
A) Categorías/secciones/tags del propio feed.
B) Señales de texto en título + URL (+ cuerpo como apoyo), con señales
   POSITIVAS fuertes/débiles y NEGATIVAS fuertes/débiles.
El ancla: si dudamos de que sea videojuegos, se descarta (precisión > recall).
"""

from __future__ import annotations

import re

from gaming_news_digest.filtering.matcher import (
    _GENERIC_NAME_TOKENS,
    _LEADING_NOISE,
    _NON_GAME_ENTITIES,
    _detect_via_anchor,
    _detect_via_known_title,
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
    "guerrilla", "nintendo", "bandai",
))

# Señales DÉBILES (peso 1): también aparecen en cine/TV, necesitan apoyarse.
_WEAK_POSITIVE: frozenset[str] = frozenset((
    "trailer", "trailers", "update", "updates", "updated", "patch", "patches",
    "beta", "alpha", "demo", "preview", "previews", "remaster", "remasters",
    "remake", "remakes", "co-op", "coop", "cooperative", "multiplayer",
    "singleplayer", "launch", "released", "release", "release date",
    "announced", "announcement", "announces", "reveals", "revealed",
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

# Categorías inequívocamente gaming: aceptar directamente.
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
    pero lo rechaza si está compuesto SOLO de ruido ("A brand", "New trailer"),
    cosa que la heurística de ancla del matcher no distingue (no es su papel).
    """
    cand = _detect_via_anchor(title_n)
    if not cand:
        return None
    if any(t.lower() not in _TOPIC_NOISE_WORDS for t in cand.split()):
        return cand
    return None


def _feed_verdict(categories: tuple[str, ...]) -> tuple[bool | None, str]:
    """Clasifica usando solo las categorías del feed. None = sin información."""
    if not categories:
        return None, ""
    clean_cats = {_clean(c) for c in categories}
    hard_neg = clean_cats & _HARD_NEG_FEED
    soft_neg = clean_cats & _SOFT_NEG_FEED
    pos = clean_cats & _POS_FEED
    if hard_neg:
        return False, "feed_seccion_incompatible"
    if pos and not soft_neg:
        return True, "feed_seccion_videojuegos"
    if soft_neg and not pos:
        # Señal blanda: la decide el texto; marcamos para no guardar doble.
        return None, "feed_seccion_blanda"
    return None, ""


def _text_verdict(title: str, body: str, url: str) -> tuple[bool, str]:
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
    has_weak_neg = bool(weak_neg)

    # Rescate por NOMBRE de juego:
    # - Lista curada (juego conocido): señal fuerte pero no anula una
    #   negativa fuerte (p. ej. "The Last of Us HBO series..." no es gaming).
    # - Detectado por ancla: solo cuenta si no hay negativas fuertes, porque
    #   es una heurística y un titular de cine puede "parecer" un juego
    #   ("Robert Downey Jr's 98-Minute Cult Classic... coming to Netflix").
    # Ambos rescates se calculan sobre el título con frases suprimidas.
    rescued_known = _detect_via_known_title(title_n)
    rescued_anchor = _anchor_rescue(title_n) if not has_strong_neg else None

    if has_strong_neg or has_weak_neg:
        pos_weight = (
            len(strong_pos) * 2
            + len(weak_pos) * 1
            + (2 if rescued_known else 0)
            + (2 if rescued_anchor else 0)
        )
        neg_weight = len(strong_neg) * 2 + len(weak_neg)
        if pos_weight - neg_weight >= 2:
            return True, "senal_positiva_supera_negativa"
        first_neg = next(iter(strong_neg or weak_neg), "")
        return False, f"senal_negativa:{first_neg}"
    if strong_pos or rescued_known or rescued_anchor:
        if strong_pos:
            return True, "senal_positiva_fuerte"
        if rescued_known:
            return True, "juego_reconocible"
        return True, "nombre_juego_detectado"
    if len(weak_pos) >= 2:
        return True, "senal_positiva_doble"
    return False, "sin_senal_suficiente"


def classify_video_game_article(
    title: str,
    body: str = "",
    url: str = "",
    feed_categories: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """Clasifica un artículo como videojuego/No-videojuego.

    Devuelve (es_videojuego, motivo). Se ejecuta ANTES del game-name: un
    artículo puede ser de videojuegos sin mencionar ningún juego concreto
    ("Nintendo announces new hardware strategy" → True, game="Videojuegos").
    """
    verdict, reason = _feed_verdict(tuple(feed_categories))
    if verdict is not None:
        return verdict, reason
    return _text_verdict(title, body, url)


def is_video_game_article(
    title: str,
    body: str = "",
    url: str = "",
    feed_categories: tuple[str, ...] = (),
) -> bool:
    """True si el artículo es claramente de videojuegos; False si es dudoso."""
    ok, _reason = classify_video_game_article(title, body, url, feed_categories)
    return ok