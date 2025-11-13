"""Streamlit multi-page entry for Deploy Scripts."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import deploy_scripts


def run() -> None:
    state = prepare_page()
    deploy_scripts.render(state)


run()

