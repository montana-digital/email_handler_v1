"""Tests for centralized JSON helper utilities."""

import pytest
from app.utils.json_helpers import (
    safe_json_loads,
    safe_json_loads_list,
    safe_json_dumps,
    safe_json_dumps_list,
    safe_json_dumps_or_none,
)


class TestSafeJsonLoads:
    """Test safe_json_loads function."""
    
    def test_valid_json_string(self):
        """Test loading valid JSON string."""
        result = safe_json_loads('{"key": "value"}')
        assert result == {"key": "value"}
    
    def test_valid_json_list(self):
        """Test loading valid JSON list."""
        result = safe_json_loads('["a", "b", "c"]')
        assert result == ["a", "b", "c"]
    
    def test_none_input(self):
        """Test handling None input."""
        result = safe_json_loads(None)
        assert result == []
    
    def test_empty_string(self):
        """Test handling empty string."""
        result = safe_json_loads("")
        assert result == []
    
    def test_invalid_json(self):
        """Test handling invalid JSON."""
        result = safe_json_loads("{invalid json}")
        assert result == []
    
    def test_custom_default(self):
        """Test custom default value."""
        result = safe_json_loads(None, default={})
        assert result == {}
    
    def test_none_default(self):
        """Test None as default."""
        result = safe_json_loads(None, default=None)
        assert result is None
    
    def test_default_returns_empty_list(self):
        """Test that default behavior returns empty list."""
        result = safe_json_loads(None)
        assert result == []


class TestSafeJsonLoadsList:
    """Test safe_json_loads_list function."""
    
    def test_valid_list(self):
        """Test loading valid JSON list."""
        result = safe_json_loads_list('["a", "b", "c"]')
        assert result == ["a", "b", "c"]
    
    def test_list_with_numbers(self):
        """Test list with numbers converted to strings."""
        result = safe_json_loads_list('[1, 2, 3]')
        assert result == ["1", "2", "3"]
    
    def test_list_filters_empty(self):
        """Test that empty values are filtered out."""
        result = safe_json_loads_list('["a", "", "b", null, "c"]')
        assert result == ["a", "b", "c"]
    
    def test_none_input(self):
        """Test handling None input."""
        result = safe_json_loads_list(None)
        assert result == []
    
    def test_empty_string(self):
        """Test handling empty string."""
        result = safe_json_loads_list("")
        assert result == []
    
    def test_invalid_json(self):
        """Test handling invalid JSON."""
        result = safe_json_loads_list("{invalid}")
        assert result == []
    
    def test_not_a_list(self):
        """Test handling JSON that's not a list."""
        result = safe_json_loads_list('{"key": "value"}')
        assert result == []
    
    def test_empty_list(self):
        """Test handling empty list."""
        result = safe_json_loads_list("[]")
        assert result == []


class TestSafeJsonDumps:
    """Test safe_json_dumps function."""
    
    def test_valid_dict(self):
        """Test dumping valid dictionary."""
        result = safe_json_dumps({"key": "value"})
        assert result == '{"key": "value"}'
    
    def test_valid_list(self):
        """Test dumping valid list."""
        result = safe_json_dumps(["a", "b", "c"])
        assert result == '["a", "b", "c"]'
    
    def test_invalid_type(self):
        """Test handling non-serializable type."""
        class Unserializable:
            pass
        
        result = safe_json_dumps(Unserializable())
        assert result == "[]"
    
    def test_custom_default(self):
        """Test custom default value."""
        class Unserializable:
            pass
        
        result = safe_json_dumps(Unserializable(), default="{}")
        assert result == "{}"


class TestSafeJsonDumpsList:
    """Test safe_json_dumps_list function."""
    
    def test_valid_list(self):
        """Test dumping valid list."""
        result = safe_json_dumps_list(["a", "b", "c"])
        assert result == '["a", "b", "c"]'
    
    def test_empty_list(self):
        """Test dumping empty list."""
        result = safe_json_dumps_list([])
        assert result == "[]"
    
    def test_list_with_numbers(self):
        """Test list with numbers."""
        result = safe_json_dumps_list(["1", "2", "3"])
        assert result == '["1", "2", "3"]'


class TestSafeJsonDumpsOrNone:
    """Test safe_json_dumps_or_none function."""
    
    def test_valid_list(self):
        """Test dumping valid list."""
        result = safe_json_dumps_or_none(["a", "b", "c"])
        assert result == '["a", "b", "c"]'
    
    def test_empty_list(self):
        """Test empty list returns None."""
        result = safe_json_dumps_or_none([])
        assert result is None
    
    def test_single_item(self):
        """Test list with single item."""
        result = safe_json_dumps_or_none(["a"])
        assert result == '["a"]'

