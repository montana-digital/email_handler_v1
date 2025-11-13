"""Streamlit multi-page entry for Attachments."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import attachments


def run() -> None:
    state = prepare_page()
    attachments.render(state)


run()

