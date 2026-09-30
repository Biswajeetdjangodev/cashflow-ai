from __future__ import annotations

import pytest
from pydantic import ValidationError

from caseflow.schemas import (
    CaseExtraction,
    CaseSummary,
    bool_to_report,
    check_evidence,
    check_grounded_facts,
    check_summary_consistency,
)
from conftest import SIMPLE_COMPLAINT, SUMMARY_PAYLOAD, extraction_payload


def test_missing_fields_stay_unknown():
    e = CaseExtraction.model_validate(extraction_payload(
        customer_name=None, email=None, complaint=None, overall_case_status="unknown",
        complaint_category="unknown",
        evidence=[{"field_name": "product_or_service", "source_quote": "Blue Kettle"},
                  {"field_name": "issue_description", "source_quote": "My Blue Kettle leaks"}]))
    assert e.customer_name is None and e.complaint is None
    assert bool_to_report(e.complaint) == "Unknown"
    assert bool_to_report(e.escalation_required) == "Unknown"  # missing is never "No"
    assert bool_to_report(True) == "Yes" and bool_to_report(False) == "No"


def test_extra_keys_forbidden():
    with pytest.raises(ValidationError):
        CaseExtraction.model_validate(extraction_payload(priority="high"))


def test_malformed_types_rejected():
    with pytest.raises(ValidationError):
        CaseExtraction.model_validate(extraction_payload(complaint_category="angry"))
    with pytest.raises(ValidationError):
        CaseExtraction.model_validate(extraction_payload(missing_information="none"))
    with pytest.raises(ValidationError):
        CaseExtraction.model_validate(extraction_payload(email="not an email"))


def test_populated_fields_require_evidence():
    payload = extraction_payload()
    payload["evidence"] = [ev for ev in payload["evidence"] if ev["field_name"] != "customer_name"]
    with pytest.raises(ValidationError, match="customer_name"):
        CaseExtraction.model_validate(payload)


def test_not_a_complaint_requires_complaint_false():
    with pytest.raises(ValidationError):
        CaseExtraction.model_validate(extraction_payload(overall_case_status="not_a_complaint"))


def test_invented_evidence_quote_fails():
    payload = extraction_payload()
    payload["evidence"][0]["source_quote"] = "Name: Joanna Bloggs"
    e = CaseExtraction.model_validate(payload)
    problems = check_evidence(e, SIMPLE_COMPLAINT)
    assert problems and "customer_name" in problems[0]


def test_evidence_matching_normalises_whitespace_case_and_quotes():
    payload = extraction_payload()
    payload["evidence"][3]["source_quote"] = "my   blue\nkettle LEAKS"
    e = CaseExtraction.model_validate(payload)
    assert check_evidence(e, SIMPLE_COMPLAINT) == []
    assert check_evidence(e, SIMPLE_COMPLAINT.replace("Jo Bloggs", "Jo Bloggs")) == []


def test_email_value_must_appear_in_source():
    e = CaseExtraction.model_validate(extraction_payload(email="other@example.com"))
    assert any("email value" in p for p in check_evidence(e, SIMPLE_COMPLAINT))


def test_grounding_flags_invented_amounts_and_references():
    src = "Refund of $20.00 approved for order AB-1234."
    assert check_grounded_facts(["We refunded $20.00 for AB-1234."], src) == []
    problems = check_grounded_facts(["Your refund of $500 and ticket TCK-99812 are complete."], src)
    assert len(problems) == 2
    assert check_grounded_facts(["Contact help@acme.test"], src)
    assert check_grounded_facts(["Visit www.acme.test/help"], src)


def test_summary_must_flag_unconfirmed_complaints():
    e = CaseExtraction.model_validate(extraction_payload(
        complaint=None, overall_case_status="unknown",
        evidence=[ev for ev in extraction_payload()["evidence"] if ev["field_name"] not in ("complaint", "overall_case_status")]))
    s = CaseSummary.model_validate(SUMMARY_PAYLOAD)
    assert check_summary_consistency(s, e)


def test_summary_review_reasons_required_when_flagged():
    with pytest.raises(ValidationError):
        CaseSummary.model_validate({**SUMMARY_PAYLOAD, "review_required": True, "review_reasons": []})
