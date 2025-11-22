"""Knowledge page for managing knowledge tables and enrichment."""

from __future__ import annotations

import io
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st
from loguru import logger
from sqlalchemy.exc import OperationalError

from app.db.init_db import session_scope
from app.utils.error_handling import format_database_error
from app.db.models import KnowledgeDomain, KnowledgeTableMetadata, KnowledgeTN
from app.services.knowledge import (
    add_knowledge_to_emails,
    detect_csv_schema,
    initialize_knowledge_table,
    upload_knowledge_data,
)
from app.ui.state import AppState


def _render_table_initialization(state: AppState, table_name: str, display_name: str) -> None:
    """Render UI for initializing a knowledge table."""
    st.subheader(f"Initialize {display_name}")
    
    # Check for initialization success from previous run first
    success_key = f"_knowledge_init_success_{table_name}"
    if st.session_state.get(success_key):
        st.success(f"✅ {display_name} initialized successfully!")
        del st.session_state[success_key]  # Clear after showing
    
    # Check if table is already initialized (use fresh session to avoid cache issues)
    with session_scope() as session:
        # Use a fresh query to ensure we see committed data
        metadata = (
            session.query(KnowledgeTableMetadata)
            .filter(KnowledgeTableMetadata.table_name == table_name)
            .first()
        )
    
    if metadata:
        st.info(f"✅ {display_name} is already initialized.")
        with st.expander("View Schema", expanded=False):
            st.json(metadata.schema_definition)
            st.caption(f"Primary Key Column: **{metadata.primary_key_column}**")
        return
    
    uploaded_file = st.file_uploader(
        f"Upload CSV to initialize {display_name}",
        type=["csv"],
        key=f"init_{table_name}",
        help="Upload a CSV file. The app will detect columns and data types.",
    )
    
    if uploaded_file:
        try:
            # Read CSV with encoding fallback
            try:
                df = pd.read_csv(uploaded_file, encoding='utf-8')
            except UnicodeDecodeError:
                try:
                    uploaded_file.seek(0)  # Reset file pointer
                    df = pd.read_csv(uploaded_file, encoding='latin-1')
                    st.warning("⚠️ CSV file is not UTF-8 encoded. Using Latin-1 encoding.")
                except Exception:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding='cp1252')
                    st.warning("⚠️ CSV file encoding detected as Windows-1252.")
            
            if df.empty:
                st.error("CSV file is empty or could not be parsed.")
                return
            
            if len(df.columns) == 0:
                st.error("CSV file has no columns.")
                return
            
            st.success(f"CSV loaded: {len(df)} rows, {len(df.columns)} columns")
            
            # Show preview
            st.dataframe(df.head(10), use_container_width=True)
            
            # Detect schema
            try:
                schema = detect_csv_schema(df)
            except ValueError as exc:
                st.error(f"Schema detection failed: {exc}")
                return
            
            # Select primary key column
            primary_key_col = st.selectbox(
                "Select Primary Key Column",
                options=list(df.columns),
                key=f"pk_{table_name}",
                help="This column will be used to match against phone numbers or URLs in emails.",
            )
            
            # Initialize button with proper error handling
            if st.button(f"Initialize {display_name}", key=f"btn_init_{table_name}", type="primary"):
                try:
                    # Initialize in one session
                    with session_scope() as session:
                        try:
                            metadata = initialize_knowledge_table(
                                session,
                                table_name=table_name,
                                primary_key_column=primary_key_col,
                                schema=schema,
                            )
                            # Session will commit automatically on exit from context manager
                            logger.info("Successfully initialized knowledge table %s with schema: %s", 
                                       table_name, schema)
                        except ValueError as exc:
                            st.error(f"Validation error: {exc}")
                            logger.warning("Validation error initializing %s: %s", table_name, exc)
                            return  # Stop here if validation fails
                        except Exception as exc:
                            error_msg = str(exc)
                            st.error(f"Failed to initialize table: {error_msg}")
                            logger.exception("Failed to initialize knowledge table %s: %s", table_name, exc)
                            return  # Stop here if initialization fails
                    
                    # Verify the initialization was committed by querying in a fresh session
                    with session_scope() as verify_session:
                        verify_metadata = (
                            verify_session.query(KnowledgeTableMetadata)
                            .filter(KnowledgeTableMetadata.table_name == table_name)
                            .first()
                        )
                        if verify_metadata:
                            logger.info("Verified knowledge table %s metadata exists in database (ID: %s)", 
                                       table_name, verify_metadata.id)
                            # Store success in session state to show after rerun
                            st.session_state[success_key] = True
                            st.rerun()  # Rerun to refresh the UI
                        else:
                            logger.error("Knowledge table %s metadata not found after initialization!", table_name)
                            st.error("⚠️ Initialization may have failed. Please check the logs and try again.")
                except Exception as exc:
                    error_msg = str(exc)
                    st.error(f"Unexpected error during initialization: {error_msg}")
                    logger.exception("Unexpected error during knowledge table initialization for %s", table_name)
        except pd.errors.EmptyDataError:
            st.error("CSV file is empty or malformed.")
        except pd.errors.ParserError as exc:
            st.error(f"Failed to parse CSV file: {exc}")
        except Exception as exc:
            st.error(f"Failed to read CSV file: {exc}")
            logger.exception("Failed to read CSV file")


