"""Parser3 - URL extraction utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Set

import tldextract

# Pattern to match fanged URLs (hxxp://, hxxps://, example[.]com, example(.)com)
FANGED_URL_PATTERN = re.compile(
    r"(?P<url>(?:hxxps?://|hxxp://|ftp://|www\.)[^\s<>\"]+)",
    flags=re.IGNORECASE,
)

# Pattern for standard URLs
URL_PATTERN = re.compile(
    r"(?P<url>(?:https?://|ftp://|www\.)[^\s<>\"]+)",
    flags=re.IGNORECASE,
)

# Pattern to match fanged domains (example[.]com, example(.)com, example{.}com)
# This matches domains where dots are replaced with brackets
FANGED_DOMAIN_PATTERN = re.compile(
    r"(?P<domain>[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\[\.\]|\(\.\)|\{\.\}|\[dot\]|\(dot\)|\{dot\})[a-z]{2,}(?:(?:\[\.\]|\(\.\)|\{\.\}|\[dot\]|\(dot\)|\{dot\})[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class URLParseResult:
    original: str
    normalized: str
    domain: str


def _defang_url(url: str) -> str:
    """Convert fanged URLs back to normal format.
    
    Handles:
    - hxxp:// -> http://
    - hxxps:// -> https://
    - example[.]com -> example.com
    - example(.)com -> example.com
    - example{.}com -> example.com
    - example[dot]com -> example.com
    """
    # Replace fanged protocols
    url = re.sub(r"^hxxps?://", lambda m: m.group(0).replace("hxxp", "http"), url, flags=re.IGNORECASE)
    
    # Replace fanged dots in domain
    url = re.sub(r"\[\.\]", ".", url, flags=re.IGNORECASE)
    url = re.sub(r"\(\.\)", ".", url, flags=re.IGNORECASE)
    url = re.sub(r"\{\.\}", ".", url, flags=re.IGNORECASE)
    url = re.sub(r"\[dot\]", ".", url, flags=re.IGNORECASE)
    url = re.sub(r"\(dot\)", ".", url, flags=re.IGNORECASE)
    url = re.sub(r"\{dot\}", ".", url, flags=re.IGNORECASE)
    
    return url


def _normalize(url: str) -> str:
    """Normalize URL format."""
    # First defang if needed
    url = _defang_url(url)
    url = url.strip().rstrip(").,;\"'")
    if url.lower().startswith("www."):
        return f"https://{url}"
    return url


def _extract_domain(url: str) -> str:
    extracted = tldextract.extract(url)
    domain = extracted.top_domain_under_public_suffix or ""
    return domain.lower()


def extract_urls(text: str | None) -> List[URLParseResult]:
    """Extract URLs from text, including fanged URLs.
    
    Handles both standard URLs (http://, https://) and fanged URLs
    (hxxp://, hxxps://, example[.]com, etc.)
    """
    if not text:
        return []

    seen: Set[str] = set()
    results: List[URLParseResult] = []

    # First, extract standard URLs
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

    # Then, extract fanged URLs
    for match in FANGED_URL_PATTERN.finditer(text):
        raw_url = match.group("url")
        normalized = _normalize(raw_url)  # This will defang it
        domain = _extract_domain(normalized)
        if not domain:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(URLParseResult(original=raw_url, normalized=normalized, domain=domain))

    # Also look for standalone fanged domains (without protocol)
    for match in FANGED_DOMAIN_PATTERN.finditer(text):
        raw_domain = match.group("domain")
        # Defang the domain
        defanged = _defang_url(raw_domain)
        # Create a normalized URL
        normalized = f"https://{defanged}"
        domain = _extract_domain(normalized)
        if not domain:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(URLParseResult(original=raw_domain, normalized=normalized, domain=domain))

    return results

