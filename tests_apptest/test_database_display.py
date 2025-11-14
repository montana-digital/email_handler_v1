from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from streamlit.testing.v1 import AppTest

from app.db.models import Attachment, Base, InputEmail, StandardEmail


def _seed_standard_email(db_path):
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        email = InputEmail(
            email_hash="standard-hash-001",
            subject="Quarterly Report",
            sender="reports@example.com",
            body_html="<p>Report content</p>",
        )
        session.add(email)
        session.flush()
        email.attachments.extend(
            [
                Attachment(
                    file_name="chart.png",
                    file_type="image/png",
                    file_size_bytes=1024,
                    storage_path=str(db_path.parent / "chart.png"),
                ),
                Attachment(
                    file_name="analysis.pdf",
                    file_type="application/pdf",
                    file_size_bytes=2048,
                    storage_path=str(db_path.parent / "analysis.pdf"),
                ),
            ]
        )

        for attachment in email.attachments:
            path = db_path.parent / attachment.file_name
            path.write_bytes(b"test")

        standard = StandardEmail(
            email_hash=email.email_hash,
            from_address=email.sender,
            subject=email.subject,
            body_html=email.body_html,
            body_urls=json.dumps(["https://reports.example.com"]),
            body_text_numbers=json.dumps(["+18005550199"]),
            source_input_email=email,
        )
        session.add(standard)
        session.commit()
    engine.dispose()


def test_database_display_renders_records(apptest_env):
    _seed_standard_email(apptest_env["db_path"])

    app = AppTest.from_file("pages/05_Database_Display.py", default_timeout=15)
    app.run()

    assert app.header, "Header not rendered"
    assert app.header[0].value == "Database Email Archive"

    # Dataframe renders with attachment counts columns
    tables = app.dataframe
    assert tables, "Saved email table not rendered"
    rendered = tables[0].value
    assert "Images" in rendered.columns
    assert "PDFs" in rendered.columns

    # Detail section should include attachments expander
    expanders = app.expander
    labels = [exp.label for exp in expanders]
    assert any("Attachments" in label for label in labels)

