from __future__ import annotations

import json
from pathlib import Path

from app.db.models import Attachment, InputEmail, StandardEmail
from app.services.standard_email_records import (
    get_standard_email_detail,
    list_standard_email_records,
)


def _build_input_with_attachments(base_dir: Path) -> tuple[InputEmail, list[Attachment]]:
    email = InputEmail(
        email_hash="hash-std-001",
        subject="Quarterly Update",
        sender="alerts@example.com",
        body_html="<p>Hello world</p>",
    )

    image_path = base_dir / "preview.png"
    pdf_path = base_dir / "report.pdf"
    csv_path = base_dir / "data.csv"
    other_path = base_dir / "notes.txt"

    for path in (image_path, pdf_path, csv_path, other_path):
        path.write_bytes(b"unit-test-payload")

    attachments = [
        Attachment(
            file_name="preview.png",
            file_type="image/png",
            file_size_bytes=1234,
            storage_path=str(image_path),
        ),
        Attachment(
            file_name="report.pdf",
            file_type="application/pdf",
            file_size_bytes=2048,
            storage_path=str(pdf_path),
        ),
        Attachment(
            file_name="data.csv",
            file_type="text/csv",
            file_size_bytes=512,
            storage_path=str(csv_path),
        ),
        Attachment(
            file_name="notes.txt",
            file_type="text/plain",
            file_size_bytes=256,
            storage_path=str(other_path),
        ),
    ]
    return email, attachments


def test_list_standard_email_records_includes_attachment_counts(db_session, tmp_path):
    email, attachments = _build_input_with_attachments(tmp_path)
    email.attachments.extend(attachments)
    db_session.add(email)
    db_session.flush()

    standard = StandardEmail(
        email_hash=email.email_hash,
        from_address=email.sender,
        subject=email.subject,
        body_html=email.body_html,
        body_urls=json.dumps(["https://example.com"]),
        body_text_numbers=json.dumps(["+1234567890"]),
        source_input_email=email,
    )
    db_session.add(standard)
    db_session.commit()

    records = list_standard_email_records(db_session, limit=10)
    assert len(records) == 1
    record = records[0]
    assert record["attachment_counts"]["image"] == 1
    assert record["attachment_counts"]["pdf"] == 1
    assert record["attachment_counts"]["csv"] == 1
    assert record["attachment_counts"]["other"] == 1
    assert record["body_urls"] == ["https://example.com"]
    assert record["body_numbers"] == ["+1234567890"]


def test_get_standard_email_detail_returns_attachment_metadata(db_session, tmp_path):
    email, attachments = _build_input_with_attachments(tmp_path)
    email.attachments.extend(attachments)
    db_session.add(email)
    db_session.flush()

    standard = StandardEmail(
        email_hash=email.email_hash,
        from_address=email.sender,
        subject=email.subject,
        body_html=email.body_html,
        body_urls=json.dumps(["https://detail.example"]),
        body_text_numbers=json.dumps(["+15551234567"]),
        source_input_email=email,
    )
    db_session.add(standard)
    db_session.commit()

    detail = get_standard_email_detail(db_session, standard.id)
    assert detail is not None
    assert detail["id"] == standard.id
    assert len(detail["attachments"]) == 4
    categories = {attachment["category"] for attachment in detail["attachments"]}
    assert categories == {"image", "pdf", "csv", "other"}
    paths = [Path(attachment["storage_path"]) for attachment in detail["attachments"]]
    assert all(path.exists() for path in paths)

