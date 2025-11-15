# Email Ingestion Resiliency Plan

Goal: make Email Display ingestion tolerant of every email format we can encounter (EML, MSG, nested files, malformed headers) while providing clear fallbacks, observability, and test coverage.

## 1. Detection & Discovery Layer
1. **Content sniffing** – before parsing, inspect magic bytes to detect MIME, OLE/CFB, ZIP, or text-only payloads independent of extension. Optional: integrate `python-magic` when available.
2. **Archive handling** – detect ZIP/RAR attachments containing email files; stage them for recursive ingestion (phase 2 goal).
3. **Metadata capture** – always persist file size, original extension, detected type, and SHA-256 hash to `OriginalEmail` even if downstream parsing fails.

Deliverables:
- `app/services/ingestion.py`: new `class EmailCandidate` describing detected type + raw bytes.
- Unit tests covering renamed files, extension-less files, and corrupt headers.

## 2. Parser Fallback Pipeline
Design a tiered strategy with standardized reporting via `ParserRun`:

| Tier | Target | Tooling | Notes |
| --- | --- | --- | --- |
| P1 | EML | current `BytesParser` flow | Keep as first attempt. |
| P2 | EML fallback | `mailparser` (3rd-party) | Better charset, inline attachments, RTF detection. |
| P3 | EML rescue | heuristics (regex-based header/body extraction) | Capture at least sender/subject/body text when all else fails. |
| M1 | MSG | `extract_msg` (current) | Primary path. |
| M2 | MSG fallback | `msg_parser` (pure Python) | Works without Outlook dependencies. |
| M3 | MSG rescue | `msgconvert` CLI -> feed into EML pipeline | Optional; guard behind config flag. |

Execution model:
1. Wrap parsing in `run_parser(candidate, strategy_name)` helper that logs start/end, captures exceptions, and updates `ParserRun`.
2. Move all parser calls into a new `app/services/parsing.py` orchestrator returning `ParsedEmail` plus trace metadata.
3. When all tiers fail, persist a stub `InputEmail` with `parse_status='failed'`, maintain reference to stored raw bytes, and surface actionable error in UI.

## 3. Retry & Manual Controls
- Add `reparse_email(email_id, strategy="auto"|"mailparser"|...)` in a new `app/services/reparse.py`.
- Email Display page: show “Parse failed” badge with a “Retry parsing” button (triggering reparse service).
- Provide CLI/Streamlit command to bulk retry all failed emails after dependency installation.

## 4. Enhanced Body & Attachment Extraction
- Charset fallback order (`charset`, `message.get_charsets`, `latin-1`, `cp1252`, `utf-8` replace) with recorded outcome.
- Convert RTF-only MSG bodies using `striprtf` (optional dependency) and store plain text fallback.
- Detect `message/rfc822` attachments and recursively parse into related child emails (phase 2 stretch goal).
- Improve attachment sanitization (filename normalization, dedupe) and store origin metadata (top-level vs nested).

## 5. Observability & UX Feedback
- Extend `ParserRun` schema: add `status` enum, `error_message`, `attempt_order`.
- Email Display ingestion summary: list failed files with parser stack trace (first few lines), suggest missing deps.
- Add a “Parser diagnostics” sidebar card enumerating optional components (extract-msg, mailparser, striprtf, msgconvert) with installed/required status.

## 6. Testing Strategy
### Unit / Integration
- **Parsers**: fixtures for
  - malformed MIME headers
  - unknown charsets
  - EML with embedded MSG attachments
  - MSG with only RTF body
  - corrupted MSG to verify fallback stub creation
- **Ingestion**: confirm that every failure still writes `OriginalEmail`, records `ParserRun` entries, and marks `parse_status`.
- **Reparse service**: simulate installing a missing dependency mid-test and ensure statuses update correctly.

### AppTest / E2E
- Create dataset variations (extend `scripts/generate_test_dataset.py`) that drop extension hints, include nested emails, and purposely break the first parser tier.
- AppTest scenario: run ingestion, confirm UI lists partially parsed items, trigger “Retry parsing” button, verify success state.
- Playwright scenario: ingest dataset with failures, view warning, install dependency (mock), re-run ingestion or reparse.

### Tooling
- Add pytest marker `@pytest.mark.requires_msgconvert` for optional CLI-based tests.
- CI matrix job enabling optional deps to ensure fallbacks stay healthy.

## 7. Rollout & Phasing
1. **Phase A**: content sniffing + parser orchestrator + failure persistence (core resilience).
2. **Phase B**: reparse service + UI hooks + parser diagnostics.
3. **Phase C**: nested email/attachment recursion + advanced archive ingestion.
4. **Phase D**: broaden test dataset + finalize AppTest/E2E coverage.

Document progress in this file; move completed items into a changelog section as we ship each phase.


