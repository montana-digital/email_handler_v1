"""Helpers to initialize shared state for every Streamlit page."""

from __future__ import annotations

from app.config import load_config
from app.db import init_db
from app.ui.state import AppState, get_state


def prepare_page() -> AppState:
    config = load_config()
    init_db()
    state = get_state(config=config)

    # Render shared sidebar (import locally to avoid circular dependencies)
    from app.ui.sidebar import render_sidebar

    render_sidebar(state)
    return state

