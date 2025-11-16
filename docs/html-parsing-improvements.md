# HTML Parsing Improvements for MSG Files

**Date:** 2025-01-27  
**Issue:** Parser fails when MSG files contain HTML tables or non-text bodies

---

## Problem Identified

When MSG files contain HTML bodies (especially HTML tables), the parser was failing because:

1. **No HTML-to-text conversion**: MSG parser didn't convert HTML to text before extracting body fields
2. **Regex pattern mismatch**: `_extract_body_fields()` expected plain text with "Field: Value" format, but HTML tables don't match this pattern
3. **No error handling**: BeautifulSoup operations could fail on malformed HTML without fallbacks
4. **Table structure ignored**: HTML tables with data in `<td>` cells weren't being converted to extractable format

---

## Solutions Implemented

### 1. HTML-to-Text Conversion Function

Added `_html_to_text()` function that:
- Converts HTML content to plain text using BeautifulSoup
- **Special handling for HTML tables**: Converts two-column table rows to "Label: Value" format
  - Example: `<tr><td>Date Reported:</td><td>2025-11-12</td></tr>` → `Date Reported: 2025-11-12`
- Removes script and style elements
- Has fallback to regex-based tag stripping if BeautifulSoup fails
- Normalizes whitespace

### 2. Enhanced Body Fields Extraction

Updated `_extract_body_fields()` to:
- Automatically detect HTML content (checks if text starts with `<`)
- Convert HTML to text before field extraction
- Handle multi-line field values
- Strip and normalize whitespace in extracted values

### 3. Improved MSG Parsing

Modified `parse_msg_file()` to:
- Convert HTML body to text for field extraction when only HTML is available
- Use converted text for `_extract_body_fields()` while preserving original HTML for display
- Ensure field extraction works with both plain text and HTML content

### 4. Error Handling for BeautifulSoup

Added `_prettify_html()` function with:
- Try/except around BeautifulSoup operations
- Fallback to original HTML if prettify fails
- Applied to both EML and MSG parsing paths

### 5. Enhanced Regex Pattern

Updated `BODY_FIELD_PATTERN` to:
- Handle multi-line field values using lookahead
- Support values that span multiple lines
- Match until next field or end of string

---

## Code Changes

### New Functions

1. **`_html_to_text(html_content)`**
   - Converts HTML to plain text
   - Special table handling
   - Error handling with fallback

2. **`_prettify_html(html_content)`**
   - Safely prettifies HTML
   - Returns original if prettify fails

### Modified Functions

1. **`_extract_body_fields(body_text)`**
   - Now detects and converts HTML automatically
   - Handles multi-line values
   - Better whitespace normalization

2. **`parse_msg_file(path)`**
   - Converts HTML to text for field extraction
   - Preserves original HTML for display

3. **`_collect_body_text(message)`**
   - Added error handling for BeautifulSoup
   - Fallback to regex tag stripping

---

## Testing Recommendations

### Test Cases to Add

1. **MSG file with HTML table**
   ```html
   <table>
     <tr><td>Date Reported:</td><td>2025-11-12T19:54:38</td></tr>
     <tr><td>Sending Source:</td><td>888-111-1111</td></tr>
   </table>
   ```
   - Should extract: `date_reported`, `sending_source`

2. **MSG file with malformed HTML**
   - Should not crash, should use fallback parsing

3. **MSG file with HTML-only body (no text version)**
   - Should convert HTML to text and extract fields

4. **MSG file with complex HTML structure**
   - Should handle nested tables, divs, etc.

---

## Fallback Strategy

The parser now has multiple fallback layers:

1. **Primary**: BeautifulSoup HTML parsing with table conversion
2. **Fallback 1**: Simple regex tag stripping if BeautifulSoup fails
3. **Fallback 2**: Use original HTML if all conversions fail (fields may be empty but email still processes)

---

## Impact

✅ **Before**: MSG files with HTML tables would fail to extract body fields  
✅ **After**: HTML tables are converted to "Label: Value" format and fields are extracted correctly

✅ **Before**: Malformed HTML could crash the parser  
✅ **After**: Multiple fallback layers ensure parsing continues

✅ **Before**: HTML-only bodies couldn't be processed for field extraction  
✅ **After**: HTML is automatically converted to text for field extraction

---

## Compatibility

- ✅ Backward compatible with plain text emails
- ✅ Works with existing EML parsing (already had HTML-to-text)
- ✅ No breaking changes to API
- ✅ All existing tests should still pass

---

## Files Modified

- `app/parsers/parser_email.py`
  - Added `_html_to_text()` function
  - Added `_prettify_html()` function
  - Enhanced `_extract_body_fields()` function
  - Modified `parse_msg_file()` function
  - Updated `_collect_body_text()` function
  - Improved `BODY_FIELD_PATTERN` regex

---

## Next Steps

1. Test with real MSG files containing HTML tables
2. Add unit tests for HTML table parsing
3. Monitor logs for any HTML parsing failures
4. Consider adding HTML table detection to parser diagnostics

