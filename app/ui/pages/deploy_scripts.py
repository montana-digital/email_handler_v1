"""Deploy Scripts page with PowerShell execution flow."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

import streamlit as st

from app.ui.state import AppState
from app.services.powershell import (
    PowerShellNotAvailableError,
    PowerShellScriptError,
    PowerShellRunResult,
    run_powershell_script,
)


def _persist_uploaded_script(upload, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / upload.name
    with destination.open("wb") as f:
        shutil.copyfileobj(upload, f)
    return destination


def render(state: AppState) -> None:
    st.header("Deploy Scripts")
    st.write(
        "Upload PowerShell scripts that retrieve email batches. "
        "Saved scripts become launchable utilities for end users."
    )

    uploaded = st.file_uploader("Upload .ps1 script", type=["ps1"])
    if uploaded:
        saved_path = _persist_uploaded_script(uploaded, state.config.scripts_dir)
        st.success(f"Saved script to {saved_path}")
        state.add_notification(f"Script uploaded: {uploaded.name}")

    scripts = sorted(state.config.scripts_dir.glob("*.ps1"))
    if not scripts:
        st.info("No scripts found. Upload a `.ps1` file to get started.")
        return

    script_options = {script.name: script for script in scripts}
    selected_name = st.selectbox("Available Scripts", options=list(script_options.keys()))

    selected_script = script_options[selected_name]
    st.code(str(selected_script), language="powershell")

    arg_text = st.text_input(
        "Optional script arguments",
        placeholder="-InputPath C:\\Emails -Verbose",
        help="Arguments are split using Windows-style quoting. Leave blank for none.",
    )

    run_button = st.button("Run Script", type="primary")
    if run_button:
        try:
            argument_list = shlex.split(arg_text, posix=False) if arg_text.strip() else []
        except ValueError as exc:
            st.error(f"Unable to parse arguments: {exc}")
            return

        with st.status("Executing PowerShell script…", expanded=True) as status:
            try:
                result = run_powershell_script(selected_script, arguments=argument_list)
            except PowerShellNotAvailableError as exc:
                status.update(label="PowerShell not available", state="error")
                st.error(str(exc))
                return
            except PowerShellScriptError as exc:
                status.update(label="Script execution timed out", state="error")
                st.error(str(exc))
                return
            except FileNotFoundError as exc:
                status.update(label="Script not found", state="error")
                st.error(str(exc))
                return

        state.record_script_run(
            {
                "script": selected_script.name,
                "path": str(selected_script),
                "arguments": argument_list,
                "result": result,
            }
        )

        summary_message = (
            f"Script completed in {result.duration_seconds:.2f}s (exit code {result.exit_code})."
        )
        if result.succeeded:
            st.success(summary_message)
        else:
            st.error(summary_message)

        st.subheader("Script Output")
        st.markdown("**STDOUT**")
        st.text(result.stdout or "<no output>")
        if result.stderr:
            st.markdown("**STDERR**")
            st.text(result.stderr)

    if state.script_runs:
        st.subheader("Run History (session)")
        for run in reversed(state.script_runs[-5:]):
            result: PowerShellRunResult = run["result"]
            with st.expander(f"{run['script']} • exit {result.exit_code} • {result.finished_at.isoformat()}"):
                st.markdown(f"**Path:** `{run['path']}`")
                st.markdown(f"**Arguments:** `{ ' '.join(run['arguments']) or '<none>' }`")
                st.markdown(
                    f"**Started:** {result.started_at.isoformat()}  \n"
                    f"**Finished:** {result.finished_at.isoformat()}  \n"
                    f"**Duration:** {result.duration_seconds:.2f}s"
                )
                st.markdown("**STDOUT**")
                st.text(result.stdout or "<no output>")
                if result.stderr:
                    st.markdown("**STDERR**")
                    st.text(result.stderr)
