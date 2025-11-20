# Batch Summary DataFrame Enhancement Plan

**Date:** 2025-01-27  
**Status:** 📋 **REVIEW - Pending Approval**

## Overview

Enhance the Batch Summary DataFrame in the Email Display page to include additional fields extracted from emails, providing more comprehensive information at a glance.

---

## Current Implementation

### Current DataFrame Columns

The Batch Summary currently displays these columns:

1. **ID** - Email record ID
2. **Status** - Parse status (success/failed/unknown)
3. **Subject** - Email subject line
4. **Sender** - Email sender address
5. **Date Sent** - When email was sent
6. **Subject ID** - Generated subject identifier
7. **URLs** - Parsed domains only (from `urls_parsed`)
8. **Callback Numbers** - Parsed phone numbers (from `callback_numbers_parsed`)

### Current Code Location

```python
# app/ui/pages/email_display.py, lines 459-471
table_rows = [
    {
        "ID": record["id"],
        "Status": record.get("parse_status") or "unknown",
        "Subject": record["subject"],
        "Sender": record["sender"],
        "Date Sent": record["date_sent"],
        "Subject ID": record["subject_id"],
        "URLs": ", ".join(record["urls_parsed"]),
        "Callback Numbers": ", ".join(record["callback_numbers_parsed"]),
    }
    for record in page_records
]
```

---

## Proposed Changes

### Fields to Add

Based on your requirements, we'll add the following columns:

#### 1. **Date Reported** ✅
- **Source:** `record["date_reported"]`
- **Format:** ISO datetime string (already formatted in serialization)
- **Display:** Show as-is, or format as readable date
- **Note:** Already available in serialized data

#### 2. **Sending Source** ✅
- **Source:** `record["sending_source_raw"]`
- **Display:** Raw sending source string
- **Note:** Already available in serialized data

#### 3. **Additional Contacts** ✅
- **Source:** `record["additional_contacts"]`
- **Display:** String value as-is
- **Note:** Already available in serialized data

#### 4. **Model Confidence** ✅
- **Source:** `record["model_confidence"]`
- **Format:** Float (0.0 to 1.0)
- **Display:** Show as decimal (e.g., "0.95") or percentage (e.g., "95%")
- **Note:** Already available in serialized data

#### 5. **Subject** (Already Exists) ✅
- **Current:** Already displayed
- **Action:** Keep as-is

#### 6. **Email Body Text** ⚠️
- **Source:** `record["body_html"]` (needs conversion to text)
- **Challenge:** Only `body_html` is stored in database, not `body_text`
- **Solution:** Convert HTML to plain text using existing `_html_to_text()` function
- **Display:** Full text body (may be long - consider truncation)
- **Note:** Requires HTML-to-text conversion

#### 7. **Full URLs** (Not Just Domains) ✅
- **Current:** Shows only domains from `urls_parsed`
- **Proposed:** Add new column with full URLs from `urls_raw`
- **Display:** Comma-separated list of full URLs
- **Note:** Already available in serialized data

---

## Implementation Plan

### Step 1: Add HTML-to-Text Conversion Helper

Since `body_text` is not stored in the database, we need to convert `body_html` to text.

**Location:** `app/ui/pages/email_display.py`

**Function to add:**
```python
def _html_to_text_for_display(html_content: str | None) -> str:
    """Convert HTML to plain text for DataFrame display."""
    if not html_content:
        return ""
    # Reuse existing HTML-to-text logic from parser
    # Or use BeautifulSoup for simple conversion
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text(separator=" ", strip=True)
        # Truncate if too long (e.g., max 500 chars for display)
        if len(text) > 500:
            return text[:500] + "..."
        return text
    except Exception:
        # Fallback: simple tag stripping
        import re
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 500:
            return text[:500] + "..."
        return text
```

### Step 2: Update DataFrame Construction

**Location:** `app/ui/pages/email_display.py`, lines 459-471

**Proposed new structure:**
```python
table_rows = [
    {
        # Existing columns
        "ID": record["id"],
        "Status": record.get("parse_status") or "unknown",
        "Subject": record["subject"],
        "Sender": record["sender"],
        "Date Sent": record["date_sent"],
        "Subject ID": record["subject_id"],
        
        # New columns
        "Date Reported": record.get("date_reported") or "",
        "Sending Source": record.get("sending_source_raw") or "",
        "Additional Contacts": record.get("additional_contacts") or "",
        "Model Confidence": (
            f"{record['model_confidence']:.2f}" 
            if record.get("model_confidence") is not None 
            else ""
        ),
        "Body Text": _html_to_text_for_display(record.get("body_html")),
        
        # Updated URL column
        "URLs (Domains)": ", ".join(record["urls_parsed"]),  # Keep existing
        "URLs (Full)": ", ".join(record["urls_raw"]),  # New column
        
        # Existing callback numbers
        "Callback Numbers": ", ".join(record["callback_numbers_parsed"]),
    }
    for record in page_records
]
```

### Step 3: Column Ordering

**Proposed column order:**
1. ID
2. Status
3. Subject
4. Sender
5. Date Sent
6. Date Reported ⭐ NEW
7. Subject ID
8. Sending Source ⭐ NEW
9. Additional Contacts ⭐ NEW
10. Model Confidence ⭐ NEW
11. URLs (Domains) - renamed from "URLs"
12. URLs (Full) ⭐ NEW
13. Callback Numbers
14. Body Text ⭐ NEW

