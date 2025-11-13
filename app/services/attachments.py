"""Attachment extraction and packaging services."""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Attachment, InputEmail, PickleBatch

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".svg"}
EMAIL_EXTENSIONS = {".eml", ".msg"}


class AttachmentCategory(str, Enum):
    IMAGES = "images"
    EMAILS = "emails"
    OTHER = "other"


@dataclass(slots=True)
class AttachmentExportResult:
    attachment_id: int
    source_path: Path
    destination_path: Path
    category: AttachmentCategory


def detect_category(attachment: Attachment) -> AttachmentCategory:
    suffix = Path(attachment.file_name or "").suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return AttachmentCategory.IMAGES
    if suffix in EMAIL_EXTENSIONS:
        return AttachmentCategory.EMAILS
    return AttachmentCategory.OTHER


def build_destination_name(attachment: Attachment) -> str:
    base_name = attachment.file_name or f"attachment_{attachment.id}"
    prefix = attachment.subject_id
    if not prefix and attachment.input_email:
        prefix = attachment.input_email.subject_id or attachment.input_email.email_hash
    if prefix:
        return f"{prefix}_{base_name}"
    return base_name


def export_attachments(
    session: Session,
    attachment_ids: Sequence[int],
    destination_root: Path,
    *,
    create_archive: bool = True,
) -> tuple[List[AttachmentExportResult], Path | None]:
    """Copy attachments into organized folders and optionally create a zip archive."""
    if not attachment_ids:
        return [], None

    destination_root.mkdir(parents=True, exist_ok=True)

    attachments = session.query(Attachment).filter(Attachment.id.in_(attachment_ids)).all()
    results: List[AttachmentExportResult] = []

    for attachment in attachments:
        if not attachment.storage_path:
            logger.warning("Attachment %s is missing a storage_path; skipping", attachment.id)
            continue

        source_path = Path(attachment.storage_path)
        if not source_path.exists():
            logger.warning("Attachment source %s does not exist; skipping", source_path)
            continue

        category = detect_category(attachment)
        category_dir = destination_root / category.value
        category_dir.mkdir(parents=True, exist_ok=True)

        destination_name = build_destination_name(attachment)
        destination_path = category_dir / destination_name

        shutil.copy2(source_path, destination_path)
        results.append(
            AttachmentExportResult(
                attachment_id=attachment.id,
                source_path=source_path,
                destination_path=destination_path,
                category=category,
            )
        )

    archive_path: Path | None = None
    if create_archive and results:
        archive_path = destination_root.with_suffix(".zip")
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for result in results:
                archive.write(
                    result.destination_path,
                    arcname=result.destination_path.relative_to(destination_root),
                )

    return results, archive_path


def list_attachment_records(
    session: Session,
    *,
    batch_id: Optional[int] = None,
    category: Optional[AttachmentCategory] = None,
) -> List[Dict]:
    stmt = (
        select(Attachment, InputEmail, PickleBatch)
        .join(InputEmail, Attachment.input_email_id == InputEmail.id)
        .join(PickleBatch, InputEmail.pickle_batch_id == PickleBatch.id, isouter=True)
        .order_by(Attachment.created_at.desc())
    )

    if batch_id is not None:
        stmt = stmt.where(InputEmail.pickle_batch_id == batch_id)

    attachments: List[Dict] = []
    for attachment, email, batch in session.execute(stmt):
        detected = detect_category(attachment)
        if category and detected != category:
            continue
        attachments.append(
            {
                "id": attachment.id,
                "file_name": attachment.file_name,
                "file_type": attachment.file_type,
                "file_size": attachment.file_size_bytes,
                "subject_id": attachment.subject_id or email.subject_id,
                "email_subject": email.subject,
                "email_sender": email.sender,
                "batch_name": batch.batch_name if batch else None,
                "category": detected.value,
                "storage_path": attachment.storage_path,
                "email_id": email.id,
                "batch_id": batch.id if batch else None,
            }
        )

    return attachments


def cleanup_exports(export_results: Iterable[AttachmentExportResult]) -> None:
    for result in export_results:
        try:
            if result.destination_path.exists():
                result.destination_path.unlink()
        except OSError as exc:
            logger.warning("Failed to remove %s: %s", result.destination_path, exc)

