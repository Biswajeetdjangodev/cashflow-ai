"""Pydantic models for the three AI tasks, plus source-grounding checks.

Schema validation (types, enums, forbidden extra keys, internal consistency) lives
in the models. Checks that need the source document text (evidence quotes, invented
amounts/references) are plain functions that return a list of problems, so the task
runner can feed them back to the model as one correction attempt.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

ComplaintCategory = Literal[
    "billing", "delivery", "product_quality", "service_quality", "refund", "technical", "other", "unknown"
]
CaseStatus = Literal["open", "in_progress", "resolved", "closed", "escalated", "not_a_complaint", "unknown"]

MAX_QUOTE_CHARS = 300
MIN_QUOTE_CHARS = 3
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceItem(StrictModel):
    field_name: str
    source_quote: str

    @field_validator("source_quote")
    @classmethod
    def _quote_length(cls, v: str) -> str:
        if not MIN_QUOTE_CHARS <= len(v) <= MAX_QUOTE_CHARS:
            raise ValueError(f"source_quote must be {MIN_QUOTE_CHARS}-{MAX_QUOTE_CHARS} characters")
        return v


# Fields whose populated (non-null / non-"unknown") values must cite a source quote.
EVIDENCE_REQUIRED_FIELDS: tuple[str, ...] = (
    "customer_name",
    "email",
    "phone_number",
    "product_or_service",
    "complaint_category",
    "issue_description",
    "resolution_provided",
    "complaint",
    "escalation_required",
    "supporting_document_available",
    "overall_case_status",
)


class CaseExtraction(StrictModel):
    """Task A output. Unknown facts stay null / 'unknown' - never guessed."""

    customer_name: str | None
    email: str | None
    phone_number: str | None
    product_or_service: str | None
    complaint_category: ComplaintCategory
    issue_description: str | None
    resolution_provided: str | None
    complaint: bool | None
    escalation_required: bool | None
    supporting_document_available: bool | None
    overall_case_status: CaseStatus
    missing_information: list[str]
    ambiguities: list[str]
    evidence: list[EvidenceItem]

    @field_validator(
        "customer_name", "email", "phone_number", "product_or_service",
        "issue_description", "resolution_provided",
    )
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        # An empty string is not information; store it as unknown.
        return v if v else None

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str | None) -> str | None:
        if v is not None and not _EMAIL_RE.match(v):
            raise ValueError("email must be a single email address or null")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "CaseExtraction":
        known = set(type(self).model_fields) - {"evidence"}
        for item in self.evidence:
            if item.field_name not in known:
                raise ValueError(f"evidence field_name {item.field_name!r} is not a CaseExtraction field")
        cited = {item.field_name for item in self.evidence}
        missing = [f for f in populated_fields(self) if f not in cited]
        if missing:
            raise ValueError(f"evidence quotes are required for populated fields: {', '.join(missing)}")
        if self.overall_case_status == "not_a_complaint" and self.complaint is not False:
            raise ValueError("overall_case_status 'not_a_complaint' requires complaint=false")
        if self.complaint is False and self.escalation_required is True:
            raise ValueError("a non-complaint cannot require complaint escalation; use null if unclear")
        return self


def populated_fields(extraction: CaseExtraction) -> list[str]:
    out = []
    for name in EVIDENCE_REQUIRED_FIELDS:
        value = getattr(extraction, name)
        if value is None or value == "unknown":
            continue
        out.append(name)
    return out


class CustomerEmail(StrictModel):
    """Task B output: a draft only - never sent."""

    subject: str
    greeting: str
    body: str
    closing: str

    @field_validator("subject", "greeting", "body", "closing")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty")
        return v

    @field_validator("subject")
    @classmethod
    def _single_line_subject(cls, v: str) -> str:
        if "\n" in v or len(v) > 150:
            raise ValueError("subject must be a single line of at most 150 characters")
        return v


class CaseSummary(StrictModel):
    """Task C output: internal management summary."""

    case_overview: str
    key_issue: str
    action_taken: str
    current_status: str
    recommended_next_action: str
    review_required: bool
    review_reasons: list[str]

    @field_validator("case_overview", "key_issue", "action_taken", "current_status", "recommended_next_action")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty (use 'Not documented' when unknown)")
        return v

    @model_validator(mode="after")
    def _reasons_when_flagged(self) -> "CaseSummary":
        if self.review_required and not self.review_reasons:
            raise ValueError("review_reasons must explain why review_required is true")
        return self


# --------------------------------------------------------------------------- #
# Source-grounding checks (need the document text, so they are not validators) #
# --------------------------------------------------------------------------- #

_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
})


def normalize_for_match(text: str) -> str:
    """Controlled normalisation: Unicode NFKC, typographic quotes/dashes to ASCII,
    whitespace runs collapsed to one space, case-folded. Nothing else is changed,
    so a quote still has to be a verbatim span of the source."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_MAP)
    return re.sub(r"\s+", " ", text).strip().casefold()


