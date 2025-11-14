"""Services for generating rich HTML reports for selected emails."""

from __future__ import annotations

import base64
import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional, Sequence

from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import InputEmail


@dataclass(slots=True)
class ReportArtifacts:
    """Paths to artifacts generated alongside the HTML report."""

    html_path: Path
    csv_path: Path


def _ensure_reports_dir(config: AppConfig) -> Path:
    reports_dir = config.output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def _format_datetime(value: Optional[datetime]) -> str:
    if not value:
        return "N/A"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _decode_json_list(payload: Optional[str]) -> list[str]:
    if not payload:
        return []
    try:
        data = json.loads(payload)
        if isinstance(data, list):
            return [str(item) for item in data]
    except json.JSONDecodeError:
        logger.debug("Failed to decode JSON payload: %s", payload)
    return []


def _build_email_section(email: InputEmail, attachments_markup: str) -> str:
    urls = ", ".join(_decode_json_list(email.url_parsed)) or "N/A"
    callbacks = ", ".join(_decode_json_list(email.callback_number_parsed)) or "N/A"
    return f"""
    <section id="email-{email.id}" class="email-card">
        <div class="email-header">
            <h2>{escape(email.subject or 'Untitled')}</h2>
            <div class="meta-grid">
                <div><strong>Sender:</strong> {escape(email.sender or 'N/A')}</div>
                <div><strong>Date Sent:</strong> {_format_datetime(email.date_sent)}</div>
                <div><strong>Date Reported:</strong> {_format_datetime(email.date_reported)}</div>
                <div><strong>Subject ID:</strong> {escape(email.subject_id or 'N/A')}</div>
                <div><strong>Message ID:</strong> {escape(email.message_id or 'N/A')}</div>
                <div><strong>Model Confidence:</strong> {email.model_confidence if email.model_confidence is not None else 'N/A'}</div>
                <div><strong>Additional Contacts:</strong> {escape(email.additional_contacts or 'N/A')}</div>
                <div><strong>URLs:</strong> {escape(urls)}</div>
                <div><strong>Callback Numbers:</strong> {escape(callbacks)}</div>
            </div>
        </div>
        <div class="email-body">
            <h3>Body Preview</h3>
            <div class="body-preview">{escape((email.body_html or '')[:3000])}</div>
        </div>
        {attachments_markup}
    </section>
    """


