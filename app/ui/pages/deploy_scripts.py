"""Deploy Scripts page with PowerShell execution flow."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path
from typing import Dict

import streamlit as st

from app.services.powershell import (
    PowerShellNotAvailableError,
    PowerShellScriptError,
    PowerShellRunResult,
    PowerShellScriptInfo,
    load_manifest,
    run_powershell_script,
)
from app.ui.state import AppState


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

    st.subheader("Upload New Scripts")
    with st.expander("Add or replace PowerShell scripts", expanded=False):
        uploaded = st.file_uploader("Upload .ps1 script", type=["ps1"])
        if uploaded:
            saved_path = _persist_uploaded_script(uploaded, state.config.scripts_dir)
            st.success(f"Saved script to {saved_path}")
            state.add_notification(f"Script uploaded: {uploaded.name}")

    scripts = sorted(state.config.scripts_dir.glob("*.ps1"))
    if not scripts:
        st.info("No scripts found. Upload a `.ps1` file to get started.")
        return

    manifest: Dict[str, PowerShellScriptInfo] = load_manifest(state.config)

    st.subheader("Available Scripts")
    st.caption("Choose a script below to review its metadata, adjust optional settings, and execute it.")

    def _script_label(script: Path) -> str:
        info = manifest.get(script.name)
        if info:
            return f"{info.display_name} ({script.name})"
        return script.name

    script_options = {script.name: script for script in scripts}
    selected_name = st.selectbox(
        "Available Scripts",
        options=list(script_options.keys()),
        format_func=lambda key: _script_label(script_options[key]),
    )

    selected_script = script_options[selected_name]
    manifest_info = manifest.get(selected_script.name)

    st.markdown(f"### {manifest_info.display_name if manifest_info else selected_script.name}")
    if manifest_info and manifest_info.description:
        st.write(manifest_info.description)
    if not manifest_info:
        st.info("No manifest metadata found for this script. Using defaults.")

    st.caption(f"Script path: `{selected_script}`")

    args_key = f"script_args_{selected_name}"
    if args_key not in st.session_state:
        st.session_state[args_key] = manifest_info.default_arguments if manifest_info else ""

    working_dir_key = f"script_workdir_{selected_name}"
    if manifest_info:
        default_workdir = manifest_info.resolved_working_directory(state.config)
    else:
        default_workdir = state.config.input_dir
    if working_dir_key not in st.session_state:
        st.session_state[working_dir_key] = str(default_workdir) if default_workdir else ""

    with st.expander("Other Settings", expanded=False):
        st.text_input(
            "Working Directory",
            key=working_dir_key,
            help="Script runs with this working directory. Leave blank to inherit the app's process directory.",
        )
        st.text_input(
            "Script Arguments",
            key=args_key,
            help="Arguments are split using Windows-style quoting. Leave blank for none.",
        )

    confirmation_ok = True
    if manifest_info and manifest_info.requires_confirmation:
        confirm_key = f"script_confirm_{selected_name}"
        st.warning(
            "This script requires confirmation before execution. Ensure you understand its effects.",
            icon="⚠️",
        )
        confirmation_ok = st.checkbox(
            "I confirm I want to run this script",
            key=confirm_key,
        )

    disabled = False
    if manifest_info and manifest_info.requires_confirmation and not confirmation_ok:
        disabled = True
    run_button = st.button("Run Script", type="primary", disabled=disabled)
    if run_button:
        arg_text = st.session_state.get(args_key, "")
        working_dir_text = st.session_state.get(working_dir_key, "")

        try:
            argument_list = shlex.split(arg_text, posix=False) if arg_text.strip() else []
        except ValueError as exc:
            st.error(f"Unable to parse arguments: {exc}")
            return

        working_path = None
        if working_dir_text:
            try:
                working_path = Path(working_dir_text).expanduser().resolve()
                working_path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Unable to prepare working directory '{working_dir_text}': {exc}")
                return

        with st.status("Executing PowerShell script…", expanded=True) as status:
            try:
                result = run_powershell_script(
                    selected_script,
                    arguments=argument_list,
                    working_directory=working_path,
                )
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
                "display_name": manifest_info.display_name if manifest_info else selected_script.name,
                "description": manifest_info.description if manifest_info else None,
                "path": str(selected_script),
                "working_directory": str(working_path) if working_path else None,
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
        for run in reversed(state.script_runs):
            result: PowerShellRunResult = run["result"]
            title = run.get("display_name") or run["script"]
            expander_label = f"{title} • exit {result.exit_code} • {result.finished_at.isoformat()}"
            with st.expander(expander_label):
                st.markdown(f"**Script:** `{run['script']}`")
                if run.get("description"):
                    st.markdown(run["description"])
                if run.get("working_directory"):
                    st.markdown(f"**Working Directory:** `{run['working_directory']}`")
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
