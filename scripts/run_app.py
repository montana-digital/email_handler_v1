"""
Launch the Streamlit Email Handler app.

Usage (PowerShell):
    python scripts/run_app.py
    python scripts/run_app.py --setup-if-missing
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = PROJECT_ROOT / ".venv"
APP_ENTRY = PROJECT_ROOT / "Home.py"


def get_streamlit_executable() -> Path:
    scripts_dir = VENV_DIR / ("Scripts" if platform.system() == "Windows" else "bin")
    executable = scripts_dir / ("streamlit.exe" if platform.system() == "Windows" else "streamlit")
    return executable


def ensure_environment(args: argparse.Namespace) -> None:
    if VENV_DIR.exists() and get_streamlit_executable().exists():
        return

    if not args.setup_if_missing:
        raise SystemExit(
            "Virtual environment or Streamlit executable not found. "
            "Run `python scripts/setup_env.py` or rerun with --setup-if-missing."
        )

    subprocess.check_call([sys.executable, str(PROJECT_ROOT / "scripts" / "setup_env.py")])


def launch_streamlit(extra_args: list[str]) -> None:
    extra_args = [arg for arg in extra_args if arg != "--"]
    streamlit_exe = get_streamlit_executable()
    if not streamlit_exe.exists():
        raise SystemExit("Streamlit executable not found in virtual environment.")

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(PROJECT_ROOT))

    command = [str(streamlit_exe), "run", str(APP_ENTRY), "--server.headless", "true", *extra_args]
    print(f"[run-app] Executing: {' '.join(command)}")
    subprocess.check_call(command, env=env)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Streamlit Email Handler app.")
    parser.add_argument(
        "--setup-if-missing",
        action="store_true",
        help="Run setup_env.py automatically if the virtual environment is missing.",
    )
    parser.add_argument(
        "streamlit_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments passed directly to `streamlit run`.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_environment(args)
    launch_streamlit(args.streamlit_args)


if __name__ == "__main__":
    main()

