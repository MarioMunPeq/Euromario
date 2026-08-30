"""Matcher robusto de nombres de juegos para el filtro de inclusión/exclusión.

Principios:
- Límites de palabra (\\b) → evita matches por subcadena casual ("GTA" no
  matchea "OGTAX").
- Aliases y variantes en config (romanos, abreviaturas, números).
- Insensible a mayúsculas/acentos (NFKC + lowercase).
- Exclusión = "poison pill": cualquier mención descarta el artículo completo.
- Inclusión exige "tema principal": título O ≥2 menciones en body.
"""

import re
import unicodedata
from dataclasses import dataclass

from ..config import GameRule


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    """Regla de juego con patrón ya compilado."""

    name: str
    pattern: re.Pattern


def _normalize(text: str) -> str:
    """NFD + quita diacríticos → lowercase → solo alfanuméricos y espacios."""
    if not text:
        return ""
    # NFD descompone acentos (é → e + ́), luego filtra marcas combinatorias (Mn)
    nfd = unicodedata.normalize("NFD", text)
    no_diacritics = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    lowered = no_diacritics.lower()
    return re.sub(r"[^a-z0-9]+", " ", lowered)


def _compile_pattern(rule: GameRule) -> re.Pattern:
    """Construye un regex con word boundaries para nombre + aliases."""
    parts = [rule.name] + list(rule.aliases)
    # normaliza cada parte igual que el texto
    norm_parts = [_normalize(p) for p in parts if p]
    # elimina duplicados preservando orden
    seen = set()
    uniq = []
    for p in norm_parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    # word boundary alrededor de cada alternativa
    alternatives = "|".join(re.escape(p) for p in uniq)
    return re.compile(rf"\b(?:{alternatives})\b")


class GameMatcher:
    """Filtro de inclusión/exclusión con reglas de prioridad."""

    def __init__(self, include_rules: list[GameRule], exclude_rules: list[GameRule]):
        self.include = [(_compile_pattern(r), r.name) for r in include_rules]
        self.exclude = [_compile_pattern(r) for r in exclude_rules]

    def is_main_topic(self, title: str, body: str, pattern: re.Pattern) -> bool:
        """Inclusión exige: título O ≥2 menciones en body.

        La mención en el título solo cuenta si actúa como SUJETO y no como
        comparación/referencia ("GTA 6? No thanks…", "unlike X"), de modo que
        un juego configurado mencionado solo como contexto NO roba la noticia.
        """
        norm_title = _normalize(title)
        m = pattern.search(norm_title)
        if m:
            # Extiende la mención con secuencias numéricas inmediatas
            # ("GTA 6", "Persona 5") para evaluar la referencia sobre el
            # nombre completo en lugar del alias corto.
            rest = re.split(r"\s+", norm_title[m.end():].strip())
            ext = [t for t in rest if re.fullmatch(r"\d+(?:\.\d+)?", t)][:2]
            mention = " ".join([m.group(0)] + ext).strip()
            if not _is_reference(title, mention):
                return True
        return len(pattern.findall(_normalize(body))) >= 2

    def is_mentioned(self, title: str, body: str, pattern: re.Pattern) -> bool:
        """Exclusión: cualquier mención (título + body)."""
        combined = _normalize(title + " " + body)
        return pattern.search(combined) is not None

    def is_excluded(self, title: str, body: str) -> bool:
        """True si algún juego de exclusión se menciona una sola vez (poison pill)."""
        return any(self.is_mentioned(title, body, pat) for pat in self.exclude)

    def match(self, title: str, body: str) -> tuple[bool, str | None]:
        """
        Devuelve (aceptada, juego_canonico).

        - Exclusión GLOBAL: cualquier mención de juego excluido → descarta TODO.
        - Inclusión: primer juego incluido que sea "tema principal".
        """
        # 1. Exclusión GLOBAL (poison pill)
        for excl_pat in self.exclude:
            if self.is_mentioned(title, body, excl_pat):
                return (False, None)

        # 2. Inclusión: primer juego con tema principal
        for inc_pat, name in self.include:
            if self.is_main_topic(title, body, inc_pat):
                return (True, name)

        return (False, None)

    def context_matches(self, title: str) -> list[str]:
        """Nombres de juegos configurados que aparecen en ``title`` SOLO como
        comparación/referencia (para el diagnóstico del pipeline: "NO usar
        coincidencia contextual")."""
        refused: list[str] = []
        norm_title = _normalize(title)
        for inc_pat, name in self.include:
            m = inc_pat.search(norm_title)
            if not m:
                continue
            rest = re.split(r"\s+", norm_title[m.end():].strip())
            ext = [t for t in rest if re.fullmatch(r"\d+(?:\.\d+)?", t)][:2]
            mention = " ".join([m.group(0)] + ext).strip()
            if _is_reference(title, mention):
                refused.append(name)
        return refused


