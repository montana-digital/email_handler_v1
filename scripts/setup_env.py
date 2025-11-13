"""
Local environment bootstrapper for the Streamlit Email Handler app.

Usage (PowerShell):
    python scripts/setup_env.py
    python scripts/setup_env.py --python "C:\\Path\\to\\python.exe"

The script will:
1. Create a virtual environment under `.venv`.
2. Install required dependencies.
3. Prepare expected runtime directories (data/, logs/, etc.).
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENV_DIR = PROJECT_ROOT / ".venv"
DEFAULT_REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"

RUNTIME_DIRECTORIES = [
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "data" / "input",
    PROJECT_ROOT / "data" / "output",
    PROJECT_ROOT / "data" / "cache",
    PROJECT_ROOT / "data" / "logs",
    PROJECT_ROOT / "data" / "scripts",
    PROJECT_ROOT / "app",
    PROJECT_ROOT / "app" / "ui",
    PROJECT_ROOT / "app" / "db",
    PROJECT_ROOT / "app" / "services",
    PROJECT_ROOT / "app" / "parsers",
    PROJECT_ROOT / "tests",
]

DEFAULT_DEPENDENCIES = [
    "streamlit>=1.40.0",
    "sqlalchemy>=2.0.29",
    "pydantic>=2.7.0",
    "phonenumbers>=8.13.41",
    "tldextract>=5.1.2",
    "python-dotenv>=1.0.1",
    "loguru>=0.7.2",
    "extract-msg>=0.48.4",
    "watchdog>=4.0.0",
    "pandas>=2.1.0",
    "pytest>=8.2.0",
    "pytest-mock>=3.14.0",
    "requests>=2.32.0",
    "beautifulsoup4>=4.12.0",
]


def ensure_requirements_file(path: Path) -> None:
    if path.exists():
        return
    content = "\n".join(sorted(DEFAULT_DEPENDENCIES)) + "\n"
    path.write_text(content, encoding="utf-8")
    print(f"[setup] Created default requirements file at {path}")


def run_command(command: list[str], env: dict | None = None) -> None:
    print(f"[setup] Executing: {' '.join(command)}")
    try:
        subprocess.check_call(command, env=env)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"[setup] Command failed with exit code {exc.returncode}: {command}") from exc


def create_virtual_env(venv_path: Path, python_executable: Path) -> None:
    if venv_path.exists():
        print(f"[setup] Virtual environment already exists at {venv_path}")
        return

    run_command([str(python_executable), "-m", "venv", str(venv_path)])
    print(f"[setup] Created virtual environment at {venv_path}")


def install_dependencies(venv_path: Path, requirements_file: Path) -> None:
    pip_executable = venv_path / ("Scripts" if platform.system() == "Windows" else "bin") / (
        "pip.exe" if platform.system() == "Windows" else "pip"
    )
    if not pip_executable.exists():
        raise SystemExit(f"[setup] pip executable not found at {pip_executable}. Was the venv created correctly?")

    run_command([str(pip_executable), "install", "--upgrade", "pip"])
    run_command([str(pip_executable), "install", "-r", str(requirements_file)])


def ensure_directories() -> None:
    for directory in RUNTIME_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").touch(exist_ok=True)
    print("[setup] Ensured project runtime directories.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap local development environment.")
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python interpreter to use for creating the virtual environment.",
    )
    parser.add_argument(
        "--venv-dir",
        type=Path,
        default=DEFAULT_VENV_DIR,
        help="Directory where the virtual environment should be created.",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS_FILE,
        help="Path to pip requirements file.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Create folders and venv, but skip installing dependencies.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_directories()
    ensure_requirements_file(args.requirements)
    create_virtual_env(args.venv_dir, args.python)

    if args.skip_install:
        print("[setup] Skipping dependency installation as requested.")
        return

    install_dependencies(args.venv_dir, args.requirements)
    print("[setup] Environment ready. Activate venv with:")
    if platform.system() == "Windows":
        print(f"    {args.venv_dir}\\Scripts\\Activate.ps1")
    else:
        print(f"    source {args.venv_dir}/bin/activate")


if __name__ == "__main__":
    main()

