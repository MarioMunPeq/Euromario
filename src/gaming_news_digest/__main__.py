"""Punto de entrada del pipeline: ``python -m gaming_news_digest``."""

import logging
import sys
from pathlib import Path

from gaming_news_digest.config import load_games, load_sources
from gaming_news_digest.pipeline import Pipeline

logger = logging.getLogger("gaming_news_digest")

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    games_path = _CONFIG_DIR / "games.yaml"
    sources_path = _CONFIG_DIR / "sources.yaml"

    logger.info("Cargando config desde %s", _CONFIG_DIR)
    games_cfg = load_games(games_path)
    sources_cfg = load_sources(sources_path)

    pipeline = Pipeline(sources=sources_cfg, games=games_cfg, limits=sources_cfg.limits)
    pipeline.run()


if __name__ == "__main__":
    main()
