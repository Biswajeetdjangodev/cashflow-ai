"""OPT-IN paid smoke test against the real OpenAI API.

Skipped unless BOTH are set:
    OPENAI_API_KEY=...            (a real key)
    CASEFLOW_RUN_PAID_SMOKE=1     (explicit authorisation to spend money on API calls)

Run:  CASEFLOW_RUN_PAID_SMOKE=1 pytest -m real_provider -s
It processes one demo document (3 API calls: extraction, email, summary).
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from caseflow.config import load_settings
from caseflow.llm_client import OpenAIProvider
from caseflow.workflow import run_batch

pytestmark = pytest.mark.real_provider


@pytest.mark.skipif(
    not (os.getenv("OPENAI_API_KEY") and os.getenv("CASEFLOW_RUN_PAID_SMOKE") == "1"),
    reason="paid real-provider smoke test: set OPENAI_API_KEY and CASEFLOW_RUN_PAID_SMOKE=1",
)
def test_real_openai_single_document(tmp_path, demo_dir):
    src = tmp_path / "in"
    src.mkdir()
    shutil.copy(demo_dir / "01_billing_refund_resolved.txt", src)
    settings = load_settings({"provider": "openai", "input_dir": src, "output_dir": tmp_path / "out"})
    provider = OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.request_timeout_seconds)

    async def go():
        try:
            return await run_batch(settings, provider)
        finally:
            await provider.aclose()

    result = asyncio.run(go())
    doc = result.documents[0]
    print({name: (t.status, t.attempts, t.error_code) for name, t in doc.tasks.items()})
    assert doc.tasks["extraction"].status == "succeeded"
    assert doc.extraction is not None and doc.extraction.complaint is True
    assert doc.processing_status in ("success", "partial_success")
