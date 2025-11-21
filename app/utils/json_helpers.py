"""Centralized JSON serialization/deserialization utilities with consistent error handling."""

from __future__ import annotations

import json
from typing import Any, List, Optional

from loguru import logger


def safe_json_loads(text: Optional[str], default: Any = ...) -> Any:
    """Safely load JSON with consistent error handling.
    
    Args:
        text: JSON string to parse, or None/empty string
        default: Default value to return on error. If not provided, returns empty list.
                 Use default=None to explicitly return None.
        
    Returns:
        Parsed JSON value, or default/empty list on error
    """
    if not text:
        if default is ...:
            return []
        return default
    
    try:
        parsed = json.loads(text)
        return parsed
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse JSON (JSONDecodeError): %s", exc)
        if default is ...:
            return []
        return default
    except (TypeError, ValueError) as exc:
        logger.warning("Failed to parse JSON (TypeError/ValueError): %s", exc)
        if default is ...:
            return []
        return default
    except Exception as exc:
        logger.warning("Unexpected error parsing JSON: %s", exc)
        if default is ...:
            return []
        return default


def safe_json_loads_list(text: Optional[str]) -> List[str]:
    """Safely load JSON list, ensuring result is a list of strings.
    
    Args:
        text: JSON string containing a list
        
    Returns:
        List of strings, empty list on error or if not a list
    """
    parsed = safe_json_loads(text, default=[])
    
    if not isinstance(parsed, list):
        logger.warning("JSON value is not a list, returning empty list")
        return []
    
    # Convert all items to strings and filter out empty values
    result = [str(item) for item in parsed if item]
    return result


def safe_json_dumps(value: Any, default: str = "[]") -> str:
    """Safely dump value to JSON string with consistent error handling.
    
    Args:
        value: Value to serialize to JSON
        default: Default string to return on error
        
    Returns:
        JSON string representation, or default on error
    """
    try:
        return json.dumps(value)
    except (TypeError, ValueError) as exc:
        logger.warning("Failed to serialize to JSON: %s", exc)
        return default
    except Exception as exc:
        logger.warning("Unexpected error serializing to JSON: %s", exc)
        return default


def safe_json_dumps_list(values: List[str]) -> str:
    """Safely dump list of strings to JSON.
    
    Args:
        values: List of strings to serialize
        
    Returns:
        JSON string representation of the list, or "[]" on error
    """
    if not values:
        return "[]"
    
    return safe_json_dumps(values, default="[]")


def safe_json_dumps_or_none(values: List[str]) -> Optional[str]:
    """Safely dump list to JSON, returning None for empty lists.
    
    Args:
        values: List of strings to serialize
        
    Returns:
        JSON string if list has items, None if empty, or "[]" on error
    """
    if not values:
        return None
    
    result = safe_json_dumps(values, default="[]")
    return result if result != "[]" else None

