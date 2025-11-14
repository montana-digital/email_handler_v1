"""Utilities for exporting individual emails and attachments."""

from __future__ import annotations

import io
import textwrap
import zipfile
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.config import AppConfig
from app.utils import sha256_file


def find_original_email_bytes(
    config: AppConfig,
    email_hash: str | None,
) -> tuple[str, bytes] | None:
    """Locate the original .eml/.msg file by hash."""
    if not email_hash:
        return None

    search_roots = [config.input_dir, config.output_dir]
    seen: set[Path] = set()

    for root in search_roots:
        if not root.exists():
            continue
        for pattern in ("*.eml", "*.msg"):
            for candidate in root.rglob(pattern):
                if candidate in seen:
                    continue
                seen.add(candidate)
                try:
                    digest = sha256_file(candidate)
                except Exception:
                    continue
                if digest == email_hash:
                    try:
                        return candidate.name, candidate.read_bytes()
                    except OSError:
                        continue
    return None


def build_attachments_zip(attachments: Sequence[Mapping[str, Any]], *, prefix: str = "attachments") -> tuple[str, bytes] | None:
    """Bundle existing attachment files into a ZIP payload."""
    buffer = io.BytesIO()
    added = False
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for attachment in attachments:
            storage_path = attachment.get("storage_path")
            file_name = attachment.get("file_name") or "attachment"
            if not storage_path:
                continue
            path = Path(storage_path)
            if not path.exists():
                continue
            try:
                archive.write(path, arcname=file_name)
                added = True
            except OSError:
                continue
    if not added:
        return None
    return f"{prefix}.zip", buffer.getvalue()


def build_single_email_html(email_detail: Mapping[str, Any]) -> bytes:
    """Render a standalone HTML document for a single email."""
    subject = email_detail.get("subject") or email_detail.get("subject_id") or "Untitled"
    sender = email_detail.get("sender") or email_detail.get("from_address") or "Unknown sender"
    date_sent = email_detail.get("date_sent") or email_detail.get("created_at") or "N/A"
    urls = email_detail.get("urls_parsed") or email_detail.get("body_urls") or []
    callbacks = email_detail.get("callback_numbers_parsed") or email_detail.get("body_numbers") or []

    body_html = email_detail.get("body_html")
    if not body_html:
        body_text = email_detail.get("body_text") or "No body content available."
        body_html = f"<pre>{escape(body_text)}</pre>"

    metadata_rows = [
        ("Subject ID", email_detail.get("subject_id") or "—"),
        ("Message ID", email_detail.get("message_id") or "—"),
        ("Sender", sender),
        ("Date Sent", str(date_sent)),
        ("URLs", ", ".join(urls) or "—"),
        ("Callback Numbers", ", ".join(callbacks) or "—"),
        ("Email Hash", email_detail.get("email_hash") or "—"),
    ]

    metadata_html = ""
    for label, raw_value in metadata_rows:
        value = raw_value or "—"
        metadata_html += f"<dt>{escape(label)}</dt><dd><code>{escape(str(value))}</code></dd>"

    document = textwrap.dedent(
        f"""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8"/>
            <title>{escape(subject)}</title>
            <style>
                body {{
                    margin: 0;
                    padding: 2rem;
                    font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
                    background: #0f172a;
                    color: #e2e8f0;
                }}
                .container {{
                    max-width: 960px;
                    margin: 0 auto;
                }}
                .card {{
                    background: #0b1120;
                    border: 1px solid #1d2939;
                    border-radius: 16px;
                    padding: 1.5rem;
                    box-shadow: 0 8px 30px rgba(15, 23, 42, 0.35);
                    margin-bottom: 1.5rem;
                }}
                h1 {{
                    margin-bottom: 0.25rem;
                }}
                dl {{
                    display: grid;
                    grid-template-columns: max-content 1fr;
                    gap: 0.25rem 1rem;
                }}
                dt {{
                    font-weight: 600;
                    color: #cbd5f5;
                }}
                dd {{
                    margin: 0;
                }}
                code {{
                    background: #111c2e;
                    padding: 0.15rem 0.35rem;
                    border-radius: 6px;
                    font-size: 0.9rem;
                    color: #f0abfc;
                }}
                .body {{
                    background: #ffffff;
                    border-radius: 12px;
                    padding: 1rem;
                    color: #111827;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <h1>{escape(subject)}</h1>
                    <p>From: <strong>{escape(sender)}</strong></p>
                </div>
                <div class="card">
                    <h2>Metadata</h2>
                    <dl>{metadata_html}</dl>
                </div>
                <div class="card">
                    <h2>Body</h2>
                    <div class="body">{body_html}</div>
                </div>
            </div>
        </body>
        </html>
        """
    ).strip()
    return document.encode("utf-8")

