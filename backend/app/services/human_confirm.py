"""Auditable, one-time human confirmation records for broker actions."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.broker.protocol import BrokerError, utc_now


class HumanConfirmError(BrokerError):
    """Raised when a confirmation is missing, stale, or already consumed."""


def _digest(action: str, payload: dict[str, Any]) -> str:
    def canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in value.items()}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value)
        return value

    encoded = json.dumps(
        {"action": action, "payload": canonical(payload)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class HumanConfirmStore:
    """Small atomic JSON store kept under user data, never in Git."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "user_data" / "human_confirmations.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, rows: list[dict[str, Any]]) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def request(self, action: str, payload: dict[str, Any], ttl_seconds: int = 300) -> dict[str, Any]:
        if not action.strip():
            raise HumanConfirmError("确认动作不能为空", code="CONFIRM_ACTION_INVALID")
        if ttl_seconds < 30 or ttl_seconds > 3600:
            raise HumanConfirmError("确认有效期必须在 30 秒至 1 小时之间", code="CONFIRM_TTL_INVALID")
        now = datetime.now(UTC)
        row = {
            "id": f"confirm_{uuid.uuid4().hex[:12]}",
            "action": action,
            "payload_hash": _digest(action, payload),
            "status": "pending",
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds"),
            "requested_at": now.isoformat(timespec="seconds"),
            "decided_at": None,
            "decided_by": None,
            "revision": 1,
        }
        with self._lock:
            rows = self._load()
            rows.append(row)
            self._save(rows)
        return row

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._load()
            now = datetime.now(UTC)
            changed = False
            for row in rows:
                if row["status"] == "pending" and _parse(row["expires_at"]) <= now:
                    row["status"] = "expired"
                    row["revision"] = int(row["revision"]) + 1
                    changed = True
            if changed:
                self._save(rows)
            return list(reversed(rows[-limit:]))

    def decide(self, confirmation_id: str, status: str, decided_by: str = "local-user") -> dict[str, Any]:
        if status not in {"approved", "rejected"}:
            raise HumanConfirmError("确认结果必须是 approved 或 rejected", code="CONFIRM_STATUS_INVALID")
        with self._lock:
            rows = self._load()
            row = next((item for item in rows if item["id"] == confirmation_id), None)
            if row is None:
                raise HumanConfirmError("人工确认请求不存在", code="CONFIRM_NOT_FOUND")
            self._expire_if_needed(row)
            if row["status"] != "pending":
                raise HumanConfirmError(f"确认请求当前状态为 {row['status']}", code="CONFIRM_NOT_PENDING")
            row["status"] = status
            row["decided_at"] = utc_now()
            row["decided_by"] = decided_by
            row["revision"] = int(row["revision"]) + 1
            self._save(rows)
            return row

    def authorize(self, confirmation_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = self._load()
            row = next((item for item in rows if item["id"] == confirmation_id), None)
            if row is None:
                raise HumanConfirmError("人工确认请求不存在", code="CONFIRM_NOT_FOUND")
            self._expire_if_needed(row)
            if row["status"] != "approved":
                raise HumanConfirmError("人工确认尚未批准或已失效", code="CONFIRM_NOT_APPROVED")
            if row["action"] != action or row["payload_hash"] != _digest(action, payload):
                raise HumanConfirmError("确认内容与待执行订单不一致", code="CONFIRM_PAYLOAD_MISMATCH")
            row["status"] = "consumed"
            row["consumed_at"] = utc_now()
            row["revision"] = int(row["revision"]) + 1
            self._save(rows)
            return row

    @staticmethod
    def _expire_if_needed(row: dict[str, Any]) -> None:
        if row["status"] == "pending" and _parse(row["expires_at"]) <= datetime.now(UTC):
            row["status"] = "expired"
            row["revision"] = int(row["revision"]) + 1
