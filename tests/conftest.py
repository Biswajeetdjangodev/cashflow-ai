"""Shared test helpers: a scriptable fake provider, settings factory, sample generator."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from caseflow.config import Settings
from caseflow.llm_client import LLMRequest

ROOT = Path(__file__).resolve().parents[1]


def _load_generator():
    spec = importlib.util.spec_from_file_location("sample_gen", ROOT / "scripts" / "generate_sample_documents.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sample_gen"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def gen():
    return _load_generator()


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory, gen) -> Path:
    d = tmp_path_factory.mktemp("demo_data")
    gen.generate_demo(d)
    return d


def make_settings(tmp_path: Path, input_dir: Path, **kw: Any) -> Settings:
    base = dict(provider="mock", input_dir=input_dir, output_dir=tmp_path / "out", log_dir=tmp_path / "logs",
                batch_concurrency=4, llm_concurrency=2, max_retries=2, request_timeout_seconds=5)
    base.update(kw)
    return Settings(**base)


Handler = Callable[[LLMRequest], Any]


class FakeProvider:
    """Controllable provider. `handler(request)` returns a dict, or raises. Records every
    call with start/end timestamps and tracks true in-flight concurrency."""

    name = "fake"
    model = "fake-model"
    is_mock = True

    def __init__(self, handler: Handler, delay: float = 0.02) -> None:
        self.handler = handler
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.in_flight = 0
        self.peak = 0

    async def generate(self, request: LLMRequest) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        entry = {"task": request.task_name, "source": request.source_name, "start": loop.time(),
                 "correction": request.correction, "prompt": request.user_prompt}
        self.calls.append(entry)
        try:
            await asyncio.sleep(self.delay)
            result = self.handler(request)
            return result
        finally:
            entry["end"] = loop.time()
            self.in_flight -= 1

    async def aclose(self) -> None:
        return None


def extraction_payload(**overrides: Any) -> dict[str, Any]:
    """A valid extraction for the text in `SIMPLE_COMPLAINT`."""
    data = {
        "customer_name": "Jo Bloggs",
        "email": "jo@example.com",
        "phone_number": None,
        "product_or_service": "Blue Kettle",
        "complaint_category": "product_quality",
        "issue_description": "The Blue Kettle leaks.",
        "resolution_provided": None,
        "complaint": True,
        "escalation_required": None,
        "supporting_document_available": None,
        "overall_case_status": "open",
        "missing_information": [],
        "ambiguities": [],
        "evidence": [
            {"field_name": "customer_name", "source_quote": "Name: Jo Bloggs"},
            {"field_name": "email", "source_quote": "jo@example.com"},
            {"field_name": "product_or_service", "source_quote": "Blue Kettle"},
            {"field_name": "complaint_category", "source_quote": "My Blue Kettle leaks"},
            {"field_name": "issue_description", "source_quote": "My Blue Kettle leaks"},
            {"field_name": "complaint", "source_quote": "I want this fixed."},
            {"field_name": "overall_case_status", "source_quote": "Status: open"},
        ],
    }
    data.update(overrides)
    return data


SIMPLE_COMPLAINT = "Name: Jo Bloggs\nEmail: jo@example.com\nMy Blue Kettle leaks everywhere. I want this fixed.\nStatus: open\n"

EMAIL_PAYLOAD = {"subject": "Your kettle", "greeting": "Dear Jo Bloggs,",
                 "body": "Thank you for telling us your Blue Kettle leaks.", "closing": "Kind regards,\nSupport"}
SUMMARY_PAYLOAD = {"case_overview": "Kettle leak complaint.", "key_issue": "Kettle leaks.",
                   "action_taken": "Not documented", "current_status": "Open.",
                   "recommended_next_action": "Offer a replacement.", "review_required": False,
                   "review_reasons": []}


def default_handler(request: LLMRequest) -> dict[str, Any]:
    return {"extraction": extraction_payload(), "customer_email": EMAIL_PAYLOAD,
            "case_summary": SUMMARY_PAYLOAD}[request.task_name]


@pytest.fixture
def complaint_dir(tmp_path: Path) -> Path:
    d = tmp_path / "in"
    d.mkdir()
    (d / "a_complaint.txt").write_text(SIMPLE_COMPLAINT, encoding="utf-8")
    return d
