"""Shared data models for parsed email content."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ParsedAttachment(BaseModel):
    file_name: str
    content_type: Optional[str] = None
    content_id: Optional[str] = None
    payload: bytes
    size: int = Field(..., ge=0)


class ParsedEmail(BaseModel):
    sender: Optional[str] = None
    cc: List[str] = Field(default_factory=list)
    subject: Optional[str] = None
    date_sent: Optional[datetime] = None
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    subject_id: Optional[str] = None
    date_reported: Optional[datetime] = None
    sending_source_raw: Optional[str] = None
    sending_source_parsed: List[str] = Field(default_factory=list)
    urls_raw: List[str] = Field(default_factory=list)
    urls_parsed: List[str] = Field(default_factory=list)
    callback_numbers_raw: List[str] = Field(default_factory=list)
    callback_numbers_parsed: List[str] = Field(default_factory=list)
    additional_contacts: Optional[str] = None
    model_confidence: Optional[float] = None
    message_id: Optional[str] = None
    image_base64: Optional[str] = None
    body_html_clean: Optional[str] = None
    attachments: List[ParsedAttachment] = Field(default_factory=list)
    email_size: int = Field(..., ge=0)


class ParsedStandardEmail(BaseModel):
    to_address: Optional[str] = None
    from_address: Optional[str] = None
    cc: Optional[str] = None
    subject: Optional[str] = None
    date_sent: Optional[datetime] = None
    email_size: int = Field(..., ge=0)
    body_html: Optional[str] = None
    body_text_numbers: List[str] = Field(default_factory=list)
    body_urls: List[str] = Field(default_factory=list)
    message_id: Optional[str] = None

