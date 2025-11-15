"""SQLAlchemy ORM models for the Email Handler application."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class InputEmail(Base):
    __tablename__ = "input_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    parse_status: Mapped[str] = mapped_column(String(32), default="success", server_default="success")
    parse_error: Mapped[Optional[str]] = mapped_column(Text, default=None)
    subject_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, default=None)
    sender: Mapped[Optional[str]] = mapped_column(String(320), default=None)
    cc: Mapped[Optional[str]] = mapped_column(Text, default=None)
    subject: Mapped[Optional[str]] = mapped_column(Text, default=None)
    date_sent: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    date_reported: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    sending_source_raw: Mapped[Optional[str]] = mapped_column(Text, default=None)
    sending_source_parsed: Mapped[Optional[str]] = mapped_column(Text, default=None)
    url_raw: Mapped[Optional[str]] = mapped_column(Text, default=None)
    url_parsed: Mapped[Optional[str]] = mapped_column(Text, default=None)
    callback_number_raw: Mapped[Optional[str]] = mapped_column(Text, default=None)
    callback_number_parsed: Mapped[Optional[str]] = mapped_column(Text, default=None)
    additional_contacts: Mapped[Optional[str]] = mapped_column(Text, default=None)
    model_confidence: Mapped[Optional[float]] = mapped_column(Float, default=None)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, default=None)
    image_base64: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_html: Mapped[Optional[str]] = mapped_column(Text, default=None)
    pickle_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pickle_batches.id"), index=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    attachments: Mapped[list[Attachment]] = relationship(
        "Attachment", back_populates="input_email", cascade="all, delete-orphan"
    )
    parser_runs: Mapped[list[ParserRun]] = relationship(
        "ParserRun", back_populates="input_email", cascade="all, delete-orphan"
    )
    pickle_batch: Mapped[Optional["PickleBatch"]] = relationship("PickleBatch", back_populates="input_emails")


class OriginalEmail(Base):
    __tablename__ = "original_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    content: Mapped[bytes] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OriginalAttachment(Base):
    __tablename__ = "original_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_hash: Mapped[str] = mapped_column(String(128), index=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    content: Mapped[bytes] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StandardEmail(Base):
    __tablename__ = "standard_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    to_address: Mapped[Optional[str]] = mapped_column(Text, default=None)
    from_address: Mapped[Optional[str]] = mapped_column(Text, default=None)
    cc: Mapped[Optional[str]] = mapped_column(Text, default=None)
    subject: Mapped[Optional[str]] = mapped_column(Text, default=None)
    date_sent: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    email_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    body_html: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_text_numbers: Mapped[Optional[str]] = mapped_column(Text, default=None)
    body_urls: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_input_email_id: Mapped[Optional[int]] = mapped_column(ForeignKey("input_emails.id"), default=None)

    source_input_email: Mapped[Optional[InputEmail]] = relationship("InputEmail")


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (UniqueConstraint("input_email_id", "file_name", name="uq_attachment_email_filename"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_email_id: Mapped[int] = mapped_column(ForeignKey("input_emails.id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[Optional[str]] = mapped_column(String(50), default=None)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    subject_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, default=None)
    storage_path: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    input_email: Mapped[InputEmail] = relationship("InputEmail", back_populates="attachments")


class PickleBatch(Base):
    __tablename__ = "pickle_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_name: Mapped[str] = mapped_column(String(255), unique=True)
    file_path: Mapped[str] = mapped_column(Text)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    input_emails: Mapped[List[InputEmail]] = relationship(
        "InputEmail", back_populates="pickle_batch", cascade="all, save-update"
    )


class ParserRun(Base):
    __tablename__ = "parser_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_email_id: Mapped[int] = mapped_column(ForeignKey("input_emails.id", ondelete="CASCADE"))
    parser_name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[str] = mapped_column(String(32), default="success")
    notes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)

    input_email: Mapped[InputEmail] = relationship("InputEmail", back_populates="parser_runs")

