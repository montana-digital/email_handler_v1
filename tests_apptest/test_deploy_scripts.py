from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

import json

from scripts.generate_test_dataset import SCRIPT_MANIFEST


def test_deploy_scripts_lists_manifest_entries(apptest_env, monkeypatch):
    scripts_dir = apptest_env["scripts_dir"]
    scripts_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = scripts_dir / "manifest.json"
    manifest_path.write_text(json.dumps(SCRIPT_MANIFEST, indent=2), encoding="utf-8")
    for script_name in SCRIPT_MANIFEST:
        (scripts_dir / script_name).write_text(f"Write-Host '{script_name}'", encoding="utf-8")

    app = AppTest.from_file("pages/01_Deploy_Scripts.py", default_timeout=15)
    app.run()

    selectboxes = app.selectbox
    assert selectboxes, "Selectbox not rendered"
    options = selectboxes[0].options
    assert any("No-Op Script" in str(option) for option in options)

