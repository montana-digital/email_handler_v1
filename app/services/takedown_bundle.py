"""Service for generating takedown bundles with CSV and associated images."""

from __future__ import annotations

import csv
import io
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from loguru import logger
from sqlalchemy.orm import Session, joinedload

from app.config import AppConfig
from app.db.models import Attachment, InputEmail, KnowledgeTableMetadata
from app.utils.file_operations import copy_file_safe, write_text_safe


@dataclass
class TakedownBundleResult:
    """Result of takedown bundle generation."""
    
    bundle_dir: Path
    csv_path: Path
    images_dir: Path
    email_count: int
    image_count: int
    skipped_images: int


def _get_takedown_csv_fields(email: InputEmail, knowledge_columns: List[str] = None) -> dict:
    """Extract fields for CSV export, excluding email_hash, image_base64, and body_html.
    
    Includes knowledge columns from email.knowledge_data if provided.
    
    Args:
        email: InputEmail record
        knowledge_columns: List of knowledge column names to include
        
    Returns:
        Dictionary of field names and values for CSV export
    """
    from app.utils.json_helpers import safe_json_loads_list as _loads
    
    fields = {
        "id": email.id,
        "subject_id": email.subject_id or "",
        "parse_status": email.parse_status or "",
        "parse_error": email.parse_error or "",
        "subject": email.subject or "",
        "sender": email.sender or "",
        "cc": ", ".join(_loads(email.cc)) if email.cc else "",
        "date_sent": email.date_sent.isoformat() if email.date_sent else "",
        "date_reported": email.date_reported.isoformat() if email.date_reported else "",
        "urls_raw": ", ".join(_loads(email.url_raw)) if email.url_raw else "",
        "urls_parsed": ", ".join(_loads(email.url_parsed)) if email.url_parsed else "",
        "callback_numbers_raw": ", ".join(_loads(email.callback_number_raw)) if email.callback_number_raw else "",
        "callback_numbers_parsed": ", ".join(_loads(email.callback_number_parsed)) if email.callback_number_parsed else "",
        "sending_source_raw": email.sending_source_raw or "",
        "sending_source_parsed": ", ".join(_loads(email.sending_source_parsed)) if email.sending_source_parsed else "",
        "additional_contacts": email.additional_contacts or "",
        "model_confidence": email.model_confidence if email.model_confidence is not None else "",
        "message_id": email.message_id or "",
        # Note: email_hash, image_base64, and body_html are explicitly excluded
    }
    
    # Add knowledge columns if provided
    if knowledge_columns:
        knowledge_data = email.knowledge_data or {}
        if not isinstance(knowledge_data, dict):
            logger.warning("Invalid knowledge_data type for email %d: %s", email.id, type(knowledge_data))
            knowledge_data = {}
        
        for col in knowledge_columns:
            try:
                value = knowledge_data.get(col, "")
                # Ensure value is serializable for CSV
                if value is None:
                    fields[col] = ""
                else:
                    fields[col] = str(value)
            except Exception as exc:
                logger.warning("Error accessing knowledge column %s for email %d: %s", col, email.id, exc)
                fields[col] = ""
    
    return fields


def _is_image_attachment(attachment: Attachment) -> bool:
    """Check if attachment is an image."""
    file_type = (attachment.file_type or "").lower()
    file_name = (attachment.file_name or "").lower()
    
    # Check MIME type
    if file_type.startswith("image/"):
        return True
    
    # Check file extension
    image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".svg", ".webp"}
    return any(file_name.endswith(ext) for ext in image_extensions)


def _copy_image_with_subjectid_naming(
    attachment: Attachment,
    destination_dir: Path,
    subject_id: str,
    image_index: int,
) -> Optional[Path]:
    """Copy image attachment to destination with SubjectID-based naming.
    
    Format: {subjectID}_images_{index}.{extension}
    
    Args:
        attachment: Attachment record
        destination_dir: Directory to copy image to
        subject_id: SubjectID to use in filename
        image_index: Iterating value for multiple images per email
    
    Returns:
        Path to copied file, or None if copy failed
    """
    if not attachment.storage_path:
        logger.warning("Attachment %d has no storage_path", attachment.id)
        return None
    
    source_path = Path(attachment.storage_path)
    if not source_path.exists():
        logger.warning("Image file not found: %s", source_path)
        return None
    
    # Get file extension from original filename or storage path
    original_ext = Path(attachment.file_name or source_path.name).suffix
    if not original_ext:
        # Try to infer from MIME type
        mime_to_ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/bmp": ".bmp",
            "image/tiff": ".tiff",
            "image/svg+xml": ".svg",
            "image/webp": ".webp",
        }
        original_ext = mime_to_ext.get((attachment.file_type or "").lower(), ".png")
    
    # Build destination filename: {subjectID}_images_{index}.{ext}
    dest_filename = f"{subject_id}_images_{image_index}{original_ext}"
    dest_path = destination_dir / dest_filename
    
    try:
        # Handle filename conflicts (shouldn't happen with index, but just in case)
        counter = 1
        while dest_path.exists():
            stem = dest_path.stem
            dest_path = destination_dir / f"{stem}_{counter}{original_ext}"
            counter += 1
        
        copy_file_safe(source_path, dest_path, create_parents=True)
        logger.debug("Copied image: %s -> %s", source_path, dest_path)
        return dest_path
    except Exception as exc:
        logger.error("Failed to copy image %s: %s", source_path, exc)
        return None


