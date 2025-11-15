"""Parsers for email content and related assets."""

from .parser_email import (
    ParsedAttachment,
    ParsedEmail,
    ParsedStandardEmail,
    parse_email_file,
    parse_eml_bytes,
    parse_input_email,
    parse_msg_file,
    parse_standard_email,
)
from .parser_urls import URLParseResult, extract_urls
from .parser_phones import PhoneParseResult, extract_phone_numbers

__all__ = [
    "ParsedEmail",
    "ParsedStandardEmail",
    "ParsedAttachment",
    "parse_email_file",
    "parse_input_email",
    "parse_standard_email",
    "parse_eml_bytes",
    "parse_msg_file",
    "URLParseResult",
    "extract_urls",
    "PhoneParseResult",
    "extract_phone_numbers",
]

