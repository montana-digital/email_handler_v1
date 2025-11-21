"""Email Display page with ingestion controls and editing UI."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, UnidentifiedImageError
from streamlit.components.v1 import html

from app.db.init_db import session_scope
from app.services.batch_finalization import finalize_batch
from app.services.email_exports import (
    build_attachments_zip,
    build_single_email_html,
    find_original_email_bytes,
)
from app.services.email_records import (
    get_batches,
    get_email_detail,
    get_emails_for_batch,
    update_email_record,
)
from app.services.ingestion import _discover_email_files, ingest_emails
from app.services.parsing import parser_capabilities
from app.services.reparse import reparse_email
from app.services.reporting import generate_email_report
from app.services.standard_emails import promote_to_standard_emails
from app.ui.state import AppState
from app.ui.utils.images import display_image_with_dialog, process_html_images


def _html_to_text_for_display(html_content: str | None) -> str:
    """Convert HTML to plain text for DataFrame display.
    
    Truncates to 500 characters for readability.
    """
    if not html_content:
        return ""
    
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text(separator=" ", strip=True)
        # Truncate if too long
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


def _format_date_for_display(date_str: str | None) -> str:
    """Format ISO date string for display.
    
    Converts "2025-01-15T10:30:00+00:00" to "2025-01-15 10:30:00"
    """
    if not date_str:
        return ""
    try:
        # Remove timezone info and replace T with space
        if "T" in date_str:
            # Split on T to get date and time parts
            parts = date_str.split("T")
            date_part = parts[0]
            time_part = parts[1] if len(parts) > 1 else ""
            
            # Remove timezone and microseconds from time part
            if time_part:
                # Remove timezone (everything after + or -)
                if "+" in time_part:
                    time_part = time_part.split("+")[0]
                elif "-" in time_part:
                    # Check if this is a timezone (format: HH:MM:SS-HH:MM or HH:MM:SS-HHMM)
                    # Timezone would be at the end after the time
                    # Pattern: digits:digits:digits followed by -digits:digits or -digitsdigits
                    import re
                    # Match timezone pattern: - followed by digits (with optional colon)
                    timezone_pattern = r'-\d{2}:?\d{2}$'
                    if re.search(timezone_pattern, time_part):
                        # Remove timezone
                        time_part = re.sub(timezone_pattern, '', time_part)
                    elif time_part.count("-") > 2:  # Has timezone (old logic for compatibility)
                        # Find the last - which is likely the timezone separator
                        time_parts = time_part.rsplit("-", 1)
                        if len(time_parts) == 2:
                            time_part = time_parts[0]
                
                # Remove microseconds if present
                time_part = time_part.split(".")[0]
                
                return f"{date_part} {time_part}"
            return date_part
        return date_str
    except Exception:
        return date_str or ""


def _input_counts(input_dir: Path) -> tuple[int, int]:
    if not input_dir.exists():
        return 0, 0
    eml_count = len(list(input_dir.glob("*.eml")))
    msg_count = len(list(input_dir.glob("*.msg")))
    return eml_count, msg_count


def _render_value_list(label: str, values: list[str]) -> None:
    if not values:
        st.markdown(f"**{label}:** —")
        return
    if len(values) <= 3:
        formatted = ", ".join(values)
        st.markdown(f"**{label}:** {formatted}")
    else:
        with st.expander(f"{label} ({len(values)})", expanded=False):
            st.write("\n".join(values))


def _has_custom_background(body_html: str) -> bool:
    lowered = body_html.lower()
    tokens = ("background-color", "background:", "bgcolor", "background=")
    return any(token in lowered for token in tokens)


def _detect_image_format_from_base64(base64_data: str) -> str:
    """Try to detect image format from base64 data.
    
    Returns MIME type like 'image/png', 'image/jpeg', etc.
    """
    if not base64_data:
        return "image/png"  # Default
    
    try:
        import base64 as b64
        # Decode first few bytes to check magic numbers
        decoded = b64.b64decode(base64_data[:20] + "==")  # Add padding for short strings
        
        # Check magic numbers
        if decoded.startswith(b'\x89PNG\r\n\x1a\n'):
            return "image/png"
        elif decoded.startswith(b'\xff\xd8\xff'):
            return "image/jpeg"
        elif decoded.startswith(b'GIF87a') or decoded.startswith(b'GIF89a'):
            return "image/gif"
        elif decoded.startswith(b'RIFF') and b'WEBP' in decoded[:12]:
            return "image/webp"
        else:
            return "image/png"  # Default fallback
    except Exception:
        return "image/png"  # Default fallback


def _fix_html_images(body_html: str, image_base64: str | None = None) -> str:
    """Fix and enhance HTML to ensure images render correctly.
    
    - Injects base64 image if provided and no images found in HTML
    - Fixes broken image references (cid:, etc.)
    - Ensures base64 images are properly formatted
    """
    if not body_html:
        return "" if body_html is None else body_html
    
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body_html, "html.parser")
        
        # Find all image tags
        images = soup.find_all("img")
        has_working_images = False
        
        # Check if we have any working images
        for img in images:
            src = img.get("src", "")
            if src and (src.startswith("data:image") or src.startswith("http")):
                has_working_images = True
                break
        
        # If we have a base64 image and no working images in HTML, inject it
        if image_base64 and not has_working_images:
            # Detect image format
            mime_type = _detect_image_format_from_base64(image_base64)
            
            img_tag = soup.new_tag("img")
            img_tag["src"] = f"data:{mime_type};base64,{image_base64}"
            img_tag["style"] = "max-width: 100%; height: auto; display: block; margin: 10px 0;"
            img_tag["alt"] = "Email image"
            
            # Insert at the beginning of body or create body if needed
            if soup.body:
                soup.body.insert(0, img_tag)
            elif soup.html:
                if not soup.html.body:
                    body_tag = soup.new_tag("body")
                    body_tag.insert(0, img_tag)
                    soup.html.append(body_tag)
                else:
                    soup.html.body.insert(0, img_tag)
            else:
                # No HTML structure, wrap in basic structure
                html_tag = soup.new_tag("html")
                body_tag = soup.new_tag("body")
                body_tag.insert(0, img_tag)
                html_tag.append(body_tag)
                soup.insert(0, html_tag)
        elif image_base64:
            # We have images but also base64 - check if any are broken
            mime_type = _detect_image_format_from_base64(image_base64)
            for img in images:
                src = img.get("src", "")
                # Fix broken references (cid:, empty, etc.)
                if not src or src.startswith("cid:") or src.startswith("x-msg-id:") or (src and not src.startswith("data:image") and not src.startswith("http")):
                    # Replace with base64 image
                    img["src"] = f"data:{mime_type};base64,{image_base64}"
                    if not img.get("alt"):
                        img["alt"] = "Email image"
                    if not img.get("style"):
                        img["style"] = "max-width: 100%; height: auto;"
        
        # Ensure all broken image references are fixed or removed
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and not src.startswith("data:image") and not src.startswith("http"):
                # Might be a broken reference - try to use base64 if available
                if image_base64:
                    mime_type = _detect_image_format_from_base64(image_base64)
                    img["src"] = f"data:{mime_type};base64,{image_base64}"
                    if not img.get("alt"):
                        img["alt"] = "Email image"
                else:
                    # Remove broken image or add placeholder
                    img["alt"] = "Image not available"
                    img["src"] = "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgZmlsbD0iI2VlZSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTQiIGZpbGw9IiM5OTkiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj5JbWFnZSBub3QgYXZhaWxhYmxlPC90ZXh0Pjwvc3ZnPg=="
        
        return str(soup)
    except Exception:
        # If processing fails, return original HTML
        return body_html


def _render_email_body(body_html: str, image_base64: str | None = None) -> None:
    """Render email body HTML with proper image support."""
    if not body_html:
        return
    
    # First, fix any broken images and inject base64 if needed
    fixed_html = _fix_html_images(body_html, image_base64)
    
    # Process HTML to convert images to thumbnails
    processed_html = process_html_images(fixed_html)
    
    if _has_custom_background(processed_html):
        html(processed_html, height=500, scrolling=True)
    else:
        wrapped = f"""
        <div style="
            background-color: #ffffff;
            color: #111111;
            padding: 1rem;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
        ">
        {processed_html}
        </div>
        """
        html(wrapped, height=500, scrolling=True)


def _render_download_buttons(email_detail: dict, attachments: list[dict], config) -> None:
    with session_scope() as session:
        original_payload = find_original_email_bytes(session, config, email_detail.get("email_hash"))
        attachments_zip = build_attachments_zip(
            attachments,
            prefix=f"email_{email_detail.get('id', 'attachments')}_files",
            session=session,
            email_hash=email_detail.get("email_hash"),
        )
    single_html = build_single_email_html(email_detail)

    download_cols = st.columns(3)
    with download_cols[0]:
        st.download_button(
            "Download Original",
            data=original_payload[1] if original_payload else b"",
            file_name=original_payload[0] if original_payload else "original_unavailable.txt",
            mime="application/octet-stream",
            disabled=original_payload is None,
            width="stretch",
        )
        if original_payload is None:
            st.caption("Original file not found.")

    with download_cols[1]:
        st.download_button(
            "Download HTML",
            data=single_html,
            file_name=f"email_{email_detail.get('id', 'detail')}.html",
            mime="text/html",
            width="stretch",
        )

    with download_cols[2]:
        st.download_button(
            "Download Attachments",
            data=attachments_zip[1] if attachments_zip else b"",
            file_name=attachments_zip[0] if attachments_zip else "attachments_unavailable.zip",
            mime="application/zip",
            disabled=attachments_zip is None,
            width="stretch",
        )
        if attachments_zip is None:
            st.caption("No attachments available.")


@st.fragment
def _render_ingestion_panel(state: AppState) -> None:
    eml_count, msg_count = _input_counts(state.config.input_dir)
    with st.container():
        st.caption(
            f"Input directory `{state.config.input_dir}` currently contains **{eml_count} EML** "
            f"and **{msg_count} MSG** files."
        )

    # Checkbox for 'original' filename feature
    use_date_sent_for_original = st.checkbox(
        "Use Date Sent as Subject ID for files containing 'original' in filename",
        value=st.session_state.get("use_date_sent_for_original", False),
        key="use_date_sent_for_original",
        help="When enabled, emails with 'original' in the filename will use their Date Sent field (formatted as YYYYMMDDTHHMMSS) as the Subject ID instead of the parsed Subject ID."
    )
    
    col_ingest, col_refresh = st.columns([1, 1])
    with col_ingest:
        if st.button("Ingest New Emails", width="stretch"):
            # Discover files first to get count
            files = _discover_email_files(state.config.input_dir)
            total_files = len(files)
            
            if total_files == 0:
                st.info("No new emails found in the input directory.")
            else:
                # Create progress bar and status
                progress_bar = st.progress(0)
                status_container = st.empty()
                
                def update_progress(current: int, total: int, file_name: str) -> None:
                    """Update progress bar and status during ingestion."""
                    progress = current / total if total > 0 else 0
                    progress_bar.progress(progress)
                    status_container.info(
                        f"Processing email {current} of {total}: **{file_name}**"
                    )
                
                with session_scope() as session:
                    result = ingest_emails(
                        session,
                        config=state.config,
                        progress_callback=update_progress,
                        use_date_sent_for_original=use_date_sent_for_original,
                    )
                
                # Clear progress indicators
                progress_bar.empty()
                status_container.empty()
                
                if result is None:
                    st.info("No new emails found in the input directory.")
                else:
                    if result.skipped:
                        skipped_preview = "\n".join(result.skipped[:5])
                        more = ""
                        if len(result.skipped) > 5:
                            more = f"\n...and {len(result.skipped) - 5} more."
                        st.warning(
                            "Some files could not be ingested:\n"
                            f"{skipped_preview}{more}\n"
                            "Check that optional dependencies (e.g., `extract-msg`) are installed and that the files are valid."
                        )
                    if result.failures:
                        failure_preview = "\n".join(result.failures[:5])
                        more_failures = ""
                        if len(result.failures) > 5:
                            more_failures = f"\n...and {len(result.failures) - 5} more."
                        st.warning(
                            "Some emails were stored but could not be fully parsed yet:\n"
                            f"{failure_preview}{more_failures}\n"
                            "You can retry parsing them after installing optional parsers."
                        )

                    if result.batch and result.email_ids:
                        batch = result.batch
                        email_ids = result.email_ids
                        state.add_notification(f"Ingested {len(email_ids)} emails into {batch.batch_name}")
                        st.success(f"Ingested {len(email_ids)} emails into '{batch.batch_name}'.")
                        st.rerun()
                    elif not result.email_ids and not result.batch:
                        st.info("No new emails were saved. See warnings above for skipped files.")
    with col_refresh:
        if st.button("Refresh Batches", width="stretch"):
            st.rerun()


@st.fragment
def _render_batch_panel(state: AppState) -> None:
    with session_scope() as session:
        batches = get_batches(session)

    if not batches:
        st.info("No batches available yet. Use 'Ingest New Emails' to create one.")
        return

    batch_lookup = {batch.id: batch for batch in batches}
    batch_ids = list(batch_lookup.keys())
    if state.selected_batch_id not in batch_ids:
        state.selected_batch_id = batch_ids[0]

    def _batch_label(batch_id: int) -> str:
        batch = batch_lookup[batch_id]
        status = batch.status or "draft"
        return f"{batch.batch_name} ({batch.record_count} emails, {status})"

    selected_batch_id = st.selectbox(
        "Select a batch",
        options=batch_ids,
        index=batch_ids.index(state.selected_batch_id),
        format_func=_batch_label,
    )
    state.selected_batch_id = selected_batch_id

    with session_scope() as session:
        email_records = get_emails_for_batch(session, state.selected_batch_id)

    state.search_query = st.text_input(
        "Search subject, sender, or hash",
        value=state.search_query,
        key="email_search_input",
        help="Filters are applied to subject, sender, and email hash within the selected batch.",
    )

    search_term = state.search_query.lower()
    filtered = [
        record
        for record in email_records
        if search_term in (record["subject"] or "").lower()
        or search_term in (record["sender"] or "").lower()
        or search_term in (record["email_hash"] or "").lower()
    ]

    # Column accessors for filtering
    column_accessors = {
        "Subject": lambda record: record["subject"] or "",
        "Sender": lambda record: record["sender"] or "",
        "Subject ID": lambda record: record["subject_id"] or "",
        "Email Hash": lambda record: record["email_hash"] or "",
        "URLs": lambda record: record["urls_parsed"] or [],
        "Callback Numbers": lambda record: record["callback_numbers_parsed"] or [],
    }

    # Helper function to extract unique values from a column
    def _extract_unique_values(records: list[dict], column_name: str, accessor) -> list[str]:
        """Extract unique, non-empty values from a column."""
        values = set()
        for record in records:
            value = accessor(record)
            if isinstance(value, list):
                # For list fields (URLs, Callback Numbers), add each item
                for item in value:
                    if item and str(item).strip():
                        values.add(str(item).strip())
            elif value and str(value).strip():
                values.add(str(value).strip())
        return sorted(list(values))

    def _filter_match(value, selected_values: list[str], match_type: str) -> bool:
        """Check if a value matches the filter criteria."""
        if isinstance(value, list):
            # For list fields, check if any item in the list matches
            value_strs = [str(v).lower().strip() for v in value if v]
            selected_lower = [str(s).lower().strip() for s in selected_values]
            
            if match_type == "include":
                # Include: at least one item in value must be in selected_values
                return any(v in selected_lower for v in value_strs)
            else:  # exclude
                # Exclude: no item in value should be in selected_values
                return not any(v in selected_lower for v in value_strs)
        else:
            # For string fields, check if the value matches
            value_str = str(value).lower().strip() if value else ""
            selected_lower = [str(s).lower().strip() for s in selected_values]
            
            if match_type == "include":
                # Include: value must be in selected_values
                return value_str in selected_lower
            else:  # exclude
                # Exclude: value must not be in selected_values
                return value_str not in selected_lower

    # Initialize filter state in session
    if "active_filters" not in st.session_state:
        st.session_state["active_filters"] = []

    # Advanced Filters UI
    with st.expander("Advanced Filters", expanded=False):
        st.markdown("**Add multiple filters to narrow down results. All filters are applied with AND logic.**")
        
        # Display active filters
        if st.session_state["active_filters"]:
            st.markdown("**Active Filters:**")
            for idx, filter_config in enumerate(st.session_state["active_filters"]):
                col_name = filter_config["column"]
                selected_values = filter_config["values"]
                filter_type = filter_config.get("type", "include")  # include or exclude
                
                with st.container(border=True):
                    filter_col1, filter_col2, filter_col3 = st.columns([3, 2, 1])
                    with filter_col1:
                        st.markdown(f"**{col_name}** ({filter_type})")
                    with filter_col2:
                        if selected_values:
                            display_text = ", ".join(selected_values[:3])
                            if len(selected_values) > 3:
                                display_text += f" (+{len(selected_values) - 3} more)"
                            st.caption(display_text)
                        else:
                            st.caption("No values selected")
                    with filter_col3:
                        if st.button("Remove", key=f"remove_filter_{idx}", use_container_width=True):
                            st.session_state["active_filters"].pop(idx)
                            st.rerun()
        
        # Add new filter section
        st.markdown("---")
        st.markdown("**Add New Filter:**")
        
        filter_col1, filter_col2 = st.columns([2, 1])
        with filter_col1:
            available_columns = list(column_accessors.keys())
            # Exclude columns that already have filters
            existing_filter_columns = {f["column"] for f in st.session_state["active_filters"]}
            new_filter_columns = [col for col in available_columns if col not in existing_filter_columns]
            
            if new_filter_columns:
                new_filter_column = st.selectbox(
                    "Select column to filter",
                    options=new_filter_columns,
                    key="new_filter_column",
                    help="Select a column that doesn't already have an active filter"
                )
            else:
                st.info("All available columns already have filters. Remove a filter to add a new one.")
                new_filter_column = None
        with filter_col2:
            filter_type = st.selectbox(
                "Filter type",
                options=["Include", "Exclude"],
                key="new_filter_type",
                help="Include: show records matching selected values. Exclude: hide records matching selected values."
            )
        
        if new_filter_column:
            # Extract unique values for the selected column
            accessor = column_accessors[new_filter_column]
            unique_values = _extract_unique_values(filtered, new_filter_column, accessor)
            
            if unique_values:
                selected_values = st.multiselect(
                    f"Select values to {filter_type.lower()}",
                    options=unique_values,
                    key=f"new_filter_values_{new_filter_column}",
                    help=f"Found {len(unique_values)} unique values. Select one or more to filter by."
                )
                
                add_filter_col1, add_filter_col2 = st.columns([1, 1])
                with add_filter_col1:
                    if st.button("Add Filter", key="add_filter_button", use_container_width=True, disabled=not selected_values):
                        new_filter = {
                            "column": new_filter_column,
                            "values": selected_values,
                            "type": filter_type.lower(),
                        }
                        st.session_state["active_filters"].append(new_filter)
                        st.rerun()
                with add_filter_col2:
                    if st.button("Clear All Filters", key="clear_all_filters", use_container_width=True):
                        st.session_state["active_filters"] = []
                        st.rerun()
            else:
                st.info(f"No unique values found in '{new_filter_column}' column for the current search results.")
        
        # Sorting options
        st.markdown("---")
        st.markdown("**Sorting:**")
        sort_col1, sort_col2 = st.columns(2)
        with sort_col1:
            sort_column = st.selectbox(
                "Sort by",
                options=["ID", "Subject", "Sender", "Date Sent", "Subject ID"],
                index=0,
                key="sort_column_select",
            )
        with sort_col2:
            sort_order = st.selectbox(
                "Sort order",
                options=["Ascending", "Descending"],
                index=0,
                key="sort_order_select",
            )

    # Apply all active filters
    for filter_config in st.session_state["active_filters"]:
        column_name = filter_config["column"]
        selected_values = filter_config["values"]
        filter_type = filter_config.get("type", "include")
        accessor = column_accessors[column_name]
        
        if not selected_values:
            continue
        
        if filter_type == "include":
            # Include: record must match at least one of the selected values
            filtered = [
                record for record in filtered
                if _filter_match(accessor(record), selected_values, match_type="include")
            ]
        else:  # exclude
            # Exclude: record must not match any of the selected values
            filtered = [
                record for record in filtered
                if _filter_match(accessor(record), selected_values, match_type="exclude")
            ]

    sort_key_map = {
        "ID": lambda record: record["id"] or 0,
        "Subject": lambda record: (record["subject"] or "").lower(),
        "Sender": lambda record: (record["sender"] or "").lower(),
        "Date Sent": lambda record: record["date_sent"] or "",
        "Subject ID": lambda record: (record["subject_id"] or "").lower(),
    }
    filtered = sorted(filtered, key=sort_key_map[sort_column], reverse=sort_order == "Descending")

    if not filtered:
        st.warning("No emails matched the current search criteria.")
        return

    page_size = st.slider("Rows per page", min_value=25, max_value=200, step=25, value=50)
    total_records = len(filtered)
    total_pages = max(1, math.ceil(total_records / page_size))
    current_page = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
    start = (current_page - 1) * page_size
    end = start + page_size
    page_records = filtered[start:end]

    # Get knowledge columns to display
    knowledge_columns = []
    try:
        with session_scope() as session:
            from app.db.models import KnowledgeTableMetadata
            tn_metadata = (
                session.query(KnowledgeTableMetadata)
                .filter(KnowledgeTableMetadata.table_name == "Knowledge_TNs")
                .first()
            )
            domain_metadata = (
                session.query(KnowledgeTableMetadata)
                .filter(KnowledgeTableMetadata.table_name == "Knowledge_Domains")
                .first()
            )
            
            if tn_metadata and tn_metadata.selected_columns:
                knowledge_columns.extend(tn_metadata.selected_columns)
            if domain_metadata and domain_metadata.selected_columns:
                knowledge_columns.extend(domain_metadata.selected_columns)
        
        # Remove duplicates while preserving order
        knowledge_columns = list(dict.fromkeys(knowledge_columns))
    except Exception as exc:
        logger.warning("Failed to load knowledge columns for display: %s", exc)
        knowledge_columns = []  # Fallback to empty list
    
    table_rows = []
    for record in page_records:
        row = {
            # Existing columns
            "ID": record["id"],
            "Status": record.get("parse_status") or "unknown",
            "Subject": record.get("subject") or "",
            "Sender": record.get("sender") or "",
            "Date Sent": _format_date_for_display(record.get("date_sent")),
            "Date Reported": _format_date_for_display(record.get("date_reported")),
            "Subject ID": record.get("subject_id") or "",
            "Sending Source": record.get("sending_source_raw") or "",
            "Additional Contacts": record.get("additional_contacts") or "",
            "Model Confidence": (
                f"{record['model_confidence']:.2f}"
                if record.get("model_confidence") is not None
                else ""
            ),
            "URLs": ", ".join(record.get("urls_parsed", [])),
            "Full URLs": ", ".join(record.get("urls_raw", [])),
            "Callback Numbers": ", ".join(record.get("callback_numbers_parsed", [])),
            "Body Text": _html_to_text_for_display(record.get("body_html")),
        }
        
        # Add knowledge columns
        knowledge_data = record.get("knowledge_data") or {}
        if not isinstance(knowledge_data, dict):
            # Handle corrupted knowledge_data
            logger.warning("Invalid knowledge_data type for email %d: %s", record["id"], type(knowledge_data))
            knowledge_data = {}
        
        for col in knowledge_columns:
            try:
                value = knowledge_data.get(col, "")
                # Ensure value is serializable for display
                if value is None:
                    row[col] = ""
                else:
                    row[col] = str(value)
            except Exception as exc:
                logger.warning("Error accessing knowledge column %s for email %d: %s", col, record["id"], exc)
                row[col] = ""
        
        table_rows.append(row)

    st.subheader("Batch Summary")
    st.caption(f"Showing {len(page_records)} of {total_records} results (page {current_page}/{total_pages}).")
    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

    available_ids = [row["ID"] for row in table_rows]
    
    # Create lookup dictionary for email details (for informative labels)
    # Use all filtered records, not just current page, for better label support
    email_lookup = {record["id"]: record for record in filtered}
    
    def format_email_label(email_id: int) -> str:
        """Format email label with Subject ID, URLs, and callback numbers."""
        email = email_lookup.get(email_id)
        if not email:
            return f"Email #{email_id}"
        
        parts = [f"#{email_id}"]
        
        # Add Subject ID
        if email.get("subject_id"):
            parts.append(f"ID: {email['subject_id']}")
        
        # Add URLs (first URL, truncated if long)
        urls = email.get("urls_parsed", [])
        if urls:
            url_display = urls[0][:40] + "..." if len(urls[0]) > 40 else urls[0]
            if len(urls) > 1:
                url_display += f" (+{len(urls)-1})"
            parts.append(f"URLs: {url_display}")
        
        # Add Callback Numbers (first 2)
        callbacks = email.get("callback_numbers_parsed", [])
        if callbacks:
            callback_display = ", ".join(callbacks[:2])
            if len(callbacks) > 2:
                callback_display += f" (+{len(callbacks)-2})"
            parts.append(f"Callbacks: {callback_display}")
        
        return " | ".join(parts)

    if "report_artifacts" not in st.session_state:
        st.session_state["report_artifacts"] = None

    # Initialize report selection in session state if not exists
    if "report_selection" not in st.session_state:
        st.session_state["report_selection"] = available_ids.copy() if available_ids else []
    
    # Add/Remove all buttons for report selection
    report_button_cols = st.columns([1, 1, 2])
    with report_button_cols[0]:
        if st.button("Add All", key="report_add_all", use_container_width=True):
            st.session_state["report_selection"] = available_ids.copy() if available_ids else []
            st.rerun()
    with report_button_cols[1]:
        if st.button("Remove All", key="report_remove_all", use_container_width=True):
            st.session_state["report_selection"] = []
            st.rerun()
    
    # Get current selection from session state (will be updated by widget)
    current_selection = st.session_state.get("report_selection", available_ids.copy() if available_ids else [])
    
    report_selection = st.multiselect(
        "Emails to include in HTML report",
        options=available_ids,
        default=current_selection,
        format_func=format_email_label,
        key="report_selection",
    )
    
    # Note: st.session_state["report_selection"] is automatically updated by the widget
    # No need to manually update it here

    finalize_col, report_col, knowledge_col, promote_col = st.columns([1, 1, 1, 2])

    with finalize_col:
        if st.button("Finalize Batch", width="stretch"):
            with session_scope() as session:
                result = finalize_batch(session, state.selected_batch_id, config=state.config)
            if result:
                state.add_notification(f"Finalized batch {result.batch_name}")
                st.success("Batch finalized and archived.")
                st.rerun()
            else:
                st.error("Unable to finalize batch. Check logs for details.")

    with report_col:
        generate_report = st.button("Generate HTML Report", disabled=not report_selection, width="stretch")
        generate_takedown = st.button("Generate Takedown Bundle", disabled=not report_selection, width="stretch",
                                     help="Create CSV and images folder for takedown requests")
    
    with knowledge_col:
        add_knowledge = st.button("Add Knowledge", disabled=not report_selection, width="stretch",
                                 help="Match phone numbers and URLs against knowledge tables and add selected columns to batch")
    if generate_takedown:
        with session_scope() as session:
            from app.services.takedown_bundle import generate_takedown_bundle
            result = generate_takedown_bundle(
                session,
                email_ids=report_selection,
                config=state.config,
            )
        if result:
            state.add_notification(f"Generated takedown bundle: {result.email_count} emails, {result.image_count} images")
            st.success(
                f"Takedown bundle created:\n"
                f"- Directory: `{result.bundle_dir}`\n"
                f"- CSV: `{result.csv_path.name}`\n"
                f"- Images: {result.image_count} images in `{result.images_dir.name}/`\n"
                f"- Skipped: {result.skipped_images} images"
            )
            # Provide download button for CSV
            csv_content = result.csv_path.read_bytes()
            st.download_button(
                label="Download Takedown CSV",
                data=csv_content,
                file_name=result.csv_path.name,
                mime="text/csv",
                key=f"download_takedown_csv_{result.bundle_dir.name}",
            )
        else:
            st.error("Takedown bundle generation failed. Check logs for details.")
    if add_knowledge:
        with session_scope() as session:
            from app.services.knowledge import add_knowledge_to_emails
            try:
                result = add_knowledge_to_emails(session, email_ids=report_selection)
                session.commit()
                
                # Build notification message
                notification_parts = []
                if result.matched_tns > 0:
                    notification_parts.append(f"{result.matched_tns} phone matches")
                if result.matched_domains > 0:
                    notification_parts.append(f"{result.matched_domains} domain matches")
                if result.updated > 0:
                    notification_parts.append(f"{result.updated} emails updated")
                if result.errors > 0:
                    notification_parts.append(f"{result.errors} errors")
                
                if notification_parts:
                    state.add_notification(f"Added knowledge: {', '.join(notification_parts)}")
                
                # Show detailed results
                if result.updated > 0:
                    success_msg = f"Knowledge enrichment completed:\n"
                    if result.matched_tns > 0:
                        success_msg += f"- Phone number matches: {result.matched_tns}\n"
                    if result.matched_domains > 0:
                        success_msg += f"- Domain matches: {result.matched_domains}\n"
                    success_msg += f"- Emails updated: {result.updated}"
                    st.success(success_msg)
                else:
                    st.warning("⚠️ No emails were updated. Check that knowledge tables are initialized and columns are selected.")
                
                if result.errors > 0:
                    st.warning(f"⚠️ {result.errors} emails had errors during processing.")
                    if result.error_details:
                        with st.expander(f"View {len(result.error_details)} error details", expanded=False):
                            for error in result.error_details[:20]:  # Show first 20 errors
                                st.text(error)
                            if len(result.error_details) > 20:
                                st.caption(f"... and {len(result.error_details) - 20} more errors")
                
                if result.updated > 0:
                    st.rerun()
            except ValueError as exc:
                st.error(f"Cannot add knowledge: {exc}")
            except Exception as exc:
                st.error(f"Failed to add knowledge: {exc}")
                logger.exception("Failed to add knowledge to emails")
    
    if generate_report:
        with session_scope() as session:
            artifacts = generate_email_report(
                session,
                report_selection,
                config=state.config,
            )
        if artifacts:
            state.add_notification(f"Generated report {artifacts.html_path.name}")
            st.session_state["report_artifacts"] = {
                "html": str(artifacts.html_path),
                "csv_text": str(artifacts.csv_text_path),
                "csv_full": str(artifacts.csv_full_path),
                "attachments_zip": str(artifacts.attachments_zip_path) if artifacts.attachments_zip_path else "",
                "emails_zip": str(artifacts.emails_zip_path) if artifacts.emails_zip_path else "",
            }
        else:
            st.error("Report generation failed or produced no output.")

    artefacts_state = st.session_state.get("report_artifacts") or None
    if artefacts_state:
        st.info("Latest report artefacts available below.")
        artifact_cols = st.columns(2)
        html_path = Path(artefacts_state["html"])
        csv_text_path = Path(artefacts_state["csv_text"])
        csv_full_path = Path(artefacts_state["csv_full"])
        with artifact_cols[0]:
            if html_path.exists():
                # Read file content into memory before passing to download button
                html_content = html_path.read_bytes()
                st.download_button(
                    label="Download HTML Report",
                    data=html_content,
                    file_name=html_path.name,
                    mime="text/html",
                    key=f"download_report_{html_path.stem}",
                )
            if csv_text_path.exists():
                # Read file content into memory before passing to download button
                csv_text_content = csv_text_path.read_bytes()
                st.download_button(
                    label="Download CSV (Text)",
                    data=csv_text_content,
                    file_name=csv_text_path.name,
                    mime="text/csv",
                    key=f"download_csv_text_{csv_text_path.stem}",
                )
        with artifact_cols[1]:
            if csv_full_path.exists():
                # Read file content into memory before passing to download button
                csv_full_content = csv_full_path.read_bytes()
                st.download_button(
                    label="Download CSV (Full)",
                    data=csv_full_content,
                    file_name=csv_full_path.name,
                    mime="text/csv",
                    key=f"download_csv_full_{csv_full_path.stem}",
                )
            attachments_path = artefacts_state.get("attachments_zip")
            if attachments_path:
                path_obj = Path(attachments_path)
                if path_obj.exists():
                    # Read file content into memory before passing to download button
                    attachments_content = path_obj.read_bytes()
                    st.download_button(
                        label="Download All Attachments (ZIP)",
                        data=attachments_content,
                        file_name=path_obj.name,
                        mime="application/zip",
                        key=f"download_zip_attachments_{path_obj.stem}",
                    )
            emails_zip = artefacts_state.get("emails_zip")
            if emails_zip:
                path_obj = Path(emails_zip)
                if path_obj.exists():
                    # Read file content into memory before passing to download button
                    emails_content = path_obj.read_bytes()
                    st.download_button(
                        label="Download All Emails (ZIP)",
                        data=emails_content,
                        file_name=path_obj.name,
                        mime="application/zip",
                        key=f"download_zip_emails_{path_obj.stem}",
                    )

    # Initialize promotion selection in session state if not exists
    if "promotion_selection" not in st.session_state:
        st.session_state["promotion_selection"] = available_ids.copy() if available_ids else []
    
    # Add/Remove all buttons
    promotion_button_cols = st.columns([1, 1, 2])
    with promotion_button_cols[0]:
        if st.button("Add All", key="promotion_add_all", use_container_width=True):
            st.session_state["promotion_selection"] = available_ids.copy() if available_ids else []
            st.rerun()
    with promotion_button_cols[1]:
        if st.button("Remove All", key="promotion_remove_all", use_container_width=True):
            st.session_state["promotion_selection"] = []
            st.rerun()
    
    # Get current selection from session state (will be updated by widget)
    current_promotion_selection = st.session_state.get("promotion_selection", available_ids.copy() if available_ids else [])
    
    promotion_selection = st.multiselect(
        "Emails to promote to Standard Emails",
        options=available_ids,
        default=current_promotion_selection,
        format_func=format_email_label,
        key="promotion_selection",
    )
    
    # Note: st.session_state["promotion_selection"] is automatically updated by the widget
    # No need to manually update it here

    if promote_col.button("Promote to Standard Emails", disabled=not promotion_selection, width="stretch"):
        with session_scope() as session:
            promotion_results = promote_to_standard_emails(
                session,
                promotion_selection,
                config=state.config,
            )

        created = [result for result in promotion_results if result.created]
        skipped = [result for result in promotion_results if not result.created]

        if created:
            created_ids = ", ".join(f"#{result.email_id}" for result in created)
            state.add_notification(f"Promoted {len(created)} emails to StandardEmail: {created_ids}")
            st.success(f"Promoted {len(created)} emails to StandardEmail.")

        if skipped:
            for result in skipped:
                st.warning(f"Email #{result.email_id} skipped: {result.reason or 'Duplicate record.'}")

    if state.selected_email_id not in available_ids:
        state.selected_email_id = available_ids[0] if available_ids else None
    
    if not available_ids:
        st.info("No emails available in this batch.")
        return
    
    # Email navigation with Previous/Next buttons
    nav_col1, nav_col2, nav_col3 = st.columns([1, 3, 1])
    
    with nav_col1:
        current_index = available_ids.index(state.selected_email_id) if state.selected_email_id in available_ids else 0
        if st.button("◀ Previous", disabled=current_index == 0, use_container_width=True):
            if current_index > 0:
                state.selected_email_id = available_ids[current_index - 1]
                st.rerun()
    
    with nav_col2:
        selected_email_id = st.selectbox(
            "Select email for detail view",
            options=available_ids,
            index=current_index,
            format_func=format_email_label,
            key="email_detail_selectbox",
        )
        state.selected_email_id = selected_email_id
    
    with nav_col3:
        if st.button("Next ▶", disabled=current_index >= len(available_ids) - 1, use_container_width=True):
            if current_index < len(available_ids) - 1:
                state.selected_email_id = available_ids[current_index + 1]
                st.rerun()
    
    # Display current position
    st.caption(f"Email {current_index + 1} of {len(available_ids)}")

    with session_scope() as session:
        email_detail = get_email_detail(session, state.selected_email_id)

    if not email_detail:
        st.error("Unable to load email details.")
        return

    st.subheader("Email Details")
    with st.container(border=True):
        st.markdown("#### Metadata")
        parse_status = email_detail.get("parse_status") or "unknown"
        st.markdown(f"**Parse Status:** `{parse_status}`")
        if email_detail.get("parse_error"):
            st.error(f"Parser error: {email_detail['parse_error']}")
        if st.button(
            "Retry Parsing",
            disabled=parse_status == "success",
            key="retry_parse_button",
            width="content",
        ):
            with session_scope() as session:
                reparse_result = reparse_email(session, state.selected_email_id)
            if reparse_result and reparse_result.success:
                st.success("Parsing succeeded. Refreshing view…")
                st.rerun()
            elif reparse_result:
                st.warning(f"Parsing still failing: {reparse_result.message}")
            else:
                st.error("Unable to reparse this email (it may have been deleted).")

        metadata = [
            ("Subject", email_detail.get("subject") or "—"),
            ("Subject ID", email_detail.get("subject_id") or "—"),
            ("Sender", email_detail.get("sender") or "—"),
            ("Date Sent", email_detail.get("date_sent") or "—"),
            ("Date Reported", email_detail.get("date_reported") or "—"),
            ("Sending Source", email_detail.get("sending_source_raw") or "—"),
            ("Additional Contacts", email_detail.get("additional_contacts") or "—"),
            ("Model Confidence", email_detail.get("model_confidence") if email_detail.get("model_confidence") is not None else "—"),
            ("Message ID", email_detail.get("message_id") or "—"),
        ]

        col_a, col_b = st.columns(2)
        for index, (label, value) in enumerate(metadata):
            value_str = value if isinstance(value, str) else str(value)
            target_col = col_a if index % 2 == 0 else col_b
            target_col.markdown(f"**{label}**")
            target_col.code(value_str or "—", language="text")

        url_list = email_detail.get("urls_parsed", []) or []
        callback_list = email_detail.get("callback_numbers_parsed", []) or []

        _render_value_list("Parsed URLs", url_list)
        _render_value_list("Callback Numbers", callback_list)

        attachments = email_detail.get("attachments") or []
        _render_download_buttons(email_detail, attachments, state.config)

        with st.expander("HTML Preview & Attachments", expanded=False):
            if email_detail.get("body_html"):
                st.markdown("#### HTML Preview")
                _render_email_body(
                    email_detail["body_html"],
                    image_base64=email_detail.get("image_base64")
                )
            elif email_detail.get("body_text"):
                st.markdown("#### Plain Text Preview")
                st.code(email_detail["body_text"])

            if attachments:
                st.markdown("#### Attachments")
                for attachment in attachments:
                    file_path = Path(attachment.get("storage_path") or "")
                    file_name = attachment.get("file_name") or "attachment"
                    file_type = (attachment.get("file_type") or "").lower()
                    file_size = attachment.get("file_size") or 0

                    st.write(f"**{file_name}** — {file_type or 'unknown'}, {file_size} bytes")

                    if file_path.exists() and file_type.startswith("image"):
                        display_image_with_dialog(
                            image_path=file_path,
                            caption=file_name,
                            key=f"attachment_{attachment.get('id')}",
                        )

                    if file_path.exists():
                        # Read file content into memory before passing to download button
                        attachment_content = file_path.read_bytes()
                        st.download_button(
                            label=f"Download {file_name}",
                            data=attachment_content,
                            file_name=file_name,
                            mime=file_type or "application/octet-stream",
                            key=f"download_attachment_{attachment['id']}",
                        )
                    else:
                        st.info("Attachment file not found on disk; regenerate or re-ingest to restore.")
            else:
                st.info("No attachments associated with this email.")

    with st.expander("Edit Email Metadata", expanded=False):
        with st.form("email_detail_form", clear_on_submit=False):
            subject = st.text_input("Subject", value=email_detail.get("subject") or "")
            subject_id = st.text_input("Subject ID", value=email_detail.get("subject_id") or "")
            sender = st.text_input("Sender", value=email_detail.get("sender") or "")

            date_sent = st.text_input(
                "Date Sent (ISO)",
                value=email_detail.get("date_sent") or "",
                help="Example: 2025-11-12T19:54:38+00:00",
            )
            date_reported = st.text_input(
                "Date Reported (ISO)",
                value=email_detail.get("date_reported") or "",
                help="Example: 2025-11-12T19:54:38+00:00",
            )

            cc_text = "\n".join(email_detail.get("cc", []))
            cc_input = st.text_area("CC (one per line)", value=cc_text, height=80)

            sending_source = st.text_input(
                "Sending Source",
                value=email_detail.get("sending_source_raw") or "",
                help="Raw sending source string; parsed domains will refresh automatically.",
            )

            urls_text = "\n".join(email_detail.get("urls_parsed", []))
            urls_input = st.text_area("Parsed URLs (one per line)", value=urls_text, height=100)

            callbacks_text = "\n".join(email_detail.get("callback_numbers_parsed", []))
            callbacks_input = st.text_area("Callback Numbers (one per line)", value=callbacks_text, height=80)

            additional_contacts = st.text_area(
                "Additional Contacts",
                value=email_detail.get("additional_contacts") or "",
                height=60,
            )

            model_confidence = st.text_input(
                "Model Confidence",
                value="" if email_detail.get("model_confidence") is None else str(email_detail["model_confidence"]),
            )

            submitted = st.form_submit_button("Save Changes")

            if submitted:
                updates = {
                    "subject": subject,
                    "subject_id": subject_id,
                    "sender": sender,
                    "date_sent": date_sent.strip() or None,
                    "date_reported": date_reported.strip() or None,
                    "cc": [line.strip() for line in cc_input.splitlines()],
                    "sending_source_raw": sending_source,
                    "urls_parsed": [line.strip() for line in urls_input.splitlines()],
                    "urls_raw": [line.strip() for line in urls_input.splitlines()],
                    "callback_numbers_parsed": [line.strip() for line in callbacks_input.splitlines()],
                    "callback_numbers_raw": [line.strip() for line in callbacks_input.splitlines()],
                    "additional_contacts": additional_contacts or None,
                    "model_confidence": model_confidence.strip() if model_confidence else None,
                }
                with session_scope() as session:
                    updated = update_email_record(
                        session,
                        state.selected_email_id,
                        updates,
                        config=state.config,
                    )
                if updated:
                    state.add_notification(f"Updated email #{state.selected_email_id}")
                    st.success("Email updated.")
                    st.rerun()
                else:
                    st.error("Update failed. Please check the log for details.")


def render(state: AppState) -> None:
    st.header("Email Display")
    st.write("Ingest new batches, review parsed results, and edit metadata before upload.")

    if importlib.util.find_spec("extract_msg") is None:
        st.warning(
            "MSG ingestion is disabled because the optional `extract-msg` package is missing. "
            "Install it via `pip install extract-msg` to process `.msg` files."
        )

    with st.expander("Parser Diagnostics", expanded=False):
        caps = parser_capabilities()
        for name, info in caps.items():
            status = info.get("available")
            description = info.get("description", "")
            if status:
                st.success(f"{name}: available — {description}")
            else:
                st.warning(f"{name}: missing — {description}")

    _render_ingestion_panel(state)
    _render_batch_panel(state)