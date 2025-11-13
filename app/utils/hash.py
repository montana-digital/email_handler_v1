"""Utility helpers for hashing content."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_digest(data: bytes) -> str:
    """Return the hexadecimal SHA-256 digest for the provided data."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file efficiently using SHA-256."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

