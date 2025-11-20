"""Windows-specific path validation and sanitization utilities."""

from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Optional

# Windows-invalid characters for file and directory names
WINDOWS_INVALID_CHARS = set('<>:"|?*')
# Windows reserved names (case-insensitive)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}
# Windows path length limit (260 characters for MAX_PATH, unless long path support enabled)
WINDOWS_MAX_PATH_LENGTH = 260


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system() == "Windows"


def validate_path_length(path: Path | str, max_length: Optional[int] = None) -> tuple[bool, Optional[str]]:
    """
    Validate that a path does not exceed Windows MAX_PATH limit.
    
    Args:
        path: Path to validate
        max_length: Maximum allowed length (defaults to WINDOWS_MAX_PATH_LENGTH on Windows)
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not is_windows():
        return True, None
    
    if max_length is None:
        max_length = WINDOWS_MAX_PATH_LENGTH
    
    path_str = str(path)
    if len(path_str) > max_length:
        return False, f"Path exceeds Windows {max_length}-character limit: {len(path_str)} characters"
    
    return True, None


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """
    Sanitize a filename by removing Windows-invalid characters.
    
    Args:
        name: Filename to sanitize
        replacement: Character to replace invalid characters with
    
    Returns:
        Sanitized filename
    """
    if not is_windows():
        return name
    
    # Remove invalid characters
    sanitized = "".join(c if c not in WINDOWS_INVALID_CHARS else replacement for c in name)
    
    # Remove trailing periods and spaces (Windows doesn't allow these)
    sanitized = sanitized.rstrip(". ")
    
    # Check for reserved names
    name_upper = sanitized.upper()
    if name_upper in WINDOWS_RESERVED_NAMES:
        sanitized = f"{replacement}{sanitized}{replacement}"
    
    return sanitized


def validate_path_characters(path: Path | str) -> tuple[bool, Optional[str]]:
    """
    Validate that a path does not contain Windows-invalid characters.
    
    Args:
        path: Path to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not is_windows():
        return True, None
    
    path_str = str(path)
    
    # Check for invalid characters in the path
    invalid_chars = [c for c in path_str if c in WINDOWS_INVALID_CHARS]
    if invalid_chars:
        unique_chars = ", ".join(f"'{c}'" for c in sorted(set(invalid_chars)))
        return False, f"Path contains Windows-invalid characters: {unique_chars}"
    
    # Check for reserved names in path components
    path_obj = Path(path)
    for part in path_obj.parts:
        # Extract filename without extension
        name_part = Path(part).stem
        if name_part.upper() in WINDOWS_RESERVED_NAMES:
            return False, f"Path contains Windows reserved name: {name_part}"
    
    return True, None


def validate_path(path: Path | str, check_length: bool = True, check_chars: bool = True) -> tuple[bool, Optional[str]]:
    """
    Comprehensive path validation for Windows compatibility.
    
    Args:
        path: Path to validate
        check_length: Whether to check path length
        check_chars: Whether to check for invalid characters
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not is_windows():
        return True, None
    
    if check_chars:
        is_valid, error = validate_path_characters(path)
        if not is_valid:
            return False, error
    
    if check_length:
        is_valid, error = validate_path_length(path)
        if not is_valid:
            return False, error
    
    return True, None


def resolve_path_safely(path_str: str, base_path: Optional[Path] = None) -> Path:
    """
    Safely resolve a path string, handling relative paths and Windows edge cases.
    
    Args:
        path_str: Path string to resolve
        base_path: Base path for resolving relative paths (defaults to current working directory)
    
    Returns:
        Resolved Path object
    """
    path = Path(path_str)
    
    # Handle relative paths
    if not path.is_absolute():
        if base_path is None:
            base_path = Path.cwd()
        path = (base_path / path).resolve()
    else:
        path = path.resolve()
    
    return path


def normalize_sqlite_path(database_url: str) -> str:
    """
    Normalize SQLite database URL for Windows compatibility.
    
    Converts Windows paths in sqlite:/// URLs to use forward slashes.
    
    Args:
        database_url: SQLite database URL
    
    Returns:
        Normalized database URL
    """
    if not database_url.startswith("sqlite:///"):
        return database_url
    
    # Extract the path part
    path_part = database_url[10:]  # Remove "sqlite:///"
    
    # Convert backslashes to forward slashes for SQLite URLs
    # SQLite URLs should use forward slashes even on Windows
    normalized = path_part.replace("\\", "/")
    
    # Handle Windows absolute paths (C:/path/to/db.db)
    if len(normalized) >= 2 and normalized[1] == ":":
        # Already has drive letter, ensure forward slashes
        return f"sqlite:///{normalized}"
    
    return f"sqlite:///{normalized}"