def _render_data_upload(state: AppState, table_name: str, display_name: str) -> None:
    """Render UI for uploading data to a knowledge table."""
    st.subheader(f"Upload Data to {display_name}")
    
    with session_scope() as session:
        metadata = (
            session.query(KnowledgeTableMetadata)
            .filter(KnowledgeTableMetadata.table_name == table_name)
            .first()
        )
    
    if not metadata:
        st.warning(f"⚠️ {display_name} is not initialized. Please initialize it first.")
        return
    
    uploaded_file = st.file_uploader(
        f"Upload CSV to {display_name}",
        type=["csv"],
        key=f"upload_{table_name}",
        help="CSV must have the same columns as the initialized schema.",
    )
    
    if uploaded_file:
        try:
            # Read CSV with encoding fallback
            try:
                df = pd.read_csv(uploaded_file, encoding='utf-8')
            except UnicodeDecodeError:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding='latin-1')
                    st.warning("⚠️ CSV file is not UTF-8 encoded. Using Latin-1 encoding.")
                except Exception:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding='cp1252')
                    st.warning("⚠️ CSV file encoding detected as Windows-1252.")
            
            if df.empty:
                st.error("CSV file is empty or could not be parsed.")
                return
            
            st.info(f"CSV loaded: {len(df)} rows")
            st.dataframe(df.head(5), use_container_width=True)
            
            # Check for upload success from previous run
            upload_success_key = f"_knowledge_upload_success_{table_name}"
            if st.session_state.get(upload_success_key):
                success_info = st.session_state[upload_success_key]
                st.success(f"✅ Uploaded {success_info.get('records_added', 0)} records to {display_name}!")
                if success_info.get('records_skipped', 0) > 0:
                    st.warning(f"⚠️ Skipped {success_info['records_skipped']} records due to errors.")
                del st.session_state[upload_success_key]  # Clear after showing
            
            if st.button(f"Upload to {display_name}", key=f"btn_upload_{table_name}", type="primary"):
                try:
                    result = None
                    # Upload in one session
                    with session_scope() as session:
                        try:
                            result = upload_knowledge_data(session, table_name, df)
                            # Session will commit automatically on exit from context manager
                            logger.info("Successfully uploaded %d records to %s (skipped: %d)", 
                                       result.records_added, table_name, result.records_skipped)
                        except ValueError as exc:
                            st.error(f"Validation error: {exc}")
                            logger.warning("Validation error uploading to %s: %s", table_name, exc)
                            return  # Stop here if validation fails
                        except Exception as exc:
                            error_msg = str(exc)
                            st.error(f"Failed to upload data: {error_msg}")
                            logger.exception("Failed to upload knowledge data to %s: %s", table_name, exc)
                            return  # Stop here if upload fails
                    
                    # Verify result was successfully obtained
                    if result is None:
                        st.error("Upload failed - no result returned")
                        logger.error("Upload returned None result")
                        return
                    
                    # Verify the upload was committed by querying record count in a fresh session
                    with session_scope() as verify_session:
                        if table_name == "Knowledge_TNs":
                            verify_count = verify_session.query(KnowledgeTN).count()
                        else:
                            verify_count = verify_session.query(KnowledgeDomain).count()
                        logger.info("Verified knowledge table %s has %d records after upload", 
                                   table_name, verify_count)
                    
                    # Show detailed results
                    if result.records_added > 0:
                        # Store success in session state to show after rerun
                        st.session_state[upload_success_key] = {
                            'records_added': result.records_added,
                            'records_skipped': result.records_skipped
                        }
                        if result.records_skipped > 0:
                            st.warning(
                                f"⚠️ Skipped {result.records_skipped} records due to errors."
                            )
                        
                        if result.errors:
                            with st.expander(f"View {len(result.errors)} errors", expanded=False):
                                for error in result.errors[:20]:  # Show first 20 errors
                                    st.text(error)
                                if len(result.errors) > 20:
                                    st.caption(f"... and {len(result.errors) - 20} more errors")
                        
                        st.rerun()  # Rerun to refresh the UI
                    else:
                        st.warning("⚠️ No records were uploaded.")
                        if result.records_skipped > 0:
                            st.warning(
                                f"⚠️ Skipped {result.records_skipped} records due to errors."
                            )
                        if result.errors:
                            with st.expander(f"View {len(result.errors)} errors", expanded=False):
                                for error in result.errors[:20]:
                                    st.text(error)
                                if len(result.errors) > 20:
                                    st.caption(f"... and {len(result.errors) - 20} more errors")
                except Exception as exc:
                    error_msg = str(exc)
                    st.error(f"Unexpected error during upload: {error_msg}")
                    logger.exception("Unexpected error during knowledge data upload for %s", table_name)
        except pd.errors.EmptyDataError:
            st.error("CSV file is empty or malformed.")
        except pd.errors.ParserError as exc:
            st.error(f"Failed to parse CSV file: {exc}")
        except Exception as exc:
            st.error(f"Failed to read CSV file: {exc}")
            logger.exception("Failed to read CSV file")