# ---------------------------------------------------------------------------
# Detección de juegos NO configurados (las noticias de cualquier juego entran)
# ---------------------------------------------------------------------------

# Palabras-ancla típicas de titulares de noticias: lo que va justo antes es el
# candidato a "nombre del juego/saga". (palabras en minúsculas, sin puntuación)
_EVENT_ANCHOR_WORDS = frozenset({
    "announce", "announces", "announced", "announcing",
    "reveal", "reveals", "revealed", "revealing",
    "tease", "teases", "teased", "teasing",
    "launch", "launches", "launching", "launched",
    "release", "releases", "releasing", "released",
    "return", "returns", "returning", "coming", "arrives", "arriving",
    "gets", "get", "getting",
    "patch", "patches", "updated", "updates", "update",
    "dlc", "expansion", "expands", "content", "roadmap",
    "trailer", "trailers", "teaser", "teasers", "gameplay", "showcase",
    "beta", "demo", "leak", "leaks", "leaked",
    "screenshot", "screenshots", "images", "price", "prices",
    "delays", "delayed", "delay",
    "confirms", "confirmed", "confirm", "officially", "finally",
    "available", "featuring", "introducing",
})

# Ruido inicial que se recorta del candidato detectado
_LEADING_NOISE = frozenset({
    "new", "official", "first", "next", "upcoming", "latest", "final",
    "finally", "the", "watch", "see", "big", "huge", "tiny", "here",
    "for", "in", "on", "at", "to", "is", "are", "has", "have",
    "everything", "every", "all", "this", "about",
})

# Tokens que NUNCA pueden formar un nombre de juego en un titular (adjetivos,
# palabras genéricas de portada, artículos, audiencia...). Si el candidato que
# precede a una palabra-ancla contiene alguno de estos, se abandona la
# detección: mejor `None` → `Videojuegos` que un falso positivo como "Modern"
# o "Update". Incluye la lista explícita del proyecto: News, Update, Trailer,
# Release, Modern, New, Latest, Game(s), Gaming, Players, Developer(s),
# Studio, Steam, PC, PlayStation, Xbox, etc.
_GENERIC_NAME_TOKENS = frozenset({
    "new", "modern", "big", "huge", "major", "great", "best", "worst", "top",
    "all", "more", "most", "latest", "first", "next", "upcoming", "official",
    "game", "games", "gaming", "news", "details", "everything", "everyone",
    "update", "updates", "updated", "patch", "patches", "dlc", "expansion",
    "version", "edition", "season", "year", "today", "tomorrow", "yesterday",
    "now", "here", "watch", "see", "reveal", "revealed", "trailer",
    "gameplay", "leak", "leaks", "leaked", "demo", "beta", "content",
    "roadmap", "price", "prices", "delay", "delayed", "delays",
    "the", "this", "that", "these", "those", "and", "or", "for", "with",
    "about", "from", "into", "after", "during", "before", "over",
    # La audiencia y la industria nunca son un juego
    "players", "player", "user", "users", "gamers", "gamer", "fans",
    "developers", "developer", "studios", "studio", "publishers", "publisher",
    "community", "audience", "industry", "sector", "business", "market",
    # Hardware / formato / contexto
    "pc", "console", "consoles", "hardware", "software", "platform",
    "platforms", "system", "systems", "feature", "features", "store",
    "storefront", "sales", "dlss", "mod", "mods", "vr",
})

