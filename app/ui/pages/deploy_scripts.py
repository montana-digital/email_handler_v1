"""Deploy Scripts page with PowerShell execution flow."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path
from typing import Dict, Optional

import streamlit as st
from loguru import logger

from app.services.powershell import (
    PowerShellNotAvailableError,
    PowerShellScriptError,
    PowerShellRunResult,
    PowerShellScriptInfo,
    launch_powershell_window,
    load_manifest,
    run_powershell_script,
    stream_powershell_script,
)
from app.ui.state import AppState


def _persist_uploaded_script(upload, target_dir: Path, filename: str | None = None) -> Path:
    """Persist an uploaded file to disk.
    
    Args:
        upload: Streamlit UploadedFile object
        target_dir: Directory to save the file
        filename: Optional filename (if not provided, uses upload.name)
    
    Returns:
        Path to the saved file
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Use provided filename or try to get from upload object
    if filename:
        file_name = filename
    else:
        try:
            file_name = upload.name
        except (AttributeError, RuntimeError) as exc:
            # File may have been cleared from memory
            logger.error("Failed to get filename from upload object: %s", exc)
            raise ValueError("Uploaded file is no longer available. Please upload again.") from exc
    
    destination = target_dir / file_name
    
    try:
        # Read the file content before it's cleared from memory
        file_content = upload.read()
        with destination.open("wb") as f:
            f.write(file_content)
    except (AttributeError, RuntimeError, OSError) as exc:
        logger.exception("Failed to persist uploaded file: %s", exc)
        raise ValueError(f"Failed to save file: {exc}") from exc
    
    return destination


@st.fragment
def _execute_script_fragment(
    state: AppState,
    selected_script: Path,
    manifest_info: Optional[PowerShellScriptInfo],
    argument_list: list[str],
    working_path: Optional[Path],
    stream_output: bool,
) -> Optional[PowerShellRunResult]:
    log_state = state.get_fragment_state(
        f"script_log::{selected_script.name}",
        {"lines": []},
    )
    log_placeholder = st.empty()

    def _append_line(chunk: str) -> None:
        lines = log_state["lines"]
        lines.append(chunk.rstrip("\n"))
        log_state["lines"] = lines[-200:]
        log_placeholder.code("\n".join(log_state["lines"]), language="powershell")

    with st.status("Executing PowerShell script…", expanded=True) as status:
        try:
            if stream_output:
                log_state["lines"] = []
                result = stream_powershell_script(
                    selected_script,
                    arguments=argument_list,
                    working_directory=working_path,
                    on_chunk=_append_line,
                )
            else:
                result = run_powershell_script(
                    selected_script,
                    arguments=argument_list,
                    working_directory=working_path,
                )
        except PowerShellNotAvailableError as exc:
            status.update(label="PowerShell not available", state="error")
            st.error(str(exc))
            return None
        except PowerShellScriptError as exc:
            status.update(label="Script execution timed out", state="error")
            st.error(str(exc))
            return None
        except FileNotFoundError as exc:
            status.update(label="Script not found", state="error")
            st.error(str(exc))
            return None

    summary_message = (
        f"Script completed in {result.duration_seconds:.2f}s (exit code {result.exit_code})."
    )
    if result.succeeded:
        st.success(summary_message)
    else:
        st.error(summary_message)

    if stream_output and log_state["lines"]:
        st.code("\n".join(log_state["lines"]), language="powershell")
    else:
        st.markdown("**STDOUT**")
        st.text(result.stdout or "<no output>")
        if result.stderr:
            st.markdown("**STDERR**")
            st.text(result.stderr)

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
    return result


def render(state: AppState) -> None:
    st.header("Deploy Scripts")
    st.write(
        "Upload PowerShell scripts that retrieve email batches. "
        "Saved scripts become launchable utilities for end users."
    )

    st.subheader("Upload New Scripts")
    with st.expander("Add or replace PowerShell scripts", expanded=False):
        uploaded = st.file_uploader("Upload .ps1 script", type=["ps1"], key="script_uploader")
        if uploaded:
            # Capture filename immediately before persisting (to avoid memory_media_file_storage errors)
            # Access upload.name immediately while the file is still in memory
            try:
                filename = uploaded.name
            except (AttributeError, RuntimeError) as exc:
                logger.error("Failed to get filename from upload: %s", exc)
                st.error("Uploaded file is no longer available. Please upload again.")
                st.stop()
            
            try:
                saved_path = _persist_uploaded_script(uploaded, state.config.scripts_dir, filename=filename)
                st.success(f"Saved script to {saved_path}")
                state.add_notification(f"Script uploaded: {filename}")
                # Clear the uploader after successful save to prevent re-processing
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                logger.exception("Failed to persist uploaded script: %s", exc)
                st.error(f"Failed to save script: {exc}")

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

    default_workdir = (
        manifest_info.resolved_working_directory(state.config)
        if manifest_info
        else state.config.input_dir
    )
    script_state = state.get_fragment_state(
        f"deploy_script::{selected_name}",
        {
            "args": manifest_info.default_arguments if manifest_info else "",
            "working_dir": str(default_workdir) if default_workdir else "",
            "stream_output": True,
            "launch_external": False,
        },
    )

    with st.expander("Other Settings", expanded=False):
        script_state["working_dir"] = st.text_input(
            "Working Directory",
            value=script_state["working_dir"],
            help="Script runs with this working directory. Leave blank to inherit the app's process directory.",
        )
        script_state["args"] = st.text_input(
            "Script Arguments",
            value=script_state["args"],
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

    script_state["stream_output"] = st.checkbox(
        "Stream output in-app (read-only)", value=script_state["stream_output"]
    )
    script_state["launch_external"] = st.checkbox(
        "Launch in separate PowerShell window", value=script_state["launch_external"]
    )

    disabled = False
    if manifest_info and manifest_info.requires_confirmation and not confirmation_ok:
        disabled = True
    run_button = st.button("Run Script", type="primary", disabled=disabled)
    if run_button:
        arg_text = script_state["args"]
        working_dir_text = script_state["working_dir"]

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

        if script_state["launch_external"]:
            try:
                launch_powershell_window(
                    selected_script,
                    arguments=argument_list,
                    working_directory=working_path,
                )
                st.info("Script launched in a separate PowerShell window. Monitor the window for progress and close it when complete.")
            except (PowerShellNotAvailableError, FileNotFoundError) as exc:
                st.error(str(exc))
            return
        result = _execute_script_fragment(
            state,
            selected_script,
            manifest_info,
            argument_list,
            working_path,
            script_state["stream_output"],
        )
        if result is None:
            return

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
