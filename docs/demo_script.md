# CaseFlow AI — 5-Minute Demo Script

Preparation: activate `.venv` and run `python scripts/generate_sample_documents.py` once. Keep the project open in your editor and a terminal ready. Delete old `output/` folders if you want a clean screen.

| Time | Segment | What to show and say |
|---|---|---|
| 0:00–0:30 | **Business objective** | "Support teams get complaints as emails, PDFs, forms and chat exports. CaseFlow turns each one into validated case data, a draft reply, and a manager summary. Unknowns stay unknown, and risky cases are flagged for a human." |
| 0:30–1:00 | **Input examples** | Open `data/`. Point out the three formats. Open `08_pending_refund_injection.txt`: "the refund is only *scheduled*, and the customer line tries to inject instructions." Open `03_...docx`: the details are in a *table*. Mention the `.csv` that will be skipped. |
| 1:00–1:40 | **Workflow** | Show the Mermaid diagram in `docs/architecture.md`. "Task A extraction must pass Pydantic and evidence checks first. Then the email and the summary run *in parallel*. A global semaphore caps real API calls." |
| 1:40–2:15 | **Batch execution** | Run `caseflow process --input data --output output --provider mock`. Point at the interleaved log lines (documents run concurrently), the MOCK banner, the counts (9 successful, 1 skipped), the peak concurrent LLM calls (3), and the report path. Say clearly: "Mock mode uses canned fixtures, not real AI. `--provider openai` makes the real calls." |
| 2:15–2:50 | **Structured JSON** | Open `structured_data/08-...json`. `overall_case_status: in_progress`, not resolved. `escalation_required: null`, not false. The injection is listed in `ambiguities`. The `evidence` quotes are verbatim and checked by code. |
| 2:50–3:20 | **Generated email** | Open `customer_emails/08-...md`. It says "approved and scheduled", not completed, and does not claim $500. Open `04-...md`: `Dear Customer`, asks for contact details (recipient missing). Note there is no email file for 05 (not a complaint) or 09 (complaint unconfirmed). |
| 3:20–3:45 | **Internal summary** | Open `case_summaries/03-...md`. "Action taken" is kept separate from "Recommended next action". Escalation is *required but not submitted*. Review required: YES, with reasons. |
| 3:45–4:15 | **Consolidated CSV** | Open `final_report.csv` in a spreadsheet. Show Yes/No/**Unknown**, `email_skip_reason`, `recipient_missing`, `review_required`, and the `'+1-555-0142` formula-safe phone number. |
| 4:15–4:45 | **Graceful failure** | Run `caseflow process --input data_failure_demo --output output --provider mock` → exit code 1. Show the CSV `error_code` column: `empty_document`, `encoding_error`, `corrupted_file`, `encrypted_pdf`, `ocr_required`, `mock_fixture_missing`. The one good file still produced all three outputs. |
| 4:45–5:00 | **Limitations** | No OCR, attachments are not opened, evidence proves presence not meaning, drafts need human review, and the live API was only exercised by the opt-in smoke test. `pytest`: 59 offline tests. |

---

## Likely viva questions

**Why Pydantic?**
It turns "the model returned some JSON" into a typed contract. It rejects wrong types, unknown enum values and extra keys (`extra='forbid'`), and runs our consistency rules. The same model also produces the JSON schema sent to OpenAI's Structured Outputs. Nothing is saved unless it validates.

**Isn't Structured Outputs enough on its own?**
No. It guarantees *shape*, not *truth*. Local validation adds rules the schema can't express: evidence is required for populated fields, quotes must exist in the source, `not_a_complaint` implies `complaint=false`, and emails can't mention amounts that aren't in the source.

**Why is extraction sequential and first?**
Tasks B and C depend on its *validated* output. Whether to send an email depends on `complaint`. Both prompts receive the extracted facts. Running them before validation would build on unverified data.

**Why run B and C in parallel?**
They are independent of each other and each is a network call that mostly waits. Running them together roughly halves latency per document. Each branch catches its own errors, so one failing doesn't lose the other.

**How do you stop parallelism exceeding API rate limits?**
With two limits. `BATCH_CONCURRENCY` controls documents in progress. A single global `LLM_CONCURRENCY` semaphore wraps *every* provider call, so B + C across many documents still never exceeds the cap. The semaphore is released during retry backoff, so a sleeping task doesn't block others. A test checks the measured peak.

**Why not RAG?**
RAG retrieves context from a large knowledge base. Here each document already *is* the full context, and there is no policy or knowledge base to consult. Adding a vector database would add cost and failure modes without improving answers. It would also make it easier for the model to cite policies that the email must not invent.

**How do you prevent hallucination?**
There are several layers:
- Prompts say to use null or unknown instead of guessing.
- Evidence quotes are verified against the source.
- A grounding guard rejects invented amounts, ticket numbers and contact details.
- There is one correction retry, and invalid output is never saved.
- A review flag routes risky cases to a human.

It reduces risk; it can't eliminate it. That is why drafts are never sent automatically.

**What about prompt injection?**
The document is fenced as untrusted data, and the system prompt says to ignore instructions inside it. The model has no tools. File paths come from code, not the model. Output is validated. Sample 08 demonstrates this: the "$500 refund completed" instruction doesn't appear in any output.

**Why Yes / No / Unknown instead of Yes / No?**
"The document doesn't say" is different from "no". Mapping unknown to "No" would, for example, hide cases where escalation *might* be required.

**How are retries bounded?**
SDK auto-retries are off. Our loop allows `MAX_RETRIES` transport retries with exponential backoff, jitter and Retry-After, plus at most one correction retry. The worst case is `2 × (MAX_RETRIES + 1)` calls per task. A 401, 404 or quota error is not retried, and it aborts the run.

**What happens if one file is corrupt?**
It becomes a `failed` row with a specific `error_code`. The rest of the batch continues, and the exit code is 1.

**What does mock mode prove?**
The whole pipeline (ingestion, validation, dependency ordering, concurrency, writers, report) with deterministic inputs. It does *not* prove model quality. It is labelled as mock everywhere, and it refuses documents it has no fixture for.

**What would you add next?**
An OCR step for scanned PDFs, a human approval step before emails are sent, prompt evaluations with a labelled test set, and cost/token tracking in the manifest.
