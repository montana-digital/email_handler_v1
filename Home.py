"""Root entrypoint for the Streamlit email handler app."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import home


def main() -> None:
    state = prepare_page()
    home.render(state)


if __name__ == "__main__":
    main()

