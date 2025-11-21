"""Services for finalizing pickle batches after analyst review."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import PickleBatch
from app.utils.file_operations import move_file_safe

ARCHIVE_SUBDIR = "batches"


@dataclass(slots=True)
class FinalizationResult:

    batch_id: int
    batch_name: str
    archived_path: Optional[Path]
    status: str
    uploaded_at: datetime


def _archive_pickle(batch: PickleBatch, config: AppConfig) -> Optional[Path]:
    if not batch.file_path:
        logger.warning("Batch %s missing file_path; skipping archive step.", batch.id)
        return None

    source_path = Path(batch.file_path)
    if not source_path.exists():
        logger.warning("Pickle file %s not found; skipping archive move.", source_path)
        return None

    archive_dir = config.output_dir / ARCHIVE_SUBDIR
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    destination = archive_dir / f"{batch.batch_name}_{timestamp}.pkl"

    move_file_safe(source_path, destination, create_parents=True)
    return destination


def finalize_batch(
    session: Session,
    batch_id: int,
    *,
    config: Optional[AppConfig] = None,
) -> Optional[FinalizationResult]:
    cfg = config or load_config()
    batch = session.get(PickleBatch, batch_id)

    if not batch:
        logger.warning("Attempted to finalize missing batch %s", batch_id)
        return None

    if batch.status == "finalized":
        logger.info("Batch %s already finalized; skipping.", batch_id)
        return FinalizationResult(
            batch_id=batch.id,
            batch_name=batch.batch_name,
            archived_path=Path(batch.file_path) if batch.file_path else None,
            status=batch.status,
            uploaded_at=batch.uploaded_at or datetime.now(timezone.utc),
        )

    archived_path = _archive_pickle(batch, cfg)

    batch.status = "finalized"
    batch.uploaded_at = datetime.now(timezone.utc)
    if archived_path:
        batch.file_path = str(archived_path)

    # Don't commit here - let the caller (session_scope) handle commits
    # This prevents double-commit issues when called from within session_scope()
    session.add(batch)

    logger.info(
        "Finalized batch %s (%s). status=%s archived=%s",
        batch.id,
        batch.batch_name,
        batch.status,
        archived_path,
    )

    return FinalizationResult(
        batch_id=batch.id,
        batch_name=batch.batch_name,
        archived_path=archived_path,
        status=batch.status,
        uploaded_at=batch.uploaded_at,
    )

