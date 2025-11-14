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
from app.services.standard_email_records import get_standard_email_detail, list_standard_email_records
from app.ui.state import AppState


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


def render(state: AppState) -> None:
    st.header("Database Email Archive")
    st.write("Review emails that have been promoted into the `standard_emails` table.")

    with session_scope() as session:
        records = list_standard_email_records(session, limit=2000)

    if not records:
        st.info("No standard emails are available yet. Promote emails from the Email Display page first.")
        return

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

    column_accessors = {
        "Subject": lambda record: record["subject"] or "",
        "Sender": lambda record: record["from_address"] or "",
        "Email Hash": lambda record: record["email_hash"] or "",
        "URLs": lambda record: " ".join(record["body_urls"]),
        "Phone Numbers": lambda record: " ".join(record["body_numbers"]),
    }

    with st.expander("Advanced Filters & Sorting", expanded=False):
        selected_column = st.selectbox("Filter Column", options=list(column_accessors.keys()))
        include_text = st.text_input("Include records containing", key="standard_include_filter").strip()
        exclude_text = st.text_input("Exclude records containing", key="standard_exclude_filter").strip()
        sort_column = st.selectbox(
            "Sort By",
            options=["Subject", "Sender", "Date Sent", "Created"],
            key="standard_sort_column",
        )
        sort_order = st.selectbox("Sort order", options=["Ascending", "Descending"], key="standard_sort_order")

    accessor = column_accessors[selected_column]
    if include_text:
        include_lower = include_text.lower()
        filtered = [record for record in filtered if include_lower in accessor(record).lower()]
    if exclude_text:
        exclude_lower = exclude_text.lower()
        filtered = [record for record in filtered if exclude_lower not in accessor(record).lower()]

    sort_key_map = {
        "Subject": lambda record: (record["subject"] or "").lower(),
        "Sender": lambda record: (record["from_address"] or "").lower(),
        "Date Sent": lambda record: record["date_sent"] or "",
        "Created": lambda record: record["created_at"] or "",
    }
    filtered = sorted(filtered, key=sort_key_map[sort_column], reverse=sort_order == "Descending")

    if not filtered:
        st.warning("No saved emails matched the current search criteria.")
        return

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
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    available_ids = [row["ID"] for row in table_rows]
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

    st.subheader("Saved Email Details")
    metadata = [
        ("Subject", detail.get("subject") or "—"),
        ("Sender", detail.get("from_address") or "—"),
        ("Email Hash", detail.get("email_hash") or "—"),
        ("Date Sent", detail.get("date_sent") or "—"),
        ("Created At", detail.get("created_at") or "—"),
        ("URLs", ", ".join(detail.get("body_urls") or []) or "—"),
        ("Phone Numbers", ", ".join(detail.get("body_numbers") or []) or "—"),
    ]

    col_a, col_b = st.columns(2)
    for index, (label, value) in enumerate(metadata):
        target = col_a if index % 2 == 0 else col_b
        target.markdown(f"**{label}:** {value}")

    with st.expander("Body Preview", expanded=False):
        if detail.get("body_html"):
            html(detail["body_html"], height=500, scrolling=True)
        else:
            st.info("No HTML body stored for this email.")

    attachments = detail.get("attachments") or []
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
                        st.image(str(path), caption=file_name, use_container_width=True)
                    except UnidentifiedImageError:
                        st.info(f"Preview not available for {file_name}.")
                    with path.open("rb") as handle:
                        st.download_button(
                            label=f"Download {file_name}",
                            data=handle.read(),
                            file_name=file_name,
                            mime=attachment.get("file_type") or "application/octet-stream",
                            key=f"download_standard_image_{attachment['id']}",
                        )

            elif category == "pdf":
                st.markdown("#### PDFs")
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
                    _render_pdf_preview(path, file_name)
                    with path.open("rb") as handle:
                        st.download_button(
                            label=f"Download {file_name}",
                            data=handle.read(),
                            file_name=file_name,
                            mime=attachment.get("file_type") or "application/pdf",
                            key=f"download_standard_pdf_{attachment['id']}",
                        )

            elif category == "csv":
                st.markdown("#### CSV Files")
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
                    _render_csv_preview(path, file_name)
                    with path.open("rb") as handle:
                        st.download_button(
                            label=f"Download {file_name}",
                            data=handle.read(),
                            file_name=file_name,
                            mime=attachment.get("file_type") or "text/csv",
                            key=f"download_standard_csv_{attachment['id']}",
                        )

            else:
                st.markdown("#### Other Attachments")
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
                    with path.open("rb") as handle:
                        st.download_button(
                            label=f"Download {file_name}",
                            data=handle.read(),
                            file_name=file_name,
                            mime=attachment.get("file_type") or "application/octet-stream",
                            key=f"download_standard_other_{attachment['id']}",
                        )

