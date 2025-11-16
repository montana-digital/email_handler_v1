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
        # Handle both forward and backward slashes, and resolve the path
        path_str = config.database_url.replace("sqlite:///", "")
        # Handle Windows paths with forward slashes
        if path_str.startswith("/") and not Path(path_str).exists():
            # Try converting /C:/path to C:/path
            if len(path_str) > 2 and path_str[1] == ":":
                path_str = path_str[1:]
        path = Path(path_str).expanduser().resolve()
        logger.debug("Resolved database path: %s (from URL: %s)", path, config.database_url)
        return path
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
        if not db_path:
            logger.warning("Could not determine database path from URL: %s", config.database_url)
            return
        
        logger.info("Attempting to delete database at: %s (exists: %s)", db_path, db_path.exists())
        
        if db_path.exists():
            # Try multiple times to delete the database file
            # SQLite may hold locks briefly after connections close
            import time
            max_attempts = 5
            deleted = False
            for attempt in range(max_attempts):
                try:
                    # Also delete SQLite WAL and SHM files if they exist
                    wal_path = db_path.with_suffix(db_path.suffix + "-wal")
                    shm_path = db_path.with_suffix(db_path.suffix + "-shm")
                    
                    logger.debug("Attempt %d/%d: Deleting database files", attempt + 1, max_attempts)
                    
                    # Delete WAL and SHM files first (they may be easier to delete)
                    if wal_path.exists():
                        try:
                            wal_path.unlink()
                            logger.info("Deleted WAL file: %s", wal_path)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Failed to delete WAL file %s: %s", wal_path, exc)
                    
                    if shm_path.exists():
                        try:
                            shm_path.unlink()
                            logger.info("Deleted SHM file: %s", shm_path)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Failed to delete SHM file %s: %s", shm_path, exc)
                    
                    # Now delete the main database file
                    db_path.unlink()
                    deleted = True
                    logger.info("Database file deleted successfully: %s", db_path)
                    break
                except PermissionError as exc:
                    if attempt < max_attempts - 1:
                        logger.debug("Database file locked, retrying in 0.5s (attempt %d/%d): %s", attempt + 1, max_attempts, exc)
                        time.sleep(0.5)
                    else:
                        logger.error("Failed to delete database file %s after %d attempts: file is locked - %s", db_path, max_attempts, exc)
                        raise
                except Exception as exc:  # noqa: BLE001
                    logger.error("Failed to delete database file %s: %s", db_path, exc)
                    raise
        else:
            logger.info("Database file does not exist at %s, nothing to delete", db_path)

    directories: list[Path] = []
    if reset_cache:
        directories.append(config.pickle_cache_dir)
    if reset_output:
        directories.append(config.output_dir)
    if reset_logs:
        directories.append(config.log_dir)

    for directory in directories:
        _clear_directory_contents(directory)

