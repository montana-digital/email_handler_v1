"""Attachments page with viewing and export workflows."""

from __future__ import annotations

from datetime import datetime
import math

import pandas as pd
import streamlit as st

from app.db.init_db import session_scope
from app.services.attachments import (
    AttachmentCategory,
    export_attachments,
    list_attachment_records,
)
from app.services.email_records import get_batches
from app.ui.state import AppState


def render(state: AppState) -> None:
    st.header("Attachments")
    st.write("Inspect extracted attachments and perform bulk download/export operations.")

    with session_scope() as session:
        batches = get_batches(session)

    batch_options = {0: "All Batches"}
    for batch in batches:
        batch_options[batch.id] = f"{batch.batch_name} ({batch.record_count} emails)"

    default_batch_key = state.selected_batch_id if state.selected_batch_id in batch_options else 0
    selected_batch_key = st.selectbox(
        "Select batch",
        options=list(batch_options.keys()),
        index=list(batch_options.keys()).index(default_batch_key),
        format_func=lambda value: batch_options[value],
    )
    state.selected_batch_id = selected_batch_key if selected_batch_key != 0 else None

    category_map = {
        "All": None,
        "Images": AttachmentCategory.IMAGES,
        "Emails": AttachmentCategory.EMAILS,
        "Other": AttachmentCategory.OTHER,
    }
    category_label = st.selectbox("Attachment Category", options=list(category_map.keys()))
    state.attachments_filter = category_label
    category_filter = category_map[category_label]

    with session_scope() as session:
        attachments = list_attachment_records(
            session,
            batch_id=state.selected_batch_id,
            category=category_filter,
        )

    if not attachments:
        st.info("No attachments found for the current filters.")
        return

    page_size = st.slider("Rows per page", min_value=50, max_value=500, step=50, value=200)
    total_records = len(attachments)
    total_pages = max(1, math.ceil(total_records / page_size))
    current_page = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
    start = (current_page - 1) * page_size
    end = start + page_size
    page_records = attachments[start:end]

    df = pd.DataFrame(
        [
            {
                "ID": record["id"],
                "File Name": record["file_name"],
                "Category": record["category"],
                "Size (KB)": round((record["file_size"] or 0) / 1024, 2),
                "Subject": record["email_subject"],
                "Sender": record["email_sender"],
                "Batch": record["batch_name"] or "N/A",
            }
            for record in page_records
        ]
    )
    st.caption(f"Showing {len(page_records)} of {total_records} attachments (page {current_page}/{total_pages}).")
    st.dataframe(df, use_container_width=True, hide_index=True)

    selected_ids = st.multiselect(
        "Select attachments to export",
        options=[record["id"] for record in page_records],
        format_func=lambda attachment_id: next(
            (record["file_name"] for record in attachments if record["id"] == attachment_id),
            str(attachment_id),
        ),
    )

    if selected_ids:
        if st.button("Export Selected Attachments"):
            destination_root = (
                state.config.output_dir
                / "exports"
                / f"attachments_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
            )
            with session_scope() as session:
                results, archive_path = export_attachments(
                    session,
                    attachment_ids=selected_ids,
                    destination_root=destination_root,
                )

            if results:
                state.add_notification(
                    f"Exported {len(results)} attachments to {destination_root}"
                )
                st.success(f"Exported {len(results)} attachments to {destination_root}")

                if archive_path and archive_path.exists():
                    with archive_path.open("rb") as handle:
                        st.download_button(
                            label="Download ZIP",
                            data=handle.read(),
                            file_name=archive_path.name,
                            mime="application/zip",
                            key=f"download_zip_{archive_path.stem}",
                        )
            else:
                st.warning("No attachments were exported. They may lack storage paths.")

    # Detailed view for single attachment
    selected_detail_id = st.selectbox(
        "Preview attachment details",
        options=[record["id"] for record in attachments],
        format_func=lambda attachment_id: next(
            (record["file_name"] for record in attachments if record["id"] == attachment_id),
            str(attachment_id),
        ),
    )

    detail = next(record for record in attachments if record["id"] == selected_detail_id)
    st.subheader("Attachment Metadata")
    st.json(
        {
            "File Name": detail["file_name"],
            "Category": detail["category"],
            "File Size Bytes": detail["file_size"],
            "Subject ID": detail["subject_id"],
            "Email Subject": detail["email_subject"],
            "Email Sender": detail["email_sender"],
            "Batch": detail["batch_name"],
            "Storage Path": detail["storage_path"],
        }
    )