def generate_takedown_bundle(
    session: Session,
    email_ids: Sequence[int],
    config: AppConfig,
) -> Optional[TakedownBundleResult]:
    """Generate a takedown bundle with CSV and associated images.
    
    Creates:
    - Directory: output/takedown_<timestamp>/
    - CSV file: takedown_data.csv (all fields except email_hash and image_base64)
    - Images folder: images/ with files named {subjectID}_images_{index}.{ext}
    
    Args:
        session: Database session
        email_ids: List of email IDs to include in bundle
        config: Application configuration
    
    Returns:
        TakedownBundleResult with paths and counts, or None if generation failed
    """
    if not email_ids:
        logger.warning("No email IDs provided for takedown bundle")
        return None
    
    # Create bundle directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    bundle_dir = config.output_dir / f"takedown_{timestamp}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    
    images_dir = bundle_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    
    # Load emails with attachments eagerly loaded
    emails = (
        session.query(InputEmail)
        .filter(InputEmail.id.in_(email_ids))
        .options(joinedload(InputEmail.attachments))
        .all()
    )
    
    if not emails:
        logger.warning("No emails found for provided IDs")
        return None
    
    # Get knowledge columns from metadata
    knowledge_columns = []
    try:
        tn_metadata = (
            session.query(KnowledgeTableMetadata)
            .filter(KnowledgeTableMetadata.table_name == "Knowledge_TNs")
            .first()
        )
        domain_metadata = (
            session.query(KnowledgeTableMetadata)
            .filter(KnowledgeTableMetadata.table_name == "Knowledge_Domains")
            .first()
        )
        
        if tn_metadata and tn_metadata.selected_columns:
            knowledge_columns.extend(tn_metadata.selected_columns)
        if domain_metadata and domain_metadata.selected_columns:
            knowledge_columns.extend(domain_metadata.selected_columns)
        
        # Remove duplicates while preserving order
        knowledge_columns = list(dict.fromkeys(knowledge_columns))
    except Exception as exc:
        logger.warning("Failed to fetch knowledge columns: %s", exc)
        knowledge_columns = []
    
    # Generate CSV
    csv_path = bundle_dir / "takedown_data.csv"
    
    try:
        # Get all field names from first email (all should have same structure)
        field_names = list(_get_takedown_csv_fields(emails[0], knowledge_columns).keys())
        
        # Build CSV content in memory, then write atomically
        with io.StringIO() as buffer:
            writer = csv.DictWriter(buffer, fieldnames=field_names)
            writer.writeheader()
            
            image_count = 0
            skipped_images = 0
            
            for email in emails:
                # Write CSV row (excluding email_hash and image_base64)
                row_data = _get_takedown_csv_fields(email, knowledge_columns)
                writer.writerow(row_data)
                
                # Copy associated images
                subject_id = email.subject_id
                if not subject_id:
                    # Fallback to email_hash if no subject_id
                    subject_id = email.email_hash[:16]  # Use first 16 chars
                    logger.warning("Email %d has no subject_id, using hash prefix: %s", email.id, subject_id)
                
                # Get image attachments for this email
                image_attachments = [
                    att for att in (email.attachments or [])
                    if _is_image_attachment(att)
                ]
                
                # Copy images with iterating index
                for index, image_att in enumerate(image_attachments, start=1):
                    copied_path = _copy_image_with_subjectid_naming(
                        image_att,
                        images_dir,
                        subject_id,
                        index,
                    )
                    if copied_path:
                        image_count += 1
                    else:
                        skipped_images += 1
            
            # Get CSV content from buffer and write atomically
            csv_content = buffer.getvalue()
        
        write_text_safe(csv_path, csv_content, encoding="utf-8", atomic=True)
        
        logger.info(
            "Generated takedown bundle: %s emails, %d images, %d skipped",
            len(emails),
            image_count,
            skipped_images,
        )
        
        return TakedownBundleResult(
            bundle_dir=bundle_dir,
            csv_path=csv_path,
            images_dir=images_dir,
            email_count=len(emails),
            image_count=image_count,
            skipped_images=skipped_images,
        )
    
    except Exception as exc:
        logger.exception("Failed to generate takedown bundle: %s", exc)
        # Clean up on failure
        try:
            shutil.rmtree(bundle_dir)
        except Exception:
            pass
        return None

