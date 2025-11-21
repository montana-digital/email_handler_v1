"""Tests for takedown bundle generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models import Attachment, InputEmail
from app.services.takedown_bundle import (
    _copy_image_with_subjectid_naming,
    _get_takedown_csv_fields,
    _is_image_attachment,
    generate_takedown_bundle,
)


def test_get_takedown_csv_fields_excludes_sensitive_data(db_session: Session):
    """Test that CSV fields exclude email_hash, image_base64, and body_html but include subject_id."""
    email = InputEmail(
        email_hash="test_hash_123",
        subject_id="2025-01-15",
        subject="Test Email",
        sender="test@example.com",
        url_parsed='["example.com"]',
        callback_number_parsed='["+18881111111"]',
        body_html="<p>Test HTML content</p>",
    )
    db_session.add(email)
    db_session.flush()

    fields = _get_takedown_csv_fields(email)

    # Must include subject_id
    assert "subject_id" in fields
    assert fields["subject_id"] == "2025-01-15"

    # Must exclude email_hash, image_base64, and body_html
    assert "email_hash" not in fields
    assert "image_base64" not in fields
    assert "body_html" not in fields

    # Should include other fields
    assert "id" in fields
    assert "subject" in fields
    assert "sender" in fields
    assert "urls_parsed" in fields
    assert "callback_numbers_parsed" in fields


def test_get_takedown_csv_fields_includes_all_other_fields(db_session: Session):
    """Test that all other fields are included in CSV (excluding body_html)."""
    email = InputEmail(
        email_hash="test_hash_456",
        subject_id="2025-01-16",
        subject="Complete Test Email",
        sender="sender@example.com",
        cc='["cc1@example.com", "cc2@example.com"]',
        date_sent=datetime(2025, 1, 16, 12, 30, 0),
        date_reported=datetime(2025, 1, 16, 14, 0, 0),
        url_raw='["https://example.com"]',
        url_parsed='["example.com"]',
        callback_number_raw='["888-111-1111"]',
        callback_number_parsed='["+18881111111"]',
        sending_source_raw="https://source.example.com",
        sending_source_parsed='["source.example.com"]',
        additional_contacts="contact@example.com",
        model_confidence=0.95,
        message_id="<msg123@example.com>",
        body_html="<p>Test HTML</p>",
    )
    db_session.add(email)
    db_session.flush()

    fields = _get_takedown_csv_fields(email)

    # Check all expected fields are present (excluding body_html)
    expected_fields = [
        "id", "subject_id", "parse_status", "parse_error",
        "subject", "sender", "cc", "date_sent", "date_reported",
        "urls_raw", "urls_parsed", "callback_numbers_raw", "callback_numbers_parsed",
        "sending_source_raw", "sending_source_parsed",
        "additional_contacts", "model_confidence", "message_id",
    ]
    for field in expected_fields:
        assert field in fields, f"Field '{field}' missing from CSV fields"
    
    # Verify body_html is excluded
    assert "body_html" not in fields, "body_html should be excluded from CSV"

    # Verify values
    assert fields["subject_id"] == "2025-01-16"
    assert fields["subject"] == "Complete Test Email"
    assert fields["cc"] == "cc1@example.com, cc2@example.com"
    assert "example.com" in fields["urls_parsed"]
    assert "+18881111111" in fields["callback_numbers_parsed"]


def test_is_image_attachment_detects_images():
    """Test that image detection works correctly."""
    # Create mock attachment objects
    class MockAttachment:
        def __init__(self, file_type, file_name):
            self.file_type = file_type
            self.file_name = file_name

    # Test MIME type detection
    assert _is_image_attachment(MockAttachment("image/png", "test.png"))
    assert _is_image_attachment(MockAttachment("image/jpeg", "test.jpg"))
    assert _is_image_attachment(MockAttachment("image/gif", "test.gif"))
    assert not _is_image_attachment(MockAttachment("application/pdf", "test.pdf"))
    assert not _is_image_attachment(MockAttachment("text/plain", "test.txt"))

    # Test file extension detection
    assert _is_image_attachment(MockAttachment("", "test.png"))
    assert _is_image_attachment(MockAttachment("", "test.jpg"))
    assert _is_image_attachment(MockAttachment("", "test.jpeg"))
    assert _is_image_attachment(MockAttachment("", "test.gif"))
    assert _is_image_attachment(MockAttachment("", "test.bmp"))
    assert _is_image_attachment(MockAttachment("", "test.tiff"))
    assert _is_image_attachment(MockAttachment("", "test.svg"))
    assert _is_image_attachment(MockAttachment("", "test.webp"))
    assert not _is_image_attachment(MockAttachment("", "test.pdf"))
    assert not _is_image_attachment(MockAttachment("", "test.doc"))


def test_copy_image_with_subjectid_naming(db_session: Session, tmp_path: Path):
    """Test that images are copied with correct SubjectID-based naming."""
    email = InputEmail(
        email_hash="test_hash_naming",
        subject_id="2025-01-20",
        subject="Naming Test",
        sender="naming@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create test image
    source_image = tmp_path / "original_image.png"
    source_image.write_bytes(b"fake png data")

    attachment = Attachment(
        input_email=email,
        file_name="original_image.png",
        file_type="image/png",
        file_size_bytes=len(source_image.read_bytes()),
        storage_path=str(source_image),
        subject_id="2025-01-20",
    )
    db_session.add(attachment)
    db_session.flush()

    # Copy image
    destination_dir = tmp_path / "images"
    destination_dir.mkdir()

    result_path = _copy_image_with_subjectid_naming(
        attachment,
        destination_dir,
        "2025-01-20",
        1,
    )

    assert result_path is not None
    assert result_path.exists()
    assert result_path.name == "2025-01-20_images_1.png"
    assert result_path.read_bytes() == source_image.read_bytes()


def test_copy_image_with_subjectid_naming_multiple_images(db_session: Session, tmp_path: Path):
    """Test that multiple images from same email get iterating index."""
    email = InputEmail(
        email_hash="test_hash_multi",
        subject_id="2025-01-21",
        subject="Multi Image Test",
        sender="multi@example.com",
    )
    db_session.add(email)
    db_session.flush()

    destination_dir = tmp_path / "images"
    destination_dir.mkdir()

    # Create multiple images
    images = []
    for i in range(3):
        source_image = tmp_path / f"image_{i}.png"
        source_image.write_bytes(f"fake png data {i}".encode())

        attachment = Attachment(
            input_email=email,
            file_name=f"image_{i}.png",
            file_type="image/png",
            file_size_bytes=len(source_image.read_bytes()),
            storage_path=str(source_image),
            subject_id="2025-01-21",
        )
        db_session.add(attachment)
        db_session.flush()
        images.append(attachment)

    # Copy all images with iterating index
    copied_paths = []
    for index, attachment in enumerate(images, start=1):
        result_path = _copy_image_with_subjectid_naming(
            attachment,
            destination_dir,
            "2025-01-21",
            index,
        )
        copied_paths.append(result_path)

    # Verify all images were copied with correct naming
    assert len(copied_paths) == 3
    assert copied_paths[0].name == "2025-01-21_images_1.png"
    assert copied_paths[1].name == "2025-01-21_images_2.png"
    assert copied_paths[2].name == "2025-01-21_images_3.png"

    # Verify all files exist
    for path in copied_paths:
        assert path.exists()


def test_generate_takedown_bundle_creates_structure(db_session: Session, tmp_path: Path, temp_config):
    """Test that takedown bundle creates correct directory structure."""
    # Create email with images
    email = InputEmail(
        email_hash="bundle_test_hash",
        subject_id="2025-01-22",
        subject="Bundle Test Email",
        sender="bundle@example.com",
        url_parsed='["bundle.example.com"]',
    )
    db_session.add(email)
    db_session.flush()

    # Create test images
    image1 = tmp_path / "test_image1.png"
    image1.write_bytes(b"png data 1")
    image2 = tmp_path / "test_image2.jpg"
    image2.write_bytes(b"jpg data 2")

    attachment1 = Attachment(
        input_email=email,
        file_name="test_image1.png",
        file_type="image/png",
        file_size_bytes=len(image1.read_bytes()),
        storage_path=str(image1),
        subject_id="2025-01-22",
    )
    attachment2 = Attachment(
        input_email=email,
        file_name="test_image2.jpg",
        file_type="image/jpeg",
        file_size_bytes=len(image2.read_bytes()),
        storage_path=str(image2),
        subject_id="2025-01-22",
    )
    db_session.add_all([attachment1, attachment2])
    db_session.flush()

    # Generate bundle
    result = generate_takedown_bundle(
        db_session,
        email_ids=[email.id],
        config=temp_config,
    )

    assert result is not None
    assert result.bundle_dir.exists()
    assert result.bundle_dir.name.startswith("takedown_")
    assert result.csv_path.exists()
    assert result.csv_path.name == "takedown_data.csv"
    assert result.images_dir.exists()
    assert result.images_dir.name == "images"
    assert result.email_count == 1
    assert result.image_count == 2
    assert result.skipped_images == 0

    # Verify CSV structure
    import csv
    with result.csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert "subject_id" in rows[0]
        assert rows[0]["subject_id"] == "2025-01-22"
        assert "email_hash" not in rows[0]
        assert "image_base64" not in rows[0]

    # Verify images were copied with correct naming
    image_files = list(result.images_dir.glob("*"))
    assert len(image_files) == 2
    image_names = [f.name for f in image_files]
    assert "2025-01-22_images_1.png" in image_names
    assert "2025-01-22_images_2.jpg" in image_names


def test_generate_takedown_bundle_handles_missing_images(db_session: Session, tmp_path: Path, temp_config):
    """Test that bundle generation handles missing image files gracefully."""
    email = InputEmail(
        email_hash="missing_image_test",
        subject_id="2025-01-23",
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
        subject_id="2025-01-23",
    )
    db_session.add(attachment)
    db_session.flush()

    # Generate bundle - should succeed but skip missing image
    result = generate_takedown_bundle(
        db_session,
        email_ids=[email.id],
        config=temp_config,
    )

    assert result is not None
    assert result.email_count == 1
    assert result.image_count == 0
    assert result.skipped_images == 1
    assert result.csv_path.exists()  # CSV should still be created


def test_generate_takedown_bundle_multiple_emails(db_session: Session, tmp_path: Path, temp_config):
    """Test bundle generation with multiple emails and images."""
    # Create two emails with different SubjectIDs
    email1 = InputEmail(
        email_hash="multi_test_1",
        subject_id="2025-01-24",
        subject="Email 1",
        sender="email1@example.com",
    )
    email2 = InputEmail(
        email_hash="multi_test_2",
        subject_id="2025-01-25",
        subject="Email 2",
        sender="email2@example.com",
    )
    db_session.add_all([email1, email2])
    db_session.flush()

    # Create images for each email
    image1 = tmp_path / "img1.png"
    image1.write_bytes(b"img1")
    image2a = tmp_path / "img2a.png"
    image2a.write_bytes(b"img2a")
    image2b = tmp_path / "img2b.jpg"
    image2b.write_bytes(b"img2b")

    att1 = Attachment(
        input_email=email1,
        file_name="img1.png",
        file_type="image/png",
        file_size_bytes=4,
        storage_path=str(image1),
        subject_id="2025-01-24",
    )
    att2a = Attachment(
        input_email=email2,
        file_name="img2a.png",
        file_type="image/png",
        file_size_bytes=5,
        storage_path=str(image2a),
        subject_id="2025-01-25",
    )
    att2b = Attachment(
        input_email=email2,
        file_name="img2b.jpg",
        file_type="image/jpeg",
        file_size_bytes=5,
        storage_path=str(image2b),
        subject_id="2025-01-25",
    )
    db_session.add_all([att1, att2a, att2b])
    db_session.flush()

    # Generate bundle
    result = generate_takedown_bundle(
        db_session,
        email_ids=[email1.id, email2.id],
        config=temp_config,
    )

    assert result is not None
    assert result.email_count == 2
    assert result.image_count == 3
    assert result.skipped_images == 0

    # Verify CSV has 2 rows
    import csv
    with result.csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 2
        subject_ids = [row["subject_id"] for row in rows]
        assert "2025-01-24" in subject_ids
        assert "2025-01-25" in subject_ids

    # Verify images are correctly named
    image_files = list(result.images_dir.glob("*"))
    assert len(image_files) == 3
    image_names = [f.name for f in image_files]
    # Email 1: one image
    assert "2025-01-24_images_1.png" in image_names
    # Email 2: two images with iterating index
    assert "2025-01-25_images_1.png" in image_names
    assert "2025-01-25_images_2.jpg" in image_names


def test_generate_takedown_bundle_handles_no_subject_id(db_session: Session, tmp_path: Path, temp_config):
    """Test that bundle handles emails without subject_id (uses hash prefix)."""
    email = InputEmail(
        email_hash="no_subject_id_test_hash_12345",
        subject_id=None,  # No subject_id
        subject="No SubjectID Test",
        sender="nosubject@example.com",
    )
    db_session.add(email)
    db_session.flush()

    image = tmp_path / "test.png"
    image.write_bytes(b"test data")

    attachment = Attachment(
        input_email=email,
        file_name="test.png",
        file_type="image/png",
        file_size_bytes=9,
        storage_path=str(image),
        subject_id=None,
    )
    db_session.add(attachment)
    db_session.flush()

    # Generate bundle
    result = generate_takedown_bundle(
        db_session,
        email_ids=[email.id],
        config=temp_config,
    )

    assert result is not None
    assert result.email_count == 1
    # Should use hash prefix for image naming (truncated to 16 chars)
    image_files = list(result.images_dir.glob("*"))
    if image_files:
        # Image should be named with hash prefix (first 16 chars of hash)
        assert image_files[0].name.startswith("no_subject_id_te")  # First 16 chars of hash


def test_generate_takedown_bundle_empty_input(db_session: Session, temp_config):
    """Test that bundle generation handles empty input gracefully."""
    result = generate_takedown_bundle(
        db_session,
        email_ids=[],
        config=temp_config,
    )

    assert result is None


def test_generate_takedown_bundle_invalid_email_ids(db_session: Session, temp_config):
    """Test that bundle generation handles invalid email IDs."""
    result = generate_takedown_bundle(
        db_session,
        email_ids=[99999, 99998],
        config=temp_config,
    )

    assert result is None


def test_generate_takedown_bundle_csv_association(db_session: Session, tmp_path: Path, temp_config):
    """Test that CSV SubjectID can be used to associate with images."""
    email = InputEmail(
        email_hash="association_test",
        subject_id="2025-01-26",
        subject="Association Test",
        sender="assoc@example.com",
    )
    db_session.add(email)
    db_session.flush()

    # Create multiple images
    for i in range(2):
        img = tmp_path / f"img_{i}.png"
        img.write_bytes(f"data{i}".encode())
        attachment = Attachment(
            input_email=email,
            file_name=f"img_{i}.png",
            file_type="image/png",
            file_size_bytes=len(img.read_bytes()),
            storage_path=str(img),
            subject_id="2025-01-26",
        )
        db_session.add(attachment)
    db_session.flush()

    # Generate bundle
    result = generate_takedown_bundle(
        db_session,
        email_ids=[email.id],
        config=temp_config,
    )

    assert result is not None

    # Verify association: CSV SubjectID matches image filename prefix
    import csv
    with result.csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        csv_subject_id = rows[0]["subject_id"]

    # All images should start with this SubjectID
    image_files = list(result.images_dir.glob("*"))
    for img_file in image_files:
        assert img_file.name.startswith(f"{csv_subject_id}_images_")
        # Verify format: {subjectID}_images_{index}.{ext}
        parts = img_file.stem.split("_images_")
        assert len(parts) == 2
        assert parts[0] == csv_subject_id
        assert parts[1].isdigit()  # Index should be numeric

