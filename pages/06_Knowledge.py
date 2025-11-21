"""Streamlit multipage entry for Knowledge."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import knowledge


def main() -> None:
    state = prepare_page()
    knowledge.render(state)


if __name__ == "__main__":
    main()