def _render_column_selection(state: AppState, table_name: str, display_name: str) -> None:
    """Render UI for selecting columns to include in 'Add Knowledge'."""
    st.subheader(f"Select Columns for {display_name}")
    
    with session_scope() as session:
        metadata = (
            session.query(KnowledgeTableMetadata)
            .filter(KnowledgeTableMetadata.table_name == table_name)
            .first()
        )
    
    if not metadata:
        st.warning(f"⚠️ {display_name} is not initialized.")
        return
    
    # Get available columns (exclude primary key)
    available_columns = [
        col for col in metadata.schema_definition.keys()
        if col != metadata.primary_key_column
    ]
    
    if not available_columns:
        st.info("No additional columns available (only primary key column).")
        return
    
    # Get current selection (ensure it's a list, handle None or wrong type)
    current_selection = metadata.selected_columns
    if current_selection is None:
        current_selection = []
    elif not isinstance(current_selection, list):
        # Handle legacy data that might be stored as dict or other type
        logger.warning("selected_columns is not a list, resetting to empty list")
        current_selection = []
    
    # Filter current_selection to only include columns that are in available_columns
    # This prevents errors when the table schema changes
    valid_selection = [col for col in current_selection if col in available_columns]
    
    selected = st.multiselect(
        f"Select columns to include in 'Add Knowledge' for {display_name}",
        options=available_columns,
        default=valid_selection,
        key=f"select_{table_name}",
        help="These columns will be added to the Batch Summary when 'Add Knowledge' is run.",
    )
    
    # Check for column selection success from previous run
    selection_success_key = f"_knowledge_selection_success_{table_name}"
    if st.session_state.get(selection_success_key):
        st.success(f"✅ Column selection saved for {display_name}!")
        del st.session_state[selection_success_key]  # Clear after showing
    
    if st.button(f"Save Column Selection for {display_name}", key=f"btn_save_{table_name}", type="primary"):
        try:
            # Save in one session
            with session_scope() as session:
                try:
                    metadata = (
                        session.query(KnowledgeTableMetadata)
                        .filter(KnowledgeTableMetadata.table_name == table_name)
                        .first()
                    )
                    if not metadata:
                        st.error(f"Table {display_name} metadata not found. Please initialize the table first.")
                        return
                    
                    # Validate selected columns exist in schema (excluding primary key)
                    schema_columns = set(metadata.schema_definition.keys())
                    invalid_columns = set(selected) - schema_columns
                    if invalid_columns:
                        st.error(f"Invalid columns selected: {', '.join(invalid_columns)}")
                        return
                    
                    metadata.selected_columns = selected
                    # Session will commit automatically on exit from context manager
                    logger.info("Saved column selection for %s: %d columns", table_name, len(selected))
                except ValueError as exc:
                    st.error(f"Validation error: {exc}")
                    logger.warning("Validation error saving column selection for %s: %s", table_name, exc)
                    return  # Stop here if validation fails
                except Exception as exc:
                    error_msg = str(exc)
                    st.error(f"Failed to save column selection: {error_msg}")
                    logger.exception("Failed to save column selection for %s: %s", table_name, exc)
                    return  # Stop here if save fails
            
            # Verify the selection was committed by querying in a fresh session
            with session_scope() as verify_session:
                verify_metadata = (
                    verify_session.query(KnowledgeTableMetadata)
                    .filter(KnowledgeTableMetadata.table_name == table_name)
                    .first()
                )
                if verify_metadata:
                    verify_selected = verify_metadata.selected_columns
                    if verify_selected is None or not isinstance(verify_selected, list):
                        verify_selected = []
                    logger.info("Verified column selection for %s: %d columns saved", 
                               table_name, len(verify_selected))
                    # Store success in session state to show after rerun
                    st.session_state[selection_success_key] = True
                    st.rerun()  # Rerun to refresh the UI
                else:
                    logger.error("Knowledge table %s metadata not found after saving selection!", table_name)
                    st.error("⚠️ Column selection may not have been saved. Please try again.")
        except Exception as exc:
            error_msg = str(exc)
            st.error(f"Unexpected error during column selection save: {error_msg}")
            logger.exception("Unexpected error during column selection save for %s", table_name)


