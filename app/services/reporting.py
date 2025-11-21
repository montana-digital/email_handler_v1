"""Services for generating immersive HTML reports for selected emails."""

from __future__ import annotations

import base64
import csv
import io
import json
import textwrap
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from html import escape
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.db.models import InputEmail, KnowledgeTableMetadata
from app.utils import sha256_file

from email import policy
from email.parser import BytesParser


@dataclass(slots=True)
class ReportArtifacts:
    """Filesystem artefacts generated alongside the HTML report."""

    html_path: Path
    csv_text_path: Path
    csv_full_path: Path
    attachments_zip_path: Optional[Path]
    emails_zip_path: Optional[Path]


JSZIP_MINIFIED = textwrap.dedent(
    r"""
    /*! jszip v3.10.1 - A library for creating, reading and editing .zip files
    * <http://stuartk.com/jszip>
    * (c) 2009-2022 Stuart Knightley, David Duponchel, Franz Buchinger, António Afonso
    * Dual licenced under the MIT license or GPLv3. See https://raw.githubusercontent.com/Stuk/jszip/main/LICENSE.markdown for details.
    */
    !function(e){"object"==typeof exports&&"undefined"!=typeof module?module.exports=e():"function"==typeof define&&define.amd?define(e):("undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof self?self:this).JSZip=e()}(function(){var e={};function t(e){return e&&e.Math==Math&&e}return e})();
    """
).strip()


def _ensure_reports_dir(config: AppConfig) -> Path:
    reports_dir = config.output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def _format_datetime(value: Optional[datetime]) -> str:
    if not value:
        return "N/A"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _decode_json_list(payload: Optional[str]) -> List[str]:
    if not payload:
        return []
    try:
        data = json.loads(payload)
        if isinstance(data, list):
            return [str(item) for item in data]
    except json.JSONDecodeError:
        logger.debug("Failed to decode JSON payload: %s", payload)
    return []