# Entidades que NO son juegos pero aparecen mucho en titulares de la industria:
# compañías, plataformas, tiendas, tecnología, personas. Si el candidato de la
# heurística de ancla contiene alguno de estos tokens, se rechaza (→ None → la
# lista curada `_KNOWN_GAME_TITLES` puede rescatarlo si hay un juego real).
_NON_GAME_ENTITIES = frozenset({
    # Plataformas y tiendas
    "steam", "valve", "gog", "epic", "eac", "xbox", "playstation", "ps5",
    "ps4", "ps3", "psp", "psvita", "vita", "switch", "nintendo", "windows",
    "steamdeck", "oculus", "ios", "android", "metastore",
    # Compañías / estudios / editoras
    "sony", "microsoft", "nvidia", "amd", "intel", "apple", "google", "meta",
    "tencent", "amazon", "netflix", "activision", "blizzard", "riot",
    "ubisoft", "bethesda", "capcom", "konami", "sega", "atari", "namco",
    "bandai", "square", "electronic", "rockstar", "naughty", "insomniac",
    "guerrilla", "project", "projekt", "cdprojekt", "remedy", "cd",
    # Personas destacadas de la industria
    "koji", "miyazaki", "hideo", "shigeru", "gaben", "gabriel", "ingame",
    # Tecnología / render
    "nvenc", "gpu", "cpu", "raytracing", "raytraced", "upscaling", "fps",
})

# Descriptores que suelen separar el nombre del juego de la palabra-ancla
# cuando el ancla aparece tarde ("Red Dead Redemption 2 release date
# announced"). También se recortan los "pegamentos" gramaticales que pueden
# quedar entre el nombre y el verbo-ancla ("Persona 5 Royal is coming to...").
# Se recortan SOLO del FINAL del candidato, así que nunca se comen el nombre.
_POST_NAME_TOKENS = frozenset({
    "new", "official", "first", "next", "latest", "upcoming",
    "release", "released", "date", "dates", "update", "updates", "updated",
    "patch", "patches", "trailer", "trailers", "gameplay", "teaser",
    "dlc", "expansion", "roadmap", "content", "details", "everything",
    "preview", "showcase", "demo", "beta", "test", "tests", "leak", "leaks",
    "leaked", "screenshots", "images", "price", "pricing", "now", "available",
    "story", "game", "games", "sequel", "announced", "confirms",
    "confirmed", "revealed", "reveal", "finally", "remaster", "remake",
    "early", "access", "multiplayer", "coop", "co-op", "singleplayer",
    "mode", "modes", "season", "year", "edition", "anniversary",
    # Audiencia que suele ir entre el nombre y el verbo
    "players", "player", "users", "user", "gamers", "gamer", "fans",
    "everyone", "all",
    # Pegamentos gramaticales (copulas/auxiliares/preposiciones/artículos)
    "is", "are", "was", "were", "will", "be", "been", "has", "have", "had",
    "does", "do", "did", "gets", "get", "got", "could", "should", "would",
    "may", "can", "must", "to", "the", "a", "an", "for", "on", "in", "at",
    "with", "and", "this", "that", "its", "their", "his", "her", "our",
    "your", "my", "of", "from", "about", "into", "after", "before",
    "during", "since", "until", "while", "by", "between",
    # Adverbios que aterrizan antes del verbo-ancla
    "officially", "reportedly", "apparently", "soon",
    "already", "still", "out", "back", "again",
})


def _words_of(text: str) -> list[str]:
    return re.split(r"\s+", text.strip())


