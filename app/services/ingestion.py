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
from app.utils import sha256_digest
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
    
    destination.write_bytes(attachment.payload)
    return destination


def _input_email_from_parsed(email_hash: str, parsed, file_name: str | None = None, use_date_sent_for_original: bool = False) -> InputEmail:
    email = InputEmail(email_hash=email_hash)
    _apply_parsed_email(email, parsed, file_name=file_name, use_date_sent_for_original=use_date_sent_for_original)
    return email


def _apply_parsed_email(target: InputEmail, parsed, file_name: str | None = None, use_date_sent_for_original: bool = False) -> None:
    target.parse_status = "success"
    target.parse_error = None
    
    # Check if filename contains 'original' and feature is enabled
    if use_date_sent_for_original and file_name and "original" in file_name.lower():
        # Use Date Sent as Subject ID (formatted as YYYYMMDDTHHMMSS)
        if parsed.date_sent:
            target.subject_id = parsed.date_sent.strftime("%Y%m%dT%H%M%S")
            logger.info("Using Date Sent as Subject ID for file with 'original' in name: %s -> %s", file_name, target.subject_id)
        else:
            # Fallback to parsed subject_id if date_sent is not available
            target.subject_id = parsed.subject_id
            logger.warning("File '%s' contains 'original' but Date Sent is not available, using parsed Subject ID", file_name)
    else:
        target.subject_id = parsed.subject_id
    
    target.sender = parsed.sender
    target.cc = json.dumps(parsed.cc)
    target.subject = parsed.subject
    target.date_sent = parsed.date_sent
    target.date_reported = parsed.date_reported
    target.sending_source_raw = parsed.sending_source_raw
    target.sending_source_parsed = json.dumps(parsed.sending_source_parsed)
    target.url_raw = json.dumps(parsed.urls_raw)
    target.url_parsed = json.dumps(parsed.urls_parsed)
    target.callback_number_raw = json.dumps(parsed.callback_numbers_raw)
    target.callback_number_parsed = json.dumps(parsed.callback_numbers_parsed)
    target.additional_contacts = parsed.additional_contacts
    target.model_confidence = parsed.model_confidence
    target.message_id = parsed.message_id
    target.image_base64 = parsed.image_base64
    # Store full email body as HTML - prefer HTML, but if only text available, preserve it
    # The body_html field should contain the complete email body content
    if parsed.body_html:
        target.body_html = parsed.body_html
    elif parsed.body_text:
        # If only text is available, wrap it in basic HTML to preserve formatting
        target.body_html = f"<pre>{parsed.body_text}</pre>"
    else:
        target.body_html = None


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


def _prepare_pickle_payload(emails: Iterable[InputEmail]) -> List[dict]:
    payload = []
    for email in emails:
        payload.append(
            {
                "id": email.id,
                "email_hash": email.email_hash,
                "subject": email.subject,
                "subject_id": email.subject_id,
                "sender": email.sender,
                "date_sent": email.date_sent.isoformat() if email.date_sent else None,
                "date_reported": email.date_reported.isoformat() if email.date_reported else None,
                # Maintain backward compatibility with "urls" and "callback_numbers"
                "urls": json.loads(email.url_parsed or "[]"),
                "urls_raw": json.loads(email.url_raw or "[]"),
                "urls_parsed": json.loads(email.url_parsed or "[]"),
                "callback_numbers": json.loads(email.callback_number_parsed or "[]"),
                "callback_numbers_raw": json.loads(email.callback_number_raw or "[]"),
                "callback_numbers_parsed": json.loads(email.callback_number_parsed or "[]"),
                "sending_source_raw": email.sending_source_raw,
                "sending_source_parsed": json.loads(email.sending_source_parsed or "[]"),
                "additional_contacts": email.additional_contacts,
                "model_confidence": email.model_confidence,
                "message_id": email.message_id,
                "body_html": email.body_html,
            }
        )
    return payload


def _summarize_failures(attempts) -> str:
    """Summarize parser failures with user-friendly messages."""
    messages = []
    for attempt in attempts:
        if attempt.status == "failed" and attempt.error_message:
            error_msg = attempt.error_message
            
            # Convert technical parser errors to user-friendly messages
            if "codec" in error_msg.lower() and "decode" in error_msg.lower():
                messages.append("Email encoding issue - file may be corrupted or in unsupported format")
            elif "extract-msg" in error_msg.lower() or "extract_msg" in error_msg.lower():
                messages.append("MSG parser unavailable - install 'extract-msg' package")
            elif "mailparser" in error_msg.lower():
                messages.append("Advanced parser unavailable - install 'mail-parser' package (optional)")
            elif "does not resemble an email" in error_msg.lower():
                messages.append("File does not appear to be a valid email")
            else:
                # Keep original message but truncate if too long
                clean_msg = error_msg[:150] + "..." if len(error_msg) > 150 else error_msg
                messages.append(f"{attempt.name}: {clean_msg}")
    
    if messages:
        return "; ".join(messages)
    return "No parser strategy available - check that email file is valid"


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
            
            original_bytes = file_path.read_bytes()
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
                error_summary = _summarize_failures(outcome.attempts) or "Unknown parser failure"
                input_email = _build_failed_email_stub(email_hash, file_path.name, error_summary)
                failures.append(f"{file_path.name}: {error_summary}")

            session.merge(
                OriginalEmail(
                    email_hash=email_hash,
                    file_name=file_path.name,
                    mime_type=_infer_mime_type(candidate),
                    content=original_bytes,
                )
            )

            upsert_input_email(session, input_email)

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
                
                attachment_models = _create_attachment_models(cfg, email_hash, input_email, valid_attachments)
                session.add_all(attachment_models)
                for attachment in valid_attachments:
                    session.add(
                        OriginalAttachment(
                            email_hash=email_hash,
                            file_name=attachment.file_name,
                            mime_type=attachment.content_type,
                            content=attachment.payload,
                        )
                    )

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

    session.flush()

    pickle_payload = _prepare_pickle_payload(ingested_emails)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    batch_label = batch_name or f"batch_{timestamp}"
    pickle_path = cfg.pickle_cache_dir / f"{batch_label}.pkl"
    with pickle_path.open("wb") as handle:
        pickle.dump(pickle_payload, handle)

    pickle_batch = PickleBatch(
        batch_name=batch_label,
        file_path=str(pickle_path),
        record_count=len(ingested_emails),
        status="draft",
    )
    register_pickle_batch(session, pickle_batch)
    for email in ingested_emails:
        email.pickle_batch = pickle_batch

    session.commit()
    logger.info("Ingested %d emails into batch %s", len(ingested_emails), batch_label)

    return IngestionResult(
        batch=pickle_batch,
        email_ids=[email.id for email in ingested_emails],
        skipped=skipped,
        failures=failures,
    )