def _compress_to_zip(files: Iterable[Tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_name, content in files:
            archive.writestr(file_name, content)
    return buffer.getvalue()


def _collect_original_email_bytes(cfg: AppConfig, emails: Sequence[InputEmail]) -> Dict[str, Tuple[str, bytes]]:
    wanted_hashes = {email.email_hash for email in emails if email.email_hash}
    if not wanted_hashes:
        return {}

    matches: Dict[str, Tuple[str, bytes]] = {}
    search_roots = [cfg.input_dir, cfg.output_dir]
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
                if digest in wanted_hashes and digest not in matches:
                    try:
                        matches[digest] = (candidate.name, candidate.read_bytes())
                    except OSError:
                        continue
                if len(matches) == len(wanted_hashes):
                    return matches
    return matches


def _escape_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _build_detail_card(label: str, value: str) -> str:
    safe_value = value or "N/A"
    attr_value = _escape_attr(safe_value)
    if safe_value == "N/A":
        display_value = "<em>N/A</em>"
    else:
        display_value = escape(safe_value).replace("\n", "<br/>")
    return textwrap.dedent(
        f"""
        <div class="detail-card">
            <div class="detail-card__header">
                <span class="detail-card__label">{label}</span>
                <button class="copy-btn" data-copy="{attr_value}" title="Copy value">
                    <span aria-hidden="true">⧉</span>
                </button>
            </div>
            <div class="detail-card__value">{display_value}</div>
        </div>
        """
    ).strip()


def _render_email_section(email: InputEmail, body_markup: str, attachments_markup: str, knowledge_columns: List[str] = None) -> str:
    urls = ", ".join(_decode_json_list(email.url_parsed)) or "N/A"
    callbacks = ", ".join(_decode_json_list(email.callback_number_parsed)) or "N/A"
    
    # Body markup is already processed with CSS in _resolve_body_markup
    body_src = base64.b64encode(body_markup.encode("utf-8")).decode("utf-8")
    
    detail_cards = [
        _build_detail_card("Subject ID", email.subject_id or "N/A"),
        _build_detail_card("Message ID", email.message_id or "N/A"),
        _build_detail_card("Sender", email.sender or "N/A"),
        _build_detail_card("Date Sent", _format_datetime(email.date_sent)),
        _build_detail_card("Date Reported", _format_datetime(email.date_reported)),
        _build_detail_card("URLs", urls),
        _build_detail_card("Callback Numbers", callbacks),
        _build_detail_card("Additional Contacts", email.additional_contacts or "N/A"),
        _build_detail_card(
            "Model Confidence",
            f"{email.model_confidence:.2f}" if email.model_confidence is not None else "N/A",
        ),
        _build_detail_card("Email Hash", email.email_hash or "N/A"),
    ]
    
    # Add knowledge columns if available
    if knowledge_columns:
        knowledge_data = email.knowledge_data or {}
        if not isinstance(knowledge_data, dict):
            knowledge_data = {}
        
        for col in knowledge_columns:
            value = knowledge_data.get(col, "")
            if value is None:
                value = ""
            else:
                value = str(value)
            detail_cards.append(_build_detail_card(col, value or "N/A"))
    
    detail_cards_html = "".join(detail_cards)

    section = textwrap.dedent(
        f"""
        <section class="email-card" data-email-id="{email.id}">
            <header class="email-card__header">
                <div class="email-card__title">
                    <label class="select-toggle">
                        <input type="checkbox" class="email-select" data-email-id="{email.id}">
                        <span>Select</span>
                    </label>
                    <div>
                        <h2>{email.subject or 'Untitled'}</h2>
                        <p class="muted">From: {email.sender or 'N/A'}</p>
                    </div>
                </div>
                <div class="email-card__actions">
                    <button class="btn secondary download-email" data-email-id="{email.id}">Download Email</button>
                    <button class="btn secondary download-attachments" data-email-id="{email.id}">Download Attachments</button>
                    <button class="btn secondary download-images" data-email-id="{email.id}">Download Images</button>
                </div>
            </header>
            <div class="email-card__content">
                <div class="email-card__body">
                    <h3>Message Body</h3>
                    <iframe class="body-preview" sandbox="allow-same-origin allow-scripts" src="data:text/html;base64,{body_src}"></iframe>
                </div>
                <div class="email-card__details">
                    {detail_cards_html}
                </div>
            </div>
            {attachments_markup}
        </section>
        """
    )
    return section.strip()


def _render_attachments(attachments: List[Dict[str, str]]) -> str:
    if not attachments:
        return '<div class="attachments"><em>No attachments.</em></div>'

    image_markup: List[str] = []
    other_markup: List[str] = []

    for attachment in attachments:
        if attachment["isImage"]:
            image_markup.append(
                textwrap.dedent(
                    f"""
                    <div class="thumb">
                        <img src="data:{attachment['mime']};base64,{attachment['base64']}"
                             alt="{attachment['fileName']}"
                             class="thumbnail"
                             data-full="data:{attachment['mime']};base64,{attachment['base64']}"
                             data-filename="{attachment['fileName']}"/>
                        <button class="btn tertiary" data-download
                                data-base64="{attachment['base64']}"
                                data-mime="{attachment['mime']}"
                                data-filename="{attachment['fileName']}">
                            Download
                        </button>
                    </div>
                    """
                ).strip()
            )
        else:
            other_markup.append(
                textwrap.dedent(
                    f"""
                    <li>
                        <strong>{attachment['fileName']}</strong>
                        <span class="muted">({attachment['mime']}, {attachment['sizeLabel']})</span>
                        <button class="btn tertiary" data-download
                                data-base64="{attachment['base64']}"
                                data-mime="{attachment['mime']}"
                                data-filename="{attachment['fileName']}">
                            Download
                        </button>
                    </li>
                    """
                ).strip()
            )

    blocks: List[str] = ['<div class="attachments">']
    if image_markup:
        blocks.append('<h3>Image Attachments</h3>')
        blocks.append('<div class="attachment-grid">' + "".join(image_markup) + "</div>")
    if other_markup:
        blocks.append('<h3>Other Attachments</h3>')
        blocks.append('<ul class="attachment-list">' + "".join(other_markup) + "</ul>")
    blocks.append("</div>")
    return "".join(blocks)


def _build_html_document(
    title: str,
    generated_at: str,
    sections_html: str,
    payload: Dict[str, object],
) -> str:
    css = textwrap.dedent(
        """
        :root {
            --bg: #f5f7fb;
            --surface: #ffffff;
            --surface-alt: rgba(255,255,255,0.82);
            --text: #1f2937;
            --muted: #64748b;
            --border: rgba(99,102,241,0.18);
            --accent: linear-gradient(135deg, #6366f1 0%, #22d3ee 100%);
            --shadow: 0 20px 45px rgba(15,23,42,0.15);
            --button-bg: rgba(99,102,241,0.18);
            --button-text: #1e293b;
        }

        body.dark {
            --bg: #020617;
            --surface: rgba(15,23,42,0.92);
            --surface-alt: rgba(15,23,42,0.78);
            --text: #e2e8f0;
            --muted: #94a3b8;
            --border: rgba(148,163,184,0.26);
            --accent: linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%);
            --shadow: 0 22px 60px rgba(2,6,23,0.72);
            --button-bg: rgba(37,99,235,0.22);
            --button-text: #dbeafe;
        }

        * {
            box-sizing: border-box;
        }

        body {
            font-family: "Inter", "Segoe UI", sans-serif;
            margin: 0;
            padding: 32px 40px 96px;
            background: #ffffff;
            color: var(--text);
            transition: background 0.3s ease, color 0.3s ease;
        }

        h1 {
            margin: 0;
            font-size: 2.8rem;
        }

        .muted {
            color: var(--muted);
        }

        .navbar {
            position: sticky;
            top: 18px;
            z-index: 999;
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: center;
            padding: 16px 22px;
            margin-bottom: 28px;
            border-radius: 16px;
            background: var(--surface-alt);
            border: 1px solid var(--border);
            backdrop-filter: blur(22px);
            box-shadow: var(--shadow);
        }

        .navbar .actions,
        .navbar .selection-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
        }

        .navbar .selection-actions {
            display: none;
        }

        .navbar .selection-actions.active {
            display: flex;
        }

        .toggle {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 0.9rem;
        }

        .toggle input {
            appearance: none;
            width: 48px;
            height: 22px;
            border-radius: 999px;
            background: var(--button-bg);
            position: relative;
            cursor: pointer;
            transition: background 0.2s ease;
        }

        .toggle input::after {
            content: "";
            position: absolute;
            top: 3px;
            left: 4px;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: var(--surface);
            transition: transform 0.2s ease;
        }

        .toggle input:checked {
            background: var(--accent);
        }

        .toggle input:checked::after {
            transform: translateX(26px);
        }

        .btn {
            border: none;
            border-radius: 11px;
            padding: 9px 18px;
            font-size: 0.92rem;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: var(--button-bg);
            color: var(--button-text);
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }

        .btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 12px 28px rgba(15,23,42,0.12);
        }

        .btn.primary {
            background-image: var(--accent);
            color: #fff;
        }

        .btn.secondary {
            background: rgba(148,163,184,0.18);
        }

        .btn.tertiary {
            background: rgba(148,163,184,0.12);
            font-size: 0.8rem;
            padding: 6px 12px;
        }

        .btn:disabled {
            opacity: 0.45;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }

        .report-meta {
            color: var(--muted);
            margin: 0 0 22px;
        }

        .toc {
            margin-bottom: 26px;
            background: var(--surface);
            padding: 22px;
            border-radius: 16px;
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
        }

        .toc h3 {
            margin: 0 0 12px;
        }

        .toc ul {
            list-style: none;
            padding: 0;
            margin: 0;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 10px;
        }

        .toc a {
            text-decoration: none;
            color: inherit;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 12px 14px;
            background: var(--surface-alt);
            display: block;
        }

        .email-card {
            background: var(--surface);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 26px;
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
        }

        .email-card__header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 18px;
            margin-bottom: 18px;
        }

        .email-card__title {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .select-toggle input {
            width: 20px;
            height: 20px;
        }

        .email-card__actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .email-card__content {
            display: grid;
            grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
            gap: 22px;
        }

        .body-preview {
            width: 100%;
            min-height: 340px;
            border: none;
            border-radius: 14px;
            background: #fff;
            box-shadow: inset 0 0 0 1px rgba(99,102,241,0.08);
        }

        body.dark .body-preview {
            background: rgba(15,23,42,0.95);
        }

        .email-card__body {
            background: var(--surface-alt);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 18px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .email-card__details {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
        }

        .detail-card {
            background: var(--surface-alt);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .detail-card__header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
        }

        .detail-card__label {
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--muted);
        }

        .detail-card__value {
            font-size: 0.95rem;
            word-break: break-word;
        }

        .copy-btn {
            border: none;
            background: rgba(99,102,241,0.16);
            color: inherit;
            cursor: pointer;
            border-radius: 8px;
            padding: 6px 8px;
            font-size: 0.85rem;
            transition: transform 0.16s ease, background 0.16s ease;
        }

        .copy-btn:hover {
            transform: translateY(-1px);
        }

        .copy-btn.copied {
            background: rgba(34,211,238,0.3);
        }

        .attachments {
            margin-top: 24px;
        }

        .attachment-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 14px;
        }

        .thumb {
            background: var(--surface-alt);
            border-radius: 12px;
            border: 1px solid var(--border);
            padding: 12px;
            text-align: center;
            box-shadow: var(--shadow);
        }

        .thumb img {
            width: 100%;
            height: 100px;
            object-fit: cover;
            border-radius: 10px;
            cursor: zoom-in;
            margin-bottom: 8px;
        }

        .attachment-list {
            margin: 16px 0 0;
            padding-left: 18px;
        }

        .attachment-list li {
            margin-bottom: 8px;
        }

        .modal {
            position: fixed;
            inset: 0;
            background: rgba(15,23,42,0.72);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }

        .modal.open {
            display: flex;
        }

        .modal img {
            max-width: 92%;
            max-height: 92%;
            border-radius: 18px;
            box-shadow: 0 32px 64px rgba(0,0,0,0.58);
        }

        .modal .close {
            position: absolute;
            top: 24px;
            right: 34px;
            font-size: 36px;
            color: #fff;
            cursor: pointer;
        }

        @media (max-width: 820px) {
            body {
                padding: 20px 18px 80px;
            }

            .navbar {
                flex-direction: column;
                align-items: stretch;
            }

            .email-card__header {
                flex-direction: column;
                align-items: flex-start;
            }

            .email-card__actions {
                width: 100%;
            }

            .email-card__content {
                grid-template-columns: 1fr;
            }
        }
        """
    )

    json_payload = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    script = textwrap.dedent(
        f"""
        <script>{JSZIP_MINIFIED}</script>
        <script id="report-data" type="application/json">{json_payload}</script>
        <script>
        (function() {{
            const DATA = JSON.parse(document.getElementById("report-data").textContent);
            const EMAIL_INDEX = new Map(DATA.emails.map((email) => [email.id, email]));
            const selectedIds = new Set();

            function base64ToUint8(base64) {{
                const raw = atob(base64);
                const buffer = new Uint8Array(raw.length);
                for (let i = 0; i < raw.length; i++) {{
                    buffer[i] = raw.charCodeAt(i);
                }}
                return buffer;
            }}

            function base64ToBlob(base64, mime) {{
                return new Blob([base64ToUint8(base64)], {{ type: mime }});
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

            async function downloadZip(items, filename) {{
                if (!items.length) {{
                    alert("Nothing to download for this action.");
                    return;
                }}
                const zip = new JSZip();
                items.forEach((item) => zip.file(item.name, base64ToUint8(item.base64), {{ binary: true }}));
                const content = await zip.generateAsync({{ type: "uint8array", compression: "DEFLATE" }});
                triggerDownload(new Blob([content], {{ type: "application/zip" }}), filename);
            }}

            function bindCopyButtons() {{
                document.querySelectorAll(".copy-btn").forEach((button) => {{
                    button.addEventListener("click", async () => {{
                        const value = button.dataset.copy || "";
                        try {{
                            await navigator.clipboard.writeText(value);
                            button.classList.add("copied");
                            setTimeout(() => button.classList.remove("copied"), 1200);
                        }} catch (err) {{
                            const textarea = document.createElement("textarea");
                            textarea.value = value;
                            textarea.style.position = "fixed";
                            textarea.style.opacity = "0";
                            document.body.appendChild(textarea);
                            textarea.focus();
                            textarea.select();
                            try {{
                                document.execCommand("copy");
                                button.classList.add("copied");
                                setTimeout(() => button.classList.remove("copied"), 1200);
                            }} catch (err2) {{
                                console.warn("Clipboard copy failed", err2);
                            }}
                            document.body.removeChild(textarea);
                        }}
                    }});
                }});
            }}

            function hydratePrimaryButtons() {{
                document.getElementById("btn-html")?.addEventListener("click", () => {{
                    triggerDownload(base64ToBlob(DATA.bundles.htmlBase64, "text/html"), DATA.bundles.htmlName);
                }});

                document.getElementById("btn-csv-text")?.addEventListener("click", () => {{
                    triggerDownload(base64ToBlob(DATA.bundles.csvText, "text/csv"), DATA.bundles.csvTextName);
                }});

                document.getElementById("btn-csv-full")?.addEventListener("click", () => {{
                    triggerDownload(base64ToBlob(DATA.bundles.csvFull, "text/csv"), DATA.bundles.csvFullName);
                }});

                document.getElementById("btn-all-attachments")?.addEventListener("click", () => {{
                    if (DATA.bundles.attachmentsZip) {{
                        triggerDownload(base64ToBlob(DATA.bundles.attachmentsZip, "application/zip"), DATA.bundles.attachmentsZipName);
                    }} else {{
                            const files = [];
                            DATA.emails.forEach((email) => {{
                                email.attachments.forEach((att) => {{
                                    files.push({{
                                        name: `${{email.subjectId || email.id}}/${{att.fileName}}`,
                                        base64: att.base64
                                    }});
                                }});
                            }});
                        downloadZip(files, "report_attachments.zip");
                    }}
                }});

                document.getElementById("btn-all-emails")?.addEventListener("click", () => {{
                    if (DATA.bundles.emailsZip) {{
                        triggerDownload(base64ToBlob(DATA.bundles.emailsZip, "application/zip"), DATA.bundles.emailsZipName);
                    }} else {{
                        const files = [];
                        DATA.emails.forEach((email) => {{
                            if (email.original) {{
                                files.push({{
                                    name: email.original.fileName,
                                    base64: email.original.base64
                                }});
                            }}
                        }});
                        downloadZip(files, "report_emails.zip");
                    }}
                }});
            }}

            function bindEmailLevelButtons() {{
                document.querySelectorAll(".download-email").forEach((button) => {{
                    button.addEventListener("click", () => {{
                        const email = EMAIL_INDEX.get(Number(button.dataset.emailId));
                        if (!email || !email.original) {{
                            alert("Original email not available for this entry.");
                            return;
                        }}
                        triggerDownload(base64ToBlob(email.original.base64, email.original.mime), email.original.fileName);
                    }});
                }});

        document.querySelectorAll(".download-attachments").forEach((button) => {{
                    button.addEventListener("click", () => {{
                        const email = EMAIL_INDEX.get(Number(button.dataset.emailId));
                        if (!email) {{
                            return;
                        }}
                        if (email.zipAttachments) {{
                            triggerDownload(base64ToBlob(email.zipAttachments, "application/zip"), `${{email.subjectId || email.id}}_attachments.zip`);
                            return;
                        }}
                        if (typeof JSZip === "undefined") {{
                            alert("Bulk attachment download unavailable (zip support missing).");
                            return;
                        }}
                        const files = email.attachments.map((att) => ({{
                            name: att.fileName,
                            base64: att.base64
                        }}));
                        downloadZip(files, `${{email.subjectId || email.id}}_attachments.zip`);
                    }});
                }});

        document.querySelectorAll(".download-images").forEach((button) => {{
                    button.addEventListener("click", () => {{
                        const email = EMAIL_INDEX.get(Number(button.dataset.emailId));
                        if (!email) {{
                            return;
                        }}
                        if (email.zipImages) {{
                            triggerDownload(base64ToBlob(email.zipImages, "application/zip"), `${{email.subjectId || email.id}}_images.zip`);
                            return;
                        }}
                        if (typeof JSZip === "undefined") {{
                            alert("Bulk image download unavailable (zip support missing).");
                            return;
                        }}
                        const files = email.attachments
                            .filter((att) => att.isImage)
                            .map((att) => ({{
                                name: att.fileName,
                                base64: att.base64
                            }}));
                        downloadZip(files, `${{email.subjectId || email.id}}_images.zip`);
                    }});
                }});
            }}

            function updateSelectionPanel() {{
                const panel = document.getElementById("selection-actions");
                const counter = document.getElementById("selection-count");
                if (!panel || !counter) {{
                    return;
                }}
                counter.textContent = String(selectedIds.size);
                if (selectedIds.size >= 2) {{
                    panel.classList.add("active");
                }} else {{
                    panel.classList.remove("active");
                }}
            }}

            function selectedFiles(kind) {{
                const files = [];
                selectedIds.forEach((id) => {{
                    const email = EMAIL_INDEX.get(id);
                    if (!email) {{
                        return;
                    }}
                    if (kind === "emails" && email.original) {{
                        files.push({{
                            name: email.original.fileName,
                            base64: email.original.base64
                        }});
                    }} else if (kind === "attachments") {{
                            email.attachments.forEach((att) => {{
                                files.push({{
                                    name: `${{email.subjectId || email.id}}/${{att.fileName}}`,
                                    base64: att.base64
                                }});
                            }});
                    }} else if (kind === "images") {{
                        email.attachments
                            .filter((att) => att.isImage)
                            .forEach((att) => {{
                                files.push({{
                                    name: `${{email.subjectId || email.id}}/${{att.fileName}}`,
                                    base64: att.base64
                                }});
                            }});
                    }} else if (kind === "bundle") {{
                        if (email.original) {{
                            files.push({{
                                name: `emails/${{email.original.fileName}}`,
                                base64: email.original.base64
                            }});
                        }}
                        email.attachments.forEach((att) => {{
                            files.push({{
                                name: `attachments/${{email.subjectId || email.id}}/${{att.fileName}}`,
                                base64: att.base64
                            }});
                        }});
                    }}
                }});
                return files;
            }}

            function bindSelectionButtons() {{
                document.querySelectorAll(".email-select").forEach((checkbox) => {{
                    checkbox.addEventListener("change", () => {{
                        const id = Number(checkbox.dataset.emailId);
                        if (checkbox.checked) {{
                            selectedIds.add(id);
                        }} else {{
                            selectedIds.delete(id);
                        }}
                        updateSelectionPanel();
                    }});
                }});

                document.getElementById("btn-selected-attachments")?.addEventListener("click", () => {{
                    if (typeof JSZip === "undefined") {{
                        alert("Bulk download unavailable (zip support missing).");
                        return;
                    }}
                    downloadZip(selectedFiles("attachments"), "selected_attachments.zip");
                }});

                document.getElementById("btn-selected-images")?.addEventListener("click", () => {{
                    if (typeof JSZip === "undefined") {{
                        alert("Bulk download unavailable (zip support missing).");
                        return;
                    }}
                    downloadZip(selectedFiles("images"), "selected_images.zip");
                }});

                document.getElementById("btn-selected-emails")?.addEventListener("click", () => {{
                    if (typeof JSZip === "undefined") {{
                        alert("Bulk download unavailable (zip support missing).");
                        return;
                    }}
                    downloadZip(selectedFiles("emails"), "selected_emails.zip");
                }});

                document.getElementById("btn-selected-all")?.addEventListener("click", () => {{
                    if (typeof JSZip === "undefined") {{
                        alert("Bulk download unavailable (zip support missing).");
                        return;
                    }}
                    downloadZip(selectedFiles("bundle"), "selected_bundle.zip");
                }});
            }}

            function configureThemeToggle() {{
                const toggle = document.getElementById("mode-toggle");
                if (!toggle) {{
                    return;
                }}
                const stored = localStorage.getItem("email-handler-theme");
                if (stored === "dark") {{
                    document.body.classList.add("dark");
                    toggle.checked = true;
                }}
                toggle.addEventListener("change", () => {{
                    if (toggle.checked) {{
                        document.body.classList.add("dark");
                        localStorage.setItem("email-handler-theme", "dark");
                    }} else {{
                        document.body.classList.remove("dark");
                        localStorage.setItem("email-handler-theme", "light");
                    }}
                }});
            }}

            hydratePrimaryButtons();
            bindEmailLevelButtons();
            bindSelectionButtons();
            updateSelectionPanel();
            configureThemeToggle();
            bindCopyButtons();

            document.getElementById("modal-close")?.addEventListener("click", () => {{
                document.getElementById("modal")?.classList.remove("open");
            }});

            const modal = document.getElementById("modal");
            const modalImage = document.getElementById("modal-image");
            document.querySelectorAll(".thumbnail").forEach((thumbnail) => {{
                thumbnail.addEventListener("click", () => {{
                    if (!modal || !modalImage) {{
                        return;
                    }}
                    modalImage.src = thumbnail.dataset.full;
                    modalImage.alt = thumbnail.dataset.filename || "";
                    modal.classList.add("open");
                }});
            }});

            modal?.addEventListener("click", (event) => {{
                if (event.target === modal) {{
                    modal.classList.remove("open");
                }}
            }});
        }})();
        </script>
        """
    )

    return textwrap.dedent(
        f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="utf-8"/>
            <title>{title}</title>
            <style>{css}</style>
        </head>
        <body>
            <nav class="navbar">
                <div class="actions">
                    <button class="btn primary" id="btn-html">Download HTML</button>
                    <button class="btn primary" id="btn-csv-text">CSV (Text)</button>
                    <button class="btn primary" id="btn-csv-full">CSV (Full)</button>
                    <button class="btn primary" id="btn-all-attachments">All Attachments</button>
                    <button class="btn primary" id="btn-all-emails">All Emails</button>
                </div>
                <div class="selection-actions" id="selection-actions">
                    <span class="muted">Selected: <span id="selection-count">0</span></span>
                    <button class="btn secondary" id="btn-selected-attachments">Attachments</button>
                    <button class="btn secondary" id="btn-selected-images">Images</button>
                    <button class="btn secondary" id="btn-selected-emails">Emails</button>
                    <button class="btn secondary" id="btn-selected-all">Combined Bundle</button>
                </div>
                <label class="toggle">
                    <input type="checkbox" id="mode-toggle">
                    <span>Dark mode</span>
                </label>
            </nav>
            <h1>{title}</h1>
            <p class="report-meta">Generated at {generated_at}</p>
            <div class="toc">
                <h3>Emails in this report</h3>
                <ul id="toc-list"></ul>
            </div>
            {sections_html}
            <div class="modal" id="modal">
                <span class="close" id="modal-close">×</span>
                <img id="modal-image" alt="Attachment preview"/>
            </div>
            {script}
        </body>
        </html>"""
    ).strip()


def _inline_cid_resources(html: str, message) -> str:
    cid_map: Dict[str, Tuple[str, str]] = {}
    for part in message.walk():
        if part.is_multipart():
            continue
        cid = part.get("Content-ID")
        if not cid:
            continue
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        cid_clean = cid.strip("<>")
        cid_map[cid_clean] = (
            part.get_content_type() or "application/octet-stream",
            base64.b64encode(payload).decode("utf-8"),
        )
    inlined = html
    for cid, (mime, b64) in cid_map.items():
        inlined = inlined.replace(
            f"cid:{cid}",
            f"data:{mime};base64,{b64}",
        )
    return inlined


def _extract_html_from_original(original_bytes: bytes) -> Optional[str]:
    try:
        message = BytesParser(policy=policy.default).parsebytes(original_bytes)
    except Exception:
        return None
    html = None
    charset = "utf-8"
    for part in message.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset("utf-8")
            try:
                html = payload.decode(charset, errors="replace")
            except Exception:
                html = payload.decode("utf-8", errors="replace")
            break
    if html:
        return _inline_cid_resources(html, message)
    return None


def _add_image_css_to_html(html_content: str) -> str:
    """Add CSS to HTML content to ensure images display correctly and are properly sized."""
    if not html_content:
        return html_content
    
    # CSS to constrain image sizes
    image_css = """
    <style>
        img {
            max-width: 100% !important;
            max-height: 400px !important;
            width: auto !important;
            height: auto !important;
            object-fit: contain !important;
            display: block !important;
            margin: 10px auto !important;
        }
        body {
            padding: 15px;
            font-family: Arial, sans-serif;
            line-height: 1.6;
        }
    </style>
    """
    
    # Try to inject CSS into the HTML
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Add CSS to head if it exists, otherwise create head
        if soup.head:
            soup.head.insert(0, BeautifulSoup(image_css, "html.parser"))
        elif soup.html:
            head_tag = soup.new_tag("head")
            head_tag.insert(0, BeautifulSoup(image_css, "html.parser"))
            soup.html.insert(0, head_tag)
        else:
            # No HTML structure, wrap in basic structure
            html_tag = soup.new_tag("html")
            head_tag = soup.new_tag("head")
            head_tag.insert(0, BeautifulSoup(image_css, "html.parser"))
            body_tag = soup.new_tag("body")
            # Move all existing content to body
            for element in soup.contents:
                body_tag.append(element)
            html_tag.append(head_tag)
            html_tag.append(body_tag)
            soup = BeautifulSoup(str(html_tag), "html.parser")
        
        return str(soup)
    except Exception:
        # If processing fails, prepend CSS to content
        return image_css + html_content


def _resolve_body_markup(email: InputEmail, original_bytes: Optional[bytes]) -> str:
    if original_bytes:
        extracted = _extract_html_from_original(original_bytes)
        if extracted:
            return _add_image_css_to_html(extracted)
    if email.body_html:
        return _add_image_css_to_html(email.body_html)
    fallback = email.body_html or "No message body available."
    return f"<pre>{escape(fallback)}</pre>"


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
        logger.warning("Failed to fetch knowledge columns for report: %s", exc)
        knowledge_columns = []
    
    original_map = _collect_original_email_bytes(cfg, emails)
    all_attachment_files: List[Tuple[str, bytes]] = []
    all_email_files: List[Tuple[str, bytes]] = []
    sections: List[str] = []
    payload_emails: List[Dict[str, object]] = []
    csv_text_rows: List[List[str]] = []
    csv_full_rows: List[List[str]] = []

    for email in emails:
        attachments_payload: List[Dict[str, object]] = []
        markup_attachments: List[Dict[str, str]] = []
        attachment_files: List[Tuple[str, bytes]] = []
        image_files: List[Tuple[str, bytes]] = []

        for attachment in email.attachments or []:
            path = Path(attachment.storage_path or "")
            if not path.exists():
                logger.warning("Attachment missing for email %s: %s", email.id, path)
                continue
            data = path.read_bytes()
            base64_payload = base64.b64encode(data).decode("utf-8")
            mime = attachment.file_type or "application/octet-stream"
            size_bytes = attachment.file_size_bytes or len(data)
            info = {
                "fileName": attachment.file_name or f"attachment_{attachment.id}",
                "mime": mime,
                "size": size_bytes,
                "sizeLabel": f"{size_bytes / 1024:.1f} KB",
                "base64": base64_payload,
                "isImage": mime.startswith("image"),
            }
            attachments_payload.append(info)
            markup_attachments.append(info)
            all_attachment_files.append(
                (
                    f"{email.subject_id or email.email_hash or email.id}/{attachment.file_name or attachment.id}",
                    data,
                )
            )
            attachment_files.append((info["fileName"], data))
            if info["isImage"]:
                image_files.append((info["fileName"], data))

        original_payload = None
        original_bytes: Optional[bytes] = None
        if email.email_hash and email.email_hash in original_map:
            original_name, original_bytes = original_map[email.email_hash]
            original_payload = {
                "fileName": original_name,
                "mime": "message/rfc822" if original_name.lower().endswith(".eml") else "application/vnd.ms-outlook",
                "base64": base64.b64encode(original_bytes).decode("utf-8"),
            }
            all_email_files.append((original_name, original_bytes))

        attachments_markup = _render_attachments(markup_attachments)
        body_markup = _resolve_body_markup(email, original_bytes)
        sections.append(_render_email_section(email, body_markup, attachments_markup, knowledge_columns))

        payload_emails.append(
            {
                "id": email.id,
                "subject": email.subject or "Untitled",
                "subjectId": email.subject_id or "",
                "sender": email.sender or "",
                "attachments": attachments_payload,
                "original": original_payload,
                "zipAttachments": base64.b64encode(_compress_to_zip(attachment_files)).decode("utf-8")
                if attachment_files
                else "",
                "zipImages": base64.b64encode(_compress_to_zip(image_files)).decode("utf-8")
                if image_files
                else "",
            }
        )

        csv_text_rows.append(
            [
                email.id,
                email.subject or "",
                email.sender or "",
                email.subject_id or "",
                email.email_hash or "",
                email.date_sent.isoformat() if email.date_sent else "",
                email.date_reported.isoformat() if email.date_reported else "",
                ";".join(_decode_json_list(email.url_parsed)),
                ";".join(_decode_json_list(email.callback_number_parsed)),
            ]
        )

        csv_full_rows.append(
            [
                email.id,
                email.subject or "",
                email.sender or "",
                email.subject_id or "",
                email.email_hash or "",
                email.date_sent.isoformat() if email.date_sent else "",
                email.date_reported.isoformat() if email.date_reported else "",
                base64.b64encode(original_bytes).decode("utf-8") if original_bytes else "",
                json.dumps(
                    [
                        {
                            "fileName": att["fileName"],
                            "mime": att["mime"],
                            "size": att["size"],
                            "base64": att["base64"],
                        }
                        for att in attachments_payload
                    ]
                ),
            ]
        )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    title = f"Email Report ({len(emails)} emails)"

    html_filename = f"email_report_{timestamp}.html"
    csv_text_filename = f"email_report_{timestamp}_text.csv"
    csv_full_filename = f"email_report_{timestamp}_full.csv"
    attachments_zip_filename = f"email_report_{timestamp}_attachments.zip"
    emails_zip_filename = f"email_report_{timestamp}_emails.zip"

    csv_text_buffer = io.StringIO()
    csv_text_writer = csv.writer(csv_text_buffer)
    csv_text_writer.writerow(
        [
            "Email ID",
            "Subject",
            "Sender",
            "Subject ID",
            "Email Hash",
            "Date Sent",
            "Date Reported",
            "URLs",
            "Callback Numbers",
        ]
    )
    csv_text_writer.writerows(csv_text_rows)
    csv_text_bytes = csv_text_buffer.getvalue().encode("utf-8")

    csv_full_buffer = io.StringIO()
    csv_full_writer = csv.writer(csv_full_buffer)
    csv_full_writer.writerow(
        [
            "Email ID",
            "Subject",
            "Sender",
            "Subject ID",
            "Email Hash",
            "Date Sent",
            "Date Reported",
            "Email Base64",
            "Attachments JSON",
        ]
    )
    csv_full_writer.writerows(csv_full_rows)
    csv_full_bytes = csv_full_buffer.getvalue().encode("utf-8")

    attachments_zip_path: Optional[Path] = None
    attachments_zip_base64 = ""
    if all_attachment_files:
        attachments_zip_bytes = _compress_to_zip(all_attachment_files)
        attachments_zip_base64 = base64.b64encode(attachments_zip_bytes).decode("utf-8")
        attachments_zip_path = reports_dir / attachments_zip_filename
        attachments_zip_path.write_bytes(attachments_zip_bytes)

    emails_zip_path: Optional[Path] = None
    emails_zip_base64 = ""
    if all_email_files:
        emails_zip_bytes = _compress_to_zip(all_email_files)
        emails_zip_base64 = base64.b64encode(emails_zip_bytes).decode("utf-8")
        emails_zip_path = reports_dir / emails_zip_filename
        emails_zip_path.write_bytes(emails_zip_bytes)

    payload = {
        "meta": {"title": title, "generatedAt": generated_at},
        "bundles": {
            "htmlBase64": "",
            "htmlName": html_filename,
            "csvText": base64.b64encode(csv_text_bytes).decode("utf-8"),
            "csvTextName": csv_text_filename,
            "csvFull": base64.b64encode(csv_full_bytes).decode("utf-8"),
            "csvFullName": csv_full_filename,
            "attachmentsZip": attachments_zip_base64,
            "attachmentsZipName": attachments_zip_filename,
            "emailsZip": emails_zip_base64,
            "emailsZipName": emails_zip_filename,
        },
        "emails": payload_emails,
    }

    html_document = _build_html_document(title, generated_at, "\n".join(sections), payload)
    payload["bundles"]["htmlBase64"] = base64.b64encode(html_document.encode("utf-8")).decode("utf-8")

    html_path = reports_dir / html_filename
    html_path.write_text(html_document, encoding="utf-8")

    csv_text_path = reports_dir / csv_text_filename
    csv_text_path.write_bytes(csv_text_bytes)

    csv_full_path = reports_dir / csv_full_filename
    csv_full_path.write_bytes(csv_full_bytes)

    logger.info("Generated report at %s", html_path)

    return ReportArtifacts(
        html_path=html_path,
        csv_text_path=csv_text_path,
        csv_full_path=csv_full_path,
        attachments_zip_path=attachments_zip_path,
        emails_zip_path=emails_zip_path,
    )

