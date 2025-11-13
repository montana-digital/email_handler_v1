from email.message import EmailMessage
from pathlib import Path

from app.db.models import InputEmail
from app.services.ingestion import ATTACHMENT_ROOT, ingest_emails


def _make_email_with_attachment() -> EmailMessage:
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
    message.add_attachment(b"attachment content", maintype="text", subtype="plain", filename="notes.txt")
    return message


def test_ingestion_creates_records_and_pickle(temp_config, db_session):
    email_path = temp_config.input_dir / "alert.eml"
    email_path.write_bytes(_make_email_with_attachment().as_bytes())

    result = ingest_emails(db_session, config=temp_config)
    assert result is not None
    batch, email_ids = result
    assert len(email_ids) == 1
    assert Path(batch.file_path).exists()

    # Attachments extracted to output directory
    attachment_dir = temp_config.output_dir / ATTACHMENT_ROOT
    assert any(file.name == "notes.txt" for file in attachment_dir.rglob("*") if file.is_file())

    email_record = db_session.get(InputEmail, email_ids[0])
    assert email_record is not None
    assert email_record.pickle_batch_id == batch.id

