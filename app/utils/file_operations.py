"""Standardized file operation utilities with consistent error handling.

This module provides file operation functions with:
- Consistent error handling
- Atomic write operations
- Retry logic for transient failures
- User-friendly error messages
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from loguru import logger


class FileOperationError(Exception):
    """Base exception for file operation errors."""
    pass


class FileReadError(FileOperationError):
    """Raised when a file read operation fails."""
    pass


class FileWriteError(FileOperationError):
    """Raised when a file write operation fails."""
    pass


class FilePermissionError(FileOperationError):
    """Raised when file permission issues occur."""
    pass


def read_bytes_safe(file_path: Path, max_retries: int = 3) -> bytes:
    """Read file bytes with error handling and retry logic.
    
    Args:
        file_path: Path to file to read
        max_retries: Maximum number of retry attempts for transient failures
        
    Returns:
        File contents as bytes
        
    Raises:
        FileReadError: If file cannot be read after retries
        FilePermissionError: If permission denied
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return file_path.read_bytes()
        except PermissionError as exc:
            error_msg = f"Permission denied reading {file_path.name}. File may be locked by another process."
            logger.error(error_msg)
            raise FilePermissionError(error_msg) from exc
        except FileNotFoundError as exc:
            error_msg = f"File not found: {file_path.name}"
            logger.error(error_msg)
            raise FileReadError(error_msg) from exc
        except OSError as exc:
            last_exception = exc
            if attempt < max_retries - 1:
                logger.warning("Transient error reading %s (attempt %d/%d): %s", file_path.name, attempt + 1, max_retries, exc)
                continue
            else:
                error_msg = f"Failed to read {file_path.name} after {max_retries} attempts: {exc}"
                logger.error(error_msg)
                raise FileReadError(error_msg) from last_exception
        except Exception as exc:
            error_msg = f"Unexpected error reading {file_path.name}: {exc}"
            logger.error(error_msg)
            raise FileReadError(error_msg) from exc
    
    # Should not reach here, but satisfy type checker
    raise FileReadError(f"Failed to read {file_path.name}") from last_exception


