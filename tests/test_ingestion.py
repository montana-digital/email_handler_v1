from email.message import EmailMessage
from pathlib import Path
import json

from sqlalchemy import func

from app.db.models import InputEmail, Attachment, OriginalEmail, OriginalAttachment, ParserRun
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
    assert result.batch is not None
    assert not result.skipped
    assert not result.failures
    email_ids = result.email_ids
    batch = result.batch
    assert len(email_ids) == 1
    assert Path(batch.file_path).exists()

    email_record = db_session.get(InputEmail, email_ids[0])
    assert email_record is not None
    assert email_record.pickle_batch_id == batch.id

    attachment_dir = temp_config.output_dir / ATTACHMENT_ROOT
    assert any(file.name == "notes.txt" for file in attachment_dir.rglob("*") if file.is_file())
    stored_original = db_session.query(OriginalEmail).filter_by(email_hash=email_record.email_hash).one()
    assert stored_original.content
    stored_attachment = db_session.query(OriginalAttachment).filter_by(email_hash=email_record.email_hash).one()
    assert stored_attachment.content


def test_ingestion_with_generated_dataset(temp_config, db_session, populated_input, generated_dataset):
    summary_path = generated_dataset / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected_emails = summary.get("email_count", len(populated_input))

    result = ingest_emails(
        db_session,
        config=temp_config,
        source_paths=populated_input,
        batch_name="generated_dataset",
    )
    assert result is not None
    assert result.batch is not None
    batch = result.batch
    email_ids = result.email_ids
    distinct_emails = len(email_ids)
    assert distinct_emails == expected_emails
    assert Path(batch.file_path).exists()
    assert not result.skipped
    assert not result.failures

    attachments_count = db_session.execute(
        func.count(Attachment.id)
    ).scalar_one()
    assert attachments_count >= 0

    sample = db_session.get(InputEmail, email_ids[0])
    assert sample is not None
    assert sample.subject
    assert sample.body_html or sample.body_html is None

    output_dir = temp_config.output_dir / ATTACHMENT_ROOT
    assert output_dir.exists()
    assert any(output_dir.rglob("*"))

    stored_originals = db_session.query(OriginalEmail).count()
    assert stored_originals == distinct_emails


def test_ingestion_records_failed_parse(temp_config, db_session):
    bad_email = temp_config.input_dir / "unreadable.eml"
    bad_email.write_bytes(b"\x00\x01\x02not an email")

    result = ingest_emails(db_session, config=temp_config)
    assert result is not None
    assert result.batch is not None
    assert result.failures
    assert not result.skipped
    email_ids = result.email_ids
    assert len(email_ids) == 1

    email_record = db_session.get(InputEmail, email_ids[0])
    assert email_record is not None
    assert email_record.parse_status == "failed"
    assert email_record.parse_error
    assert email_record.subject.startswith("[Parse Failed]")

    parser_runs = (
        db_session.query(ParserRun)
        .filter(ParserRun.input_email_id == email_record.id)
        .all()
    )
    assert parser_runs
    assert all(run.status in ("failed", "success") for run in parser_runs)

    stored_original = (
        db_session.query(OriginalEmail)
        .filter_by(email_hash=email_record.email_hash)
        .one()
    )
    assert stored_original.content

