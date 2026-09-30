"""OpenAIProvider against the real openai SDK, with HTTP mocked (no network, no cost).

Verifies the request we send (Responses API, strict JSON schema, no SDK auto-retry) and
how HTTP outcomes map onto our retryable / fatal / output error categories.
"""

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest

from caseflow.llm_client import LLMRequest, OpenAIProvider, ProviderError, ProviderOutputError
from caseflow.schemas import CustomerEmail
from conftest import EMAIL_PAYLOAD


def _response_body(text: str) -> dict:
    return {
        "id": "resp_test", "object": "response", "created_at": 0, "status": "completed",
        "model": "test-model", "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "output": [{"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
    }


def _call(handler):
    seen = []

    def transport(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    async def go():
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(transport))
        provider = OpenAIProvider("sk-test-key", "test-model", timeout=5, http_client=client)
        try:
            return await provider.generate(LLMRequest("customer_email", "SYS", "USER", CustomerEmail, "a.txt"))
        finally:
            await provider.aclose()

    return asyncio.run(go()), seen


def _run_expect_error(handler):
    with pytest.raises(ProviderError) as e:
        _call(handler)
    return e.value


def test_structured_output_request_and_parse():
    result, seen = _call(lambda r: httpx2.Response(200, json=_response_body(json.dumps(EMAIL_PAYLOAD))))
    assert result == EMAIL_PAYLOAD
    assert len(seen) == 1
    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith("/responses")
    assert body["model"] == "test-model" and body["instructions"] == "SYS" and body["input"] == "USER"
    assert body["store"] is False
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == {"subject", "greeting", "body", "closing"}


def test_invalid_json_from_model_is_output_error():
    err = _run_expect_error(lambda r: httpx2.Response(200, json=_response_body('{"subject": 1')))
    assert isinstance(err, ProviderOutputError)


def test_schema_violation_from_model_is_output_error():
    err = _run_expect_error(lambda r: httpx2.Response(200, json=_response_body('{"subject": "x"}')))
    assert isinstance(err, ProviderOutputError) and err.code == "invalid_structured_output"


def test_401_is_fatal_and_not_retried():
    calls = []
    err = _run_expect_error(lambda r: calls.append(1) or httpx2.Response(401, json={"error": {"message": "bad key"}}))
    assert err.fatal and not err.retryable and err.code == "authentication_failed"
    assert len(calls) == 1  # SDK auto-retry disabled


def test_429_retryable_with_retry_after():
    err = _run_expect_error(lambda r: httpx2.Response(
        429, headers={"retry-after": "7"}, json={"error": {"message": "slow down", "code": "rate_limit_exceeded"}}))
    assert err.retryable and err.retry_after == 7.0


def test_insufficient_quota_is_fatal():
    err = _run_expect_error(lambda r: httpx2.Response(
        429, json={"error": {"message": "quota", "code": "insufficient_quota", "type": "insufficient_quota"}}))
    assert err.fatal and not err.retryable


def test_5xx_retryable_and_400_not():
    assert _run_expect_error(lambda r: httpx2.Response(503, json={"error": {"message": "x"}})).retryable
    err = _run_expect_error(lambda r: httpx2.Response(400, json={"error": {"message": "bad param"}}))
    assert not err.retryable and not err.fatal and err.code == "bad_request"


def test_404_model_not_found_is_fatal():
    err = _run_expect_error(lambda r: httpx2.Response(404, json={"error": {"message": "no model"}}))
    assert err.fatal and err.code == "model_not_found"
