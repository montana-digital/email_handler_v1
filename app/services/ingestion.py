"""Ingestion service for processing raw email files into the database and cache."""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from dataclasses import dataclass
from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import Attachment, InputEmail, OriginalAttachment, OriginalEmail, ParserRun, PickleBatch
from app.db.repositories import find_input_email_by_hash, register_pickle_batch, upsert_input_email
from app.parsers import ParsedAttachment
from app.services.parsing import detect_candidate, run_parsing_pipeline
from app.utils import sha256_digest

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
    safe_name = attachment.file_name.replace("/", "_").replace("\\", "_")
    destination = attachment_dir / safe_name
    destination.write_bytes(attachment.payload)
    return destination


def _input_email_from_parsed(email_hash: str, parsed) -> InputEmail:
    email = InputEmail(email_hash=email_hash)
    _apply_parsed_email(email, parsed)
    return email


def _apply_parsed_email(target: InputEmail, parsed) -> None:
    target.parse_status = "success"
    target.parse_error = None
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
    target.body_html = parsed.body_html or parsed.body_text


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
                "sender": email.sender,
                "date_sent": email.date_sent.isoformat() if email.date_sent else None,
                "date_reported": email.date_reported.isoformat() if email.date_reported else None,
                "subject_id": email.subject_id,
                "urls": json.loads(email.url_parsed or "[]"),
                "callback_numbers": json.loads(email.callback_number_parsed or "[]"),
                "model_confidence": email.model_confidence,
            }
        )
    return payload


def _summarize_failures(attempts) -> str:
    messages = [
        f"{attempt.name}: {attempt.error_message}"
        for attempt in attempts
        if attempt.status == "failed" and attempt.error_message
    ]
    if messages:
        return "; ".join(messages)
    return "No parser strategy available"


def _infer_mime_type(candidate) -> str:
    if candidate.detected_type == "msg":
        return "application/vnd.ms-outlook"
    return "message/rfc822"


def ingest_emails(
    session: Session,
    *,
    config: Optional[AppConfig] = None,
    source_paths: Optional[Sequence[Path]] = None,
    batch_name: Optional[str] = None,
) -> Optional[IngestionResult]:
    """Process emails from the configured input directory into SQLite and cache."""
    cfg = config or load_config()
    _ensure_directories(cfg)

    files = list(source_paths) if source_paths is not None else _discover_email_files(cfg.input_dir)

    if not files:
        logger.info("No email files discovered for ingestion.")
        return None

    ingested_emails: List[InputEmail] = []
    skipped: List[str] = []
    failures: List[str] = []

    for file_path in files:
        try:
            original_bytes = file_path.read_bytes()
        except Exception as exc:
            logger.exception("Failed to read %s: %s", file_path, exc)
            skipped.append(f"{file_path.name}: {exc}")
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
                input_email = _input_email_from_parsed(email_hash, parsed)
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
                attachment_models = _create_attachment_models(cfg, email_hash, input_email, parsed.attachments)
                session.add_all(attachment_models)
                for attachment in parsed.attachments:
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
            skipped.append(f"{file_path.name}: {exc}")
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

