"""Helpers to reset the application to a first-run state."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from loguru import logger

from app.config import AppConfig


def _clear_directory_contents(path: Path) -> None:
    if not path.exists():
        return
    for item in path.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to remove %s: %s", item, exc)


def reset_application(config: AppConfig) -> None:
    """Remove database, cache, output, and log data to simulate first run."""
    if config.database_url.startswith("sqlite:///"):
        db_path = Path(config.database_url.replace("sqlite:///", "")).expanduser()
        if db_path.exists():
            try:
                db_path.unlink()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to delete database file %s: %s", db_path, exc)

    for directory in _directories_to_clear(config):
        _clear_directory_contents(directory)


def _directories_to_clear(config: AppConfig) -> Iterable[Path]:
    yield config.pickle_cache_dir
    yield config.output_dir
    yield config.log_dir

