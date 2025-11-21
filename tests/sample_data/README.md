# Sample Knowledge Data Files

This directory contains sample CSV files for testing the Knowledge feature.

## Files

### `knowledge_tns_sample.csv`
Sample data for the **Knowledge_TNs** (Telephone Numbers) table.

**Columns:**
- `phone` - Phone number (will be normalized to E.164 format)
- `carrier` - Phone carrier name
- `region` - Geographic region
- `status` - Status (Active/Inactive)
- `notes` - Additional notes

**Usage:**
1. Go to Knowledge page in the app
2. Select "Knowledge_TNs (Phone Numbers)" tab
3. Upload this CSV file to initialize the table
4. Select `phone` as the Primary Key Column
5. After initialization, you can select which columns to include in "Add Knowledge" (e.g., `carrier`, `region`)

### `knowledge_domains_sample.csv`
Sample data for the **Knowledge_Domains** (URLs/Domains) table.

**Columns:**
- `domain` - Domain or full URL (will be normalized to base domain)
- `registrar` - Domain registrar name
- `country` - Country code
- `status` - Status (Active/Inactive)
- `notes` - Additional notes

**Usage:**
1. Go to Knowledge page in the app
2. Select "Knowledge_Domains (URLs)" tab
3. Upload this CSV file to initialize the table
4. Select `domain` as the Primary Key Column
5. After initialization, you can select which columns to include in "Add Knowledge" (e.g., `registrar`, `country`)

## Testing Workflow

1. **Initialize Tables:**
   - Upload `knowledge_tns_sample.csv` to initialize Knowledge_TNs
   - Upload `knowledge_domains_sample.csv` to initialize Knowledge_Domains

2. **Select Columns:**
   - Choose which columns from each table should be added to emails when "Add Knowledge" is run
   - For example: select `carrier` and `region` from Knowledge_TNs

3. **Upload Additional Data:**
   - After initialization, you can upload more CSV files with the same column structure
   - The app will validate that columns match before adding data

4. **Add Knowledge to Emails:**
   - Go to Email Display page
   - Select emails in a batch
   - Click "Add Knowledge" button
   - The app will match phone numbers and URLs from emails against the knowledge tables
   - Selected columns will be added to the Batch Summary

## Notes

- Phone numbers are normalized to E.164 format (e.g., `+15551234567`)
- URLs are normalized to base domains (e.g., `https://example.com/path` → `example.com`)
- If no match is found, columns will be set to "not available"
- Re-running "Add Knowledge" will overwrite existing knowledge data for selected columns

