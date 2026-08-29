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
        """Inclusión exige: título O ≥2 menciones en body."""
        norm_title = _normalize(title)
        if pattern.search(norm_title):
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


def _detect_via_known_title(title: str) -> str | None:
    """Busca nombres de juegos conocidos en el titular (límites de palabra).

    Devuelve el nombre más específico (el de mayor longitud) que aparezca.
    Nunca inventa nombres: si no hay match, devuelve ``None``.
    """
    norm = _normalize(title)
    best: str | None = None
    best_len = 0
    for pattern, display, key_len in _KNOWN_TITLE_PATTERNS:
        if pattern.search(norm) and key_len > best_len:
            best = display
            best_len = key_len
    return best


def _detect_game_name_with_reason(
    title: str, body: str = "", *, hint: str | None = None
) -> tuple[str | None, str | None]:
    """Como ``detect_game_name`` pero además devuelve la razón del match.

    Razones: "hint" (Steam), "anchor" (palabra-ancla y contexto), "known_title"
    (lista curada) o ``None`` (sin conclusión fiable → llamada usa genérico).
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
       palabra.
    4. Sin conclusión fiable → ``None`` (la llamada usa el nombre genérico).

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