def check_evidence(extraction: CaseExtraction, source_text: str) -> list[str]:
    """Every evidence quote must occur in the source text.

    This proves the quote exists in the document - not that the model interpreted
    it correctly (semantic truth is outside what string matching can verify).
    """
    haystack = normalize_for_match(source_text)
    problems = []
    for item in extraction.evidence:
        if normalize_for_match(item.source_quote) not in haystack:
            problems.append(
                f"evidence for '{item.field_name}' is not a verbatim quote from the document: "
                f"{item.source_quote[:80]!r}"
            )
    for name in ("email", "phone_number"):
        value = getattr(extraction, name)
        if value is not None and normalize_for_match(value) not in haystack:
            problems.append(f"{name} value does not appear verbatim in the document")
    return problems


# Specific facts a generated email/summary must not invent: money amounts,
# ticket/order/invoice references, email addresses, URLs, and phone numbers.
_GROUNDED_PATTERNS = (
    re.compile(r"[$£€₹]\s?\d[\d,]*(?:\.\d+)?"),
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|INR|dollars|euros|pounds|rupees)\b", re.I),
    re.compile(r"\b[A-Z]{2,}-?\d{3,}\b"),
    re.compile(r"#\s?\d{3,}"),
    re.compile(r"[^@\s<>()]+@[^@\s<>()]+\.[A-Za-z]{2,}"),
    re.compile(r"https?://\S+|www\.\S+", re.I),
    re.compile(r"\+?\(?\d[\d\s().-]{7,}\d"),
)


def check_grounded_facts(texts: list[str], source_text: str, allowed: list[str] | None = None) -> list[str]:
    """Heuristic guard: flag amounts, references, contact details or links in the
    generated text that do not appear in the source document."""
    haystack = normalize_for_match(source_text)
    allowed_norm = [normalize_for_match(a) for a in (allowed or [])]
    problems: list[str] = []
    for text in texts:
        for pattern in _GROUNDED_PATTERNS:
            for match in pattern.findall(text):
                token = normalize_for_match(match.rstrip(".,;:)"))
                if token and token not in haystack and not any(token in a for a in allowed_norm):
                    problems.append(
                        f"mentions {match.strip()!r}, which does not appear in the source document; "
                        "do not invent amounts, references, contact details or links"
                    )
    return sorted(set(problems))


def check_summary_consistency(summary: CaseSummary, extraction: CaseExtraction) -> list[str]:
    problems = []
    if extraction.complaint is None and not summary.review_required:
        problems.append("review_required must be true because complaint status is unconfirmed")
    if extraction.ambiguities and not summary.review_required:
        problems.append("review_required must be true because the extraction recorded ambiguities")
    return problems


def bool_to_report(value: bool | None) -> str:
    """CSV mapping. Missing information is 'Unknown', never 'No'."""
    if value is None:
        return "Unknown"
    return "Yes" if value else "No"
