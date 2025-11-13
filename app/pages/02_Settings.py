"""Streamlit multi-page entry for Settings."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import settings


def run() -> None:
    state = prepare_page()
    settings.render(state)


run()

