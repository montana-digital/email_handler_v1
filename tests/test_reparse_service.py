import hashlib
from email.message import EmailMessage

from app.db.models import InputEmail, OriginalEmail
from app.services.reparse import reparse_email


def _build_email_bytes() -> bytes:
    message = EmailMessage()
    message["From"] = "alerts@example.com"
    message["Subject"] = "Security Alert"
    message["Date"] = "Wed, 12 Nov 2025 19:54:38 -0000"
    message.set_content(
        """Subject: Alert-2025
Date Reported: 2025-11-12T19:54:38
Sending Source: https://phish.example.com/login
URL: https://malicious.example.com/verify
Callback Number: (888) 111-1111
Additional Contacts: helpdesk@example.com
Model Confidence: 0.92
"""
    )
    return message.as_bytes()


def test_reparse_updates_failed_email(db_session):
    payload = _build_email_bytes()
    email_hash = hashlib.sha256(payload).hexdigest()

    input_email = InputEmail(
        email_hash=email_hash,
        parse_status="failed",
        parse_error="Initial failure",
        subject="[Parse Failed] sample",
    )
    db_session.add(input_email)
    db_session.add(
        OriginalEmail(
            email_hash=email_hash,
            file_name="sample.eml",
            mime_type="message/rfc822",
            content=payload,
        )
    )
    db_session.commit()

    result = reparse_email(db_session, input_email.id)
    assert result is not None
    assert result.success
    db_session.refresh(input_email)
    assert input_email.parse_status == "success"
    assert input_email.subject == "Security Alert"
    assert input_email.parse_error is None


def test_reparse_preserves_failure_on_bad_content(db_session):
    payload = b"\x00\x01not-parsable"
    email_hash = hashlib.sha256(payload).hexdigest()

    input_email = InputEmail(
        email_hash=email_hash,
        parse_status="failed",
        parse_error="Initial failure",
        subject="[Parse Failed] sample",
    )
    db_session.add(input_email)
    db_session.add(
        OriginalEmail(
            email_hash=email_hash,
            file_name="sample.eml",
            mime_type="message/rfc822",
            content=payload,
        )
    )
    db_session.commit()

    result = reparse_email(db_session, input_email.id)
    assert result is not None
    assert not result.success
    db_session.refresh(input_email)
    assert input_email.parse_status == "failed"
    assert input_email.parse_error

