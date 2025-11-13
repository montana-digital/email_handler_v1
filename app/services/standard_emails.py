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


def _deserialize_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
        return []
    except json.JSONDecodeError:
        return []


def _serialize_or_none(values: Iterable[str]) -> str | None:
    data = [value for value in values if value]
    if not data:
        return None
    return json.dumps(data)


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
        body_text_numbers=_serialize_or_none(phone.e164 for phone in phones),
        body_urls=_serialize_or_none(url.normalized for url in urls),
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
    existing_by_hash = {email.email_hash: find_standard_email_by_hash(session, email.email_hash) for email in emails}

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

        standard_email = _build_standard_email(email)
        session.add(standard_email)
        session.flush()

        results.append(
            PromotionResult(
                email_id=email.id,
                created=True,
                standard_email_id=standard_email.id,
                reason=None,
            )
        )

    session.commit()
    logger.info("Standard email promotion completed with %d records.", len(results))
    return results

