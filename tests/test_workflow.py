"""Batch orchestration: ordering, isolation, skips, concurrency and statuses."""

from __future__ import annotations

import asyncio
import csv
import json

from caseflow.llm_client import ProviderError
from caseflow.workflow import run_batch
from conftest import (
    EMAIL_PAYLOAD,
    SIMPLE_COMPLAINT,
    SUMMARY_PAYLOAD,
    FakeProvider,
    default_handler,
    extraction_payload,
    make_settings,
)


def _batch(tmp_path, input_dir, provider, **kw):
    return asyncio.run(run_batch(make_settings(tmp_path, input_dir, **kw), provider))


def _rows(result):
    with result.report_path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def test_extraction_completes_before_downstream_tasks(tmp_path, complaint_dir):
    provider = FakeProvider(default_handler, delay=0.05)
    result = _batch(tmp_path, complaint_dir, provider)
    calls = {c["task"]: c for c in provider.calls}
    assert calls["customer_email"]["start"] >= calls["extraction"]["end"]
    assert calls["case_summary"]["start"] >= calls["extraction"]["end"]
    # B and C overlap in time -> they ran concurrently
    assert calls["case_summary"]["start"] < calls["customer_email"]["end"]
    assert result.documents[0].processing_status == "success"


def test_downstream_failure_keeps_other_artifacts(tmp_path, complaint_dir):
    def handler(req):
        if req.task_name == "customer_email":
            raise ProviderError("bad_request", "rejected")
        return default_handler(req)

    result = _batch(tmp_path, complaint_dir, FakeProvider(handler))
    [row] = _rows(result)
    assert row["processing_status"] == "partial_success"
    assert (row["extraction_status"], row["email_status"], row["summary_status"]) == ("succeeded", "failed", "succeeded")
    assert (result.run_dir / row["structured_output_path"]).exists()
    assert (result.run_dir / row["summary_output_path"]).exists()
    assert row["email_output_path"] == "" and row["error_stage"] == "customer_email"
    assert row["review_required"] == "Yes"


def test_extraction_failure_skips_downstream(tmp_path, complaint_dir):
    provider = FakeProvider(lambda r: (_ for _ in ()).throw(ProviderError("bad_request", "no")))
    result = _batch(tmp_path, complaint_dir, provider)
    [row] = _rows(result)
    assert row["processing_status"] == "failed"
    assert row["email_status"] == row["summary_status"] == "skipped"
    assert {c["task"] for c in provider.calls} == {"extraction"}
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["documents"][0]["tasks"]["customer_email"]["skip_reason"] == "extraction_failed"


def _noncomplaint_handler(complaint):
    evidence = [ev for ev in extraction_payload()["evidence"] if ev["field_name"] not in ("complaint", "overall_case_status")]
    status = "unknown"
    if complaint is False:
        evidence.append({"field_name": "complaint", "source_quote": "I want this fixed."})
        status = "not_a_complaint"
        evidence.append({"field_name": "overall_case_status", "source_quote": "Status: open"})
    summary = {**SUMMARY_PAYLOAD, "review_required": True, "review_reasons": ["unclear"]}

    def handler(req):
        if req.task_name == "extraction":
            return extraction_payload(complaint=complaint, overall_case_status=status, evidence=evidence)
        if req.task_name == "case_summary":
            return summary
        raise AssertionError("email must not be requested")
    return handler


def test_email_skipped_for_noncomplaint(tmp_path, complaint_dir):
    result = _batch(tmp_path, complaint_dir, FakeProvider(_noncomplaint_handler(False)))
    [row] = _rows(result)
    assert row["processing_status"] == "success"
    assert row["email_status"] == "skipped" and row["email_skip_reason"] == "not_a_complaint"
    assert row["complaint"] == "No"


def test_email_skipped_and_review_flagged_for_unconfirmed_complaint(tmp_path, complaint_dir):
    result = _batch(tmp_path, complaint_dir, FakeProvider(_noncomplaint_handler(None)))
    [row] = _rows(result)
    assert row["email_skip_reason"] == "complaint_unconfirmed"
    assert row["complaint"] == "Unknown" and row["review_required"] == "Yes"


