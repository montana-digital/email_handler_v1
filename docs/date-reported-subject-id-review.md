# Date Reported & Subject ID Logic Review

**Date:** 2025-01-27  
**Status:** 📋 **REVIEW - Current Implementation Analysis**

## Current Implementation

### Current Flow

1. **Extract Date Reported from Body**
   - Uses `_extract_body_fields()` to find "Date Reported:" field in email body
   - Parses using `_parse_date()` function
   - Stores as `date_reported` (datetime)

2. **Build Subject ID**
   - Primary: From `date_reported` → formatted as `YYYYMMDDTHHMMSS`
   - Fallback: From `body_fields.get("subject")` → the "Subject:" field from body (NOT email header)

### Current Code

```python
# Line 271: Extract date_reported from body fields
date_reported=_parse_date(body_fields.get("date_reported"))

# Line 237-240: Build subject_id from date_reported
def _build_subject_id(date_reported: Optional[datetime]) -> Optional[str]:
    if not date_reported:
        return None
    return date_reported.strftime("%Y%m%dT%H%M%S")

# Line 288: Set subject_id with fallback
parsed.subject_id = _build_subject_id(parsed.date_reported) or body_fields.get("subject")
```

### Current Issues

1. **Fallback Logic**
   - Currently falls back to `body_fields.get("subject")` (from body)
   - Does NOT check email Subject header for timestamp
   - No timestamp detection/cleaning logic

2. **No Timestamp Detection**
   - Doesn't check if email Subject header is a timestamp
   - Doesn't clean timestamp strings (remove symbols, trailing zeros)

3. **No Symbol Removal**
   - If subject is a timestamp like "20250115T123000", it's used as-is
   - No removal of symbols or trailing zeros

---

## Proposed Enhancement

### New Logic Flow

1. **Primary: Date Reported from Body**
   - Extract "Date Reported:" from email body
   - Parse as datetime
   - Format as `YYYYMMDDTHHMMSS`

2. **Fallback: Email Subject Header as Timestamp**
   - Check if email Subject header looks like a timestamp
   - Clean timestamp: remove symbols, remove trailing "0000" if present
   - Parse and format as `YYYYMMDDTHHMMSS`

3. **Final Fallback: Body Subject Field**
   - Use "Subject:" field from body (current fallback)

### Timestamp Detection Patterns

Common timestamp formats in email subjects:
- `20250115T123000` (ISO-like)
- `2025-01-15T12:30:00` (ISO with separators)
- `20250115 123000` (space separated)
- `20250115T12300000` (with trailing zeros)
- `20250115T1230` (without seconds)
- `20250115` (date only)

### Cleaning Logic

1. **Remove Symbols**
   - Remove: `-`, `:`, ` ` (spaces), `/`, etc.
   - Keep: digits and `T` (if present)

2. **Remove Trailing Zeros**
   - If timestamp ends with `0000`, remove it
   - Example: `20250115T12300000` → `20250115T123000`

3. **Normalize Format**
   - Ensure format: `YYYYMMDDTHHMMSS` or `YYYYMMDDTHHMM`
   - Add `T` if missing between date and time
   - Pad time components if needed

---

## Implementation Plan

### Step 1: Create Timestamp Detection Function

```python
def _is_timestamp_like(text: str) -> bool:
    """Check if text looks like a timestamp."""
    if not text:
        return False
    # Remove common separators and check if mostly digits
    cleaned = re.sub(r'[^\dT]', '', text)
    # Should have at least 8 digits (date) and optionally time
    return len(cleaned) >= 8 and cleaned.replace('T', '').isdigit()
```

### Step 2: Create Timestamp Cleaning Function

```python
def _clean_timestamp_from_subject(subject: str) -> Optional[str]:
    """Extract and clean timestamp from email subject.
    
    Returns cleaned timestamp in YYYYMMDDTHHMMSS format, or None if not a timestamp.
    """
    if not subject:
        return None
    
    # Remove all non-digit and non-T characters
    cleaned = re.sub(r'[^\dT]', '', subject.upper())
    
    # Check if it looks like a timestamp (at least 8 digits for date)
    if len(cleaned.replace('T', '')) < 8:
        return None
    
    # Ensure T is between date and time if not present
    if 'T' not in cleaned and len(cleaned) > 8:
        # Insert T after date (8 digits)
        cleaned = cleaned[:8] + 'T' + cleaned[8:]
    
    # Remove trailing 0000 if present
    if cleaned.endswith('0000'):
        cleaned = cleaned[:-4]
    
    # Validate and normalize format
    # Should be YYYYMMDDTHHMMSS or YYYYMMDDTHHMM
    if len(cleaned) == 15:  # YYYYMMDDTHHMMSS
        return cleaned
    elif len(cleaned) == 13:  # YYYYMMDDTHHMM
        return cleaned + "00"  # Add seconds
    elif len(cleaned) == 8:  # YYYYMMDD only
        return cleaned + "T000000"  # Add default time
    else:
        return None
```

### Step 3: Update Subject ID Logic

```python
# Current (line 288):
parsed.subject_id = _build_subject_id(parsed.date_reported) or body_fields.get("subject")

# New:
# Priority 1: Date Reported from body
subject_id = _build_subject_id(parsed.date_reported)

# Priority 2: Email Subject header as timestamp
if not subject_id:
    cleaned_timestamp = _clean_timestamp_from_subject(parsed.subject)
    if cleaned_timestamp:
        subject_id = cleaned_timestamp

# Priority 3: Body Subject field
if not subject_id:
    subject_id = body_fields.get("subject")

parsed.subject_id = subject_id
```

---

## Examples

### Example 1: Date Reported in Body
```
Body: "Date Reported: 2025-01-15T12:30:00"
Result: subject_id = "20250115T123000"
```

### Example 2: Timestamp in Subject Header
```
Subject: "2025-01-15T12:30:00"
Result: subject_id = "20250115T123000" (after cleaning)
```

### Example 3: Timestamp with Trailing Zeros
```
Subject: "20250115T12300000"
Result: subject_id = "20250115T123000" (trailing 0000 removed)
```

### Example 4: Timestamp with Symbols
```
Subject: "2025-01-15 12:30:00"
Result: subject_id = "20250115T123000" (symbols removed, T added)
```

### Example 5: Date Only
```
Subject: "20250115"
Result: subject_id = "20250115T000000" (default time added)
```

---

## Questions for Review

1. **Timestamp Format Detection**
   - Should we support more formats?
   - What's the minimum length to consider it a timestamp?

2. **Trailing Zeros**
   - Remove exactly 4 zeros (`0000`)?
   - Or any trailing zeros?
   - What about `000` (3 zeros)?

3. **Date-Only Handling**
   - If only date is present, should we use `T000000` (midnight)?
   - Or should we reject date-only as not a valid timestamp?

4. **Validation**
   - Should we validate that the timestamp is actually a valid date/time?
   - Or just check format and clean it?

5. **Priority Order**
   - Current: Date Reported → Body Subject → (new) Email Subject
   - Is this the correct priority?

---

## Testing Scenarios

1. Date Reported exists in body
2. Date Reported missing, Subject is timestamp
3. Date Reported missing, Subject is timestamp with symbols
4. Date Reported missing, Subject is timestamp with trailing zeros
5. Date Reported missing, Subject is date only
6. Date Reported missing, Subject is not a timestamp
7. All fields missing

---

**Document Version:** 1.0  
**Last Updated:** 2025-01-27  
**Status:** Awaiting Review & Approval

