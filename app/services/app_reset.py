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


def _sqlite_path(config: AppConfig) -> Path | None:
    if config.database_url.startswith("sqlite:///"):
        return Path(config.database_url.replace("sqlite:///", "")).expanduser()
    return None


def backup_database(config: AppConfig, destination: Path) -> Path | None:
    source = _sqlite_path(config)
    if not source or not source.exists():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def reset_application(
    config: AppConfig,
    *,
    reset_database: bool = True,
    reset_cache: bool = True,
    reset_output: bool = True,
    reset_logs: bool = True,
) -> None:
    """Remove data according to the supplied flags."""
    if reset_database:
        db_path = _sqlite_path(config)
        if db_path and db_path.exists():
            try:
                db_path.unlink()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to delete database file %s: %s", db_path, exc)

    directories: list[Path] = []
    if reset_cache:
        directories.append(config.pickle_cache_dir)
    if reset_output:
        directories.append(config.output_dir)
    if reset_logs:
        directories.append(config.log_dir)

    for directory in directories:
        _clear_directory_contents(directory)

