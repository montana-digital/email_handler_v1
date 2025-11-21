"""Error handling utilities for user-friendly error messages."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import DatabaseError, IntegrityError, OperationalError, SQLAlchemyError


def format_database_error(exc: Exception, operation: str = "database operation") -> str:
    """Convert database exceptions to user-friendly error messages.
    
    Args:
        exc: The exception that occurred
        operation: Description of the operation that failed
        
    Returns:
        User-friendly error message
    """
    exc_type = type(exc).__name__
    exc_str = str(exc)
    
    # Handle SQLAlchemy specific errors
    if isinstance(exc, IntegrityError):
        if "UNIQUE constraint" in exc_str or "unique constraint" in exc_str:
            if "email_hash" in exc_str:
                return f"Email already exists in database. This email has been processed before."
            elif "primary_key_value" in exc_str:
                return f"Record with this key already exists. The data may have been updated by another process."
            else:
                return f"Duplicate record detected. This record already exists in the database."
        elif "FOREIGN KEY constraint" in exc_str or "foreign key constraint" in exc_str:
            return f"Referenced record not found. Please ensure all related records exist before {operation}."
        elif "NOT NULL constraint" in exc_str or "not null constraint" in exc_str:
            return f"Required field is missing. Please provide all required information for {operation}."
        else:
            return f"Data integrity error during {operation}. The operation could not be completed due to data constraints."
    
    elif isinstance(exc, OperationalError):
        if "database is locked" in exc_str.lower() or "database lock" in exc_str.lower():
            return f"Database is currently locked. Another process may be using it. Please wait a moment and try again."
        elif "no such table" in exc_str.lower():
            return f"Database table not found. The database schema may need to be initialized."
        elif "unable to open database" in exc_str.lower() or "cannot open database" in exc_str.lower():
            return f"Cannot access database file. Check file permissions and ensure the database file exists."
        elif "disk i/o error" in exc_str.lower() or "i/o error" in exc_str.lower():
            return f"Database file access error. Check disk space and file permissions."
        else:
            return f"Database operation failed: {exc_str[:200]}"
    
    elif isinstance(exc, DatabaseError):
        return f"Database error during {operation}: {exc_str[:200]}"
    
    elif isinstance(exc, SQLAlchemyError):
        return f"Database error during {operation}: {exc_str[:200]}"
    
    # Handle generic Python exceptions
    elif exc_type == "PermissionError":
        return f"Permission denied accessing database. Check file permissions."
    elif exc_type == "FileNotFoundError":
        return f"Database file not found. The database may need to be initialized."
    elif exc_type == "OSError":
        if "WinError 5" in exc_str or "access is denied" in exc_str.lower():
            return f"Access denied to database file. Check file permissions or close programs using this file."
        elif "WinError 32" in exc_str or "being used by another process" in exc_str.lower():
            return f"Database file is in use by another program. Close it and try again."
        elif "No space left" in exc_str or "disk full" in exc_str.lower():
            return f"Disk is full. Free up space and try again."
        else:
            return f"System error accessing database: {exc_str[:200]}"
    else:
        # Generic fallback
        return f"An error occurred during {operation}: {exc_str[:200]}"


def format_validation_error(field: str, reason: str) -> str:
    """Format a validation error message.
    
    Args:
        field: The field that failed validation
        reason: Reason for validation failure
        
    Returns:
        User-friendly validation error message
    """
    return f"Invalid {field}: {reason}"


def format_connection_error(exc: Exception, database_url: Optional[str] = None) -> str:
    """Format database connection errors.
    
    Args:
        exc: The connection exception
        database_url: Optional database URL for context
        
    Returns:
        User-friendly connection error message
    """
    exc_str = str(exc)
    
    if "unable to open database" in exc_str.lower():
        if database_url and "sqlite" in database_url.lower():
            return "Cannot connect to SQLite database. Check that the database file exists and is accessible."
        return "Cannot connect to database. Check connection settings and file permissions."
    
    if "database is locked" in exc_str.lower():
        return "Database is locked by another process. Please wait and try again."
    
    if "no such file" in exc_str.lower() or "file not found" in exc_str.lower():
        return "Database file not found. The database may need to be initialized."
    
    return f"Database connection failed: {exc_str[:200]}"

