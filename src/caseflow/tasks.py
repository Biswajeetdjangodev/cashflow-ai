"""The three AI tasks and the shared retry/validation runner.

Retry budget per task call (all bounded):
  transport retries: up to MAX_RETRIES extra attempts for timeouts, rate limits and 5xx,
                     with exponential backoff + jitter, honouring Retry-After;
  correction retry:  at most ONE extra attempt when the answer fails schema/evidence
                     validation, with the validation problems fed back to the model.
Worst case provider calls per task = 2 * (MAX_RETRIES + 1). The global LLM semaphore is
held only while a request is in flight, never while sleeping between retries.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from . import prompts
from .llm_client import LLMLimiter, LLMProvider, LLMRequest, ProviderError, ProviderOutputError, sanitize, validation_problems
from .schemas import (
    CaseExtraction,
    CaseSummary,
    CustomerEmail,
    check_evidence,
    check_grounded_facts,
    check_summary_consistency,
)

log = logging.getLogger("caseflow.tasks")

T = TypeVar("T", bound=BaseModel)
Sleeper = Callable[[float], Awaitable[None]]

BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
RETRY_AFTER_CAP_SECONDS = 60.0


class TaskFailed(Exception):
    def __init__(self, code: str, message: str, attempts: int, fatal: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = attempts
        self.fatal = fatal


@dataclass
class TaskContext:
    provider: LLMProvider
    limiter: LLMLimiter
    max_retries: int
    request_timeout: float
    company_name: str
    sleep: Sleeper = asyncio.sleep
    rng: random.Random = field(default_factory=random.Random)


@dataclass
class TaskOutput(Generic[T]):
    value: T
    attempts: int
    corrected: bool


def backoff_delay(retry_index: int, retry_after: float | None, rng: random.Random) -> float:
    if retry_after is not None and retry_after >= 0:
        return min(retry_after, RETRY_AFTER_CAP_SECONDS) + rng.uniform(0, 0.25)
    base = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** retry_index))
    return base / 2 + rng.uniform(0, base / 2)  # "equal jitter"


async def _call_with_retries(ctx: TaskContext, request: LLMRequest, doc_label: str) -> tuple[dict[str, Any], int]:
    attempts = 0
    while True:
        attempts += 1
        try:
            async with ctx.limiter:
                result = await asyncio.wait_for(ctx.provider.generate(request), timeout=ctx.request_timeout + 5)
            return result, attempts
        except asyncio.TimeoutError:
            err = ProviderError("timeout", "request timed out", retryable=True)
        except ProviderError as exc:
            err = exc
        if not err.retryable:
            err.attempts = attempts
            raise err
        if attempts > ctx.max_retries:
            raise TaskFailed("retries_exhausted", f"{err.code}: gave up after {attempts} attempts", attempts)
        delay = backoff_delay(attempts - 1, err.retry_after, ctx.rng)
        log.warning("doc=%s task=%s transient error=%s attempt=%d retry_in=%.1fs",
                    doc_label, request.task_name, err.code, attempts, delay)
        await ctx.sleep(delay)  # semaphore is NOT held here


async def run_structured_task(
    ctx: TaskContext,
    *,
    task_name: str,
    schema: type[T],
    system_prompt: str,
    user_prompt: str,
    source_name: str,
    doc_label: str,
    grounding_check: Callable[[T], list[str]],
) -> TaskOutput[T]:
    total_attempts = 0
    problems: list[str] = []
    for correction in (False, True):
        prompt = user_prompt + (prompts.correction_suffix(problems) if correction else "")
        request = LLMRequest(task_name, system_prompt, prompt, schema, source_name, correction)
        try:
            raw, used = await _call_with_retries(ctx, request, doc_label)
            total_attempts += used
        except TaskFailed as exc:
            exc.attempts += total_attempts
            raise
        except ProviderOutputError as exc:
            total_attempts += exc.attempts
            problems = [exc.message]
            log.warning("doc=%s task=%s invalid output code=%s correction=%s", doc_label, task_name, exc.code, correction)
            continue
        except ProviderError as exc:
            total_attempts += exc.attempts
            raise TaskFailed(exc.code, sanitize(exc.message), total_attempts, fatal=exc.fatal) from exc

        try:
            value = schema.model_validate(raw)
        except ValidationError as exc:
            problems = validation_problems(exc)
        else:
            problems = grounding_check(value)
            if not problems:
                return TaskOutput(value=value, attempts=total_attempts, corrected=correction)
        log.warning("doc=%s task=%s validation failed problems=%d correction=%s",
                    doc_label, task_name, len(problems), correction)

    raise TaskFailed(
        "validation_failed",
        sanitize("output failed validation after one correction attempt: " + "; ".join(problems[:3])),
        total_attempts,
    )


# ----------------------------- Task A / B / C ----------------------------- #

async def extract_case(ctx: TaskContext, source_name: str, source_text: str, doc_label: str) -> TaskOutput[CaseExtraction]:
    system, user = prompts.extraction_prompts(source_name, source_text)
    return await run_structured_task(
        ctx, task_name="extraction", schema=CaseExtraction, system_prompt=system, user_prompt=user,
        source_name=source_name, doc_label=doc_label,
        grounding_check=lambda e: check_evidence(e, source_text),
    )


async def draft_customer_email(ctx: TaskContext, extraction: CaseExtraction, source_name: str,
                               source_text: str, doc_label: str) -> TaskOutput[CustomerEmail]:
    system, user = prompts.email_prompts(extraction, source_text, ctx.company_name)
    return await run_structured_task(
        ctx, task_name="customer_email", schema=CustomerEmail, system_prompt=system, user_prompt=user,
        source_name=source_name, doc_label=doc_label,
        grounding_check=lambda m: check_grounded_facts(
            [m.subject, m.greeting, m.body, m.closing], source_text, allowed=[ctx.company_name]),
    )


async def summarize_case(ctx: TaskContext, extraction: CaseExtraction, source_name: str,
                         source_text: str, doc_label: str) -> TaskOutput[CaseSummary]:
    system, user = prompts.summary_prompts(extraction, source_text)

    def check(s: CaseSummary) -> list[str]:
        fields = [s.case_overview, s.key_issue, s.action_taken, s.current_status, s.recommended_next_action]
        return check_summary_consistency(s, extraction) + check_grounded_facts(fields, source_text)

    return await run_structured_task(
        ctx, task_name="case_summary", schema=CaseSummary, system_prompt=system, user_prompt=user,
        source_name=source_name, doc_label=doc_label, grounding_check=check,
    )


def email_decision(extraction: CaseExtraction) -> str | None:
    """None = draft an email; otherwise the documented skip reason."""
    if extraction.complaint is True:
        return None
    if extraction.complaint is False:
        return "not_a_complaint"
    return "complaint_unconfirmed"


def monotonic() -> float:
    return time.perf_counter()
