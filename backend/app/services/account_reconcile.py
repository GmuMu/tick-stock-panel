"""Persistent account/order/fill/position reconciliation history."""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from app.broker.protocol import utc_now
from app.broker.reconcile import ReconcileService


class AccountReconcileService:
    """Run read-only reconciliations and retain reports for later review."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "user_data" / "account_reconcile.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._comparator = ReconcileService()

    def run(
        self,
        broker_snapshot: dict[str, Any],
        local_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        report = self._comparator.compare(
            broker_snapshot,
            local_snapshot if local_snapshot is not None else broker_snapshot,
            checked_at=utc_now(),
        ).to_dict()
        record = {
            "id": f"reconcile_{uuid.uuid4().hex[:12]}",
            "report": report,
            "created_at": utc_now(),
        }
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        rows: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return list(reversed(rows))
