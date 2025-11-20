"""Streamlit page for reviewing standardised emails saved to the database."""

from __future__ import annotations

import base64
import math
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, UnidentifiedImageError
from streamlit.components.v1 import html

from app.db.init_db import session_scope
from app.services.email_exports import (
    build_attachments_zip,
    build_single_email_html,
    find_original_email_bytes,
)
from app.services.reporting import generate_email_report
from app.services.standard_email_records import get_standard_email_detail, list_standard_email_records
from app.ui.state import AppState
from app.ui.utils.images import display_image_with_dialog, process_html_images


def _render_pdf_preview(file_path: Path, file_name: str) -> None:
    try:
        encoded = base64.b64encode(file_path.read_bytes()).decode("utf-8")
    except OSError as exc:  # pragma: no cover - best effort preview
        st.warning(f"Unable to preview {file_name}: {exc}")
        return
    html(
        f"""
        <iframe
            src="data:application/pdf;base64,{encoded}"
            style="width: 100%; height: 520px; border: none;"
        ></iframe>
        """,
        height=540,
    )


def _render_csv_preview(file_path: Path, file_name: str) -> None:
    try:
        df = pd.read_csv(file_path)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Unable to preview {file_name}: {exc}")
        return

    if len(df) > 200:
        st.caption(f"Previewing first 200 of {len(df)} rows.")
        st.dataframe(df.head(200), use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True)


def _render_value_list(label: str, values: list[str]) -> None:
    if not values:
        st.markdown(f"**{label}:** —")
        return
    if len(values) <= 3:
        st.markdown(f"**{label}:** {', '.join(values)}")
    else:
        with st.expander(f"{label} ({len(values)})", expanded=False):
            st.write("\n".join(values))


def _has_custom_background(body_html: str) -> bool:
    lowered = body_html.lower()
    tokens = ("background-color", "background:", "bgcolor", "background=")
    return any(token in lowered for token in tokens)


def _render_email_body(body_html: str) -> None:
    # Process HTML to convert images to thumbnails
    processed_html = process_html_images(body_html)
    
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


