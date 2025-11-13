"""Parsers for email content and related assets."""

from .parser_email import ParsedEmail, ParsedStandardEmail, ParsedAttachment, parse_email_file, parse_input_email, parse_standard_email
from .parser_urls import URLParseResult, extract_urls
from .parser_phones import PhoneParseResult, extract_phone_numbers

__all__ = [
    "ParsedEmail",
    "ParsedStandardEmail",
    "ParsedAttachment",
    "parse_email_file",
    "parse_input_email",
    "parse_standard_email",
    "URLParseResult",
    "extract_urls",
    "PhoneParseResult",
    "extract_phone_numbers",
]

