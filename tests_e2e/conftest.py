from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from scripts import create_dataset


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("PLAYWRIGHT_BASE_URL")
    if not url:
        pytest.skip("PLAYWRIGHT_BASE_URL environment variable not set for e2e tests.")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def input_dir() -> Path:
    value = os.environ.get("PLAYWRIGHT_INPUT_DIR")
    if not value:
        pytest.skip("PLAYWRIGHT_INPUT_DIR environment variable not set for e2e tests.")
    path = Path(value).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def e2e_dataset(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("e2e_dataset")
    create_dataset(root, email_count=120, seed=98765)
    return root


@pytest.fixture(scope="function", autouse=True)
def populate_input_dir(input_dir: Path, e2e_dataset: Path):
    shutil.rmtree(input_dir, ignore_errors=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    for email_file in (e2e_dataset / "emails").glob("*.eml"):
        shutil.copy2(email_file, input_dir / email_file.name)