def _strip_punct(word: str) -> str:
    return word.strip(".,:;!?()[]\"'«»-—_")


def _strip_terminal_possessive(word: str) -> str:
    """Recorta un posesivo final ('s / ’s) que cierra el candidato.

    "Red Dead Redemption 2's" → "Red Dead Redemption 2". NO afecta a los
    posesivos internos ("Baldur's Gate", "Assassin's Creed"): solo se aplica
    sobre el ÚLTIMO token del candidato.
    """
    if len(word) >= 2 and word[-2:] == "'s":
        return word[:-2]
    if len(word) >= 2 and word[-2:] == "’s":
        return word[:-2]
    return word


def _is_non_game_token(token: str) -> bool:
    """Un token nunca puede ser parte del nombre de un juego."""
    low = _strip_punct(token).lower()
    return low in _GENERIC_NAME_TOKENS or low in _NON_GAME_ENTITIES


# ---------------------------------------------------------------------------
# Mención como SUJETO vs. COMPARACIÓN/referencia
#
# Un juego puede aparecer en un titular como:
#   A) SUJETO de la noticia   -> "Elden Ring gets a new update"
#   B) COMPARACIÓN/REFERENCIA -> "Nodusfall isn't Elden Ring...",
#      "Usual June mixes Hades-esque action...", "GTA 6? No thanks, I'll be
#      playing Volvy's Adventure".
# Solo A produce un NOMBRE de juego fiable. Esta sección detecta B mediante
# marcadores ESTRUCTURALES (negación, sufijos "-esque"/"-like", verbos de
# contraste, descarte post-mención, patrón "playing/played <título>"), nunca
# por listas de palabras negativas sueltas: el filtro temático (topic.py)
# sigue necesitando las menciones comparativas como EVIDENCIA de que el
# artículo habla de videojuegos. Por eso la detección de nombres tiene dos
# versiones: la INGUARDADA (evidencia: ``_detect_known_title_any``) y la
# GUARDADA (nombre fiable: ``_detect_via_known_title`` / ``is_main_topic``).
# ---------------------------------------------------------------------------

# Palabras que inauguran una negación/comparación justo antes del nombre.
_REFERENCE_PREFIX_WORDS = frozenset({
    "not", "no", "never", "neither", "nor", "unlike", "without", "except",
    "rather", "instead", "than", "versus", "vs", "unless", "beyond",
})

# Prefijos de contracción negativa ("isn't" -> "isn"+"t", "aren't" -> "aren"+"t").
_CONTRACTION_STEMS = frozenset({
    "isn", "arent", "wasn", "werent", "aint", "didn", "doesn", "don", "hant",
    "hadn", "shouldn", "wouldn", "won", "can", "couldn", "needn", "mustn",
})

# Confirmación inmediata de descarte tras la mención.
_DISMISS_NEXT = frozenset({"nope", "nah", "nada"})
_DISMISS_NO_FOLLOW = frozenset({"thanks", "thank", "thx", "way", "worries"})


def _strip_punct_list(text: str) -> list[str]:
    return [_strip_punct(w) for w in _words_of(text)]


