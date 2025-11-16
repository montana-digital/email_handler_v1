"""Global sidebar renderer shared across Streamlit pages."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Union
import time

import streamlit as st

from app.config import PROJECT_ROOT
from app.services.parsing import parser_capabilities
from app.ui.state import AppState

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    psutil = None

APP_VERSION = "0.4.0"
LOGO_CANDIDATES = [
    Path("assets/logo.png"),
    Path("public/logo.png"),
    Path("SPEAR_transparent_cropped.png"),
]


def _find_logo() -> Optional[Path]:
    for candidate in LOGO_CANDIDATES:
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved
    return None


def _open_folder(path: Union[str, Path]) -> None:
    resolved = Path(path).resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(resolved))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(resolved)], check=False)
    else:
        subprocess.run(["xdg-open", str(resolved)], check=False)


def _format_bytes(value: int) -> str:
    if value < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _directory_size(root: Path) -> int:
    total = 0
    for entry in root.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


@st.cache_resource
def _resource_cache() -> Dict[str, float | Dict[str, Optional[float]]]:
    return {"timestamp": 0.0, "data": {}}


def _resource_snapshot(project_root: str, database_url: str) -> Dict[str, Optional[float]]:
    cache = _resource_cache()
    if time.time() - cache["timestamp"] > 60 or not cache["data"]:
        cache["data"] = _compute_resource_snapshot(project_root, database_url)
        cache["timestamp"] = time.time()
    return cache["data"]  # type: ignore[return-value]


def _compute_resource_snapshot(project_root: str, database_url: str) -> Dict[str, Optional[float]]:
    root_path = Path(project_root)
    app_size = _directory_size(root_path)

    disk_usage = shutil.disk_usage(root_path)

    db_size = None
    db_file = None
    if database_url.startswith("sqlite:///"):
        db_file = Path(database_url.replace("sqlite:///", "")).expanduser()
        if db_file.exists():
            try:
                db_size = db_file.stat().st_size
            except OSError:
                db_size = None

    cpu_percent = None
    memory_percent = None
    process_memory = None
    if psutil is not None:  # pragma: no branch
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent
            process_memory = psutil.Process(os.getpid()).memory_info().rss
        except Exception:  # noqa: BLE001 - fallback to None on psutil errors
            cpu_percent = memory_percent = process_memory = None

    return {
        "app_size": float(app_size),
        "disk_total": float(disk_usage.total),
        "disk_used": float(disk_usage.used),
        "disk_free": float(disk_usage.free),
        "db_size": float(db_size) if db_size is not None else None,
        "db_path": str(db_file) if db_file else None,
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "process_memory": float(process_memory) if process_memory is not None else None,
        "psutil_available": psutil is not None,
    }


def render_sidebar(state: AppState) -> None:
    st.sidebar.title("Email Handler")
    logo_path = _find_logo()
    if logo_path:
        st.sidebar.image(str(logo_path), width="stretch")
    st.sidebar.caption(f"Version {APP_VERSION}")
    st.sidebar.divider()

    st.sidebar.subheader("Quick Access")

    def _try_open(label: str, path: Union[str, Path]) -> None:
        try:
            _open_folder(path)
            state.add_notification(f"Opened {label.lower()} {path}")
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Failed to open {label.lower()}: {exc}")

    if st.sidebar.button("Open Input Folder", width="stretch"):
        _try_open("input folder", state.config.input_dir)
    if st.sidebar.button("Open Output Folder", width="stretch"):
        _try_open("output folder", state.config.output_dir)
    if st.sidebar.button("Open Cache Folder", width="stretch"):
        _try_open("cache folder", state.config.pickle_cache_dir)
    if st.sidebar.button("Open Scripts Folder", width="stretch"):
        _try_open("scripts folder", state.config.scripts_dir)

    db_path = state.config.database_url
    if db_path.startswith("sqlite:///"):
        db_file = Path(db_path.replace("sqlite:///", "")).expanduser()
        if st.sidebar.button("Open Database Location", width="stretch"):
            _try_open("database location", db_file.parent if db_file.is_file() else db_file)

    # Parser diagnostics
    parser_status = parser_capabilities()
    with st.sidebar.expander("Parser Status", expanded=False):
        extract_msg_status = parser_status.get("extract_msg", {})
        mailparser_status = parser_status.get("mailparser", {})
        
        if extract_msg_status.get("available"):
            st.success("✅ MSG Parser: Available")
        else:
            st.warning("⚠️ MSG Parser: Missing `extract-msg` package")
            st.caption("Install with: `pip install extract-msg`")
        
        if mailparser_status.get("available"):
            st.success("✅ EML Fallback: Available")
        else:
            st.info("ℹ️ EML Fallback: Optional `mailparser` not installed")
            st.caption("Install for better EML parsing: `pip install mail-parser`")
    
    snapshot = _resource_snapshot(str(PROJECT_ROOT), state.config.database_url)
    with st.sidebar.expander("Resource Usage", expanded=False):
        col_cpu, col_mem = st.columns(2)
        cpu_value = (
            f"{snapshot['cpu_percent']:.1f}%" if snapshot["cpu_percent"] is not None else "N/A"
        )
        mem_value = (
            f"{snapshot['memory_percent']:.1f}%" if snapshot["memory_percent"] is not None else "N/A"
        )
        col_cpu.metric("CPU Load", cpu_value)
        col_mem.metric("RAM Usage", mem_value)

        st.caption("Storage Footprint")
        st.write(f"• App directory: {_format_bytes(int(snapshot['app_size']))}")
        st.write(
            f"• Disk used: {_format_bytes(int(snapshot['disk_used']))} / {_format_bytes(int(snapshot['disk_total']))}"
        )
        st.write(f"• Disk free: {_format_bytes(int(snapshot['disk_free']))}")

        if snapshot["db_size"] is not None:
            st.write(
                f"• Database ({snapshot['db_path']}): {_format_bytes(int(snapshot['db_size']))}"
            )
        else:
            st.write("• Database size: N/A")

        if snapshot["process_memory"] is not None:
            st.caption("Process")
            st.write(f"• App memory usage: {_format_bytes(int(snapshot['process_memory']))}")

        if not snapshot["psutil_available"]:
            st.info("Install `psutil` to view live CPU/RAM metrics.")

    if state.notifications:
        st.sidebar.divider()
        st.sidebar.subheader("Notifications")
        for note in state.notifications[-3:]:
            st.sidebar.info(note)

    st.sidebar.divider()
    st.sidebar.caption("Docs: `docs/setup_guide.md` · `docs/architecture.md`")

