# Email Body Parsing Review

**Date:** 2025-01-27  
**Purpose:** Comprehensive review of what fields are parsed from email bodies

## Overview

The email parser extracts structured data from email bodies using pattern matching, specialized parsers, and field extraction. This document details all fields that are attempted to be parsed from email body content.

## Parsing Architecture

The parser uses a multi-layered approach:

1. **Body Text Collection** - Extracts HTML and plain text from email
2. **Structured Field Extraction** - Uses regex pattern to find "Label: Value" pairs
3. **Specialized Parsers** - URL and phone number extraction
4. **HTML Processing** - Converts HTML tables to structured format for better field extraction

---

## 1. Structured Field Extraction

### Pattern: `BODY_FIELD_PATTERN`

```python
BODY_FIELD_PATTERN = re.compile(
    r"^\s*(?P<field>[A-Za-z _-]+):\s*(?P<value>.*?)(?=\n\s*[A-Za-z _-]+:|$)",
    re.MULTILINE | re.DOTALL,
)
```

**What it does:**
- Matches lines in format: `Field Name: Value`
- Field name can contain letters, spaces, underscores, hyphens
- Value continues until next field or end of line
- Case-insensitive matching (fields are lowercased)
- Spaces in field names are converted to underscores

**Example matches:**
```
Date Reported: 2025-01-15T10:30:00
Sending Source: https://example.com
Callback Number: +1-555-123-4567
Model Confidence: 0.95
Additional Contacts: contact@example.com
```

### Fields Actually Used

The parser specifically looks for and uses these fields from the body:

#### 1. `date_reported`
- **Source:** Body field `"date_reported"` or `"Date Reported"`
- **Usage:** Parsed as datetime, used for `subject_id` generation
- **Format:** ISO format or standard date strings
- **Code Reference:**
  ```python
  date_reported=_parse_date(body_fields.get("date_reported"))
  ```

#### 2. `sending_source`
- **Source:** Body field `"sending_source"` or `"Sending Source"`
- **Usage:** Stored as `sending_source_raw`, then parsed for URLs to extract domains
- **Processing:** URLs in this field are extracted and domains stored in `sending_source_parsed`
- **Code Reference:**
  ```python
  sending_source_raw = body_fields.get("sending_source")
  sending_source_parsed = _dedupe([result.domain for result in extract_urls(sending_source_raw or "")])
  ```

#### 3. `callback_number`
- **Source:** Body field `"callback_number"` or `"Callback Number"`
- **Usage:** Stored in `callback_numbers_raw` (as single-item list)
- **Note:** This is separate from phone numbers extracted from entire body text
- **Code Reference:**
  ```python
  callback_number_raw = body_fields.get("callback_number")
  callback_numbers_raw=[callback_number_raw] if callback_number_raw else []
  ```

#### 4. `additional_contacts`
- **Source:** Body field `"additional_contacts"` or `"Additional Contacts"`
- **Usage:** Stored as string (not parsed further)
- **Code Reference:**
  ```python
  additional_contacts = body_fields.get("additional_contacts")
  ```

#### 5. `model_confidence`
- **Source:** Body field `"model_confidence"` or `"Model Confidence"`
- **Usage:** Parsed as float
- **Code Reference:**
  ```python
  model_confidence=float(body_fields["model_confidence"]) if body_fields.get("model_confidence") else None
  ```

#### 6. `subject` (Fallback Only)
- **Source:** Body field `"subject"` or `"Subject"`
- **Usage:** Only used as fallback for `subject_id` if `date_reported` is not available
- **Code Reference:**
  ```python
  parsed.subject_id = _build_subject_id(parsed.date_reported) or body_fields.get("subject")
  ```

---

## 2. URL Extraction (Parser3)

### What Gets Extracted

URLs are extracted from the **entire email body** (both HTML and text), not just from structured fields.

### Extraction Methods

#### Standard URLs
- **Pattern:** `(?:https?://|ftp://|www\.)[^\s<>\"]+`
- **Examples:**
  - `https://example.com/path`
  - `http://test.org`
  - `www.example.com`
  - `ftp://files.example.com`

