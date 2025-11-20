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

from bs4 import BeautifulSoup

try:
    import extract_msg
except ImportError:  # pragma: no cover - optional dependency
    extract_msg = None  # type: ignore[assignment]

from loguru import logger

from app.parsers.models import ParsedAttachment, ParsedEmail, ParsedStandardEmail
from app.parsers.parser_phones import extract_phone_numbers
from app.parsers.parser_urls import extract_urls

BODY_FIELD_PATTERN = re.compile(
    r"^\s*(?P<field>[A-Za-z _-]+):\s*(?P<value>.*?)(?=\n\s*[A-Za-z _-]+:|$)",
    re.MULTILINE | re.DOTALL,
)
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
    if text_parts:
        text = "\n".join(text_parts)
    elif html:
        # Convert HTML to text as fallback
        try:
            text = BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
        except Exception:  # noqa: BLE001 - fallback to simple tag stripping
            import re
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
    else:
        text = None
    return html, text


def _html_to_text(html_content: str | None) -> str | None:
    """Convert HTML content to plain text for field extraction.
    
    Handles HTML tables by converting table cells to "Label: Value" format
    for better field extraction compatibility.
    """
    if not html_content:
        return None
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Special handling for HTML tables - convert to "Label: Value" format
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) == 2:
                    # Convert two-column table rows to "Label: Value" format
                    label = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    if label and value:
                        # Remove trailing colon from label if present, then add one
                        label = label.rstrip(":")
                        # Replace the table row with formatted text
                        new_tag = soup.new_tag("div")
                        new_tag.string = f"{label}: {value}"
                        row.replace_with(new_tag)
        
        # Get text and normalize whitespace
        text = soup.get_text(separator="\n", strip=True)
        # Clean up excessive whitespace while preserving line breaks
        import re
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)  # Max 2 consecutive newlines
        return text
    except Exception:  # noqa: BLE001 - fallback to original if parsing fails
        # If BeautifulSoup fails, try simple regex to strip HTML tags
        import re
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = re.sub(r"\s+", " ", text)
        return text.strip() if text.strip() else None


def _extract_body_fields(body_text: str | None) -> dict[str, str]:
    """Extract structured fields from email body text.
    
    Handles both plain text and HTML content by converting HTML to text first.
    """
    if not body_text:
        return {}
    
    # If body_text looks like HTML, convert it to text first
    if body_text.strip().startswith("<") and ">" in body_text:
        body_text = _html_to_text(body_text) or body_text
    
    matches = BODY_FIELD_PATTERN.finditer(body_text)
    data: dict[str, str] = {}
    for match in matches:
        field = match.group("field").strip().lower().replace(" ", "_")
        value = match.group("value").strip()
        # Remove trailing newlines and normalize whitespace
        value = " ".join(value.split())
        if value:  # Only add non-empty values
            data[field] = value
    return data


def _prettify_html(html_content: str | None) -> Optional[str]:
    """Safely prettify HTML content with error handling."""
    if not html_content:
        return None
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.prettify()
    except Exception:  # noqa: BLE001 - return original if prettify fails
        # If prettify fails, return original HTML
        return html_content


def _extract_image_base64(body: str | None) -> Optional[str]:
    if not body:
        return None
    match = DATA_URI_PATTERN.search(body)
    if match:
        return match.group("data")
    return None


def _infer_attachment_mime_type(file_name: str, provided_mime_type: str | None) -> str:
    """Infer MIME type from filename if provided type is missing or generic.
    
    This is especially important for EML attachments which may not have
    the correct MIME type set in MSG files.
    """
    if provided_mime_type and provided_mime_type not in ("application/octet-stream", "binary/octet-stream"):
        return provided_mime_type
    
    # Infer from file extension
    file_name_lower = file_name.lower()
    if file_name_lower.endswith(".eml"):
        return "message/rfc822"
    elif file_name_lower.endswith(".msg"):
        return "application/vnd.ms-outlook"
    elif file_name_lower.endswith((".png",)):
        return "image/png"
    elif file_name_lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    elif file_name_lower.endswith(".gif"):
        return "image/gif"
    elif file_name_lower.endswith(".pdf"):
        return "application/pdf"
    elif file_name_lower.endswith((".doc", ".docx")):
        return "application/msword" if file_name_lower.endswith(".doc") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif file_name_lower.endswith((".xls", ".xlsx")):
        return "application/vnd.ms-excel" if file_name_lower.endswith(".xls") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    # Default fallback
    return provided_mime_type or "application/octet-stream"


def _parse_attachments(message: EmailMessage | Message) -> list[ParsedAttachment]:
    attachments: list[ParsedAttachment] = []
    for part in message.walk():
        disposition = part.get_content_disposition()
        if disposition != "attachment":
            continue
        payload = part.get_payload(decode=True) or b""
        file_name = part.get_filename() or "attachment"
        content_type = _infer_attachment_mime_type(file_name, part.get_content_type())
        attachments.append(
            ParsedAttachment(
                file_name=file_name,
                content_type=content_type,
                content_id=part.get("Content-ID"),
                payload=payload,
                size=len(payload),
            )
        )
    return attachments


