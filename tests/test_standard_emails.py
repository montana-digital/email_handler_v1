from __future__ import annotations

import hashlib
import json

from app.db.models import InputEmail, StandardEmail
from app.services.standard_emails import promote_to_standard_emails


def _make_input_email() -> InputEmail:
    # Use proper SHA256 hash (64 characters) for validation
    test_content = b"test email content for hashing"
    email_hash = hashlib.sha256(test_content).hexdigest()
    return InputEmail(
        email_hash=email_hash,
        subject="Test Subject",
        sender="alerts@example.com",
        cc=json.dumps(["cc1@example.com", "cc2@example.com"]),
        body_html="""
        <p>This is a test email.</p>
        <p>Visit https://malicious.example.com/verify</p>
        <p>Call (888) 111-1111 for assistance.</p>
        """,
    )


def test_promote_to_standard_email_creates_record(db_session, temp_config):
    email = _make_input_email()
    db_session.add(email)
    db_session.commit()

    results = promote_to_standard_emails(db_session, [email.id], config=temp_config)

    assert len(results) == 1
    assert results[0].created is True
    assert results[0].standard_email_id is not None

    standard_email = db_session.get(StandardEmail, results[0].standard_email_id)
    assert standard_email is not None
    assert standard_email.from_address == email.sender
    assert standard_email.subject == email.subject

    numbers = json.loads(standard_email.body_text_numbers)
    assert "+18881111111" in numbers

    urls = json.loads(standard_email.body_urls)
    assert any("malicious.example.com" in url for url in urls)


def test_promote_to_standard_email_skips_duplicates(db_session, temp_config):
    email = _make_input_email()
    db_session.add(email)
    db_session.commit()

    first = promote_to_standard_emails(db_session, [email.id], config=temp_config)
    second = promote_to_standard_emails(db_session, [email.id], config=temp_config)

    assert first[0].created is True
    assert second[0].created is False
    assert second[0].reason is not None

