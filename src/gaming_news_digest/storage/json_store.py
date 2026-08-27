"""Lectura/escritura atómica del JSON que consume el frontend (`frontend/data/news.json`).

Incluye merge con histórico existente y escritura atómica (tmp + os.replace).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..models import ModelValidationError, NewsItem

logger = logging.getLogger(__name__)

DATA_PATH = Path("frontend/data/news.json")

#: Corrupción histórica de codificación detectada en ``source.name`` de
#: ejecuciones viejas: el punto medio "·" (U+00B7) quedó escrito como "┬À".
_LEGACY_MOJIBAKE = "┬À"
_INTERPUNCT = "·"


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

    - Un archivo ausente, ilegible o con JSON inválido devuelve lista vacía.
    - Cada item se migra de la forma histórica a la actual y se valida
      contra el contrato INDIVIDUALMENTE: uno inválido se descarta con log
      y NUNCA tumba el resto del histórico (regla P0).
    """
    if not DATA_PATH.exists():
        return []

    try:
        content = DATA_PATH.read_text(encoding="utf-8")
        data = json.loads(content)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "news.json corrupto o ilegible (%s); se inicia histórico vacío", exc
        )
        return []

    news = data.get("news") if isinstance(data, dict) else None
    if not isinstance(news, list):
        logger.warning("news.json sin lista 'news'; se inicia histórico vacío")
        return []

    items: list[NewsItem] = []
    for index, raw in enumerate(news):
        if not isinstance(raw, dict):
            logger.warning(
                "Item %d del histórico descartado: no es un objeto JSON", index
            )
            continue
        try:
            item = NewsItem.from_dict(_migrate_legacy_item(raw))
        except (ModelValidationError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Item %d del histórico descartado por validación del contrato "
                "(motivo: %s). Contexto: %s",
                index,
                exc,
                _item_context(raw),
            )
            continue
        if item.summary is None:
            logger.info(
                "Item '%s' cargado con summary=null: fallback IA documentado",
                item.title,
            )
        items.append(item)

    discarded = len(news) - len(items)
    if discarded:
        logger.warning("%d item(s) del histórico descartados por contrato", discarded)
    return items


def _migrate_legacy_item(item: dict) -> dict:
    """Adecúa un item del JSON histórico al contrato actual (sin inventar).

    - ``fetched_at`` ausente (no existía) → se rellena con ``published_at``:
      es el timestamp conocido más cercano al hecho; se registra en log.
    - ``author`` / ``game_id`` / ``is_verified`` ausentes → ``None``/``False``.
    - Destrozado de codificación "┬À" en ``source.name`` → "·" (reparación
      determinista del punto medio histórico).
    - Formato histórico ``source`` anidado → plano ``source`` + ``source_type`` (+ ``source_subreddit`` para Reddit).
    - ``image_url`` → ``image``.
    """
    migrated = dict(item)
    source = migrated.get("source")
    if isinstance(source, dict) and isinstance(source.get("name"), str):
        # Extraer campos del source anidado y convertir a formato plano
        source_name = source.get("name")
        source_type = source.get("type", "media")
        source_subreddit = source.get("subreddit") if source_type == "reddit" else None
        if _LEGACY_MOJIBAKE in source_name:
            logger.info(
                "Migración: source.name con mojibake reparado (%r → %r)",
                source_name,
                source_name.replace(_LEGACY_MOJIBAKE, _INTERPUNCT),
            )
            source_name = source_name.replace(_LEGACY_MOJIBAKE, _INTERPUNCT)
        migrated["source"] = source_name
        migrated["source_type"] = source_type
        if source_subreddit:
            migrated["source_subreddit"] = source_subreddit

    if not str(migrated.get("fetched_at") or "").strip():
        fallback = migrated.get("published_at")
        logger.info(
            "Migración: item histórico sin fetched_at → usa published_at (%s)",
            fallback,
        )
        migrated["fetched_at"] = fallback

    # Renombrar image_url → image
    if "image" not in migrated and "image_url" in migrated:
        migrated["image"] = migrated.pop("image_url")

    # is_verified: true para medios oficiales y Steam, false para Reddit
    # Si no existe, inferirlo del source_type migrado
    if "is_verified" not in migrated:
        st = migrated.get("source_type")
        if st == "reddit":
            migrated["is_verified"] = False
        elif st in ("media", "steam"):
            migrated["is_verified"] = True
        else:
            migrated["is_verified"] = False

    migrated.setdefault("author", None)
    migrated.setdefault("game_id", None)
    return migrated


def _item_context(raw: dict) -> dict:
    """Extrae contexto mínimo (sin lanzar) para el log de descarte."""
    source_name = None
    src = raw.get("source")
    if isinstance(src, dict):
        source_name = src.get("name")
    elif isinstance(src, str):
        source_name = src
    return {key: raw[key] for key in ("id", "title", "url")
            if isinstance(raw.get(key), str)} | {"source": source_name}


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