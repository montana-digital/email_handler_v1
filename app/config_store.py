"""Helpers for persisting application configuration to the .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from dotenv import dotenv_values
from loguru import logger

from app.config import AppConfig, PROJECT_ROOT
from app.utils.path_validation import validate_path

ENV_KEY_MAP = {
    "database_url": "EMAIL_HANDLER_DATABASE_URL",
    "pickle_cache_dir": "EMAIL_HANDLER_CACHE_DIR",
    "input_dir": "EMAIL_HANDLER_INPUT_DIR",
    "output_dir": "EMAIL_HANDLER_OUTPUT_DIR",
    "scripts_dir": "EMAIL_HANDLER_SCRIPTS_DIR",
    "log_dir": "EMAIL_HANDLER_LOG_DIR",
    "env_name": "EMAIL_HANDLER_ENV",
}


def _config_to_env_values(config: AppConfig) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for field_name, env_key in ENV_KEY_MAP.items():
        value = getattr(config, field_name)
        if value is None:
            continue
        # For paths, validate before saving
        if isinstance(value, Path):
            is_valid, error = validate_path(value)
            if not is_valid:
                logger.warning("Path validation failed for %s: %s", field_name, error)
                # Continue anyway, but log the warning
        values[env_key] = str(value)
    return values


def save_config(config: AppConfig, env_file: Path | None = None) -> Path:
    """Persist the provided configuration to a .env file."""
    target_file = env_file or PROJECT_ROOT / ".env"
    target_file.parent.mkdir(parents=True, exist_ok=True)

    existing = dotenv_values(target_file) if target_file.exists() else {}
    updated = {**existing, **_config_to_env_values(config)}

    lines = [f"{key}={value}" for key, value in sorted(updated.items()) if value is not None]
    target_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target_file

