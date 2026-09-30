"""CSV safety, atomic writes, the mock end-to-end demo, and CLI exit codes."""

from __future__ import annotations

import csv
import io
import json
import os

import pytest

from caseflow import cli
from caseflow.output_writer import atomic_write_text, create_run_dir, escape_csv_cell, render_report_csv
from caseflow.schemas import CaseExtraction, CaseSummary, CustomerEmail


def test_formula_injection_escaped():
    for value in ("=SUM(A1)", "+1-555-0142", "-2", "@cmd", "\tx"):
        assert escape_csv_cell(value).startswith("'")
    assert escape_csv_cell("(555) 010-7788") == "(555) 010-7788"
    assert escape_csv_cell(None) == ""


def test_csv_quotes_commas_newlines_and_quotes():
    text = render_report_csv([{"customer_name": 'Doe, "JJ"', "ambiguities": "line1\nline2", "phone_number": "+44 1"}])
    [row] = list(csv.DictReader(io.StringIO(text)))
    assert row["customer_name"] == 'Doe, "JJ"'
    assert row["ambiguities"] == "line1\nline2"
    assert row["phone_number"] == "'+44 1"


def test_atomic_write_replaces_and_leaves_no_temp(tmp_path):
    p = tmp_path / "f.json"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    assert p.read_text() == "two"
    assert os.listdir(tmp_path) == ["f.json"]


def test_run_dir_never_reused(tmp_path):
    create_run_dir(tmp_path, "run1")
    with pytest.raises(FileExistsError):
        create_run_dir(tmp_path, "run1")


EXPECTED = {
    "01_billing_refund_resolved.txt": ("success", "Yes", "succeeded", "closed"),
    "02_delivery_open.pdf": ("success", "Yes", "succeeded", "open"),
    "03_defective_product_escalation.docx": ("success", "Yes", "succeeded", "open"),
    "04_service_missing_contact.txt": ("success", "Yes", "succeeded", "unknown"),
    "05_positive_feedback.pdf": ("success", "No", "skipped", "not_a_complaint"),
    "06_ambiguous_conflicting_status.docx": ("success", "Yes", "succeeded", "unknown"),
    "07_invoice_attached_claim.pdf": ("success", "Yes", "succeeded", "unknown"),
    "08_pending_refund_injection.txt": ("success", "Yes", "succeeded", "in_progress"),
    "09_unconfirmed_enquiry.docx": ("success", "Unknown", "skipped", "unknown"),
    "10_order_export.csv": ("skipped", "", "skipped", ""),
}


def test_mock_demo_end_to_end(tmp_path, demo_dir, capsys):
    code = cli.main(["process", "--input", str(demo_dir), "--output", str(tmp_path / "out"),
                     "--provider", "mock", "--log-dir", str(tmp_path / "logs"), "--log-level", "WARNING"])
    assert code == 0
    out = capsys.readouterr().out
    assert "MOCK MODE" in out and "final_report.csv" in out

    run_id = (tmp_path / "out" / "LATEST_RUN.txt").read_text().strip()
    run_dir = tmp_path / "out" / run_id
    with (run_dir / "final_report.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = {r["source_file"]: r for r in csv.DictReader(fh)}
    got = {k: (r["processing_status"], r["complaint"], r["email_status"], r["overall_case_status"]) for k, r in rows.items()}
    assert got == EXPECTED
    assert all(r["provider_mode"] == "mock" for r in rows.values())
    assert rows["04_service_missing_contact.txt"]["recipient_missing"] == "Yes"
    assert rows["07_invoice_attached_claim.pdf"]["supporting_document_available"] == "Yes"
    assert rows["03_defective_product_escalation.docx"]["escalation_required"] == "Yes"
    assert rows["01_billing_refund_resolved.txt"]["phone_number"] == "'+1-555-0142"

    # Every saved AI JSON output re-validates against its schema.
    for folder, model in (("structured_data", CaseExtraction), ("customer_emails", CustomerEmail),
                          ("case_summaries", CaseSummary)):
        files = list((run_dir / folder).glob("*.json"))
        assert files
        for f in files:
            model.model_validate_json(f.read_text(encoding="utf-8"))
    # Canonical (unescaped) phone number stays in JSON.
    s = json.loads((run_dir / rows["01_billing_refund_resolved.txt"]["structured_output_path"]).read_text())
    assert s["phone_number"] == "+1-555-0142"
    # The injection document did not produce the injected claims.
    email_md = (run_dir / rows["08_pending_refund_injection.txt"]["email_output_path"]).read_text()
    assert "$500" not in email_md and "API key" not in email_md

    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["provider"]["is_mock"] is True and manifest["status"] == "completed"
    log_text = (tmp_path / "logs" / f"{run_id}.log").read_text()
    assert "@example.com" not in log_text and "Priya" not in log_text


def test_failure_demo_exit_code(tmp_path, gen, demo_dir, capsys):
    fail_dir = tmp_path / "fails"
    gen.generate_failure_fixtures(fail_dir, demo_dir)
    code = cli.main(["process", "--input", str(fail_dir), "--output", str(tmp_path / "out"),
                     "--provider", "mock", "--log-dir", str(tmp_path / "logs"), "--log-level", "ERROR"])
    assert code == 1
    assert "failed:               8" in capsys.readouterr().out


def test_real_mode_without_key_is_fatal_startup_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("caseflow.config.load_dotenv", lambda **kw: None)
    code = cli.main(["process", "--input", str(tmp_path), "--provider", "openai"])
    assert code == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_missing_input_folder_is_fatal(tmp_path, capsys):
    assert cli.main(["process", "--input", str(tmp_path / "nope"), "--provider", "mock"]) == 2


def test_dashboard_written_and_escapes_document_text(tmp_path, demo_dir, capsys):
    out = tmp_path / "out"
    cli.main(["process", "--input", str(demo_dir), "--output", str(out), "--provider", "mock",
              "--log-dir", str(tmp_path / "logs"), "--log-level", "ERROR"])
    run_dir = out / (out / "LATEST_RUN.txt").read_text().strip()
    html = (run_dir / "dashboard.html").read_text(encoding="utf-8")
    assert "Hiroshi Tanaka" in html and "Demo mode" in html and "is_mock\": true" in html
    data = html.split('type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "<" not in data  # document text cannot break out of the data block
    assert cli.main(["dashboard", "--output", str(out)]) == 0