def write_bytes_safe(file_path: Path, data: bytes, atomic: bool = True, max_retries: int = 3) -> None:
    """Write bytes to file with error handling, atomic writes, and retry logic.
    
    Args:
        file_path: Path to file to write
        data: Bytes to write
        atomic: If True, write to temporary file first then rename (atomic operation)
        max_retries: Maximum number of retry attempts for transient failures
        
    Raises:
        FileWriteError: If file cannot be written after retries
        FilePermissionError: If permission denied
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            if atomic:
                # Write to temporary file first, then rename for atomic operation
                temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
                try:
                    temp_path.write_bytes(data)
                    # Atomic rename - only succeeds if write was complete
                    temp_path.replace(file_path)
                    return
                except Exception as write_exc:
                    # Clean up temp file on error
                    if temp_path.exists():
                        try:
                            temp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    raise write_exc
            else:
                file_path.write_bytes(data)
                return
        except PermissionError as exc:
            error_msg = f"Permission denied writing {file_path.name}. File may be locked or access denied."
            logger.error(error_msg)
            raise FilePermissionError(error_msg) from exc
        except OSError as exc:
            last_exception = exc
            # Check for disk full
            if "No space left" in str(exc) or "disk full" in str(exc).lower():
                error_msg = f"Disk is full. Cannot write {file_path.name}"
                logger.error(error_msg)
                raise FileWriteError(error_msg) from exc
            # Check for path too long (Windows)
            if "WinError 3" in str(exc) or "path too long" in str(exc).lower():
                error_msg = f"Path too long for {file_path.name}. Maximum path length is 260 characters on Windows."
                logger.error(error_msg)
                raise FileWriteError(error_msg) from exc
            if attempt < max_retries - 1:
                logger.warning("Transient error writing %s (attempt %d/%d): %s", file_path.name, attempt + 1, max_retries, exc)
                continue
            else:
                error_msg = f"Failed to write {file_path.name} after {max_retries} attempts: {exc}"
                logger.error(error_msg)
                raise FileWriteError(error_msg) from last_exception
        except Exception as exc:
            error_msg = f"Unexpected error writing {file_path.name}: {exc}"
            logger.error(error_msg)
            raise FileWriteError(error_msg) from exc
    
    # Should not reach here, but satisfy type checker
    raise FileWriteError(f"Failed to write {file_path.name}") from last_exception


def write_text_safe(
    file_path: Path,
    text: str,
    encoding: str = "utf-8",
    atomic: bool = True,
    max_retries: int = 3,
) -> None:
    """Write text to file with error handling, atomic writes, and retry logic.
    
    Args:
        file_path: Path to file to write
        text: Text to write
        encoding: Text encoding (default: utf-8)
        atomic: If True, write to temporary file first then rename (atomic operation)
        max_retries: Maximum number of retry attempts for transient failures
        
    Raises:
        FileWriteError: If file cannot be written after retries
        FilePermissionError: If permission denied
    """
    try:
        data = text.encode(encoding)
        write_bytes_safe(file_path, data, atomic=atomic, max_retries=max_retries)
    except UnicodeEncodeError as exc:
        error_msg = f"Encoding error writing {file_path.name}: {exc}"
        logger.error(error_msg)
        raise FileWriteError(error_msg) from exc


def copy_file_safe(
    source: Path,
    destination: Path,
    create_parents: bool = True,
    max_retries: int = 3,
) -> None:
    """Copy file with error handling and retry logic.
    
    Args:
        source: Source file path
        destination: Destination file path
        create_parents: If True, create parent directories if they don't exist
        max_retries: Maximum number of retry attempts for transient failures
        
    Raises:
        FileReadError: If source file cannot be read
        FileWriteError: If destination file cannot be written
        FilePermissionError: If permission denied
    """
    if not source.exists():
        error_msg = f"Source file not found: {source.name}"
        logger.error(error_msg)
        raise FileReadError(error_msg)
    
    if create_parents:
        destination.parent.mkdir(parents=True, exist_ok=True)
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            shutil.copy2(source, destination)
            return
        except PermissionError as exc:
            error_msg = f"Permission denied copying {source.name} to {destination.name}"
            logger.error(error_msg)
            raise FilePermissionError(error_msg) from exc
        except OSError as exc:
            last_exception = exc
            if attempt < max_retries - 1:
                logger.warning("Transient error copying %s (attempt %d/%d): %s", source.name, attempt + 1, max_retries, exc)
                continue
            else:
                error_msg = f"Failed to copy {source.name} to {destination.name} after {max_retries} attempts: {exc}"
                logger.error(error_msg)
                raise FileWriteError(error_msg) from last_exception
        except Exception as exc:
            error_msg = f"Unexpected error copying {source.name} to {destination.name}: {exc}"
            logger.error(error_msg)
            raise FileWriteError(error_msg) from exc
    
    # Should not reach here, but satisfy type checker
    raise FileWriteError(f"Failed to copy {source.name} to {destination.name}") from last_exception


def move_file_safe(
    source: Path,
    destination: Path,
    create_parents: bool = True,
    max_retries: int = 3,
) -> None:
    """Move file with error handling and retry logic.
    
    Args:
        source: Source file path
        destination: Destination file path
        create_parents: If True, create parent directories if they don't exist
        max_retries: Maximum number of retry attempts for transient failures
        
    Raises:
        FileReadError: If source file cannot be read
        FileWriteError: If destination file cannot be written
        FilePermissionError: If permission denied
    """
    if not source.exists():
        error_msg = f"Source file not found: {source.name}"
        logger.error(error_msg)
        raise FileReadError(error_msg)
    
    if create_parents:
        destination.parent.mkdir(parents=True, exist_ok=True)
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            shutil.move(str(source), destination)
            return
        except PermissionError as exc:
            error_msg = f"Permission denied moving {source.name} to {destination.name}"
            logger.error(error_msg)
            raise FilePermissionError(error_msg) from exc
        except OSError as exc:
            last_exception = exc
            if attempt < max_retries - 1:
                logger.warning("Transient error moving %s (attempt %d/%d): %s", source.name, attempt + 1, max_retries, exc)
                continue
            else:
                error_msg = f"Failed to move {source.name} to {destination.name} after {max_retries} attempts: {exc}"
                logger.error(error_msg)
                raise FileWriteError(error_msg) from last_exception
        except Exception as exc:
            error_msg = f"Unexpected error moving {source.name} to {destination.name}: {exc}"
            logger.error(error_msg)
            raise FileWriteError(error_msg) from exc
    
    # Should not reach here, but satisfy type checker
    raise FileWriteError(f"Failed to move {source.name} to {destination.name}") from last_exception


def ensure_directory(path: Path, parents: bool = True) -> None:
    """Ensure directory exists, creating it if necessary.
    
    Args:
        path: Directory path to ensure
        parents: If True, create parent directories as needed
        
    Raises:
        FilePermissionError: If permission denied
        FileWriteError: If directory cannot be created
    """
    try:
        path.mkdir(parents=parents, exist_ok=True)
    except PermissionError as exc:
        error_msg = f"Permission denied creating directory {path}"
        logger.error(error_msg)
        raise FilePermissionError(error_msg) from exc
    except OSError as exc:
        error_msg = f"Failed to create directory {path}: {exc}"
        logger.error(error_msg)
        raise FileWriteError(error_msg) from exc

