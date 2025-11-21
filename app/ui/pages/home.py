"""Home page for the Email Handler app."""

from __future__ import annotations

import platform
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st
from loguru import logger
from sqlalchemy import func

from app.db.init_db import session_scope
from app.db.models import Attachment, InputEmail, PickleBatch, StandardEmail
from app.ui.state import AppState
from app.ui.styles.animations import inject_reveal_animations
from app.utils.version import get_app_version

APP_VERSION = get_app_version()
KEY_DEPENDENCIES = ["streamlit", "sqlalchemy", "pandas", "pydantic", "loguru"]
RECENT_BATCH_LIMIT = 3
LOGO_CANDIDATES = [
    Path("assets/logo.png"),
    Path("public/logo.png"),
    Path("SPEAR_transparent_cropped.png"),
]


def _format_datetime(value: Optional[datetime]) -> str:
    if not value:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _sqlite_path(database_url: str) -> Optional[Path]:
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        return Path(database_url.replace(prefix, "")).expanduser()
    return None


def _get_database_stats(state: AppState) -> Dict[str, object]:
    config = state.config
    stats: Dict[str, object] = {
        "input_emails": 0,
        "attachments": 0,
        "standard_emails": 0,
        "pickle_batches": 0,
        "finalized_batches": 0,
        "pending_batches": 0,
        "latest_ingest": None,
        "last_finalized": None,
        "recent_batches": [],
        "db_path": None,
        "db_size_mb": 0.0,
    }

    try:
        with session_scope() as session:
            stats["input_emails"] = session.query(func.count(InputEmail.id)).scalar() or 0
            stats["attachments"] = session.query(func.count(Attachment.id)).scalar() or 0
            stats["standard_emails"] = session.query(func.count(StandardEmail.id)).scalar() or 0
            stats["pickle_batches"] = session.query(func.count(PickleBatch.id)).scalar() or 0
            stats["finalized_batches"] = (
                session.query(func.count(PickleBatch.id))
                .filter(PickleBatch.status == "finalized")
                .scalar()
                or 0
            )
            stats["pending_batches"] = (
                session.query(func.count(PickleBatch.id))
                .filter(PickleBatch.status != "finalized")
                .scalar()
                or 0
            )

            stats["latest_ingest"] = (
                session.query(func.max(InputEmail.created_at)).scalar()
            )
            stats["last_finalized"] = (
                session.query(func.max(PickleBatch.uploaded_at)).scalar()
            )

            recent = (
                session.query(PickleBatch)
                .order_by(PickleBatch.created_at.desc())
                .limit(RECENT_BATCH_LIMIT)
                .all()
            )
            stats["recent_batches"] = [
                {
                    "name": batch.batch_name,
                    "records": batch.record_count,
                    "status": batch.status or "draft",
                    "created": batch.created_at,
                }
                for batch in recent
            ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to compute database stats: {}", exc)

    db_path = _sqlite_path(config.database_url)
    stats["db_path"] = str(db_path) if db_path else config.database_url
    if db_path and db_path.exists():
        stats["db_size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)

    return stats


def _get_system_info() -> Dict[str, object]:
    deps: Dict[str, str] = {}
    for dep in KEY_DEPENDENCIES:
        try:
            deps[dep] = metadata.version(dep)
        except metadata.PackageNotFoundError:
            deps[dep] = "Not installed"
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": deps,
    }


def _find_logo() -> Optional[Path]:
    for candidate in LOGO_CANDIDATES:
        path = candidate.expanduser()
        if path.exists():
            return path
    return None


def _inject_header_styles() -> None:
    st.markdown(
        """
        <style>
        .eh-hero {
            position: relative;
            padding: 1.8rem 0 1.2rem;
        }
        .eh-title {
            font-size: 3.1rem;
            margin-bottom: 0.35rem;
            letter-spacing: -0.03em;
        }
        .eh-title .gold-shimmer {
            background: linear-gradient(120deg, #d6e4ff 0%, #9fb8ff 50%, #c8d7ff 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent !important;
            color: transparent !important;
        }
        .eh-tagline.silver-shimmer {
            color: rgba(209, 213, 255, 0.85) !important;
        }
        .eh-tagline {
            color: rgba(226,232,255,0.78);
            font-size: 1.05rem;
            margin-bottom: 0.75rem;
        }
        .eh-tagline--secondary {
            opacity: 0.9;
            margin-bottom: 1.6rem;
        }
        .eh-badge {
            display: inline-flex;
            gap: 0.65rem;
            padding: 0.55rem 1rem;
            border-radius: 999px;
            background: rgba(18, 20, 35, 0.55);
            border: 1px solid rgba(120,140,200,0.45);
            color: rgba(226,232,255,0.85);
            font-size: 0.9rem;
            backdrop-filter: blur(6px);
        }
        .eh-hero-columns {
            display: grid;
            gap: 28px;
            grid-template-columns: minmax(0, 1.8fr) minmax(0, 1fr);
            align-items: center;
        }
        .eh-logo-wrapper {
            position: relative;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }
        .eh-logo-wrapper::before,
        .eh-logo-wrapper::after {
            content: none;
        }
        .eh-logo-wrapper img {
            max-width: 220px;
            border-radius: 14px;
            box-shadow: 0 12px 30px -18px rgba(10, 15, 40, 0.6);
            position: relative;
            z-index: 1;
            animation: none;
        }
        @media (max-width: 820px) {
            .eh-hero-columns {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render(state: AppState) -> None:
    config = state.config
    stats = _get_database_stats(state)
    system_info = _get_system_info()
    logo_path = _find_logo()

    _inject_header_styles()
    inject_reveal_animations()

    hero_cols = st.columns([2, 1], gap="large")
    with hero_cols[0]:
        st.markdown("<h1 class='eh-title'><span class='gold-shimmer'>Email Handler</span></h1>", unsafe_allow_html=True)
        st.markdown(
            "<p class='eh-tagline silver-shimmer'>Part of the SPEAR toolkit</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p class='eh-tagline eh-tagline--secondary'>Local phishing triage workspace for analysts.</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<span class='eh-badge'>Version {APP_VERSION} · Env `{config.env_name}`</span>",
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            **Email Handler streamlines your investigation workflow:**
            - Ingest phishing reports from local folders with deterministic hashing.
            - Normalize sender details, URLs, callback numbers, and attachments.
            - Review, edit, and promote records before finalizing batches.
            - Export evidence packages and HTML reports for downstream teams.
            """
        )
    with hero_cols[1]:
        if logo_path:
            st.markdown("<div class='eh-logo-wrapper'>", unsafe_allow_html=True)
            st.image(str(logo_path))
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div style='height: 140px;'></div>", unsafe_allow_html=True)

    with st.expander("Key Directories", expanded=False):
        st.write(f"**Input:** `{config.input_dir}`")
        st.write(f"**Output:** `{config.output_dir}`")
        st.write(f"**Cache:** `{config.pickle_cache_dir}`")
        st.write(f"**Scripts:** `{config.scripts_dir}`")
        st.write(f"**Database:** `{stats['db_path']}`")

    st.divider()

    metrics = st.columns(4)
    metrics[0].metric("Input Emails", f"{stats['input_emails']:,}")
    metrics[1].metric("Attachments", f"{stats['attachments']:,}")
    metrics[2].metric("Standard Emails", f"{stats['standard_emails']:,}")
    metrics[3].metric(
        "Pending Batches",
        f"{stats['pending_batches']:,}",
        delta=f"{stats['finalized_batches']:,} finalized",
    )

    st.subheader("Quick Start")
    st.markdown(
        """
        1. Use **Deploy Scripts** to run approved PowerShell downloaders.
        2. In **Email Display**, ingest new files, review metadata, and update fields.
        3. Promote curated records to Standard Emails or generate HTML reports.
        4. Finalize the batch once review is complete to archive the pickle snapshot.
        5. Visit **Attachments** for export bundles and targeted investigations.
        """
    )

    st.subheader("Database Overview")
    db_left, db_right = st.columns([2, 1])
    with db_left:
        st.write(f"**Database:** `{stats['db_path']}` ({stats['db_size_mb']} MB)")
        st.write(f"**Latest Ingest:** {_format_datetime(stats['latest_ingest'])}")
        st.write(f"**Last Finalized Batch:** {_format_datetime(stats['last_finalized'])}")
    with db_right:
        st.markdown("**Recent Batches**")
        recent_batches: List[Dict[str, object]] = stats.get("recent_batches", [])  # type: ignore[assignment]
        if recent_batches:
            st.code(
                "\n".join(
                    f"{batch['created']:%Y-%m-%d %H:%M} · {batch['name']} · "
                    f"{batch['records']} emails · {batch['status']}"
                    for batch in recent_batches
                ),
                language="text",
            )
        else:
            st.info("No batches ingested yet. Run a script to populate your input directory.")

    with st.expander("System Information", expanded=False):
        sys_left, sys_right = st.columns(2)
        with sys_left:
            st.write(f"**Python Version:** {system_info['python_version']}")
            st.write(f"**Platform:** {system_info['platform']}")
            if config.database_url.startswith("sqlite"):
                st.write("**Database Engine:** SQLite (SQLAlchemy)")
            else:
                st.write(f"**Database Engine:** {config.database_url}")
        with sys_right:
            st.write("**Key Dependencies:**")
            deps: Dict[str, str] = system_info["dependencies"]  # type: ignore[assignment]
            for dep, version in deps.items():
                st.write(f"- {dep}: {version}")

    st.subheader("Notifications & Activity")
    if state.notifications:
        for note in state.notifications[-5:]:
            st.info(note)
    else:
        st.write("No recent notifications.")

