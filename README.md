# CaseFlow AI — AI Customer Complaint & Case Processing System

CaseFlow AI is a batch command-line tool. It reads customer documents (TXT, PDF, DOCX) from a folder and runs **three separate LLM tasks** on each one:

1. **Task A: structured extraction.** It extracts validated case data (customer, product, category, status, escalation, and so on), with verbatim evidence quotes.
2. **Task B: customer email draft.** It writes a professional reply for each *confirmed* complaint. Drafts are never sent.
3. **Task C: management summary.** It writes a short internal summary with a review flag.

Everything is validated with Pydantic and saved as JSON and readable Markdown, plus a manifest and one consolidated `final_report.csv` per run.

> **Business problem.** Support teams receive complaints as emails, forms, chat exports and scanned letters. Triage by hand is slow and inconsistent. Staff also tend to "fill in" unknowns: they assume a refund happened, or treat an escalation request as if the escalation had already happened. CaseFlow gives every document the same structured treatment. It keeps unknowns *unknown*, points to evidence, and flags cases a human must review.

---

## Contents
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Input formats](#input-formats)
- [Outputs](#outputs)
- [How the workflow runs](#how-the-workflow-runs)
- [Schema fields](#schema-fields)
- [Error handling](#error-handling)
- [Tests](#tests)
- [Privacy and safety](#privacy-and-safety)
- [Limitations](#limitations)
- [Git setup](#git-setup)

More documentation: [docs/architecture.md](docs/architecture.md) (diagram and requirement mapping), [docs/demo_script.md](docs/demo_script.md) (5-minute demo and viva Q&A).

---

## Quick start

Requires **Python 3.11+**. It was developed and tested on Python 3.14.

```bash
python -m venv .venv
```

Activate the environment:

| OS | Command |
|---|---|
| macOS / Linux | `source .venv/bin/activate` |
| Windows (PowerShell) | `.venv\Scripts\Activate.ps1` |
| Windows (cmd) | `.venv\Scripts\activate.bat` |

```bash
pip install -e '.[dev]'
```

(On Windows cmd, use double quotes: `pip install -e ".[dev]"`.)

Create your `.env`:

```bash
cp .env.example .env
```

On Windows: `copy .env.example .env` (cmd) or `Copy-Item .env.example .env` (PowerShell).

Generate the synthetic sample documents. They are also committed, so this step is optional:

```bash
python scripts/generate_sample_documents.py
```

Run the **offline demo** (no API key, no cost):

```bash
caseflow process --input data --output output --provider mock
```

Run with the **real OpenAI API**. This needs `OPENAI_API_KEY` in `.env`, and it sends document text to OpenAI:

```bash
caseflow process --input data --output output --provider openai
```

Run the **graceful-failure demo**, which uses corrupt, empty, encrypted, scanned and wrongly encoded files:

```bash
caseflow process --input data_failure_demo --output output --provider mock
```

Run the tests:

```bash
pytest
```

`python -m caseflow process ...` works the same way as the `caseflow` command.

### CLI options

```
caseflow process [--input DIR] [--output DIR] [--provider {mock,openai}] [--recursive]
                 [--log-dir DIR] [--batch-concurrency N] [--llm-concurrency N]
                 [--company-name NAME] [--log-level {DEBUG,INFO,WARNING,ERROR}]
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Every document succeeded. Expected email skips and skipped unsupported files count as success. |
| `1` | The run completed, but at least one document **failed** or was only **partially** processed. |
| `2` | Fatal: invalid configuration at startup, or the run **aborted** (for example, an invalid API key or unknown model). |
| `130` | Interrupted with Ctrl+C. Completed outputs and the manifest are kept. |

### Mock vs real mode

| | `--provider mock` | `--provider openai` |
|---|---|---|
| API key | not needed | `OPENAI_API_KEY` required |
| Network or cost | none | one request per task (3 per confirmed complaint) |
| Outputs | **canned fixtures** for the 9 bundled demo documents | real model output |
| Unknown documents | fail clearly with `mock_fixture_missing` | processed |
| Labelling | "MOCK MODE" in the terminal, `provider_mode=mock` in the CSV, `is_mock: true` in the manifest, and a banner in every Markdown file | `provider_mode=openai` |

Mock mode goes through **the same** schemas, evidence checks, task dependencies, concurrency limits, writers and report as real mode. Only the provider call is replaced. Mock output is **not** AI output and is always labelled that way.

---

## Configuration

All settings come from `.env` or environment variables. CLI flags override them.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | – | Required for `--provider openai` only. |
| `OPENAI_MODEL` | `gpt-5.5` | Must support Structured Outputs on the Responses API. `gpt-5.5` is the model used in the official `openai` Python SDK 3.x docs. This default appears in one place only (`config.py`). |
| `COMPANY_NAME` | `Brightlane Home Supplies` | Used in the email sign-off. |
| `BATCH_CONCURRENCY` | `4` | Documents processed at once. |
| `LLM_CONCURRENCY` | `3` | Global cap on in-flight API requests across all documents and both downstream tasks. |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Per-request timeout. |
| `MAX_RETRIES` | `3` | Extra attempts for timeouts, 429s and 5xx errors. |
| `MAX_FILE_BYTES` | `10485760` | Larger files are reported as `document_too_large`. |
| `MAX_DOCUMENT_CHARS` | `60000` | Longer extracted text is reported as `document_too_large`. **Nothing is ever truncated.** |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |

Configuration is validated at startup. A missing key in real mode, an out-of-range concurrency value or a missing input folder gives exit code `2` before any work starts.

### Dependencies

Pinned ranges in `pyproject.toml`, validated together on 2026-09-30:

- `openai` 3.22.1
- `pydantic` 2.13
- `python-dotenv` 1.2
- `pypdf` 6.19
- `python-docx` 1.2
- dev extras: `pytest` 9.1 and `reportlab` 5.0 (reportlab is only needed to generate sample PDFs)

---

## Input formats

| Format | How text is extracted |
|---|---|
| `.txt` | Decoded as UTF-8. A BOM is removed. Non-UTF-8 files fail with `encoding_error` and the byte position. |
| `.pdf` | Text from **every page**, in page order. Encrypted PDFs that cannot be opened fail with `encrypted_pdf`. PDFs with no text layer fail with `ocr_required`. |
| `.docx` | Paragraphs **and table cells** in document order. Each table row becomes `cell | cell`, and merged cells are emitted once. |

- Extensions are matched case-insensitively (`.PDF` works).
- By default only the top level of the input folder is scanned. Add `--recursive` to include subfolders.
- Paths are sorted, so report order is always the same.
- Hidden files (`.DS_Store` and similar) are ignored.
- Any other extension (for example `.csv`) is reported as **skipped** (`unsupported_format`) and is never sent to the LLM.
- **Scanned PDFs need OCR.** This version does **not** do OCR. It detects PDFs with no usable text and reports `ocr_required`. Run such files through an OCR tool first (for example `ocrmypdf`).

**Document IDs** combine a slug of the relative path (including the extension) with 8 characters of the file's SHA-256, for example `08-pending-refund-injection-txt-cf8c3c27`. Files with the same name in different subfolders, or `a.txt` next to `a.pdf`, never overwrite each other's outputs.

### Sample data

All sample data is synthetic: `example.com` emails and 555 or drama-range phone numbers. `data/` holds nine demo documents and one unsupported file:

| File | Scenario |
|---|---|
| `01_billing_refund_resolved.txt` | Billing complaint with a **completed** refund |
| `02_delivery_open.pdf` (2 pages) | Delivery complaint that is still **open** |
| `03_defective_product_escalation.docx` (table) | Safety defect; escalation **required but not yet submitted** |
| `04_service_missing_contact.txt` | Service complaint with **no contact details** |
| `05_positive_feedback.pdf` | Positive feedback plus a question: **not a complaint** |
| `06_ambiguous_conflicting_status.docx` | Notes that **conflict** ("resolved" vs "not resolved") |
| `07_invoice_attached_claim.pdf` | Customer **claims** an invoice is attached (not verified) |
| `08_pending_refund_injection.txt` | Refund **pending** (not complete), plus a **prompt-injection** line |
| `09_unconfirmed_enquiry.docx` | Unclear whether it is a complaint: **complaint unconfirmed** |
| `10_order_export.csv` | Unsupported format: **skipped** |

`data_failure_demo/` contains one good document plus an empty file, a whitespace-only file, a Latin-1 file, a corrupt PDF, a corrupt DOCX, a scanned (text-less) PDF, a password-protected PDF, and a valid complaint that mock mode has no fixture for.

---

## Outputs

Each run writes to its **own folder** named by run ID. Earlier runs are never overwritten:

```
output/
├── LATEST_RUN.txt                      # ID of the most recent run
└── 20260930T062801Z-e563/              # <UTC timestamp>-<random>
    ├── structured_data/<document_id>.json     # Task A (CaseExtraction)
    ├── customer_emails/<document_id>.json|.md # Task B (CustomerEmail) + copyable draft
    ├── case_summaries/<document_id>.json|.md  # Task C (CaseSummary) + readable table
    ├── run_manifest.json                      # task timings, attempts, errors, paths
    ├── final_report.csv                       # one row per discovered file
    └── dashboard.html                         # open in a browser: visual view of this run
logs/<run_id>.log
```

**A run's `final_report.csv` is at `output/<run_id>/final_report.csv`**, and the terminal prints its path. All paths inside the manifest and CSV are relative to the run folder, so you can move or zip the folder.

**Dashboard.** Open `output/<run_id>/dashboard.html` in any browser. It works offline and needs no server. It shows:
- run statistics
- a filterable document list
- each document's pipeline status, extracted fields with evidence quotes, the email draft with copy buttons, the summary and the task log

To rebuild it for the latest run, or for a specific run, use:

```bash
caseflow dashboard
```
```bash
caseflow dashboard output/<run_id>
```

Every `.json` file contains exactly the validated Pydantic model, so it re-validates against its schema. Raw model text is never saved.

### Example: structured extraction (`08_pending_refund_injection.txt`, mock)

```json
{
  "customer_name": "Hiroshi Tanaka",
  "email": "hiroshi.tanaka@example.com",
  "phone_number": null,
  "complaint_category": "refund",
  "resolution_provided": "Return received at warehouse on 9 May; refund approved and scheduled to the original payment method, but not yet completed and no date confirmed.",
  "complaint": true,
  "escalation_required": null,
  "overall_case_status": "in_progress",
  "missing_information": ["refund completion date", "refund amount", "phone number"],
  "ambiguities": ["The transcript contains an instruction-like message asking the system to mark the case resolved and claim a completed refund; it was treated as data and ignored."],
  "evidence": [
    {"field_name": "resolution_provided", "source_quote": "A refund has been approved and is scheduled to be issued to your original payment method."},
    {"field_name": "resolution_provided", "source_quote": "I cannot confirm the exact date."}
  ]
}
```
*(Shortened. The real file includes every field and every evidence item.)*

### Example: email draft Markdown

````
# Customer email draft - 01_billing_refund_resolved.txt
> **DRAFT ONLY - NOT SENT.** Review before sending. Generated by: MOCK provider (...)
**To:** priya.raman@example.com
**Subject** (copy):
```text
Your duplicate membership charge has been refunded
```
**Email body** (copy):
```text
Dear Priya Raman,
...
Kind regards,
Customer Support Team
Brightlane Home Supplies
```
````

### CSV report

The report has one row per discovered file, including skipped and failed files. The columns are:

`run_id, document_id, source_file, file_format, provider_mode, processing_status, extraction_status, email_status, summary_status, customer_name, email, phone_number, product_or_service, complaint_category, complaint, escalation_required, supporting_document_available, overall_case_status, review_required, recipient_missing, missing_information, ambiguities, structured_output_path, email_output_path, summary_output_path, email_skip_reason, error_stage, error_code, error_message, duration_seconds`

- **Yes / No / Unknown.** Boolean fields use `Unknown` when the source does not say. Missing information is **never** turned into `No`. This deliberately extends the assignment's Yes/No examples, because "we don't know" and "no" mean different things to a support team.
- `processing_status` is `success`, `partial_success`, `failed`, `skipped`, `interrupted` or `aborted`. This is **workflow** status. The **business** status of the case is `overall_case_status`.
- Task statuses are `succeeded`, `failed`, `skipped` or `not_run`. `email_skip_reason` explains skips: `not_a_complaint`, `complaint_unconfirmed`, `extraction_failed`, `ingestion_failed` or `unsupported_format`.
- `recipient_missing = Yes` means an email was drafted but the source had no email address.
- Lists (`missing_information`, `ambiguities`) are joined with `; `.
- **Spreadsheet safety.** The CSV is written with Python's `csv` module in UTF-8 with a BOM, so Excel detects the encoding. Any cell starting with `=`, `+`, `-`, `@`, tab or CR gets a leading `'`, which stops spreadsheet apps from running it as a formula. **This affects phone numbers**: `+1-555-0142` is exported as `'+1-555-0142`. The canonical, unescaped value is always in the JSON output.

---

## How the workflow runs

```
Ingest → Extract text → Task A (extract + validate + evidence check) → save
                              ├─ Task B: customer email (only if complaint = true) ─┐  concurrent
                              └─ Task C: management summary ────────────────────────┘
                              → save outputs → report row
```

- **Task A runs first**, because B and C need its *validated* output. If extraction fails, B and C are marked `skipped` with reason `extraction_failed`, and no downstream call is made.
- **B and C run concurrently** with `asyncio.gather`. Each branch catches its own errors, so a failed email never discards a successful summary or extraction. The document is then `partial_success`.
- **Email rules.** If `complaint=true`, a draft is written. If `complaint=false`, the email is skipped with reason `not_a_complaint`; this counts as a successful outcome. If `complaint=null`, it is skipped with reason `complaint_unconfirmed` and the case is flagged for review. A missing email address does not stop the draft; the report shows `recipient_missing=Yes`.
- **Two concurrency limits.** `BATCH_CONCURRENCY` limits how many documents are processed at once. `LLM_CONCURRENCY` is a **global semaphore** around every provider request, so the real API request count never exceeds the cap, even when B and C run in parallel for several documents. The semaphore is held only while a request is in flight, **not** during retry backoff. The manifest records `peak_in_flight`.
- The manifest records timings, attempt counts, whether a correction retry was used, errors and output paths for **each task** (`ingestion`, `extraction`, `customer_email`, `case_summary`).

Code map:

| Module | Contents |
|---|---|
| `cli.py` | Command line |
| `config.py` | Settings |
| `ingestion.py` | File discovery and text extraction |
| `prompts.py` | Prompt templates |
| `schemas.py` | Pydantic models and grounding checks |
| `llm_client.py` | Providers, errors and limiter |
| `tasks.py` | The three tasks, retries and correction |
| `workflow.py` | Orchestration, report rows and manifest |
| `output_writer.py` | Atomic writes, Markdown and CSV |
| `logging_config.py` | Logging and redaction |
| `mock_fixtures.py` | Canned demo responses |

---

## Schema fields

**`CaseExtraction`** (Task A; `extra='forbid'`):

| Field | Type |
|---|---|
| `customer_name`, `email`, `phone_number` (kept as text), `product_or_service`, `issue_description`, `resolution_provided` | `str \| null` |
| `complaint_category` | `billing \| delivery \| product_quality \| service_quality \| refund \| technical \| other \| unknown` |
| `complaint`, `escalation_required`, `supporting_document_available` | `bool \| null` |
| `overall_case_status` | `open \| in_progress \| resolved \| closed \| escalated \| not_a_complaint \| unknown` |
| `missing_information`, `ambiguities` | `list[str]` |
| `evidence` | `list[{field_name, source_quote}]` |

Rules enforced **in code**, on top of the prompt rules:

- Every populated fact or classification (not null and not `unknown`) needs at least one evidence item.
- Every `source_quote` must occur **verbatim** in the extracted text. Before matching, both sides go through a controlled normalisation: Unicode NFKC, typographic quotes and dashes converted to ASCII, whitespace runs collapsed, and case folding. `email` and `phone_number` values must also appear in the source.
- `overall_case_status = not_a_complaint` requires `complaint = false`.
- A non-complaint cannot have `escalation_required = true`.
- `email` must look like one address.

**Limitation:** evidence matching proves a quote *exists* in the source. It does not prove the model *interpreted* it correctly. That is why the review flag and human review remain part of the process.

Rules given to the model in the prompt: don't infer names from email addresses; a planned or approved refund is not a completed refund; an escalation request is not an escalation already done; a missing resolution does not mean resolved; conflicting statements get `unknown` and are listed in `ambiguities`; `supporting_document_available=true` only records the source's *claim* that something is attached, because the app never opens attachments.

**`CustomerEmail`** (Task B) has `subject` (one line), `greeting`, `body` and `closing`. The greeting uses the customer's name, or `Dear Customer` when the name is unknown.

**`CaseSummary`** (Task C) has `case_overview`, `key_issue`, `action_taken` (`Not documented` when nothing is documented), `current_status`, `recommended_next_action` (phrased as a proposal), `review_required` and `review_reasons`. `review_reasons` is an addition that explains *why* a case is flagged.

**Grounding guard (B and C).** Money amounts, ticket/order/invoice-style references, email addresses, URLs and phone numbers in generated text must appear in the source document. The company name is allowed in emails. This heuristic catches invented refund amounts, ticket numbers and contact details. Summaries must also set `review_required=true` whenever the complaint is unconfirmed or ambiguities were recorded.

---

## Error handling

| Situation | Behaviour |
|---|---|
| Unsupported, empty, corrupt, encrypted, scanned, badly encoded or oversized file | File-level failure or skip with a clear `error_code`; the batch continues |
| Timeout, HTTP 429, 408, 409 or 5xx | Retried up to `MAX_RETRIES` times with exponential backoff and jitter (capped at 30 s). `Retry-After` / `retry-after-ms` headers are honoured (capped at 60 s). |
| Invalid key (401), no permission (403), unknown model (404), no quota | **Not retried.** Marked fatal: the run stops sending documents, the remaining ones become `aborted`, and the exit code is 2. |
| Other 4xx errors | Not retried. That task fails and the batch continues. |
| Invalid JSON, schema violation, invented evidence, ungrounded amount | **One** correction retry with brief validation feedback. If it still fails, the task fails with `validation_failed`. Invalid data is never saved. |
| Ctrl+C | Completed outputs are kept, and the manifest and CSV are written with unfinished documents marked `interrupted`. Exit code 130. |

The retry budget is bounded. The SDK's own automatic retries are **disabled** (`max_retries=0`), so retries are not multiplied across layers. The worst case per task is `2 × (MAX_RETRIES + 1)` provider calls. Each request is also bounded by the timeout.

**Atomic writes.** Every output is written to a temporary file, fsynced, then renamed into place. A crash never leaves a half-written file.

**Logging.** The console gets concise progress; `logs/<run_id>.log` gets detail. Log lines contain run ID, document ID, task, duration, attempts and outcome codes. **They never contain** API keys, document text, customer emails, phone numbers or raw provider responses. A redaction filter is a second line of defence, and error messages stored in the report are sanitised the same way.

---

## Tests

```bash
pytest               # 60 offline tests, no network
pytest -q -k workflow
```

| Area | Test file |
|---|---|
| TXT (BOM, bad encoding), multi-page PDF, DOCX tables in order, empty/corrupt/encrypted/scanned/oversized, discovery, ID collisions | `tests/test_ingestion.py` |
| Nullable fields → `Unknown`, extra keys forbidden, malformed types, evidence required, invented quotes rejected, normalisation, grounding guard | `tests/test_schemas.py` |
| Bounded retries, Retry-After, semaphore released during backoff, non-retryable errors, one correction retry, timeouts | `tests/test_tasks.py` |
| Extraction before B and C, B and C concurrent, independent failure → `partial_success`, email skips, corrupt file doesn't stop the batch, global LLM cap respected, fatal abort, interruption | `tests/test_workflow.py` |
| CSV quoting and formula escaping, atomic writes, full mock demo end to end, failure demo exit code, startup errors | `tests/test_output_and_cli.py` |
| Real `OpenAIProvider` against the real `openai` SDK with **mocked HTTP**: request shape (Responses API, strict JSON schema, `store=false`), parsing, and error mapping for 401, 404, 429, quota, 5xx and 400 | `tests/test_openai_provider.py` |
| **Opt-in paid smoke test** against the live API | `tests/test_real_provider_smoke.py` |

The live smoke test is skipped unless you explicitly authorise the spend:

```bash
CASEFLOW_RUN_PAID_SMOKE=1 pytest -m real_provider -s
```

It needs `OPENAI_API_KEY` and makes 3 API calls.

---

## Privacy and safety

- **Real mode sends document text to OpenAI** (the Responses API with `store=false`). Only process documents you are allowed to share with that provider, under your organisation's data policy. Mock mode sends nothing anywhere.
- **Documents are untrusted data.** Prompts wrap the source in `<source_document>` tags and tell the model to ignore instructions inside it. The model has no tools. Output paths, file names and folder layout come from code, never from the model. Everything the model returns is schema- and evidence-validated before it is saved. Sample 08 contains an injection attempt; the saved outputs record it as an ambiguity and do not act on it.
- **Emails are drafts only.** Nothing is ever sent.
- Put real customer documents in `data/private/`, which Git ignores, or outside the repository. `.env`, `output/`, `logs/` and `.venv/` are also ignored.

---

## Limitations

- **No OCR.** Scanned PDFs are reported as `ocr_required`.
- **No attachment handling.** "Attached" is recorded only as a claim in the source.
- **Evidence matching checks presence, not meaning**, and the grounding guard is a pattern heuristic. Neither replaces human review of drafts before sending.
- **Real mode was only tested with mocked HTTP.** The live API path was **not** run during development (no key was available); the smoke test is there for you to run. Model behaviour can vary, and the correction retry and validators are the safety net.
- **Mock mode only understands the bundled demo documents**, matched by file name. Edited demo files fail validation, and new files fail with `mock_fixture_missing`.
- **Size limits.** Documents above the limits are rejected rather than chunked.
- **Scope.** There is no database, queue, web UI or authentication, because this is a batch CLI by design. RAG, fine-tuning and multi-agent frameworks are not used: each document holds all the context its tasks need.

---

## Git setup

`git init` has not been run. To publish your own copy:

```bash
git init
git add .
git status          # check: no .env, output/, logs/, .venv/ or real documents
git commit -m "CaseFlow AI capstone"
git branch -M main
git remote add origin https://github.com/<your-username>/caseflow-ai.git
git push -u origin main
```

Create the empty `caseflow-ai` repository on GitHub first, and don't add a README there.
