# Testing Roadmap & Automation Plan

_Last updated: 2025-11-13_

This document tracks the strategy, tooling, and action items for validating **Email Handler** end-to-end. It captures the data-generation pipeline, automation layers (unit → AppTest → Playwright), stress tests, and edge-case coverage. Update it as we implement new capabilities or discover additional scenarios.

---

## 1. Goals

- **Functional coverage** – ingestion, attachment handling, reporting, Standard Email promotion, batch finalization, PowerShell integration, settings persistence, DB admin tooling.
- **Stress coverage** – high-volume batches (≥200 emails + attachments) to exercise deduplication, hashing, UI rendering, and DB operations.
- **Regression prevention** – reusable automation suite runnable via CI (pytest + Streamlit AppTest + Playwright).
- **Edge resilience** – ensure malformed/partial data, duplicates, large payloads, and editor actions don’t break workflows.

---

## 2. Test Data Generation

| Asset | Location | Description | Status |
|-------|----------|-------------|--------|
| Email corpus generator | `scripts/generate_test_dataset.py` | Produce ≥220 `.eml` messages with metadata variations. 60% subjects include `External Info - TEAM`. Include malformed headers, duplicates, multi-part content. | TODO |
| Attachment generator | `tests/data/attachments/<email-hash>/` | Provide mix of image, HTML, CSV, PDF, DOCX, ZIP, MSG, large binaries. Validate duplicate names & size edge cases. | TODO |
| PowerShell samples | `tests/data/scripts/` | `noop.ps1`, `bulk_copy.ps1`, `log_env.ps1`, `slow_script.ps1` with manifest metadata. | TODO |
| DB seed snapshots | `tests/data/db/*.sqlite` | Pre-populate DB variants for targeted tests (optional). | TODO |

### Email fields to randomize
- Sender formats, CC lists, `Date Reported` (valid/missing/malformed), `Message-ID`, message body variants, base64 inline images (valid/truncated), nested attachments, mixed encodings.
- Duplicate content with different filenames to trigger hash skip logic.
- Long subjects (>255 chars), blank subjects, unusual unicode.

### Attachment mix
- 0–3 attachments per email, referencing files created above.
- Ensure path collisions, unusual MIME types, large payloads (~5MB).

---

## 3. Automation Layers

### 3.1 Pytest unit & integration tests
| Area | Files | Notes |
|------|-------|-------|
| Ingestion | `tests/test_ingestion.py` | Expand to handle generated dataset, dedupe verification. |
| Parsers | `tests/test_parser_email.py`, `tests/test_parser_msg.py` | Cover External Info subjects, malformed bodies, nested attachments. |
| Attachments/Reporting | `tests/test_attachments_service.py`, `tests/test_reporting_service.py` | Validate exports & HTML generation with complex data. |
| Standard Email promotion | `tests/test_standard_emails.py` | Confirm dedupe + edge-case handling. |
| DB Admin services | **NEW** tests for `database_admin.py` & `app_reset.py` (sync edits, truncate, drop, reset combinations). |

### 3.2 Streamlit AppTest suite
- **Home**: ensure hero renders, metrics match dataset counts.
- **Deploy Scripts**: simulate running sample scripts, validate stdout capture.
- **Settings**: update directories, run reset, verify config updates.
- **Email Display**: ingest dataset, search, edit records, generate reports.
- **Attachments**: filter categories, export attachments, inspect metadata.
- **DB Admin**: expand table, edit via data_editor, truncate/delete, run SQL.

Leverage `streamlit.testing.AppTest` (docs: https://docs.streamlit.io/library/api-reference/app-testing).

### 3.3 Playwright end-to-end flows
Launch Streamlit app on controlled port. Scenarios:
1. Cold start ingestion via PowerShell script, verify batch summary & search results.
2. Record edit + save + validation (UI + DB query).
3. Generate HTML report & download attachments ZIP.
4. Promote to Standard Emails, tabulate DB entries.
5. Finalize batch; confirm pickle path archived.
6. Attachments page filter/export & download verification.
7. Settings update & revert; .env check.
8. DB Admin: edit row, truncate, drop, run SQL query, run VACUUM, reset selective toggles.
9. PowerShell runner: run scripts (success, failure, long-running) and confirm history entries.
10. Reset workflow (with/without backup) & app relaunch validation.

CI integration: run Playwright tests after launching app in background process.

### 3.4 Performance & stress scripts
- Batch ingestion benchmark (pytest-benchmark optional).
- After large ingest, run DB admin actions to ensure responsive.
- Monitor logs for warnings/errors (capture in CI artifacts).

---

## 4. Execution Pipeline (CI/CD)

1. Generate dataset (`python scripts/generate_test_dataset.py`).
2. Run standard `pytest` suite.
3. Run AppTest tests (`pytest streamlit_tests/` or similar).
4. Launch app (`streamlit run Home.py --browser.serverAddress localhost --server.port 8501`) in background.
5. Execute Playwright tests (`pytest tests_e2e/ --base-url http://localhost:8501`).
6. Optional: run performance script nightly or per-release.
7. Collect artifacts (logs, reports, dataset zipped) on failure.

Add GitHub Actions workflow referencing the above steps, ensure caching for generated data to speed runs.

#### Playwright runtime configuration
- `PLAYWRIGHT_BASE_URL` – full URL (e.g. `http://127.0.0.1:8502`) of a running Streamlit instance.
- `PLAYWRIGHT_INPUT_DIR` – absolute path to the app’s input directory; tests copy generated `.eml` files here before each run.
- Optional: `PLAYWRIGHT_TEST_TIMEOUT` or similar can be set via pytest to handle slower environments.

---

## 5. Edge Case Matrix

| Scenario | Covered by |
|----------|------------|
| Duplicate emails (hash dedupe) | Dataset + ingestion tests |
| Missing / malformed `Date Reported` | Parser tests + ingestion UI |
| External Info subject variants | Dataset + search tests |
| Non-ASCII & long subjects | Parser + DB integration |
| Inline base64 images (valid/truncated) | Parser + HTML preview |
| Nested `.msg` attachments | Ingestion/attachment tests |
| Missing `Message-ID` | Parser/ingestion |
| No attachments vs multiples w/ same name | Attachment export tests |
| Large attachments (~5MB) | Stress tests + downloads |
| Primary-keyless tables | DB admin read-only check |
| SQL editor errors | SQL execution error handling test |
| Reset toggles combinations | Reset tests (unit + UI) |
| PowerShell script failures/timeouts | Playwright scenario |
| UI editing conflicting with DB constraints | Table edit tests |

---

## 6. Deliverables & Owners (initial assignment)

| Task | Owner | Status |
|------|-------|--------|
| Email/attachment generator script | _TBD_ | TODO |
| PowerShell sample scripts | _TBD_ | TODO |
| Unit test expansions | _TBD_ | TODO |
| AppTest scenarios | _TBD_ | IN PROGRESS |
| Playwright harness | _TBD_ | IN PROGRESS (smoke + main workflows) |
| Performance benchmark script | _TBD_ | TODO |
| CI pipeline updates | _TBD_ | TODO |
| Testing documentation maintenance | _TBD_ | TODO |

Set owners as we start implementing.

---

## 7. Next Steps

1. Build dataset generation tooling + sample scripts (highest priority).
2. Add unit tests for new dataset coverage (parsers, ingestion, DB admin).
3. Stand up AppTest + Playwright scaffolding.
4. Configure CI workflow to orchestrate steps.
5. Iterate on test scenarios as new features/edge cases emerge.

Add progress notes and references below as we implement.

