"""Helpers to initialize shared state for every Streamlit page."""

from __future__ import annotations

import streamlit as st

from app.config import load_config
from app.db import init_db
from app.ui.state import AppState, get_state


def _ensure_page_config() -> None:
    if st.session_state.get("_eh_page_configured"):
        return
    st.set_page_config(page_title="Email Handler", layout="wide")
    st.session_state["_eh_page_configured"] = True


def prepare_page() -> AppState:
    _ensure_page_config()

    config = load_config()
    init_db()
    state = get_state(config=config)

    # Render shared sidebar (import locally to avoid circular dependencies)
    from app.ui.sidebar import render_sidebar

    render_sidebar(state)
    return state

