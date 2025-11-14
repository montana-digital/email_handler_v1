"""Helpers for loading StandardEmail records and related attachments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session, selectinload

from app.db.models import Attachment, InputEmail, StandardEmail


def _parse_json_list(value: str | None) -> list[str]:
    """Decode a JSON list stored in a text column."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    return []


def _classify_attachment(attachment: Attachment) -> str:
    """Map attachment MIME types to coarse categories used by the UI."""
    file_type = (attachment.file_type or "").lower()
    if file_type.startswith("image/"):
        return "image"
    if file_type in {"application/pdf", "application/x-pdf"}:
        return "pdf"
    if file_type in {"text/csv", "application/csv"} or attachment.file_name.lower().endswith(".csv"):
        return "csv"
    return "other"


def _attachment_info(attachment: Attachment) -> Dict[str, Optional[str]]:
    storage_path = Path(attachment.storage_path) if attachment.storage_path else None
    exists = storage_path.exists() if storage_path else False
    return {
        "id": attachment.id,
        "file_name": attachment.file_name,
        "file_type": attachment.file_type,
        "file_size": attachment.file_size_bytes,
        "storage_path": attachment.storage_path,
        "category": _classify_attachment(attachment),
        "exists": exists,
    }


def _serialize_standard_email(record: StandardEmail) -> Dict:
    source = record.source_input_email
    attachments: Iterable[Attachment] = source.attachments if source else []
    serialized_attachments = [_attachment_info(attachment) for attachment in attachments]

    counts = {"image": 0, "pdf": 0, "csv": 0, "other": 0}
    for item in serialized_attachments:
        key = item["category"] or "other"
        counts[key] = counts.get(key, 0) + 1

    return {
        "id": record.id,
        "email_hash": record.email_hash,
        "subject": record.subject,
        "from_address": record.from_address,
        "cc": record.cc,
        "date_sent": record.date_sent.isoformat() if record.date_sent else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "body_html": record.body_html,
        "body_urls": _parse_json_list(record.body_urls),
        "body_numbers": _parse_json_list(record.body_text_numbers),
        "source_input_email_id": record.source_input_email_id,
        "attachments": serialized_attachments,
        "attachment_counts": counts,
    }


def list_standard_email_records(
    session: Session,
    *,
    limit: int = 1000,
) -> List[Dict]:
    """Return StandardEmail rows with related source InputEmail + attachments."""
    query = (
        session.query(StandardEmail)
        .options(selectinload(StandardEmail.source_input_email).selectinload(InputEmail.attachments))
        .order_by(StandardEmail.created_at.desc())
        .limit(limit)
    )
    records = query.all()
    return [_serialize_standard_email(record) for record in records]


def get_standard_email_detail(session: Session, standard_email_id: int) -> Optional[Dict]:
    """Fetch a single StandardEmail including attachments."""
    record = (
        session.query(StandardEmail)
        .options(selectinload(StandardEmail.source_input_email).selectinload(InputEmail.attachments))
        .filter(StandardEmail.id == standard_email_id)
        .one_or_none()
    )
    if not record:
        return None
    return _serialize_standard_email(record)