def test_batch_continues_after_corrupt_file(tmp_path, complaint_dir):
    (complaint_dir / "b_broken.pdf").write_bytes(b"%PDF-1.4 broken")
    (complaint_dir / "c_empty.txt").write_bytes(b"")
    (complaint_dir / "d_complaint.txt").write_text(SIMPLE_COMPLAINT, encoding="utf-8")
    result = _batch(tmp_path, complaint_dir, FakeProvider(default_handler))
    statuses = {r["source_file"]: (r["processing_status"], r["error_code"]) for r in _rows(result)}
    assert statuses == {
        "a_complaint.txt": ("success", ""),
        "b_broken.pdf": ("failed", "corrupted_file"),
        "c_empty.txt": ("failed", "empty_document"),
        "d_complaint.txt": ("success", ""),
    }


def test_global_llm_concurrency_limit_respected(tmp_path, complaint_dir):
    for i in range(6):
        (complaint_dir / f"x{i}.txt").write_text(SIMPLE_COMPLAINT, encoding="utf-8")
    provider = FakeProvider(default_handler, delay=0.03)
    result = _batch(tmp_path, complaint_dir, provider, batch_concurrency=5, llm_concurrency=2)
    assert len(provider.calls) == 7 * 3
    assert provider.peak == 2 == result.llm_peak_concurrency


def test_fatal_provider_error_aborts_remaining_documents(tmp_path, complaint_dir):
    for i in range(3):
        (complaint_dir / f"x{i}.txt").write_text(SIMPLE_COMPLAINT, encoding="utf-8")
    provider = FakeProvider(lambda r: (_ for _ in ()).throw(
        ProviderError("authentication_failed", "401", fatal=True)))
    result = _batch(tmp_path, complaint_dir, provider, batch_concurrency=1)
    assert result.status == "aborted"
    assert len(provider.calls) == 1  # no retries, no further documents sent
    assert [d.processing_status for d in result.documents].count("aborted") == 3


def test_outputs_saved_are_schema_valid_and_isolated_per_run(tmp_path, complaint_dir):
    r1 = _batch(tmp_path, complaint_dir, FakeProvider(default_handler))
    r2 = _batch(tmp_path, complaint_dir, FakeProvider(default_handler))
    assert r1.run_dir != r2.run_dir and r1.report_path.exists() and r2.report_path.exists()
    from caseflow.schemas import CaseExtraction, CaseSummary, CustomerEmail
    [row] = _rows(r1)
    CaseExtraction.model_validate_json((r1.run_dir / row["structured_output_path"]).read_text())
    CustomerEmail.model_validate_json((r1.run_dir / row["email_output_path"]).with_suffix(".json").read_text())
    CaseSummary.model_validate_json((r1.run_dir / row["summary_output_path"]).with_suffix(".json").read_text())
    assert EMAIL_PAYLOAD["subject"] in (r1.run_dir / row["email_output_path"]).read_text()


def test_interruption_preserves_completed_outputs_and_manifest(tmp_path, complaint_dir):
    for i in range(4):
        (complaint_dir / f"x{i}.txt").write_text(SIMPLE_COMPLAINT, encoding="utf-8")
    settings = make_settings(tmp_path, complaint_dir, batch_concurrency=1)
    provider = FakeProvider(default_handler, delay=0.05)

    async def go():
        task = asyncio.create_task(run_batch(settings, provider))
        await asyncio.sleep(0.4)  # let the first document or two finish
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(go())
    [run_dir] = [p for p in (tmp_path / "out").iterdir() if p.is_dir()]
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    statuses = [d["processing_status"] for d in manifest["documents"]]
    assert manifest["status"] == "interrupted"
    assert "success" in statuses and "interrupted" in statuses
    assert (run_dir / "final_report.csv").exists()
    assert list((run_dir / "structured_data").glob("*.json"))
