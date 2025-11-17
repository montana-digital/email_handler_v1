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
    generate_image_grid_report,
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

    column_accessors = {
        "File Name": lambda record: record["file_name"] or "",
        "Category": lambda record: record["category"] or "",
        "Subject": lambda record: record["email_subject"] or "",
        "Subject ID": lambda record: record["subject_id"] or "",
        "Sender": lambda record: record["email_sender"] or "",
        "Batch": lambda record: record["batch_name"] or "",
    }

    with st.expander("Advanced Filters", expanded=False):
        selected_column = st.selectbox("Filter column", options=list(column_accessors.keys()))
        include_text = st.text_input("Include attachments containing", key="attachments_include").strip()
        exclude_text = st.text_input("Exclude attachments containing", key="attachments_exclude").strip()
        # Subject ID filter
        subject_id_filter = st.text_input("Filter by Subject ID", key="attachments_subject_id_filter").strip()
        sort_column = st.selectbox("Sort by", options=["File Name", "Category", "Subject", "Subject ID", "Sender", "Batch", "Size"])
        sort_order = st.selectbox("Sort order", options=["Ascending", "Descending"], index=0)  # Default to Ascending

    accessor = column_accessors[selected_column]
    filtered_records = attachments
    if include_text:
        include_lower = include_text.lower()
        filtered_records = [record for record in filtered_records if include_lower in accessor(record).lower()]
    if exclude_text:
        exclude_lower = exclude_text.lower()
        filtered_records = [record for record in filtered_records if exclude_lower not in accessor(record).lower()]
    # Filter by Subject ID
    if subject_id_filter:
        subject_id_lower = subject_id_filter.lower()
        filtered_records = [record for record in filtered_records if subject_id_lower in (record.get("subject_id") or "").lower()]

    sort_key_map = {
        "File Name": lambda record: (record["file_name"] or "").lower(),
        "Category": lambda record: (record["category"] or "").lower(),
        "Subject": lambda record: (record["email_subject"] or "").lower(),
        "Subject ID": lambda record: (record.get("subject_id") or "").lower(),
        "Sender": lambda record: (record["email_sender"] or "").lower(),
        "Batch": lambda record: (record["batch_name"] or "").lower(),
        "Size": lambda record: record["file_size"] or 0,
    }
    filtered_records = sorted(filtered_records, key=sort_key_map[sort_column], reverse=sort_order == "Descending")

    if not filtered_records:
        st.warning("No attachments matched the current search criteria.")
        return

    page_size = st.slider("Rows per page", min_value=50, max_value=500, step=50, value=200)
    total_records = len(filtered_records)
    total_pages = max(1, math.ceil(total_records / page_size))
    current_page = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
    start = (current_page - 1) * page_size
    end = start + page_size
    page_records = filtered_records[start:end]

    df = pd.DataFrame(
        [
            {
                "ID": record["id"],
                "File Name": record["file_name"],
                "Category": record["category"],
                "Size (KB)": round((record["file_size"] or 0) / 1024, 2),
                "Subject ID": record.get("subject_id") or "N/A",
                "Subject": record["email_subject"],
                "Sender": record["email_sender"],
                "Batch": record["batch_name"] or "N/A",
            }
            for record in page_records
        ]
    )
    st.caption(f"Showing {len(page_records)} of {total_records} attachments (page {current_page}/{total_pages}).")
    st.dataframe(df, width="stretch", hide_index=True)

    # Initialize attachment selection in session state
    page_attachment_ids = [record["id"] for record in page_records]
    if "attachment_selection" not in st.session_state:
        st.session_state["attachment_selection"] = []
    
    # Add/Remove all buttons for attachment selection
    attachment_button_cols = st.columns([1, 1, 2])
    with attachment_button_cols[0]:
        if st.button("Add All", key="attachment_add_all", use_container_width=True):
            st.session_state["attachment_selection"] = page_attachment_ids.copy()
            st.rerun()
    with attachment_button_cols[1]:
        if st.button("Remove All", key="attachment_remove_all", use_container_width=True):
            st.session_state["attachment_selection"] = []
            st.rerun()
    
    # Get current selection from session state (will be updated by widget)
    current_attachment_selection = st.session_state.get("attachment_selection", [])
    
    selected_ids = st.multiselect(
        "Select attachments to export",
        options=page_attachment_ids,
        default=current_attachment_selection,
        format_func=lambda attachment_id: next(
            (f"{record['file_name']} (Subject ID: {record.get('subject_id') or 'N/A'})" 
             for record in page_records if record["id"] == attachment_id),
            str(attachment_id),
        ),
        key="attachment_selection",
    )
    
    # Note: st.session_state["attachment_selection"] is automatically updated by the widget
    # No need to manually update it here

    if selected_ids:
        # Check if all selected attachments are of the same category
        selected_records = [r for r in page_records if r["id"] in selected_ids]
        categories = {r["category"] for r in selected_records}
        is_single_category = len(categories) == 1
        single_category = list(categories)[0] if is_single_category else None
        
        # Show category-specific export button if all of one category
        if is_single_category and single_category == "images":
            st.info(f"All {len(selected_ids)} selected attachments are images. Category-specific export available.")
            category_cols = st.columns([1, 1, 1])
            with category_cols[0]:
                if st.button("Download Images Grid Report", use_container_width=True,
                           help="Generate HTML report with images in grid layout, including numbers and URLs"):
                    report_path = (
                        state.config.output_dir
                        / "reports"
                        / f"image_grid_{datetime.now().strftime('%Y%m%dT%H%M%S')}.html"
                    )
                    try:
                        with session_scope() as session:
                            generate_image_grid_report(
                                session,
                                attachment_ids=selected_ids,
                                output_path=report_path,
                            )
                        
                        if report_path.exists():
                            with report_path.open("rb") as handle:
                                st.download_button(
                                    label="Download Image Grid Report",
                                    data=handle.read(),
                                    file_name=report_path.name,
                                    mime="text/html",
                                    key=f"download_image_grid_{report_path.stem}",
                                )
                            state.add_notification(f"Generated image grid report with {len(selected_ids)} images")
                            st.success(f"Generated image grid report: {report_path.name}")
                        else:
                            st.error("Failed to generate report file")
                    except Exception as e:
                        st.error(f"Failed to generate image grid report: {e}")
                        logger.exception("Image grid report generation failed")
            
            with category_cols[1]:
                if st.button("Export Images to ZIP", use_container_width=True):
                    destination_root = (
                        state.config.output_dir
                        / "exports"
                        / f"images_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
                    )
                    with session_scope() as session:
                        results, archive_path = export_attachments(
                            session,
                            attachment_ids=selected_ids,
                            destination_root=destination_root,
                        )

                    if results:
                        state.add_notification(
                            f"Exported {len(results)} images to {destination_root}"
                        )
                        st.success(f"Exported {len(results)} images to {destination_root}")

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
                        st.warning("No images were exported. They may lack storage paths.")
            
            with category_cols[2]:
                st.caption("Select other attachments for different export options")
        else:
            # General export for mixed categories
            export_cols = st.columns([1, 1])
            with export_cols[0]:
                if st.button("Export Selected to ZIP", use_container_width=True):
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
        
        with export_cols[1]:
            # Copy email attachments to input folder
            email_attachments = [record for record in page_records 
                                if record["id"] in selected_ids 
                                and record["category"] == "emails"]
            if email_attachments:
                if st.button("Copy Email Attachments to Input Folder", use_container_width=True, 
                           help="Copies selected EML/MSG attachments to the input folder for reprocessing"):
                    import shutil
                    copied_count = 0
                    failed_count = 0
                    
                    with session_scope() as session:
                        from app.db.models import Attachment
                        attachments = session.query(Attachment).filter(
                            Attachment.id.in_([a["id"] for a in email_attachments])
                        ).all()
                        
                        for attachment in attachments:
                            if not attachment.storage_path:
                                failed_count += 1
                                continue
                            
                            source_path = Path(attachment.storage_path)
                            if not source_path.exists():
                                failed_count += 1
                                continue
                            
                            # Build destination filename with SubjectID prefix
                            dest_filename = attachment.file_name or f"attachment_{attachment.id}"
                            if attachment.subject_id:
                                dest_filename = f"{attachment.subject_id}_{dest_filename}"
                            
                            dest_path = state.config.input_dir / dest_filename
                            
                            try:
                                # Handle filename conflicts
                                counter = 1
                                while dest_path.exists():
                                    stem = dest_path.stem
                                    suffix = dest_path.suffix
                                    dest_path = state.config.input_dir / f"{stem}_{counter}{suffix}"
                                    counter += 1
                                
                                shutil.copy2(source_path, dest_path)
                                copied_count += 1
                            except Exception as e:
                                st.error(f"Failed to copy {attachment.file_name}: {e}")
                                failed_count += 1
                    
                    if copied_count > 0:
                        state.add_notification(
                            f"Copied {copied_count} email attachment(s) to input folder"
                        )
                        st.success(f"Copied {copied_count} email attachment(s) to input folder")
                    if failed_count > 0:
                        st.warning(f"Failed to copy {failed_count} attachment(s)")
            else:
                st.caption("Select email attachments (EML/MSG) to copy to input folder")

    # Detailed view for single attachment
    selected_detail_id = st.selectbox(
        "Preview attachment details",
        options=[record["id"] for record in attachments],
        format_func=lambda attachment_id: next(
            (f"{record['file_name']} (Subject ID: {record.get('subject_id') or 'N/A'})" 
             for record in attachments if record["id"] == attachment_id),
            str(attachment_id),
        ),
    )

    detail = next(record for record in attachments if record["id"] == selected_detail_id)
    st.subheader("Attachment Metadata")
    
    # Show Subject ID prominently and link to related emails
    subject_id = detail.get("subject_id")
    if subject_id:
        st.info(f"**Subject ID:** {subject_id}")
        with session_scope() as session:
            from app.db.models import InputEmail, Attachment
            # Find related emails and attachments with same Subject ID
            related_emails = session.query(InputEmail).filter(
                InputEmail.subject_id == subject_id
            ).all()
            related_attachments = session.query(Attachment).join(InputEmail).filter(
                InputEmail.subject_id == subject_id
            ).all()
            
            if related_emails or related_attachments:
                with st.expander(f"Related Records (Subject ID: {subject_id})", expanded=False):
                    if related_emails:
                        st.write(f"**Related Emails:** {len(related_emails)}")
                        for email in related_emails[:10]:  # Show first 10
                            st.caption(f"Email #{email.id}: {email.subject or 'No subject'}")
                        if len(related_emails) > 10:
                            st.caption(f"... and {len(related_emails) - 10} more")
                    if related_attachments:
                        st.write(f"**Related Attachments:** {len(related_attachments)}")
                        for att in related_attachments[:10]:  # Show first 10
                            st.caption(f"Attachment #{att.id}: {att.file_name or 'No filename'}")
                        if len(related_attachments) > 10:
                            st.caption(f"... and {len(related_attachments) - 10} more")
    
    st.json(
        {
            "File Name": detail["file_name"],
            "Category": detail["category"],
            "File Size Bytes": detail["file_size"],
            "Subject ID": detail.get("subject_id"),
            "Email Subject": detail["email_subject"],
            "Email Sender": detail["email_sender"],
            "Batch": detail["batch_name"],
            "Storage Path": detail["storage_path"],
        }
    )