"""Home page for the Email Handler app."""

from __future__ import annotations

import streamlit as st

from app.ui.state import AppState


def render(state: AppState) -> None:
    st.title("Email Handler")
    st.caption("Local review tool for parsed phishing emails and attachments.")

    st.subheader("Environment Summary")
    col1, col2, col3 = st.columns(3)
    col1.metric("Environment", state.config.env_name)
    col2.metric("Input Folder", str(state.config.input_dir))
    col3.metric("Database", state.config.database_url)

    st.subheader("Getting Started")
    st.markdown(
        """
        1. Use the **Deploy Scripts** page to launch a PowerShell helper that downloads email batches.
        2. Switch to **Email Display** to ingest the new batch, review parsed results, and perform edits.
        3. Visit **Attachments** for deep-dive analysis, packaging, and exports.
        4. Use **Settings** to adjust folder paths or database configuration.
        """
    )

    if state.notifications:
        with st.expander("Recent Notifications"):
            for note in state.notifications:
                st.info(note)

