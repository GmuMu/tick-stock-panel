"""Shared provider health, retry and fallback governance.

This module deliberately stores only operational metadata. Provider objects,
API keys and raw responses never enter the registry, so the status API can be
exposed to the settings UI without leaking provider implementation details.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any

_RETRYABLE_ERROR_NAMES = {
    "ConnectError",
    "ConnectTimeout",
    "NetworkError",
    "ReadError",
    "ReadTimeout",
    "RemoteProtocolError",
    "Timeout",
    "TimeoutError",
    "WriteError",
    "WriteTimeout",
}
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|authorization|secret|password)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sanitize_error(error: BaseException | str | None, *, limit: int = 240) -> str | None:
    """Return a bounded error string with common credential fields redacted."""
    if error is None:
        return None
    text = str(error).strip()
    if not text:
        return None
    text = _SECRET_RE.sub(r"\1\2[REDACTED]", text)
    return text[:limit]


def is_retryable_error(error: BaseException) -> bool:
    """Classify transient transport/rate-limit failures.

    Authentication and contract failures intentionally do not retry. HTTP
    clients expose status codes inconsistently, so both ``status_code`` and
    conventional transport exception names are supported.
    """
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    if status_code is not None:
        try:
            return int(status_code) == 429 or int(status_code) >= 500
        except (TypeError, ValueError):
            pass
    text = str(error).lower()
    if any(marker in text for marker in ("code=2001", "code=2003", "unauthorized", "forbidden")):
        return False
    return (
        error.__class__.__name__ in _RETRYABLE_ERROR_NAMES
        or isinstance(error, (TimeoutError, ConnectionError))
        or any(
            marker in text
            for marker in (
                "timeout",
                "timed out",
                "connection refused",
                "connection reset",
                "network request failed",
                "temporarily unavailable",
                "too many requests",
            )
        )
    )


@dataclass(frozen=True)
class RetryPolicy:
    """Deterministic exponential-backoff policy.

    ``max_attempts`` includes the first call. A zero delay is useful in
    offline tests and for providers whose own client already rate-limits.
    """

    max_attempts: int = 2
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays must be >= 0")

    def delay_for_retry(self, retry_number: int) -> float:
        """Return the delay before retry number 1, 2, ..."""
        if retry_number < 1:
            raise ValueError("retry_number must be >= 1")
        return min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (retry_number - 1)),
        )


@dataclass
class _ProviderHealth:
    provider: str
    dataset: str
    calls: int = 0
    successes: int = 0
    failures: int = 0
    retries: int = 0
    last_retry_delay_seconds: float | None = None
    fallbacks: int = 0
    consecutive_failures: int = 0
    last_error: str | None = None
    last_failure_at: str | None = None
    last_success_at: str | None = None
    last_fallback_at: str | None = None
    total_latency_ms: float = 0.0
    last_latency_ms: float | None = None
    updated_at: str | None = None

    def health(self) -> str:
        if self.consecutive_failures >= 3:
            return "unavailable"
        if self.consecutive_failures:
            return "degraded"
        return "healthy"

    def to_dict(self) -> dict[str, Any]:
        error_rate = self.failures / self.calls if self.calls else 0.0
        return {
            "provider": self.provider,
            "dataset": self.dataset,
            "health": self.health(),
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "error_rate": round(error_rate, 4),
            "retries": self.retries,
            "last_retry_delay_seconds": self.last_retry_delay_seconds,
            "fallbacks": self.fallbacks,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "last_failure_at": self.last_failure_at,
            "last_success_at": self.last_success_at,
            "last_fallback_at": self.last_fallback_at,
            "last_latency_ms": (
                round(self.last_latency_ms, 2)
                if self.last_latency_ms is not None
                else None
            ),
            "average_latency_ms": (
                round(self.total_latency_ms / self.successes, 2)
                if self.successes
                else None
            ),
            "updated_at": self.updated_at,
        }


class ProviderHealthRegistry:
    """Thread-safe operational registry keyed by ``provider + dataset``."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[tuple[str, str], _ProviderHealth] = {}

    @staticmethod
    def _key(provider: str, dataset: str) -> tuple[str, str]:
        return (
            str(provider or "unknown").strip().lower() or "unknown",
            str(dataset or "unknown").strip().lower() or "unknown",
        )

    def _record(self, provider: str, dataset: str) -> _ProviderHealth:
        key = self._key(provider, dataset)
        record = self._records.get(key)
        if record is None:
            record = _ProviderHealth(provider=key[0], dataset=key[1])
            self._records[key] = record
        return record

    def record_success(
        self,
        provider: str,
        dataset: str,
        *,
        latency_ms: float | None = None,
    ) -> None:
        with self._lock:
            record = self._record(provider, dataset)
            record.calls += 1
            record.successes += 1
            record.consecutive_failures = 0
            record.last_error = None
            record.last_success_at = _utc_now()
            record.updated_at = record.last_success_at
            if latency_ms is not None:
                record.last_latency_ms = max(0.0, float(latency_ms))
                record.total_latency_ms += record.last_latency_ms

    def record_failure(
        self,
        provider: str,
        dataset: str,
        error: BaseException | str | None,
        *,
        latency_ms: float | None = None,
    ) -> None:
        with self._lock:
            record = self._record(provider, dataset)
            record.calls += 1
            record.failures += 1
            record.consecutive_failures += 1
            record.last_error = sanitize_error(error)
            record.last_failure_at = _utc_now()
            record.updated_at = record.last_failure_at
            if latency_ms is not None:
                record.last_latency_ms = max(0.0, float(latency_ms))

    def record_retry(
        self,
        provider: str,
        dataset: str,
        *,
        delay_seconds: float | None = None,
    ) -> None:
        with self._lock:
            record = self._record(provider, dataset)
            record.retries += 1
            if delay_seconds is not None:
                record.last_retry_delay_seconds = max(0.0, float(delay_seconds))
            record.updated_at = _utc_now()

    def record_fallback(
        self,
        provider: str,
        dataset: str,
        *,
        reason: str | None = None,
        error: BaseException | str | None = None,
    ) -> None:
        """Record a route fallback without counting it as another call."""
        with self._lock:
            record = self._record(provider, dataset)
            record.fallbacks += 1
            record.consecutive_failures = max(record.consecutive_failures, 1)
            record.last_error = sanitize_error(error) or sanitize_error(reason)
            record.last_fallback_at = _utc_now()
            record.updated_at = record.last_fallback_at

    def snapshot(
        self,
        *,
        provider: str | None = None,
        dataset: str | None = None,
    ) -> list[dict[str, Any]]:
        provider_filter = str(provider or "").strip().lower()
        dataset_filter = str(dataset or "").strip().lower()
        with self._lock:
            rows = [
                record.to_dict()
                for record in self._records.values()
                if (not provider_filter or record.provider == provider_filter)
                and (not dataset_filter or record.dataset == dataset_filter)
            ]
        return sorted(rows, key=lambda row: (row["provider"], row["dataset"]))

    def health_for(self, provider: str, dataset: str) -> str | None:
        with self._lock:
            record = self._records.get(self._key(provider, dataset))
            return record.health() if record else None

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


