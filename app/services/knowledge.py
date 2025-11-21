"""Knowledge table management and matching services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import KnowledgeDomain, KnowledgeTableMetadata, KnowledgeTN, InputEmail
from app.parsers.parser_phones import extract_phone_numbers
from app.parsers.parser_urls import extract_urls
from app.utils.error_handling import format_database_error


@dataclass
class KnowledgeTableSchema:
    """Schema definition for a knowledge table."""
    table_name: str
    primary_key_column: str
    columns: Dict[str, str]  # column_name -> data_type
    selected_columns: List[str]  # Columns selected for "Add Knowledge"


def normalize_phone_number(phone: str) -> Optional[str]:
    """Normalize phone number to E.164 format for matching.
    
    Args:
        phone: Phone number in any format
        
    Returns:
        E.164 formatted phone number, or None if invalid
    """
    if not phone:
        return None
    
    # Ensure string type
    if not isinstance(phone, str):
        phone = str(phone).strip()
    else:
        phone = phone.strip()
    
    if not phone:
        return None
    
    try:
        # Use existing phone parser
        results = extract_phone_numbers(phone, default_region="US")
        if results:
            return results[0].e164
    except Exception as exc:
        logger.warning("Failed to normalize phone number '%s': %s", phone, exc)
        # Return None to indicate normalization failure - caller should handle this
    
    return None


def normalize_domain(url_or_domain: str) -> Optional[str]:
    """Normalize URL or domain to base domain for matching.
    
    Args:
        url_or_domain: URL or domain string
        
    Returns:
        Normalized domain (lowercase), or None if invalid
    """
    if not url_or_domain:
        return None
    
    # Ensure string type
    if not isinstance(url_or_domain, str):
        url_or_domain = str(url_or_domain).strip()
    else:
        url_or_domain = url_or_domain.strip()
    
    if not url_or_domain:
        return None
    
    try:
        # Use existing URL parser to extract domain
        results = extract_urls(url_or_domain)
        if results:
            return results[0].domain.lower()
        
        # If no URL pattern found, try treating as domain directly
        import tldextract
        extracted = tldextract.extract(url_or_domain)
        # Use top_domain_under_public_suffix (preferred, non-deprecated)
        domain = extracted.top_domain_under_public_suffix
        # Only use if it's a valid domain (has both domain and suffix)
        if domain and extracted.domain and extracted.suffix:
            return domain.lower()
        # If top_domain_under_public_suffix is empty but we have domain+suffix, construct it
        if extracted.domain and extracted.suffix:
            domain = f"{extracted.domain}.{extracted.suffix}"
            return domain.lower()
    except Exception as exc:
        logger.warning("Failed to normalize domain '%s': %s", url_or_domain, exc)
    
    return None


def detect_csv_schema(df: pd.DataFrame) -> Dict[str, str]:
    """Detect data types for CSV columns.
    
    Args:
        df: DataFrame from CSV
        
    Returns:
        Dictionary mapping column names to SQLite-compatible types
        
    Raises:
        ValueError: If DataFrame is empty or has no columns
    """
    if df.empty:
        raise ValueError("DataFrame is empty. Cannot detect schema.")
    
    if len(df.columns) == 0:
        raise ValueError("DataFrame has no columns. Cannot detect schema.")
    
    schema = {}
    for col in df.columns:
        if not col or not isinstance(col, str):
            logger.warning("Skipping invalid column name: %s", col)
            continue
            
        dtype = str(df[col].dtype)
        
        # Map pandas dtypes to SQLite types
        if dtype.startswith("int"):
            schema[col] = "INTEGER"
        elif dtype.startswith("float"):
            schema[col] = "REAL"
        elif dtype == "bool":
            schema[col] = "INTEGER"  # SQLite uses INTEGER for boolean
        else:
            schema[col] = "TEXT"
    
    if not schema:
        raise ValueError("No valid columns found in DataFrame.")
    
    return schema


def initialize_knowledge_table(
    session: Session,
    table_name: str,
    primary_key_column: str,
    schema: Dict[str, str],
) -> KnowledgeTableMetadata:
    """Initialize a knowledge table with schema.
    
    Args:
        session: Database session
        table_name: "Knowledge_TNs" or "Knowledge_Domains"
        primary_key_column: Column name to use as primary key
        schema: Column name -> data type mapping
        
    Returns:
        Created metadata record
        
    Raises:
        ValueError: If table_name is invalid, primary_key_column not in schema, or schema is empty
    """
    # Validate table_name
    if table_name not in ("Knowledge_TNs", "Knowledge_Domains"):
        raise ValueError(f"Invalid table name: {table_name}. Must be 'Knowledge_TNs' or 'Knowledge_Domains'")
    
    # Validate schema
    if not schema:
        raise ValueError("Schema cannot be empty")
    
    # Validate primary_key_column exists in schema
    if primary_key_column not in schema:
        raise ValueError(
            f"Primary key column '{primary_key_column}' not found in schema. "
            f"Available columns: {', '.join(schema.keys())}"
        )
    
    try:
        # Check if table already exists
        existing = (
            session.query(KnowledgeTableMetadata)
            .filter(KnowledgeTableMetadata.table_name == table_name)
            .first()
        )
        
        if existing:
            # Update existing metadata
            existing.primary_key_column = primary_key_column
            existing.schema_definition = schema
            return existing
        
        # Create new metadata
        metadata = KnowledgeTableMetadata(
            table_name=table_name,
            primary_key_column=primary_key_column,
            schema_definition=schema,
            selected_columns=None,
        )
        session.add(metadata)
        session.flush()  # Flush to get the ID and validate
        logger.info("Created knowledge table metadata for %s with primary key column %s", 
                   table_name, primary_key_column)
        return metadata
    except Exception as exc:
        logger.error("Failed to initialize knowledge table %s: %s", table_name, exc)
        session.rollback()
        raise


@dataclass
class UploadResult:
    """Result of knowledge data upload."""
    records_added: int
    records_skipped: int
    errors: List[str]


def upload_knowledge_data(
    session: Session,
    table_name: str,
    df: pd.DataFrame,
) -> UploadResult:
    """Upload CSV data to knowledge table.
    
    Validates that columns match the schema before adding.
    Handles errors gracefully and continues processing remaining rows.
    
    Args:
        session: Database session
        table_name: "Knowledge_TNs" or "Knowledge_Domains"
        df: DataFrame from CSV
        
    Returns:
        UploadResult with statistics
        
    Raises:
        ValueError: If columns don't match schema or table not initialized
    """
    if df.empty:
        return UploadResult(records_added=0, records_skipped=0, errors=["DataFrame is empty"])
    
    # Get metadata
    metadata = (
        session.query(KnowledgeTableMetadata)
        .filter(KnowledgeTableMetadata.table_name == table_name)
        .first()
    )
    
    if not metadata:
        raise ValueError(f"Table {table_name} not initialized. Please initialize it first.")
    
    # Validate columns match schema
    expected_columns = set(metadata.schema_definition.keys())
    actual_columns = set(df.columns)
    
    if expected_columns != actual_columns:
        missing = expected_columns - actual_columns
        extra = actual_columns - expected_columns
        error_msg = f"Column mismatch for {table_name}:\n"
        if missing:
            error_msg += f"  Missing columns: {', '.join(missing)}\n"
        if extra:
            error_msg += f"  Extra columns: {', '.join(extra)}\n"
        error_msg += f"  Expected: {', '.join(sorted(expected_columns))}\n"
        error_msg += f"  Got: {', '.join(sorted(actual_columns))}"
        raise ValueError(error_msg)
    
    # Determine which table to use
    if table_name == "Knowledge_TNs":
        table_class = KnowledgeTN
    elif table_name == "Knowledge_Domains":
        table_class = KnowledgeDomain
    else:
        raise ValueError(f"Unknown table name: {table_name}")
    
    primary_key_col = metadata.primary_key_column
    records_added = 0
    records_skipped = 0
    errors = []
    
    logger.info("Starting upload to %s: %d rows, primary key column: %s", 
                table_name, len(df), primary_key_col)
    
    # Insert or update records with error handling per row
    for idx, row in df.iterrows():
        try:
            # Get primary key value and normalize
            pk_value_raw = str(row[primary_key_col]) if pd.notna(row[primary_key_col]) else None
            if not pk_value_raw or not pk_value_raw.strip():
                records_skipped += 1
                errors.append(f"Row {idx + 1}: Empty primary key value")
                continue
            
            # Normalize based on table type
            if table_name == "Knowledge_TNs":
                pk_value = normalize_phone_number(pk_value_raw)
                if not pk_value:
                    records_skipped += 1
                    errors.append(f"Row {idx + 1}: Failed to normalize phone number '{pk_value_raw}'")
                    continue
            else:  # Knowledge_Domains
                pk_value = normalize_domain(pk_value_raw)
                if not pk_value:
                    records_skipped += 1
                    errors.append(f"Row {idx + 1}: Failed to normalize domain '{pk_value_raw}'")
                    continue
            
            if not pk_value:
                records_skipped += 1
                errors.append(f"Row {idx + 1}: Failed to normalize primary key '{pk_value_raw}'")
                continue
            
            # Prepare data dict (all columns except primary key)
            data_dict = {}
            for col in df.columns:
                if col != primary_key_col:
                    try:
                        value = row[col]
                        # Convert pandas types to Python types
                        if pd.isna(value):
                            data_dict[col] = None
                        elif isinstance(value, (int, float, str, bool)):
                            data_dict[col] = value
                        else:
                            data_dict[col] = str(value)
                    except Exception as exc:
                        logger.warning("Error processing column %s in row %d: %s", col, idx + 1, exc)
                        data_dict[col] = None  # Fallback to None
            
            # Validate data_dict can be serialized to JSON
            try:
                from app.utils.json_helpers import safe_json_dumps
                safe_json_dumps(data_dict)  # Test serialization
            except (TypeError, ValueError) as exc:
                records_skipped += 1
                errors.append(f"Row {idx + 1}: Invalid data types (cannot serialize to JSON): {exc}")
                continue
            
            # Use merge pattern to handle race conditions (check-then-insert)
            # This avoids IntegrityError if another process inserts between check and insert
            try:
                # Check if record exists
                existing = (
                    session.query(table_class)
                    .filter(table_class.primary_key_value == pk_value)
                    .first()
                )
                
                if existing:
                    # Update existing record
                    existing.data = data_dict
                    existing.updated_at = datetime.now()
                else:
                    # Create new record
                    new_record = table_class(
                        primary_key_value=pk_value,
                        data=data_dict,
                    )
                    session.add(new_record)
                
                records_added += 1
                if records_added % 10 == 0:
                    logger.debug("Processed %d records so far", records_added)
            except Exception as db_exc:
                # Handle unique constraint violations (race condition)
                from sqlalchemy.exc import IntegrityError
                if isinstance(db_exc, IntegrityError) and "primary_key_value" in str(db_exc).lower():
                    # Another process inserted between our check and insert
                    # Try to update the existing record
                    try:
                        existing = (
                            session.query(table_class)
                            .filter(table_class.primary_key_value == pk_value)
                            .first()
                        )
                        if existing:
                            existing.data = data_dict
                            existing.updated_at = datetime.now()
                            records_added += 1
                            logger.debug("Handled race condition for primary_key_value %s", pk_value)
                        else:
                            raise  # Re-raise if we still can't find it
                    except Exception:
                        records_skipped += 1
                        error_msg = format_database_error(db_exc, f"process row {idx + 1}")
                        errors.append(f"Row {idx + 1}: Database error (race condition) - {error_msg}")
                        logger.warning("Failed to handle race condition for row %d: %s", idx + 1, db_exc)
                        continue
                else:
                    # Re-raise other exceptions with formatted error
                    error_msg = format_database_error(db_exc, f"save row {idx + 1}")
                    raise ValueError(error_msg) from db_exc
            
        except Exception as exc:
            records_skipped += 1
            # Format error message based on exception type
            if isinstance(exc, ValueError):
                error_msg = f"Row {idx + 1}: {str(exc)}"
            else:
                error_msg = format_database_error(exc, f"process row {idx + 1}")
                error_msg = f"Row {idx + 1}: {error_msg}"
            errors.append(error_msg)
            logger.exception("Error processing row %d: %s", idx + 1, exc)
            continue
    
    try:
        session.flush()
        logger.info("Upload to %s completed: %d added, %d skipped, %d errors", 
                   table_name, records_added, records_skipped, len(errors))
    except Exception as exc:
        logger.error("Failed to flush database changes for %s: %s", table_name, exc)
        session.rollback()
        raise
    
    return UploadResult(
        records_added=records_added,
        records_skipped=records_skipped,
        errors=errors,
    )


@dataclass
class KnowledgeEnrichmentResult:
    """Result of knowledge enrichment operation."""
    matched_tns: int
    matched_domains: int
    updated: int
    errors: int
    error_details: List[str]


def add_knowledge_to_emails(
    session: Session,
    email_ids: List[int],
    config: Optional[Dict] = None,
) -> KnowledgeEnrichmentResult:
    """Add knowledge data to emails based on phone numbers and URLs.
    
    Handles errors gracefully and continues processing remaining emails.
    
    Args:
        session: Database session
        email_ids: List of InputEmail IDs to process
        config: Optional configuration dict with selected columns
        
    Returns:
        KnowledgeEnrichmentResult with statistics
        
    Raises:
        ValueError: If no tables initialized or no columns selected
    """
    if not email_ids:
        return KnowledgeEnrichmentResult(
            matched_tns=0, matched_domains=0, updated=0, errors=0, error_details=[]
        )
    
    # Get metadata for both tables
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
    
    if not tn_metadata and not domain_metadata:
        raise ValueError("No knowledge tables initialized. Please initialize at least one table.")
    
    # Get selected columns for each table (ensure they are lists)
    tn_selected = []
    if tn_metadata and tn_metadata.selected_columns:
        tn_selected = tn_metadata.selected_columns if isinstance(tn_metadata.selected_columns, list) else []
    
    domain_selected = []
    if domain_metadata and domain_metadata.selected_columns:
        domain_selected = domain_metadata.selected_columns if isinstance(domain_metadata.selected_columns, list) else []
    
    if not tn_selected and not domain_selected:
        raise ValueError("No columns selected for knowledge enrichment. Please select columns in Knowledge page.")
    
    # Get emails
    emails = (
        session.query(InputEmail)
        .filter(InputEmail.id.in_(email_ids))
        .all()
    )
    
    if not emails:
        return KnowledgeEnrichmentResult(
            matched_tns=0, matched_domains=0, updated=0, errors=0,
            error_details=[f"No emails found for IDs: {email_ids}"]
        )
    
    stats = KnowledgeEnrichmentResult(
        matched_tns=0, matched_domains=0, updated=0, errors=0, error_details=[]
    )
    
    for email in emails:
        try:
            knowledge_updates = {}
            
            # Match phone numbers
            if tn_metadata and tn_selected:
                from app.utils.json_helpers import safe_json_loads_list
                phone_numbers = safe_json_loads_list(email.callback_number_parsed)
                
                for phone in phone_numbers:
                    if not phone or not isinstance(phone, str):
                        continue
                    normalized = normalize_phone_number(phone)
                    if normalized:
                        try:
                            tn_record = (
                                session.query(KnowledgeTN)
                                .filter(KnowledgeTN.primary_key_value == normalized)
                                .first()
                            )
                            if tn_record and tn_record.data:
                                # Add selected columns to knowledge_updates
                                for col in tn_selected:
                                    if col in tn_record.data:
                                        knowledge_updates[col] = tn_record.data[col]
                                stats.matched_tns += 1
                                break  # Use first match
                        except Exception as exc:
                            logger.warning("Error querying knowledge for phone %s: %s", normalized, exc)
            
            # Match domains
            if domain_metadata and domain_selected:
                from app.utils.json_helpers import safe_json_loads_list
                domains = safe_json_loads_list(email.url_parsed)
                
                for domain in domains:
                    if not domain or not isinstance(domain, str):
                        continue
                    normalized = normalize_domain(domain)
                    if normalized:
                        try:
                            domain_record = (
                                session.query(KnowledgeDomain)
                                .filter(KnowledgeDomain.primary_key_value == normalized)
                                .first()
                            )
                            if domain_record and domain_record.data:
                                # Add selected columns to knowledge_updates
                                for col in domain_selected:
                                    if col in domain_record.data:
                                        knowledge_updates[col] = domain_record.data[col]
                                stats.matched_domains += 1
                                break  # Use first match
                        except Exception as exc:
                            logger.warning("Error querying knowledge for domain %s: %s", normalized, exc)
            
            # Update email knowledge_data (overwrites existing for selected columns)
            # Validate existing knowledge_data is valid JSON/dict
            existing = {}
            if email.knowledge_data:
                if isinstance(email.knowledge_data, dict):
                    existing = dict(email.knowledge_data)
                else:
                    logger.warning("Invalid knowledge_data type for email %d, resetting", email.id)
                    existing = {}
            
            # Overwrite selected columns with new knowledge (or "not available")
            all_selected = set(tn_selected + domain_selected)
            
            # First, set all selected columns to "not available" (will be overwritten if matched)
            for col in all_selected:
                existing[col] = "not available"
            
            # Then, update with matched knowledge (this overwrites "not available" for matched columns)
            existing.update(knowledge_updates)
            
            # Validate the dict can be serialized to JSON
            try:
                from app.utils.json_helpers import safe_json_dumps
                safe_json_dumps(existing)
            except (TypeError, ValueError) as exc:
                logger.error("Cannot serialize knowledge_data for email %d: %s", email.id, exc)
                stats.errors += 1
                stats.error_details.append(f"Email {email.id}: Invalid data types in knowledge_data")
                continue
            
            # Assign new dict to trigger SQLAlchemy change detection
            email.knowledge_data = existing
            stats.updated += 1
            
        except Exception as exc:
            stats.errors += 1
            error_msg = f"Email {email.id}: {str(exc)}"
            stats.error_details.append(error_msg)
            logger.exception("Error processing email %d: %s", email.id, exc)
            continue
    
    try:
        session.flush()
    except Exception as exc:
        logger.error("Failed to flush knowledge enrichment changes: %s", exc)
        session.rollback()
        raise
    
    return stats

