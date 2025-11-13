"""Configuration utilities for the Email Handler app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "email_handler.db"
DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "logs"


@dataclass(slots=True)
class AppConfig:
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH}"
    pickle_cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    input_dir: Path = PROJECT_ROOT / "data" / "input"
    output_dir: Path = PROJECT_ROOT / "data" / "output"
    scripts_dir: Path = PROJECT_ROOT / "data" / "scripts"
    log_dir: Path = DEFAULT_LOG_DIR
    env_name: str = "local"


def load_config(env_file: Optional[Path] = None) -> AppConfig:
    if env_file is None:
        env_file = PROJECT_ROOT / ".env"

    load_dotenv(dotenv_path=env_file, override=False)

    database_url = os.getenv("EMAIL_HANDLER_DATABASE_URL")
    if not database_url:
        database_url = f"sqlite:///{DEFAULT_DB_PATH}"

    cfg = AppConfig(
        database_url=database_url,
        pickle_cache_dir=Path(os.getenv("EMAIL_HANDLER_CACHE_DIR", PROJECT_ROOT / "data" / "cache")),
        input_dir=Path(os.getenv("EMAIL_HANDLER_INPUT_DIR", PROJECT_ROOT / "data" / "input")),
        output_dir=Path(os.getenv("EMAIL_HANDLER_OUTPUT_DIR", PROJECT_ROOT / "data" / "output")),
        scripts_dir=Path(os.getenv("EMAIL_HANDLER_SCRIPTS_DIR", PROJECT_ROOT / "data" / "scripts")),
        log_dir=Path(os.getenv("EMAIL_HANDLER_LOG_DIR", DEFAULT_LOG_DIR)),
        env_name=os.getenv("EMAIL_HANDLER_ENV", "local"),
    )

    return cfg