---

## Considerations & Decisions Needed

### 1. Body Text Display Length ⚠️

**Question:** How should we handle long email bodies?

**Options:**
- **A)** Show full text (may make DataFrame very wide/tall)
- **B)** Truncate to first 200-500 characters with "..." indicator
- **C)** Show first line only
- **D)** Make it expandable/collapsible in DataFrame

**Recommendation:** Option B - Truncate to 500 characters with "..." for readability

### 2. URL Column Naming

**Question:** How should we name the URL columns?

**Options:**
- **A)** "URLs (Domains)" and "URLs (Full)"
- **B)** "URL Domains" and "URLs"
- **C)** Keep "URLs" for domains, add "Full URLs" for full URLs
- **D)** "URLs" and "Full URLs"

**Recommendation:** Option C - Keep existing "URLs" name, add "Full URLs"

### 3. Model Confidence Format

**Question:** How should model confidence be displayed?

**Options:**
- **A)** Decimal format: "0.95"
- **B)** Percentage: "95%"
- **C)** Both: "0.95 (95%)"
- **D)** Rounded: "0.95" or "1.00"

**Recommendation:** Option A - Decimal format (2 decimal places)

### 4. Date Formatting

**Question:** Should dates be formatted for readability?

**Current:** ISO format strings (e.g., "2025-01-15T10:30:00+00:00")
**Options:**
- **A)** Keep ISO format
- **B)** Format as "2025-01-15 10:30:00"
- **C)** Format as "Jan 15, 2025 10:30 AM"

**Recommendation:** Option B - Simplified ISO format without timezone

### 5. Empty/Null Value Display

**Question:** How should empty/null values be displayed?

**Options:**
- **A)** Empty string ""
- **B)** "—" or "N/A"
- **C)** "(empty)"

**Recommendation:** Option A - Empty string for cleaner DataFrame

---

## Performance Considerations

### HTML-to-Text Conversion

- **Impact:** Converting HTML to text for each row in the DataFrame
- **Mitigation:** 
  - Only convert for displayed page (already paginated)
  - Use efficient BeautifulSoup parsing
  - Cache conversion if same email shown multiple times (unlikely needed)

### DataFrame Size

- **Impact:** More columns = wider DataFrame, potentially harder to view
- **Mitigation:**
  - Streamlit DataFrames are scrollable
  - Users can resize columns
  - Consider column width settings

---

## Testing Checklist

- [ ] Verify all new columns appear correctly
- [ ] Test with emails that have all fields populated
- [ ] Test with emails that have missing/null fields
- [ ] Test HTML-to-text conversion with various HTML formats
- [ ] Test with very long email bodies (truncation)
- [ ] Test with emails containing many URLs
- [ ] Verify existing columns still work
- [ ] Test pagination with new columns
- [ ] Test filtering with new columns (if applicable)

---

## Code Changes Summary

### Files to Modify

1. **`app/ui/pages/email_display.py`**
   - Add `_html_to_text_for_display()` helper function
   - Update `table_rows` dictionary construction
   - Update column names/ordering

### Estimated Lines Changed

- **Add:** ~30-40 lines (helper function)
- **Modify:** ~15-20 lines (DataFrame construction)
- **Total:** ~45-60 lines

---

## Proposed Final Column Structure

| Column Name | Source | Format | Notes |
|------------|--------|--------|-------|
| ID | `record["id"]` | Integer | Existing |
| Status | `record["parse_status"]` | String | Existing |
| Subject | `record["subject"]` | String | Existing |
| Sender | `record["sender"]` | String | Existing |
| Date Sent | `record["date_sent"]` | ISO String | Existing |
| Date Reported | `record["date_reported"]` | ISO String | ⭐ NEW |
| Subject ID | `record["subject_id"]` | String | Existing |
| Sending Source | `record["sending_source_raw"]` | String | ⭐ NEW |
| Additional Contacts | `record["additional_contacts"]` | String | ⭐ NEW |
| Model Confidence | `record["model_confidence"]` | Float (2 decimals) | ⭐ NEW |
| URLs | `record["urls_parsed"]` | Comma-separated | Existing (domains) |
| Full URLs | `record["urls_raw"]` | Comma-separated | ⭐ NEW |
| Callback Numbers | `record["callback_numbers_parsed"]` | Comma-separated | Existing |
| Body Text | `record["body_html"]` → converted | String (truncated) | ⭐ NEW |

---

## Questions for Review

1. **Body Text Length:** Do you prefer truncation (500 chars) or full text?
2. **URL Column Names:** Which naming convention do you prefer?
3. **Model Confidence:** Decimal (0.95) or percentage (95%) format?
4. **Date Format:** Keep ISO or format for readability?
5. **Empty Values:** Show as empty string or "—"/"N/A"?
6. **Column Order:** Is the proposed order acceptable, or would you prefer different ordering?

---

## Next Steps

1. **Review this plan** and provide feedback on decisions
2. **Approve implementation approach**
3. **Implement changes** based on approved decisions
4. **Test thoroughly** with real email data
5. **Deploy and verify** in production

---

**Document Version:** 1.0  
**Last Updated:** 2025-01-27  
**Status:** Awaiting Review & Approval