def _build_subject_id(date_reported: Optional[datetime]) -> Optional[str]:
    """Build Subject ID from date_reported datetime.
    
    Formats as YYYYMMDDTHHMMSS (no timezone).
    """
    if not date_reported:
        return None
    return date_reported.strftime("%Y%m%dT%H%M%S")


def _clean_timestamp_from_subject(subject: str | None) -> Optional[str]:
    """Extract and clean timestamp from email subject header.
    
    Handles format: 2025-01-15T12:30:00+00:00
    - Removes symbols (dashes, colons, spaces, timezone)
    - Removes trailing 0000 if present
    - Returns cleaned timestamp in YYYYMMDDTHHMMSS format
    
    Args:
        subject: Email subject header string
        
    Returns:
        Cleaned timestamp string (YYYYMMDDTHHMMSS) or None if not a timestamp
    """
    if not subject:
        return None
    
    import re
    
    # Pattern to match timestamp-like format: 2025-01-15T12:30:00+00:00 or variations
    # Matches: YYYY-MM-DDTHH:MM:SS+00:00, YYYY-MM-DDTHH:MM:SS, YYYYMMDDTHHMMSS, etc.
    timestamp_pattern = re.compile(
        r'(\d{4})[-/]?(\d{2})[-/]?(\d{2})[T\s](\d{2})[:]?(\d{2})[:]?(\d{2})([+-]\d{2}[:]?\d{2})?'
    )
    
    match = timestamp_pattern.search(subject)
    if match:
        # Extract components from matched pattern
        year = match.group(1)
        month = match.group(2)
        day = match.group(3)
        hour = match.group(4)
        minute = match.group(5)
        second = match.group(6)
        # Timezone is in group(7) but we ignore it
        
        # Build timestamp: YYYYMMDDTHHMMSS
        timestamp = f"{year}{month}{day}T{hour}{minute}{second}"
        
        # Remove trailing 0000 if present (exactly 4 zeros)
        if timestamp.endswith('0000'):
            timestamp = timestamp[:-4]
            # If we removed seconds, add back "00" to maintain format
            if len(timestamp) == 13:  # YYYYMMDDTHHMM
                timestamp = timestamp + "00"
        
        return timestamp
    
    # If regex pattern didn't match, try simpler pattern for date-only or compact format
    if not match:
        # Try simpler pattern for date-only or compact format
        # Remove all non-digit and non-T characters, check if it looks like timestamp
        cleaned = re.sub(r'[^\dT]', '', subject.upper())
        
        # Check if it has at least 8 digits (date) and looks timestamp-like
        digits_only = cleaned.replace('T', '')
        if len(digits_only) < 8:
            return None
        
        # Ensure T is between date and time if not present and we have time digits
        if 'T' not in cleaned and len(digits_only) > 8:
            cleaned = digits_only[:8] + 'T' + digits_only[8:]
        elif 'T' not in cleaned:
            # Date only - add default time
            cleaned = digits_only[:8] + 'T000000'
        
        # Remove trailing 0000 if present (exactly 4 zeros)
        if cleaned.endswith('0000'):
            cleaned = cleaned[:-4]
        
        # Validate format: should be YYYYMMDDTHHMMSS or YYYYMMDDTHHMM
        if len(cleaned) == 15:  # YYYYMMDDTHHMMSS
            return cleaned
        elif len(cleaned) == 13:  # YYYYMMDDTHHMM
            return cleaned + "00"  # Add seconds
        elif len(cleaned) == 11:  # YYYYMMDDTHH (just hours)
            return cleaned + "0000"  # Add minutes and seconds
        elif len(cleaned) == 8:  # YYYYMMDD only
            return cleaned + "T000000"  # Add default time
        else:
            return None
    
    # Extract components from matched pattern
    year = match.group(1)
    month = match.group(2)
    day = match.group(3)
    hour = match.group(4) if match.group(4) else "00"
    minute = match.group(5) if match.group(5) else "00"
    second = match.group(6) if match.group(6) else "00"
    
    # Build timestamp: YYYYMMDDTHHMMSS
    timestamp = f"{year}{month}{day}T{hour}{minute}{second}"
    
    # Remove trailing 0000 if present (exactly 4 zeros)
    if timestamp.endswith('0000'):
        timestamp = timestamp[:-4]
        # If we removed seconds, add back "00" to maintain format
        if len(timestamp) == 13:  # YYYYMMDDTHHMM
            timestamp = timestamp + "00"
    
    return timestamp


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
        body_html_clean=_prettify_html(html_body),
        attachments=_parse_attachments(message),
        email_size=size_hint,
    )
    # Subject ID priority:
    # 1. Date Reported from body (formatted as YYYYMMDDTHHMMSS)
    # 2. Email Subject header as timestamp (cleaned and formatted)
    # 3. "Subject:" field from body (fallback)
    subject_id = _build_subject_id(parsed.date_reported)
    
    if not subject_id:
        # Try to extract timestamp from email Subject header
        cleaned_timestamp = _clean_timestamp_from_subject(parsed.subject)
        if cleaned_timestamp:
            subject_id = cleaned_timestamp
    
    if not subject_id:
        # Final fallback: body Subject field
        subject_id = body_fields.get("subject")
    
    parsed.subject_id = subject_id
    return parsed