def _render_table_status(state: AppState, table_name: str, display_name: str) -> None:
    """Render status and record count for a knowledge table."""
    # Use a fresh session to ensure we see the latest data
    with session_scope() as session:
        # Query with explicit filter to avoid any cache issues
        metadata = (
            session.query(KnowledgeTableMetadata)
            .filter(KnowledgeTableMetadata.table_name == table_name)
            .first()
        )
        
        if table_name == "Knowledge_TNs":
            record_count = session.query(KnowledgeTN).count()
        else:
            record_count = session.query(KnowledgeDomain).count()
        
        # Get selected columns count, handling None and non-list types
        selected_count = 0
        if metadata:
            selected_cols = metadata.selected_columns
            if selected_cols is not None:
                if isinstance(selected_cols, list):
                    selected_count = len(selected_cols)
                else:
                    logger.warning("selected_columns for %s is not a list (type: %s), value: %s", 
                                  table_name, type(selected_cols), selected_cols)
                    selected_count = 0
    
    if metadata:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Status", "✅ Initialized")
        with col2:
            st.metric("Records", record_count)
        with col3:
            st.metric("Selected Columns", selected_count)
            if selected_count == 0:
                st.caption("No columns selected")
    else:
        st.metric("Status", "⚠️ Not Initialized")
        logger.debug("Knowledge table %s status check: metadata not found", table_name)


def render(state: AppState) -> None:
    """Render the Knowledge page."""
    st.header("Knowledge Tables")
    st.write(
        "Manage knowledge tables for enriching email data. "
        "Initialize tables with CSV files, then match phone numbers and URLs to add knowledge columns to batches."
    )
    
    # Tabs for each table
    tab_tns, tab_domains = st.tabs(["Knowledge_TNs (Phone Numbers)", "Knowledge_Domains (URLs)"])
    
    with tab_tns:
        _render_table_status(state, "Knowledge_TNs", "Knowledge_TNs")
        st.divider()
        _render_table_initialization(state, "Knowledge_TNs", "Knowledge_TNs")
        st.divider()
        _render_data_upload(state, "Knowledge_TNs", "Knowledge_TNs")
        st.divider()
        _render_column_selection(state, "Knowledge_TNs", "Knowledge_TNs")
    
    with tab_domains:
        _render_table_status(state, "Knowledge_Domains", "Knowledge_Domains")
        st.divider()
        _render_table_initialization(state, "Knowledge_Domains", "Knowledge_Domains")
        st.divider()
        _render_data_upload(state, "Knowledge_Domains", "Knowledge_Domains")
        st.divider()
        _render_column_selection(state, "Knowledge_Domains", "Knowledge_Domains")

