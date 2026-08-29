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
})


def detect_game_name(title: str, body: str = "", *, hint: str | None = None) -> str | None:
    """Detecta el nombre de un juego/saga NO configurado en ``games.yaml``.

    Respecta el comportamiento del filter: no se usa a modo de inclusión ni
    le gana nunca a una exclusión (la llamada solo ocurre tras verificar que
    el artículo no está excluido y que no matcha ningún juego configurado).

    Orden de confianza:
    1. ``hint`` explícito (p. ej. el nombre de la app de Steam, que siempre
       identifica el juego aunque no esté en ``games.yaml``).
    2. Título: las palabras-ancla de noticia separan "nombre del juego" del
       resto del titular (p. ej. "Hollow Knight Silksong Patch 1.1").
    3. Título: la secuencia más larga de tokens capitalizados/números.
    4. Sin conclusión fiable → ``None`` (la llamada usa un nombre genérico).

    El resultado se conserva tal cual llega del título (mayúsculas originales).
    """
    if hint and hint.strip():
        return hint.strip()

    title_clean = title.strip()
    if title_clean:
        cand = _detect_via_anchor(title_clean)
        if cand:
            return cand
        cand = _detect_via_capitalized_run(title_clean)
        if cand:
            return cand
    return None


def _words_of(text: str) -> list[str]:
    return re.split(r"\s+", text.strip())


def _strip_punct(word: str) -> str:
    return word.strip(".,:;!?()[]\"'«»-—_")


def _detect_via_anchor(title: str) -> str | None:
    words = _words_of(title)
    for i, word in enumerate(words):
        if _strip_punct(word).lower() in _EVENT_ANCHOR_WORDS:
            name_tokens = words[:i]
            while name_tokens and _strip_punct(name_tokens[0]).lower() in _LEADING_NOISE:
                name_tokens = name_tokens[1:]
            if not name_tokens:
                return None
            candidate = " ".join(_strip_punct(t) for t in name_tokens[:6])
            candidate = candidate.strip(" :;—,-")
            return candidate if len(candidate) >= 2 else None
    return None


_OR_CAPITALIZED = re.compile(
    r"(?:[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ0-9]*|\d+|[A-ZÁÉÍÓÚÜÑ]{2,5})"
    r"(?:\s+(?:[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ0-9]*|\d+|[A-ZÁÉÍÓÚÜÑ]{2,5}))*"
)


def _detect_via_capitalized_run(title: str) -> str | None:
    best: str | None = None
    best_len = 0
    for match in _OR_CAPITALIZED.finditer(title):
        run = match.group().strip()
        tokens = _words_of(run)
        if len(tokens) > best_len:
            best = run
            best_len = len(tokens)
    if best and best_len >= 1:
        return best
    return None


def create_matcher(
    include_rules: list[GameRule], exclude_rules: list[GameRule]
) -> GameMatcher:
    """Factory para construir el matcher desde la configuración."""
    return GameMatcher(include_rules, exclude_rules)