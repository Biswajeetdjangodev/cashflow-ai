"""Batch orchestration.

Per document:
    ingest -> extract text -> Task A (extraction + validation) -> save
                                   |-- Task B: customer email (if complaint=true) --|
                                   |-- Task C: management summary ------------------|  (concurrent)
                                   -> save outputs -> report row

Documents run concurrently (BATCH_CONCURRENCY); every provider request, from any
document or branch, passes through one global LLM semaphore (LLM_CONCURRENCY).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import output_writer as ow
from .config import Settings
from .dashboard import write_dashboard
from .ingestion import IngestionError, SourceDocument, discover_documents, extract_text
from .llm_client import LLMLimiter, LLMProvider, sanitize
from .prompts import PROMPT_VERSION
from .schemas import CaseExtraction, CaseSummary, bool_to_report
from .tasks import TaskContext, TaskFailed, draft_customer_email, email_decision, extract_case, summarize_case

log = logging.getLogger("caseflow.workflow")

# processing_status values
SUCCESS, PARTIAL, FAILED, SKIPPED, INTERRUPTED, ABORTED = (
    "success", "partial_success", "failed", "skipped", "interrupted", "aborted")
# per-task status values
T_OK, T_FAILED, T_SKIPPED, T_PENDING = "succeeded", "failed", "skipped", "not_run"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class TaskRecord:
    name: str
    status: str = T_PENDING
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    attempts: int = 0
    corrected: bool = False
    skip_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    outputs: list[str] = field(default_factory=list)

    def start(self) -> float:
        self.started_at = _now()
        return time.perf_counter()

    def finish(self, t0: float, status: str) -> None:
        self.status = status
        self.finished_at = _now()
        self.duration_seconds = round(time.perf_counter() - t0, 3)

    def skip(self, reason: str) -> None:
        self.status, self.skip_reason = T_SKIPPED, reason


@dataclass
class DocumentResult:
    doc: SourceDocument
    tasks: dict[str, TaskRecord] = field(default_factory=lambda: {
        n: TaskRecord(n) for n in ("ingestion", "extraction", "customer_email", "case_summary")})
    processing_status: str = INTERRUPTED
    extraction: CaseExtraction | None = None
    summary: CaseSummary | None = None
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_seconds: float = 0.0

    def fail(self, stage: str, code: str, message: str) -> None:
        if self.error_stage is None:  # keep the first (root-cause) error for the report
            self.error_stage, self.error_code, self.error_message = stage, code, message


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    report_path: Path
    manifest_path: Path
    documents: list[DocumentResult]
    status: str  # completed | interrupted | aborted
    elapsed_seconds: float
    provider_mode: str
    llm_peak_concurrency: int
    fatal_error: str | None = None

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in (SUCCESS, PARTIAL, FAILED, SKIPPED, INTERRUPTED, ABORTED)}
        for d in self.documents:
            out[d.processing_status] += 1
        return out


class _Run:
    """State shared by all document coroutines in one batch."""

    def __init__(self, settings: Settings, provider: LLMProvider, run_id: str, run_dir: Path) -> None:
        self.settings = settings
        self.provider = provider
        self.run_id = run_id
        self.run_dir = run_dir
        self.limiter = LLMLimiter(settings.llm_concurrency)
        self.doc_sem = asyncio.Semaphore(settings.batch_concurrency)
        self.ctx = TaskContext(
            provider=provider, limiter=self.limiter, max_retries=settings.max_retries,
            request_timeout=settings.request_timeout_seconds, company_name=settings.company_name,
        )
        self.fatal_error: str | None = None
        self.provider_label = (
            "MOCK provider (canned demo fixtures - not real AI output)" if provider.is_mock
            else f"OpenAI model {provider.model}"
        )

    def rel(self, path: Path) -> str:
        return path.relative_to(self.run_dir).as_posix()


async def process_document(run: _Run, result: DocumentResult) -> DocumentResult:
    """Fills `result` in place, so an interrupted run still reports partial progress."""
    doc = result.doc
    async with run.doc_sem:
        t_doc = time.perf_counter()
        try:
            await _process(run, doc, result)
        finally:
            result.duration_seconds = round(time.perf_counter() - t_doc, 3)
    return result


async def _process(run: _Run, doc: SourceDocument, result: DocumentResult) -> None:
    label = doc.document_id
    tasks = result.tasks
    downstream = (tasks["customer_email"], tasks["case_summary"])

    if run.fatal_error:
        result.processing_status = ABORTED
        result.fail("run", "run_aborted", f"not processed: run aborted ({run.fatal_error})")
        for t in tasks.values():
            t.skip("run_aborted")
        return

    # ---- Stage 1: ingestion / text extraction -----------------------------------
    ing = tasks["ingestion"]
    t0 = ing.start()
    try:
        text = await asyncio.to_thread(
            extract_text, doc, run.settings.max_file_bytes, run.settings.max_document_chars)
    except IngestionError as exc:
        skipped = exc.code == "unsupported_format"
        ing.finish(t0, T_SKIPPED if skipped else T_FAILED)
        ing.error_code, ing.error_message = exc.code, exc.message
        result.processing_status = SKIPPED if skipped else FAILED
        result.fail("ingestion", exc.code, exc.message)
        for t in (tasks["extraction"], *downstream):
            t.skip("unsupported_format" if skipped else "ingestion_failed")
        log.log(logging.INFO if skipped else logging.WARNING,
                "doc=%s stage=ingestion outcome=%s code=%s", label, ing.status, exc.code)
        return
    ing.finish(t0, T_OK)
    log.info("doc=%s stage=ingestion outcome=succeeded chars=%d", label, len(text))

    # ---- Stage 2: Task A - structured extraction (must succeed first) -----------
    ext = tasks["extraction"]
    t0 = ext.start()
    try:
        out = await extract_case(run.ctx, doc.path.name, text, label)
    except TaskFailed as exc:
        ext.finish(t0, T_FAILED)
        ext.attempts, ext.error_code, ext.error_message = exc.attempts, exc.code, exc.message
        if exc.fatal:
            run.fatal_error = exc.code
        result.processing_status = FAILED
        result.fail("extraction", exc.code, exc.message)
        for t in downstream:
            t.skip("extraction_failed")
        log.warning("doc=%s task=extraction outcome=failed code=%s attempts=%d", label, exc.code, exc.attempts)
        return
    extraction = out.value
    result.extraction = extraction
    path = run.run_dir / "structured_data" / f"{doc.document_id}.json"
    ow.write_model_json(path, extraction)
    ext.finish(t0, T_OK)
    ext.attempts, ext.corrected, ext.outputs = out.attempts, out.corrected, [run.rel(path)]
    log.info("doc=%s task=extraction outcome=succeeded attempts=%d duration=%.2fs",
             label, out.attempts, ext.duration_seconds)

    # ---- Stage 3: Tasks B and C, concurrently, failures isolated ----------------
    await asyncio.gather(
        _email_branch(run, doc, text, extraction, tasks["customer_email"], result),
        _summary_branch(run, doc, text, extraction, tasks["case_summary"], result),
    )

    # Expected skips (non-complaints) are success; a failed applicable task is partial.
    failed = [t for t in downstream if t.status == T_FAILED]
    result.processing_status = PARTIAL if failed else SUCCESS


async def _email_branch(run: _Run, doc: SourceDocument, text: str, extraction: CaseExtraction,
                        rec: TaskRecord, result: DocumentResult) -> None:
    label = doc.document_id
    reason = email_decision(extraction)
    if reason is not None:
        rec.skip(reason)
        log.info("doc=%s task=customer_email outcome=skipped reason=%s", label, reason)
        return
    t0 = rec.start()
    try:
        out = await draft_customer_email(run.ctx, extraction, doc.path.name, text, label)
        base = run.run_dir / "customer_emails" / doc.document_id
        ow.write_model_json(base.with_suffix(".json"), out.value)
        ow.atomic_write_text(base.with_suffix(".md"), ow.render_email_markdown(
            out.value, extraction, doc.relative_path, run.provider_label))
    except TaskFailed as exc:
        rec.finish(t0, T_FAILED)
        rec.attempts, rec.error_code, rec.error_message = exc.attempts, exc.code, exc.message
        if exc.fatal:
            run.fatal_error = exc.code
        result.fail("customer_email", exc.code, exc.message)
        log.warning("doc=%s task=customer_email outcome=failed code=%s attempts=%d", label, exc.code, exc.attempts)
        return
    except OSError as exc:
        rec.finish(t0, T_FAILED)
        rec.error_code, rec.error_message = "write_failed", sanitize(str(exc))
        result.fail("customer_email", "write_failed", rec.error_message)
        return
    rec.finish(t0, T_OK)
    rec.attempts, rec.corrected = out.attempts, out.corrected
    rec.outputs = [run.rel(base.with_suffix(".json")), run.rel(base.with_suffix(".md"))]
    log.info("doc=%s task=customer_email outcome=succeeded attempts=%d duration=%.2fs",
             label, out.attempts, rec.duration_seconds)


async def _summary_branch(run: _Run, doc: SourceDocument, text: str, extraction: CaseExtraction,
                          rec: TaskRecord, result: DocumentResult) -> None:
    label = doc.document_id
    t0 = rec.start()
    try:
        out = await summarize_case(run.ctx, extraction, doc.path.name, text, label)
        base = run.run_dir / "case_summaries" / doc.document_id
        ow.write_model_json(base.with_suffix(".json"), out.value)
        ow.atomic_write_text(base.with_suffix(".md"), ow.render_summary_markdown(
            out.value, doc.relative_path, run.provider_label))
    except TaskFailed as exc:
        rec.finish(t0, T_FAILED)
        rec.attempts, rec.error_code, rec.error_message = exc.attempts, exc.code, exc.message
        if exc.fatal:
            run.fatal_error = exc.code
        result.fail("case_summary", exc.code, exc.message)
        log.warning("doc=%s task=case_summary outcome=failed code=%s attempts=%d", label, exc.code, exc.attempts)
        return
    except OSError as exc:
        rec.finish(t0, T_FAILED)
        rec.error_code, rec.error_message = "write_failed", sanitize(str(exc))
        result.fail("case_summary", "write_failed", rec.error_message)
        return
    result.summary = out.value
    rec.finish(t0, T_OK)
    rec.attempts, rec.corrected = out.attempts, out.corrected
    rec.outputs = [run.rel(base.with_suffix(".json")), run.rel(base.with_suffix(".md"))]
    log.info("doc=%s task=case_summary outcome=succeeded attempts=%d duration=%.2fs",
             label, out.attempts, rec.duration_seconds)


# ------------------------------- reporting ---------------------------------- #

def review_required(r: DocumentResult) -> bool | None:
    if r.processing_status == SKIPPED:
        return None
    e = r.extraction
    if e is None:
        return True  # failed documents need a human
    flags = [e.complaint is None, bool(e.ambiguities), r.processing_status == PARTIAL]
    if r.summary is not None:
        flags.append(r.summary.review_required)
    return any(flags)


def report_row(run_id: str, provider_mode: str, r: DocumentResult) -> dict[str, Any]:
    e, t = r.extraction, r.tasks
    email_task = t["customer_email"]

    def first(task: TaskRecord, suffix: str) -> str | None:
        return next((p for p in task.outputs if p.endswith(suffix)), None)

    return {
        "run_id": run_id,
        "document_id": r.doc.document_id,
        "source_file": r.doc.relative_path,
        "file_format": r.doc.file_format,
        "provider_mode": provider_mode,
        "processing_status": r.processing_status,
        "extraction_status": t["extraction"].status,
        "email_status": email_task.status,
        "summary_status": t["case_summary"].status,
        "customer_name": e.customer_name if e else None,
        "email": e.email if e else None,
        "phone_number": e.phone_number if e else None,
        "product_or_service": e.product_or_service if e else None,
        "complaint_category": e.complaint_category if e else None,
        "complaint": bool_to_report(e.complaint) if e else None,
        "escalation_required": bool_to_report(e.escalation_required) if e else None,
        "supporting_document_available": bool_to_report(e.supporting_document_available) if e else None,
        "overall_case_status": e.overall_case_status if e else None,
        "review_required": bool_to_report(review_required(r)) if r.processing_status != SKIPPED else None,
        "recipient_missing": (bool_to_report(e.email is None)
                              if e and email_task.status == T_OK else None),
        "missing_information": "; ".join(e.missing_information) if e else None,
        "ambiguities": "; ".join(e.ambiguities) if e else None,
        "structured_output_path": t["extraction"].outputs[0] if t["extraction"].outputs else None,
        "email_output_path": first(email_task, ".md"),
        "summary_output_path": first(t["case_summary"], ".md"),
        "email_skip_reason": email_task.skip_reason,
        "error_stage": r.error_stage,
        "error_code": r.error_code,
        "error_message": r.error_message,
        "duration_seconds": f"{r.duration_seconds:.3f}",
    }


def build_manifest(run: _Run, docs: list[DocumentResult], status: str, started_at: str,
                   elapsed: float) -> dict[str, Any]:
    counts = {s: 0 for s in (SUCCESS, PARTIAL, FAILED, SKIPPED, INTERRUPTED, ABORTED)}
    for d in docs:
        counts[d.processing_status] += 1
    return {
        "run_id": run.run_id,
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "elapsed_seconds": round(elapsed, 3),
        "provider": {
            "mode": run.provider.name,
            "model": run.provider.model,
            "is_mock": run.provider.is_mock,
            "notice": ("MOCK MODE: outputs are canned fixtures for the demo documents, not real AI results."
                       if run.provider.is_mock else "Real mode: document text was sent to the OpenAI API."),
        },
        "prompt_version": PROMPT_VERSION,
        "settings": run.settings.public_dict(),
        "llm": {"concurrency_limit": run.limiter.limit, "peak_in_flight": run.limiter.peak,
                "total_provider_calls": run.limiter.total_calls},
        "fatal_error": run.fatal_error,
        "counts": counts,
        "paths_relative_to": "this run directory",
        "report": "final_report.csv",
        "documents": [
            {
                "document_id": d.doc.document_id,
                "source_file": d.doc.relative_path,
                "file_format": d.doc.file_format,
                "size_bytes": d.doc.size_bytes,
                "processing_status": d.processing_status,
                "duration_seconds": d.duration_seconds,
                "tasks": {name: asdict(rec) for name, rec in d.tasks.items()},
            }
            for d in docs
        ],
    }


# ------------------------------- entry point -------------------------------- #

async def run_batch(settings: Settings, provider: LLMProvider, run_id: str | None = None) -> RunResult:
    run_id = run_id or ow.make_run_id()
    run_dir = ow.create_run_dir(settings.output_dir, run_id)
    run = _Run(settings, provider, run_id, run_dir)
    started_at, t_run = _now(), time.perf_counter()
    docs = discover_documents(settings.input_dir, settings.recursive)
    log.info("run=%s provider=%s model=%s documents=%d batch_concurrency=%d llm_concurrency=%d",
             run_id, provider.name, provider.model, len(docs),
             settings.batch_concurrency, settings.llm_concurrency)

    results = [DocumentResult(d) for d in docs]  # placeholders -> "interrupted" if never finished
    status = "interrupted"

    async def worker(i: int) -> None:
        try:
            await process_document(run, results[i])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # defensive: one document must never sink the batch
            r = results[i]
            r.processing_status = FAILED
            r.fail("internal", "unexpected_error", sanitize(f"{type(exc).__name__}: {exc}"))
            log.exception("doc=%s unexpected error", docs[i].document_id)

    try:
        await asyncio.gather(*(worker(i) for i in range(len(docs))))
        status = "aborted" if run.fatal_error else "completed"
    finally:
        elapsed = time.perf_counter() - t_run
        report_path = run_dir / "final_report.csv"
        manifest_path = run_dir / "run_manifest.json"
        ow.write_report_csv(report_path, [report_row(run_id, provider.name, r) for r in results])
        ow.write_json(manifest_path, build_manifest(run, results, status, started_at, elapsed))
        ow.atomic_write_text(settings.output_dir / "LATEST_RUN.txt", f"{run_id}\n")
        try:
            write_dashboard(run_dir)
        except Exception:  # the dashboard is a convenience; never fail the run over it
            log.exception("run=%s dashboard could not be written", run_id)
        log.info("run=%s status=%s elapsed=%.2fs report=%s", run_id, status, elapsed, report_path)

    return RunResult(
        run_id=run_id, run_dir=run_dir, report_path=report_path, manifest_path=manifest_path,
        documents=results, status=status, elapsed_seconds=elapsed, provider_mode=provider.name,
        llm_peak_concurrency=run.limiter.peak, fatal_error=run.fatal_error,
    )
