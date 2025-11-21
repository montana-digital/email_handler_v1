"""Tests for the 'original' filename feature that uses Date Sent as Subject ID."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models import InputEmail
from app.services.ingestion import _apply_parsed_email, _input_email_from_parsed
from app.parsers.models import ParsedEmail


class MockParsedEmail:
    """Mock ParsedEmail for testing."""
    def __init__(self, subject_id: str | None, date_sent: datetime | None):
        self.subject_id = subject_id
        self.date_sent = date_sent
        self.sender = "test@example.com"
        self.cc = []
        self.subject = "Test Subject"
        self.date_reported = None
        self.sending_source_raw = None
        self.sending_source_parsed = []
        self.urls_raw = []
        self.urls_parsed = []
        self.callback_numbers_raw = []  # Note: plural, not singular
        self.callback_numbers_parsed = []
        self.additional_contacts = None
        self.model_confidence = None
        self.message_id = None
        self.image_base64 = None
        self.body_html = None
        self.body_text = None


def test_apply_parsed_email_with_original_filename_enabled():
    """Test that Date Sent is used as Subject ID when filename contains 'original' and feature is enabled."""
    email = InputEmail(email_hash="test_hash")
    parsed = MockParsedEmail(
        subject_id="2025-01-15",
        date_sent=datetime(2025, 1, 20, 14, 30, 45)
    )
    
    # Test with 'original' in filename and feature enabled
    _apply_parsed_email(email, parsed, file_name="original_email.eml", use_date_sent_for_original=True)
    
    # Should use Date Sent formatted as YYYYMMDDTHHMMSS
    assert email.subject_id == "20250120T143045"
    assert email.parse_status == "success"


def test_apply_parsed_email_with_original_filename_disabled():
    """Test that parsed Subject ID is used when feature is disabled."""
    email = InputEmail(email_hash="test_hash")
    parsed = MockParsedEmail(
        subject_id="2025-01-15",
        date_sent=datetime(2025, 1, 20, 14, 30, 45)
    )
    
    # Test with 'original' in filename but feature disabled
    _apply_parsed_email(email, parsed, file_name="original_email.eml", use_date_sent_for_original=False)
    
    # Should use parsed Subject ID
    assert email.subject_id == "2025-01-15"
    assert email.parse_status == "success"


def test_apply_parsed_email_without_original_in_filename():
    """Test that parsed Subject ID is used when filename doesn't contain 'original'."""
    email = InputEmail(email_hash="test_hash")
    parsed = MockParsedEmail(
        subject_id="2025-01-15",
        date_sent=datetime(2025, 1, 20, 14, 30, 45)
    )
    
    # Test with feature enabled but no 'original' in filename
    _apply_parsed_email(email, parsed, file_name="regular_email.eml", use_date_sent_for_original=True)
    
    # Should use parsed Subject ID (not Date Sent)
    assert email.subject_id == "2025-01-15"
    assert email.parse_status == "success"


def test_apply_parsed_email_original_case_insensitive():
    """Test that 'original' detection is case-insensitive."""
    email = InputEmail(email_hash="test_hash")
    parsed = MockParsedEmail(
        subject_id="2025-01-15",
        date_sent=datetime(2025, 1, 20, 14, 30, 45)
    )
    
    # Test with uppercase 'ORIGINAL'
    _apply_parsed_email(email, parsed, file_name="ORIGINAL_email.eml", use_date_sent_for_original=True)
    assert email.subject_id == "20250120T143045"
    
    # Test with mixed case
    email2 = InputEmail(email_hash="test_hash2")
    _apply_parsed_email(email2, parsed, file_name="Original_Email.eml", use_date_sent_for_original=True)
    assert email2.subject_id == "20250120T143045"


def test_apply_parsed_email_original_no_date_sent():
    """Test fallback to parsed Subject ID when Date Sent is not available."""
    email = InputEmail(email_hash="test_hash")
    parsed = MockParsedEmail(
        subject_id="2025-01-15",
        date_sent=None  # No Date Sent
    )
    
    # Test with 'original' in filename and feature enabled, but no Date Sent
    _apply_parsed_email(email, parsed, file_name="original_email.eml", use_date_sent_for_original=True)
    
    # Should fallback to parsed Subject ID
    assert email.subject_id == "2025-01-15"
    assert email.parse_status == "success"


def test_input_email_from_parsed_with_original():
    """Test the full flow from parsed email to InputEmail with original filename feature."""
    parsed = MockParsedEmail(
        subject_id="2025-01-15",
        date_sent=datetime(2025, 1, 20, 14, 30, 45)
    )
    
    # Test with 'original' in filename and feature enabled
    email = _input_email_from_parsed(
        "test_hash",
        parsed,
        file_name="original_email.eml",
        use_date_sent_for_original=True
    )
    
    assert email.email_hash == "test_hash"
    assert email.subject_id == "20250120T143045"
    assert email.parse_status == "success"


def test_input_email_from_parsed_without_original():
    """Test the full flow when filename doesn't contain 'original'."""
    parsed = MockParsedEmail(
        subject_id="2025-01-15",
        date_sent=datetime(2025, 1, 20, 14, 30, 45)
    )
    
    # Test without 'original' in filename
    email = _input_email_from_parsed(
        "test_hash",
        parsed,
        file_name="regular_email.eml",
        use_date_sent_for_original=True
    )
    
    assert email.email_hash == "test_hash"
    assert email.subject_id == "2025-01-15"  # Uses parsed Subject ID
    assert email.parse_status == "success"


def test_date_sent_formatting():
    """Test that Date Sent is correctly formatted as YYYYMMDDTHHMMSS."""
    email = InputEmail(email_hash="test_hash")
    
    # Test various dates
    test_cases = [
        (datetime(2025, 1, 20, 14, 30, 45), "20250120T143045"),
        (datetime(2024, 12, 31, 23, 59, 59), "20241231T235959"),
        (datetime(2025, 1, 1, 0, 0, 0), "20250101T000000"),
        (datetime(2025, 6, 15, 9, 5, 3), "20250615T090503"),
    ]
    
    for date_sent, expected_subject_id in test_cases:
        parsed = MockParsedEmail(
            subject_id="parsed_id",
            date_sent=date_sent
        )
        email = InputEmail(email_hash="test_hash")
        _apply_parsed_email(email, parsed, file_name="original_email.eml", use_date_sent_for_original=True)
        assert email.subject_id == expected_subject_id, f"Failed for {date_sent}"


def test_original_in_middle_of_filename():
    """Test that 'original' is detected even when it's in the middle of the filename."""
    email = InputEmail(email_hash="test_hash")
    parsed = MockParsedEmail(
        subject_id="2025-01-15",
        date_sent=datetime(2025, 1, 20, 14, 30, 45)
    )
    
    # Test with 'original' in the middle
    _apply_parsed_email(email, parsed, file_name="email_original_backup.eml", use_date_sent_for_original=True)
    assert email.subject_id == "20250120T143045"
    
    # Test with 'original' at the end
    email2 = InputEmail(email_hash="test_hash2")
    _apply_parsed_email(email2, parsed, file_name="backup_original.eml", use_date_sent_for_original=True)
    assert email2.subject_id == "20250120T143045"