def parse_eml_bytes(data: bytes) -> ParsedEmail:
    message = BytesParser(policy=policy.default).parsebytes(data)
    return _parse_email_message(message, size_hint=len(data))


def parse_msg_file(path: Path) -> ParsedEmail:
    if extract_msg is None:
        raise RuntimeError(
            "MSG parsing is unavailable because the optional 'extract-msg' dependency is not installed."
        )

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
    
    # Prefer HTML for field extraction (HTML often contains structured data in tables)
    # Convert HTML to text for field extraction, falling back to text_body if no HTML
    body_text_for_fields = None
    if html_body:
        body_text_for_fields = _html_to_text(html_body)
    elif text_body:
        body_text_for_fields = text_body

    urls = extract_urls(text_body or html_body or "")
    phones = extract_phone_numbers(text_body or html_body or "")
    body_fields = _extract_body_fields(body_text_for_fields)

    attachments: list[ParsedAttachment] = []
    for att in msg.attachments:
        file_name = att.longFilename or att.shortFilename or "attachment"
        original_mime_type = getattr(att, "mimeType", None) or getattr(att, "contentType", None)
        
        # Infer MIME type from filename if missing or generic (important for EML attachments)
        content_type = _infer_attachment_mime_type(file_name, original_mime_type)
        
        # Try multiple ways to get attachment data
        # extract_msg may store it in different attributes or require saving to disk first
        payload = None
        
        # Method 1: Direct data attribute
        if hasattr(att, "data") and att.data:
            payload = att.data
        # Method 2: Binary attribute
        elif hasattr(att, "binary") and att.binary:
            payload = att.binary
        # Method 3: Try to save and read (extract_msg may require this for some attachments)
        else:
            try:
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_path = Path(tmpdir) / file_name
                    # Try to save attachment to temp file
                    if hasattr(att, "save"):
                        att.save(tmp_path)
                        if tmp_path.exists():
                            payload = tmp_path.read_bytes()
                    # Alternative: try to get data after saving
                    elif hasattr(msg, "saveAttachments"):
                        msg.saveAttachments(tmpdir)
                        saved_path = Path(tmpdir) / file_name
                        if saved_path.exists():
                            payload = saved_path.read_bytes()
            except Exception as exc:
                logger.debug("Failed to extract attachment '%s' via save method: %s", file_name, exc)
        
        # Convert string to bytes if needed
        if isinstance(payload, str):
            payload = payload.encode("utf-8", errors="replace")
        
        # Fallback to empty bytes if still no payload
        if payload is None:
            payload = b""
            logger.warning(
                "MSG attachment '%s' (type: %s) has no extractable data. "
                "This may indicate the attachment was not properly embedded in the MSG file.",
                file_name,
                original_mime_type,
            )
        
        attachments.append(
            ParsedAttachment(
                file_name=file_name,
                content_type=content_type,
                content_id=None,
                payload=payload,
                size=len(payload),
            )
        )

    # Use converted HTML text for body_text if no text_body is available
    final_body_text = text_body
    if not final_body_text and html_body:
        final_body_text = _html_to_text(html_body)
    
    parsed = ParsedEmail(
        sender=message.get("From"),
        cc=_dedupe([addr.strip() for addr in (message.get("Cc") or "").split(",") if addr.strip()]),
        subject=message.get("Subject"),
        date_sent=_parse_date(message.get("Date")),
        body_html=html_body,
        body_text=final_body_text,
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
        body_html_clean=_prettify_html(html_body),
        attachments=attachments,
        email_size=path.stat().st_size,
    )
    # Subject ID priority:
    # 1. Date Reported from body (formatted as YYYYMMDDTHHMMSS)
    # 2. Email Subject header as timestamp (cleaned and formatted)
    # 3. "Subject:" field from body (fallback)
    subject_id = _build_subject_id(parsed.date_reported)
    
    if not subject_id:
        # Try to extract timestamp from email Subject header
        cleaned_timestamp = _clean_timestamp_from_subject(parsed.subject)
        if cleaned_timestamp:
            subject_id = cleaned_timestamp
    
    if not subject_id:
        # Final fallback: body Subject field
        subject_id = body_fields.get("subject")
    
    parsed.subject_id = subject_id
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