#### Fanged URLs (Security Evasion)
- **Pattern:** `(?:hxxps?://|hxxp://|ftp://|www\.)[^\s<>\"]+`
- **Examples:**
  - `hxxp://malicious.com` → normalized to `http://malicious.com`
  - `hxxps://secure.com` → normalized to `https://secure.com`

#### Fanged Domains (Standalone)
- **Pattern:** Domains with dots replaced by brackets
- **Examples:**
  - `example[.]com` → normalized to `https://example.com`
  - `test(.)org` → normalized to `https://test.org`
  - `site{.}net` → normalized to `https://site.net`
  - `domain[dot]com` → normalized to `https://domain.com`

### Output Fields

1. **`urls_raw`** - List of original URLs as found in email
2. **`urls_parsed`** - List of extracted domains (normalized, deduplicated)
3. **`sending_source_parsed`** - Domains extracted from `sending_source` field specifically

### Processing Steps

1. Defang URLs (convert `hxxp://` → `http://`, `[.]` → `.`)
2. Normalize format (add `https://` to `www.` URLs)
3. Extract domain using `tldextract` library
4. Deduplicate results

---

## 3. Phone Number Extraction (Parser4)

### What Gets Extracted

Phone numbers are extracted from the **entire email body** (both HTML and text), not just from structured fields.

### Extraction Methods

#### Primary Method: `phonenumbers` Library
- Uses Google's `phonenumbers` library for robust parsing
- Default region: `US`
- Formats numbers to E.164 format (e.g., `+15551234567`)

#### Fallback Method: Regex Pattern
- **Pattern:** `(?:\+?\d[\d\s().-]{6,}\d)`
- Handles cases where library might miss numbers
- Formats 10-digit US numbers as `+1XXXXXXXXXX`
- Formats 11-digit numbers starting with 1 as `+1XXXXXXXXXX`

### Output Fields

1. **`callback_numbers_parsed`** - List of E.164 formatted phone numbers
2. **`callback_numbers_raw`** - List containing the `callback_number` field value (if present)

**Note:** The `callback_number` from structured fields is stored separately from phone numbers extracted from body text.

---

## 4. HTML Processing for Field Extraction

### HTML to Text Conversion

The parser converts HTML to text before extracting structured fields:

1. **Removes script/style tags**
2. **Converts HTML tables to "Label: Value" format**
   - Two-column tables (`<td>` pairs) are converted to `Label: Value` lines
   - This improves field extraction from HTML emails
3. **Extracts text content**
4. **Normalizes whitespace**

### Example HTML Table Conversion

**Before:**
```html
<table>
  <tr>
    <td>Date Reported</td>
    <td>2025-01-15</td>
  </tr>
  <tr>
    <td>Sending Source</td>
    <td>https://example.com</td>
  </tr>
</table>
```

**After (for field extraction):**
```
Date Reported: 2025-01-15
Sending Source: https://example.com
```

---

## 5. Image Extraction

### Base64 Image Extraction

- **Pattern:** `data:image/(?P<format>[a-zA-Z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=]+)`
- **Output:** `image_base64` field contains the base64 data
- **Usage:** Extracts embedded images from HTML body

---

## 6. Complete Field Mapping

### From Email Headers (Not Body)
These are extracted from email headers, not body:
- `sender` - From header
- `cc` - CC header
- `subject` - Subject header
- `date_sent` - Date header
- `message_id` - Message-ID header

### From Email Body

| Field Name | Source | Processing | Output Field(s) |
|------------|--------|------------|-----------------|
| `date_reported` | Body field | Date parsing | `date_reported`, `subject_id` |
| `sending_source` | Body field | URL extraction | `sending_source_raw`, `sending_source_parsed` |
| `callback_number` | Body field | None | `callback_numbers_raw` |
| `additional_contacts` | Body field | None | `additional_contacts` |
| `model_confidence` | Body field | Float conversion | `model_confidence` |
| `subject` | Body field | None | `subject_id` (fallback only) |
| URLs | Entire body | Defang, normalize, extract domain | `urls_raw`, `urls_parsed` |
| Phone numbers | Entire body | E.164 formatting | `callback_numbers_parsed` |
| Base64 images | HTML body | Extract data | `image_base64` |

---

## 7. Field Extraction Logic Flow

