"""Shared provider error envelope (429/5xx typed, retry-after surfaced).

Contract: 429 -> RateLimitedError (retry_after or None); 5xx + transport
errors -> RetryableProviderError (safe to retry with backoff); other 4xx
> ProviderError (do not retry blindly). Messages carry a body snippet.
"""

from __future__ import annotations


PROVIDER_FAILURE_REASONS = frozenset({
    "rate_limited",
    "provider_unavailable",
    "request_rejected",
    "transport_error",
    "completion_incomplete",
    "invalid_response",
})


class ProviderError(Exception):
    """Non-retryable provider failure (bad request, bad payload)."""

    def __init__(
        self, *args, reason: str | None = None, status_code: int | None = None
    ) -> None:
        # Positional exception arguments/messages retain their existing behavior.
        # Only these closed fields may be surfaced outside private diagnostics.
        super().__init__(*args)
        self.reason = (
            reason
            if type(reason) is str and reason in PROVIDER_FAILURE_REASONS
            else None
        )
        self.status_code = (
            status_code
            if type(status_code) is int and 100 <= status_code <= 599
            else None
        )


class RetryableProviderError(ProviderError):
    """Transient failure (5xx, timeout, connection error). Retry w/ backoff."""


class RateLimitedError(RetryableProviderError):
    """HTTP 429. retry_after carries the Retry-After seconds (or None)."""

    def __init__(
        self, message: str = "rate limited", retry_after: float | None = None
    ) -> None:
        super().__init__(message, reason="rate_limited", status_code=429)
        self.retry_after = retry_after


def _snippet(response) -> str:
    try:
        return f" body={response.text[:200]!r}"
    except Exception:
        return ""


def raise_for_provider(response, context: str) -> None:
    """Raise typed errors for non-2xx httpx responses."""
    if response.status_code < 400:
        return
    if response.status_code == 429:
        raw = response.headers.get("retry-after")
        try:
            retry_after = float(raw) if raw is not None else None
        except ValueError:
            retry_after = None
        raise RateLimitedError(f"{context}: 429", retry_after)
    if response.status_code >= 500:
        raise RetryableProviderError(
            f"{context}: HTTP {response.status_code}{_snippet(response)}",
            reason="provider_unavailable",
            status_code=response.status_code,
        )
    raise ProviderError(
        f"{context}: HTTP {response.status_code}{_snippet(response)}",
        reason="request_rejected",
        status_code=response.status_code,
    )
