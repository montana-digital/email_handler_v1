"""Global sidebar renderer shared across Streamlit pages."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Union

import streamlit as st

from app.ui.state import AppState


def _format_path(value: object, max_length: int = 60) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"...{text[-(max_length - 3):]}"


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
    st.sidebar.caption("Local phishing triage workspace")

    st.sidebar.subheader("Environment")
    st.sidebar.text(f"Env: {state.config.env_name}")
    st.sidebar.text(f"DB: {_format_path(state.config.database_url)}")

    st.sidebar.subheader("Directories")
    st.sidebar.markdown(
        "\n".join(
            [
                f"- 📥 `{_format_path(state.config.input_dir)}`",
                f"- 📦 `{_format_path(state.config.pickle_cache_dir)}`",
                f"- 📤 `{_format_path(state.config.output_dir)}`",
            ]
        ),
        help="Keep PowerShell scripts pointed at these locations.",
    )

    col_open_in, col_open_out = st.sidebar.columns(2)
    if col_open_in.button("Open Input", use_container_width=True):
        try:
            _open_folder(state.config.input_dir)
            state.add_notification(f"Opened input folder {state.config.input_dir}")
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Failed to open input folder: {exc}")
    if col_open_out.button("Open Output", use_container_width=True):
        try:
            _open_folder(state.config.output_dir)
            state.add_notification(f"Opened output folder {state.config.output_dir}")
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Failed to open output folder: {exc}")

    if state.notifications:
        st.sidebar.divider()
        st.sidebar.subheader("Notifications")
        for note in state.notifications[-3:]:
            st.sidebar.info(note)

    st.sidebar.divider()
    st.sidebar.caption("Docs: `docs/setup_guide.md` · `docs/architecture.md`")