```
Email Body (HTML/Text)
    ↓
1. Convert HTML to text (if HTML)
   - Remove scripts/styles
   - Convert tables to "Label: Value"
    ↓
2. Extract structured fields
   - Apply BODY_FIELD_PATTERN
   - Lowercase field names
   - Replace spaces with underscores
    ↓
3. Process specific fields:
   - date_reported → parse as datetime
   - sending_source → extract URLs → extract domains
   - callback_number → store as-is
   - additional_contacts → store as-is
   - model_confidence → parse as float
   - subject → use as fallback for subject_id
    ↓
4. Extract URLs from entire body
   - Find standard URLs
   - Find fanged URLs
   - Find fanged domains
   - Defang and normalize
   - Extract domains
    ↓
5. Extract phone numbers from entire body
   - Use phonenumbers library
   - Fallback to regex
   - Format as E.164
    ↓
6. Extract base64 images from HTML
   - Find data URIs
   - Extract base64 data
```

---

## 8. Limitations and Edge Cases

### Structured Field Extraction

1. **Field Name Matching**
   - Must start at beginning of line (with optional whitespace)
   - Field name must be followed by colon and space
   - Value continues until next field or end of line
   - Case-insensitive but exact match required

2. **HTML Table Conversion**
   - Only converts two-column tables
   - Requires `<td>` or `<th>` tags
   - May miss nested tables or complex structures

3. **Multi-line Values**
   - Values can span multiple lines until next field
   - May include unwanted content if field boundaries unclear

### URL Extraction

1. **Fanged URL Variations**
   - Supports common fanging patterns
   - May miss uncommon variations
   - Some obfuscation techniques may not be detected

2. **Domain Extraction**
   - Relies on `tldextract` library
   - May not handle all TLDs correctly
   - International domains may have issues

### Phone Number Extraction

1. **Region Detection**
   - Defaults to US region
   - May misparse international numbers without country code
   - Fallback regex is basic

2. **Format Variations**
   - Handles common formats
   - May miss unusual formatting
   - Extension numbers may be included incorrectly

---

## 9. Recommendations for Enhancement

### Potential Improvements

1. **Field Name Variations**
   - Support common variations (e.g., "Date Reported" vs "Reported Date")
   - Handle abbreviations
   - Support multiple languages

2. **Better HTML Parsing**
   - Handle nested tables
   - Support more table structures
   - Extract fields from div-based layouts

3. **Enhanced URL Detection**
   - Support more fanging patterns
   - Detect IP addresses as URLs
   - Handle encoded URLs

4. **Phone Number Improvements**
   - Better international number detection
   - Handle extensions separately
   - Support more format variations

5. **Additional Field Extraction**
   - Extract email addresses from body
   - Extract dates/times more broadly
   - Extract file names/paths
   - Extract IP addresses

---

## 10. Testing Recommendations

### Test Cases for Field Extraction

1. **Structured Fields**
   - Test with various field name formats
   - Test with multi-line values
   - Test with HTML tables
   - Test with missing fields

2. **URL Extraction**
   - Test standard URLs
   - Test fanged URLs
   - Test fanged domains
   - Test edge cases (malformed URLs)

3. **Phone Numbers**
   - Test US numbers (various formats)
   - Test international numbers
   - Test with extensions
   - Test edge cases

4. **HTML Processing**
   - Test various table structures
   - Test nested HTML
   - Test with scripts/styles
   - Test with images

---

## Summary

The parser attempts to extract the following from email bodies:

**Structured Fields (6 fields):**
1. `date_reported` - Date/time when email was reported
2. `sending_source` - Source URL/domain
3. `callback_number` - Phone number from structured field
4. `additional_contacts` - Additional contact information
5. `model_confidence` - Confidence score (float)
6. `subject` - Subject line (fallback for subject_id)

**Unstructured Extraction:**
- **URLs** - All URLs from entire body (standard and fanged)
- **Phone Numbers** - All phone numbers from entire body
- **Base64 Images** - Embedded images in HTML

**Processing:**
- HTML tables converted to structured format
- URLs defanged and normalized
- Phone numbers formatted to E.164
- Domains extracted from URLs

---

**Document Version:** 1.0  
**Last Updated:** 2025-01-27

