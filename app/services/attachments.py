"""Attachment extraction and packaging services."""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Attachment, InputEmail, PickleBatch

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".svg"}
EMAIL_EXTENSIONS = {".eml", ".msg"}


class AttachmentCategory(str, Enum):
    IMAGES = "images"
    EMAILS = "emails"
    OTHER = "other"


@dataclass(slots=True)
class AttachmentExportResult:
    attachment_id: int
    source_path: Path
    destination_path: Path
    category: AttachmentCategory


def detect_category(attachment: Attachment) -> AttachmentCategory:
    suffix = Path(attachment.file_name or "").suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return AttachmentCategory.IMAGES
    if suffix in EMAIL_EXTENSIONS:
        return AttachmentCategory.EMAILS
    return AttachmentCategory.OTHER


def build_destination_name(attachment: Attachment) -> str:
    base_name = attachment.file_name or f"attachment_{attachment.id}"
    prefix = attachment.subject_id
    if not prefix and attachment.input_email:
        prefix = attachment.input_email.subject_id or attachment.input_email.email_hash
    if prefix:
        return f"{prefix}_{base_name}"
    return base_name


def export_attachments(
    session: Session,
    attachment_ids: Sequence[int],
    destination_root: Path,
    *,
    create_archive: bool = True,
) -> tuple[List[AttachmentExportResult], Path | None]:
    """Copy attachments into organized folders and optionally create a zip archive."""
    if not attachment_ids:
        return [], None

    destination_root.mkdir(parents=True, exist_ok=True)

    attachments = session.query(Attachment).filter(Attachment.id.in_(attachment_ids)).all()
    results: List[AttachmentExportResult] = []

    for attachment in attachments:
        if not attachment.storage_path:
            logger.warning("Attachment %s is missing a storage_path; skipping", attachment.id)
            continue

        source_path = Path(attachment.storage_path)
        if not source_path.exists():
            logger.warning("Attachment source %s does not exist; skipping", source_path)
            continue

        category = detect_category(attachment)
        category_dir = destination_root / category.value
        category_dir.mkdir(parents=True, exist_ok=True)

        destination_name = build_destination_name(attachment)
        destination_path = category_dir / destination_name

        shutil.copy2(source_path, destination_path)
        results.append(
            AttachmentExportResult(
                attachment_id=attachment.id,
                source_path=source_path,
                destination_path=destination_path,
                category=category,
            )
        )

    archive_path: Path | None = None
    if create_archive and results:
        archive_path = destination_root.with_suffix(".zip")
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for result in results:
                archive.write(
                    result.destination_path,
                    arcname=result.destination_path.relative_to(destination_root),
                )

    return results, archive_path


def list_attachment_records(
    session: Session,
    *,
    batch_id: Optional[int] = None,
    category: Optional[AttachmentCategory] = None,
) -> List[Dict]:
    stmt = (
        select(Attachment, InputEmail, PickleBatch)
        .join(InputEmail, Attachment.input_email_id == InputEmail.id)
        .join(PickleBatch, InputEmail.pickle_batch_id == PickleBatch.id, isouter=True)
        .order_by(Attachment.created_at.desc())
    )

    if batch_id is not None:
        stmt = stmt.where(InputEmail.pickle_batch_id == batch_id)

    attachments: List[Dict] = []
    for attachment, email, batch in session.execute(stmt):
        detected = detect_category(attachment)
        if category and detected != category:
            continue
        attachments.append(
            {
                "id": attachment.id,
                "file_name": attachment.file_name,
                "file_type": attachment.file_type,
                "file_size": attachment.file_size_bytes,
                "subject_id": attachment.subject_id or email.subject_id,
                "email_subject": email.subject,
                "email_sender": email.sender,
                "batch_name": batch.batch_name if batch else None,
                "category": detected.value,
                "storage_path": attachment.storage_path,
                "email_id": email.id,
                "batch_id": batch.id if batch else None,
            }
        )

    return attachments


def cleanup_exports(export_results: Iterable[AttachmentExportResult]) -> None:
    for result in export_results:
        try:
            if result.destination_path.exists():
                result.destination_path.unlink()
        except OSError as exc:
            logger.warning("Failed to remove %s: %s", result.destination_path, exc)


