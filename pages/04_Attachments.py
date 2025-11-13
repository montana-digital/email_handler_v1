"""Streamlit multipage entry for Attachments."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import attachments


def main() -> None:
    state = prepare_page()
    attachments.render(state)


if __name__ == "__main__":
    main()

