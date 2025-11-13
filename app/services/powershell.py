"""Utilities for launching PowerShell scripts from the UI."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from loguru import logger


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
) -> PowerShellRunResult:
    """Execute a PowerShell script and capture its output."""
    resolved_script = script_path.resolve()

    if resolved_script.suffix.lower() != ".ps1":
        raise ValueError(f"Unsupported script type: {resolved_script}")
    if not resolved_script.exists():
        raise FileNotFoundError(f"PowerShell script not found: {resolved_script}")

    shell_executable = _resolve_powershell_executable(powershell_path)

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

    logger.info("Launching PowerShell script: {}", shlex.join(command))

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
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

