from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_home_dashboard_renders(apptest_env):
    app = AppTest.from_file("Home.py", default_timeout=15)
    app.run()

    assert app.title[0].value == "Email Handler"
    subheaders = [sub.value for sub in app.subheader]
    assert any(value.startswith("Quick Start") for value in subheaders)
    assert any(value.startswith("Database Overview") for value in subheaders)

    metrics = app.metric
    assert any(metric.label == "Input Emails" for metric in metrics)


def test_home_key_directories(apptest_env):
    app = AppTest.from_file("Home.py", default_timeout=15)
    app.run()
    expanders = app.expander
    assert any(exp.label.startswith("Key Directories") for exp in expanders)

