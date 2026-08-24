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


def create_matcher(
    include_rules: list[GameRule], exclude_rules: list[GameRule]
) -> GameMatcher:
    """Factory para construir el matcher desde la configuración."""
    return GameMatcher(include_rules, exclude_rules)