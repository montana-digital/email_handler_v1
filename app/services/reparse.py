"""Services for re-running the parsing pipeline on stored emails."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.db.models import InputEmail, OriginalEmail, ParserRun
from app.services.parsing import detect_candidate, run_parsing_pipeline
from app.services.shared import apply_parsed_email_to_input, summarize_parser_failures
from app.utils.validation import validate_email_id


@dataclass(slots=True)
class ReparseResult:
    success: bool
    message: str
    email: InputEmail


def reparse_email(session: Session, email_id: int) -> Optional[ReparseResult]:
    """Reparse an email using stored original content.
    
    Args:
        session: Database session
        email_id: Email ID to reparse
        
    Returns:
        ReparseResult if successful, None if email not found
        
    Raises:
        ValueError: If email_id is invalid or original content unavailable
    """
    is_valid, error_msg = validate_email_id(email_id)
    if not is_valid:
        logger.warning("Invalid email_id in reparse_email: %s", error_msg)
        raise ValueError(error_msg)
    
    email = session.get(InputEmail, email_id)
    if not email:
        return None

    original = (
        session.query(OriginalEmail).filter(OriginalEmail.email_hash == email.email_hash).one_or_none()
    )
    if not original or not original.content:
        raise ValueError("Original email content is unavailable; cannot reparse.")

    suffix = Path(original.file_name or "").suffix or ".eml"

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(original.content)
            temp_path = Path(tmp.name)

        candidate = detect_candidate(temp_path, original.content)
        outcome = run_parsing_pipeline(candidate)
    finally:
        # Always clean up temporary file, even if an exception occurs
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except Exception as cleanup_exc:
                logger.warning("Failed to clean up temporary file %s: %s", temp_path, cleanup_exc)

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
        apply_parsed_email_to_input(email, outcome.parsed_email)
        # Don't commit here - let the caller (session_scope) handle commits
        session.add(email)
        logger.info("Reparsed email %s successfully.", email_id)
        return ReparseResult(success=True, message="Parsing successful.", email=email)

    error_message = summarize_parser_failures(outcome.attempts)
    email.parse_status = "failed"
    email.parse_error = error_message
    # Don't commit here - let the caller (session_scope) handle commits
    session.add(email)
    logger.warning("Reparse failed for email %s: %s", email_id, error_message)
    return ReparseResult(success=False, message=error_message, email=email)


