"""Repository helpers encapsulating common database operations."""

from __future__ import annotations

from typing import Iterable, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.utils.error_handling import format_database_error
from app.utils.validation import validate_batch_id, validate_email_hash, validate_email_id, validate_limit

from .models import InputEmail, PickleBatch, StandardEmail


def get_input_email(session: Session, email_id: int, eager_load_attachments: bool = False) -> Optional[InputEmail]:
    """Get an input email by ID with validation.
    
    Args:
        session: Database session
        email_id: Email ID to retrieve
        eager_load_attachments: If True, eagerly load attachments relationship
        
    Returns:
        InputEmail if found, None otherwise
        
    Raises:
        ValueError: If email_id is invalid
    """
    is_valid, error_msg = validate_email_id(email_id)
    if not is_valid:
        logger.warning("Invalid email_id in get_input_email: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        if eager_load_attachments:
            stmt = select(InputEmail).options(joinedload(InputEmail.attachments)).where(InputEmail.id == email_id)
            return session.execute(stmt).unique().scalar_one_or_none()
        else:
            return session.get(InputEmail, email_id)
    except Exception as exc:
        logger.error("Error retrieving input email %s: %s", email_id, exc)
        raise


def find_input_email_by_hash(session: Session, email_hash: str) -> Optional[InputEmail]:
    """Find an input email by hash with validation.
    
    Args:
        session: Database session
        email_hash: Email hash to search for
        
    Returns:
        InputEmail if found, None otherwise
        
    Raises:
        ValueError: If email_hash is invalid
    """
    is_valid, error_msg = validate_email_hash(email_hash)
    if not is_valid:
        logger.warning("Invalid email_hash in find_input_email_by_hash: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        stmt = select(InputEmail).where(InputEmail.email_hash == email_hash)
        return session.execute(stmt).scalar_one_or_none()
    except Exception as exc:
        logger.error("Error finding input email by hash %s: %s", email_hash[:16] + "...", exc)
        raise


def list_input_emails(session: Session, limit: int = 100) -> Iterable[InputEmail]:
    """List input emails with validation.
    
    Args:
        session: Database session
        limit: Maximum number of emails to return
        
    Returns:
        Iterable of InputEmail objects
        
    Raises:
        ValueError: If limit is invalid
    """
    is_valid, error_msg = validate_limit(limit, min_value=1, max_value=10000)
    if not is_valid:
        logger.warning("Invalid limit in list_input_emails: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        stmt = select(InputEmail).order_by(InputEmail.created_at.desc()).limit(limit)
        return session.scalars(stmt)
    except Exception as exc:
        logger.error("Error listing input emails: %s", exc)
        raise


def upsert_input_email(session: Session, email: InputEmail) -> InputEmail:
    """Upsert an input email with validation and error handling.
    
    Args:
        session: Database session
        email: InputEmail object to upsert
        
    Returns:
        InputEmail that was inserted or updated
        
    Raises:
        ValueError: If email or email_hash is invalid
        IntegrityError: If database constraint violation occurs
    """
    if email is None:
        raise ValueError("Email object cannot be None")
    
    if not email.email_hash:
        raise ValueError("Email hash is required for upsert")
    
    is_valid, error_msg = validate_email_hash(email.email_hash)
    if not is_valid:
        logger.warning("Invalid email_hash in upsert_input_email: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
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
                "knowledge_data",  # Include knowledge_data in updates
            ):
                setattr(existing, attr, getattr(email, attr))
            return existing
        session.add(email)
        return email
    except IntegrityError as exc:
        error_msg = format_database_error(exc, "upsert email")
        logger.error("Integrity error upserting email %s: %s", email.email_hash[:16] + "...", exc)
        raise IntegrityError(error_msg, None, None) from exc
    except Exception as exc:
        logger.error("Error upserting email %s: %s", email.email_hash[:16] + "...", exc)
        raise


def list_standard_emails(session: Session, limit: int = 100) -> Iterable[StandardEmail]:
    """List standard emails with validation.
    
    Args:
        session: Database session
        limit: Maximum number of emails to return
        
    Returns:
        Iterable of StandardEmail objects
        
    Raises:
        ValueError: If limit is invalid
    """
    is_valid, error_msg = validate_limit(limit, min_value=1, max_value=10000)
    if not is_valid:
        logger.warning("Invalid limit in list_standard_emails: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        stmt = select(StandardEmail).order_by(StandardEmail.created_at.desc()).limit(limit)
        return session.scalars(stmt)
    except Exception as exc:
        logger.error("Error listing standard emails: %s", exc)
        raise


def find_standard_email_by_hash(session: Session, email_hash: str) -> Optional[StandardEmail]:
    """Find a standard email by hash with validation.
    
    Args:
        session: Database session
        email_hash: Email hash to search for
        
    Returns:
        StandardEmail if found, None otherwise
        
    Raises:
        ValueError: If email_hash is invalid
    """
    is_valid, error_msg = validate_email_hash(email_hash)
    if not is_valid:
        logger.warning("Invalid email_hash in find_standard_email_by_hash: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        stmt = select(StandardEmail).where(StandardEmail.email_hash == email_hash)
        return session.execute(stmt).scalar_one_or_none()
    except Exception as exc:
        logger.error("Error finding standard email by hash %s: %s", email_hash[:16] + "...", exc)
        raise


def register_pickle_batch(session: Session, batch: PickleBatch) -> PickleBatch:
    """Register a pickle batch with validation.
    
    Args:
        session: Database session
        batch: PickleBatch object to register
        
    Returns:
        PickleBatch that was added
        
    Raises:
        ValueError: If batch is None or invalid
        IntegrityError: If database constraint violation occurs
    """
    if batch is None:
        raise ValueError("Batch object cannot be None")
    
    if not batch.batch_name:
        raise ValueError("Batch name is required")
    
    try:
        session.add(batch)
        return batch
    except IntegrityError as exc:
        error_msg = format_database_error(exc, "register pickle batch")
        logger.error("Integrity error registering pickle batch %s: %s", batch.batch_name, exc)
        raise IntegrityError(error_msg, None, None) from exc
    except Exception as exc:
        logger.error("Error registering pickle batch %s: %s", batch.batch_name, exc)
        raise


def list_pickle_batches(session: Session, limit: int = 50) -> List[PickleBatch]:
    """List pickle batches with validation.
    
    Args:
        session: Database session
        limit: Maximum number of batches to return
        
    Returns:
        List of PickleBatch objects
        
    Raises:
        ValueError: If limit is invalid
    """
    is_valid, error_msg = validate_limit(limit, min_value=1, max_value=1000)
    if not is_valid:
        logger.warning("Invalid limit in list_pickle_batches: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        stmt = select(PickleBatch).order_by(PickleBatch.created_at.desc()).limit(limit)
        return list(session.scalars(stmt))
    except Exception as exc:
        logger.error("Error listing pickle batches: %s", exc)
        raise


def get_pickle_batch(session: Session, batch_id: int) -> Optional[PickleBatch]:
    """Get a pickle batch by ID with validation.
    
    Args:
        session: Database session
        batch_id: Batch ID to retrieve
        
    Returns:
        PickleBatch if found, None otherwise
        
    Raises:
        ValueError: If batch_id is invalid
    """
    is_valid, error_msg = validate_batch_id(batch_id)
    if not is_valid:
        logger.warning("Invalid batch_id in get_pickle_batch: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        return session.get(PickleBatch, batch_id)
    except Exception as exc:
        logger.error("Error retrieving pickle batch %s: %s", batch_id, exc)
        raise


def list_emails_by_batch(session: Session, batch_id: int, eager_load_attachments: bool = False) -> List[InputEmail]:
    """List emails by batch ID with validation.
    
    Args:
        session: Database session
        batch_id: Batch ID to filter by
        eager_load_attachments: If True, eagerly load attachments relationship
        
    Returns:
        List of InputEmail objects
        
    Raises:
        ValueError: If batch_id is invalid
    """
    is_valid, error_msg = validate_batch_id(batch_id)
    if not is_valid:
        logger.warning("Invalid batch_id in list_emails_by_batch: %s", error_msg)
        raise ValueError(error_msg)
    
    try:
        stmt = (
            select(InputEmail)
            .where(InputEmail.pickle_batch_id == batch_id)
            .order_by(InputEmail.created_at.desc())
        )
        if eager_load_attachments:
            stmt = stmt.options(joinedload(InputEmail.attachments))
        return list(session.scalars(stmt).unique())
    except Exception as exc:
        logger.error("Error listing emails for batch %s: %s", batch_id, exc)
        raise

