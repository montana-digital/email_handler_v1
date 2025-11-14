"""Email Display page with ingestion controls and editing UI."""

from __future__ import annotations

from pathlib import Path
import importlib.util
import math

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html
from PIL import Image, UnidentifiedImageError

from app.db.init_db import session_scope
from app.services.batch_finalization import finalize_batch
from app.services.email_records import (
    get_batches,
    get_email_detail,
    get_emails_for_batch,
    update_email_record,
)
from app.services.ingestion import ingest_emails
from app.services.reporting import generate_email_report
from app.services.standard_emails import promote_to_standard_emails
from app.ui.state import AppState


def render(state: AppState) -> None:
    st.header("Email Display")
    st.write("Ingest new batches, review parsed results, and edit metadata before upload.")

    if importlib.util.find_spec("extract_msg") is None:
        st.warning(
            "MSG ingestion is disabled because the optional `extract-msg` package is missing. "
            "Install it via `pip install extract-msg` to process `.msg` files."
        )

    col_ingest, col_refresh = st.columns([1, 1])
    with col_ingest:
        if st.button("Ingest New Emails", use_container_width=True):
            with session_scope() as session:
                result = ingest_emails(session, config=state.config)
            if result:
                batch, email_ids = result
                state.add_notification(f"Ingested {len(email_ids)} emails into {batch.batch_name}")
                st.success(f"Ingested {len(email_ids)} emails into '{batch.batch_name}'.")
                st.rerun()
            else:
                st.info("No new emails found in the input directory.")
    with col_refresh:
        if st.button("Refresh Batches", use_container_width=True):
            st.rerun()

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

    column_accessors = {
        "Subject": lambda record: record["subject"] or "",
        "Sender": lambda record: record["sender"] or "",
        "Subject ID": lambda record: record["subject_id"] or "",
        "Email Hash": lambda record: record["email_hash"] or "",
        "URLs": lambda record: " ".join(record["urls_parsed"]),
        "Callback Numbers": lambda record: " ".join(record["callback_numbers_parsed"]),
    }

    with st.expander("Advanced Filters", expanded=False):
        selected_column = st.selectbox("Filter column", options=list(column_accessors.keys()))
        include_text = st.text_input("Include records containing", key="include_filter").strip()
        exclude_text = st.text_input("Exclude records containing", key="exclude_filter").strip()
        sort_column = st.selectbox(
            "Sort by",
            options=["Subject", "Sender", "Date Sent", "Subject ID"],
        )
        sort_order = st.selectbox("Sort order", options=["Ascending", "Descending"])

    accessor = column_accessors[selected_column]
    if include_text:
        include_lower = include_text.lower()
        filtered = [
            record for record in filtered if include_lower in accessor(record).lower()
        ]
    if exclude_text:
        exclude_lower = exclude_text.lower()
        filtered = [
            record for record in filtered if exclude_lower not in accessor(record).lower()
        ]

    sort_key_map = {
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

    table_rows = [
        {
            "ID": record["id"],
            "Subject": record["subject"],
            "Sender": record["sender"],
            "Date Sent": record["date_sent"],
            "Subject ID": record["subject_id"],
            "URLs": ", ".join(record["urls_parsed"]),
            "Callback Numbers": ", ".join(record["callback_numbers_parsed"]),
        }
        for record in page_records
    ]

    st.subheader("Batch Summary")
    st.caption(f"Showing {len(page_records)} of {total_records} results (page {current_page}/{total_pages}).")
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    available_ids = [row["ID"] for row in table_rows]

    if "report_artifacts" not in st.session_state:
        st.session_state["report_artifacts"] = None

    report_selection = st.multiselect(
        "Emails to include in HTML report",
        options=available_ids,
        default=available_ids,
        format_func=lambda record_id: f"Email #{record_id}",
        key="report_selection",
    )

    finalize_col, report_col, promote_col = st.columns([1, 1, 2])

    with finalize_col:
        if st.button("Finalize Batch", use_container_width=True):
            with session_scope() as session:
                result = finalize_batch(session, state.selected_batch_id, config=state.config)
            if result:
                state.add_notification(f"Finalized batch {result.batch_name}")
                st.success("Batch finalized and archived.")
                st.rerun()
            else:
                st.error("Unable to finalize batch. Check logs for details.")

    with report_col:
        generate_report = st.button("Generate HTML Report", disabled=not report_selection, use_container_width=True)
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
                with html_path.open("rb") as handle:
                    st.download_button(
                        label="Download HTML Report",
                        data=handle.read(),
                        file_name=html_path.name,
                        mime="text/html",
                        key=f"download_report_{html_path.stem}",
                    )
            if csv_text_path.exists():
                with csv_text_path.open("rb") as handle:
                    st.download_button(
                        label="Download CSV (Text)",
                        data=handle.read(),
                        file_name=csv_text_path.name,
                        mime="text/csv",
                        key=f"download_csv_text_{csv_text_path.stem}",
                    )
        with artifact_cols[1]:
            if csv_full_path.exists():
                with csv_full_path.open("rb") as handle:
                    st.download_button(
                        label="Download CSV (Full)",
                        data=handle.read(),
                        file_name=csv_full_path.name,
                        mime="text/csv",
                        key=f"download_csv_full_{csv_full_path.stem}",
                    )
            attachments_path = artefacts_state.get("attachments_zip")
            if attachments_path:
                path_obj = Path(attachments_path)
                if path_obj.exists():
                    with path_obj.open("rb") as handle:
                        st.download_button(
                            label="Download All Attachments (ZIP)",
                            data=handle.read(),
                            file_name=path_obj.name,
                            mime="application/zip",
                            key=f"download_zip_attachments_{path_obj.stem}",
                        )
            emails_zip = artefacts_state.get("emails_zip")
            if emails_zip:
                path_obj = Path(emails_zip)
                if path_obj.exists():
                    with path_obj.open("rb") as handle:
                        st.download_button(
                            label="Download All Emails (ZIP)",
                            data=handle.read(),
                            file_name=path_obj.name,
                            mime="application/zip",
                            key=f"download_zip_emails_{path_obj.stem}",
                        )

    promotion_selection = st.multiselect(
        "Emails to promote to Standard Emails",
        options=available_ids,
        default=[],
        format_func=lambda record_id: f"Email #{record_id}",
        key="promotion_selection",
    )

    if promote_col.button("Promote to Standard Emails", disabled=not promotion_selection, use_container_width=True):
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
        state.selected_email_id = available_ids[0]

    selected_email_id = st.selectbox(
        "Select email for detail view",
        options=available_ids,
        index=available_ids.index(state.selected_email_id),
        format_func=lambda record_id: f"Email #{record_id}",
    )
    state.selected_email_id = selected_email_id

    with session_scope() as session:
        email_detail = get_email_detail(session, state.selected_email_id)

    if not email_detail:
        st.error("Unable to load email details.")
        return

    st.subheader("Email Details")

    metadata = [
        ("Subject", email_detail.get("subject") or "—"),
        ("Subject ID", email_detail.get("subject_id") or "—"),
        ("Sender", email_detail.get("sender") or "—"),
        ("Date Sent", email_detail.get("date_sent") or "—"),
        ("Date Reported", email_detail.get("date_reported") or "—"),
        ("Sending Source", email_detail.get("sending_source_raw") or "—"),
        ("Parsed URLs", ", ".join(email_detail.get("urls_parsed", [])) or "—"),
        ("Callback Numbers", ", ".join(email_detail.get("callback_numbers_parsed", [])) or "—"),
        ("Additional Contacts", email_detail.get("additional_contacts") or "—"),
        ("Model Confidence", email_detail.get("model_confidence") if email_detail.get("model_confidence") is not None else "—"),
        ("Message ID", email_detail.get("message_id") or "—"),
    ]

    st.markdown("### Metadata")
    col_a, col_b = st.columns(2)
    for index, (label, value) in enumerate(metadata):
        target_col = col_a if index % 2 == 0 else col_b
        target_col.markdown(f"**{label}:** {value}")

    attachments = email_detail.get("attachments") or []
    with st.expander("HTML Preview & Attachments", expanded=False):
        if email_detail.get("body_html"):
            st.markdown("#### HTML Preview")
            body_html = email_detail["body_html"]
            lowered = body_html.lower()
            if "<html" in lowered or "<body" in lowered:
                html(body_html, height=500, scrolling=True)
            else:
                st.markdown(body_html, unsafe_allow_html=True)

        if attachments:
            st.markdown("#### Attachments")
            for attachment in attachments:
                file_path = Path(attachment.get("storage_path") or "")
                file_name = attachment.get("file_name") or "attachment"
                file_type = (attachment.get("file_type") or "").lower()
                file_size = attachment.get("file_size") or 0

                st.write(f"**{file_name}** — {file_type or 'unknown'}, {file_size} bytes")

                if file_path.exists() and file_type.startswith("image"):
                    try:
                        with file_path.open("rb") as fh:
                            Image.open(fh)
                        st.image(str(file_path), caption=file_name, use_container_width=True)
                    except UnidentifiedImageError:
                        st.info("Preview not available for this attachment type.")

                if file_path.exists():
                    with file_path.open("rb") as handle:
                        st.download_button(
                            label=f"Download {file_name}",
                            data=handle.read(),
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