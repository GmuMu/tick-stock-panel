from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.broker import router
from app.broker.protocol import BrokerSafetyError, OrderRequest
from app.broker.reconcile import ReconcileService
from app.broker.runtime import BrokerRuntime


def test_mock_broker_is_explicitly_network_free_and_quote_quality_is_provenanced(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    assert runtime.status()["network_enabled"] is False
    assert runtime.status()["real_order_enabled"] is False
    assert runtime.quote("000001.SZ")["quality"] == "UNAVAILABLE"

    runtime.connect("mock", "HUMAN_CONFIRM")
    quote = runtime.seed_quote("000001.SZ", 10.0, bid_price=9.99, ask_price=10.01)
    assert quote["quality"] == "FRESH"
    assert quote["provenance"]["adapter"] == "mock"


def test_human_confirm_live_shadow_and_auto_are_fail_closed(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    runtime.connect("mock", "HUMAN_CONFIRM")
    order = OrderRequest("client-1", "000001.SZ", "buy", 100, 10.0)
    with pytest.raises(BrokerSafetyError, match="人工确认"):
        runtime.submit(order)

    submitted = runtime.submit(OrderRequest(**{**order.to_dict(), "human_confirmed": True}))
    assert submitted["status"] == "accepted"

    runtime.set_mode("LIVE_SHADOW")
    shadow_order = runtime.submit(OrderRequest("client-2", "000001.SZ", "buy", 100, 10.0))
    assert shadow_order["provenance"]["simulation"] is True

    with pytest.raises(BrokerSafetyError, match="AUTO"):
        runtime.set_mode("AUTO")


def test_kill_switch_blocks_order_but_reset_restores_confirmed_mock_flow(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    runtime.connect("mock", "HUMAN_CONFIRM")
    runtime.trip_kill_switch("test stop")
    with pytest.raises(BrokerSafetyError, match="Kill Switch"):
        runtime.submit(OrderRequest("client-1", "000001.SZ", "buy", 100, 10.0, human_confirmed=True))
    runtime.reset_kill_switch()
    assert runtime.submit(OrderRequest("client-1", "000001.SZ", "buy", 100, 10.0, human_confirmed=True))["status"] == "accepted"


def test_qmt_selection_is_blocked_without_vendor_sdk(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    status = runtime.connect("qmt", "HUMAN_CONFIRM")
    assert status["connection"] == "blocked"
    assert status["sdk_configured"] is False
    assert status["real_order_enabled"] is False
    quote = runtime.quote("000001.SZ")
    assert quote["quality"] == "UNAVAILABLE"
    assert quote["provenance"]["sdk_configured"] is False


def test_reconcile_reports_match_and_drift_without_mutating_state():
    service = ReconcileService()
    base = {"quality": "FRESH", "cash": 100.0, "equity": 100.0, "orders": [], "fills": [], "positions": []}
    matched = service.compare(base, base, checked_at="2026-09-06T10:00:00+00:00")
    assert matched.status == "matched"
    drift = service.compare(base, {**base, "cash": 99.0}, checked_at="2026-09-06T10:00:00+00:00")
    assert drift.status == "mismatched"
    assert drift.mismatches[0]["code"] == "VALUE_MISMATCH"


def test_broker_api_exposes_safety_quote_order_and_reconcile(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    client = TestClient(app)

    assert client.post("/api/broker/connect", json={"adapter": "mock", "mode": "HUMAN_CONFIRM"}).status_code == 200
    seeded = client.post("/api/broker/quote/seed", json={"symbol": "000001.SZ", "last_price": 10}).json()
    assert seeded["quality"] == "FRESH"
    assert client.get("/api/broker/quote?symbol=000001.SZ").json()["quality"] == "FRESH"

    blocked = client.post("/api/broker/orders", json={
        "client_order_id": "api-1", "symbol": "000001.SZ", "side": "buy",
        "quantity": 100, "limit_price": 10,
    })
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "HUMAN_CONFIRM_REQUIRED"
    payload = {
        "client_order_id": "api-1", "symbol": "000001.SZ", "side": "buy",
        "quantity": 100, "limit_price": 10, "order_type": "limit",
        "human_confirmed": False, "metadata": {},
    }
    confirmation = client.post("/api/broker/confirmations", json={
        "action": "broker.submit_order", "payload": payload,
    }).json()
    client.post(f"/api/broker/confirmations/{confirmation['id']}/decision", json={"status": "approved"})
    accepted = client.post("/api/broker/orders", json={**payload, "confirmation_id": confirmation["id"]})
    assert accepted.status_code == 200
    order_id = accepted.json()["item"]["id"]
    assert client.post(f"/api/broker/orders/{order_id}/fills", json={"quantity": 100, "price": 10}).status_code == 200
    report = client.post("/api/broker/reconcile", json={}).json()
    assert report["status"] == "matched"
