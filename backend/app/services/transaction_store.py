"""SQLite-backed research, paper-trading and audit record store.

Paper trading is deliberately local and simulated.  There is no broker or
webhook side effect in this module; all state transitions are transactional,
idempotent and represented in the immutable audit trail.
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

from app.services.position_projection import project_fill
from app.services.risk_engine import evaluate_paper_order

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
ORDER_STATUSES = {"new", "accepted", "partially_filled", "filled", "cancelled", "rejected"}
ORDER_TRANSITIONS = {
    "new": {"accepted", "rejected", "cancelled"},
    "accepted": {"partially_filled", "filled", "cancelled", "rejected"},
    "partially_filled": {"partially_filled", "filled", "cancelled"},
    "filled": set(),
    "cancelled": set(),
    "rejected": set(),
}
OUTBOX_STATUSES = {"pending", "sent", "failed"}


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
    for key in (
        "evidence", "counter_evidence", "candidate_source", "metadata", "payload",
        "provenance", "reasons", "snapshot",
    ):
        value = result.get(key)
        if value:
            result[key] = json.loads(value)
        elif key in result:
            result[key] = [] if key in {"evidence", "counter_evidence", "reasons"} else {}
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
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    action TEXT NOT NULL,
                    score REAL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    provenance TEXT NOT NULL DEFAULT '{}',
                    contract_version TEXT NOT NULL DEFAULT '1.0',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS risk_checks (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    reasons TEXT NOT NULL DEFAULT '[]',
                    snapshot TEXT NOT NULL DEFAULT '{}',
                    contract_version TEXT NOT NULL,
                    rules_version TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(plan_id) REFERENCES trade_plans(id)
                );
                CREATE TABLE IF NOT EXISTS paper_orders (
                    id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL UNIQUE,
                    plan_id TEXT NOT NULL,
                    signal_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    execution_date TEXT NOT NULL,
                    order_type TEXT NOT NULL DEFAULT 'limit',
                    quantity REAL NOT NULL,
                    limit_price REAL NOT NULL,
                    status TEXT NOT NULL,
                    filled_quantity REAL NOT NULL DEFAULT 0,
                    avg_fill_price REAL,
                    reject_reason TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES trade_plans(id),
                    FOREIGN KEY(signal_id) REFERENCES signals(id)
                );
                CREATE TABLE IF NOT EXISTS paper_fills (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    trade_date TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    revision INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(order_id) REFERENCES paper_orders(id)
                );
                CREATE TABLE IF NOT EXISTS outbox_events (
                    id TEXT PRIMARY KEY,
                    event_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    next_attempt_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity REAL NOT NULL DEFAULT 0,
                    available_quantity REAL NOT NULL DEFAULT 0,
                    avg_cost REAL NOT NULL DEFAULT 0,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    last_fill_id TEXT,
                    as_of TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_reviews (
                    id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(as_of)
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_journal_occurred ON journal_entries(occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_signals_as_of ON signals(as_of DESC);
                CREATE INDEX IF NOT EXISTS idx_orders_updated ON paper_orders(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_fills_occurred ON paper_fills(occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events(status, created_at);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('contract_version', ?)",
                (CONTRACT_VERSION,),
            )
            self._ensure_column(conn, "paper_orders", "execution_date", "TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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

    # ------------------------------------------------------------------
    # Phase 9/10: unified signals, paper execution and projections
    # ------------------------------------------------------------------
    def create_signal(self, data: dict[str, Any]) -> dict[str, Any]:
        signal_id = data.get("id") or data.get("signal_id") or f"sig_{uuid.uuid4().hex[:12]}"
        key = data.get("idempotency_key") or f"signal:{signal_id}"
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                now = _now()
                row = {
                    "id": signal_id,
                    "symbol": str(data["symbol"]).upper(),
                    "as_of": str(data["as_of"]),
                    "source": str(data["source"]),
                    "source_id": str(data["source_id"]),
                    "kind": str(data.get("kind", "observation")),
                    "action": str(data["action"]),
                    "score": data.get("score"),
                    "payload": data.get("payload", {}),
                    "provenance": data.get("provenance", {}),
                    "contract_version": str(data.get("contract_version", "1.0")),
                    "revision": 1,
                    "created_at": now,
                    "updated_at": now,
                }
                if row["kind"] not in {"entry", "exit", "observation"}:
                    raise TransactionValidationError("无效的 Signal 类型")
                conn.execute(
                    "INSERT INTO signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["id"], row["symbol"], row["as_of"], row["source"], row["source_id"],
                     row["kind"], row["action"], row["score"], _json(row["payload"]),
                     _json(row["provenance"]), row["contract_version"], 1, now, now),
                )
                self._audit(conn, "signal", signal_id, "created", 1, f"{key}:audit", row)
                self._remember(conn, key, "signal", signal_id, row)
                conn.commit()
                return row
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def list_signals(self, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [_decode(row) for row in conn.execute(
                "SELECT * FROM signals ORDER BY as_of DESC, created_at DESC LIMIT ?", (limit,)
            ).fetchall()]

    def evaluate_risk(self, plan_id: str, snapshot: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
        key = idempotency_key or f"risk:{plan_id}:{uuid.uuid4().hex}"
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                result = self._evaluate_risk_in_transaction(conn, plan_id, snapshot, key)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _evaluate_risk_in_transaction(
        self, conn: sqlite3.Connection, plan_id: str, snapshot: dict[str, Any], key: str,
        *, remember: bool = True,
    ) -> dict[str, Any]:
        plan = _decode(conn.execute("SELECT * FROM trade_plans WHERE id=?", (plan_id,)).fetchone())
        if plan is None:
            raise TransactionValidationError("交易计划不存在")
        gate_row = conn.execute(
            "SELECT * FROM decision_gates WHERE plan_id=? ORDER BY updated_at DESC LIMIT 1", (plan_id,)
        ).fetchone()
        gate = _decode(gate_row)
        if gate and gate["status"] == "pending" and gate.get("expires_at") and gate["expires_at"] < _now():
            gate["status"] = "expired"
        position = _decode(conn.execute("SELECT * FROM positions WHERE symbol=?", (plan["symbol"],)).fetchone())
        decision = evaluate_paper_order(
            plan=plan, gate=gate, snapshot=snapshot, existing_position=position,
        )
        check_id = f"risk_{uuid.uuid4().hex[:12]}"
        now = _now()
        risk_row = {
            "id": check_id, "plan_id": plan_id, "symbol": plan["symbol"],
            "status": decision.status, "passed": int(decision.passed),
            "reasons": list(decision.reasons), "snapshot": decision.snapshot,
            "contract_version": decision.contract_version, "rules_version": decision.rules_version,
            "evaluated_at": now, "revision": 1,
        }
        conn.execute(
            "INSERT INTO risk_checks VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (check_id, plan_id, plan["symbol"], decision.status, int(decision.passed),
             _json(risk_row["reasons"]), _json(risk_row["snapshot"]), decision.contract_version,
             decision.rules_version, now, 1),
        )
        self._audit(conn, "risk_check", check_id, "evaluated", 1, f"{key}:risk", risk_row)
        response = {"risk": risk_row, "accepted": decision.passed, "order": None}
        if remember:
            self._remember(conn, key, "risk_check", check_id, response)
        return response

    def list_risk_checks(self, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [_decode(row) for row in conn.execute(
                "SELECT * FROM risk_checks ORDER BY evaluated_at DESC LIMIT ?", (limit,)
            ).fetchall()]

    def submit_paper_order(
        self, plan_id: str, snapshot: dict[str, Any], *, signal_id: str | None = None,
        client_order_id: str | None = None, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = idempotency_key or f"paper-order:{plan_id}:{uuid.uuid4().hex}"
        client_id = client_order_id or f"paper-{uuid.uuid4().hex[:16]}"
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                risk_response = self._evaluate_risk_in_transaction(conn, plan_id, snapshot, key, remember=False)
                if not risk_response["accepted"]:
                    conn.commit()
                    return risk_response
                risk = risk_response["risk"]
                existing_order = _decode(conn.execute(
                    "SELECT * FROM paper_orders WHERE client_order_id=?", (client_id,)
                ).fetchone())
                if existing_order is not None:
                    response = {"accepted": True, "risk": risk, "order": existing_order}
                    self._remember(conn, key, "paper_order", existing_order["id"], response)
                    conn.commit()
                    return response
                plan = _decode(conn.execute("SELECT * FROM trade_plans WHERE id=?", (plan_id,)).fetchone())
                assert plan is not None
                order_id = f"ord_{uuid.uuid4().hex[:12]}"
                now = _now()
                order = {
                    "id": order_id, "client_order_id": client_id, "plan_id": plan_id,
                    "signal_id": signal_id, "symbol": plan["symbol"], "side": plan["direction"],
                    "execution_date": str(snapshot.get("as_of") or now[:10]),
                    "order_type": "limit", "quantity": float(plan["quantity"]),
                    "limit_price": float(plan["entry_price"]), "status": "accepted",
                    "filled_quantity": 0.0, "avg_fill_price": None, "reject_reason": None,
                    "revision": 1, "created_at": now, "updated_at": now,
                }
                conn.execute(
                    "INSERT INTO paper_orders (id, client_order_id, plan_id, signal_id, symbol, side, execution_date, order_type, quantity, limit_price, status, filled_quantity, avg_fill_price, reject_reason, revision, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (order["id"], order["client_order_id"], order["plan_id"], order["signal_id"], order["symbol"], order["side"], order["execution_date"], order["order_type"], order["quantity"], order["limit_price"], order["status"], order["filled_quantity"], order["avg_fill_price"], order["reject_reason"], order["revision"], order["created_at"], order["updated_at"]),
                )
                self._audit(conn, "paper_order", order_id, "accepted", 1, f"{key}:order", {"order": order, "risk_id": risk["id"]})
                self._append_outbox(conn, "paper_order.accepted", "paper_order", order_id, order, f"{key}:outbox")
                response = {"accepted": True, "risk": risk, "order": order}
                self._remember(conn, key, "paper_order", order_id, response)
                conn.commit()
                return response
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def list_orders(self, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [_decode(row) for row in conn.execute(
                "SELECT * FROM paper_orders ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()]

    def transition_order(
        self, order_id: str, status: str, *, expected_revision: int | None = None,
        reason: str | None = None, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if status not in ORDER_STATUSES:
            raise TransactionValidationError("无效的订单状态")
        key = idempotency_key or f"order-transition:{order_id}:{uuid.uuid4().hex}"
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                order = _decode(conn.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone())
                if order is None:
                    raise TransactionValidationError("纸面订单不存在")
                if expected_revision is not None and int(expected_revision) != int(order["revision"]):
                    raise TransactionConflictError(f"revision 冲突: 当前为 {order['revision']}, 请求为 {expected_revision}")
                if status not in ORDER_TRANSITIONS.get(order["status"], set()):
                    raise TransactionValidationError(f"订单状态不可从 {order['status']} 转为 {status}")
                now = _now()
                revision = int(order["revision"]) + 1
                conn.execute(
                    "UPDATE paper_orders SET status=?, reject_reason=?, revision=?, updated_at=? WHERE id=?",
                    (status, reason if status in {"rejected", "cancelled"} else None, revision, now, order_id),
                )
                updated = _decode(conn.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone())
                self._audit(conn, "paper_order", order_id, status, revision, f"{key}:audit", {"reason": reason, "order": updated})
                self._remember(conn, key, "paper_order", order_id, updated or {})
                conn.commit()
                return updated or {}
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def simulate_fill(
        self, order_id: str, data: dict[str, Any], *, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = idempotency_key or f"fill:{order_id}:{uuid.uuid4().hex}"
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                order = _decode(conn.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone())
                if order is None:
                    raise TransactionValidationError("纸面订单不存在")
                if order["status"] not in {"accepted", "partially_filled"}:
                    raise TransactionValidationError(f"订单状态 {order['status']} 不允许模拟成交")
                quantity = float(data["quantity"])
                price = float(data["price"])
                remaining = float(order["quantity"]) - float(order["filled_quantity"])
                if quantity <= 0 or quantity > remaining:
                    raise TransactionValidationError("成交数量超过订单剩余数量")
                fill_id = f"fill_{uuid.uuid4().hex[:12]}"
                now = _now()
                trade_date = str(data.get("trade_date") or now[:10])
                fill = {
                    "id": fill_id, "order_id": order_id, "symbol": order["symbol"],
                    "side": order["side"], "quantity": quantity, "price": price,
                    "trade_date": trade_date, "occurred_at": str(data.get("occurred_at") or now),
                    "status": "confirmed", "revision": 1,
                }
                conn.execute(
                    "INSERT INTO paper_fills VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(fill.values()),
                )
                filled = float(order["filled_quantity"]) + quantity
                status = "filled" if abs(filled - float(order["quantity"])) < 1e-9 else "partially_filled"
                avg = ((float(order["avg_fill_price"] or 0) * float(order["filled_quantity"])) + price * quantity) / filled
                revision = int(order["revision"]) + 1
                conn.execute(
                    "UPDATE paper_orders SET status=?, filled_quantity=?, avg_fill_price=?, revision=?, updated_at=? WHERE id=?",
                    (status, filled, avg, revision, now, order_id),
                )
                previous = _decode(conn.execute("SELECT * FROM positions WHERE symbol=?", (order["symbol"],)).fetchone())
                projected = project_fill(previous, fill)
                old_revision = int(previous["revision"]) if previous else 0
                conn.execute(
                    "INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity, available_quantity=excluded.available_quantity, avg_cost=excluded.avg_cost, realized_pnl=excluded.realized_pnl, last_fill_id=excluded.last_fill_id, as_of=excluded.as_of, revision=excluded.revision, updated_at=excluded.updated_at",
                    (projected["symbol"], projected["quantity"], projected["available_quantity"], projected["avg_cost"], projected["realized_pnl"], projected["last_fill_id"], projected["as_of"], old_revision + 1, now),
                )
                order = _decode(conn.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone())
                position = _decode(conn.execute("SELECT * FROM positions WHERE symbol=?", (order["symbol"],)).fetchone())
                self._audit(conn, "paper_fill", fill_id, "confirmed", 1, f"{key}:fill", {"fill": fill, "order": order})
                self._audit(conn, "position", order["symbol"], "projected", int(position["revision"]), f"{key}:position", position)
                self._append_outbox(conn, "paper_fill.confirmed", "paper_fill", fill_id, {"fill": fill, "position": position}, f"{key}:outbox")
                response = {"fill": fill, "order": order, "position": position}
                self._remember(conn, key, "paper_fill", fill_id, response)
                conn.commit()
                return response
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def list_fills(self, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [_decode(row) for row in conn.execute(
                "SELECT * FROM paper_fills ORDER BY occurred_at DESC LIMIT ?", (limit,)
            ).fetchall()]

    def list_positions(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [_decode(row) for row in conn.execute(
                "SELECT * FROM positions WHERE quantity > 0 ORDER BY symbol"
            ).fetchall()]

    def settle_positions(self, trade_date: str) -> int:
        """Release buys from earlier dates for the explicit A-share T+1 step."""
        with self._lock:
            conn = self._begin()
            try:
                now = _now()
                cur = conn.execute(
                    "UPDATE positions SET available_quantity=quantity, revision=revision+1, updated_at=? WHERE as_of < ? AND available_quantity < quantity",
                    (now, trade_date),
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _append_outbox(
        self, conn: sqlite3.Connection, event_type: str, entity_type: str, entity_id: str,
        payload: dict[str, Any], event_key: str,
    ) -> dict[str, Any]:
        now = _now()
        event = {
            "id": f"evt_{uuid.uuid4().hex[:12]}", "event_key": event_key,
            "event_type": event_type, "entity_type": entity_type, "entity_id": entity_id,
            "payload": payload, "status": "pending", "attempts": 0,
            "last_error": None, "next_attempt_at": None, "created_at": now, "updated_at": now,
        }
        conn.execute(
            "INSERT INTO outbox_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (event["id"], event["event_key"], event["event_type"], event["entity_type"], event["entity_id"],
             _json(event["payload"]), event["status"], 0, None, None, now, now),
        )
        return event

    def list_outbox(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            if status and status not in OUTBOX_STATUSES:
                raise TransactionValidationError("无效的 Outbox 状态")
            if status:
                rows = conn.execute(
                    "SELECT * FROM outbox_events WHERE status=? ORDER BY created_at LIMIT ?", (status, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM outbox_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [_decode(row) for row in rows]

    def update_outbox(self, event_id: str, status: str, error: str | None = None) -> dict[str, Any]:
        if status not in OUTBOX_STATUSES:
            raise TransactionValidationError("无效的 Outbox 状态")
        with self._lock:
            conn = self._begin()
            try:
                row = _decode(conn.execute("SELECT * FROM outbox_events WHERE id=?", (event_id,)).fetchone())
                if row is None:
                    raise TransactionValidationError("Outbox 事件不存在")
                now = _now()
                attempts = int(row["attempts"]) + (1 if status != "pending" else 0)
                conn.execute(
                    "UPDATE outbox_events SET status=?, attempts=?, last_error=?, updated_at=? WHERE id=?",
                    (status, attempts, error, now, event_id),
                )
                updated = _decode(conn.execute("SELECT * FROM outbox_events WHERE id=?", (event_id,)).fetchone())
                self._audit(conn, "outbox_event", event_id, status, attempts, f"outbox:{event_id}:{attempts}", updated or {})
                conn.commit()
                return updated or {}
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def create_daily_review(self, as_of: str, summary: str = "", *, idempotency_key: str | None = None) -> dict[str, Any]:
        key = idempotency_key or f"review:{as_of}"
        with self._lock:
            conn = self._begin()
            try:
                replay = self._replay(conn, key)
                if replay:
                    conn.rollback()
                    return replay
                existing = conn.execute("SELECT * FROM daily_reviews WHERE as_of=?", (as_of,)).fetchone()
                if existing:
                    result = _decode(existing)
                    self._remember(conn, key, "daily_review", result["id"], result)
                    conn.commit()
                    return result
                snapshot = {
                    "signals": [_decode(row) for row in conn.execute("SELECT * FROM signals WHERE as_of=? ORDER BY created_at", (as_of,)).fetchall()],
                    "risk_checks": [_decode(row) for row in conn.execute("SELECT * FROM risk_checks WHERE substr(evaluated_at,1,10)=? ORDER BY evaluated_at", (as_of,)).fetchall()],
                    "orders": [_decode(row) for row in conn.execute("SELECT * FROM paper_orders WHERE execution_date=? ORDER BY created_at", (as_of,)).fetchall()],
                    "fills": [_decode(row) for row in conn.execute("SELECT * FROM paper_fills WHERE trade_date=? ORDER BY occurred_at", (as_of,)).fetchall()],
                    "positions": [_decode(row) for row in conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()],
                }
                now = _now()
                row = {"id": f"review_{uuid.uuid4().hex[:12]}", "as_of": as_of, "summary": summary, "snapshot": snapshot, "created_at": now}
                conn.execute("INSERT INTO daily_reviews VALUES(?,?,?,?,?)", (row["id"], as_of, summary, _json(snapshot), now))
                self._audit(conn, "daily_review", row["id"], "created", 1, f"{key}:audit", row)
                self._remember(conn, key, "daily_review", row["id"], row)
                conn.commit()
                return row
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def list_daily_reviews(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [_decode(row) for row in conn.execute(
                "SELECT * FROM daily_reviews ORDER BY as_of DESC LIMIT ?", (limit,)
            ).fetchall()]

    def paper_summary(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            return {
                "signals": conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0],
                "risk_checks": conn.execute("SELECT COUNT(*) FROM risk_checks").fetchone()[0],
                "orders": conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0],
                "fills": conn.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0],
                "positions": conn.execute("SELECT COUNT(*) FROM positions WHERE quantity > 0").fetchone()[0],
                "outbox_pending": conn.execute("SELECT COUNT(*) FROM outbox_events WHERE status='pending'").fetchone()[0],
                "reviews": conn.execute("SELECT COUNT(*) FROM daily_reviews").fetchone()[0],
            }

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
