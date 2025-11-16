"""Shared Streamlit session state helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import streamlit as st

from app.config import AppConfig, load_config


@dataclass
class AppState:
    config: AppConfig
    selected_batch_id: Optional[int] = None
    selected_email_id: Optional[int] = None
    selected_standard_email_id: Optional[int] = None
    attachments_filter: str = "Images"
    search_query: str = ""
    standard_email_search: str = ""
    notifications: list[str] = field(default_factory=list)
    script_runs: list[dict] = field(default_factory=list)
    ui_state: dict[str, Any] = field(default_factory=dict)

    def add_notification(self, message: str) -> None:
        self.notifications.append(message)

    def record_script_run(self, run: dict) -> None:
        self.script_runs.append(run)
        if len(self.script_runs) > 10:
            self.script_runs = self.script_runs[-10:]

    def get_fragment_state(self, key: str, default: Any) -> Any:
        if key not in self.ui_state:
            self.ui_state[key] = default
        return self.ui_state[key]

    def update_fragment_state(self, key: str, **updates: Any) -> None:
        state = self.get_fragment_state(key, {})
        state.update(updates)
        self.ui_state[key] = state


def get_state(*, config: Optional[AppConfig] = None) -> AppState:
    if "app_state" not in st.session_state:
        st.session_state["app_state"] = AppState(config=config or load_config())

    state: AppState = st.session_state["app_state"]

    if config:
        state.config = config

    return state

