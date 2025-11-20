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
ENV_FILE = PROJECT_ROOT / ".env"
ENV_TEMPLATE_CANDIDATES = [PROJECT_ROOT / ".env.example", PROJECT_ROOT / "env.example"]


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


def verify_platform() -> None:
    if platform.system() != "Windows":
        raise SystemExit("[run-app] This launcher currently supports Windows environments only.")


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    for candidate in ENV_TEMPLATE_CANDIDATES:
        if candidate.exists():
            ENV_FILE.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[run-app] Created .env from template {candidate.name}.")
            return
    
    # Use absolute paths for better Windows compatibility
    # Paths are resolved relative to PROJECT_ROOT in load_config()
    db_path = (PROJECT_ROOT / "data" / "email_handler.db").resolve()
    # Convert Windows path to SQLite URL format (forward slashes)
    db_url = f"sqlite:///{str(db_path).replace(chr(92), '/')}"
    
    ENV_FILE.write_text(
        "\n".join(
            [
                f"EMAIL_HANDLER_DATABASE_URL={db_url}",
                "EMAIL_HANDLER_INPUT_DIR=data/input",
                "EMAIL_HANDLER_OUTPUT_DIR=data/output",
                "EMAIL_HANDLER_CACHE_DIR=data/cache",
                "EMAIL_HANDLER_SCRIPTS_DIR=data/scripts",
                "EMAIL_HANDLER_LOG_DIR=data/logs",
                "EMAIL_HANDLER_ENV=local",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print("[run-app] Created default .env configuration.")


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
    verify_platform()
    args = parse_args()
    ensure_environment(args)
    ensure_env_file()
    verify_streamlit_available()
    launch_streamlit(args.streamlit_args)


if __name__ == "__main__":
    main()

