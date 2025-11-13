"""Services for generating HTML reports for selected emails."""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable, Optional, Sequence

from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import InputEmail


def _ensure_reports_dir(config: AppConfig) -> Path:
    reports_dir = config.output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def _format_datetime(value: Optional[datetime]) -> str:
    if not value:
        return "N/A"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _render_email_section(email: InputEmail) -> str:
    attachments = email.attachments or []
    attachments_html = ""
    if attachments:
        rows = []
        for attachment in attachments:
            rows.append(
                f"<tr><td>{escape(attachment.file_name or '')}</td>"
                f"<td>{escape(attachment.file_type or '')}</td>"
                f"<td>{attachment.file_size_bytes or 0}</td>"
                f"<td>{escape(attachment.storage_path or '')}</td></tr>"
            )
        attachments_html = (
            "<h4>Attachments</h4>"
            "<table><thead><tr>"
            "<th>File Name</th><th>Type</th><th>Size (bytes)</th><th>Storage Path</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )
    else:
        attachments_html = "<p><em>No attachments.</em></p>"

    urls = []
    if email.url_parsed:
        try:
            urls = json.loads(email.url_parsed)
        except json.JSONDecodeError:
            urls = []

    callback_numbers = []
    if email.callback_number_parsed:
        try:
            callback_numbers = json.loads(email.callback_number_parsed)
        except json.JSONDecodeError:
            callback_numbers = []

    return f"""
    <section>
        <h3>{escape(email.subject or 'Untitled')}</h3>
        <p><strong>Sender:</strong> {escape(email.sender or 'N/A')}</p>
        <p><strong>Date Sent:</strong> {_format_datetime(email.date_sent)}</p>
        <p><strong>Date Reported:</strong> {_format_datetime(email.date_reported)}</p>
        <p><strong>Subject ID:</strong> {escape(email.subject_id or 'N/A')}</p>
        <p><strong>URLs:</strong> {escape(', '.join(urls) or 'N/A')}</p>
        <p><strong>Callback Numbers:</strong> {escape(', '.join(callback_numbers) or 'N/A')}</p>
        <p><strong>Model Confidence:</strong> {email.model_confidence if email.model_confidence is not None else 'N/A'}</p>
        <p><strong>Additional Contacts:</strong> {escape(email.additional_contacts or 'N/A')}</p>
        <p><strong>Message ID:</strong> {escape(email.message_id or 'N/A')}</p>
        <h4>Body Preview</h4>
        <div style="border:1px solid #ccc;padding:10px;margin-bottom:10px;white-space:pre-wrap;">
            {escape((email.body_html or '')[:2000])}
        </div>
        {attachments_html}
    </section>
    <hr/>
    """


def generate_email_report(
    session: Session,
    email_ids: Sequence[int],
    *,
    config: Optional[AppConfig] = None,
) -> Optional[Path]:
    if not email_ids:
        return None

    cfg = config or load_config()
    reports_dir = _ensure_reports_dir(cfg)

    emails = (
        session.query(InputEmail)
        .filter(InputEmail.id.in_(email_ids))
        .order_by(InputEmail.created_at.asc())
        .all()
    )

    if not emails:
        logger.info("No matching emails found for report generation.")
        return None

    sections = "\n".join(_render_email_section(email) for email in emails)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = f"Email Report ({len(emails)} emails)"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <title>{escape(title)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        h3 {{ margin-top: 40px; }}
    </style>
</head>
<body>
    <h1>{escape(title)}</h1>
    <p><em>Generated at {escape(generated_at)}</em></p>
    {sections}
</body>
</html>
"""
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    report_path = reports_dir / f"email_report_{timestamp}.html"
    report_path.write_text(html, encoding="utf-8")
    logger.info("Generated report at %s", report_path)
    return report_path

