"""Streamlit multipage entry for Database Display."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import database_display


def main() -> None:
    state = prepare_page()
    database_display.render(state)


if __name__ == "__main__":
    main()


