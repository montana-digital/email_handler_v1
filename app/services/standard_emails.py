"""Services for promoting parsed input emails to the StandardEmail table."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import InputEmail, StandardEmail
from app.db.repositories import find_standard_email_by_hash
from app.parsers.parser_phones import extract_phone_numbers
from app.parsers.parser_urls import extract_urls
from app.utils.json_helpers import safe_json_loads_list, safe_json_dumps_or_none
from app.utils.validation import validate_email_hash


# Use centralized JSON utilities
_deserialize_list = safe_json_loads_list
_serialize_or_none = safe_json_dumps_or_none


@dataclass(slots=True)
class PromotionResult:
    email_id: int
    created: bool
    standard_email_id: int | None
    reason: str | None = None


def _build_standard_email(input_email: InputEmail) -> StandardEmail:
    cc_values = _deserialize_list(input_email.cc)
    body_source = input_email.body_html or ""

    phones = extract_phone_numbers(body_source)
    urls = extract_urls(body_source)

    standard = StandardEmail(
        email_hash=input_email.email_hash,
        to_address=None,
        from_address=input_email.sender,
        cc=", ".join(cc_values) if cc_values else None,
        subject=input_email.subject,
        date_sent=input_email.date_sent,
        email_size_bytes=None,
        body_html=input_email.body_html,
        body_text_numbers=_serialize_or_none([phone.e164 for phone in phones]),
        body_urls=_serialize_or_none([url.normalized for url in urls]),
        source_input_email=input_email,
    )
    return standard


def promote_to_standard_emails(
    session: Session,
    email_ids: Sequence[int],
    *,
    config: AppConfig | None = None,
) -> List[PromotionResult]:
    """Promote selected InputEmail records to the StandardEmail table."""
    if not email_ids:
        return []

    cfg = config or load_config()
    logger.info("Promoting %d emails to StandardEmail table (env=%s)", len(email_ids), cfg.env_name)

    emails: List[InputEmail] = (
        session.query(InputEmail).filter(InputEmail.id.in_(email_ids)).order_by(InputEmail.id.asc()).all()
    )

    results: List[PromotionResult] = []
    
    # Build existing_by_hash dictionary using a single query to avoid N+1 problem
    # Get all unique, valid email hashes
    email_hashes = []
    invalid_hashes = set()
    for email in emails:
        if not email.email_hash:
            continue  # Skip emails without hash - will be handled in main loop
        # Validate hash format before adding to query
        is_valid, _ = validate_email_hash(email.email_hash)
        if is_valid:
            email_hashes.append(email.email_hash)
        else:
            invalid_hashes.add(email.email_hash)
            logger.warning("Invalid email_hash format for email %s: %s", email.id, email.email_hash)
    
    # Single query to get all existing standard emails
    existing_by_hash = {}
    if email_hashes:
        try:
            from sqlalchemy import select
            from app.db.models import StandardEmail
            stmt = select(StandardEmail).where(StandardEmail.email_hash.in_(email_hashes))
            existing_standards = list(session.execute(stmt).scalars())
            existing_by_hash = {se.email_hash: se for se in existing_standards}
        except Exception as exc:
            logger.error("Error querying existing standard emails: %s", exc)
            # Fall back to empty dict - will handle individually in loop
    
    # Mark invalid hashes as None
    for invalid_hash in invalid_hashes:
        existing_by_hash[invalid_hash] = None

    for email in emails:
        if not email.email_hash:
            results.append(
                PromotionResult(
                    email_id=email.id,
                    created=False,
                    standard_email_id=None,
                    reason="Email record is missing a hash value.",
                )
            )
            continue

        existing = existing_by_hash.get(email.email_hash)
        if existing:
            results.append(
                PromotionResult(
                    email_id=email.id,
                    created=False,
                    standard_email_id=existing.id,
                    reason="Standard email already exists for this hash.",
                )
            )
            continue

        try:
            standard_email = _build_standard_email(email)
            session.add(standard_email)
            session.flush()  # Flush to get the ID, but don't commit yet

            results.append(
                PromotionResult(
                    email_id=email.id,
                    created=True,
                    standard_email_id=standard_email.id,
                    reason=None,
                )
            )
        except Exception as exc:
            # Handle unique constraint violations (email_hash already exists)
            from sqlalchemy.exc import IntegrityError
            if isinstance(exc, IntegrityError) and "email_hash" in str(exc).lower():
                logger.warning("Standard email already exists for hash %s: %s", email.email_hash, exc)
                # Expunge the failed object from session without rolling back all changes
                session.expunge(standard_email)
                # Refresh session state to clear the failed insert
                session.rollback()
                # Try to find the existing record after rollback
                try:
                    existing = find_standard_email_by_hash(session, email.email_hash)
                    if existing:
                        results.append(
                            PromotionResult(
                                email_id=email.id,
                                created=False,
                                standard_email_id=existing.id,
                                reason="Standard email already exists for this hash (race condition).",
                            )
                        )
                    else:
                        results.append(
                            PromotionResult(
                                email_id=email.id,
                                created=False,
                                standard_email_id=None,
                                reason="Standard email already exists for this hash (race condition), but could not retrieve existing record.",
                            )
                        )
                except Exception as lookup_exc:
                    logger.error("Failed to lookup existing standard email after rollback: %s", lookup_exc)
                    results.append(
                        PromotionResult(
                            email_id=email.id,
                            created=False,
                            standard_email_id=None,
                            reason=f"Failed to create standard email due to duplicate hash, and lookup failed: {lookup_exc}",
                        )
                    )
                continue
            else:
                # Re-raise other exceptions - these will be handled by session_scope
                raise

    # Don't commit here - let the caller (session_scope) handle commits
    # This prevents double-commit issues when called from within session_scope()
    logger.info("Standard email promotion completed with %d records.", len(results))
    return results

