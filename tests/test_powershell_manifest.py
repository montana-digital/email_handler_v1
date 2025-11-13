from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from app.services.powershell import PowerShellScriptInfo, load_manifest


def _build_config(tmp_path: Path) -> AppConfig:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        database_url="sqlite://",
        pickle_cache_dir=tmp_path / "cache",
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        scripts_dir=scripts_dir,
        log_dir=tmp_path / "logs",
        env_name="test",
    )


def test_load_manifest_parses_entries(tmp_path: Path):
    config = _build_config(tmp_path)
    manifest_data = {
        "sample.ps1": {
            "displayName": "Sample Script",
            "description": "Demo run",
            "defaultArgs": "-Name Test",
            "workingDirectory": "%OUTPUT_DIR%",
            "requiresConfirmation": True,
        }
    }
    path = config.scripts_dir / "manifest.json"
    path.write_text(json.dumps(manifest_data), encoding="utf-8")

    manifest = load_manifest(config)
    assert "sample.ps1" in manifest

    info = manifest["sample.ps1"]
    assert isinstance(info, PowerShellScriptInfo)
    assert info.display_name == "Sample Script"
    assert info.description == "Demo run"
    assert info.default_arguments == "-Name Test"
    assert info.requires_confirmation is True

    resolved = info.resolved_working_directory(config)
    assert resolved == config.output_dir.resolve()


def test_load_manifest_handles_missing_file(tmp_path: Path):
    config = _build_config(tmp_path)
    manifest = load_manifest(config)
    assert manifest == {}

