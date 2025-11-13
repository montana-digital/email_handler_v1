"""Streamlit multi-page entry for Email Display."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import email_display


def run() -> None:
    state = prepare_page()
    email_display.render(state)


run()