def generate_image_grid_report(
    session: Session,
    attachment_ids: Sequence[int],
    output_path: Path,
) -> Path:
    """Generate an HTML report with images in a grid layout, including numbers and URL information.
    
    Returns the path to the generated HTML file.
    """
    from app.db.models import Attachment, InputEmail
    import base64
    
    attachments = session.query(Attachment).filter(Attachment.id.in_(attachment_ids)).all()
    
    # Filter to only images
    image_attachments = [att for att in attachments if detect_category(att) == AttachmentCategory.IMAGES]
    
    if not image_attachments:
        raise ValueError("No image attachments found in selection")
    
    # Get related email information for each attachment
    image_data = []
    for idx, attachment in enumerate(image_attachments, 1):
        email = attachment.input_email if attachment.input_email_id else None
        
        # Get URLs from email
        urls = []
        if email:
            import json
            try:
                url_parsed = json.loads(email.url_parsed or "[]")
                urls = url_parsed if isinstance(url_parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Read image and convert to base64 for embedding
        image_base64 = None
        if attachment.storage_path:
            image_path = Path(attachment.storage_path)
            if image_path.exists():
                try:
                    image_bytes = image_path.read_bytes()
                    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                    # Determine MIME type from extension
                    suffix = image_path.suffix.lower()
                    mime_type = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".bmp": "image/bmp",
                        ".tiff": "image/tiff",
                        ".svg": "image/svg+xml",
                    }.get(suffix, "image/png")
                except Exception as e:
                    logger.warning("Failed to read image %s: %s", image_path, e)
        
        image_data.append({
            "number": idx,
            "attachment_id": attachment.id,
            "file_name": attachment.file_name or f"image_{attachment.id}",
            "subject_id": attachment.subject_id or (email.subject_id if email else None),
            "urls": urls,
            "email_subject": email.subject if email else None,
            "email_sender": email.sender if email else None,
            "image_base64": image_base64,
            "mime_type": mime_type if image_base64 else None,
        })
    
    # Generate HTML with grid layout
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Image Grid Report - {len(image_data)} Images</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            margin: 0 0 10px 0;
            color: #333;
        }}
        .header p {{
            margin: 5px 0;
            color: #666;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .image-card {{
            background: white;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .image-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }}
        .image-number {{
            font-size: 18px;
            font-weight: bold;
            color: #2563eb;
            margin-bottom: 10px;
        }}
        .image-container {{
            width: 100%;
            margin-bottom: 10px;
            text-align: center;
        }}
        .image-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .image-info {{
            font-size: 12px;
            color: #666;
            margin-top: 10px;
        }}
        .image-info strong {{
            color: #333;
        }}
        .urls {{
            margin-top: 8px;
        }}
        .urls a {{
            display: block;
            color: #2563eb;
            text-decoration: none;
            font-size: 11px;
            word-break: break-all;
            margin-top: 4px;
        }}
        .urls a:hover {{
            text-decoration: underline;
        }}
        .no-image {{
            text-align: center;
            padding: 40px;
            color: #999;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Image Grid Report</h1>
        <p><strong>Total Images:</strong> {len(image_data)}</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div class="grid">
"""
    
    for img in image_data:
        html_content += f"""        <div class="image-card">
            <div class="image-number">Image #{img['number']}</div>
            <div class="image-container">
"""
        
        if img['image_base64']:
            html_content += f"""                <img src="data:{img['mime_type']};base64,{img['image_base64']}" alt="{img['file_name']}">
"""
        else:
            html_content += f"""                <div class="no-image">Image not available</div>
"""
        
        html_content += f"""            </div>
            <div class="image-info">
                <div><strong>File:</strong> {img['file_name']}</div>
"""
        
        if img['subject_id']:
            html_content += f"""                <div><strong>Subject ID:</strong> {img['subject_id']}</div>
"""
        
        if img['email_subject']:
            html_content += f"""                <div><strong>Email Subject:</strong> {img['email_subject']}</div>
"""
        
        if img['email_sender']:
            html_content += f"""                <div><strong>Sender:</strong> {img['email_sender']}</div>
"""
        
        if img['urls']:
            html_content += f"""                <div class="urls">
                    <strong>Related URLs:</strong>
"""
            for url in img['urls'][:5]:  # Limit to 5 URLs per image
                html_content += f"""                    <a href="{url}" target="_blank">{url}</a>
"""
            if len(img['urls']) > 5:
                html_content += f"""                    <div style="font-size: 10px; color: #999; margin-top: 4px;">... and {len(img['urls']) - 5} more</div>
"""
            html_content += """                </div>
"""
        
        html_content += """            </div>
        </div>
"""
    
    html_content += """    </div>
</body>
</html>
"""
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    return output_path
