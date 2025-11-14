from __future__ import annotations

from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, expect


def wait_for_toast(page: Page, text_substring: str) -> None:
    locator = page.locator(f"text={text_substring}")
    expect(locator).to_be_visible()


def ensure_download_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_with(page: Page, trigger: Callable[[], None], download_dir: Path) -> Path:
    ensure_download_directory(download_dir)
    with page.expect_download() as download_info:
        trigger()
    download = download_info.value
    destination = download_dir / download.suggested_filename
    download.save_as(destination)
    return destination

