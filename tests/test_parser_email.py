from email.message import EmailMessage

from app.parsers.parser_email import parse_eml_bytes


def make_test_email() -> bytes:
    message = EmailMessage()
    message["From"] = "alerts@example.com"
    message["Subject"] = "Security Alert"
    message["Date"] = "Wed, 12 Nov 2025 19:54:38 -0000"
    body = """Subject: Alert-2025
Date Reported: 2025-11-12T19:54:38
Sending Source: https://phish.example.com/login
URL: https://malicious.example.com/verify
Callback Number: (888) 111-1111
Additional Contacts: helpdesk@example.com
Model Confidence: 0.92
"""
    message.set_content(body)
    return message.as_bytes()


def test_parse_eml_bytes_extracts_fields():
    data = make_test_email()
    parsed = parse_eml_bytes(data)
    assert parsed.sender == "alerts@example.com"
    assert parsed.subject_id == "Alert-2025"
    assert parsed.date_reported is not None
    assert parsed.urls_parsed == ["example.com"]
    assert "+18881111111" in parsed.callback_numbers_parsed
    assert parsed.model_confidence == 0.92

