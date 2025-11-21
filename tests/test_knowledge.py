"""Tests for knowledge table management and matching."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.db.models import InputEmail, KnowledgeDomain, KnowledgeTableMetadata, KnowledgeTN
from app.services.knowledge import (
    add_knowledge_to_emails,
    detect_csv_schema,
    initialize_knowledge_table,
    normalize_domain,
    normalize_phone_number,
    upload_knowledge_data,
)


def test_normalize_phone_number():
    """Test phone number normalization to E.164 format."""
    # Test various phone formats
    assert normalize_phone_number("+1-555-123-4567") == "+15551234567"
    assert normalize_phone_number("(555) 123-4567") == "+15551234567"
    assert normalize_phone_number("555-123-4567") == "+15551234567"
    assert normalize_phone_number("+44 20 7946 0958") is not None  # UK number
    assert normalize_phone_number("invalid") is None
    assert normalize_phone_number("") is None
    assert normalize_phone_number(None) is None


def test_normalize_domain():
    """Test domain normalization from URLs."""
    # Test various URL formats
    assert normalize_domain("https://example.com/path") == "example.com"
    assert normalize_domain("http://www.example.com") == "example.com"
    assert normalize_domain("example.com") == "example.com"
    assert normalize_domain("subdomain.example.com") == "example.com"
    assert normalize_domain("https://test.co.uk/page") == "test.co.uk"
    assert normalize_domain("invalid") is None
    assert normalize_domain("") is None
    assert normalize_domain(None) is None


def test_detect_csv_schema():
    """Test CSV schema detection."""
    df = pd.DataFrame({
        "phone": ["+15551234567", "+15551234568"],
        "name": ["John", "Jane"],
        "age": [30, 25],
        "score": [95.5, 87.3],
        "active": [True, False],
    })
    
    schema = detect_csv_schema(df)
    
    assert schema["phone"] == "TEXT"
    assert schema["name"] == "TEXT"
    assert schema["age"] == "INTEGER"
    assert schema["score"] == "REAL"
    assert schema["active"] == "INTEGER"  # SQLite uses INTEGER for boolean


def test_initialize_knowledge_table_tns(db_session: Session):
    """Test initializing Knowledge_TNs table."""
    schema = {
        "phone": "TEXT",
        "carrier": "TEXT",
        "region": "TEXT",
    }
    
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    
    assert metadata is not None
    assert metadata.table_name == "Knowledge_TNs"
    assert metadata.primary_key_column == "phone"
    assert metadata.schema_definition == schema
    assert metadata.selected_columns is None
    
    db_session.commit()
    
    # Test updating existing
    new_schema = {
        "phone": "TEXT",
        "carrier": "TEXT",
        "region": "TEXT",
        "status": "TEXT",
    }
    
    updated = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=new_schema,
    )
    
    assert updated.id == metadata.id
    assert updated.schema_definition == new_schema


def test_initialize_knowledge_table_domains(db_session: Session):
    """Test initializing Knowledge_Domains table."""
    schema = {
        "domain": "TEXT",
        "registrar": "TEXT",
        "country": "TEXT",
    }
    
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_Domains",
        primary_key_column="domain",
        schema=schema,
    )
    
    assert metadata is not None
    assert metadata.table_name == "Knowledge_Domains"
    assert metadata.primary_key_column == "domain"
    assert metadata.schema_definition == schema


def test_upload_knowledge_data_tns(db_session: Session):
    """Test uploading data to Knowledge_TNs."""
    # Initialize table first
    schema = {
        "phone": "TEXT",
        "carrier": "TEXT",
        "region": "TEXT",
    }
    initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    db_session.commit()
    
    # Create test data
    df = pd.DataFrame({
        "phone": ["+15551234567", "+15551234568"],
        "carrier": ["Verizon", "AT&T"],
        "region": ["NY", "CA"],
    })
    
    result = upload_knowledge_data(db_session, "Knowledge_TNs", df)
    
    assert result.records_added == 2
    assert result.records_skipped == 0
    db_session.commit()
    
    # Verify data was inserted
    records = db_session.query(KnowledgeTN).all()
    assert len(records) == 2
    
    # Check normalized phone numbers
    phone_values = [r.primary_key_value for r in records]
    assert "+15551234567" in phone_values
    assert "+15551234568" in phone_values
    
    # Check data JSON
    for record in records:
        assert "carrier" in record.data
        assert "region" in record.data


def test_upload_knowledge_data_domains(db_session: Session):
    """Test uploading data to Knowledge_Domains."""
    # Initialize table first
    schema = {
        "domain": "TEXT",
        "registrar": "TEXT",
        "country": "TEXT",
    }
    initialize_knowledge_table(
        db_session,
        table_name="Knowledge_Domains",
        primary_key_column="domain",
        schema=schema,
    )
    db_session.commit()
    
    # Create test data
    df = pd.DataFrame({
        "domain": ["https://example.com", "https://test.com"],
        "registrar": ["GoDaddy", "Namecheap"],
        "country": ["US", "US"],
    })
    
    result = upload_knowledge_data(db_session, "Knowledge_Domains", df)
    
    assert result.records_added == 2
    assert result.records_skipped == 0
    db_session.commit()
    
    # Verify data was inserted
    records = db_session.query(KnowledgeDomain).all()
    assert len(records) == 2
    
    # Check normalized domains
    domain_values = [r.primary_key_value for r in records]
    assert "example.com" in domain_values
    assert "test.com" in domain_values


def test_upload_knowledge_data_column_validation(db_session: Session):
    """Test that column validation works."""
    # Initialize table
    schema = {
        "phone": "TEXT",
        "carrier": "TEXT",
    }
    initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    db_session.commit()
    
    # Try to upload with wrong columns
    df = pd.DataFrame({
        "phone": ["+15551234567"],
        "wrong_column": ["value"],
    })
    
    with pytest.raises(ValueError, match="Column mismatch"):
        upload_knowledge_data(db_session, "Knowledge_TNs", df)


def test_upload_knowledge_data_updates_existing(db_session: Session):
    """Test that uploading updates existing records."""
    # Initialize and upload first batch
    schema = {"phone": "TEXT", "carrier": "TEXT"}
    initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    db_session.commit()
    
    df1 = pd.DataFrame({
        "phone": ["+15551234567"],
        "carrier": ["Verizon"],
    })
    result1 = upload_knowledge_data(db_session, "Knowledge_TNs", df1)
    assert result1.records_added == 1
    db_session.commit()
    
    # Upload same phone with different carrier
    df2 = pd.DataFrame({
        "phone": ["+15551234567"],
        "carrier": ["AT&T"],
    })
    result2 = upload_knowledge_data(db_session, "Knowledge_TNs", df2)
    assert result2.records_added == 1
    db_session.commit()
    
    # Should only have one record, with updated carrier
    records = db_session.query(KnowledgeTN).all()
    assert len(records) == 1
    assert records[0].data["carrier"] == "AT&T"


def test_add_knowledge_to_emails_phone_match(db_session: Session):
    """Test adding knowledge data via phone number matching."""
    # Initialize Knowledge_TNs
    schema = {"phone": "TEXT", "carrier": "TEXT", "region": "TEXT"}
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    metadata.selected_columns = ["carrier", "region"]
    db_session.commit()
    
    # Add knowledge data
    df = pd.DataFrame({
        "phone": ["+15551234567"],
        "carrier": ["Verizon"],
        "region": ["NY"],
    })
    upload_knowledge_data(db_session, "Knowledge_TNs", df)
    db_session.commit()
    
    # Create email with matching phone number
    email = InputEmail(
        email_hash="test_hash_phone",
        callback_number_parsed=json.dumps(["+15551234567"]),
    )
    db_session.add(email)
    db_session.commit()
    
    # Add knowledge
    result = add_knowledge_to_emails(db_session, [email.id])
    db_session.commit()
    
    assert result.matched_tns == 1
    assert result.updated == 1
    assert result.errors == 0
    
    # Verify knowledge data was added
    db_session.refresh(email)
    assert email.knowledge_data is not None
    assert email.knowledge_data["carrier"] == "Verizon"
    assert email.knowledge_data["region"] == "NY"


def test_add_knowledge_to_emails_domain_match(db_session: Session):
    """Test adding knowledge data via domain matching."""
    # Initialize Knowledge_Domains
    schema = {"domain": "TEXT", "registrar": "TEXT", "country": "TEXT"}
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_Domains",
        primary_key_column="domain",
        schema=schema,
    )
    metadata.selected_columns = ["registrar", "country"]
    db_session.commit()
    
    # Add knowledge data
    df = pd.DataFrame({
        "domain": ["https://example.com"],
        "registrar": ["GoDaddy"],
        "country": ["US"],
    })
    upload_knowledge_data(db_session, "Knowledge_Domains", df)
    db_session.commit()
    
    # Create email with matching domain
    email = InputEmail(
        email_hash="test_hash_domain",
        url_parsed=json.dumps(["example.com"]),
    )
    db_session.add(email)
    db_session.commit()
    
    # Add knowledge
    result = add_knowledge_to_emails(db_session, [email.id])
    db_session.commit()
    
    assert result.matched_domains == 1
    assert result.updated == 1
    assert result.errors == 0
    
    # Verify knowledge data was added
    db_session.refresh(email)
    assert email.knowledge_data is not None
    assert email.knowledge_data["registrar"] == "GoDaddy"
    assert email.knowledge_data["country"] == "US"


def test_add_knowledge_to_emails_no_match(db_session: Session):
    """Test that 'not available' is set when no match is found."""
    # Initialize Knowledge_TNs with selected columns
    schema = {"phone": "TEXT", "carrier": "TEXT"}
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    metadata.selected_columns = ["carrier"]
    db_session.commit()
    
    # Create email with phone number not in knowledge table
    email = InputEmail(
        email_hash="test_hash_no_match",
        callback_number_parsed=json.dumps(["+19999999999"]),
    )
    db_session.add(email)
    db_session.commit()
    
    # Add knowledge
    result = add_knowledge_to_emails(db_session, [email.id])
    db_session.commit()
    
    assert result.matched_tns == 0
    assert result.updated == 1
    assert result.errors == 0
    
    # Verify "not available" was set
    db_session.refresh(email)
    assert email.knowledge_data is not None
    assert email.knowledge_data["carrier"] == "not available"


def test_add_knowledge_to_emails_overwrites_existing(db_session: Session):
    """Test that rerunning overwrites existing knowledge data."""
    # Initialize and set up knowledge
    schema = {"phone": "TEXT", "carrier": "TEXT"}
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    metadata.selected_columns = ["carrier"]
    db_session.commit()
    
    # Add knowledge data
    df = pd.DataFrame({
        "phone": ["+15551234567"],
        "carrier": ["Verizon"],
    })
    upload_knowledge_data(db_session, "Knowledge_TNs", df)
    db_session.commit()
    
    # Create email
    email = InputEmail(
        email_hash="test_hash_overwrite",
        callback_number_parsed=json.dumps(["+15551234567"]),
        knowledge_data={"carrier": "Old Carrier"},  # Existing data
    )
    db_session.add(email)
    db_session.commit()
    
    # Add knowledge (should overwrite)
    result = add_knowledge_to_emails(db_session, [email.id])
    db_session.commit()
    
    # Refresh email to get latest data
    db_session.refresh(email)
    
    # Verify overwritten - should be "Verizon" not "Old Carrier"
    assert result.matched_tns == 1, "Phone number should have matched"
    assert result.errors == 0, "No errors expected"
    assert email.knowledge_data is not None, "Knowledge data should exist"
    assert email.knowledge_data["carrier"] == "Verizon", f"Expected 'Verizon', got '{email.knowledge_data.get('carrier')}'"


def test_add_knowledge_to_emails_multiple_emails(db_session: Session):
    """Test adding knowledge to multiple emails."""
    # Initialize
    schema = {"phone": "TEXT", "carrier": "TEXT"}
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    metadata.selected_columns = ["carrier"]
    db_session.commit()
    
    # Add knowledge data
    df = pd.DataFrame({
        "phone": ["+15551234567", "+15551234568"],
        "carrier": ["Verizon", "AT&T"],
    })
    upload_knowledge_data(db_session, "Knowledge_TNs", df)
    db_session.commit()
    
    # Create multiple emails
    email1 = InputEmail(
        email_hash="test_hash_1",
        callback_number_parsed=json.dumps(["+15551234567"]),
    )
    email2 = InputEmail(
        email_hash="test_hash_2",
        callback_number_parsed=json.dumps(["+15551234568"]),
    )
    email3 = InputEmail(
        email_hash="test_hash_3",
        callback_number_parsed=json.dumps(["+19999999999"]),  # No match
    )
    db_session.add_all([email1, email2, email3])
    db_session.commit()
    
    # Add knowledge to all
    result = add_knowledge_to_emails(db_session, [email1.id, email2.id, email3.id])
    db_session.commit()
    
    assert result.matched_tns == 2
    assert result.updated == 3
    assert result.errors == 0
    
    # Verify all emails updated
    db_session.refresh(email1)
    db_session.refresh(email2)
    db_session.refresh(email3)
    
    assert email1.knowledge_data["carrier"] == "Verizon"
    assert email2.knowledge_data["carrier"] == "AT&T"
    assert email3.knowledge_data["carrier"] == "not available"


def test_upload_knowledge_data_handles_invalid_rows(db_session: Session):
    """Test that upload handles rows with invalid data gracefully."""
    schema = {"phone": "TEXT", "carrier": "TEXT"}
    initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    db_session.commit()
    
    # Create DataFrame with some invalid rows
    df = pd.DataFrame({
        "phone": ["+15551234567", "", "invalid_phone", "+15551234568"],
        "carrier": ["Verizon", "AT&T", "T-Mobile", "Sprint"],
    })
    
    result = upload_knowledge_data(db_session, "Knowledge_TNs", df)
    db_session.commit()
    
    # Should add 2 valid records, skip 2 invalid ones
    assert result.records_added == 2
    assert result.records_skipped == 2
    assert len(result.errors) == 2


def test_add_knowledge_to_emails_handles_invalid_json(db_session: Session):
    """Test that add_knowledge handles invalid JSON in email fields."""
    schema = {"phone": "TEXT", "carrier": "TEXT"}
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    metadata.selected_columns = ["carrier"]
    db_session.commit()
    
    # Create email with invalid JSON in callback_number_parsed
    email = InputEmail(
        email_hash="test_hash_invalid_json",
        callback_number_parsed="invalid json!!!",  # Invalid JSON
    )
    db_session.add(email)
    db_session.commit()
    
    # Should handle gracefully
    result = add_knowledge_to_emails(db_session, [email.id])
    db_session.commit()
    
    # Should still update email with "not available"
    assert result.errors == 0  # JSON parsing error is handled gracefully
    assert result.updated == 1
    db_session.refresh(email)
    assert email.knowledge_data is not None
    assert email.knowledge_data["carrier"] == "not available"


def test_add_knowledge_to_emails_handles_missing_emails(db_session: Session):
    """Test that add_knowledge handles missing email IDs gracefully."""
    schema = {"phone": "TEXT", "carrier": "TEXT"}
    metadata = initialize_knowledge_table(
        db_session,
        table_name="Knowledge_TNs",
        primary_key_column="phone",
        schema=schema,
    )
    metadata.selected_columns = ["carrier"]
    db_session.commit()
    
    # Try to add knowledge to non-existent email IDs
    result = add_knowledge_to_emails(db_session, [99999, 99998])
    
    assert result.updated == 0
    assert result.errors == 0  # Missing emails are handled gracefully
    assert len(result.error_details) > 0  # Should have error details


def test_detect_csv_schema_handles_empty_dataframe():
    """Test that detect_csv_schema handles empty DataFrame."""
    df = pd.DataFrame()
    
    with pytest.raises(ValueError, match="empty"):
        detect_csv_schema(df)


def test_initialize_knowledge_table_validates_primary_key():
    """Test that initialize_knowledge_table validates primary key exists."""
    schema = {"phone": "TEXT", "carrier": "TEXT"}
    
    with pytest.raises(ValueError, match="not found in schema"):
        from app.db.init_db import session_scope
        with session_scope() as session:
            initialize_knowledge_table(
                session,
                table_name="Knowledge_TNs",
                primary_key_column="nonexistent",
                schema=schema,
            )


