"""Streamlit multipage entry for Settings."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import settings


def main() -> None:
    state = prepare_page()
    settings.render(state)


if __name__ == "__main__":
    main()

