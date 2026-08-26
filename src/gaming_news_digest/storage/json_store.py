"""Lectura/escritura atómica del JSON que consume el frontend (`frontend/data/news.json`).

Incluye merge con histórico existente y escritura atómica (tmp + os.replace).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..models import NewsItem

logger = logging.getLogger(__name__)

DATA_PATH = Path("frontend/data/news.json")


def _make_digest_data(items: list[NewsItem]) -> dict[str, Any]:
    """Construye el dict completo que se serializa a JSON."""
    return {
        "generated_at": utc_now_iso(),
        "total": len(items),
        "news": [item.to_dict() for item in items],
    }


def utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_existing_digest() -> list[NewsItem]:
    """Carga el digest existente desde `frontend/data/news.json`.

    Devuelve lista vacía si el archivo no existe o está corrupto.
    """
    if not DATA_PATH.exists():
        return []

    try:
        content = DATA_PATH.read_text(encoding="utf-8")
        data = json.loads(content)
        news = data.get("news", [])
        return [NewsItem.from_dict(item) for item in news]
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("news.json corrupto o inválido (%s); se inicia histórico vacío", exc)
        return []


def merge_and_retain(existing: list[NewsItem], new: list[NewsItem]) -> list[NewsItem]:
    """
    Combina histórico existente + items nuevos, deduplicando por id.

    Regla: NUEVO GANA (el item de la ejecución actual sobrescribe al histórico
    si tienen mismo id — por si cambió summary/relevance/category).
    Devuelve lista ordenada descendente por published_at con retención aplicada.
    """
    by_id = {it.id: it for it in existing}
    for item in new:
        by_id[item.id] = item  # nuevo gana

    merged = list(by_id.values())
    merged.sort(key=lambda x: x.published_at, reverse=True)

    from .retention import apply_retention
    return apply_retention(merged)


def save_digest(items: list[NewsItem]) -> None:
    """
    Guarda el digest de forma atómica en `frontend/data/news.json`.

    1. Carga histórico existente
    2. Merge + retención
    3. Escritura atómica: escribe .tmp + os.replace (atómico en POSIX/Windows)
    """
    existing = load_existing_digest()
    merged = merge_and_retain(existing, items)
    data = _make_digest_data(merged)

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DATA_PATH.with_suffix(".tmp")

    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path.write_text(json_str, encoding="utf-8")
    os.replace(tmp_path, DATA_PATH)

    logger.info("Digest guardado: %d items (generado %s)", len(merged), utc_now_iso())


GAMES_CONFIG_PATH = Path("frontend/data/games.json")


def save_games_config(games: list[dict]) -> None:
    """Guarda la config de juegos (nombre→logo) para el frontend."""
    GAMES_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = GAMES_CONFIG_PATH.with_suffix(".tmp")
    data = {"games": games}
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path.write_text(json_str, encoding="utf-8")
    os.replace(tmp_path, GAMES_CONFIG_PATH)
    logger.info("Games config guardado: %d juegos", len(games))