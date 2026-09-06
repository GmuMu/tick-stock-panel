"""Small dependency-free observability primitives used by the API boundary."""
from __future__ import annotations

import re
import threading
import time
import uuid
from collections import Counter
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

CORRELATION_HEADER = "X-Correlation-ID"
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")
_VALID_CORRELATION = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_PATH_ID = re.compile(r"/(?:[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9]{2,})(?=/|$)", re.IGNORECASE)
_SECRET_VALUE = re.compile(
    r"(?i)(\b(?:api[_-]?key|token|authorization|secret|password|webhook)\b"
    r"\s*[:=]\s*)([^\s,;}&]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def new_correlation_id(value: str | None = None) -> str:
    """Accept a safe caller-provided ID, otherwise create one."""
    candidate = (value or "").strip()
    if not _VALID_CORRELATION.fullmatch(candidate):
        candidate = uuid.uuid4().hex
    return candidate


def set_correlation_id(value: str) -> Any:
    return _correlation_id.set(value)


def reset_correlation_id(token: Any) -> None:
    _correlation_id.reset(token)


def current_correlation_id() -> str:
    return _correlation_id.get()


def redact_text(value: str) -> str:
    """Remove common secret values while preserving useful error context."""
    redacted = _SECRET_VALUE.sub(r"\1[REDACTED]", str(value))
    return _BEARER.sub("Bearer [REDACTED]", redacted)


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


class RedactionFilter:
    """Logging filter that also injects the request correlation ID."""

    def filter(self, record: Any) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
        except Exception:
            pass
        record.correlation_id = current_correlation_id()
        return True


class RequestMetrics:
    """Bounded in-memory request counters suitable for a self-hosted panel."""

    def __init__(self, *, max_routes: int = 200) -> None:
        self.max_routes = max_routes
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._total = 0
        self._errors = 0
        self._status = Counter()
        self._routes: dict[str, dict[str, float | int]] = {}
        self._recent_errors: list[dict[str, str]] = []

    def observe(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        correlation_id: str,
    ) -> None:
        route = _PATH_ID.sub("/:id", path.split("?", 1)[0])[:160]
        key = f"{method.upper()} {route}"
        with self._lock:
            self._total += 1
            self._status[str(status_code)] += 1
            if status_code >= 500:
                self._errors += 1
                self._recent_errors.append({
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "route": key,
                    "status": str(status_code),
                    "correlation_id": correlation_id,
                })
                del self._recent_errors[:-20]
            item = self._routes.get(key)
            if item is None:
                if len(self._routes) >= self.max_routes:
                    key = "OTHER"
                    item = self._routes.setdefault(key, {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
                else:
                    item = self._routes.setdefault(key, {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
            item["count"] = int(item["count"]) + 1
            item["total_ms"] = float(item["total_ms"]) + duration_ms
            item["max_ms"] = max(float(item["max_ms"]), duration_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            routes = {}
            for key, item in self._routes.items():
                count = int(item["count"])
                routes[key] = {
                    "count": count,
                    "avg_ms": round(float(item["total_ms"]) / max(count, 1), 2),
                    "max_ms": round(float(item["max_ms"]), 2),
                }
            return {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "uptime_seconds": round(time.time() - self.started_at, 2),
                "requests_total": self._total,
                "server_errors": self._errors,
                "status_codes": dict(self._status),
                "routes": routes,
                "recent_errors": list(self._recent_errors),
            }


metrics = RequestMetrics()
