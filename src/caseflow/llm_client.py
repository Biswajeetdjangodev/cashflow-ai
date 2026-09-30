"""Provider interface, error taxonomy, concurrency limiter, and the two providers.

The workflow only sees `LLMProvider.generate(request) -> dict`. SDK response objects
never leave this module.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class LLMRequest:
    task_name: str  # extraction | customer_email | case_summary
    system_prompt: str
    user_prompt: str
    schema: type[BaseModel]
    source_name: str  # used by the mock provider to pick a fixture
    correction: bool = False


class ProviderError(Exception):
    """A provider call failed.

    retryable: transient (timeout, rate limit, 5xx) - retried with backoff.
    fatal: the whole run cannot succeed (bad credentials, unknown model) - batch aborts.
    Otherwise the error is final for this task only.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False, fatal: bool = False,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.fatal = fatal
        self.retry_after = retry_after
        self.attempts = 1  # provider calls consumed before this error surfaced


class ProviderOutputError(ProviderError):
    """The model answered but the output was not valid for the schema. Eligible for
    the single correction attempt, not for transport retries."""


class LLMProvider(Protocol):
    name: str
    model: str
    is_mock: bool

    async def generate(self, request: LLMRequest) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


@dataclass
class LLMLimiter:
    """Global cap on concurrent provider requests (LLM_CONCURRENCY), shared by all
    documents and both downstream branches. Also records peak concurrency."""

    limit: int
    _sem: asyncio.Semaphore = field(init=False)
    in_flight: int = 0
    peak: int = 0
    total_calls: int = 0

    def __post_init__(self) -> None:
        self._sem = asyncio.Semaphore(self.limit)

    async def __aenter__(self) -> "LLMLimiter":
        await self._sem.acquire()
        self.in_flight += 1
        self.total_calls += 1
        self.peak = max(self.peak, self.in_flight)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.in_flight -= 1
        self._sem.release()


_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-*]{4,}|Bearer\s+\S+)")
_EMAIL_RE = re.compile(r"[^@\s'\"<>]+@[^@\s'\"<>]+\.[A-Za-z]{2,}")
# Phone-like: digit groups joined by separators, 7+ digits in total (so run IDs,
# durations and hashes are left alone).
_PHONE_RE = re.compile(r"(?<![\w-])\+?\(?\d{1,4}\)?(?:[\s.-]\(?\d{1,5}\)?){1,4}(?![\w-])")


def sanitize(message: str, limit: int = 300) -> str:
    """Strip credentials and personal contact details from error text before logging/saving."""
    message = _SECRET_RE.sub("[redacted-key]", str(message))
    message = _EMAIL_RE.sub("[redacted-email]", message)
    message = _PHONE_RE.sub(
        lambda m: "[redacted-number]" if sum(c.isdigit() for c in m.group()) >= 7 else m.group(), message)
    message = " ".join(message.split())
    return message[:limit] + ("..." if len(message) > limit else "")


def validation_problems(exc: ValidationError) -> list[str]:
    """Readable validation errors without echoing input values (which may be personal data)."""
    out = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
        out.append(f"{loc}: {err.get('msg', 'invalid')}")
    return out


class OpenAIProvider:
    """OpenAI Responses API with Structured Outputs (strict JSON schema from the
    Pydantic model). SDK auto-retries are disabled (max_retries=0) so that the only
    retry loop is ours and total attempts stay bounded."""

    name = "openai"
    is_mock = False

    def __init__(self, api_key: str, model: str, timeout: float, http_client: Any = None) -> None:
        from openai import AsyncOpenAI

        self.model = model
        # http_client is only injected by tests (mock transport); None = SDK default.
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=0, http_client=http_client)

    async def generate(self, request: LLMRequest) -> dict[str, Any]:
        import openai

        try:
            response = await self._client.responses.parse(
                model=self.model,
                instructions=request.system_prompt,
                input=request.user_prompt,
                text_format=request.schema,
                store=False,
            )
        except ValidationError as exc:
            raise ProviderOutputError("invalid_structured_output", "; ".join(validation_problems(exc))) from exc
        except json.JSONDecodeError as exc:
            raise ProviderOutputError("malformed_json", "model returned malformed JSON") from exc
        except openai.AuthenticationError as exc:
            raise ProviderError("authentication_failed", "OpenAI rejected the API key (401)", fatal=True) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderError("permission_denied", "API key lacks access to this model/project (403)", fatal=True) from exc
        except openai.NotFoundError as exc:
            raise ProviderError("model_not_found", f"model {self.model!r} was not found (404); check OPENAI_MODEL", fatal=True) from exc
        except openai.RateLimitError as exc:
            if getattr(exc, "code", None) == "insufficient_quota":
                raise ProviderError("insufficient_quota", "OpenAI account has no remaining quota", fatal=True) from exc
            raise ProviderError("rate_limited", "rate limited (429)", retryable=True,
                                retry_after=_retry_after(exc.response)) from exc
        except openai.APITimeoutError as exc:
            raise ProviderError("timeout", "request timed out", retryable=True) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("connection_error", "could not reach the OpenAI API", retryable=True) from exc
        except openai.APIStatusError as exc:
            status = exc.status_code
            if status >= 500 or status in (408, 409):
                raise ProviderError("server_error", f"transient API error ({status})", retryable=True,
                                    retry_after=_retry_after(exc.response)) from exc
            raise ProviderError("bad_request", sanitize(f"API rejected the request ({status}): {exc.message}")) from exc

        if getattr(response, "status", None) == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None) or "unknown"
            raise ProviderOutputError("incomplete_output", f"model output was incomplete ({reason})")
        parsed = response.output_parsed
        if parsed is None:
            raise ProviderOutputError("model_refusal", "model returned no structured output (refusal or empty)")
        return parsed.model_dump(mode="json")

    async def aclose(self) -> None:
        await self._client.close()


def _retry_after(response: Any) -> float | None:
    try:
        headers = response.headers
        if (ms := headers.get("retry-after-ms")) is not None:
            return float(ms) / 1000
        if (sec := headers.get("retry-after")) is not None:
            return float(sec)
    except (AttributeError, TypeError, ValueError):
        return None
    return None


class MockProvider:
    """Deterministic offline provider. Returns canned responses for the bundled demo
    documents only, and fails clearly for anything else. Responses still go through
    the same schema validation, evidence checks and writers as real output."""

    name = "mock"
    model = "mock-fixtures"
    is_mock = True

    def __init__(self, company_name: str, latency_seconds: float = 0.15) -> None:
        from .mock_fixtures import MOCK_RESPONSES

        self._fixtures = MOCK_RESPONSES
        self._company_name = company_name
        self._latency = latency_seconds

    async def generate(self, request: LLMRequest) -> dict[str, Any]:
        await asyncio.sleep(self._latency)  # makes concurrency visible in the demo timings
        fixture = self._fixtures.get(request.source_name, {}).get(request.task_name)
        if fixture is None:
            raise ProviderError(
                "mock_fixture_missing",
                f"mock mode has no fixture for '{request.source_name}' ({request.task_name}). "
                "Mock mode only understands the bundled demo documents; use --provider openai for other files.",
            )
        escaped = json.dumps(self._company_name)[1:-1]
        return json.loads(json.dumps(fixture).replace("{company_name}", escaped))

    async def aclose(self) -> None:
        return None


def build_provider(settings: Any) -> LLMProvider:
    if settings.provider == "mock":
        return MockProvider(company_name=settings.company_name)
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout=settings.request_timeout_seconds,
    )
