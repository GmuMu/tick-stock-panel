"""HTTP bridge for a local free-stockdb service.

The application talks to this small client instead of importing free-stockdb
implementation details.  The endpoint paths are configurable because
free-stockdb deployments may expose the same datasets under different API
prefixes.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 20.0
PROBE_TIMEOUT = 2.0

_PATH_CANDIDATES = {
    "health": ("/health", "/api/health", "/api/v1/health", "/api/status"),
    "daily": (
        "/api/v1/stocks/daily",
        "/api/stocks/daily",
        "/api/v1/stock/daily",
        "/api/stock/daily",
    ),
    "minute": (
        "/api/v1/stocks/minute",
        "/api/stocks/minute",
        "/api/v1/stock/minute",
        "/api/stock/minute",
    ),
    "realtime": (
        "/api/v1/stocks/tick",
        "/api/stocks/tick",
        "/api/v1/stock/tick",
        "/api/stock/tick",
        "/api/v1/stocks/realtime",
        "/api/stocks/realtime",
    ),
    "adj_factor": (
        "/api/v1/stocks/adj-factors",
        "/api/stocks/adj-factors",
        "/api/v1/stock/adj-factors",
        "/api/stock/adj-factors",
    ),
    "instruments": (
        "/api/v1/stocks/instruments",
        "/api/stocks/instruments",
        "/api/v1/stock/instruments",
        "/api/stock/instruments",
    ),
}

_ENV_PATHS = {
    "health": "FREE_STOCKDB_HEALTH_PATH",
    "daily": "FREE_STOCKDB_DAILY_PATH",
    "minute": "FREE_STOCKDB_MINUTE_PATH",
    "realtime": "FREE_STOCKDB_TICK_PATH",
    "adj_factor": "FREE_STOCKDB_ADJ_FACTOR_PATH",
    "instruments": "FREE_STOCKDB_INSTRUMENTS_PATH",
}


class FreeStockDBError(RuntimeError):
    """Raised when the free-stockdb bridge cannot return a valid response."""


def _base_url() -> str:
    return (os.getenv("FREE_STOCKDB_URL") or DEFAULT_BASE_URL).strip().rstrip("/") + "/"


def _timeout(value: float = DEFAULT_TIMEOUT) -> float:
    raw = os.getenv("FREE_STOCKDB_TIMEOUT")
    if raw is None:
        return value
    try:
        return max(0.1, min(float(raw), 300.0))
    except ValueError:
        return value


def _paths(dataset: str) -> tuple[str, ...]:
    override = (os.getenv(_ENV_PATHS[dataset]) or "").strip()
    if not override:
        return _PATH_CANDIDATES[dataset]
    return (override, *[path for path in _PATH_CANDIDATES[dataset] if path != override])


def _as_rows(payload: Any) -> list[dict] | dict[str, list[dict]]:
    """Unwrap common JSON envelopes without imposing a vendor SDK shape."""
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("data", "rows", "items", "results", "result"):
        value = payload.get(key)
        if isinstance(value, (list, dict)):
            return _as_rows(value)

    keyed: dict[str, list[dict]] = {}
    for key, value in payload.items():
        if isinstance(value, list) and all(isinstance(row, dict) for row in value):
            keyed[str(key)] = [dict(row) for row in value]
    return keyed


def _flatten_rows(rows: list[dict] | dict[str, list[dict]]) -> list[dict]:
    if isinstance(rows, list):
        return rows
    out: list[dict] = []
    for symbol, items in rows.items():
        for item in items:
            row = dict(item)
            row.setdefault("symbol", symbol)
            out.append(row)
    return out


def _symbol_params(symbols: Iterable[str] | None) -> dict[str, str]:
    values = [str(symbol).strip() for symbol in (symbols or []) if str(symbol).strip()]
    return {"symbols": ",".join(values)} if values else {}


class FreeStockDBClient:
    """Small, dependency-light HTTP client for the free-stockdb API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        http: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or _base_url()).rstrip("/") + "/"
        self._http = http or httpx.Client(
            timeout=_timeout(timeout),
            headers={"Accept": "application/json"},
        )
        self._owns_http = http is None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _get(self, dataset: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for path in _paths(dataset):
            try:
                response = self._http.get(
                    urljoin(self.base_url, path.lstrip("/")),
                    params=params or {},
                    timeout=_timeout(),
                )
            except httpx.HTTPError as exc:
                last_error = exc
                break
            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                raise FreeStockDBError(
                    f"free-stockdb HTTP {response.status_code}: {path}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise FreeStockDBError(f"free-stockdb returned invalid JSON: {path}") from exc
        if last_error is not None:
            raise FreeStockDBError(f"free-stockdb network request failed: {last_error}") from last_error
        raise FreeStockDBError(f"free-stockdb endpoint not found: {dataset}")

    def ping(self) -> dict:
        payload = self._get("health")
        if isinstance(payload, dict):
            return payload
        return {"status": "ok", "data": payload}

    def fetch(
        self,
        dataset: str,
        *,
        symbols: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        asset_type: str = "stock",
        freq: str = "1m",
    ) -> list[dict] | dict[str, list[dict]]:
        params: dict[str, Any] = {
            **_symbol_params(symbols),
            "start": start or "",
            "end": end or "",
            "asset_type": asset_type,
            "freq": freq,
        }
        return _as_rows(self._get(dataset, params))

    def fetch_flat(
        self,
        dataset: str,
        *,
        symbols: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        asset_type: str = "stock",
        freq: str = "1m",
    ) -> list[dict]:
        return _flatten_rows(
            self.fetch(
                dataset,
                symbols=symbols,
                start=start,
                end=end,
                asset_type=asset_type,
                freq=freq,
            )
        )


def availability() -> tuple[bool, str]:
    """Probe the configured server without making the plugin mandatory."""
    try:
        client = FreeStockDBClient(timeout=PROBE_TIMEOUT)
        try:
            payload = client.ping()
        finally:
            client.close()
        status = payload.get("status") or payload.get("message") or "ok"
        return True, f"ok ({status})"
    except FreeStockDBError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.debug("free-stockdb availability probe failed", exc_info=True)
        return False, f"probe failed: {exc}"
