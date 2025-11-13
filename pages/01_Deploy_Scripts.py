"""Streamlit multipage entry for Deploy Scripts."""

from __future__ import annotations

from app.ui.bootstrap import prepare_page
from app.ui.pages import deploy_scripts


def main() -> None:
    state = prepare_page()
    deploy_scripts.render(state)


if __name__ == "__main__":
    main()