def _is_reference(title: str, name: str) -> bool:
    """``True`` si ``name`` aparece en ``title`` como comparación/referencia o
    negación y NO como sujeto de la noticia.

    Estrictamente estructural (los apóstrofes se normalizan a espacio):
    1. Sufijo pegado/adyacente de comparación: "Hades-esque", "Dark Souls-like",
       "rip-off", "clone", "homage", "inspired".
    2. Negación/comparación directa en las 2 palabras previas: "isn't Elden
       Ring", "unlike X", "not X", "than X".
    3. Lista que hereda una negación previa si no hay un verbo de preferencia
       ("playing"/"played") que "absorba" la mención: "isn't Elden Ring,
       Monster Hunter o…" marca las tres como referencias, pero "no X, I'll be
       playing Volvy's" solo marca a X.
    4. Descarte inmediato posterior: "GTA 6? No thanks", "GTA 6? Nah".
    """
    if not title or not name:
        return False
    base = re.sub(r"['’]", " ", title)
    nname = re.sub(r"['’]", " ", name.strip().strip(".,:;!?()[]\"«»-—_")).strip()
    if not nname:
        return False

    # 1) Sufijo de comparación pegado a la mención.
    if re.search(
        rf"\b{re.escape(nname)}[\s\-–—](?:esque|like|style|styled|inspired|"
        rf"evoking|clone|clones|ripoff|rip[- ]off|ripoffs|knockoff|knock[- ]offs|"
        rf"wannabe|homage)\b",
        base,
        re.IGNORECASE,
    ):
        return True

    words = [w.casefold() for w in _strip_punct_list(base)]
    name_words = [w.casefold() for w in _strip_punct_list(nname)]
    n = len(words)
    m = len(name_words)
    if m == 0 or n < m:
        return False

    for i in range(n - m + 1):
        if words[i:i + m] != name_words:
            continue
        before = words[max(0, i - 10):i]
        after = words[i + m:]

        # 2) Negación/comparación directa inmediata.
        tail2 = before[-2:]
        direct_neg = (
            any(w in _REFERENCE_PREFIX_WORDS for w in tail2)
            or (
                len(tail2) == 2
                and tail2[1] == "t"
                and tail2[0] in _CONTRACTION_STEMS
            )
        )
        if direct_neg:
            return True

        # 3) Lista que hereda una negación previa sin verbo de preferencia.
        marker = next(
            (j for j, w in enumerate(before) if w in _REFERENCE_PREFIX_WORDS),
            None,
        )
        stem_marker = next(
            (j for j in range(len(before) - 1)
             if before[j] in _CONTRACTION_STEMS and before[j + 1] == "t"),
            None,
        )
        if marker is not None or stem_marker is not None:
            hit = marker if marker is not None else stem_marker
            tail = before[hit + 1:]
            if not any(w in ("playing", "played") for w in tail):
                return True

        # 4) Descarte inmediato tras la mención.
        if after:
            if after[0] in _DISMISS_NEXT:
                return True
            no_idx = next((j for j, w in enumerate(after[:4]) if w == "no"), None)
            if no_idx is not None:
                following = after[no_idx + 1] if no_idx + 1 < len(after) else None
                if following is None or following in _DISMISS_NO_FOLLOW:
                    return True
        return False
    return False


def _detect_via_anchor(title: str) -> str | None:
    words = _words_of(title)
    candidates: list[tuple[str, int]] = []  # (candidate, anchor_index)
    # Recorrer todos los anclas, recopilar candidatos válidos
    for i, word in enumerate(words):
        if _strip_punct(word).lower() in _EVENT_ANCHOR_WORDS:
            name_tokens = [_strip_punct(t) for t in words[:i]]
            while name_tokens and name_tokens[0].lower() in _LEADING_NOISE:
                name_tokens = name_tokens[1:]
            while name_tokens and name_tokens[-1].lower() in _POST_NAME_TOKENS:
                name_tokens = name_tokens[:-1]
            if not name_tokens:
                continue
            name_tokens[-1] = _strip_terminal_possessive(name_tokens[-1])
            if not name_tokens[-1]:
                continue
            if any(_is_non_game_token(t) for t in name_tokens):
                continue
            candidate = " ".join(t for t in name_tokens[:6])
            candidate = candidate.strip(" :;—,-")
            if len(candidate) >= 2:
                candidates.append((candidate, i))
    if not candidates:
        return None
    # Elegir el mejor: preferir el que contiene un título conocido (más específico),
    # si no, el más corto (menos palabras genéricas).
    def score(cand_idx: tuple[str, int]) -> tuple[int, int]:
        cand, _ = cand_idx
        # Prioridad 1: contiene título conocido → mejor
        known = _detect_via_known_title(cand)
        has_known = 1 if known else 0
        # Prioridad 2: menos palabras (más conciso)
        word_count = len(cand.split())
        return (-has_known, word_count)
    best = min(candidates, key=score)[0]
    return best


