"""Bootstrap a local virtual environment for the Email Handler app."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENV_DIR = PROJECT_ROOT / ".venv"
CORE_REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
TEST_REQUIREMENTS = PROJECT_ROOT / "requirements-test.txt"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_TEMPLATE_CANDIDATES = [PROJECT_ROOT / ".env.example", PROJECT_ROOT / "env.example"]

RUNTIME_DIRECTORIES = [
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "data" / "input",
    PROJECT_ROOT / "data" / "output",
    PROJECT_ROOT / "data" / "cache",
    PROJECT_ROOT / "data" / "logs",
    PROJECT_ROOT / "data" / "scripts",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the local Email Handler environment.")
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python interpreter that should be used to create the virtual environment.",
    )
    parser.add_argument(
        "--venv-dir",
        type=Path,
        default=DEFAULT_VENV_DIR,
        help="Directory for the virtual environment (default: .venv).",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Install optional test/development dependencies in addition to the core runtime packages.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Only create directories and the virtual environment without installing dependencies.",
    )
    return parser.parse_args()


def check_python_version(python_exec: Path) -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("[setup] Python 3.11 or later is required to run this script.")
    print(f"[setup] Using bootstrap interpreter: {python_exec} (Python {platform.python_version()})")


def ensure_runtime_directories() -> None:
    for directory in RUNTIME_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
    print("[setup] Ensured runtime directories exist under data/.")


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    for candidate in ENV_TEMPLATE_CANDIDATES:
        if candidate.exists():
            ENV_FILE.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[setup] Created .env from template {candidate.name}.")
            return
    default_contents = "\n".join(
        [
            "EMAIL_HANDLER_DATABASE_URL=sqlite:///data/email_handler.db",
            "EMAIL_HANDLER_INPUT_DIR=data/input",
            "EMAIL_HANDLER_OUTPUT_DIR=data/output",
            "EMAIL_HANDLER_CACHE_DIR=data/cache",
            "EMAIL_HANDLER_SCRIPTS_DIR=data/scripts",
            "EMAIL_HANDLER_LOG_DIR=data/logs",
            "EMAIL_HANDLER_ENV=local",
        ]
    )
    ENV_FILE.write_text(default_contents + "\n", encoding="utf-8")
    print("[setup] Created .env with default values.")


def run_command(command: list[str], *, allow_failure: bool = False) -> None:
    print(f"[setup] Executing: {' '.join(command)}")
    try:
        subprocess.check_call(command)
    except subprocess.CalledProcessError as exc:
        if allow_failure:
            print(f"[setup] Command failed (allowed to continue): {exc}")
            return
        raise SystemExit(f"[setup] Command failed with exit code {exc.returncode}.") from exc


def create_virtual_env(venv_path: Path, python_exec: Path) -> None:
    if venv_path.exists():
        print(f"[setup] Virtual environment already exists at {venv_path}")
        return
    run_command([str(python_exec), "-m", "venv", str(venv_path)])
    print(f"[setup] Created virtual environment at {venv_path}")


def pip_path(venv_path: Path) -> Path:
    scripts_dir = venv_path / ("Scripts" if platform.system() == "Windows" else "bin")
    pip_name = "pip.exe" if platform.system() == "Windows" else "pip"
    pip_executable = scripts_dir / pip_name
    if not pip_executable.exists():
        raise SystemExit(f"[setup] Could not find pip executable at {pip_executable}.")
    return pip_executable


def install_requirements(pip_executable: Path, requirements: Path, *, label: str, optional: bool = False) -> None:
    if not requirements.exists():
        if optional:
            print(f"[setup] Skipping {label} install; {requirements.name} not found.")
            return
        raise SystemExit(f"[setup] Required file {requirements} is missing.")

    run_command([str(pip_executable), "install", "--upgrade", "pip"])
    try:
        run_command([str(pip_executable), "install", "-r", str(requirements)])
    except SystemExit:
        if optional:
            print(f"[setup] Failed to install optional {label} dependencies. Continue without them.")
            return
        raise


def main() -> None:
    args = parse_args()
    check_python_version(args.python)
    ensure_runtime_directories()
    ensure_env_file()
    create_virtual_env(args.venv_dir, args.python)

    if args.skip_install:
        print("[setup] Skipping dependency installation (--skip-install).")
        return

    pip_executable = pip_path(args.venv_dir)
    install_requirements(pip_executable, CORE_REQUIREMENTS, label="core runtime")
    if args.include_tests:
        install_requirements(pip_executable, TEST_REQUIREMENTS, label="test", optional=True)

    activate_hint = (
        f"{args.venv_dir}\\Scripts\\Activate.ps1"
        if platform.system() == "Windows"
        else f"source {args.venv_dir}/bin/activate"
    )
    print(f"[setup] Environment ready. Activate with:\n    {activate_hint}")
    print("[setup] Launch app via: python scripts/run_app.py")


if __name__ == "__main__":
    main()

