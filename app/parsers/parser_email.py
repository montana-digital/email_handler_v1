"""Parser1 & Parser2 implementations for email content."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional, Tuple

import extract_msg
from bs4 import BeautifulSoup

from app.parsers.models import ParsedAttachment, ParsedEmail, ParsedStandardEmail
from app.parsers.parser_phones import extract_phone_numbers
from app.parsers.parser_urls import extract_urls

BODY_FIELD_PATTERN = re.compile(r"^\s*(?P<field>[A-Za-z _-]+):\s*(?P<value>.+?)\s*$", re.MULTILINE)
DATA_URI_PATTERN = re.compile(r"data:image/(?P<format>[a-zA-Z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=]+)")


def _parse_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None


def _collect_body_text(message: EmailMessage) -> Tuple[Optional[str], Optional[str]]:
    html_parts: list[str] = []
    text_parts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            disposition = part.get_content_disposition()
            if disposition == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset("utf-8")
            decoded = payload.decode(charset, errors="replace")
            content_type = part.get_content_type()
            if content_type == "text/html":
                html_parts.append(decoded)
            elif content_type == "text/plain":
                text_parts.append(decoded)
    else:
        payload = message.get_payload(decode=True)
        if payload:
            decoded = payload.decode(message.get_content_charset("utf-8"), errors="replace")
            if message.get_content_type() == "text/html":
                html_parts.append(decoded)
            else:
                text_parts.append(decoded)

    html = "\n".join(html_parts) if html_parts else None
    text = "\n".join(text_parts) if text_parts else (
        BeautifulSoup(html, "html.parser").get_text("\n") if html else None
    )
    return html, text


def _extract_body_fields(body_text: str | None) -> dict[str, str]:
    if not body_text:
        return {}
    matches = BODY_FIELD_PATTERN.finditer(body_text)
    data: dict[str, str] = {}
    for match in matches:
        field = match.group("field").strip().lower().replace(" ", "_")
        data[field] = match.group("value").strip()
    return data


def _extract_image_base64(body: str | None) -> Optional[str]:
    if not body:
        return None
    match = DATA_URI_PATTERN.search(body)
    if match:
        return match.group("data")
    return None


def _parse_attachments(message: EmailMessage | Message) -> list[ParsedAttachment]:
    attachments: list[ParsedAttachment] = []
    for part in message.walk():
        disposition = part.get_content_disposition()
        if disposition != "attachment":
            continue
        payload = part.get_payload(decode=True) or b""
        attachments.append(
            ParsedAttachment(
                file_name=part.get_filename() or "attachment",
                content_type=part.get_content_type(),
                content_id=part.get("Content-ID"),
                payload=payload,
                size=len(payload),
            )
        )
    return attachments


def _build_subject_id(date_reported: Optional[datetime]) -> Optional[str]:
    if not date_reported:
        return None
    return date_reported.strftime("%Y%m%dT%H%M%S")


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def _parse_email_message(message: EmailMessage, size_hint: int) -> ParsedEmail:
    html_body, text_body = _collect_body_text(message)
    body_fields = _extract_body_fields(text_body or html_body)

    urls = extract_urls(text_body or html_body or "")
    phones = extract_phone_numbers(text_body or html_body or "")

    sending_source_raw = body_fields.get("sending_source")
    additional_contacts = body_fields.get("additional_contacts")
    callback_number_raw = body_fields.get("callback_number")

    parsed = ParsedEmail(
        sender=message.get("From"),
        cc=_dedupe([addr.strip() for addr in (message.get("Cc") or "").split(",") if addr.strip()]),
        subject=message.get("Subject"),
        date_sent=_parse_date(message.get("Date")),
        body_html=html_body,
        body_text=text_body,
        date_reported=_parse_date(body_fields.get("date_reported")),
        sending_source_raw=sending_source_raw,
        sending_source_parsed=_dedupe([result.domain for result in extract_urls(sending_source_raw or "")]),
        urls_raw=_dedupe([item.original for item in urls]),
        urls_parsed=_dedupe([item.domain for item in urls]),
        callback_numbers_raw=[callback_number_raw] if callback_number_raw else [],
        callback_numbers_parsed=[item.e164 for item in phones],
        additional_contacts=additional_contacts,
        model_confidence=float(body_fields["model_confidence"]) if body_fields.get("model_confidence") else None,
        message_id=message.get("Message-ID"),
        image_base64=_extract_image_base64(html_body),
        body_html_clean=BeautifulSoup(html_body, "html.parser").prettify() if html_body else None,
        attachments=_parse_attachments(message),
        email_size=size_hint,
    )
    parsed.subject_id = body_fields.get("subject") or _build_subject_id(parsed.date_reported)
    return parsed


def parse_eml_bytes(data: bytes) -> ParsedEmail:
    message = BytesParser(policy=policy.default).parsebytes(data)
    return _parse_email_message(message, size_hint=len(data))


def parse_msg_file(path: Path) -> ParsedEmail:
    msg = extract_msg.Message(str(path))
    message = EmailMessage()
    message["From"] = msg.sender or msg.sender_email
    message["To"] = msg.to
    message["Cc"] = msg.cc
    message["Subject"] = msg.subject
    message["Date"] = msg.date
    message["Message-ID"] = getattr(msg, "message_id", None) or getattr(msg, "messageId", None)

    html_body = msg.htmlBody or None
    if isinstance(html_body, bytes):
        html_body = html_body.decode("utf-8", errors="replace")
    text_body = msg.body or None
    if isinstance(text_body, bytes):
        text_body = text_body.decode("utf-8", errors="replace")

    urls = extract_urls(text_body or html_body or "")
    phones = extract_phone_numbers(text_body or html_body or "")
    body_fields = _extract_body_fields(text_body or html_body)

    attachments: list[ParsedAttachment] = []
    for att in msg.attachments:
        payload = att.data or b""
        attachments.append(
            ParsedAttachment(
                file_name=att.longFilename or att.shortFilename or "attachment",
                content_type=att.mimeType,
                content_id=None,
                payload=payload,
                size=len(payload),
            )
        )

    parsed = ParsedEmail(
        sender=message.get("From"),
        cc=_dedupe([addr.strip() for addr in (message.get("Cc") or "").split(",") if addr.strip()]),
        subject=message.get("Subject"),
        date_sent=_parse_date(message.get("Date")),
        body_html=html_body,
        body_text=text_body,
        date_reported=_parse_date(body_fields.get("date_reported")),
        sending_source_raw=body_fields.get("sending_source"),
        sending_source_parsed=_dedupe(
            [result.domain for result in extract_urls(body_fields.get("sending_source", ""))]
        ),
        urls_raw=_dedupe([item.original for item in urls]),
        urls_parsed=_dedupe([item.domain for item in urls]),
        callback_numbers_raw=[body_fields.get("callback_number")] if body_fields.get("callback_number") else [],
        callback_numbers_parsed=[item.e164 for item in phones],
        additional_contacts=body_fields.get("additional_contacts"),
        model_confidence=float(body_fields["model_confidence"]) if body_fields.get("model_confidence") else None,
        message_id=message.get("Message-ID"),
        image_base64=_extract_image_base64(html_body),
        body_html_clean=BeautifulSoup(html_body, "html.parser").prettify() if html_body else None,
        attachments=attachments,
        email_size=path.stat().st_size,
    )
    parsed.subject_id = body_fields.get("subject") or _build_subject_id(parsed.date_reported)
    return parsed


def parse_input_email(path: Path, data: bytes | None = None) -> ParsedEmail:
    if path.suffix.lower() == ".msg":
        return parse_msg_file(path)
    payload = data if data is not None else path.read_bytes()
    return parse_eml_bytes(payload)


def parse_standard_email(path: Path, data: bytes | None = None) -> ParsedStandardEmail:
    parsed = parse_input_email(path, data)
    urls = extract_urls(parsed.body_text or parsed.body_html or "")
    phones = extract_phone_numbers(parsed.body_text or parsed.body_html or "")
    return ParsedStandardEmail(
        to_address=None,  # not provided in raw models
        from_address=parsed.sender,
        cc=", ".join(parsed.cc) if parsed.cc else None,
        subject=parsed.subject,
        date_sent=parsed.date_sent,
        email_size=parsed.email_size,
        body_html=parsed.body_html,
        body_text_numbers=_dedupe([item.e164 for item in phones]),
        body_urls=_dedupe([item.normalized for item in urls]),
        message_id=parsed.message_id,
    )


def parse_email_file(path: Path, data: bytes | None = None) -> ParsedEmail:
    return parse_input_email(path, data)