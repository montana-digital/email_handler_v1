from __future__ import annotations

from playwright.sync_api import Page, expect


def _navigate(page: Page, url: str, wait_selector: str) -> None:
    page.goto(url)
    page.wait_for_load_state("networkidle")
    expect(page.locator(wait_selector)).to_be_visible()


def _ingest_dataset(page: Page, base_url: str) -> None:
    _navigate(page, f"{base_url}/03_Email_Display", "text=Email Display")
    ingest_button = page.get_by_role("button", name="Ingest New Emails")
    expect(ingest_button).to_be_visible()
    ingest_button.click()
    expect(page.locator("text=Ingested")).to_be_visible()


def test_home_page_loads(page: Page, base_url: str):
    _navigate(page, f"{base_url}/", "text=Email Handler")
    expect(page.locator("text=Quick Start")).to_be_visible()


def test_ingest_flow(page: Page, base_url: str):
    _ingest_dataset(page, base_url)
    table = page.get_by_role("grid")
    expect(table).to_be_visible()
    search_box = page.get_by_label("Search subject, sender, or hash")
    search_box.fill("External Info - TEAM")
    expect(page.locator("text=External Info - TEAM").first).to_be_visible()


def test_generate_report(page: Page, base_url: str):
    _ingest_dataset(page, base_url)
    report_button = page.get_by_role("button", name="Generate HTML Report")
    report_button.click()
    expect(page.locator("text=Generated report at").first).to_be_visible()


def test_finalize_batch(page: Page, base_url: str):
    _ingest_dataset(page, base_url)
    finalize_button = page.get_by_role("button", name="Finalize Batch")
    finalize_button.click()
    expect(page.locator("text=Batch finalized and archived").first).to_be_visible()


def test_attachments_page(page: Page, base_url: str):
    _ingest_dataset(page, base_url)
    _navigate(page, f"{base_url}/04_Attachments", "text=Attachments")


def test_settings_reset(page: Page, base_url: str):
    _navigate(page, f"{base_url}/02_Settings", "text=Settings")
    reset_expander = page.get_by_role("button", name="Reset to first-run state")
    reset_expander.click()
    reset_input = page.get_by_label("Type RESET to confirm")
    reset_input.fill("RESET")
    reset_button = page.get_by_role("button", name="Reset Application")
    reset_button.click()
    expect(page.locator("text=Application reset successfully").first).to_be_visible()

