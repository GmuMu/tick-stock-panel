from __future__ import annotations

import sqlite3

import pytest

from app.services.transaction_store import (
    TransactionConflictError,
    TransactionStore,
    TransactionValidationError,
)


def _thesis(store: TransactionStore) -> dict:
    return store.create_thesis({
        "symbol": "000001.SZ",
        "title": "趋势延续",
        "direction": "long",
        "hypothesis": "价格站稳趋势线后有继续扩张可能",
        "evidence": ["放量突破"],
        "counter_evidence": ["跌回突破位"],
        "idempotency_key": "thesis-create-1",
    })


def test_schema_and_full_research_chain_are_transactional(tmp_path):
    store = TransactionStore(tmp_path)
    thesis = _thesis(store)
    plan = store.create_plan({
        "thesis_id": thesis["id"],
        "symbol": thesis["symbol"],
        "direction": "buy",
        "entry_price": 10,
        "stop_price": 9,
        "target_price": 12,
        "position_pct": 10,
        "candidate_source": {"strategy_id": "sequoia_x", "candidate_id": "c1"},
        "idempotency_key": "plan-create-1",
    })
    gate = store.create_decision({"plan_id": plan["id"], "idempotency_key": "gate-create-1"})
    store.create_journal({
        "plan_id": plan["id"],
        "decision_id": gate["id"],
        "kind": "note",
        "content": "等待下一个交易日确认",
        "idempotency_key": "journal-create-1",
    })

    approved = store.transition_decision(
        gate["id"],
        {"status": "approved", "expected_revision": 1, "idempotency_key": "gate-approve-1"},
    )
    assert approved["status"] == "approved"
    assert store.summary() == {
        "contract_version": "1.0",
        "theses": 1,
        "plans": 1,
        "decisions": 1,
        "journal": 1,
        "audit_events": 5,
    }


def test_idempotency_replays_without_duplicate_audit(tmp_path):
    store = TransactionStore(tmp_path)
    first = _thesis(store)
    replay = store.create_thesis({
        "symbol": "SHOULD_NOT_BE_WRITTEN",
        "title": "replay",
        "direction": "short",
        "hypothesis": "replay",
        "idempotency_key": "thesis-create-1",
    })
    assert replay == first
    assert len(store.list_theses()) == 1
    assert len(store.list_audit()) == 1


def test_revision_conflict_and_invalid_links_fail_closed(tmp_path):
    store = TransactionStore(tmp_path)
    thesis = _thesis(store)
    with pytest.raises(TransactionValidationError, match="交易计划不存在"):
        store.create_decision({"plan_id": "missing", "idempotency_key": "bad-gate"})

    with pytest.raises(TransactionConflictError, match="revision 冲突"):
        store.update_thesis(
            thesis["id"],
            {"title": "stale", "expected_revision": 2, "idempotency_key": "stale-update"},
        )


def test_expired_pending_gate_is_read_as_expired(tmp_path):
    store = TransactionStore(tmp_path)
    thesis = _thesis(store)
    plan = store.create_plan({"thesis_id": thesis["id"], "symbol": thesis["symbol"], "idempotency_key": "plan-expire"})
    store.create_decision({
        "plan_id": plan["id"],
        "expires_at": "2020-01-01T00:00:00+00:00",
        "idempotency_key": "gate-expire",
    })
    assert store.list_decisions()[0]["status"] == "expired"


def test_decision_gate_rejects_invalid_transition(tmp_path):
    store = TransactionStore(tmp_path)
    thesis = _thesis(store)
    plan = store.create_plan({"thesis_id": thesis["id"], "symbol": thesis["symbol"], "direction": "buy"})
    gate = store.create_decision({"plan_id": plan["id"]})
    store.transition_decision(gate["id"], {"status": "approved"})
    with pytest.raises(TransactionValidationError, match="不可从 approved 转为 rejected"):
        store.transition_decision(gate["id"], {"status": "rejected"})


def test_sqlite_file_is_closed_after_reads(tmp_path):
    store = TransactionStore(tmp_path)
    _thesis(store)
    store.list_theses()
    store.summary()
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
