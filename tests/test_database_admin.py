from __future__ import annotations

import copy
from pathlib import Path
from typing import Dict

import pytest
from sqlalchemy import func

from app.config import AppConfig
from app.db.models import InputEmail
from app.services.app_reset import backup_database, reset_application
from app.services.database_admin import (
    execute_sql,
    fetch_table_data,
    list_user_table_names,
    load_table_summary,
    sync_table_changes,
    truncate_table,
)


@pytest.fixture()
def seeded_db(temp_config: AppConfig, db_session):
    email = InputEmail(
        email_hash="hash-1",
        subject="Test Email 1",
        sender="alerts@example.com",
        body_html="<p>Example</p>",
    )
    email2 = InputEmail(
        email_hash="hash-2",
        subject="Test Email 2",
        sender="alerts@example.com",
        body_html="<p>Example</p>",
    )
    db_session.add_all([email, email2])
    db_session.commit()
    yield


def test_list_tables(temp_config: AppConfig, db_session, seeded_db):
    engine = db_session.get_bind()
    tables = list_user_table_names(engine, exclude=["sqlite_sequence"])
    assert "input_emails" in tables


def test_table_summary_and_sync(temp_config: AppConfig, db_session, seeded_db):
    summary = load_table_summary(db_session, "input_emails")
    assert summary.row_count == 2
    assert summary.schema.columns

    original = fetch_table_data(db_session, "input_emails")
    updated = copy.deepcopy(original)
    for item in updated:
        if item["email_hash"] == "hash-1":
            item["subject"] = "Updated Subject"
    updated.append(
        {
            "id": max(row["id"] for row in original) + 1,
            "email_hash": "hash-3",
            "subject": "Inserted row",
            "sender": "alerts@example.com",
            "body_html": "<p>Generated</p>",
        }
    )
    updated = [row for row in updated if row["email_hash"] != "hash-2"]

    pk_columns = [col.name for col in summary.schema.columns if col.primary_key]
    inserts, updates, deletes = sync_table_changes(
        db_session,
        "input_emails",
        original,
        updated,
        pk_columns,
    )
    assert inserts == 1
    assert updates == 1
    assert deletes == 1

    count = db_session.query(func.count(InputEmail.id)).scalar() or 0
    assert count == 2


def test_truncate_and_execute_sql(temp_config: AppConfig, db_session, seeded_db):
    truncate_table(db_session, "input_emails")
    count = db_session.query(func.count(InputEmail.id)).scalar() or 0
    assert count == 0

    result = execute_sql(db_session, "INSERT INTO input_emails (email_hash, subject) VALUES ('hash-10', 'Manual insert')")
    assert result["rowcount"] == 1

    result = execute_sql(db_session, "SELECT email_hash FROM input_emails")
    assert result["rows"]


def test_reset_application(temp_config: AppConfig):
    db_path = Path(temp_config.database_url.replace("sqlite:///", ""))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("dummy", encoding="utf-8")
    temp_config.output_dir.mkdir(parents=True, exist_ok=True)
    sample_file = temp_config.output_dir / "sample.txt"
    sample_file.write_text("content")

    backup_dir = temp_config.output_dir / "backups"
    backup_path = backup_database(temp_config, backup_dir / "backup.sqlite")
    assert backup_path is not None and backup_path.exists()

    reset_application(temp_config, reset_database=True, reset_output=True, reset_cache=True, reset_logs=True)

    assert not db_path.exists()
    assert not sample_file.exists()

