from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def apptest_env(tmp_path, monkeypatch):
    base = tmp_path
    input_dir = base / "input"
    cache_dir = base / "cache"
    output_dir = base / "output"
    scripts_dir = base / "scripts"
    log_dir = base / "logs"
    db_path = base / "email_handler.db"

    for directory in (input_dir, cache_dir, output_dir, scripts_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("EMAIL_HANDLER_INPUT_DIR", str(input_dir))
    monkeypatch.setenv("EMAIL_HANDLER_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("EMAIL_HANDLER_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("EMAIL_HANDLER_SCRIPTS_DIR", str(scripts_dir))
    monkeypatch.setenv("EMAIL_HANDLER_LOG_DIR", str(log_dir))
    monkeypatch.setenv("EMAIL_HANDLER_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("EMAIL_HANDLER_ENV", "apptest")

    return {
        "input_dir": input_dir,
        "cache_dir": cache_dir,
        "output_dir": output_dir,
        "scripts_dir": scripts_dir,
        "log_dir": log_dir,
        "db_path": db_path,
    }

