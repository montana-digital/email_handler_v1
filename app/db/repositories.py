"""Repository helpers encapsulating common database operations."""

from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import InputEmail, PickleBatch, StandardEmail


def get_input_email(session: Session, email_id: int) -> Optional[InputEmail]:
    return session.get(InputEmail, email_id)


def find_input_email_by_hash(session: Session, email_hash: str) -> Optional[InputEmail]:
    stmt = select(InputEmail).where(InputEmail.email_hash == email_hash)
    return session.execute(stmt).scalar_one_or_none()


def list_input_emails(session: Session, limit: int = 100) -> Iterable[InputEmail]:
    stmt = select(InputEmail).order_by(InputEmail.created_at.desc()).limit(limit)
    return session.scalars(stmt)


def upsert_input_email(session: Session, email: InputEmail) -> InputEmail:
    existing = find_input_email_by_hash(session, email.email_hash)
    if existing:
        for attr in (
            "parse_status",
            "parse_error",
            "subject_id",
            "sender",
            "cc",
            "subject",
            "date_sent",
            "date_reported",
            "sending_source_raw",
            "sending_source_parsed",
            "url_raw",
            "url_parsed",
            "callback_number_raw",
            "callback_number_parsed",
            "additional_contacts",
            "model_confidence",
            "message_id",
            "image_base64",
            "body_html",
        ):
            setattr(existing, attr, getattr(email, attr))
        return existing
    session.add(email)
    return email


def list_standard_emails(session: Session, limit: int = 100) -> Iterable[StandardEmail]:
    stmt = select(StandardEmail).order_by(StandardEmail.created_at.desc()).limit(limit)
    return session.scalars(stmt)


def find_standard_email_by_hash(session: Session, email_hash: str) -> Optional[StandardEmail]:
    stmt = select(StandardEmail).where(StandardEmail.email_hash == email_hash)
    return session.execute(stmt).scalar_one_or_none()


def register_pickle_batch(session: Session, batch: PickleBatch) -> PickleBatch:
    session.add(batch)
    return batch


def list_pickle_batches(session: Session, limit: int = 50) -> List[PickleBatch]:
    stmt = select(PickleBatch).order_by(PickleBatch.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def get_pickle_batch(session: Session, batch_id: int) -> Optional[PickleBatch]:
    return session.get(PickleBatch, batch_id)


def list_emails_by_batch(session: Session, batch_id: int) -> List[InputEmail]:
    stmt = (
        select(InputEmail)
        .where(InputEmail.pickle_batch_id == batch_id)
        .order_by(InputEmail.created_at.desc())
    )
    return list(session.scalars(stmt))

