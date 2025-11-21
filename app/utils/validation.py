"""Input validation functions for database operations."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def validate_email_id(email_id: Optional[int]) -> tuple[bool, Optional[str]]:
    """Validate an email ID.
    
    Args:
        email_id: The email ID to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if email_id is None:
        return False, "Email ID is required"
    
    if not isinstance(email_id, int):
        return False, f"Email ID must be an integer, got {type(email_id).__name__}"
    
    if email_id <= 0:
        return False, "Email ID must be a positive integer"
    
    return True, None


def validate_batch_id(batch_id: Optional[int]) -> tuple[bool, Optional[str]]:
    """Validate a batch ID.
    
    Args:
        batch_id: The batch ID to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if batch_id is None:
        return False, "Batch ID is required"
    
    if not isinstance(batch_id, int):
        return False, f"Batch ID must be an integer, got {type(batch_id).__name__}"
    
    if batch_id <= 0:
        return False, "Batch ID must be a positive integer"
    
    return True, None


def validate_table_name(table_name: Optional[str]) -> tuple[bool, Optional[str]]:
    """Validate a database table name.
    
    Args:
        table_name: The table name to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not table_name:
        return False, "Table name is required"
    
    if not isinstance(table_name, str):
        return False, f"Table name must be a string, got {type(table_name).__name__}"
    
    # Basic SQL injection prevention - only allow alphanumeric and underscore
    if not table_name.replace("_", "").isalnum():
        return False, "Table name contains invalid characters. Only letters, numbers, and underscores are allowed."
    
    # Prevent SQL keywords that could be dangerous
    dangerous_keywords = ["drop", "delete", "truncate", "alter", "create", "insert", "update"]
    if table_name.lower() in dangerous_keywords:
        return False, f"Table name cannot be a SQL keyword: {table_name}"
    
    return True, None


def validate_file_path(file_path: Optional[Path | str], must_exist: bool = False) -> tuple[bool, Optional[str]]:
    """Validate a file path.
    
    Args:
        file_path: The file path to validate
        must_exist: Whether the file must exist
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not file_path:
        return False, "File path is required"
    
    try:
        path = Path(file_path) if isinstance(file_path, str) else file_path
    except Exception as exc:
        return False, f"Invalid file path: {exc}"
    
    if must_exist and not path.exists():
        return False, f"File does not exist: {path}"
    
    # Check for path traversal attempts
    try:
        path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return False, "File path is outside the allowed directory"
    
    return True, None


def validate_email_hash(email_hash: Optional[str]) -> tuple[bool, Optional[str]]:
    """Validate an email hash.
    
    Args:
        email_hash: The email hash to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not email_hash:
        return False, "Email hash is required"
    
    if not isinstance(email_hash, str):
        return False, f"Email hash must be a string, got {type(email_hash).__name__}"
    
    # SHA256 hashes are 64 hex characters
    if len(email_hash) != 64:
        return False, f"Email hash must be 64 characters (SHA256), got {len(email_hash)}"
    
    try:
        int(email_hash, 16)  # Verify it's valid hex
    except ValueError:
        return False, "Email hash must be a valid hexadecimal string"
    
    return True, None


def validate_limit(limit: Optional[int], min_value: int = 1, max_value: int = 10000) -> tuple[bool, Optional[str]]:
    """Validate a limit parameter.
    
    Args:
        limit: The limit value to validate
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if limit is None:
        return True, None  # None is allowed for "no limit"
    
    if not isinstance(limit, int):
        return False, f"Limit must be an integer, got {type(limit).__name__}"
    
    if limit < min_value:
        return False, f"Limit must be at least {min_value}, got {limit}"
    
    if limit > max_value:
        return False, f"Limit must be at most {max_value}, got {limit}"
    
    return True, None

