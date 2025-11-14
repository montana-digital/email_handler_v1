"""
Dataset generator for Email Handler automated testing.

Usage:
    python scripts/generate_test_dataset.py \
        --output-root tests/data \
        --email-count 240 \
        --seed 123

Outputs:
- <output>/emails/*.eml
- <output>/scripts/*.ps1 (sample PowerShell scripts + manifest)
- summary.json (basic manifest)

The generator purposely introduces:
- Mixed subject patterns (60% External Info - TEAM variants)
- Duplicated emails (hash collision testing)
- Missing / malformed metadata fields
- Multi-part bodies with URLs, phone numbers, contacts
- Attachments of varied MIME types and sizes (including large 5MB files)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import string
import textwrap
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ATTACHMENT_TYPES: List[Tuple[str, str, str]] = [
    ("image/png", "png", "PNG"),
    ("image/jpeg", "jpg", "JPEG"),
    ("text/html", "html", "HTML"),
    ("text/csv", "csv", "CSV"),
    ("text/plain", "txt", "TXT"),
    ("application/pdf", "pdf", "PDF"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx", "DOCX"),
    ("application/zip", "zip", "ZIP"),
    ("message/rfc822", "msg", "MSG"),
]

EXTERNAL_VARIANTS = [
    "External Info - TEAM",
    "External info - Team",
    "external info - team",
    "External Info - TEAM ",
    "External Info  -  TEAM",
]

SAMPLE_SCRIPTS: Dict[str, str] = {
    "noop.ps1": textwrap.dedent(
        """
        param([string]$Message = "noop")
        Write-Host "Starting NOOP script with message: $Message"
        Start-Sleep -Seconds 1
        Write-Host "Finished NOOP script."
        """
    ).strip(),
    "bulk_copy.ps1": textwrap.dedent(
        """
        param(
            [string]$Source = ".\\tests\\data\\emails",
            [string]$Destination = ".\\data\\input",
            [int]$Count = 50
        )
        Write-Host "Copying $Count emails from $Source to $Destination"
        $files = Get-ChildItem -Path $Source -Filter *.eml | Sort-Object {Get-Random}
        $files | Select-Object -First $Count | ForEach-Object {
            Copy-Item $_.FullName -Destination (Join-Path $Destination $_.Name) -Force
        }
        Write-Host "Copy complete."
        """
    ).strip(),
    "log_env.ps1": textwrap.dedent(
        """
        Write-Host "Environment snapshot:"
        Get-ChildItem Env: | Sort-Object Name | ForEach-Object {
            Write-Host "$($_.Name) = $($_.Value)"
        }
        """
    ).strip(),
    "slow_script.ps1": textwrap.dedent(
        """
        param([int]$DelaySeconds = 10)
        Write-Host "Simulating long-running script..."
        Start-Sleep -Seconds $DelaySeconds
        Write-Host "Slow script finished."
        """
    ).strip(),
}

SCRIPT_MANIFEST = {
    "noop.ps1": {
        "displayName": "No-Op Script",
        "description": "Simple script that logs a start/end message.",
        "defaultArgs": "-Message \"Test Run\"",
        "workingDirectory": "%PROJECT_ROOT%",
        "requiresConfirmation": False,
    },
    "bulk_copy.ps1": {
        "displayName": "Bulk Copy Emails",
        "description": "Copies a subset of generated emails into the app input directory.",
        "defaultArgs": "-Source \"%PROJECT_ROOT%\\\\tests\\\\data\\\\emails\" -Destination \"%INPUT_DIR%\" -Count 75",
        "workingDirectory": "%PROJECT_ROOT%",
        "requiresConfirmation": True,
    },
    "log_env.ps1": {
        "displayName": "Log Environment Variables",
        "description": "Writes environment variables to stdout for diagnostic capture.",
        "defaultArgs": "",
        "workingDirectory": "%PROJECT_ROOT%",
        "requiresConfirmation": False,
    },
    "slow_script.ps1": {
        "displayName": "Slow Script",
        "description": "Simulates a long-running process to test timeout handling.",
        "defaultArgs": "-DelaySeconds 12",
        "workingDirectory": "%PROJECT_ROOT%",
        "requiresConfirmation": True,
    },
}


def random_datetime(rng: random.Random, days_back: int = 30) -> datetime:
    base = datetime.now(timezone.utc) - timedelta(days=rng.randint(0, days_back))
    offset = timedelta(minutes=rng.randint(0, 1440))
    return base - offset


def random_phone_number(rng: random.Random) -> str:
    return f"+1{rng.randint(2000000000, 9999999999)}"


def random_domain(rng: random.Random) -> str:
    tlds = ["com", "net", "org", "io", "co"]
    name = "".join(rng.choice(string.ascii_lowercase) for _ in range(8))
    return f"{name}.{rng.choice(tlds)}"


def build_email_body(rng: random.Random, subject_id: str | None, include_fields: Dict[str, bool]) -> str:
    reported = random_datetime(rng)
    sending_source = f"https://{random_domain(rng)}/login"
    url_1 = f"http://{random_domain(rng)}/verify"
    callback = random_phone_number(rng)
    additional_contact = f"security-team@{random_domain(rng)}"
    body = textwrap.dedent(
        f"""
        Subject: {subject_id or 'N/A'}
        Date Reported: {reported.isoformat()}
        Sending Source: {sending_source}
        URL: {url_1}
        Callback Number: {callback}
        Additional Contacts: {additional_contact}
        Model Confidence: {rng.uniform(0.25, 0.99):0.2f}
        Message-ID: <{rng.randint(1, 999999)}-{random_domain(rng)}>

        Dear team,

        This is an automated notification regarding suspicious activity observed in recent reports. Please review the attached evidence and confirm remediation steps.

        Regards,
        Automated Watchdog
        """
    ).strip()

    lines = body.splitlines()
    if not include_fields.get("subject", True):
        lines = [line for line in lines if not line.startswith("Subject:")]
    if not include_fields.get("date_reported", True):
        lines = [line for line in lines if not line.startswith("Date Reported:")]
    if not include_fields.get("sending_source", True):
        lines = [line for line in lines if not line.startswith("Sending Source:")]
    if not include_fields.get("url", True):
        lines = [line for line in lines if not line.startswith("URL:")]
    if not include_fields.get("callback", True):
        lines = [line for line in lines if not line.startswith("Callback Number:")]
    if not include_fields.get("additional_contacts", True):
        lines = [line for line in lines if not line.startswith("Additional Contacts:")]
    if not include_fields.get("confidence", True):
        lines = [line for line in lines if not line.startswith("Model Confidence:")]
    if not include_fields.get("message_id", True):
        lines = [line for line in lines if not line.startswith("Message-ID:")]

    return "\n".join(lines)


def generate_attachment(rng: random.Random, kind: Tuple[str, str, str], large: bool = False) -> Tuple[str, bytes]:
    mime, ext, label = kind
    if mime.startswith("image/"):
        payload = os.urandom(4096)  # placeholder binary content
    elif mime == "application/pdf":
        payload = textwrap.dedent(
            """
            %PDF-1.4
            1 0 obj << /Type /Catalog /Pages 2 0 R >>
            endobj
            2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >>
            endobj
            3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
            endobj
            %%EOF
            """
        ).encode("utf-8")
    elif mime == "application/zip":
        payload = os.urandom(2048)
    elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        payload = os.urandom(4096)
    elif mime == "message/rfc822":
        payload = textwrap.dedent(
            f"""
            From: nested@example.com
            To: analyst@example.com
            Subject: Nested Alert
            Date: {format_datetime(datetime.now(timezone.utc))}

            This is a nested message used for testing attachments.
            """
        ).encode("utf-8")
    else:
        payload = textwrap.dedent(
            f"""
            Column,Value
            label,{label}
            random,{rng.randint(1, 1_000_000)}
            """
        ).encode("utf-8")

    if large:
        payload = os.urandom(5 * 1024 * 1024)

    name = f"attachment_{rng.randint(1000, 9999)}.{ext}"
    return name, payload


def build_email(
    rng: random.Random,
    index: int,
    subject_variant: bool,
) -> EmailMessage:
    msg = EmailMessage()

    is_external = subject_variant or rng.random() < 0.6
    subject_base = rng.choice(EXTERNAL_VARIANTS) if is_external else f"Security Alert #{rng.randint(1000, 99999)}"
    decorated = subject_base
    if rng.random() < 0.2:
        decorated += f" [{rng.choice(['URGENT', 'ACTION REQUIRED', 'FYI'])}]"

    msg["Subject"] = decorated
    msg["From"] = f"alerts+{rng.randint(100, 999)}@{random_domain(rng)}"
    msg["To"] = f"user{rng.randint(1, 200)}@example.com"
    msg["Cc"] = f"manager{rng.randint(1, 20)}@example.com" if rng.random() < 0.3 else ""
    msg["Date"] = format_datetime(random_datetime(rng))
    msg["Message-ID"] = make_msgid()

    subject_id = f"{datetime.now():%Y%m%dT%H%M%S}-{rng.randint(10, 99)}"

    include_fields = {
        "subject": rng.random() > 0.05,
        "date_reported": rng.random() > 0.04,
        "sending_source": True,
        "url": True,
        "callback": rng.random() > 0.02,
        "additional_contacts": rng.random() > 0.03,
        "confidence": True,
        "message_id": rng.random() > 0.05,
    }

    body = build_email_body(rng, subject_id if include_fields["subject"] else None, include_fields)
    msg.set_content(body)

    attachment_count = rng.randint(0, 3)
    for i in range(attachment_count):
        kind = rng.choice(ATTACHMENT_TYPES)
        large = (i == 0) and (rng.random() < 0.05)
        name, payload = generate_attachment(rng, kind, large=large)
        maintype, subtype = kind[0].split("/", 1)
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=name)

    return msg


def create_dataset(
    output_root: Path,
    email_count: int,
    seed: int,
) -> None:
    rng = random.Random(seed)

    emails_dir = output_root / "emails"
    scripts_dir = output_root / "scripts"
    attachments_dir = output_root / "attachments"  # reserved placeholder

    if emails_dir.exists():
        shutil.rmtree(emails_dir)
    if scripts_dir.exists():
        shutil.rmtree(scripts_dir)
    attachments_dir.mkdir(parents=True, exist_ok=True)
    emails_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    summary_entries = []

    for idx in range(email_count):
        subject_variant = idx % 2 == 0 and idx % 3 != 0
        msg = build_email(rng, idx, subject_variant)

        filename = f"email_{idx:04d}.eml"
        file_path = emails_dir / filename
        with file_path.open("wb") as fh:
            fh.write(msg.as_bytes())

        summary_entries.append(
            {
                "file": filename,
                "subject": msg["Subject"],
                "from": msg["From"],
                "has_attachments": any(True for _ in msg.iter_attachments()),
            }
        )

    for script_name, contents in SAMPLE_SCRIPTS.items():
        script_path = scripts_dir / script_name
        script_path.write_text(contents, encoding="utf-8")

    manifest_path = scripts_dir / "manifest.json"
    manifest_path.write_text(json.dumps(SCRIPT_MANIFEST, indent=2), encoding="utf-8")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "email_count": email_count,
        "emails": summary_entries[:50],  # preview; avoid massive file
    }

    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Generated {email_count} emails in {emails_dir}")
    print(f"Sample scripts written to {scripts_dir}")
    print(f"Summary manifest: {summary_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate stress dataset for Email Handler testing.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("tests/data"),
        help="Root directory for generated dataset (default: tests/data)",
    )
    parser.add_argument(
        "--email-count",
        type=int,
        default=240,
        help="Number of email files to generate (default: 240)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=2025,
        help="Random seed for reproducibility (default: 2025)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    create_dataset(args.output_root, args.email_count, args.seed)


if __name__ == "__main__":
    main()

