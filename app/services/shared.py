"""Shared utilities for email parsing and data transformation used across multiple services.

This module contains functions that are used by multiple services to avoid circular dependencies
and promote code reuse. Functions here should be stateless and not depend on database sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Iterable, List

from loguru import logger
from app.utils.json_helpers import safe_json_dumps

if TYPE_CHECKING:
    from app.db.models import InputEmail
    from app.parsers.models import ParsedEmail


def apply_parsed_email_to_input(
    target: InputEmail,
    parsed: ParsedEmail,
    file_name: str | None = None,
    use_date_sent_for_original: bool = False,
) -> None:
    """Apply parsed email data to an InputEmail model.
    
    This function is shared between ingestion and reparse services to ensure
    consistent data transformation logic.
    
    Args:
        target: InputEmail model to update
        parsed: ParsedEmail data to apply
        file_name: Optional filename for special handling (e.g., "original" in name)
        use_date_sent_for_original: If True and filename contains "original", use date_sent as subject_id
    """
    target.parse_status = "success"
    target.parse_error = None
    
    # Check if filename contains 'original' and feature is enabled
    if use_date_sent_for_original and file_name and "original" in file_name.lower():
        # Use Date Sent as Subject ID (formatted as YYYYMMDDTHHMMSS)
        if parsed.date_sent:
            target.subject_id = parsed.date_sent.strftime("%Y%m%dT%H%M%S")
            logger.info("Using Date Sent as Subject ID for file with 'original' in name: %s -> %s", file_name, target.subject_id)
        else:
            # Fallback to parsed subject_id if date_sent is not available
            target.subject_id = parsed.subject_id
            logger.warning("File '%s' contains 'original' but Date Sent is not available, using parsed Subject ID", file_name)
    else:
        target.subject_id = parsed.subject_id
    
    target.sender = parsed.sender
    target.cc = safe_json_dumps(parsed.cc)
    target.subject = parsed.subject
    target.date_sent = parsed.date_sent
    target.date_reported = parsed.date_reported
    target.sending_source_raw = parsed.sending_source_raw
    target.sending_source_parsed = safe_json_dumps(parsed.sending_source_parsed)
    target.url_raw = safe_json_dumps(parsed.urls_raw)
    target.url_parsed = safe_json_dumps(parsed.urls_parsed)
    target.callback_number_raw = safe_json_dumps(parsed.callback_numbers_raw)
    target.callback_number_parsed = safe_json_dumps(parsed.callback_numbers_parsed)
    target.additional_contacts = parsed.additional_contacts
    target.model_confidence = parsed.model_confidence
    target.message_id = parsed.message_id
    target.image_base64 = parsed.image_base64
    # Store full email body as HTML - prefer HTML, but if only text available, preserve it
    # The body_html field should contain the complete email body content
    if parsed.body_html:
        target.body_html = parsed.body_html
    elif parsed.body_text:
        # If only text is available, wrap it in basic HTML to preserve formatting
        target.body_html = f"<pre>{parsed.body_text}</pre>"
    else:
        target.body_html = None


def summarize_parser_failures(attempts) -> str:
    """Summarize parser failures with user-friendly messages.
    
    Args:
        attempts: List of ParserAttempt objects from parsing pipeline
        
    Returns:
        User-friendly error message summarizing parser failures
    """
    messages = []
    for attempt in attempts:
        if attempt.status == "failed" and attempt.error_message:
            error_msg = attempt.error_message
            
            # Convert technical parser errors to user-friendly messages
            if "codec" in error_msg.lower() and "decode" in error_msg.lower():
                messages.append("Email encoding issue - file may be corrupted or in unsupported format")
            elif "extract-msg" in error_msg.lower() or "extract_msg" in error_msg.lower():
                messages.append("MSG parser unavailable - install 'extract-msg' package")
            elif "mailparser" in error_msg.lower():
                messages.append("Advanced parser unavailable - install 'mail-parser' package (optional)")
            elif "does not resemble an email" in error_msg.lower():
                messages.append("File does not appear to be a valid email")
            else:
                # Keep original message but truncate if too long
                clean_msg = error_msg[:150] + "..." if len(error_msg) > 150 else error_msg
                messages.append(f"{attempt.name}: {clean_msg}")
    
    if messages:
        return "; ".join(messages)
    return "No parser strategy available - check that email file is valid"


def build_pickle_payload_record(email: InputEmail) -> Dict:
    """Build a single pickle payload record from an InputEmail.
    
    This function is shared between ingestion and email_records services to ensure
    consistent pickle payload structure.
    
    Args:
        email: InputEmail model to convert to pickle payload record
        
    Returns:
        Dictionary representing the email in pickle payload format
    """
    from app.utils.json_helpers import safe_json_loads_list
    
    return {
        "id": email.id,
        "email_hash": email.email_hash,
        "subject": email.subject,
        "subject_id": email.subject_id,
        "sender": email.sender,
        "date_sent": email.date_sent.isoformat() if email.date_sent else None,
        "date_reported": email.date_reported.isoformat() if email.date_reported else None,
        # Maintain backward compatibility with "urls" and "callback_numbers"
        "urls": safe_json_loads_list(email.url_parsed),
        "urls_raw": safe_json_loads_list(email.url_raw),
        "urls_parsed": safe_json_loads_list(email.url_parsed),
        "callback_numbers": safe_json_loads_list(email.callback_number_parsed),
        "callback_numbers_raw": safe_json_loads_list(email.callback_number_raw),
        "callback_numbers_parsed": safe_json_loads_list(email.callback_number_parsed),
        "sending_source_raw": email.sending_source_raw,
        "sending_source_parsed": safe_json_loads_list(email.sending_source_parsed),
        "additional_contacts": email.additional_contacts,
        "model_confidence": email.model_confidence,
        "message_id": email.message_id,
        "body_html": email.body_html,
    }


def build_pickle_payload(emails: Iterable[InputEmail]) -> List[Dict]:
    """Build pickle payload from a collection of InputEmail objects.
    
    Args:
        emails: Iterable of InputEmail objects
        
    Returns:
        List of dictionaries representing emails in pickle payload format
    """
    return [build_pickle_payload_record(email) for email in emails]

