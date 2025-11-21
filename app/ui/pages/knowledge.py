"""Knowledge page for managing knowledge tables and enrichment."""

from __future__ import annotations

import io
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st
from loguru import logger

from app.db.init_db import session_scope
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
    
    with session_scope() as session:
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
            
            if st.button(f"Initialize {display_name}", key=f"btn_init_{table_name}"):
                with session_scope() as session:
                    try:
                        metadata = initialize_knowledge_table(
                            session,
                            table_name=table_name,
                            primary_key_column=primary_key_col,
                            schema=schema,
                        )
                        session.commit()
                        st.success(f"✅ {display_name} initialized successfully!")
                        st.rerun()
                    except ValueError as exc:
                        st.error(f"Validation error: {exc}")
                    except Exception as exc:
                        st.error(f"Failed to initialize table: {exc}")
                        logger.exception("Failed to initialize knowledge table")
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
            
            if st.button(f"Upload to {display_name}", key=f"btn_upload_{table_name}"):
                with session_scope() as session:
                    try:
                        result = upload_knowledge_data(session, table_name, df)
                        session.commit()
                        
                        # Show detailed results
                        if result.records_added > 0:
                            st.success(
                                f"✅ Uploaded {result.records_added} records to {display_name}!"
                            )
                        else:
                            st.warning("⚠️ No records were uploaded.")
                        
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
                        
                        if result.records_added > 0:
                            st.rerun()
                    except ValueError as exc:
                        st.error(f"Validation error: {exc}")
                    except Exception as exc:
                        st.error(f"Failed to upload data: {exc}")
                        logger.exception("Failed to upload knowledge data")
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
    
    # Get current selection
    current_selection = metadata.selected_columns or []
    
    selected = st.multiselect(
        f"Select columns to include in 'Add Knowledge' for {display_name}",
        options=available_columns,
        default=current_selection,
        key=f"select_{table_name}",
        help="These columns will be added to the Batch Summary when 'Add Knowledge' is run.",
    )
    
    if st.button(f"Save Column Selection for {display_name}", key=f"btn_save_{table_name}"):
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
                session.commit()
                st.success(f"✅ Column selection saved for {display_name}!")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to save column selection: {exc}")
                logger.exception("Failed to save column selection")


def _render_table_status(state: AppState, table_name: str, display_name: str) -> None:
    """Render status and record count for a knowledge table."""
    with session_scope() as session:
        metadata = (
            session.query(KnowledgeTableMetadata)
            .filter(KnowledgeTableMetadata.table_name == table_name)
            .first()
        )
        
        if table_name == "Knowledge_TNs":
            record_count = session.query(KnowledgeTN).count()
        else:
            record_count = session.query(KnowledgeDomain).count()
    
    if metadata:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Status", "✅ Initialized")
        with col2:
            st.metric("Records", record_count)
        with col3:
            selected_count = len(metadata.selected_columns or [])
            st.metric("Selected Columns", selected_count)
    else:
        st.metric("Status", "⚠️ Not Initialized")


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

