<!-- aad8ba42-19d9-4e45-9879-47e739ef1961 43f786b2-0fd6-490f-bed9-17bc43ed569d -->
# Streamlit Email Handler Plan

## Architecture & Documentation

- summarize-context: Author `docs/architecture.md` capturing domain model, module boundaries, data flow, and PowerShell integration touchpoints.
- spec-schemas: Draft ERD and SQLite schema definitions in `docs/data-model.md` plus migration strategy notes.
- ui-blueprint: Produce low-fidelity wireframes and navigation notes in `docs/ui-ux.md` for Streamlit multipage layout.

## Phase 0 – Environment Automation

- env-bootstrap: Implement `scripts/setup_env.py` to create venv, install deps, and prepare local directories.
- launcher: Build `scripts/run_app.py` verifying environment, loading config, and launching Streamlit with diagnostics.

## Phase 1 – Data Layer & Parsers

- schema-setup: Define SQLAlchemy models and Alembic-lite migrations in `app/db/models.py` and `app/db/init_db.py` using SQLite.
- parsers-core: Implement modular email/attachment parsing pipeline under `app/parsers/` with unit tests via Pytest.
- ingestion-service: Create file watcher/importer in `app/services/ingestion.py` handling email hash, pickle round-trip, and CSV/MSG normalization.

## Phase 2 – Streamlit Core UI

- multipage-shell: Scaffold Streamlit multipage structure in `app/ui/` with pages for Home, Deploy Scripts, Settings, Email Display, Attachments.
- state-management: Implement shared session state, data access layer hooks, and Pickle selection UI components.
- edit-flows: Enable record updates syncing back to SQLite/pickle using transactional service layer.

## Phase 3 – Advanced Features & Ops

- attachment-ops: Add bulk attachment extraction, tagging, and ZIP packaging services.
- reporting: Implement batch HTML report generation and Standard Email promotion workflows.
- qa-hardening: Expand Pytest coverage, add integration tests, and document manual test checklist in `docs/testing.md`.

## Phase 4 – Packaging & Delivery

- config-docs: Write editor-oriented README and usage guides in `docs/` including PowerShell script onboarding.
- distribution: Provide optional packaged executable instructions and verify end-to-end setup/run scripts.

### To-dos

- [x] Draft architecture document describing module responsibilities and data flow.
- [x] Build Python setup script to create virtual environment, install dependencies, and initialize folders.
- [x] Implement SQLite schema and SQLAlchemy ORM models with initialization routine.
- [x] Scaffold Streamlit multipage UI with navigation placeholders.
- [x] Add bulk attachment handling, extraction, and packaging workflows.
- [x] Document setup, operation, and PowerShell script integration for local deployments.