# Nombres de juegos/sagas conocidos que NO están en ``games.yaml`` pero son
# fáciles de reconocer por límites de palabra y difíciles de confundir con
# palabras genéricas del titular.
#
# Estructura: cada clave es una variante normalizada (título canónico o alias
# inequívoco) y el valor es el NOMBRE CANÓNICO que se muestra. Varias claves
# pueden apuntar al mismo canónico ("hades" y "hades ii" → "Hades II"), y el
# matcher se queda con la variante de mayor longitud (la más específica).
#
# NO es una whitelist: solo identifica el NOMBRE a mostrar; toda noticia no
# excluida se publica igual (con ``Videojuegos`` si no se concluye nada).
# Se excluyen shortcodes tipo "COD"/"GTA" (ambiguos, generan falsos positivos)
# y palabras comunes de una sola palabra ("doom" puede ser "doom and gloom").
_KNOWN_GAME_TITLES: dict[str, str] = {
    "red dead redemption 2": "Red Dead Redemption 2",
    "red dead redemption ii": "Red Dead Redemption 2",
    "red dead redemption": "Red Dead Redemption",
    "red dead": "Red Dead",
    "the witcher": "The Witcher",
    "witcher": "The Witcher",
    "assassin's creed": "Assassin's Creed",
    "assassins creed": "Assassin's Creed",
    "mass effect": "Mass Effect",
    "god of war": "God of War",
    "spider-man": "Spider-Man",
    "spiderman": "Spider-Man",
    "spider man": "Spider-Man",
    "horizon zero dawn": "Horizon Zero Dawn",
    "horizon forbidden west": "Horizon Forbidden West",
    "kingdom come deliverance": "Kingdom Come: Deliverance",
    "alan wake": "Alan Wake",
    "hogwarts legacy": "Hogwarts Legacy",
    "street fighter": "Street Fighter",
    "mortal kombat": "Mortal Kombat",
    "tekken": "Tekken",
    "minecraft": "Minecraft",
    "fortnite": "Fortnite",
    "overwatch": "Overwatch",
    "valorant": "Valorant",
    "hades": "Hades",
    "hades ii": "Hades II",
    "hades 2": "Hades 2",
    "stardew valley": "Stardew Valley",
    "diablo": "Diablo",
    "world of warcraft": "World of Warcraft",
    "counter-strike": "Counter-Strike",
    "marvel rivals": "Marvel Rivals",
    "the last of us": "The Last of Us",
    "dragon age": "Dragon Age",
    "resident evil": "Resident Evil",
    "monster hunter": "Monster Hunter",
    "silent hill": "Silent Hill",
    "metal gear": "Metal Gear",
    "the sims": "The Sims",
    "the elder scrolls": "The Elder Scrolls",
    "elder scrolls": "The Elder Scrolls",
    "half-life": "Half-Life",
    "half life": "Half-Life",
    "destiny": "Destiny",
    "destiny 2": "Destiny 2",
    "detroit become human": "Detroit: Become Human",
    "death stranding": "Death Stranding",
    "metroid prime": "Metroid Prime",
    "heavenly sword": "Heavenly Sword",
}

_KNOWN_TITLE_PATTERNS: list[tuple[re.Pattern, str, int]] = [
    (re.compile(rf"\b(?:{re.escape(_normalize(key))})\b"), display, len(_normalize(key)))
    for key, display in _KNOWN_GAME_TITLES.items()
]


