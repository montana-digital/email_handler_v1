from __future__ import annotations

from app.parsers import parser_email


class _FakeAttachment:
    def __init__(self) -> None:
        self.longFilename = "evidence.txt"
        self.shortFilename = None
        self.mimeType = "text/plain"
        self.data = b"test"


class _FakeMsg:
    def __init__(self, path: str, html_body: str | None = None, text_body: str | None = None) -> None:
        self.sender = "alerts@example.com"
        self.sender_email = None
        self.to = "target@example.com"
        self.cc = "cc@example.com"
        self.subject = "MSG Subject"
        self.date = "Wed, 12 Nov 2025 19:54:38 -0000"
        self.message_id = "<msg-id>"
        # Use provided html_body, or default if not explicitly None
        if html_body is not None:
            self.htmlBody = html_body
        else:
            self.htmlBody = "<p>URL: https://msg.example.com/login</p>"
        # Use provided text_body, or default if not explicitly None
        if text_body is not None:
            self.body = text_body
        else:
            self.body = "Callback Number: (888) 111-1111"
        self.attachments = [_FakeAttachment()]


def test_parse_msg_file(monkeypatch, tmp_path):
    msg_path = tmp_path / "sample.msg"
    msg_path.write_bytes(b"msg content")

    monkeypatch.setattr(parser_email.extract_msg, "Message", lambda path: _FakeMsg(path))

    class _FakeUrl:
        def __init__(self) -> None:
            self.original = "https://msg.example.com/login"
            self.normalized = self.original
            self.domain = "msg.example.com"

    monkeypatch.setattr(parser_email, "extract_urls", lambda text: [_FakeUrl()] if text else [])

    parsed = parser_email.parse_msg_file(msg_path)

    assert parsed.sender == "alerts@example.com"
    assert parsed.subject == "MSG Subject"
    assert parsed.date_sent is not None
    assert parsed.urls_parsed == ["msg.example.com"]
    assert "+18881111111" in parsed.callback_numbers_parsed
    assert parsed.attachments
    assert parsed.attachments[0].file_name == "evidence.txt"


def test_parse_msg_with_html_table(monkeypatch, tmp_path):
    """Test MSG parsing with HTML table containing field data."""
    msg_path = tmp_path / "html_table.msg"
    msg_path.write_bytes(b"msg content")

    html_body = """
    <html>
    <body>
        <table>
            <tr>
                <td>Subject:</td>
                <td>Alert-2025</td>
            </tr>
            <tr>
                <td>Date Reported:</td>
                <td>2025-11-12T19:54:38</td>
            </tr>
            <tr>
                <td>Sending Source:</td>
                <td>888-111-1111</td>
            </tr>
            <tr>
                <td>URL:</td>
                <td>https://example.com/verify</td>
            </tr>
            <tr>
                <td>Callback Number:</td>
                <td>(555) 123-4567</td>
            </tr>
            <tr>
                <td>Model Confidence:</td>
                <td>0.95</td>
            </tr>
        </table>
    </body>
    </html>
    """

    monkeypatch.setattr(parser_email.extract_msg, "Message", lambda path: _FakeMsg(path, html_body=html_body, text_body=""))

    class _FakeUrl:
        def __init__(self, url: str) -> None:
            self.original = url
            self.normalized = url
            self.domain = "example.com"

    def _extract_urls(text: str | None) -> list:
        # Check both HTML and converted text for URLs
        if text and ("example.com" in text or "verify" in text):
            return [_FakeUrl("https://example.com/verify")]
        return []

    monkeypatch.setattr(parser_email, "extract_urls", _extract_urls)

    class _FakePhone:
        def __init__(self, number: str) -> None:
            self.e164 = number

    def _extract_phones(text: str | None) -> list:
        if text and "555" in text:
            return [_FakePhone("+15551234567")]
        return []

    monkeypatch.setattr(parser_email, "extract_phone_numbers", _extract_phones)

    parsed = parser_email.parse_msg_file(msg_path)

    # Verify fields were extracted from HTML table
    assert parsed.subject_id == "Alert-2025"
    assert parsed.date_reported is not None
    assert parsed.sending_source_raw == "888-111-1111"
    assert parsed.urls_parsed == ["example.com"]
    assert "+15551234567" in parsed.callback_numbers_parsed
    assert parsed.model_confidence == 0.95
    assert parsed.body_html is not None
    assert "table" in parsed.body_html.lower()


def test_parse_msg_with_html_only_body(monkeypatch, tmp_path):
    """Test MSG parsing when only HTML body is available (no text version)."""
    msg_path = tmp_path / "html_only.msg"
    msg_path.write_bytes(b"msg content")

    html_body = """
    <html>
    <body>
        <p>Subject: Test-Alert</p>
        <p>Date Reported: 2025-11-12T19:54:38</p>
        <p>Sending Source: https://phish.example.com</p>
    </body>
    </html>
    """

    monkeypatch.setattr(parser_email.extract_msg, "Message", lambda path: _FakeMsg(path, html_body=html_body, text_body=""))

    class _FakeUrl:
        def __init__(self) -> None:
            self.original = "https://phish.example.com"
            self.normalized = self.original
            self.domain = "phish.example.com"

    monkeypatch.setattr(parser_email, "extract_urls", lambda text: [_FakeUrl()] if text and "phish" in text else [])

    parsed = parser_email.parse_msg_file(msg_path)

    # Should extract fields from HTML
    assert parsed.subject_id == "Test-Alert"
    assert parsed.date_reported is not None
    assert parsed.sending_source_raw == "https://phish.example.com"
    assert parsed.body_html is not None
    # Should have converted HTML to text for body_text
    assert parsed.body_text is not None
    assert "Test-Alert" in parsed.body_text


def test_html_to_text_conversion():
    """Test HTML-to-text conversion function directly."""
    from app.parsers.parser_email import _html_to_text

    html_table = """
    <table>
        <tr>
            <td>Date Reported:</td>
            <td>2025-11-12T19:54:38</td>
        </tr>
        <tr>
            <td>Sending Source:</td>
            <td>888-111-1111</td>
        </tr>
    </table>
    """

    text = _html_to_text(html_table)

    assert text is not None
    assert "Date Reported: 2025-11-12T19:54:38" in text
    assert "Sending Source: 888-111-1111" in text
    # Should not contain HTML tags
    assert "<table>" not in text
    assert "<td>" not in text


def test_extract_body_fields_from_html():
    """Test that body fields can be extracted from HTML content."""
    from app.parsers.parser_email import _extract_body_fields

    html_content = """
    <html>
    <body>
        <p>Subject: Alert-2025</p>
        <p>Date Reported: 2025-11-12T19:54:38</p>
        <p>Model Confidence: 0.92</p>
    </body>
    </html>
    """

    fields = _extract_body_fields(html_content)

    assert fields.get("subject") == "Alert-2025"
    assert fields.get("date_reported") == "2025-11-12T19:54:38"
    assert fields.get("model_confidence") == "0.92"


def test_prettify_html_error_handling():
    """Test that prettify_html handles malformed HTML gracefully."""
    from app.parsers.parser_email import _prettify_html

    # Malformed HTML
    malformed = "<html><body><p>Unclosed tag<div>Content</body>"

    result = _prettify_html(malformed)

    # Should return something (either prettified or original)
    assert result is not None
    assert "Content" in result

