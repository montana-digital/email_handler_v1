from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.db.models import Attachment, InputEmail
from app.services.reporting import generate_email_report


def _create_email(db_session, temp_config) -> InputEmail:
    email = InputEmail(
        email_hash="hash-report",
        subject="Report Subject",
        sender="alerts@example.com",
        date_sent=datetime.now(timezone.utc),
        body_html="<p>Callback Number: (888) 111-1111</p><p>URL: https://malicious.example.com</p>",
        url_parsed=json.dumps(["malicious.example.com"]),
        callback_number_parsed=json.dumps(["+18881111111"]),
    )
    db_session.add(email)
    db_session.flush()

    saved_attachment = Attachment(
        input_email=email,
        file_name="report.txt",
        file_type="text/plain",
        file_size_bytes=4,
        storage_path=str(temp_config.output_dir / "attachments" / "report.txt"),
    )
    attachment_path = Path(saved_attachment.storage_path)
    attachment_path.parent.mkdir(parents=True, exist_ok=True)
    attachment_path.write_text("demo", encoding="utf-8")
    db_session.add(saved_attachment)
    db_session.commit()
    return email


def test_generate_email_report_creates_file(db_session, temp_config, tmp_path, monkeypatch):
    email = _create_email(db_session, temp_config)

    artifacts = generate_email_report(db_session, [email.id], config=temp_config)

    assert artifacts is not None
    assert artifacts.html_path.exists()
    assert artifacts.csv_path.exists()

    content = artifacts.html_path.read_text(encoding="utf-8")
    assert "Report Subject" in content
    assert "malicious.example.com" in content
    csv_content = artifacts.csv_path.read_text(encoding="utf-8")
    assert "Report Subject" in csv_content


def test_generate_email_report_returns_none_for_missing_records(db_session, temp_config):
    artifacts = generate_email_report(db_session, [9999], config=temp_config)
    assert artifacts is None

