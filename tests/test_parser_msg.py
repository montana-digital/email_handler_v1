from __future__ import annotations

from app.parsers import parser_email


class _FakeAttachment:
    def __init__(self) -> None:
        self.longFilename = "evidence.txt"
        self.shortFilename = None
        self.mimeType = "text/plain"
        self.data = b"test"


class _FakeMsg:
    def __init__(self, path: str) -> None:
        self.sender = "alerts@example.com"
        self.sender_email = None
        self.to = "target@example.com"
        self.cc = "cc@example.com"
        self.subject = "MSG Subject"
        self.date = "Wed, 12 Nov 2025 19:54:38 -0000"
        self.message_id = "<msg-id>"
        self.htmlBody = "<p>URL: https://msg.example.com/login</p>"
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

