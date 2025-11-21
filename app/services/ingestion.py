"""Ingestion service for processing raw email files into the database and cache."""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from dataclasses import dataclass
from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import Attachment, InputEmail, OriginalAttachment, OriginalEmail, ParserRun, PickleBatch
from app.db.repositories import find_input_email_by_hash, register_pickle_batch, upsert_input_email
from app.parsers import ParsedAttachment
from app.services.parsing import detect_candidate, run_parsing_pipeline
from app.services.shared import apply_parsed_email_to_input, build_pickle_payload, summarize_parser_failures
from app.utils import sha256_digest
from app.utils.error_handling import format_database_error
from app.utils.file_operations import read_bytes_safe, write_bytes_safe
from app.utils.json_helpers import safe_json_loads_list
from app.utils.path_validation import validate_path_length

ATTACHMENT_ROOT = "attachments"


@dataclass(slots=True)
class IngestionResult:
    batch: PickleBatch | None
    email_ids: List[int]
    skipped: List[str]
    failures: List[str]


def _ensure_directories(config: AppConfig) -> None:
    config.pickle_cache_dir.mkdir(parents=True, exist_ok=True)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / ATTACHMENT_ROOT).mkdir(parents=True, exist_ok=True)


def _discover_email_files(directory: Path) -> List[Path]:
    candidates = []
    for pattern in ("*.eml", "*.msg"):
        candidates.extend(sorted(directory.glob(pattern)))
    return candidates


def _save_attachment(config: AppConfig, email_hash: str, attachment: ParsedAttachment) -> Path:
    attachment_dir = config.output_dir / ATTACHMENT_ROOT / email_hash
    attachment_dir.mkdir(parents=True, exist_ok=True)
    
    # Use proper Windows filename sanitization
    from app.utils.path_validation import sanitize_filename
    safe_name = sanitize_filename(attachment.file_name)
    
    destination = attachment_dir / safe_name
    
    # Validate path length before writing (Windows 260-char limit)
    is_valid, error = validate_path_length(destination)
    if not is_valid:
        # Truncate filename if path is too long
        # Calculate max filename length: 260 (max path) - directory length - 1 (separator) - some buffer
        dir_str = str(attachment_dir)
        max_path_len = 260
        buffer = 10  # Safety buffer
        max_name_len = max_path_len - len(dir_str) - 1 - buffer
        
        name_part = Path(safe_name).stem
        ext_part = Path(safe_name).suffix
        if len(name_part) > max_name_len:
            name_part = name_part[:max_name_len]
        safe_name = f"{name_part}{ext_part}"
        destination = attachment_dir / safe_name
        logger.warning("Attachment path too long, truncated filename: %s", safe_name)
    
    try:
        write_bytes_safe(destination, attachment.payload, atomic=True)
    except Exception as exc:
        logger.error("Failed to write attachment %s to %s: %s", attachment.file_name, destination, exc)
        raise
    
    return destination


def _input_email_from_parsed(email_hash: str, parsed, file_name: str | None = None, use_date_sent_for_original: bool = False) -> InputEmail:
    email = InputEmail(email_hash=email_hash)
    apply_parsed_email_to_input(email, parsed, file_name=file_name, use_date_sent_for_original=use_date_sent_for_original)
    return email


# Re-export shared function for backward compatibility
_apply_parsed_email = apply_parsed_email_to_input


def _build_failed_email_stub(email_hash: str, file_name: str, error: str) -> InputEmail:
    empty = json.dumps([])
    return InputEmail(
        email_hash=email_hash,
        parse_status="failed",
        parse_error=error,
        subject=f"[Parse Failed] {file_name}",
        cc=empty,
        url_raw=empty,
        url_parsed=empty,
        callback_number_raw=empty,
        callback_number_parsed=empty,
        sending_source_parsed=empty,
    )


def _create_attachment_models(
    config: AppConfig,
    email_hash: str,
    input_email: InputEmail,
    attachments: Sequence[ParsedAttachment],
) -> List[Attachment]:
    models: List[Attachment] = []
    for attachment in attachments:
        storage_path = _save_attachment(config, email_hash, attachment)
        models.append(
            Attachment(
                input_email=input_email,
                file_name=attachment.file_name,
                file_type=attachment.content_type,
                file_size_bytes=attachment.size,
                storage_path=str(storage_path),
                subject_id=input_email.subject_id,
            )
        )
    return models


# Use shared pickle payload building function
_prepare_pickle_payload = build_pickle_payload


# Re-export shared function for backward compatibility
_summarize_failures = summarize_parser_failures


def _infer_mime_type(candidate) -> str:
    if candidate.detected_type == "msg":
        return "application/vnd.ms-outlook"
    return "message/rfc822"


