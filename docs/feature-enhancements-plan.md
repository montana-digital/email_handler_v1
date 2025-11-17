# Feature Enhancements Plan

## Completed ✅
1. **URL Parser - Fanged URLs**: Fixed to handle fanged URLs (hxxps://example[.]com)

## In Progress / To Do

### 2. Review Original Specs - Data Issues
**Issues Identified:**
- Subject ID: Currently uses "Subject:" field from body first, then falls back to date_reported. According to specs, should be from "Date Reported" formatted as YYYYMMDDTHHMMSS.
- Full Email Body: body_html may fall back to body_text. Need to ensure full HTML is always stored.
- Missing Columns: Need to verify all columns from specs are present in display.

**Fix Required:**
- Update Subject ID logic to prioritize date_reported over body "Subject:" field
- Ensure body_html always contains full HTML (not fallback to text)
- Review email display page to show all required columns

### 3. Standard Emails Page Improvements
**Requirements:**
- Default to select all emails
- Add "Add all" / "Remove all" buttons for multi-select fields (To, From, CC, etc.)

### 4. Attachments Page - Filtering & Selection
**Requirements:**
- Add filter functions (by type, date, subject_id, etc.)
- Multi-select with "Add all" / "Remove all" buttons
- Export selected attachments to Zip
- For email attachments: button to copy to input folder
- Track SubjectID for linking related emails

### 5. Reports - Category-Specific Exports
**Requirements:**
- When all of one category is selected (e.g., Images), show export button
- Images: Download in grid layout with related number and URL information
- Other categories: Similar structured exports

### 6. Progress Info During Ingestion
**Requirements:**
- Show progress bar/status during "Ingest New Emails" operation
- Display file count, current file being processed, errors encountered

