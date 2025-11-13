from __future__ import annotations

import zipfile
from pathlib import Path

from app.db.models import Attachment, InputEmail
from app.services.attachments import export_attachments


def _create_email_with_attachment(db_session, source_file: Path) -> Attachment:
    email = InputEmail(email_hash="hash-attachments")
    db_session.add(email)
    db_session.flush()

    attachment = Attachment(
        input_email=email,
        file_name=source_file.name,
        file_type="image/png",
        file_size_bytes=source_file.stat().st_size,
        subject_id="SUBJECT123",
        storage_path=str(source_file),
    )
    db_session.add(attachment)
    db_session.commit()
    return attachment


def test_export_attachments_creates_files_and_archive(db_session, tmp_path, temp_config):
    source_file = tmp_path / "evidence.png"
    source_file.write_bytes(b"binary-image")

    attachment = _create_email_with_attachment(db_session, source_file)

    destination_root = temp_config.output_dir / "exports_test"
    results, archive_path = export_attachments(db_session, [attachment.id], destination_root)

    assert len(results) == 1
    copied_path = results[0].destination_path
    assert copied_path.exists()
    assert copied_path.name.startswith("SUBJECT123_")

    assert archive_path is not None and archive_path.exists()
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        assert any(name.endswith(source_file.name) for name in names)


def test_export_attachments_skips_missing_files(db_session, tmp_path, temp_config):
    email = InputEmail(email_hash="hash-missing")
    db_session.add(email)
    db_session.flush()

    missing_attachment = Attachment(
        input_email=email,
        file_name="missing.txt",
        file_type="text/plain",
        file_size_bytes=10,
        subject_id="SUBJECT999",
        storage_path=str(tmp_path / "does_not_exist.txt"),
    )
    db_session.add(missing_attachment)
    db_session.commit()

    destination_root = temp_config.output_dir / "exports_missing"
    results, archive = export_attachments(db_session, [missing_attachment.id], destination_root)

    assert results == []
    assert archive is None

