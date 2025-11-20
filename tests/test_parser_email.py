from datetime import datetime
from email.message import EmailMessage

from app.parsers.parser_email import (
    _build_subject_id,
    _clean_timestamp_from_subject,
    parse_eml_bytes,
)


def make_test_email() -> bytes:
    message = EmailMessage()
    message["From"] = "alerts@example.com"
    message["Subject"] = "Security Alert"
    message["Date"] = "Wed, 12 Nov 2025 19:54:38 -0000"
    body = """Subject: Alert-2025
Date Reported: 2025-11-12T19:54:38
Sending Source: https://phish.example.com/login
URL: https://malicious.example.com/verify
Callback Number: (888) 111-1111
Additional Contacts: helpdesk@example.com
Model Confidence: 0.92
"""
    message.set_content(body)
    return message.as_bytes()


def test_parse_eml_bytes_extracts_fields():
    data = make_test_email()
    parsed = parse_eml_bytes(data)
    assert parsed.sender == "alerts@example.com"
    # Subject ID should be from Date Reported (YYYYMMDDTHHMMSS format), not from body "Subject:" field
    assert parsed.subject_id == "20251112T195438"
    assert parsed.date_reported is not None
    assert parsed.urls_parsed == ["example.com"]
    assert "+18881111111" in parsed.callback_numbers_parsed
    assert parsed.model_confidence == 0.92


def test_build_subject_id_from_date_reported():
    """Test that _build_subject_id formats datetime correctly."""
    date_reported = datetime(2025, 1, 15, 12, 30, 45)
    subject_id = _build_subject_id(date_reported)
    assert subject_id == "20250115T123045"
    
    # Test with None
    assert _build_subject_id(None) is None


def test_clean_timestamp_from_subject_standard_format():
    """Test cleaning timestamp from subject with standard format: 2025-01-15T12:30:00+00:00"""
    subject = "2025-01-15T12:30:00+00:00"
    result = _clean_timestamp_from_subject(subject)
    assert result == "20250115T123000"
    
    # Test with different timezone
    subject = "2025-01-15T12:30:00-05:00"
    result = _clean_timestamp_from_subject(subject)
    assert result == "20250115T123000"


def test_clean_timestamp_from_subject_with_trailing_zeros():
    """Test that exactly 4 trailing zeros are removed."""
    # Standard format with trailing 0000 (seconds are 00)
    subject = "2025-01-15T12:30:00+00:00"
    result = _clean_timestamp_from_subject(subject)
    assert result == "20250115T123000"
    
    # Compact format with trailing 0000
    subject = "20250115T12300000"
    result = _clean_timestamp_from_subject(subject)
    assert result == "20250115T123000"
    
    # Test that exactly 4 trailing zeros are removed (minutes and seconds are 00)
    # "2025-01-15T12:00:00+00:00" -> "20250115T120000" -> remove "0000" -> "20250115T12"
    # Since length is 11 (not 13), we don't add "00" back
    subject = "2025-01-15T12:00:00+00:00"  # Minutes are 00, seconds are 00
    result = _clean_timestamp_from_subject(subject)
    # The function removes trailing "0000", resulting in "20250115T12"
    assert result == "20250115T12"
    
    # Test case where we have HHMM00 (hours, minutes, seconds=00)
    # After removing "00" (seconds), we should have "20250115T1230" (13 chars), then add "00"
    subject = "2025-01-15T12:30:00+00:00"  # This has non-zero minutes
    result = _clean_timestamp_from_subject(subject)
    # Should be "20250115T123000" (no trailing 0000 to remove since minutes are 30)
    assert result == "20250115T123000"


def test_clean_timestamp_from_subject_variations():
    """Test various timestamp format variations."""
    # Without timezone
    subject = "2025-01-15T12:30:00"
    result = _clean_timestamp_from_subject(subject)
    assert result == "20250115T123000"
    
    # With spaces instead of dashes
    subject = "2025 01 15 T 12 30 00"
    result = _clean_timestamp_from_subject(subject)
    assert result == "20250115T123000"
    
    # Compact format
    subject = "20250115T123000"
    result = _clean_timestamp_from_subject(subject)
    assert result == "20250115T123000"
    
    # With slashes
    subject = "2025/01/15T12:30:00"
    result = _clean_timestamp_from_subject(subject)
    assert result == "20250115T123000"


def test_clean_timestamp_from_subject_invalid():
    """Test that invalid subjects return None."""
    assert _clean_timestamp_from_subject(None) is None
    assert _clean_timestamp_from_subject("") is None
    assert _clean_timestamp_from_subject("Not a timestamp") is None
    assert _clean_timestamp_from_subject("2025") is None  # Too short
    assert _clean_timestamp_from_subject("Security Alert") is None


def test_subject_id_priority_date_reported():
    """Test that Subject ID uses Date Reported when available."""
    message = EmailMessage()
    message["From"] = "test@example.com"
    message["Subject"] = "Some Subject"
    message["Date"] = "Wed, 15 Jan 2025 12:30:00 +0000"
    body = "Date Reported: 2025-01-15T12:30:00+00:00"
    message.set_content(body)
    
    parsed = parse_eml_bytes(message.as_bytes())
    # Should use Date Reported from body
    assert parsed.subject_id == "20250115T123000"


def test_subject_id_priority_subject_header():
    """Test that Subject ID uses Subject header timestamp when Date Reported is not available."""
    message = EmailMessage()
    message["From"] = "test@example.com"
    message["Subject"] = "2025-01-15T12:30:00+00:00"
    message["Date"] = "Wed, 15 Jan 2025 12:30:00 +0000"
    body = "Some email body without Date Reported"
    message.set_content(body)
    
    parsed = parse_eml_bytes(message.as_bytes())
    # Should use Subject header timestamp
    assert parsed.subject_id == "20250115T123000"


def test_subject_id_priority_subject_header_with_trailing_zeros():
    """Test that Subject ID correctly handles trailing zeros in Subject header."""
    message = EmailMessage()
    message["From"] = "test@example.com"
    message["Subject"] = "2025-01-15T12:30:00+00:00"
    message["Date"] = "Wed, 15 Jan 2025 12:30:00 +0000"
    body = "Some email body"
    message.set_content(body)
    
    parsed = parse_eml_bytes(message.as_bytes())
    # Should clean the timestamp correctly
    assert parsed.subject_id == "20250115T123000"


def test_subject_id_fallback_to_body_subject():
    """Test that Subject ID falls back to body Subject field when neither Date Reported nor Subject header work."""
    message = EmailMessage()
    message["From"] = "test@example.com"
    message["Subject"] = "Regular Email Subject"
    message["Date"] = "Wed, 15 Jan 2025 12:30:00 +0000"
    body = "Subject: Alert-2025-001"
    message.set_content(body)
    
    parsed = parse_eml_bytes(message.as_bytes())
    # Should use body Subject field as fallback
    assert parsed.subject_id == "Alert-2025-001"

