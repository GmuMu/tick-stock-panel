"""Independent alert-delivery status and audit records.

The alert store remains the source of truth for triggered events.  This module
records channel outcomes separately so a failed external notification never
changes the alert itself or blocks SSE delivery.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DELIVERY_CONTRACT_VERSION = "1.0"
DELIVERY_STATUSES = {"queued", "sent", "failed", "skipped"}
_lock = threading.Lock()


def _path(data_dir: Path) -> Path:
    path = data_dir / "user_data" / "alert_deliveries.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def delivery_id(event: dict[str, Any], channel: str) -> str:
    raw = "|".join(
        str(event.get(key, ""))
        for key in ("ts", "rule_id", "source", "type", "symbol", "message")
    ) + f"|{channel}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def record(
    data_dir: Path,
    event: dict[str, Any],
    channel: str,
    status: str,
    *,
    attempts: int = 0,
    error: str | None = None,
    delivery_key: str | None = None,
    queued_at: int | None = None,
    ts: float | None = None,
) -> dict[str, Any]:
    """Append one immutable delivery state transition."""
    if status not in DELIVERY_STATUSES:
        raise ValueError(f"unsupported delivery status: {status}")
    now = ts if ts is not None else time.time()
    item = {
        "contract_version": DELIVERY_CONTRACT_VERSION,
        "delivery_id": delivery_key or delivery_id(event, channel),
        "event_ts": event.get("ts"),
        "rule_id": event.get("rule_id"),
        "rule_revision": (event.get("alert_rule") or {}).get("revision"),
        "channel": channel,
        "status": status,
        "attempts": max(0, int(attempts)),
        "queued_at": queued_at or event.get("delivery_queued_at"),
        "updated_at": int(now * 1000),
        "error": error,
    }
    if status == "queued":
        item["queued_at"] = item["updated_at"]
    with _lock, _path(data_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def submit(
    data_dir: Path,
    event: dict[str, Any],
    channel: str,
    sender: Callable[..., Any],
    args: tuple[Any, ...],
    executor: Executor,
) -> str:
    """Record queued and run one channel delivery asynchronously."""
    key = delivery_id(event, channel)
    queued = record(data_dir, event, channel, "queued", delivery_key=key)
    queued_at = int(queued["updated_at"])

    def run() -> None:
        started = time.monotonic()
        try:
            ok = bool(sender(*args))
            record(
                data_dir,
                event,
                channel,
                "sent" if ok else "failed",
                attempts=1,
                error=None if ok else "sender returned false",
                delivery_key=key,
                queued_at=queued_at,
            )
        except Exception as exc:
            logger.warning("alert delivery failed channel=%s: %s", channel, exc)
            record(
                data_dir,
                event,
                channel,
                "failed",
                attempts=1,
                error=str(exc),
                delivery_key=key,
                queued_at=queued_at,
            )
        finally:
            logger.debug("alert delivery channel=%s completed in %.3fs", channel, time.monotonic() - started)

    try:
        executor.submit(run)
    except Exception as exc:
        record(
            data_dir, event, channel, "failed", error=str(exc), delivery_key=key,
            queued_at=queued_at,
        )
        logger.warning("alert delivery queue failed channel=%s: %s", channel, exc)
    return key


def record_skipped(
    data_dir: Path,
    event: dict[str, Any],
    channel: str,
    reason: str,
) -> dict[str, Any]:
    return record(data_dir, event, channel, "skipped", error=reason)


def list_recent(data_dir: Path, limit: int = 500) -> list[dict[str, Any]]:
    """Read the most recent delivery transitions for diagnostics."""
    path = _path(data_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with _lock, path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning("alert delivery audit read failed: %s", exc)
        return []
    rows.sort(key=lambda row: row.get("updated_at", 0), reverse=True)
    return rows[: max(1, int(limit))]
