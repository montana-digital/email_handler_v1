"""
Utility to generate sample .eml files for local testing.

Usage:
    python scripts/generate_test_emails.py
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

from PIL import Image

EMAIL_INPUT_DIR = Path("data/input")

EMAIL_TEMPLATES = [
    {
        "filename": "phish_alert_1.eml",
        "subject": "Security Alert – Action Required",
        "sender": "alerts@example.com",
        "recipients": ["analysis@example.com"],
        "cc": ["security@example.com", "audit@example.com"],
        "body": """Subject: Alert-2025-001
Date Reported: 2025-11-12T19:54:38+00:00
Sending Source: https://secure-login.example.net/review
URL: https://malicious-payments.example.org/re-auth
Callback Number: (888) 111-1111
Additional Contacts: helpdesk@example.com
Model Confidence: 0.97
Message-ID: <ALERT-2025-001@example.com>

Dear team,

Please review the attached HTML snapshot and confirm whether the user provided credentials. The login domain looks suspicious.

Thanks,
Security Ops
""",
        "attachment": {
            "filename": "login_snapshot.html",
            "content": b"<html><body><h1>Fake Login</h1></body></html>",
            "maintype": "text",
            "subtype": "html",
        },
    },
    {
        "filename": "phish_alert_2.eml",
        "subject": "Suspicious Callback Request",
        "sender": "soc@example.com",
        "recipients": ["triage@example.com"],
        "cc": [],
        "body": """Subject: Callback-Request-339
Date Reported: 2025-11-13T02:15:09+00:00
Sending Source: https://voice.example.org/call
URL: https://example-phish.biz/voice
Callback Number: +1 202-555-0199
Additional Contacts: voiceops@example.com
Model Confidence: 0.84
Message-ID: <CALLBACK-339@example.com>

Analyst note:
User reported an unexpected voicemail with callback instructions. No attachment provided.

""",
        "attachment": None,
    },
    {
        "filename": "standard_reference.eml",
        "subject": "Monthly KPI Report",
        "sender": "reports@example.com",
        "recipients": ["analysis@example.com"],
        "cc": ["finance@example.com"],
        "body": """Team,

Attached is this month’s KPI dashboard. Please archive in Standard_Emails if no anomalies are found.

Thanks,
Reporting Bot
""",
        "attachment": None,
    },
    {
        "filename": "image_alert.eml",
        "subject": "Suspicious Image Detected",
        "sender": "vision@example.com",
        "recipients": ["analysis@example.com"],
        "cc": [],
        "body": """Subject: Image-Alert-512
Date Reported: 2025-11-14T08:22:01+00:00
Sending Source: https://cdn.example.net/assets
URL: https://phish-media.example.com/img
Callback Number: 888-222-3333
Additional Contacts: imaging@example.com
Model Confidence: 0.78
Message-ID: <IMAGE-ALERT-512@example.com>

Inline evidence:
data:image/png;base64,{inline_b64}

The attached PNG contains the login prompt screenshot supplied by the user.
""",
        "attachment": {
            "filename": "evidence.png",
            "content": None,  # Filled at runtime
            "maintype": "image",
            "subtype": "png",
        },
    },
]


def build_sample_png(size=(200, 100), color="#FF5733") -> bytes:
    image = Image.new("RGB", size, color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_message(template: dict) -> EmailMessage:
    message = EmailMessage()
    message["From"] = template["sender"]
    message["To"] = ", ".join(template["recipients"])
    if template["cc"]:
        message["Cc"] = ", ".join(template["cc"])
    message["Subject"] = template["subject"]
    message["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    message.set_content(template["body"])

    attachment = template["attachment"]
    if attachment:
        content = attachment["content"]
        if content is None and attachment["subtype"] == "png":
            content = build_sample_png()
        attachment_bytes = content or b""
        message.add_attachment(
            attachment_bytes,
            maintype=attachment["maintype"],
            subtype=attachment["subtype"],
            filename=attachment["filename"],
        )
    return message


def main() -> None:
    EMAIL_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    for template in EMAIL_TEMPLATES:
        inline_b64 = ""
        if "{inline_b64}" in template["body"]:
            inline_b64 = base64.b64encode(build_sample_png(size=(120, 120), color="#3366FF")).decode(
                "utf-8"
            )
            template = {**template, "body": template["body"].format(inline_b64=inline_b64)}
        message = build_message(template)
        destination = EMAIL_INPUT_DIR / template["filename"]
        destination.write_bytes(message.as_bytes())
        print(f"Created {destination}")


if __name__ == "__main__":
    main()