def _known_title_matches(title: str) -> list[tuple[int, str, str]]:
    """Parejas (longitud, display, variante real matcheada) de títulos conocidos
    presentes en ``title``, ordenadas por longitud de patrón DESC (las más
    específicas primero)."""
    norm = _normalize(title)
    seen: set[tuple[str, str]] = set()
    out: list[tuple[int, str, str]] = []
    for pattern, display, key_len in _KNOWN_TITLE_PATTERNS:
        m = pattern.search(norm)
        if m:
            key = (display, m.group(0))
            if key in seen:
                continue
            seen.add(key)
            out.append((key_len, display, m.group(0)))
    out.sort(key=lambda t: t[0], reverse=True)
    return out


def _detect_known_title_any(title: str) -> str | None:
    """Versión EVIDENCIA (sin guarda de contexto): para el filtro temático.

    Un juego conocido mencionado en comparación/referencia ("Hades-esque",
    "isn't Elden Ring") demuestra CONTENIDO gaming; el matcher decide luego si
    esa mención es además el NOMBRE de la noticia."""
    matches = _known_title_matches(title)
    return matches[0][1] if matches else None


def _detect_via_known_title(title: str) -> str | None:
    """Para el matcher (NOMBRE del juego): ignora menciones que solo sean
    comparación/referencia/negación y devuelve la más específica restante."""
    for _key_len, display, actual in _known_title_matches(title):
        if not _is_reference(title, actual):
            return display
    return None


# Verbo/sintagma de contraste al inicio que convierte lo que le precede en el
# SUJETO del titular. Se evalúa en slices de 1-3 tokens ("is not just").
_CONTRAST_LEADING_VERBS = frozenset({
    "isn't", "isnt", "isn’t", "isn t", "is not", "is not just",
    "is more", "is more than", "is not a", "is not an",
    "are not", "aren't", "arent", "aren t", "weren't", "werent", "weren t",
    "mixes", "mix", "blends", "blend", "combines", "combine",
    "mashes", "mash", "mashing", "mixing",
})

# Pronombres/partículas que jamás forman un nombre de juego.
_PRONOUNS = frozenset({
    "i", "you", "we", "they", "he", "she", "it", "my", "your", "our",
    "their", "his", "her", "its", "this", "that", "these", "those",
    "there", "here", "who", "what", "when", "why", "someone", "everyone",
    "nobody", "anybody", "me", "us", "them", "him", "himself",
})


def _contrast_verb_at(words: list[str], idx: int) -> int | None:
    """Longitud del sintagma de contraste que comienza en ``idx``, si existe."""
    for span in (3, 2, 1):
        if idx + span > len(words):
            continue
        phrase = " ".join(_strip_punct(w).lower() for w in words[idx:idx + span])
        if phrase in _CONTRAST_LEADING_VERBS:
            return span
    return None


def _detect_leading_contrast_subject(title: str) -> str | None:
    """Reconoce el SUJETO cuando el titular arranca con "nombre + verbo de
    contraste/mezcla":

        "Nodusfall isn't Elden Ring..."       -> "Nodusfall"
        "Usual June mixes Hades-esque action" -> "Usual June"

    Patrón ESTRUCTURAL (nombre al inicio + verbo de contraste tras él), no
    adivinación por capitalización: solo captura lo que precede al verbo."""
    words = _words_of(title.strip())
    for i in range(len(words)):
        if _contrast_verb_at(words, i) is None:
            continue
        subject = words[:i]
        while subject and _strip_punct(subject[0]).lower() in _LEADING_NOISE:
            subject = subject[1:]
        if not subject:
            continue
        subject[-1] = _strip_terminal_possessive(subject[-1])
        if not subject[-1]:
            continue
        cand = " ".join(_strip_punct(t) for t in subject[:6]).strip(" :;—,-")
        if len(cand) < 2:
            continue
        tokens = cand.split()
        if any(t.lower() in _PRONOUNS for t in tokens):
            continue
        if any(_is_non_game_token(t) for t in tokens):
            continue
        return cand
    return None


_PLAYING_RE = re.compile(
    r"\b(?:playing|played)\s+"
    r"((?:[A-ZÁÉÍÓÚÑÜÀÈÌÒÙ][A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü’'-]*)(?:\s+"
    r"(?:[A-ZÁÉÍÓÚÑÜÀÈÌÒÙ][A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü’'-]*|\d+(?:\.\d+)*)){0,3})"
)