def _build_html_document(title: str, generated_at: str, zip_base64: str, sections: str) -> str:
    download_all_button = ""
    if zip_base64:
        download_all_button = f"""
        <button id="download-all-images" data-zip="{zip_base64}" data-filename="images_bundle.zip">
            Download All Images
        </button>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <title>{escape(title)}</title>
    <style>
        body {{
            font-family: "Segoe UI", Arial, sans-serif;
            margin: 32px;
            background: #f5f7fb;
            color: #1f2933;
        }}
        h1 {{
            margin-bottom: 0;
        }}
        .report-meta {{
            color: #52606d;
            margin-bottom: 24px;
        }}
        .controls {{
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
        }}
        button {{
            border: none;
            background: #335dff;
            color: white;
            padding: 10px 18px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }}
        button.secondary {{
            background: #8899bb;
        }}
        button:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
        }}
        .email-card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 6px 20px rgba(15, 23, 42, 0.08);
            margin-bottom: 32px;
            padding: 24px;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 12px;
            margin-top: 16px;
        }}
        .body-preview {{
            background: #f1f4ff;
            border-radius: 10px;
            padding: 16px;
            margin-top: 12px;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .attachments {{
            margin-top: 20px;
        }}
        .attachment-grid {{
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
        }}
        .thumb {{
            width: 140px;
            background: #f8f9ff;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.08);
        }}
        .thumb img {{
            width: 100%;
            height: 90px;
            object-fit: cover;
            border-radius: 6px;
            cursor: pointer;
        }}
        .thumb button {{
            margin-top: 8px;
            width: 100%;
        }}
        .attachment-list {{
            margin-top: 16px;
            padding-left: 20px;
        }}
        .modal {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(15, 23, 42, 0.75);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 9999;
        }}
        .modal.open {{
            display: flex;
        }}
        .modal img {{
            max-width: 90%;
            max-height: 90%;
            border-radius: 12px;
            box-shadow: 0 15px 45px rgba(0, 0, 0, 0.45);
        }}
        .modal .close {{
            position: absolute;
            top: 20px;
            right: 30px;
            font-size: 32px;
            color: white;
            cursor: pointer;
        }}
        .toc {{
            margin-bottom: 24px;
            background: white;
            padding: 16px;
            border-radius: 10px;
            box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
        }}
        .toc ul {{
            list-style: none;
            padding: 0;
            margin: 0;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 8px;
        }}
        .toc a {{
            text-decoration: none;
            color: #335dff;
        }}
    </style>
</head>
<body>
    <div class="modal" id="image-modal">
        <span class="close" id="modal-close">&times;</span>
        <img id="modal-image" alt="Attachment preview"/>
    </div>

    <h1>{escape(title)}</h1>
    <div class="report-meta">Generated at {escape(generated_at)}</div>
    <div class="controls">
        {download_all_button}
    </div>
    <div class="toc">
        <h3>Emails in this report</h3>
        <ul id="toc-list"></ul>
    </div>
    {sections}
    <script>
    (function() {{
        const modal = document.getElementById("image-modal");
        const modalImage = document.getElementById("modal-image");
        const modalClose = document.getElementById("modal-close");

        document.querySelectorAll(".thumbnail").forEach((thumb) => {{
            thumb.addEventListener("click", () => {{
                modalImage.src = thumb.dataset.full;
                modalImage.alt = thumb.dataset.filename;
                modal.classList.add("open");
            }});
        }});

        modalClose.addEventListener("click", () => modal.classList.remove("open"));
        modal.addEventListener("click", (event) => {{
            if (event.target === modal) {{
                modal.classList.remove("open");
            }}
        }});

        function base64ToBlob(base64, mime) {{
            const binary = atob(base64);
            const len = binary.length;
            const buffer = new Uint8Array(len);
            for (let i = 0; i < len; i++) {{
                buffer[i] = binary.charCodeAt(i);
            }}
            return new Blob([buffer], {{ type: mime }});
        }}

        function triggerDownload(blob, filename) {{
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = filename;
            document.body.appendChild(anchor);
            anchor.click();
            document.body.removeChild(anchor);
            URL.revokeObjectURL(url);
        }}

        document.querySelectorAll("[data-download]").forEach((button) => {{
            button.addEventListener("click", () => {{
                const base64 = button.dataset.base64;
                const filename = button.dataset.filename;
                const mime = button.dataset.mime || "application/octet-stream";
                const blob = base64ToBlob(base64, mime);
                triggerDownload(blob, filename);
            }});
        }});

        const downloadAllButton = document.getElementById("download-all-images");
        if (downloadAllButton) {{
            downloadAllButton.addEventListener("click", () => {{
                const zipBase64 = downloadAllButton.dataset.zip;
                if (!zipBase64) {{
                    return;
                }}
                const blob = base64ToBlob(zipBase64, "application/zip");
                const filename = downloadAllButton.dataset.filename || "images_bundle.zip";
                triggerDownload(blob, filename);
            }});
        }}

        const tocList = document.getElementById("toc-list");
        document.querySelectorAll("section.email-card").forEach((section) => {{
            const id = section.id;
            const title = section.querySelector("h2").textContent;
            const li = document.createElement("li");
            const link = document.createElement("a");
            link.href = "#" + id;
            link.textContent = title;
            li.appendChild(link);
            tocList.appendChild(li);
        }});
    }})();
    </script>
</body>
</html>
"""


