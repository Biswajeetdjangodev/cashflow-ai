"""Retry, correction and concurrency behaviour of the task runner."""

from __future__ import annotations

import asyncio
import random

import pytest

from caseflow.llm_client import LLMLimiter, ProviderError, ProviderOutputError
from caseflow.tasks import TaskContext, TaskFailed, backoff_delay, extract_case
from conftest import SIMPLE_COMPLAINT, FakeProvider, extraction_payload


def _ctx(provider, *, max_retries=2, limit=2, sleeps=None):
    async def fake_sleep(delay):
        if sleeps is not None:
            sleeps.append((delay, limiter.in_flight))

    limiter = LLMLimiter(limit)
    return TaskContext(provider=provider, limiter=limiter, max_retries=max_retries, request_timeout=5,
                       company_name="Acme", sleep=fake_sleep, rng=random.Random(0))


def _run(coro):
    return asyncio.run(coro)


def test_transient_errors_are_retried_then_succeed():
    outcomes = [ProviderError("rate_limited", "429", retryable=True, retry_after=2.0),
                ProviderError("server_error", "503", retryable=True)]

    def handler(req):
        if outcomes:
            raise outcomes.pop(0)
        return extraction_payload()

    sleeps = []
    provider = FakeProvider(handler, delay=0)
    out = _run(extract_case(_ctx(provider, sleeps=sleeps), "a.txt", SIMPLE_COMPLAINT, "doc"))
    assert out.attempts == 3 and len(provider.calls) == 3
    assert 2.0 <= sleeps[0][0] <= 2.25  # Retry-After honoured
    assert all(in_flight == 0 for _, in_flight in sleeps)  # semaphore released during backoff


def test_retries_are_bounded():
    provider = FakeProvider(lambda r: (_ for _ in ()).throw(ProviderError("timeout", "t", retryable=True)), delay=0)
    with pytest.raises(TaskFailed) as e:
        _run(extract_case(_ctx(provider, max_retries=2), "a.txt", SIMPLE_COMPLAINT, "doc"))
    assert e.value.code == "retries_exhausted"
    assert len(provider.calls) == 3 == e.value.attempts  # 1 + MAX_RETRIES


def test_nonretryable_error_is_not_retried():
    provider = FakeProvider(lambda r: (_ for _ in ()).throw(
        ProviderError("authentication_failed", "bad key sk-abcdefgh1234", fatal=True)), delay=0)
    with pytest.raises(TaskFailed) as e:
        _run(extract_case(_ctx(provider), "a.txt", SIMPLE_COMPLAINT, "doc"))
    assert len(provider.calls) == 1
    assert e.value.fatal and e.value.code == "authentication_failed"
    assert "sk-abcdefgh" not in e.value.message  # sanitised


def test_one_correction_retry_fixes_invented_quote():
    bad = extraction_payload()
    bad["evidence"][0]["source_quote"] = "Name: Somebody Else"
    answers = [bad, extraction_payload()]
    provider = FakeProvider(lambda r: answers.pop(0), delay=0)
    out = _run(extract_case(_ctx(provider), "a.txt", SIMPLE_COMPLAINT, "doc"))
    assert out.corrected and len(provider.calls) == 2
    assert provider.calls[1]["correction"] and "rejected by validation" in provider.calls[1]["prompt"]


def test_malformed_output_never_accepted_after_correction():
    provider = FakeProvider(lambda r: {"customer_name": 42, "unexpected": True}, delay=0)
    with pytest.raises(TaskFailed) as e:
        _run(extract_case(_ctx(provider), "a.txt", SIMPLE_COMPLAINT, "doc"))
    assert e.value.code == "validation_failed" and len(provider.calls) == 2


def test_provider_output_error_uses_correction_slot():
    provider = FakeProvider(lambda r: (_ for _ in ()).throw(ProviderOutputError("malformed_json", "bad json")), delay=0)
    with pytest.raises(TaskFailed) as e:
        _run(extract_case(_ctx(provider), "a.txt", SIMPLE_COMPLAINT, "doc"))
    assert e.value.code == "validation_failed" and len(provider.calls) == 2


def test_hung_request_times_out_and_is_bounded():
    provider = FakeProvider(lambda r: extraction_payload(), delay=10)
    ctx = _ctx(provider, max_retries=1)
    ctx.request_timeout = -4.9  # wait_for(timeout + 5) => 0.1s
    with pytest.raises(TaskFailed) as e:
        _run(extract_case(ctx, "a.txt", SIMPLE_COMPLAINT, "doc"))
    assert e.value.code == "retries_exhausted" and len(provider.calls) == 2


def test_backoff_grows_and_is_capped():
    rng = random.Random(1)
    delays = [backoff_delay(i, None, rng) for i in range(10)]
    assert delays[0] <= 1.0 and delays[3] >= 4.0 and max(delays) <= 30.0
    assert backoff_delay(0, 500, rng) <= 60.25
