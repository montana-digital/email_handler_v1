# Email Handler Architecture

## 1. Objectives
- Provide a local-first Streamlit application for reviewing, annotating, and triaging downloaded email batches.
- Support repeatable ingestion of pre-downloaded `.msg` and `.eml` messages via user-triggered PowerShell scripts.
- Persist parsed results in SQLite with deterministic hashing to reconstruct original artifacts when required.
- Offer modular parsers enabling future expansion to additional content formats without core rewrites.

## 2. Operating Assumptions
- All emails and attachments are made available on the local filesystem before ingestion (PowerShell handles download).
- No outbound network calls are required post-setup; the app runs entirely on the user's workstation.
- Python 3.11+ is available; Streamlit serves the UI in the default browser.
- Users can execute bundled Python scripts (`setup_env.py`, `run_app.py`) from Windows PowerShell.

## 3. High-Level System Context
```
┌──────────────┐     ┌────────────────────┐
│PowerShell    │     │Local Email Folder  │
│Deploy Scripts│───▶ │(.msg/.eml batches) │
└────┬─────────┘     └─────────┬──────────┘
     │                          │
     │                  ┌───────▼────────┐
     │                  │Ingestion Layer │
     │                  │(parsers + hash)│
     │                  └───────┬────────┘
     │                          │
     │                  ┌───────▼────────┐
     │                  │SQLite Database │◀──┐
     │                  └───────┬────────┘   │
     │                          │            │
     │                  ┌───────▼────────┐   │
     └─────────────────▶│Streamlit UI    │───┘
                        │(Home + pages/) │
                        └────────────────┘
```

## 4. Module Responsibilities
- `scripts/`
  - `setup_env.py`: bootstrap virtual environment, install dependencies, create folders (`data/input`, `data/output`, `data/cache`), validate PowerShell requirements.
  - `run_app.py`: ensure environment is active, run lightweight diagnostics, and launch Streamlit via `streamlit run Home.py`.
- `app/db/`
  - `models.py`: SQLAlchemy ORM models for `InputEmail`, `StandardEmail`, `Attachment`, `PickleBatch`, and auxiliary tables (e.g., `ParserRun`).
  - `init_db.py`: idempotent initializer creating SQLite schema, seeding lookup values, applying simple migrations.
  - `repositories.py`: query abstractions used by services and UI layers (list, filter, update).
- `app/parsers/`
  - `parser_email.py`: orchestrates Parser1 & Parser2, normalizing email metadata and body content.
  - `parser_urls.py` (Parser3): extracts URLs using regex + `tldextract` normalization, returning unique canonical forms.
  - `parser_phones.py` (Parser4): extracts and normalizes phone numbers via `phonenumbers` library.
- `app/services/`
  - `ingestion.py`: batch orchestrator handling file discovery, hashing, parser execution, and conversion to ORM entities.
  - `attachments.py`: manages attachment extraction, categorization, and ZIP packaging.
  - `reporting.py`: builds HTML summaries for selected emails.
  - `standard_emails.py`: promotes curated `InputEmail` records into the `StandardEmail` table with supplemental parsing.
  - `powershell.py`: launches PowerShell scripts, captures execution output, and loads manifest metadata for script UX.
  - `batch_finalization.py`: archives reviewed pickle batches, updates status, and records finalization timestamps.
- `app/ui/`
  - `bootstrap.py`: loads configuration, initializes the database, renders the shared sidebar, and returns session state for every page.
  - `sidebar.py`: shared sidebar layout (environment summary, docs links, notifications, quick-open directory buttons).
  - `pages/`: renderers for `home`, `deploy_scripts`, `settings`, `email_display`, `attachments`.
  - `state.py`: shared state container bridging Streamlit session with database services.
  - `main_nav.py`: legacy navigation helper retained for backward compatibility.

## 5. Data Flow Summary
1. User downloads emails using Deploy Scripts page (PowerShell script launched directly from Streamlit with stdout/stderr capture).
2. Ingestion service scans configured input folder, hashing files to detect new/duplicate items.
3. Parser pipeline produces structured records and persists them to SQLite; simultaneously, intermediate results can be cached as Pickle batches in `data/cache/`.
4. Streamlit UI loads available batches/records, enabling filtering, selection, edits, and bulk operations.
5. Edits trigger service layer updates (SQLite + Pickle). Finalization archives the pickle and marks the batch as finalized.
6. Attachment operations and reporting are initiated from UI, leveraging services to extract assets or generate HTML reports in `data/output/`.

## 6. PowerShell Integration Touchpoints
- Deploy Scripts page resolves `powershell.exe`/`pwsh` and runs scripts in-process, capturing stdout/stderr and exit codes for analyst review.
- Manifest-driven metadata (`data/scripts/manifest.json`) provides friendly names, default arguments, working-directory placeholders, and confirmation requirements.
- Scripts must write emails into the configured input directory; environment setup documents expected folder names.
- Analysts can still override arguments ad-hoc; manifest defaults simply provide a starting point.
- Run history is retained per session, and sidebar buttons allow opening input/output directories for faster navigation.

## 7. Technology Stack
- Python: 3.11+
- Streamlit: UI framework
- SQLAlchemy + SQLite: persistence
- `email` / `extract-msg`: parsing `.eml` / `.msg`
- `phonenumbers`, `tldextract`: Parser3/4 helpers
- `pytest`: automated testing
- `pydantic`: schema validation for parsed results
- `watchdog`: optional file system monitoring for future automation (Phase 3+)

## 8. Cross-Cutting Concerns
- **Configuration**: `.env` persisted via `app/config_store.save_config`; default config stored in `app/config.py` with environment overrides. Settings UI rewrites the `.env` file and rebuilds the SQLAlchemy engine immediately.
- **Logging**: structured JSON logs via `loguru`, persisted to `data/logs/app.log` for troubleshooting.
- **Error Handling**: differentiate operational (bad email formats) vs programmer errors; operational issues surfaced in UI notifications.
- **Security**: local-only, but still sanitize paths, lock down script execution to user-provided directory, and avoid storing sensitive data in logs.
- **Performance**: batch parsing uses worker pool (ThreadPoolExecutor) to keep UI responsive; caching for repeated queries.
- **Testing Strategy**: Pytest unit tests for parsers and services, integration tests simulating ingestion-to-DB flow, smoke test for setup scripts.

## 9. Future Extension Points
- Swap SQLite for PostgreSQL with minimal changes (SQLAlchemy abstraction).
- Add webhook or API ingestion once remote access is required.
- Extend attachment handling to support OCR or malware scanning.
- Integrate authentication for multi-user scenarios if deployed beyond local workstation.

## 10. Current Roadmap
- **PowerShell UX**: add script manifest metadata, live output streaming, and optional elevated execution for complex automation.
- **Standard Email Workflow**: extend promotion pipeline with bulk approval, audit history, and StandardEmail browsing UI.
- **Reporting Enhancements**: add templated exports (PDF/CSV) and scheduled batch summaries.
- **Testing & QA**: finish automating ingestion edge cases, integrate `.msg` regression fixtures, and wire test runs into CI.
- **Content/CMS**: implement markdown-based content collections (`src/content/`) to satisfy editorial requirements.
- **Collaboration**: design multi-user access, role-based permissions, and change tracking for shared analyst deployments.

