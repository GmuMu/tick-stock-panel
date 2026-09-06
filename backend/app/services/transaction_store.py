"""SQLite-backed research and paper-trading record store.

This module intentionally stops at research records. It does not place orders,
maintain broker state, or project positions. Those concerns belong to later
phases and must consume the immutable audit trail created here.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "1.0"
DECISION_STATUSES = {"pending", "approved", "rejected", "expired"}
DECISION_TRANSITIONS = {
    "pending": {"approved", "rejected", "expired"},
    "approved": set(),
    "rejected": set(),
    "expired": set(),
}
PLAN_STATUSES = {"draft", "active", "closed", "cancelled", "expired"}
JOURNAL_KINDS = {"plan", "decision", "order", "fill", "review", "note"}


class TransactionStoreError(RuntimeError):
    """Base error for the transaction store."""


class TransactionConflictError(TransactionStoreError):
    """Raised when a client writes against an old revision."""


class TransactionValidationError(TransactionStoreError, ValueError):
    """Raised for invalid domain state or malformed stored data."""


_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("evidence", "counter_evidence", "candidate_source", "metadata", "payload"):
        value = result.get(key)
        if value:
            result[key] = json.loads(value)
        elif key in result:
            result[key] = [] if key in {"evidence", "counter_evidence"} else {}
    return result


class TransactionStore:
    """Durable transaction-domain boundary, one SQLite file per data directory."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "user_data" / "transactions.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.path)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS theses (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    title TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    counter_evidence TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    version INTEGER NOT NULL DEFAULT 1,
                    revision INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trade_plans (
                    id TEXT PRIMARY KEY,
                    thesis_id TEXT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL,
                    stop_price REAL,
                    target_price REAL,
                    position_pct REAL,
                    quantity REAL,
                    valid_from TEXT,
                    valid_until TEXT,
                    candidate_source TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    notes TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(thesis_id) REFERENCES theses(id)
                );
                CREATE TABLE IF NOT EXISTS decision_gates (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    rationale TEXT NOT NULL DEFAULT '',
                    expires_at TEXT,
                    decided_at TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES trade_plans(id)
                );
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT,
                    decision_id TEXT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    occurred_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES trade_plans(id),
                    FOREIGN KEY(decision_id) REFERENCES decision_gates(id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    response TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_journal_occurred ON journal_entries(occurred_at DESC);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('contract_version', ?)",
                (CONTRACT_VERSION,),
            )

    def _replay(self, conn: sqlite3.Connection, key: str | None) -> dict[str, Any] | None:
        if not key:
            return None
        row = conn.execute(
            "SELECT response FROM idempotency_keys WHERE idempotency_key=?", (key,)
        ).fetchone()
        return json.loads(row["response"]) if row else None

    def _remember(
        self,
        conn: sqlite3.Connection,
        key: str | None,
        entity_type: str,
        entity_id: str,
        response: dict[str, Any],
    ) -> None:
        if key:
            conn.execute(
                "INSERT INTO idempotency_keys VALUES(?,?,?,?,?)",
                (key, entity_type, entity_id, _json(response), _now()),
            )

    def _audit(
        self,
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        action: str,
        revision: int,
        key: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), entity_type, entity_id, action, revision, key, _json(payload), _now()),
        )

    def _begin(self) -> sqlite3.Connection:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        return conn

    def create_thesis(self, data: dict[str, Any]) -> dict[str, Any]:
        thesis_id = data.get("id") or f"th_{uuid.uuid4().hex[:12]}"
        key = data.get("idempotency_key") or str(uuid.uuid4())
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                now = _now()
                row = {
                    "id": thesis_id, "symbol": data["symbol"], "title": data["title"],
                    "direction": data["direction"], "hypothesis": data["hypothesis"],
                    "evidence": data.get("evidence", []),
                    "counter_evidence": data.get("counter_evidence", []),
                    "status": data.get("status", "open"), "version": 1, "revision": 1,
                    "metadata": data.get("metadata", {}), "created_at": now, "updated_at": now,
                }
                conn.execute(
                    "INSERT INTO theses VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["id"], row["symbol"], row["title"], row["direction"], row["hypothesis"],
                     _json(row["evidence"]), _json(row["counter_evidence"]), row["status"],
                     row["version"], row["revision"], _json(row["metadata"]), now, now),
                )
                self._audit(conn, "thesis", thesis_id, "created", 1, key, row)
                self._remember(conn, key, "thesis", thesis_id, row)
                conn.commit()
                return row
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def list_theses(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [
                _decode(row) for row in conn.execute(
                    "SELECT * FROM theses ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            ]

    def update_thesis(self, thesis_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._update_entity("thesis", thesis_id, data)

    def create_plan(self, data: dict[str, Any]) -> dict[str, Any]:
        plan_id = data.get("id") or f"plan_{uuid.uuid4().hex[:12]}"
        key = data.get("idempotency_key") or str(uuid.uuid4())
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                if data.get("thesis_id") and not conn.execute(
                    "SELECT 1 FROM theses WHERE id=?", (data["thesis_id"],)
                ).fetchone():
                    raise TransactionValidationError("关联的 thesis 不存在")
                now = _now()
                row = {
                    "id": plan_id, "thesis_id": data.get("thesis_id"), "symbol": data["symbol"],
                    "direction": data.get("direction", "buy"), "entry_price": data.get("entry_price"),
                    "stop_price": data.get("stop_price"), "target_price": data.get("target_price"),
                    "position_pct": data.get("position_pct"), "quantity": data.get("quantity"),
                    "valid_from": data.get("valid_from"), "valid_until": data.get("valid_until"),
                    "candidate_source": data.get("candidate_source", {}),
                    "status": data.get("status", "draft"), "notes": data.get("notes", ""),
                    "revision": 1, "created_at": now, "updated_at": now,
                }
                conn.execute(
                    "INSERT INTO trade_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["id"], row["thesis_id"], row["symbol"], row["direction"], row["entry_price"],
                     row["stop_price"], row["target_price"], row["position_pct"], row["quantity"],
                     row["valid_from"], row["valid_until"], _json(row["candidate_source"]),
                     row["status"], row["notes"], 1, now, now),
                )
                self._audit(conn, "trade_plan", plan_id, "created", 1, key, row)
                self._remember(conn, key, "trade_plan", plan_id, row)
                conn.commit()
                return row
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def list_plans(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [_decode(row) for row in conn.execute(
                "SELECT * FROM trade_plans ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()]

    def update_plan(self, plan_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._update_entity("trade_plan", plan_id, data)

    def create_decision(self, data: dict[str, Any]) -> dict[str, Any]:
        plan_id = data["plan_id"]
        decision_id = data.get("id") or f"gate_{uuid.uuid4().hex[:12]}"
        key = data.get("idempotency_key") or str(uuid.uuid4())
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                if not conn.execute("SELECT 1 FROM trade_plans WHERE id=?", (plan_id,)).fetchone():
                    raise TransactionValidationError("关联的交易计划不存在")
                now = _now()
                status = data.get("status", "pending")
                if status not in DECISION_STATUSES:
                    raise TransactionValidationError("无效的决策状态")
                row = {
                    "id": decision_id, "plan_id": plan_id, "status": status,
                    "rationale": data.get("rationale", ""), "expires_at": data.get("expires_at"),
                    "decided_at": now if status != "pending" else None, "revision": 1,
                    "created_at": now, "updated_at": now,
                }
                conn.execute(
                    "INSERT INTO decision_gates VALUES(?,?,?,?,?,?,?,?,?)",
                    tuple(row.values()),
                )
                self._audit(conn, "decision_gate", decision_id, "created", 1, key, row)
                self._remember(conn, key, "decision_gate", decision_id, row)
                conn.commit()
                return row
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def list_decisions(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM decision_gates ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            result = []
            now = _now()
            for row in rows:
                item = _decode(row)
                if item and item["status"] == "pending" and item.get("expires_at") and item["expires_at"] < now:
                    item["status"] = "expired"
                result.append(item)
            return result

    def transition_decision(self, decision_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._update_entity("decision_gate", decision_id, data, action="transition")

    def create_journal(self, data: dict[str, Any]) -> dict[str, Any]:
        entry_id = data.get("id") or f"jrn_{uuid.uuid4().hex[:12]}"
        key = data.get("idempotency_key") or str(uuid.uuid4())
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                if data.get("plan_id") and not conn.execute(
                    "SELECT 1 FROM trade_plans WHERE id=?", (data["plan_id"],)
                ).fetchone():
                    raise TransactionValidationError("关联的交易计划不存在")
                if data.get("decision_id") and not conn.execute(
                    "SELECT 1 FROM decision_gates WHERE id=?", (data["decision_id"],)
                ).fetchone():
                    raise TransactionValidationError("关联的决策门不存在")
                now = _now()
                row = {
                    "id": entry_id, "plan_id": data.get("plan_id"), "decision_id": data.get("decision_id"),
                    "kind": data["kind"], "content": data["content"],
                    "payload": data.get("payload", {}), "occurred_at": data.get("occurred_at") or now,
                    "revision": 1, "created_at": now,
                }
                conn.execute(
                    "INSERT INTO journal_entries VALUES(?,?,?,?,?,?,?,?,?)",
                    (row["id"], row["plan_id"], row["decision_id"], row["kind"], row["content"],
                     _json(row["payload"]), row["occurred_at"], 1, now),
                )
                self._audit(conn, "journal_entry", entry_id, "created", 1, key, row)
                self._remember(conn, key, "journal_entry", entry_id, row)
                conn.commit()
                return row
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def list_journal(self, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [_decode(row) for row in conn.execute(
                "SELECT * FROM journal_entries ORDER BY occurred_at DESC LIMIT ?", (limit,)
            ).fetchall()]

    def list_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [_decode(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            counts = {}
            for table, key in (("theses", "theses"), ("trade_plans", "plans"),
                               ("decision_gates", "decisions"), ("journal_entries", "journal"),
                               ("audit_events", "audit_events")):
                counts[key] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return {"contract_version": CONTRACT_VERSION, **counts}

    def _update_entity(
        self,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any],
        *,
        action: str = "updated",
    ) -> dict[str, Any]:
        table = {"thesis": "theses", "trade_plan": "trade_plans", "decision_gate": "decision_gates"}[entity_type]
        columns = {
            "thesis": {"title", "direction", "hypothesis", "evidence", "counter_evidence", "status", "metadata"},
            "trade_plan": {"thesis_id", "entry_price", "stop_price", "target_price", "position_pct", "quantity", "valid_from", "valid_until", "candidate_source", "status", "notes"},
            "decision_gate": {"status", "rationale", "expires_at"},
        }[entity_type]
        key = data.get("idempotency_key") or str(uuid.uuid4())
        expected = data.get("expected_revision")
        updates = {k: v for k, v in data.items() if k in columns}
        if not updates:
            raise TransactionValidationError("没有可更新字段")
        if entity_type == "decision_gate":
            status = updates.get("status")
            if status not in DECISION_STATUSES:
                raise TransactionValidationError("无效的决策状态")
        if entity_type == "trade_plan" and "status" in updates and updates["status"] not in PLAN_STATUSES:
            raise TransactionValidationError("无效的交易计划状态")
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                current = conn.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone()
                if current is None:
                    raise TransactionValidationError("记录不存在")
                current_revision = int(current["revision"])
                if expected is not None and int(expected) != current_revision:
                    raise TransactionConflictError(
                        f"revision 冲突: 当前为 {current_revision}, 请求为 {expected}"
                    )
                revision = current_revision + 1
                now = _now()
                if entity_type == "decision_gate" and action == "transition":
                    current_status = current["status"]
                    if current_status == "pending" and current["expires_at"] and current["expires_at"] < now:
                        current_status = "expired"
                    next_status = updates.get("status")
                    if next_status not in DECISION_TRANSITIONS.get(current_status, set()):
                        raise TransactionValidationError(
                            f"决策状态不可从 {current_status} 转为 {next_status}"
                        )
                encoded = {k: (_json(v) if k in {"evidence", "counter_evidence", "metadata", "candidate_source"} else v)
                           for k, v in updates.items()}
                if entity_type == "decision_gate" and encoded.get("status") != "pending":
                    encoded["decided_at"] = now
                assignments = ", ".join(f"{key_name}=?" for key_name in encoded)
                values = [*encoded.values(), revision, now, entity_id]
                conn.execute(
                    f"UPDATE {table} SET {assignments}, revision=?, updated_at=? WHERE id=?",
                    values,
                )
                updated = _decode(conn.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone())
                assert updated is not None
                self._audit(conn, entity_type, entity_id, action, revision, key, {"changes": updates, "record": updated})
                self._remember(conn, key, entity_type, entity_id, updated)
                conn.commit()
                return updated
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
