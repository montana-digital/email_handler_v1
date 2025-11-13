"""Ingestion service for processing raw email files into the database and cache."""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import Attachment, InputEmail, ParserRun, PickleBatch
from app.db.repositories import find_input_email_by_hash, register_pickle_batch, upsert_input_email
from app.parsers import ParsedAttachment, parse_email_file
from app.utils import sha256_file

ATTACHMENT_ROOT = "attachments"


class IngestionResult(Tuple[PickleBatch, List[int]]):
    """Tuple representing (PickleBatch, list of InputEmail IDs)."""


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


def _record_parser_run(email: InputEmail, parser_name: str, version: str = "1.0.0") -> ParserRun:
    return ParserRun(
        input_email=email,
        parser_name=parser_name,
        version=version,
        status="success",
    )


def _input_email_from_parsed(email_hash: str, parsed) -> InputEmail:
    return InputEmail(
        email_hash=email_hash,
        subject_id=parsed.subject_id,
        sender=parsed.sender,
        cc=json.dumps(parsed.cc),
        subject=parsed.subject,
        date_sent=parsed.date_sent,
        date_reported=parsed.date_reported,
        sending_source_raw=parsed.sending_source_raw,
        sending_source_parsed=json.dumps(parsed.sending_source_parsed),
        url_raw=json.dumps(parsed.urls_raw),
        url_parsed=json.dumps(parsed.urls_parsed),
        callback_number_raw=json.dumps(parsed.callback_numbers_raw),
        callback_number_parsed=json.dumps(parsed.callback_numbers_parsed),
        additional_contacts=parsed.additional_contacts,
        model_confidence=parsed.model_confidence,
        message_id=parsed.message_id,
        image_base64=parsed.image_base64,
        body_html=parsed.body_html or parsed.body_text,
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

    for file_path in files:
        try:
            email_hash = sha256_file(file_path)
            existing = find_input_email_by_hash(session, email_hash)
            if existing:
                logger.info("Skipping already ingested email %s", file_path)
                continue

            parsed = parse_email_file(file_path)
            input_email = _input_email_from_parsed(email_hash, parsed)
            upsert_input_email(session, input_email)
            attachment_models = _create_attachment_models(cfg, email_hash, input_email, parsed.attachments)
            session.add_all(attachment_models)
            session.add(_record_parser_run(input_email, parser_name="Parser1"))
            ingested_emails.append(input_email)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to ingest %s: %s", file_path, exc)
            continue

    if not ingested_emails:
        logger.info("No new emails ingested.")
        return None

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

    return pickle_batch, [email.id for email in ingested_emails]

