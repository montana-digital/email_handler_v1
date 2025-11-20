# File Uploader Memory Media Storage Fix

**Date:** 2025-01-27  
**Issue:** "Bad Filename" error from Streamlit's `memory_media_file_storage`

---

## Problem Description

The application was experiencing errors like:
```
Bad Filename '{filename}'. (No media file with id)
```

This error occurs in Streamlit's `memory_media_file_storage` system when:
1. A file is uploaded via `st.file_uploader()`
2. The file is processed/persisted
3. Streamlit reruns the page
4. Code tries to access the uploaded file object after it's been cleared from memory

## Root Cause

In `app/ui/pages/deploy_scripts.py`, the code was:
1. Uploading a file via `st.file_uploader()`
2. Calling `_persist_uploaded_script(uploaded, ...)` which used `shutil.copyfileobj(upload, f)`
3. Then accessing `uploaded.name` after the file might have been cleared from memory

The issue is that Streamlit stores uploaded files in memory temporarily, and after a page rerun or when the file is read, it may be cleared from the media cache. Accessing properties like `.name` after this can cause the error.

## Solution

### Changes Made

1. **Immediate filename capture**: Capture `uploaded.name` immediately when the upload is detected, before any file operations
2. **Immediate file content reading**: Read the entire file content into memory immediately in `_persist_uploaded_script()` instead of using `copyfileobj()` which might access the file later
3. **Better error handling**: Added try/except blocks to handle cases where the file is no longer available
4. **File uploader key**: Added a unique key to the file uploader to help with state management
5. **Rerun after save**: Added `st.rerun()` after successful save to clear the uploader and prevent re-processing

### Code Changes

**Before:**
```python
uploaded = st.file_uploader("Upload .ps1 script", type=["ps1"])
if uploaded:
    saved_path = _persist_uploaded_script(uploaded, state.config.scripts_dir)
    st.success(f"Saved script to {saved_path}")
    state.add_notification(f"Script uploaded: {uploaded.name}")  # ❌ May fail here
```

**After:**
```python
uploaded = st.file_uploader("Upload .ps1 script", type=["ps1"], key="script_uploader")
if uploaded:
    # Capture filename immediately while file is still in memory
    try:
        filename = uploaded.name
    except (AttributeError, RuntimeError) as exc:
        st.error("Uploaded file is no longer available. Please upload again.")
        st.stop()
    
    try:
        saved_path = _persist_uploaded_script(uploaded, state.config.scripts_dir, filename=filename)
        st.success(f"Saved script to {saved_path}")
        state.add_notification(f"Script uploaded: {filename}")
        st.rerun()  # Clear uploader after successful save
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Failed to save script: {exc}")
```

**Updated `_persist_uploaded_script()` function:**
```python
def _persist_uploaded_script(upload, target_dir: Path, filename: str | None = None) -> Path:
    """Persist an uploaded file to disk.
    
    Args:
        upload: Streamlit UploadedFile object
        target_dir: Directory to save the file
        filename: Optional filename (if not provided, uses upload.name)
    """
    # Use provided filename or try to get from upload object
    if filename:
        file_name = filename
    else:
        try:
            file_name = upload.name
        except (AttributeError, RuntimeError) as exc:
            raise ValueError("Uploaded file is no longer available. Please upload again.") from exc
    
    destination = target_dir / file_name
    
    try:
        # Read the file content immediately before it's cleared from memory
        file_content = upload.read()
        with destination.open("wb") as f:
            f.write(file_content)
    except (AttributeError, RuntimeError, OSError) as exc:
        raise ValueError(f"Failed to save file: {exc}") from exc
    
    return destination
```

## Key Principles

1. **Read immediately**: Always read file content immediately when the upload is detected
2. **Capture metadata early**: Capture filename and other metadata before any file operations
3. **Handle errors gracefully**: Provide clear error messages when files are no longer available
4. **Clear state**: Use `st.rerun()` after successful operations to clear the uploader state

## Testing

To verify the fix:
1. Upload a PowerShell script via the Deploy Scripts page
2. Verify it saves successfully without errors
3. Try uploading multiple files in succession
4. Verify no "Bad Filename" errors appear in the console

## Related Files

- `app/ui/pages/deploy_scripts.py` - Main file with the fix
- All download buttons in other pages use file handles from disk, which are safe and don't have this issue

---

**Fix Completed:** 2025-01-27

