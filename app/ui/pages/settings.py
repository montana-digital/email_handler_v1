"""Settings page with persistent configuration updates."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.config import AppConfig
from app.config_store import save_config
from app.db.init_db import reset_engine
from app.ui.state import AppState


def _as_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def render(state: AppState) -> None:
    st.header("Settings")
    st.write("Configure local directories and database connection. Changes persist to `.env`.")

    with st.form("settings_form"):
        input_dir = st.text_input(
            "Email Input Directory",
            value=str(state.config.input_dir),
            key="settings_input_dir",
        )
        cache_dir = st.text_input(
            "Pickle Cache Directory",
            value=str(state.config.pickle_cache_dir),
            key="settings_cache_dir",
        )
        output_dir = st.text_input(
            "Output Directory",
            value=str(state.config.output_dir),
            key="settings_output_dir",
        )
        scripts_dir = st.text_input(
            "Scripts Directory",
            value=str(state.config.scripts_dir),
            key="settings_scripts_dir",
        )
        log_dir = st.text_input(
            "Log Directory",
            value=str(state.config.log_dir),
            key="settings_log_dir",
        )
        db_url = st.text_input(
            "Database URL",
            value=state.config.database_url,
            key="settings_db_url",
            help="For SQLite, use format sqlite:///C:/path/to/email_handler.db",
        )

        submitted = st.form_submit_button("Save Settings")

    if not submitted:
        return

    try:
        new_config = AppConfig(
            database_url=db_url.strip(),
            pickle_cache_dir=_as_path(cache_dir),
            input_dir=_as_path(input_dir),
            output_dir=_as_path(output_dir),
            scripts_dir=_as_path(scripts_dir),
            log_dir=_as_path(log_dir),
            env_name=state.config.env_name,
        )

        # Ensure directories exist before persisting
        new_config.input_dir.mkdir(parents=True, exist_ok=True)
        new_config.output_dir.mkdir(parents=True, exist_ok=True)
        new_config.pickle_cache_dir.mkdir(parents=True, exist_ok=True)
        new_config.scripts_dir.mkdir(parents=True, exist_ok=True)
        new_config.log_dir.mkdir(parents=True, exist_ok=True)

        env_path = save_config(new_config)
        reset_engine(new_config)

        state.config = new_config
        state.add_notification("Configuration updated and persisted.")

        st.success(f"Settings saved to {env_path} and database connection reloaded.")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to save settings: {exc}")
