"""Parser4 - Phone number extraction utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Set

import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException


@dataclass(frozen=True)
class PhoneParseResult:
    original: str
    e164: str
    region_code: str | None


def extract_phone_numbers(text: str | None, default_region: str = "US") -> List[PhoneParseResult]:
    if not text:
        return []

    seen: Set[str] = set()
    results: List[PhoneParseResult] = []

    matcher = phonenumbers.PhoneNumberMatcher(text, default_region)
    for match in matcher:
        candidate = match.raw_string
        number = match.number
        try:
            e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        except NumberParseException:
            continue

        if e164 in seen:
            continue

        seen.add(e164)
        region_code = phonenumbers.region_code_for_number(number)
        results.append(PhoneParseResult(original=candidate, e164=e164, region_code=region_code))

    fallback_pattern = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
    for match in fallback_pattern.finditer(text):
        candidate = match.group()
        digits = re.sub(r"\D", "", candidate)
        if len(digits) == 10:
            e164 = f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            e164 = f"+{digits}"
        elif digits.startswith("+") and len(digits) > 1:
            e164 = digits
        else:
            continue
        if e164 in seen:
            continue
        seen.add(e164)
        results.append(PhoneParseResult(original=candidate, e164=e164, region_code=None))

    return results

