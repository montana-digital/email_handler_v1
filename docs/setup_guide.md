# Local Setup & Operations Guide

This guide targets analysts running the Email Handler app on Windows with PowerShell.

## 1. Prerequisites
- Windows 10/11 with PowerShell 5.1+.
- Python 3.11 (64-bit) on the `PATH`.
- Git (optional) if you plan to pull updates from version control.

## 2. First-Time Environment Bootstrap
```powershell
cd C:\Users\<username>\OneDrive\Desktop\email_handler_v1
python scripts\setup_env.py
```

The script will:
1. Create a virtual environment in `.venv`.
2. Generate `requirements.txt` (if missing) and install dependencies such as Streamlit, SQLAlchemy, and parser helpers.
3. Create the required directory structure:
   - `data\input` – drop downloaded `.eml` / `.msg` files here.
   - `data\cache` – interim Pickle batches.
   - `data\output` – reports, extracted attachments, and archives.
   - `data\logs` – application and parser logs.
   - `data\scripts` – approved PowerShell utilities for downloading emails.

You can safely re-run the script; it is idempotent.

## 3. Launching the Application
```powershell
python scripts\run_app.py
```

Options:
- `--setup-if-missing` – automatically run `setup_env.py` if the virtual environment is absent.
- Append Streamlit flags by prefixing with `--`, for example:
  ```powershell
  python scripts\run_app.py -- --server.port 8502
  ```

The launcher calls `streamlit run Home.py`, which is the root page of the multipage app. Streamlit automatically discovers additional pages in `pages/` and lists them at the top of the sidebar (Home, Deploy Scripts, Settings, Email Display, Attachments). The app opens at `http://localhost:8501`.

## 4. PowerShell Script Workflow
1. Place approved `.ps1` scripts under `data\scripts` or upload them via the app's **Deploy Scripts** page.
2. Select a script inside the app, optionally provide arguments (for example `-InputPath "C:\Staging"`), and click **Run Script**.
3. The app resolves `powershell.exe`/`pwsh`, runs the script, and streams stdout/stderr plus the exit code. Recent runs are listed for quick review.
4. Each script should output downloaded emails (and attachments) into the configured input folder (`data\input` by default). Use the sidebar **Open Input** button to jump there.
5. After downloads complete, switch to **Email Display** to ingest and review the new batch.

## 5. Directory Overview
| Path | Purpose |
| --- | --- |
| `Home.py` | Main Streamlit entrypoint (landing page). |
| `pages/` | Streamlit multipage directory for Deploy Scripts, Settings, Email Display, Attachments. |
| `app/` | Python package containing UI helpers, services, and data access layers (`app/main.py` exists for backward compatibility). |
| `scripts/` | Automation helpers (`setup_env.py`, `run_app.py`). |
| `data/input/` | Staging area for raw email files. |
| `data/cache/` | Pickle snapshots of parsed batches (editable via UI). |
| `data/output/` | Exported attachments, HTML reports, and ZIP bundles. |
| `data/logs/` | Structured logs for troubleshooting. |

## 6. Maintenance Tips
- Re-run `python scripts\setup_env.py` after pulling new code to ensure dependencies stay in sync.
- Clear `data/cache` files after uploading batches to the database to conserve disk space.
- Retain execution logs (`data\logs`) when reporting issues to developers.
- Keep PowerShell scripts versioned separately and review them regularly for access or API changes.
- Update directories or database settings via the **Settings** page; changes are persisted to `.env`, folders are created automatically, and the SQLite engine reloads in-place.
- Use the sidebar **Open Input** / **Open Output** buttons for quick navigation while debugging scripts.

## 7. Troubleshooting
- **Missing Streamlit executable**: re-run `python scripts\setup_env.py`.
- **Port already in use**: specify an alternate port (`python scripts\run_app.py -- --server.port 8502`).
- **Execution policy blocks scripts**: launch PowerShell with `-ExecutionPolicy Bypass` for the session or sign scripts per organizational policy.
- **Database locked**: ensure only one Streamlit session runs at a time or restart the app to release SQLite locks.

For additional architecture details, refer to `docs/architecture.md`. Future updates will extend this guide with ingestion and parser operations once implemented.

