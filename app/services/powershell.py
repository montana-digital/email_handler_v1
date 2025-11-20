"""Utilities for launching PowerShell scripts from the UI."""

from __future__ import annotations

import json
import platform
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Sequence

from loguru import logger

from app.config import AppConfig, PROJECT_ROOT, load_config

MANIFEST_FILENAME = "manifest.json"
PLACEHOLDER_MAP = {
    "%PROJECT_ROOT%": lambda cfg: PROJECT_ROOT,
    "%INPUT_DIR%": lambda cfg: cfg.input_dir,
    "%OUTPUT_DIR%": lambda cfg: cfg.output_dir,
    "%CACHE_DIR%": lambda cfg: cfg.pickle_cache_dir,
    "%SCRIPTS_DIR%": lambda cfg: cfg.scripts_dir,
    "%LOG_DIR%": lambda cfg: cfg.log_dir,
}


class PowerShellNotAvailableError(RuntimeError):
    """Raised when no PowerShell executable can be located."""


class PowerShellScriptError(RuntimeError):
    """Raised when a script execution fails."""


@dataclass(slots=True)
class PowerShellRunResult:
    """Outcome of executing a PowerShell script."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


@dataclass(slots=True)
class PowerShellScriptInfo:
    """Manifest metadata describing how to run a PowerShell script."""

    name: str
    display_name: str
    description: str | None = None
    default_arguments: str | None = None
    working_directory: str | None = None
    requires_confirmation: bool = False

    def resolved_working_directory(self, config: AppConfig) -> Path | None:
        if not self.working_directory:
            return None
        path = _apply_placeholders(self.working_directory, config)
        return Path(path).expanduser().resolve()


def _apply_placeholders(value: str, config: AppConfig) -> str:
    """Apply path placeholders, ensuring Windows paths are properly formatted."""
    resolved = value
    for placeholder, getter in PLACEHOLDER_MAP.items():
        if placeholder in resolved:
            path_value = getter(config)
            # Ensure path is resolved and uses proper format
            if isinstance(path_value, Path):
                path_str = str(path_value.resolve())
            else:
                path_str = str(path_value)
            resolved = resolved.replace(placeholder, path_str)
    return resolved


def load_manifest(
    config: AppConfig | None = None,
    *,
    manifest_path: Path | None = None,
) -> Dict[str, PowerShellScriptInfo]:
    cfg = config or load_config()
    path = manifest_path or (cfg.scripts_dir / MANIFEST_FILENAME)

    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load PowerShell manifest %s: %s", path, exc)
        return {}

    entries: Dict[str, PowerShellScriptInfo] = {}
    if isinstance(data, Mapping):
        iterator = data.items()
    elif isinstance(data, list):
        iterator = ((item.get("name"), item) for item in data if isinstance(item, Mapping))
    else:
        logger.warning("Unsupported manifest format in %s", path)
        return {}

    for name, payload in iterator:
        if not name:
            continue
        script_name = str(name)
        display_name = str(payload.get("displayName") or script_name)
        description = payload.get("description")
        default_args = payload.get("defaultArgs")
        working_dir = payload.get("workingDirectory")
        requires_confirmation = bool(payload.get("requiresConfirmation", False))
        entries[script_name] = PowerShellScriptInfo(
            name=script_name,
            display_name=display_name,
            description=description,
            default_arguments=default_args,
            working_directory=working_dir,
            requires_confirmation=requires_confirmation,
        )

    return entries


def _resolve_powershell_executable(explicit_path: str | None = None) -> str:
    """Resolve the path to the PowerShell executable."""
    if explicit_path:
        explicit = Path(explicit_path)
        if explicit.exists():
            return str(explicit)
        raise PowerShellNotAvailableError(f"PowerShell executable not found at {explicit}")

    for candidate in ("powershell.exe", "pwsh.exe", "pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise PowerShellNotAvailableError(
        "Unable to locate a PowerShell executable. Ensure PowerShell is installed and on PATH."
    )


def run_powershell_script(
    script_path: Path,
    *,
    arguments: Sequence[str] | None = None,
    timeout_seconds: int | None = None,
    execution_policy: str = "Bypass",
    powershell_path: str | None = None,
    working_directory: Path | None = None,
) -> PowerShellRunResult:
    """Execute a PowerShell script and capture its output."""
    resolved_script = script_path.resolve()

    if resolved_script.suffix.lower() != ".ps1":
        raise ValueError(f"Unsupported script type: {resolved_script}")
    if not resolved_script.exists():
        raise FileNotFoundError(f"PowerShell script not found: {resolved_script}")

    shell_executable = _resolve_powershell_executable(powershell_path)

    # Resolve working directory if provided
    resolved_working_dir = None
    if working_directory:
        resolved_working_dir = working_directory.resolve()
        if not resolved_working_dir.exists():
            logger.warning("Working directory does not exist: %s", resolved_working_dir)
            resolved_working_dir.mkdir(parents=True, exist_ok=True)

    command = [
        shell_executable,
        "-ExecutionPolicy",
        execution_policy,
        "-File",
        str(resolved_script),
    ]

    if arguments:
        command.extend(arguments)

    started_at = datetime.now(timezone.utc)
    start = time.monotonic()

    logger.info(
        "Launching PowerShell script: {} (cwd={})",
        shlex.join(command),
        str(resolved_working_dir) if resolved_working_dir else "default",
    )

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(resolved_working_dir) if resolved_working_dir else None,
        )
    except subprocess.TimeoutExpired as exc:  # noqa: PERF203 - streamlit triggers on main thread
        logger.error("PowerShell script timed out after {} seconds: {}", exc.timeout, resolved_script)
        raise PowerShellScriptError(f"Script timed out after {exc.timeout} seconds") from exc
    except FileNotFoundError as exc:
        logger.exception("Failed to start PowerShell script {}", resolved_script)
        raise PowerShellNotAvailableError(str(exc)) from exc

    finished_at = datetime.now(timezone.utc)
    duration_seconds = time.monotonic() - start

    result = PowerShellRunResult(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
    )

    if result.succeeded:
        logger.info("PowerShell script completed successfully: {}", resolved_script)
    else:
        logger.warning(
            "PowerShell script exited with code {}: {}\nSTDERR: {}",
            result.exit_code,
            resolved_script,
            result.stderr.strip(),
        )

    return result


def stream_powershell_script(
    script_path: Path,
    *,
    arguments: Sequence[str] | None = None,
    timeout_seconds: int | None = None,
    execution_policy: str = "Bypass",
    powershell_path: str | None = None,
    working_directory: Path | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> PowerShellRunResult:
    """Execute a PowerShell script while streaming stdout back to a callback."""
    resolved_script = script_path.resolve()
    if resolved_script.suffix.lower() != ".ps1":
        raise ValueError(f"Unsupported script type: {resolved_script}")
    if not resolved_script.exists():
        raise FileNotFoundError(f"PowerShell script not found: {resolved_script}")

    shell_executable = _resolve_powershell_executable(powershell_path)
    
    # Resolve working directory if provided
    resolved_working_dir = None
    if working_directory:
        resolved_working_dir = working_directory.resolve()
        if not resolved_working_dir.exists():
            logger.warning("Working directory does not exist: %s", resolved_working_dir)
            resolved_working_dir.mkdir(parents=True, exist_ok=True)
    
    command = [
        shell_executable,
        "-ExecutionPolicy",
        execution_policy,
        "-File",
        str(resolved_script),
    ]
    if arguments:
        command.extend(arguments)

    started_at = datetime.now(timezone.utc)
    start = time.monotonic()

    logger.info(
        "Streaming PowerShell script: {} (cwd={})",
        shlex.join(command),
        str(resolved_working_dir) if resolved_working_dir else "default",
    )

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(resolved_working_dir) if resolved_working_dir else None,
        )
    except FileNotFoundError as exc:
        logger.exception("Failed to start PowerShell script {}", resolved_script)
        raise PowerShellNotAvailableError(str(exc)) from exc

    collected: list[str] = []
    try:
        if process.stdout:
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                collected.append(line)
                if on_chunk:
                    on_chunk(line)
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        logger.error("PowerShell script timed out while streaming: {}", resolved_script)
        raise PowerShellScriptError("Script timed out while streaming output.")

    finished_at = datetime.now(timezone.utc)
    duration_seconds = time.monotonic() - start

    result = PowerShellRunResult(
        command=command,
        exit_code=process.returncode,
        stdout="".join(collected),
        stderr="",
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
    )

    if result.succeeded:
        logger.info("Streaming PowerShell script completed: {}", resolved_script)
    else:
        logger.warning("Streaming PowerShell script exited with %s: %s", result.exit_code, resolved_script)
    return result


def launch_powershell_window(
    script_path: Path,
    *,
    arguments: Sequence[str] | None = None,
    execution_policy: str = "Bypass",
    powershell_path: str | None = None,
    working_directory: Path | None = None,
) -> None:
    """Launch script in a detached PowerShell window (no output captured)."""
    resolved_script = script_path.resolve()
    if resolved_script.suffix.lower() != ".ps1":
        raise ValueError(f"Unsupported script type: {resolved_script}")
    if not resolved_script.exists():
        raise FileNotFoundError(f"PowerShell script not found: {resolved_script}")

    shell_executable = _resolve_powershell_executable(powershell_path)
    command = [
        shell_executable,
        "-NoExit",
        "-ExecutionPolicy",
        execution_policy,
        "-File",
        str(resolved_script),
    ]
    if arguments:
        command.extend(arguments)

    creationflags = 0
    if platform.system() == "Windows":
        creationflags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]

    subprocess.Popen(
        command,
        cwd=str(working_directory) if working_directory else None,
        creationflags=creationflags,
    )

