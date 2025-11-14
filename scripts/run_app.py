"""Launch the Streamlit Email Handler app using the managed virtual environment."""

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
SETUP_SCRIPT = PROJECT_ROOT / "scripts" / "setup_env.py"


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
        help="Arguments forwarded to `streamlit run` (prefix with `--`).",
    )
    return parser.parse_args()


def venv_python() -> Path:
    scripts_dir = VENV_DIR / ("Scripts" if platform.system() == "Windows" else "bin")
    python_name = "python.exe" if platform.system() == "Windows" else "python"
    python_path = scripts_dir / python_name
    if not python_path.exists():
        raise SystemExit("[run-app] Virtual environment is missing. Run `python scripts/setup_env.py` first.")
    return python_path


def ensure_environment(args: argparse.Namespace) -> None:
    if VENV_DIR.exists():
        return
    if not args.setup_if_missing:
        raise SystemExit(
            "[run-app] Virtual environment not found. "
            "Run `python scripts/setup_env.py` or re-run with --setup-if-missing."
        )
    print("[run-app] Virtual environment missing; running setup_env.py ...")
    subprocess.check_call([sys.executable, str(SETUP_SCRIPT)])


def verify_streamlit_available() -> None:
    python_bin = venv_python()
    try:
        subprocess.check_call(
            [str(python_bin), "-c", "import streamlit"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "[run-app] Streamlit is not installed in the virtual environment. "
            "Run `python scripts/setup_env.py`."
        ) from exc


def launch_streamlit(extra_args: list[str]) -> None:
    python_bin = venv_python()
    passthrough = [arg for arg in extra_args if arg != "--"]

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(PROJECT_ROOT))

    command = [
        str(python_bin),
        "-m",
        "streamlit",
        "run",
        str(APP_ENTRY),
        "--server.headless",
        "true",
        *passthrough,
    ]
    print(f"[run-app] Executing: {' '.join(command)}")
    subprocess.check_call(command, env=env)


def main() -> None:
    args = parse_args()
    ensure_environment(args)
    verify_streamlit_available()
    launch_streamlit(args.streamlit_args)


if __name__ == "__main__":
    main()

