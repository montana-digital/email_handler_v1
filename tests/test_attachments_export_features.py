"""Tests for attachment export features including subjectID prefix and error handling."""

from __future__ import annotations

import base64
from pathlib import Path
from email.message import EmailMessage

import pytest
from sqlalchemy.orm import Session

from app.db.models import Attachment, InputEmail, PickleBatch
from app.services.attachments import (
    build_destination_name,
    export_attachments,
    generate_image_grid_report,
    AttachmentCategory,
)


def test_build_destination_name_with_subject_id(db_session: Session, tmp_path: Path):
    """Test that build_destination_name uses subject_id when available."""
    # Create email with subject_id
    email = InputEmail(
        email_hash="test_hash_123",
        subject_id="2025-01-15",
        subject="Test Email",
        sender="test@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create attachment with subject_id
    attachment = Attachment(
        input_email=email,
        file_name="image.png",
        file_type="image/png",
        file_size_bytes=1024,
        storage_path=str(tmp_path / "test.png"),
        subject_id="2025-01-15",
    )
    db_session.add(attachment)
    db_session.flush()

    result = build_destination_name(attachment)
    assert result == "2025-01-15_image.png"
    assert result.startswith("2025-01-15_")


def test_build_destination_name_fallback_to_email_subject_id(db_session: Session, tmp_path: Path):
    """Test that build_destination_name falls back to email.subject_id."""
    # Create email with subject_id but attachment without
    email = InputEmail(
        email_hash="test_hash_456",
        subject_id="2025-01-16",
        subject="Test Email 2",
        sender="test2@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create attachment without subject_id
    attachment = Attachment(
        input_email=email,
        file_name="document.pdf",
        file_type="application/pdf",
        file_size_bytes=2048,
        storage_path=str(tmp_path / "test.pdf"),
        subject_id=None,  # No subject_id on attachment
    )
    db_session.add(attachment)
    db_session.flush()

    result = build_destination_name(attachment)
    assert result == "2025-01-16_document.pdf"
    assert result.startswith("2025-01-16_")


def test_build_destination_name_fallback_to_email_hash(db_session: Session, tmp_path: Path):
    """Test that build_destination_name falls back to email_hash when no subject_id."""
    # Create email without subject_id
    email = InputEmail(
        email_hash="abc123def456",
        subject_id=None,
        subject="Test Email 3",
        sender="test3@example.com",
    )
    db_session.add(email)
    db_session.flush()

    attachment = Attachment(
        input_email=email,
        file_name="file.txt",
        file_type="text/plain",
        file_size_bytes=512,
        storage_path=str(tmp_path / "test.txt"),
        subject_id=None,
    )
    db_session.add(attachment)
    db_session.flush()

    result = build_destination_name(attachment)
    assert result == "abc123def456_file.txt"
    assert result.startswith("abc123def456_")


def test_build_destination_name_fallback_to_attachment_id(db_session: Session, tmp_path: Path):
    """Test that build_destination_name falls back to attachment ID when no email relationship available."""
    # Create email with hash but no subject_id (valid case)
    email = InputEmail(
        email_hash="test_hash_for_fallback",
        subject_id=None,  # No subject_id
        subject="Test Email",
        sender="test@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create attachment without subject_id
    attachment = Attachment(
        input_email=email,
        file_name="test.png",
        file_type="image/png",
        file_size_bytes=1024,
        storage_path=str(tmp_path / "test.png"),
        subject_id=None,
    )
    db_session.add(attachment)
    db_session.flush()

    # Test normal case - should use email_hash
    result = build_destination_name(attachment)
    assert result.startswith("test_hash_for_fallback_")
    assert "test.png" in result

    # Now test the edge case where relationship is not loaded (simulate detached object)
    # This tests the final fallback to attachment ID
    from sqlalchemy.orm import object_session
    session = object_session(attachment)
    if session:
        session.expunge(attachment)  # Detach from session
    
    # Manually set input_email to None to test fallback
    attachment.input_email = None
    result_fallback = build_destination_name(attachment)
    assert result_fallback.startswith("att_")
    assert "test.png" in result_fallback
    assert str(attachment.id) in result_fallback


def test_export_attachments_with_subject_id_prefix(db_session: Session, tmp_path: Path, temp_config):
    """Test that exported attachments have subjectID prefix in filename."""
    # Create email with subject_id
    email = InputEmail(
        email_hash="export_test_hash",
        subject_id="2025-01-20",
        subject="Export Test",
        sender="export@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create test image file
    test_image = tmp_path / "test_image.png"
    test_image.write_bytes(b"fake image data")

    # Create attachment
    attachment = Attachment(
        input_email=email,
        file_name="test_image.png",
        file_type="image/png",
        file_size_bytes=len(test_image.read_bytes()),
        storage_path=str(test_image),
        subject_id="2025-01-20",
    )
    db_session.add(attachment)
    db_session.flush()

    # Export
    destination = tmp_path / "export"
    results, archive_path = export_attachments(
        db_session,
        attachment_ids=[attachment.id],
        destination_root=destination,
        create_archive=True,
    )

    assert len(results) == 1
    assert results[0].destination_path.name.startswith("2025-01-20_")
    assert results[0].destination_path.name == "2025-01-20_test_image.png"
    assert archive_path is not None
    assert archive_path.exists()


def test_export_attachments_handles_duplicate_filenames(db_session: Session, tmp_path: Path, temp_config):
    """Test that export handles duplicate destination filenames by appending numbers."""
    # Create two emails with same subject_id (different emails, same subjectID)
    email1 = InputEmail(
        email_hash="dup_test_1",
        subject_id="2025-01-21",
        subject="Duplicate Test 1",
        sender="dup1@example.com",
    )
    email2 = InputEmail(
        email_hash="dup_test_2",
        subject_id="2025-01-21",  # Same subject_id
        subject="Duplicate Test 2",
        sender="dup2@example.com",
    )
    db_session.add_all([email1, email2])
    db_session.flush()

    # Create two attachments from different emails but same filename
    test_file1 = tmp_path / "same_name.png"
    test_file1.write_bytes(b"image1")
    test_file2 = tmp_path / "same_name2.png"
    test_file2.write_bytes(b"image2")

    attachment1 = Attachment(
        input_email=email1,
        file_name="same_name.png",
        file_type="image/png",
        file_size_bytes=6,
        storage_path=str(test_file1),
        subject_id="2025-01-21",
    )
    attachment2 = Attachment(
        input_email=email2,
        file_name="same_name.png",  # Same filename, different email
        file_type="image/png",
        file_size_bytes=6,
        storage_path=str(test_file2),
        subject_id="2025-01-21",
    )
    db_session.add_all([attachment1, attachment2])
    db_session.flush()

    destination = tmp_path / "export"
    results, _ = export_attachments(
        db_session,
        attachment_ids=[attachment1.id, attachment2.id],
        destination_root=destination,
        create_archive=False,
    )

    assert len(results) == 2
    # Both will have same prefix (subject_id) and same filename, so one should get _1 appended
    names = [r.destination_path.name for r in results]
    assert "2025-01-21_same_name.png" in names
    assert any("_1.png" in name for name in names)


def test_export_attachments_handles_missing_files(db_session: Session, tmp_path: Path, temp_config):
    """Test that export gracefully handles missing source files."""
    email = InputEmail(
        email_hash="missing_file_test",
        subject_id="2025-01-22",
        subject="Missing File Test",
        sender="missing@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create attachment pointing to non-existent file
    attachment = Attachment(
        input_email=email,
        file_name="missing.png",
        file_type="image/png",
        file_size_bytes=0,
        storage_path=str(tmp_path / "does_not_exist.png"),
        subject_id="2025-01-22",
    )
    db_session.add(attachment)
    db_session.flush()

    destination = tmp_path / "export"
    results, archive_path = export_attachments(
        db_session,
        attachment_ids=[attachment.id],
        destination_root=destination,
        create_archive=False,
    )

    # Should skip the missing file
    assert len(results) == 0
    assert archive_path is None


def test_generate_image_grid_report_with_subject_id(db_session: Session, tmp_path: Path, temp_config):
    """Test that image grid report includes subject_id information."""
    # Create email with subject_id
    email = InputEmail(
        email_hash="grid_test_hash",
        subject_id="2025-01-23",
        subject="Grid Test Email",
        sender="grid@example.com",
        url_parsed='["https://example.com"]',
    )
    db_session.add(email)
    db_session.flush()

    # Create test image
    test_image = tmp_path / "grid_test.png"
    test_image.write_bytes(b"fake png data")

    attachment = Attachment(
        input_email=email,
        file_name="grid_test.png",
        file_type="image/png",
        file_size_bytes=len(test_image.read_bytes()),
        storage_path=str(test_image),
        subject_id="2025-01-23",
    )
    db_session.add(attachment)
    db_session.flush()

    # Generate report
    report_path = tmp_path / "image_grid.html"
    result_path = generate_image_grid_report(
        db_session,
        attachment_ids=[attachment.id],
        output_path=report_path,
    )

    assert result_path == report_path
    assert report_path.exists()

    # Check that HTML contains subject_id
    html_content = report_path.read_text(encoding="utf-8")
    assert "2025-01-23" in html_content
    assert "Grid Test Email" in html_content
    assert "grid_test.png" in html_content


def test_generate_image_grid_report_handles_large_images(db_session: Session, tmp_path: Path, temp_config):
    """Test that image grid report skips images that are too large."""
    email = InputEmail(
        email_hash="large_image_test",
        subject_id="2025-01-24",
        subject="Large Image Test",
        sender="large@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create a large image file (>10MB)
    large_image = tmp_path / "large.png"
    large_image.write_bytes(b"x" * (11 * 1024 * 1024))  # 11MB

    attachment = Attachment(
        input_email=email,
        file_name="large.png",
        file_type="image/png",
        file_size_bytes=large_image.stat().st_size,
        storage_path=str(large_image),
        subject_id="2025-01-24",
    )
    db_session.add(attachment)
    db_session.flush()

    # Generate report - should succeed but skip base64 encoding
    report_path = tmp_path / "large_image_grid.html"
    result_path = generate_image_grid_report(
        db_session,
        attachment_ids=[attachment.id],
        output_path=report_path,
    )

    assert result_path.exists()
    html_content = report_path.read_text(encoding="utf-8")
    # Should still include the image info but without base64 data
    assert "large.png" in html_content
    assert "2025-01-24" in html_content
    # Should show "Image not available" for large images
    assert "Image not available" in html_content or "no-image" in html_content


def test_generate_image_grid_report_handles_missing_images(db_session: Session, tmp_path: Path, temp_config):
    """Test that image grid report handles missing image files gracefully."""
    email = InputEmail(
        email_hash="missing_image_test",
        subject_id="2025-01-25",
        subject="Missing Image Test",
        sender="missing@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create attachment pointing to non-existent file
    attachment = Attachment(
        input_email=email,
        file_name="missing.png",
        file_type="image/png",
        file_size_bytes=0,
        storage_path=str(tmp_path / "does_not_exist.png"),
        subject_id="2025-01-25",
    )
    db_session.add(attachment)
    db_session.flush()

    # Generate report - should still create HTML but show "Image not available"
    report_path = tmp_path / "missing_image_grid.html"
    result_path = generate_image_grid_report(
        db_session,
        attachment_ids=[attachment.id],
        output_path=report_path,
    )

    assert result_path.exists()
    html_content = report_path.read_text(encoding="utf-8")
    assert "missing.png" in html_content
    assert "2025-01-25" in html_content
    assert "Image not available" in html_content


def test_generate_image_grid_report_validates_input(db_session: Session, tmp_path: Path, temp_config):
    """Test that generate_image_grid_report validates input properly."""
    # Test with empty attachment_ids
    with pytest.raises(ValueError, match="No attachment IDs provided"):
        generate_image_grid_report(
            db_session,
            attachment_ids=[],
            output_path=tmp_path / "empty.html",
        )

    # Test with non-existent attachment IDs
    with pytest.raises(ValueError, match="No attachments found"):
        generate_image_grid_report(
            db_session,
            attachment_ids=[99999],
            output_path=tmp_path / "nonexistent.html",
        )
    
    # Test with non-image attachment
    email = InputEmail(
        email_hash="non_image_test",
        subject_id="2025-01-26",
        subject="Non-Image Test",
        sender="nonimage@example.com",
    )
    db_session.add(email)
    db_session.flush()
    
    test_file = tmp_path / "document.pdf"
    test_file.write_bytes(b"pdf content")
    
    attachment = Attachment(
        input_email=email,
        file_name="document.pdf",
        file_type="application/pdf",
        file_size_bytes=len(test_file.read_bytes()),
        storage_path=str(test_file),
        subject_id="2025-01-26",
    )
    db_session.add(attachment)
    db_session.flush()
    
    # Should raise error because it's not an image
    with pytest.raises(ValueError, match="No image attachments found"):
        generate_image_grid_report(
            db_session,
            attachment_ids=[attachment.id],
            output_path=tmp_path / "non_image.html",
        )


def test_export_attachments_handles_empty_input(db_session: Session, tmp_path: Path, temp_config):
    """Test that export_attachments handles empty input gracefully."""
    results, archive_path = export_attachments(
        db_session,
        attachment_ids=[],
        destination_root=tmp_path / "empty_export",
        create_archive=True,
    )

    assert results == []
    assert archive_path is None

