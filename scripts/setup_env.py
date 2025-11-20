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


def discover_python_interpreters() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        if path.exists():
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(resolved)

    _add(Path(sys.executable))

    path_env = os.environ.get("PATH", "")
    for entry in path_env.split(os.pathsep):
        bin_path = Path(entry)
        python_names = ["python.exe", "python3.exe", "py.exe"] if platform.system() == "Windows" else ["python3", "python"]
        for name in python_names:
            _add(bin_path / name)

    # Add Windows Store python launcher if available
    if platform.system() == "Windows":
        py_launcher = shutil.which("py")
        if py_launcher:
            versions = ["3.11", "3.12", "3.10"]
            for version in versions:
                try:
                    result = subprocess.check_output([py_launcher, f"-{version}", "-c", "import sys; print(sys.executable)"])
                    interpreter = Path(result.decode("utf-8").strip())
                    _add(interpreter)
                except Exception:
                    continue

    # Deduplicate while preserving order
    unique_candidates = []
    seen = set()
    for interpreter in candidates:
        if interpreter not in seen:
            seen.add(interpreter)
            unique_candidates.append(interpreter)
    return unique_candidates


def select_python_interpreter(cli_override: Path | None) -> Path:
    if cli_override:
        return cli_override

    interpreters = discover_python_interpreters()
    if not interpreters:
        raise SystemExit("[setup] No Python interpreters were found on this system.")

    if len(interpreters) == 1:
        selected = interpreters[0]
        print(f"[setup] Using detected interpreter: {selected}")
        return selected

    print("[setup] Multiple Python interpreters detected. Select one:")
    for idx, interpreter in enumerate(interpreters, start=1):
        print(f"  {idx}. {interpreter}")

    while True:
        choice = input("Enter the number of the interpreter to use: ").strip()
        if not choice.isdigit():
            print("Please enter a number from the list.")
            continue
        index = int(choice)
        if 1 <= index <= len(interpreters):
            selected = interpreters[index - 1]
            print(f"[setup] Selected interpreter: {selected}")
            return selected
        print("Invalid selection. Try again.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the local Email Handler environment.")
    parser.add_argument(
        "--python",
        type=Path,
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


def verify_platform() -> None:
    if platform.system() != "Windows":
        raise SystemExit("[setup] This automation currently supports Windows environments only.")


def check_python_version(python_exec: Path) -> None:
    version_output = subprocess.check_output([str(python_exec), "-c", "import sys; print(sys.version)"]).decode("utf-8").strip()
    major_minor = subprocess.check_output([str(python_exec), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]).decode(
        "utf-8"
    ).strip()
    major, minor = map(int, major_minor.split("."))
    if (major, minor) < (3, 11):
        raise SystemExit("[setup] Python 3.11 or later is required to run this script.")
    print(f"[setup] Using bootstrap interpreter: {python_exec} (Python {version_output})")


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
    
    # Use absolute paths for better Windows compatibility
    # Paths are resolved relative to PROJECT_ROOT in load_config()
    db_path = (PROJECT_ROOT / "data" / "email_handler.db").resolve()
    # Convert Windows path to SQLite URL format (forward slashes)
    db_url = f"sqlite:///{str(db_path).replace(chr(92), '/')}"
    
    default_contents = "\n".join(
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


def venv_python_path(venv_path: Path) -> Path:
    scripts_dir = venv_path / ("Scripts" if platform.system() == "Windows" else "bin")
    python_name = "python.exe" if platform.system() == "Windows" else "python"
    python_executable = scripts_dir / python_name
    if not python_executable.exists():
        raise SystemExit(f"[setup] Could not find python executable at {python_executable}.")
    return python_executable


def install_requirements(venv_python: Path, requirements: Path, *, label: str, optional: bool = False) -> None:
    if not requirements.exists():
        if optional:
            print(f"[setup] Skipping {label} install; {requirements.name} not found.")
            return
        raise SystemExit(f"[setup] Required file {requirements} is missing.")

    run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    try:
        run_command([str(venv_python), "-m", "pip", "install", "-r", str(requirements)])
    except SystemExit:
        if optional:
            print(f"[setup] Failed to install optional {label} dependencies. Continue without them.")
            return
        raise


def main() -> None:
    verify_platform()
    args = parse_args()
    python_exec = select_python_interpreter(args.python)
    check_python_version(python_exec)
    ensure_runtime_directories()
    ensure_env_file()
    create_virtual_env(args.venv_dir, python_exec)

    if args.skip_install:
        print("[setup] Skipping dependency installation (--skip-install).")
        return

    venv_python = venv_python_path(args.venv_dir)
    install_requirements(venv_python, CORE_REQUIREMENTS, label="core runtime")
    if args.include_tests:
        install_requirements(venv_python, TEST_REQUIREMENTS, label="test", optional=True)

    activate_hint = (
        f"{args.venv_dir}\\Scripts\\Activate.ps1"
        if platform.system() == "Windows"
        else f"source {args.venv_dir}/bin/activate"
    )
    print(f"[setup] Environment ready. Activate with:\n    {activate_hint}")
    print("[setup] Launch app via: python scripts/run_app.py")


if __name__ == "__main__":
    main()