def _render_download_buttons(detail: dict, attachments: list[dict], config) -> None:
    with session_scope() as session:
        original_payload = find_original_email_bytes(session, config, detail.get("email_hash"))
        attachments_zip = build_attachments_zip(
            attachments,
            prefix=f"standard_email_{detail.get('id', 'attachments')}",
            session=session,
            email_hash=detail.get("email_hash"),
        )
    single_html = build_single_email_html(detail)

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
            file_name=f"standard_email_{detail.get('id', 'detail')}.html",
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
def _render_saved_email_table(state: AppState) -> tuple[list[dict], list[int]]:
    with session_scope() as session:
        records = list_standard_email_records(session, limit=2000)

    if not records:
        st.info("No standard emails are available yet. Promote emails from the Email Display page first.")
        return [], []

    state.standard_email_search = st.text_input(
        "Search subject, sender, or hash",
        value=state.standard_email_search,
        key="standard_email_search_input",
        help="Filters subject, sender, and email hash across saved emails.",
    )
    search_term = state.standard_email_search.lower().strip()

    filtered = records
    if search_term:
        filtered = [
            record
            for record in filtered
            if search_term in (record["subject"] or "").lower()
            or search_term in (record["from_address"] or "").lower()
            or search_term in (record["email_hash"] or "").lower()
        ]

    # Column accessors for filtering
    column_accessors = {
        "Subject": lambda record: record["subject"] or "",
        "Sender": lambda record: record["from_address"] or "",
        "Email Hash": lambda record: record["email_hash"] or "",
        "URLs": lambda record: record.get("body_urls", []) or [],
        "Phone Numbers": lambda record: record.get("body_numbers", []) or [],
    }

    # Helper function to extract unique values from a column
    def _extract_unique_values(records: list[dict], column_name: str, accessor) -> list[str]:
        """Extract unique, non-empty values from a column."""
        values = set()
        for record in records:
            value = accessor(record)
            if isinstance(value, list):
                # For list fields, add each item
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
    if "database_active_filters" not in st.session_state:
        st.session_state["database_active_filters"] = []

    # Advanced Filters UI
    with st.expander("Advanced Filters & Sorting", expanded=False):
        st.markdown("**Add multiple filters to narrow down results. All filters are applied with AND logic.**")
        
        # Display active filters
        if st.session_state["database_active_filters"]:
            st.markdown("**Active Filters:**")
            for idx, filter_config in enumerate(st.session_state["database_active_filters"]):
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
                        if st.button("Remove", key=f"remove_database_filter_{idx}", use_container_width=True):
                            st.session_state["database_active_filters"].pop(idx)
                            st.rerun()
        
        # Add new filter section
        st.markdown("---")
        st.markdown("**Add New Filter:**")
        
        filter_col1, filter_col2 = st.columns([2, 1])
        with filter_col1:
            available_columns = list(column_accessors.keys())
            # Exclude columns that already have filters
            existing_filter_columns = {f["column"] for f in st.session_state["database_active_filters"]}
            new_filter_columns = [col for col in available_columns if col not in existing_filter_columns]
            
            if new_filter_columns:
                new_filter_column = st.selectbox(
                    "Select column to filter",
                    options=new_filter_columns,
                    key="new_database_filter_column",
                    help="Select a column that doesn't already have an active filter"
                )
            else:
                st.info("All available columns already have filters. Remove a filter to add a new one.")
                new_filter_column = None
        with filter_col2:
            filter_type = st.selectbox(
                "Filter type",
                options=["Include", "Exclude"],
                key="new_database_filter_type",
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
                    key=f"new_database_filter_values_{new_filter_column}",
                    help=f"Found {len(unique_values)} unique values. Select one or more to filter by."
                )
                
                add_filter_col1, add_filter_col2 = st.columns([1, 1])
                with add_filter_col1:
                    if st.button("Add Filter", key="add_database_filter_button", use_container_width=True, disabled=not selected_values):
                        new_filter = {
                            "column": new_filter_column,
                            "values": selected_values,
                            "type": filter_type.lower(),
                        }
                        st.session_state["database_active_filters"].append(new_filter)
                        st.rerun()
                with add_filter_col2:
                    if st.button("Clear All Filters", key="clear_all_database_filters", use_container_width=True):
                        st.session_state["database_active_filters"] = []
                        st.rerun()
            else:
                st.info(f"No unique values found in '{new_filter_column}' column for the current search results.")
        
        # Sorting options
        st.markdown("---")
        st.markdown("**Sorting:**")
        sort_col1, sort_col2 = st.columns(2)
        with sort_col1:
            sort_column = st.selectbox(
                "Sort By",
                options=["Subject", "Sender", "Date Sent", "Created"],
                index=0,
                key="database_sort_column_select",
            )
        with sort_col2:
            sort_order = st.selectbox(
                "Sort order",
                options=["Ascending", "Descending"],
                index=0,
                key="database_sort_order_select",
            )

    # Apply all active filters
    for filter_config in st.session_state["database_active_filters"]:
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
        "Subject": lambda record: (record["subject"] or "").lower(),
        "Sender": lambda record: (record["from_address"] or "").lower(),
        "Date Sent": lambda record: record["date_sent"] or "",
        "Created": lambda record: record["created_at"] or "",
    }
    filtered = sorted(filtered, key=sort_key_map[sort_column], reverse=sort_order == "Descending")

    if not filtered:
        st.warning("No saved emails matched the current search criteria.")
        return [], []

    page_size = st.slider("Rows per page", min_value=25, max_value=200, step=25, value=50)
    total_records = len(filtered)
    total_pages = max(1, math.ceil(total_records / page_size))
    current_page = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
    start = (current_page - 1) * page_size
    end = start + page_size
    page_records = filtered[start:end]

    table_rows = [
        {
            "ID": record["id"],
            "Subject": record["subject"],
            "Sender": record["from_address"],
            "Date Sent": record["date_sent"],
            "Email Hash": record["email_hash"],
            "Images": record["attachment_counts"]["image"],
            "PDFs": record["attachment_counts"]["pdf"],
            "CSVs": record["attachment_counts"]["csv"],
        }
        for record in page_records
    ]

    st.subheader("Saved Email Summary")
    st.caption(f"Showing {len(page_records)} of {total_records} saved emails (page {current_page}/{total_pages}).")
    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

    report_selection = st.multiselect(
        "Select emails for HTML report",
        options=[record["id"] for record in filtered],
        default=[record["id"] for record in filtered],
        format_func=lambda record_id: f"Email #{record_id}",
        key="standard_report_selection",
    )

    if st.button("Generate HTML Report (Saved Emails)", disabled=not report_selection, width="stretch"):
        with session_scope() as session:
            artifacts = generate_email_report(session, report_selection, config=state.config)
        if artifacts:
            st.success(f"Generated report {artifacts.html_path.name}")
            st.session_state["standard_report_artifacts"] = {
                "html": str(artifacts.html_path),
                "csv_text": str(artifacts.csv_text_path),
                "csv_full": str(artifacts.csv_full_path),
                "attachments_zip": str(artifacts.attachments_zip_path) if artifacts.attachments_zip_path else "",
                "emails_zip": str(artifacts.emails_zip_path) if artifacts.emails_zip_path else "",
            }
        else:
            st.error("Report generation failed or produced no output.")

    artifact_state = st.session_state.get("standard_report_artifacts")
    if artifact_state:
        st.info("Latest report artefacts available below.")
        artifact_cols = st.columns(5)
        html_path = Path(artifact_state["html"])
        csv_text_path = Path(artifact_state["csv_text"])
        csv_full_path = Path(artifact_state["csv_full"])

        with artifact_cols[0]:
            if html_path.exists():
                with html_path.open("rb") as handle:
                    st.download_button(
                        label="Download HTML Report",
                        data=handle.read(),
                        file_name=html_path.name,
                        mime="text/html",
                        key=f"download_standard_report_{html_path.stem}",
                        width="stretch",
                    )
        with artifact_cols[1]:
            if csv_text_path.exists():
                with csv_text_path.open("rb") as handle:
                    st.download_button(
                        label="Download CSV (Text)",
                        data=handle.read(),
                        file_name=csv_text_path.name,
                        mime="text/csv",
                        key=f"download_standard_csv_text_{csv_text_path.stem}",
                        width="stretch",
                    )
        with artifact_cols[2]:
            if csv_full_path.exists():
                with csv_full_path.open("rb") as handle:
                    st.download_button(
                        label="Download CSV (Full)",
                        data=handle.read(),
                        file_name=csv_full_path.name,
                        mime="text/csv",
                        key=f"download_standard_csv_full_{csv_full_path.stem}",
                        width="stretch",
                    )
        if artifact_state.get("attachments_zip"):
            path_obj = Path(artifact_state["attachments_zip"])
            if path_obj.exists():
                with artifact_cols[3]:
                    with path_obj.open("rb") as handle:
                        st.download_button(
                            label="All Attachments (ZIP)",
                            data=handle.read(),
                            file_name=path_obj.name,
                            mime="application/zip",
                            key=f"download_standard_attachments_zip_{path_obj.stem}",
                            width="stretch",
                        )
        if artifact_state.get("emails_zip"):
            path_obj = Path(artifact_state["emails_zip"])
            if path_obj.exists():
                with artifact_cols[4]:
                    with path_obj.open("rb") as handle:
                        st.download_button(
                            label="All Emails (ZIP)",
                            data=handle.read(),
                            file_name=path_obj.name,
                            mime="application/zip",
                            key=f"download_standard_emails_zip_{path_obj.stem}",
                            width="stretch",
                        )

    available_ids = [row["ID"] for row in table_rows]
    return filtered, available_ids