def _format_user_error(exc: Exception, file_name: str) -> str:
    """Convert technical exceptions to user-friendly error messages."""
    exc_type = type(exc).__name__
    exc_str = str(exc)
    
    if exc_type == "PermissionError":
        return f"{file_name}: File is locked or access denied. Close any programs using this file and try again."
    elif exc_type == "FileNotFoundError":
        return f"{file_name}: File was moved or deleted before processing."
    elif exc_type == "OSError":
        if "WinError 5" in exc_str or "access is denied" in exc_str.lower():
            return f"{file_name}: Access denied. Check file permissions or close programs using this file."
        elif "WinError 32" in exc_str or "being used by another process" in exc_str.lower():
            return f"{file_name}: File is in use by another program. Close it and try again."
        elif "No space left" in exc_str or "disk full" in exc_str.lower():
            return f"{file_name}: Disk is full. Free up space and try again."
        else:
            return f"{file_name}: System error - {exc_str}"
    elif exc_type == "MemoryError":
        return f"{file_name}: File is too large to process. Maximum recommended size is 50MB."
    elif "codec" in exc_str.lower() and "decode" in exc_str.lower():
        return f"{file_name}: Encoding issue detected. The file may be corrupted or in an unsupported format."
    else:
        # For unknown errors, provide a generic but helpful message
        return f"{file_name}: Processing failed - {exc_str[:100]}"


