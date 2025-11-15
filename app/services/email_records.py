"""Helpers for loading and updating email records for the UI."""

from __future__ import annotations

import json
import pickle
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import InputEmail, PickleBatch
from app.db.repositories import get_input_email, get_pickle_batch, list_emails_by_batch, list_pickle_batches
from app.parsers import extract_urls


def _loads(text: Optional[str]) -> List[str]:
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []


def _dumps(values: List[str]) -> str:
    return json.dumps(values)


def _serialize_email(email: InputEmail) -> Dict:
    return {
        "id": email.id,
        "email_hash": email.email_hash,
        "parse_status": email.parse_status,
        "parse_error": email.parse_error,
        "subject": email.subject,
        "subject_id": email.subject_id,
        "sender": email.sender,
        "cc": _loads(email.cc),
        "date_sent": email.date_sent.isoformat() if email.date_sent else None,
        "date_reported": email.date_reported.isoformat() if email.date_reported else None,
        "urls_raw": _loads(email.url_raw),
        "urls_parsed": _loads(email.url_parsed),
        "callback_numbers_raw": _loads(email.callback_number_raw),
        "callback_numbers_parsed": _loads(email.callback_number_parsed),
        "sending_source_raw": email.sending_source_raw,
        "sending_source_parsed": _loads(email.sending_source_parsed),
        "additional_contacts": email.additional_contacts,
        "model_confidence": email.model_confidence,
        "message_id": email.message_id,
        "body_html": email.body_html,
        "pickle_batch_id": email.pickle_batch_id,
        "attachments": [
            {
                "id": attachment.id,
                "file_name": attachment.file_name,
                "file_type": attachment.file_type,
                "file_size": attachment.file_size_bytes,
                "storage_path": attachment.storage_path,
            }
            for attachment in email.attachments or []
        ],
    }


def get_batches(session: Session) -> List[PickleBatch]:
    return list_pickle_batches(session)


def get_emails_for_batch(session: Session, batch_id: int) -> List[Dict]:
    emails = list_emails_by_batch(session, batch_id)
    return [_serialize_email(email) for email in emails]


def get_email_detail(session: Session, email_id: int) -> Optional[Dict]:
    email = get_input_email(session, email_id)
    if not email:
        return None
    return _serialize_email(email)


def _parse_datetime(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _update_pickle(batch: PickleBatch, email: InputEmail) -> None:
    path = Path(batch.file_path)
    if not path.exists():
        logger.warning("Pickle file %s is missing; skipping update.", path)
        return
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load pickle %s: %s", path, exc)
        return

    updated = False
    for record in payload:
        if record.get("id") == email.id:
            record.update(
                {
                    "subject": email.subject,
                    "subject_id": email.subject_id,
                    "model_confidence": email.model_confidence,
                    "urls": _loads(email.url_parsed),
                    "callback_numbers": _loads(email.callback_number_parsed),
                    "date_sent": email.date_sent.isoformat() if email.date_sent else None,
                    "date_reported": email.date_reported.isoformat() if email.date_reported else None,
                }
            )
            updated = True
            break

    if not updated:
        payload.append(
            {
                "id": email.id,
                "email_hash": email.email_hash,
                "subject": email.subject,
                "subject_id": email.subject_id,
                "sender": email.sender,
                "date_sent": email.date_sent.isoformat() if email.date_sent else None,
                "date_reported": email.date_reported.isoformat() if email.date_reported else None,
                "urls": _loads(email.url_parsed),
                "callback_numbers": _loads(email.callback_number_parsed),
                "model_confidence": email.model_confidence,
            }
        )

    with path.open("wb") as handle:
        pickle.dump(payload, handle)


def update_email_record(
    session: Session,
    email_id: int,
    updates: Dict,
    *,
    config: Optional[AppConfig] = None,
) -> Optional[Dict]:
    email = get_input_email(session, email_id)
    if not email:
        return None

    cfg = config or load_config()

    email.subject = updates.get("subject") or email.subject
    email.subject_id = updates.get("subject_id") or email.subject_id
    email.sender = updates.get("sender") or email.sender

    email.date_sent = _parse_datetime(updates.get("date_sent")) or email.date_sent
    email.date_reported = _parse_datetime(updates.get("date_reported")) or email.date_reported

    cc_list = [line.strip() for line in updates.get("cc", []) if line.strip()]
    email.cc = _dumps(cc_list)

    urls = [line.strip() for line in updates.get("urls_parsed", []) if line.strip()]
    email.url_parsed = _dumps(urls)
    email.url_raw = _dumps(updates.get("urls_raw", urls))

    callback_numbers = [line.strip() for line in updates.get("callback_numbers_parsed", []) if line.strip()]
    email.callback_number_parsed = _dumps(callback_numbers)
    email.callback_number_raw = _dumps(updates.get("callback_numbers_raw", callback_numbers))

    sending_source_raw = updates.get("sending_source_raw")
    if sending_source_raw is not None:
        email.sending_source_raw = sending_source_raw
        sources = extract_urls(sending_source_raw)
        email.sending_source_parsed = _dumps([item.domain for item in sources])

    email.additional_contacts = updates.get("additional_contacts")
    model_confidence = updates.get("model_confidence")
    try:
        email.model_confidence = float(model_confidence) if model_confidence not in (None, "") else None
    except (TypeError, ValueError):
        logger.warning("Invalid model confidence value %s", model_confidence)

    session.add(email)
    session.commit()

    if email.pickle_batch_id:
        batch = get_pickle_batch(session, email.pickle_batch_id)
        if batch:
            _update_pickle(batch, email)

    logger.info("Updated email %s", email_id)
    return _serialize_email(email)