_REGISTRY = ProviderHealthRegistry()


def get_provider_health_registry() -> ProviderHealthRegistry:
    """Return the process-wide registry shared by all provider boundaries."""
    return _REGISTRY


def call_with_retry(
    provider: str,
    dataset: str,
    operation: Callable[[], Any],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    health: ProviderHealthRegistry | None = None,
) -> Any:
    """Execute one provider operation and record success/failure/retries."""
    policy = policy or RetryPolicy()
    health = health or get_provider_health_registry()
    started = time.perf_counter()
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = operation()
        except Exception as error:  # provider boundary
            retryable = is_retryable_error(error)
            if retryable and attempt < policy.max_attempts:
                delay = policy.delay_for_retry(attempt)
                health.record_retry(
                    provider,
                    dataset,
                    delay_seconds=delay,
                )
                sleep(delay)
                continue
            health.record_failure(
                provider,
                dataset,
                error,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            raise
        health.record_success(
            provider,
            dataset,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return result
    raise RuntimeError("provider retry loop exited unexpectedly")


def record_route_fallback(route: Any) -> None:
    """Record a ProviderRoute fallback without importing the route type."""
    if not getattr(route, "fallback", False):
        return
    get_provider_health_registry().record_fallback(
        getattr(route, "requested_provider", "unknown"),
        getattr(route, "dataset", "unknown"),
        reason=getattr(route, "fallback_reason", None),
        error=getattr(route, "error", None),
    )
