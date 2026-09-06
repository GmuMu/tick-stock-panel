from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.broker import router
from app.broker.protocol import OrderRequest
from app.broker.runtime import BrokerRuntime
from app.services.human_confirm import HumanConfirmError


def _order_payload(client_order_id: str = "confirm-1") -> dict:
    return {
        "client_order_id": client_order_id,
        "symbol": "000001.SZ",
        "side": "buy",
        "quantity": 100,
        "limit_price": 10,
        "order_type": "limit",
        "human_confirmed": False,
        "metadata": {},
    }


def test_human_confirmation_is_content_bound_and_one_time(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    payload = _order_payload()
    pending = runtime.request_confirmation("broker.submit_order", payload)
    approved = runtime.decide_confirmation(pending["id"], "approved", "tester")
    assert approved["status"] == "approved"
    runtime.confirmations.authorize(pending["id"], "broker.submit_order", payload)
    with pytest.raises(HumanConfirmError) as exc:
        runtime.confirmations.authorize(pending["id"], "broker.submit_order", payload)
    assert exc.value.code == "CONFIRM_NOT_APPROVED"


def test_human_confirmation_rejects_changed_order_payload(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    payload = _order_payload()
    pending = runtime.request_confirmation("broker.submit_order", payload)
    runtime.decide_confirmation(pending["id"], "approved")
    with pytest.raises(HumanConfirmError, match="内容与待执行订单不一致"):
        runtime.confirmations.authorize(
            pending["id"], "broker.submit_order", {**payload, "limit_price": 10.01},
        )


def test_account_reconcile_history_persists_match_and_drift(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    runtime.connect("mock", "LIVE_SHADOW")
    first = runtime.reconcile_snapshot()
    assert first["status"] == "matched"
    drift = runtime.reconcile_snapshot({"quality": "FRESH", "cash": 1.0, "equity": 1.0, "orders": [], "fills": [], "positions": []})
    assert drift["status"] == "mismatched"
    assert len(runtime.list_reconciliations()) == 2


def test_live_shadow_runs_full_mock_loop_without_real_side_effect(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    runtime.connect("mock", "LIVE_SHADOW")
    runtime.seed_quote("000001.SZ", 10)
    result = runtime.run_live_shadow(
        OrderRequest("shadow-1", "000001.SZ", "buy", 100, 10),
        simulate_fill=True,
    )
    assert result["status"] == "passed"
    assert [stage["name"] for stage in result["stages"]] == ["preflight", "quote", "submit", "fill", "reconcile"]
    assert result["real_order_submitted"] is False
    assert result["network_enabled"] is False


def test_phase12_api_requires_approved_confirmation_for_human_confirm(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    client = TestClient(app)
    client.post("/api/broker/connect", json={"adapter": "mock", "mode": "HUMAN_CONFIRM"})
    payload = _order_payload("api-confirm-1")
    confirmation = client.post("/api/broker/confirmations", json={
        "action": "broker.submit_order", "payload": payload,
    })
    assert confirmation.status_code == 200
    confirmation_id = confirmation.json()["id"]
    assert client.post(f"/api/broker/confirmations/{confirmation_id}/decision", json={"status": "approved"}).status_code == 200
    accepted = client.post("/api/broker/orders", json={**payload, "confirmation_id": confirmation_id})
    assert accepted.status_code == 200
    reused = client.post("/api/broker/orders", json={**payload, "confirmation_id": confirmation_id})
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "CONFIRM_NOT_APPROVED"
