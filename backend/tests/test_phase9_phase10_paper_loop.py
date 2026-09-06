from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.paper_trading import router
from app.services.transaction_store import TransactionStore
from app.strategy.unified_signal import adapt_signal


def _snapshot(entry: float = 10.0) -> dict:
    return {
        "as_of": "2026-09-07",
        "market_session": {"trading_day": True, "is_continuous": True, "phase": "morning"},
        "data_quality": {"status": "FRESH", "usable": True},
        "quote": {"last_price": entry, "prev_close": entry},
    }


def _approved_plan(store: TransactionStore, *, symbol: str = "000001.SZ", side: str = "buy"):
    plan = store.create_plan({
        "symbol": symbol,
        "direction": side,
        "entry_price": 10,
        "stop_price": 9 if side == "buy" else 11,
        "target_price": 12 if side == "buy" else 8,
        "position_pct": 10,
        "quantity": 100,
        "status": "active",
        "idempotency_key": f"plan-{symbol}-{side}",
    })
    gate = store.create_decision({"plan_id": plan["id"], "idempotency_key": f"gate-{plan['id']}"})
    store.transition_decision(gate["id"], {"status": "approved", "expected_revision": 1})
    return plan


def test_unified_signal_is_deterministic_and_persisted_once(tmp_path):
    store = TransactionStore(tmp_path)
    signal = adapt_signal(
        source="strategy", source_id="sequoia_x", symbol="000001.SZ", as_of="2026-09-07", action="entry", kind="entry",
    )
    first = store.create_signal({**signal.to_dict(), "idempotency_key": "signal-once"})
    replay = store.create_signal({**signal.to_dict(), "symbol": "SHOULD_NOT_WRITE", "idempotency_key": "signal-once"})
    assert replay == first
    assert len(store.list_signals()) == 1


def test_risk_fails_closed_without_fresh_data_or_approval(tmp_path):
    store = TransactionStore(tmp_path)
    plan = store.create_plan({
        "symbol": "000001.SZ", "direction": "buy", "entry_price": 10,
        "position_pct": 10, "quantity": 100, "status": "active",
    })
    result = store.evaluate_risk(plan["id"], {"quote": {"last_price": 10}, "data_quality": {"status": "STALE", "usable": False}}, idempotency_key="risk-reject")
    codes = {item["code"] for item in result["risk"]["reasons"]}
    assert result["accepted"] is False
    assert {"decision_not_approved", "data_quality_not_fresh", "market_not_continuous"} <= codes
    assert store.list_orders() == []


def test_paper_order_fill_outbox_and_t_plus_one_projection(tmp_path):
    store = TransactionStore(tmp_path)
    plan = _approved_plan(store)
    signal = adapt_signal(source="manual", source_id="manual-1", symbol=plan["symbol"], as_of="2026-09-07", action="entry", kind="entry")
    stored_signal = store.create_signal({**signal.to_dict(), "idempotency_key": "paper-signal"})
    submitted = store.submit_paper_order(
        plan["id"], _snapshot(), signal_id=stored_signal["id"],
        client_order_id="client-1", idempotency_key="order-once",
    )
    assert submitted["accepted"] is True
    order = submitted["order"]
    filled = store.simulate_fill(order["id"], {"quantity": 100, "price": 10, "trade_date": "2026-09-07"}, idempotency_key="fill-once")
    assert filled["order"]["status"] == "filled"
    assert filled["position"]["quantity"] == 100
    assert filled["position"]["available_quantity"] == 0
    assert len(store.list_outbox("pending")) == 2
    assert store.settle_positions("2026-09-08") == 1
    assert store.list_positions()[0]["available_quantity"] == 100


def test_sell_is_rejected_when_t_plus_one_position_is_unavailable(tmp_path):
    store = TransactionStore(tmp_path)
    buy_plan = _approved_plan(store)
    order = store.submit_paper_order(buy_plan["id"], _snapshot(), idempotency_key="buy-order")["order"]
    store.simulate_fill(order["id"], {"quantity": 100, "price": 10, "trade_date": "2026-09-07"}, idempotency_key="buy-fill")
    sell_plan = _approved_plan(store, side="sell")
    rejected = store.submit_paper_order(sell_plan["id"], _snapshot(), idempotency_key="sell-order")
    assert rejected["accepted"] is False
    assert any(item["code"] == "position_unavailable" for item in rejected["risk"]["reasons"])


def test_oms_transition_enforces_revision_and_terminal_states(tmp_path):
    store = TransactionStore(tmp_path)
    plan = _approved_plan(store)
    order = store.submit_paper_order(plan["id"], _snapshot(), idempotency_key="cancel-order")["order"]
    cancelled = store.transition_order(
        order["id"], "cancelled", expected_revision=1, reason="paper test", idempotency_key="cancel-transition",
    )
    assert cancelled["status"] == "cancelled"
    try:
        store.transition_order(cancelled["id"], "filled", expected_revision=2)
    except ValueError as exc:
        assert "不可从 cancelled 转为 filled" in str(exc)
    else:
        raise AssertionError("terminal OMS state unexpectedly transitioned")


def test_outbox_retry_and_daily_review_are_auditable(tmp_path):
    store = TransactionStore(tmp_path)
    plan = _approved_plan(store)
    order = store.submit_paper_order(plan["id"], _snapshot(), idempotency_key="review-order")["order"]
    store.simulate_fill(order["id"], {"quantity": 100, "price": 10, "trade_date": "2026-09-07"}, idempotency_key="review-fill")
    event = store.list_outbox("pending")[0]
    updated = store.update_outbox(event["id"], "failed", "local consumer unavailable")
    assert updated["attempts"] == 1
    assert updated["last_error"] == "local consumer unavailable"
    review = store.create_daily_review("2026-09-07", "纸面闭环复核", idempotency_key="review-once")
    replay = store.create_daily_review("2026-09-07", "should not mutate", idempotency_key="review-once")
    assert replay == review
    assert review["snapshot"]["orders"]
    assert review["snapshot"]["fills"]
    assert store.paper_summary()["reviews"] == 1


def test_paper_trading_api_exposes_the_same_transactional_boundary(tmp_path):
    store = TransactionStore(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.transaction_store = store
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    client = TestClient(app)
    signal = client.post("/api/paper-trading/signals", json={
        "symbol": "000001.SZ", "as_of": "2026-09-07", "source": "manual",
        "source_id": "api-test", "kind": "entry", "action": "entry",
        "idempotency_key": "api-signal",
    })
    assert signal.status_code == 200
    plan = _approved_plan(store)
    submitted = client.post("/api/paper-trading/orders", json={
        "plan_id": plan["id"], "signal_id": signal.json()["item"]["id"],
        "snapshot": _snapshot(), "idempotency_key": "api-order",
    })
    assert submitted.status_code == 200
    order_id = submitted.json()["order"]["id"]
    transition = client.post(f"/api/paper-trading/orders/{order_id}/transition", json={
        "status": "cancelled", "expected_revision": 1, "reason": "api test",
    })
    assert transition.status_code == 200
    assert transition.json()["item"]["status"] == "cancelled"
