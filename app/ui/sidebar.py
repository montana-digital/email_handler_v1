"""Global sidebar renderer shared across Streamlit pages."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union

import streamlit as st

from app.ui.state import AppState

APP_VERSION = "0.4.0"
LOGO_CANDIDATES = [
    Path("assets/logo.png"),
    Path("public/logo.png"),
    Path("SPEAR_transparent_cropped.png"),
]


def _find_logo() -> Optional[Path]:
    for candidate in LOGO_CANDIDATES:
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved
    return None


def _open_folder(path: Union[str, Path]) -> None:
    resolved = Path(path).resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(resolved))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(resolved)], check=False)
    else:
        subprocess.run(["xdg-open", str(resolved)], check=False)


def render_sidebar(state: AppState) -> None:
    st.sidebar.title("Email Handler")
    logo_path = _find_logo()
    if logo_path:
        st.sidebar.image(str(logo_path), use_container_width=True)
    st.sidebar.caption(f"Version {APP_VERSION}")
    st.sidebar.divider()

    st.sidebar.subheader("Quick Access")

    def _try_open(label: str, path: Union[str, Path]) -> None:
        try:
            _open_folder(path)
            state.add_notification(f"Opened {label.lower()} {path}")
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Failed to open {label.lower()}: {exc}")

    if st.sidebar.button("Open Input Folder", use_container_width=True):
        _try_open("input folder", state.config.input_dir)
    if st.sidebar.button("Open Output Folder", use_container_width=True):
        _try_open("output folder", state.config.output_dir)
    if st.sidebar.button("Open Cache Folder", use_container_width=True):
        _try_open("cache folder", state.config.pickle_cache_dir)
    if st.sidebar.button("Open Scripts Folder", use_container_width=True):
        _try_open("scripts folder", state.config.scripts_dir)

    db_path = state.config.database_url
    if db_path.startswith("sqlite:///"):
        db_file = Path(db_path.replace("sqlite:///", "")).expanduser()
        if st.sidebar.button("Open Database Location", use_container_width=True):
            _try_open("database location", db_file.parent if db_file.is_file() else db_file)

    if state.notifications:
        st.sidebar.divider()
        st.sidebar.subheader("Notifications")
        for note in state.notifications[-3:]:
            st.sidebar.info(note)

    st.sidebar.divider()
    st.sidebar.caption("Docs: `docs/setup_guide.md` · `docs/architecture.md`")

