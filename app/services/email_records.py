"""Helpers for loading and updating email records for the UI."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import InputEmail, PickleBatch
from app.db.repositories import get_input_email, get_pickle_batch, list_emails_by_batch, list_pickle_batches
from app.parsers import extract_urls
from app.services.shared import build_pickle_payload_record
from app.utils.error_handling import format_database_error
from app.utils.file_operations import read_bytes_safe, write_bytes_safe
from app.utils.json_helpers import safe_json_loads_list, safe_json_dumps
from app.utils.validation import validate_email_id
from sqlalchemy.orm import joinedload


@dataclass
class PickleUpdateResult:
    """Result of pickle file update operation."""
    success: bool
    error_message: Optional[str] = None


# Use centralized JSON utilities
_loads = safe_json_loads_list
_dumps = safe_json_dumps


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
        "image_base64": email.image_base64,
        "pickle_batch_id": email.pickle_batch_id,
        "knowledge_data": email.knowledge_data or {},
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
    # Eagerly load attachments to avoid N+1 queries
    emails = list_emails_by_batch(session, batch_id, eager_load_attachments=True)
    return [_serialize_email(email) for email in emails]


def get_email_detail(session: Session, email_id: int) -> Optional[Dict]:
    """Get email detail with validation.
    
    Args:
        session: Database session
        email_id: Email ID to retrieve
        
    Returns:
        Email dictionary if found, None otherwise
        
    Raises:
        ValueError: If email_id is invalid
    """
    is_valid, error_msg = validate_email_id(email_id)
    if not is_valid:
        logger.warning("Invalid email_id in get_email_detail: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        # Eagerly load attachments to avoid N+1 queries
        email = get_input_email(session, email_id, eager_load_attachments=True)
        if not email:
            return None
        return _serialize_email(email)
    except Exception as exc:
        logger.error("Error getting email detail for ID %s: %s", email_id, exc)
        raise


def _parse_datetime(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _update_pickle(batch: PickleBatch, email: InputEmail) -> PickleUpdateResult:
    """Update pickle file with email changes.
    
    Args:
        batch: PickleBatch object
        email: Updated InputEmail object
        
    Returns:
        PickleUpdateResult indicating success or failure
    """
    if not batch.file_path:
        return PickleUpdateResult(
            success=False,
            error_message="Batch file path is not set"
        )
    
    path = Path(batch.file_path)
    if not path.exists():
        logger.warning("Pickle file %s is missing; skipping update.", path)
        return PickleUpdateResult(
            success=False,
            error_message=f"Pickle file not found: {path}"
        )
    
    try:
        pickle_bytes = read_bytes_safe(path)
        payload = pickle.loads(pickle_bytes)
    except pickle.UnpicklingError as exc:
        logger.error("Failed to unpickle file %s: %s", path, exc)
        return PickleUpdateResult(
            success=False,
            error_message=f"Pickle file is corrupted or invalid format: {exc}"
        )
    except MemoryError as exc:
        logger.error("Out of memory loading pickle file %s (size: %d bytes): %s", 
                    path, path.stat().st_size if path.exists() else 0, exc)
        return PickleUpdateResult(
            success=False,
            error_message=f"Pickle file is too large to load into memory: {exc}"
        )
    except Exception as exc:
        logger.error("Failed to load pickle %s: %s", path, exc)
        return PickleUpdateResult(
            success=False,
            error_message=f"Failed to read pickle file: {exc}"
        )

    try:
        updated = False
        for record in payload:
            if record.get("id") == email.id:
                # Update existing record using shared function
                new_record = build_pickle_payload_record(email)
                record.update(new_record)
                updated = True
                break

        if not updated:
            # Append new record using shared function
            payload.append(build_pickle_payload_record(email))

        # Use atomic write utility for pickle file
        try:
            pickle_bytes = pickle.dumps(payload)
        except (MemoryError, pickle.PicklingError) as exc:
            logger.error("Failed to serialize pickle payload for batch %s: %s", batch.file_path, exc)
            return PickleUpdateResult(
                success=False,
                error_message=f"Failed to serialize pickle data: {exc}"
            )
        write_bytes_safe(path, pickle_bytes, atomic=True)
        
        return PickleUpdateResult(success=True)
    except (OSError, PermissionError) as exc:
        logger.error("Failed to write pickle file %s: %s", path, exc)
        return PickleUpdateResult(
            success=False,
            error_message=f"Failed to write pickle file: {exc}"
        )
    except Exception as exc:
        logger.error("Unexpected error updating pickle file %s: %s", path, exc)
        return PickleUpdateResult(
            success=False,
            error_message=f"Unexpected error updating pickle file: {exc}"
        )


def update_email_record(
    session: Session,
    email_id: int,
    updates: Dict,
    *,
    config: Optional[AppConfig] = None,
) -> Optional[Dict]:
    """Update email record with validation and error handling.
    
    Args:
        session: Database session
        email_id: Email ID to update
        updates: Dictionary of fields to update
        config: Optional app config
        
    Returns:
        Updated email dictionary, or None if email not found
        
    Raises:
        ValueError: If email_id is invalid or updates are invalid
        IntegrityError: If database constraint violation occurs
    """
    is_valid, error_msg = validate_email_id(email_id)
    if not is_valid:
        logger.warning("Invalid email_id in update_email_record: %s", error_msg)
        raise ValueError(error_msg)
    
    if updates is None:
        raise ValueError("Updates dictionary cannot be None")
    
    try:
        email = get_input_email(session, email_id)
        if not email:
            logger.warning("Email %s not found for update", email_id)
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
            try:
                sources = extract_urls(sending_source_raw)
                email.sending_source_parsed = _dumps([item.domain for item in sources])
            except Exception as exc:
                logger.warning("Failed to extract URLs from sending_source_raw: %s", exc)
                # Continue without parsed sources

        email.additional_contacts = updates.get("additional_contacts")
        model_confidence = updates.get("model_confidence")
        try:
            email.model_confidence = float(model_confidence) if model_confidence not in (None, "") else None
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid model confidence value %s: %s", model_confidence, exc)
            # Continue without model_confidence

        # Don't commit here - let the caller (session_scope) handle commits
        # This prevents double-commit issues when called from within session_scope()
        session.add(email)
        session.flush()  # Flush to ensure changes are visible for pickle update

        # Update pickle file if batch exists
        pickle_result = None
        if email.pickle_batch_id:
            try:
                batch = get_pickle_batch(session, email.pickle_batch_id)
                if batch:
                    pickle_result = _update_pickle(batch, email)
                    if not pickle_result.success:
                        logger.warning("Pickle update failed for email %s: %s", email_id, pickle_result.error_message)
            except Exception as exc:
                logger.warning("Failed to update pickle for email %s: %s", email_id, exc)
                # Continue even if pickle update fails - database update is more important

        logger.info("Updated email %s", email_id)
        result = _serialize_email(email)
        
        # Add pickle update status to result if available
        if pickle_result and not pickle_result.success:
            result["_pickle_update_error"] = pickle_result.error_message
        
        return result
    except IntegrityError as exc:
        error_msg = format_database_error(exc, "update email record")
        logger.error("Integrity error updating email %s: %s", email_id, exc)
        raise IntegrityError(error_msg, None, None) from exc
    except ValueError:
        raise  # Re-raise validation errors
    except Exception as exc:
        logger.error("Error updating email %s: %s", email_id, exc)
        raise

