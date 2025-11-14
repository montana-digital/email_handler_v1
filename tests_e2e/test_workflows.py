from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests_e2e.utils import download_with, wait_for_toast


def _base_url() -> str:
    url = os.environ.get("PLAYWRIGHT_BASE_URL")
    if not url:
        pytest.skip("PLAYWRIGHT_BASE_URL environment variable not set for e2e tests.")
    return url.rstrip("/")


def _output_dir() -> Path:
    value = os.environ.get("PLAYWRIGHT_OUTPUT_DIR")
    if not value:
        pytest.skip("PLAYWRIGHT_OUTPUT_DIR environment variable not set for e2e tests.")
    path = Path(value).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_powerShell_runner(page: Page):
    base_url = _base_url()
    page.goto(f"{base_url}/01_Deploy_Scripts")
    page.wait_for_load_state("networkidle")

    selectbox = page.get_by_role("combobox")
    expect(selectbox).to_be_visible()
    selectbox.select_option(label=lambda label: "Bulk Copy Emails" in label)

    run_button = page.get_by_role("button", name="Run Script")
    run_button.click()
    wait_for_toast(page, "Script completed")


def test_ingest_edit_promote_finalize(page: Page):
    base_url = _base_url()
    page.goto(f"{base_url}/03_Email_Display")
    page.wait_for_load_state("networkidle")

    ingest_button = page.get_by_role("button", name="Ingest New Emails")
    ingest_button.click()
    wait_for_toast(page, "Ingested")

    search_box = page.get_by_label("Search subject, sender, or hash")
    search_box.fill("External Info - TEAM")
    expect(page.locator("text=External Info - TEAM").first).to_be_visible()

    detail_select = page.get_by_label("Select email for detail view")
    detail_select.select_option(index=0)

    edit_expander = page.locator("text=Edit Email Metadata")
    edit_expander.click()
    subject_input = page.get_by_label("Subject")
    subject_input.fill("Updated Subject via Playwright")
    save_button = page.get_by_role("button", name="Save Changes")
    save_button.click()
    wait_for_toast(page, "Email updated.")

    multiselect = page.get_by_label("Emails to promote to Standard Emails")
    multiselect.select_option(index=[0, 1, 2])
    promote_button = page.get_by_role("button", name="Promote to Standard Emails")
    promote_button.click()
    wait_for_toast(page, "Promoted")

    report_button = page.get_by_role("button", name="Generate HTML Report")
    report_button.click()
    wait_for_toast(page, "Generated report")

    finalize_button = page.get_by_role("button", name="Finalize Batch")
    finalize_button.click()
    wait_for_toast(page, "Batch finalized")


def test_attachments_export(page: Page):
    base_url = _base_url()
    download_dir = _output_dir() / "attachments_exports"
    page.goto(f"{base_url}/04_Attachments")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Attachments")).to_be_visible()

    multiselect = page.get_by_label("Select attachments to export")
    multiselect.select_option(index=[0, 1])
    export_button = page.get_by_role("button", name="Export Selected Attachments")
    download_with(page, lambda: export_button.click(), download_dir)


def test_database_admin_actions(page: Page):
    base_url = _base_url()
    page.goto(f"{base_url}/02_Settings")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Database Administration")).to_be_visible()

    table_button = page.get_by_role("button", name=pytest.regex(r"input_emails"))
    table_button.click()

    refresh_button = page.get_by_role("button", name="Refresh")
    refresh_button.click()
    wait_for_toast(page, "Refreshed")

    truncate_button = page.get_by_role("button", name="Truncate Table")
    truncate_button.click()
    wait_for_toast(page, "truncated")

    sql_textarea = page.get_by_label("SQL Statement")
    sql_textarea.fill("SELECT name FROM sqlite_master;")
    execute_button = page.get_by_role("button", name="Execute SQL")
    execute_button.click()
    expect(page.locator("text=sqlite_master").first).to_be_visible()

    maintenance_button = page.get_by_role("button", name="Vacuum Database")
    maintenance_button.click()
    wait_for_toast(page, "VACUUM completed")


def test_reset_with_backup(page: Page):
    base_url = _base_url()
    page.goto(f"{base_url}/02_Settings")
    page.wait_for_load_state("networkidle")
    reset_expander = page.get_by_role("button", name="Reset to first-run state")
    reset_expander.click()

    page.get_by_label("Delete database file").check()
    page.get_by_label("Clear cache directory").check()
    page.get_by_label("Clear output directory").check()
    page.get_by_label("Clear log directory").check()
    page.get_by_label("Create database backup before reset").check()

    reset_button = page.get_by_role("button", name="Reset Application")
    reset_button.click()
    wait_for_toast(page, "Application reset successfully")