@st.fragment
def _render_saved_email_detail(state: AppState, detail: dict) -> None:
    st.subheader("Saved Email Details")
    with st.container(border=True):
        st.markdown("#### Metadata")
        metadata = [
            ("Subject", detail.get("subject") or "—"),
            ("Sender", detail.get("from_address") or "—"),
            ("Email Hash", detail.get("email_hash") or "—"),
            ("Date Sent", detail.get("date_sent") or "—"),
            ("Created At", detail.get("created_at") or "—"),
        ]

        col_a, col_b = st.columns(2)
        for index, (label, value) in enumerate(metadata):
            value_str = value if isinstance(value, str) else str(value)
            target = col_a if index % 2 == 0 else col_b
            target.markdown(f"**{label}**")
            target.code(value_str or "—", language="text")

        _render_value_list("URLs", detail.get("body_urls") or [])
        _render_value_list("Phone Numbers", detail.get("body_numbers") or [])

        attachments = detail.get("attachments") or []
        _render_download_buttons(detail, attachments, state.config)

        with st.expander("Body Preview", expanded=False):
            if detail.get("body_html"):
                _render_email_body(detail["body_html"])
            else:
                st.info("No HTML body stored for this email.")

        if not attachments:
            st.info("No attachments linked to this saved email.")
            return

        grouped = {"image": [], "pdf": [], "csv": [], "other": []}
        for attachment in attachments:
            category = attachment.get("category") or "other"
            grouped.setdefault(category, []).append(attachment)

        with st.expander("Attachments & Previews", expanded=True):
            for category, items in grouped.items():
                if not items:
                    continue

                if category == "image":
                    st.markdown("#### Images")
                    for attachment in items:
                        file_name = attachment["file_name"]
                        storage_path = attachment.get("storage_path")
                        if not storage_path:
                            st.warning(f"{file_name} missing storage path.")
                            continue
                        path = Path(storage_path)
                        if not path.exists():
                            st.warning(f"{file_name} not found on disk.")
                            continue
                        try:
                            with path.open("rb") as fh:
                                Image.open(fh)
                            display_image_with_dialog(
                                image_path=path,
                                caption=file_name,
                                key=f"db_attachment_{record_id}_{file_name}",
                            )
                        except UnidentifiedImageError:
                            st.info(f"{file_name}: preview not available for this image type.")
                elif category == "pdf":
                    st.markdown("#### PDFs")
                    for attachment in items:
                        st.code(f"{attachment['file_name']} · {attachment['display_size']}")
                elif category == "csv":
                    st.markdown("#### CSVs")
                    for attachment in items:
                        st.code(f"{attachment['file_name']} · {attachment['display_size']}")
                else:
                    st.markdown("#### Other Attachments")
                    for attachment in items:
                        st.code(f"{attachment['file_name']} · {attachment['display_size']}")

        st.divider()
def render(state: AppState) -> None:
    st.header("Database Email Archive")
    st.write("Review emails that have been promoted into the `standard_emails` table.")

    filtered_records, available_ids = _render_saved_email_table(state)
    if not filtered_records or not available_ids:
        return

    if state.selected_standard_email_id not in available_ids:
        state.selected_standard_email_id = available_ids[0]

    selected_id = st.selectbox(
        "Select email for detail view",
        options=available_ids,
        index=available_ids.index(state.selected_standard_email_id),
        format_func=lambda record_id: f"Email #{record_id}",
    )
    state.selected_standard_email_id = selected_id

    with session_scope() as session:
        detail = get_standard_email_detail(session, selected_id)

    if not detail:
        st.error("Unable to load saved email details.")
        return

    _render_saved_email_detail(state, detail)
    return