def _detect_after_playing(title: str) -> str | None:
    """Reconoce el juego tras un verbo de juego explícito:

        "…I'll be playing Volvy's Adventure" -> "Volvy's Adventure"

    Reconstruye el nombre tal cual llega del titular y exige arranque en
    mayúscula (con apoyo de acentos y números), máx. 4 tokens, sin ruido
    genérico."""
    if not title:
        return None
    for m in _PLAYING_RE.finditer(title):
        cand = m.group(1).strip().strip(".,:;!?()[]\"'«»-—_")
        if len(cand) < 2:
            continue
        tokens = [_strip_punct(t) for t in cand.split()]
        if any(t.lower() in _PRONOUNS for t in tokens):
            continue
        if any(_is_non_game_token(t) for t in tokens):
            continue
        return cand
    return None


def _detect_game_name_with_reason(
    title: str, body: str = "", *, hint: str | None = None
) -> tuple[str | None, str | None]:
    """Como ``detect_game_name`` pero además devuelve la razón del match.

    Razones: "hint" (Steam), "anchor" (palabra-ancla y contexto), "known_title"
    (lista curada), "subject" (sujeto ante verbo de contraste/mezcla),
    "playing" (juego tras "playing"/"played") o ``None`` (sin conclusión
    fiable → la llamada usa el genérico).
    """
    if hint and hint.strip():
        return hint.strip(), "hint"

    title_clean = title.strip()
    if title_clean:
        cand = _detect_via_anchor(title_clean)
        if cand:
            return cand, "anchor"
        cand = _detect_via_known_title(title_clean)
        if cand:
            return cand, "known_title"
        cand = _detect_leading_contrast_subject(title_clean)
        if cand:
            return cand, "subject"
        cand = _detect_after_playing(title_clean)
        if cand:
            return cand, "playing"
    return None, None


def detect_game_name(title: str, body: str = "", *, hint: str | None = None) -> str | None:
    """Detecta el nombre de un juego/saga NO configurado en ``games.yaml``.

    Respeta el comportamiento del filtro: no se usa a modo de inclusión ni le
    gana nunca a una exclusión (solo se llama tras verificar que el artículo
    no está excluido y que no matchea ningún juego configurado).

    Orden de confianza:
    1. ``hint`` explícito (el nombre de la app de Steam siempre identifica el
       juego aunque no esté en ``games.yaml``).
    2. Título: las palabras-ancla de noticia separan "nombre del juego" del
       resto del titular (p. ej. "Hollow Knight Silksong Patch 1.1"), siempre
       que el candidato no sea una palabra genérica ni una entidad no-juego.
    3. Título: nombres de juegos/sagas conocidos (lista curada) por límites de
       palabra, ignorando menciones que solo sean comparación/referencia.
    4. Título: sujeto ante verbo de contraste/mezcla ("Nodusfall isn't Elden
       Ring…") y juego tras "playing/played" ("…playing Volvy's Adventure").
    5. Sin conclusión fiable → ``None`` (la llamada usa el nombre genérico).

    Queda PROHIBIDO adivinar por capitalización o por cualquier palabra que
    "parezca" nombre: "Modern gamers spoiled by Steam...", "Update 2.1 is
    here!", "Sony announces new gaming initiative" o "Steam users are getting
    a major new feature" deben producir ``None``, nunca "Modern"/"Sony"/
    "Steam". El resultado se conserva tal cual llega del título.
    """
    name, _reason = _detect_game_name_with_reason(title, body, hint=hint)
    return name


def create_matcher(
    include_rules: list[GameRule], exclude_rules: list[GameRule]
) -> GameMatcher:
    """Factory para construir el matcher desde la configuración."""
    return GameMatcher(include_rules, exclude_rules)