def ingest_emails(
    session: Session,
    *,
    config: Optional[AppConfig] = None,
    source_paths: Optional[Sequence[Path]] = None,
    batch_name: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    use_date_sent_for_original: bool = False,
) -> Optional[IngestionResult]:
    """Process emails from the configured input directory into SQLite and cache."""
    cfg = config or load_config()
    _ensure_directories(cfg)

    files = list(source_paths) if source_paths is not None else _discover_email_files(cfg.input_dir)

    if not files:
        logger.info("No email files discovered for ingestion.")
        return None

    total_files = len(files)
    ingested_emails: List[InputEmail] = []
    skipped: List[str] = []
    failures: List[str] = []

    # File size limits (in bytes)
    MAX_EMAIL_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB
    
    for idx, file_path in enumerate(files, 1):
        # Update progress
        if progress_callback:
            progress_callback(idx, total_files, file_path.name)
        try:
            # Validate path length (Windows 260-char limit)
            is_valid, error = validate_path_length(file_path)
            if not is_valid:
                skipped.append(f"{file_path.name}: {error}")
                continue
            
            # Check file size before reading
            file_size = file_path.stat().st_size
            if file_size > MAX_EMAIL_SIZE:
                skipped.append(
                    f"{file_path.name}: File is too large ({file_size / (1024*1024):.1f}MB). "
                    f"Maximum size is {MAX_EMAIL_SIZE / (1024*1024):.0f}MB."
                )
                continue
            
            original_bytes = read_bytes_safe(file_path)
        except Exception as exc:
            logger.exception("Failed to read %s: %s", file_path, exc)
            skipped.append(_format_user_error(exc, file_path.name))
            continue

        try:
            email_hash = sha256_digest(original_bytes)
            existing = find_input_email_by_hash(session, email_hash)
            if existing:
                logger.info("Skipping already ingested email %s", file_path)
                continue

            candidate = detect_candidate(file_path, original_bytes)
            outcome = run_parsing_pipeline(candidate)

            input_email: InputEmail
            if outcome.parsed_email:
                parsed = outcome.parsed_email
                input_email = _input_email_from_parsed(
                    email_hash, 
                    parsed, 
                    file_name=file_path.name,
                    use_date_sent_for_original=use_date_sent_for_original
                )
                input_email.parse_status = "success"
                input_email.parse_error = None
            else:
                error_summary = summarize_parser_failures(outcome.attempts) or "Unknown parser failure"
                input_email = _build_failed_email_stub(email_hash, file_path.name, error_summary)
                failures.append(f"{file_path.name}: {error_summary}")

            try:
                session.merge(
                    OriginalEmail(
                        email_hash=email_hash,
                        file_name=file_path.name,
                        mime_type=_infer_mime_type(candidate),
                        content=original_bytes,
                    )
                )
            except Exception as exc:
                logger.error("Failed to merge OriginalEmail for %s: %s", file_path.name, exc)
                skipped.append(f"{file_path.name}: Database error saving original email - {format_database_error(exc, 'save original email')}")
                continue

            try:
                input_email = upsert_input_email(session, input_email)
            except Exception as exc:
                logger.error("Failed to upsert InputEmail for %s: %s", file_path.name, exc)
                skipped.append(f"{file_path.name}: Database error saving email record - {format_database_error(exc, 'save email record')}")
                continue
            
            # Flush to ensure the email is persisted and we can check for existing attachments
            try:
                session.flush()
            except Exception as exc:
                logger.error("Failed to flush session for %s: %s", file_path.name, exc)
                skipped.append(f"{file_path.name}: Database error flushing changes - {format_database_error(exc, 'flush database changes')}")
                continue

            if outcome.parsed_email:
                parsed = outcome.parsed_email
                # Validate attachment sizes
                valid_attachments = []
                for attachment in parsed.attachments:
                    if attachment.size > MAX_ATTACHMENT_SIZE:
                        logger.warning(
                            "Skipping attachment %s (size: %d bytes) - exceeds limit",
                            attachment.file_name,
                            attachment.size,
                        )
                        skipped.append(
                            f"{file_path.name}: Attachment '{attachment.file_name}' is too large "
                            f"({attachment.size / (1024*1024):.1f}MB). Maximum size is {MAX_ATTACHMENT_SIZE / (1024*1024):.0f}MB."
                        )
                    else:
                        valid_attachments.append(attachment)
                
                # Check for existing attachments to avoid unique constraint violations
                existing_attachment_filenames = {
                    att.file_name for att in (input_email.attachments or [])
                }
                
                # Only create attachments that don't already exist
                new_attachments = [
                    att for att in valid_attachments
                    if att.file_name not in existing_attachment_filenames
                ]
                
                if new_attachments:
                    try:
                        attachment_models = _create_attachment_models(cfg, email_hash, input_email, new_attachments)
                        session.add_all(attachment_models)
                        for attachment in new_attachments:
                            session.add(
                                OriginalAttachment(
                                    email_hash=email_hash,
                                    file_name=attachment.file_name,
                                    mime_type=attachment.content_type,
                                    content=attachment.payload,
                                )
                            )
                    except Exception as exc:
                        logger.error("Failed to save attachments for %s: %s", file_path.name, exc)
                        skipped.append(f"{file_path.name}: Database error saving attachments - {format_database_error(exc, 'save attachments')}")
                        # Continue without attachments rather than failing entire email
                elif valid_attachments:
                    # All attachments already exist, log but don't error
                    logger.debug(
                        "All attachments for email %s already exist, skipping attachment creation",
                        email_hash
                    )

            try:
                for attempt in outcome.attempts:
                    session.add(
                        ParserRun(
                            input_email=input_email,
                            parser_name=attempt.name,
                            version=attempt.version,
                            status=attempt.status,
                            error_message=attempt.error_message,
                        )
                    )
            except Exception as exc:
                logger.warning("Failed to save parser runs for %s: %s", file_path.name, exc)
                # Continue even if parser runs fail - email is still ingested

            ingested_emails.append(input_email)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to ingest %s: %s", file_path, exc)
            skipped.append(_format_user_error(exc, file_path.name))
            continue

    if not ingested_emails and not skipped:
        logger.info("No new emails ingested.")
        return None

    if not ingested_emails and (skipped or failures):
        return IngestionResult(batch=None, email_ids=[], skipped=skipped, failures=failures)

    # Create batch and pickle file
    try:
        session.flush()
    except Exception as exc:
        logger.error("Failed to flush session before batch creation: %s", exc)
        # Return partial result - emails are saved but no batch
        return IngestionResult(
            batch=None,
            email_ids=[email.id for email in ingested_emails],
            skipped=skipped + [f"Batch creation failed: {format_database_error(exc, 'create batch')}"],
            failures=failures,
        )

    try:
        pickle_payload = _prepare_pickle_payload(ingested_emails)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        batch_label = batch_name or f"batch_{timestamp}"
        pickle_path = cfg.pickle_cache_dir / f"{batch_label}.pkl"
        
        # Use atomic write utility for pickle file
        try:
            pickle_bytes = pickle.dumps(pickle_payload)
        except (MemoryError, pickle.PicklingError) as exc:
            logger.error("Failed to serialize pickle payload for batch %s: %s", batch_label, exc)
            skipped.append(f"Batch pickle file serialization failed: {format_database_error(exc, 'serialize pickle file')}")
            # Return partial result without batch
            return IngestionResult(
                batch=None,
                email_ids=[email.id for email in ingested_emails],
                skipped=skipped,
                failures=failures,
            )
        write_bytes_safe(pickle_path, pickle_bytes, atomic=True)
    except Exception as exc:
        logger.error("Failed to create pickle file for batch: %s", exc)
        skipped.append(f"Batch pickle file creation failed: {format_database_error(exc, 'create pickle file')}")
        # Return partial result without batch
        return IngestionResult(
            batch=None,
            email_ids=[email.id for email in ingested_emails],
            skipped=skipped,
            failures=failures,
        )

    try:
        pickle_batch = PickleBatch(
            batch_name=batch_label,
            file_path=str(pickle_path),
            record_count=len(ingested_emails),
            status="draft",
        )
        register_pickle_batch(session, pickle_batch)
        for email in ingested_emails:
            email.pickle_batch = pickle_batch
        
        # Don't commit here - let the caller (session_scope) handle commits
        # This prevents double-commit issues when called from within session_scope()
        session.flush()
    except Exception as exc:
        logger.error("Failed to register pickle batch: %s", exc)
        skipped.append(f"Batch registration failed: {format_database_error(exc, 'register batch')}")
        # Return partial result without batch
        return IngestionResult(
            batch=None,
            email_ids=[email.id for email in ingested_emails],
            skipped=skipped,
            failures=failures,
        )

    logger.info("Ingested %d emails into batch %s", len(ingested_emails), batch_label)

    return IngestionResult(
        batch=pickle_batch,
        email_ids=[email.id for email in ingested_emails],
        skipped=skipped,
        failures=failures,
    )

