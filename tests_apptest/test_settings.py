from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_settings_configuration_expander(apptest_env, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    monkeypatch.setenv("EMAIL_HANDLER_DATABASE_URL", f"sqlite:///{apptest_env['db_path']}")

    app = AppTest.from_file("pages/02_Settings.py", default_timeout=20)
    app.run()

    expanders = app.expander
    labels = [exp.label for exp in expanders]
    assert any(label.startswith("Configuration") for label in labels)


def test_settings_reset_confirmation(apptest_env, monkeypatch):
    app = AppTest.from_file("pages/02_Settings.py", default_timeout=20)
    app.run()

    expanders = app.expander
    reset_expander = next(
        (exp for exp in expanders if exp.label.startswith("Reset to first-run state")),
        None,
    )
    assert reset_expander is not None
    assert reset_expander.text_input

