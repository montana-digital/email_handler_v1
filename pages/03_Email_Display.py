"""Streamlit multipage entry for Email Display."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import email_display


def main() -> None:
    state = prepare_page()
    email_display.render(state)


if __name__ == "__main__":
    main()

