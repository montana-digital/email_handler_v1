"""Services for re-running the parsing pipeline on stored emails."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.db.models import InputEmail, OriginalEmail, ParserRun
from app.services.ingestion import _apply_parsed_email, _summarize_failures
from app.services.parsing import detect_candidate, run_parsing_pipeline


@dataclass(slots=True)
class ReparseResult:
    success: bool
    message: str
    email: InputEmail


def reparse_email(session: Session, email_id: int) -> Optional[ReparseResult]:
    email = session.get(InputEmail, email_id)
    if not email:
        return None

    original = (
        session.query(OriginalEmail).filter(OriginalEmail.email_hash == email.email_hash).one_or_none()
    )
    if not original or not original.content:
        raise ValueError("Original email content is unavailable; cannot reparse.")

    suffix = Path(original.file_name or "").suffix or ".eml"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(original.content)
        temp_path = Path(tmp.name)

    candidate = detect_candidate(temp_path, original.content)
    outcome = run_parsing_pipeline(candidate)
    temp_path.unlink(missing_ok=True)

    for attempt in outcome.attempts:
        session.add(
            ParserRun(
                input_email=email,
                parser_name=attempt.name,
                version=attempt.version,
                status=attempt.status,
                error_message=attempt.error_message,
            )
        )

    if outcome.parsed_email:
        _apply_parsed_email(email, outcome.parsed_email)
        session.add(email)
        session.commit()
        logger.info("Reparsed email %s successfully.", email_id)
        return ReparseResult(success=True, message="Parsing successful.", email=email)

    error_message = _summarize_failures(outcome.attempts)
    email.parse_status = "failed"
    email.parse_error = error_message
    session.add(email)
    session.commit()
    logger.warning("Reparse failed for email %s: %s", email_id, error_message)
    return ReparseResult(success=False, message=error_message, email=email)


