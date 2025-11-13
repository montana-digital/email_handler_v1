"""Parser3 - URL extraction utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Set

import tldextract

URL_PATTERN = re.compile(
    r"(?P<url>(?:https?://|ftp://|www\.)[^\s<>\"]+)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class URLParseResult:
    original: str
    normalized: str
    domain: str


def _normalize(url: str) -> str:
    url = url.strip().rstrip(").,;\"'")
    if url.lower().startswith("www."):
        return f"https://{url}"
    return url


def _extract_domain(url: str) -> str:
    extracted = tldextract.extract(url)
    domain = extracted.top_domain_under_public_suffix or ""
    return domain.lower()


def extract_urls(text: str | None) -> List[URLParseResult]:
    if not text:
        return []

    seen: Set[str] = set()
    results: List[URLParseResult] = []

    for match in URL_PATTERN.finditer(text):
        raw_url = match.group("url")
        normalized = _normalize(raw_url)
        domain = _extract_domain(normalized)
        if not domain:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(URLParseResult(original=raw_url, normalized=normalized, domain=domain))

    return results