def generate_email_report(
    session: Session,
    email_ids: Sequence[int],
    *,
    config: Optional[AppConfig] = None,
) -> Optional[ReportArtifacts]:
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

    image_zip_buffer = io.BytesIO()
    with zipfile.ZipFile(image_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as image_zip:
        image_added = False
        email_sections = []
        csv_rows = []

        for email in emails:
            image_cards = []
            other_attachments = []
            image_references = []

            for index, attachment in enumerate(email.attachments or []):
                file_name = attachment.file_name or f"attachment_{attachment.id}"
                file_type = (attachment.file_type or "").lower()
                storage_path = Path(attachment.storage_path or "")
                is_image = file_type.startswith("image")

                if storage_path.exists():
                    data = storage_path.read_bytes()
                    base64_payload = base64.b64encode(data).decode("utf-8")

                    if is_image:
                        safe_file_name = f"{email.subject_id or email.id}_{index}_{file_name}"
                        image_zip.writestr(safe_file_name, data)
                        image_added = True
                        image_references.append(safe_file_name)

                        image_cards.append(
                            f"""
                            <div class="thumb">
                                <img src="data:{attachment.file_type};base64,{base64_payload}"
                                     alt="{escape(file_name)}"
                                     class="thumbnail"
                                     data-full="data:{attachment.file_type};base64,{base64_payload}"
                                     data-filename="{escape(file_name)}"/>
                                <button class="secondary" data-download data-base64="{base64_payload}"
                                        data-filename="{escape(file_name)}" data-mime="{escape(attachment.file_type or 'image/png')}">
                                    Download
                                </button>
                            </div>
                            """
                        )
                    else:
                        other_attachments.append(
                            f"""
                            <li>
                                <strong>{escape(file_name)}</strong> ({escape(attachment.file_type or 'unknown')})
                                <button class="secondary" data-download data-base64="{base64_payload}"
                                        data-filename="{escape(file_name)}" data-mime="{escape(attachment.file_type or 'application/octet-stream')}">
                                    Download
                                </button>
                            </li>
                            """
                        )
                else:
                    other_attachments.append(
                        f"<li><strong>{escape(file_name)}</strong> — file missing on disk.</li>"
                    )

            attachments_markup = '<div class="attachments"><em>No attachments.</em></div>'
            if image_cards or other_attachments:
                attachments_markup = '<div class="attachments">'
                if image_cards:
                    attachments_markup += '<h3>Image Attachments</h3><div class="attachment-grid">' + "".join(image_cards) + "</div>"
                if other_attachments:
                    attachments_markup += '<h3>Other Attachments</h3><ul class="attachment-list">' + "".join(other_attachments) + "</ul>"
                attachments_markup += "</div>"

            email_sections.append(_build_email_section(email, attachments_markup))

            csv_rows.append(
                [
                    email.id,
                    email.subject or "",
                    email.sender or "",
                    email.subject_id or "",
                    email.date_sent.isoformat() if email.date_sent else "",
                    email.date_reported.isoformat() if email.date_reported else "",
                    ";".join(_decode_json_list(email.url_parsed)),
                    ";".join(_decode_json_list(email.callback_number_parsed)),
                    ";".join(image_references),
                ]
            )

    zip_base64 = (
        base64.b64encode(image_zip_buffer.getvalue()).decode("utf-8")
        if image_zip_buffer.getbuffer().nbytes > 0
        else ""
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = f"Email Report ({len(emails)} emails)"
    html_document = _build_html_document(title, generated_at, zip_base64, "\n".join(email_sections))

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    report_path = reports_dir / f"email_report_{timestamp}.html"
    report_path.write_text(html_document, encoding="utf-8")
    logger.info("Generated report at %s", report_path)

    csv_path = reports_dir / f"email_report_{timestamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "Email ID",
                "Subject",
                "Sender",
                "Subject ID",
                "Date Sent",
                "Date Reported",
                "URLs",
                "Callback Numbers",
                "Image References",
            ]
        )
        writer.writerows(csv_rows)

    return ReportArtifacts(html_path=report_path, csv_path=csv_path)

