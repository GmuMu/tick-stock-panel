from __future__ import annotations

import json
import sys

import pytest

from app.broker.external_agent import ExternalAgentConfig, ExternalQmtAgentClient
from app.broker.protocol import BrokerError, BrokerSafetyError, OrderRequest
from app.broker.runtime import BrokerRuntime

FAKE_AGENT = """
import json
import sys

for line in sys.stdin:
    command = json.loads(line)
    action = command.get("action")
    if action in {"connect", "status"}:
        result = {
            "adapter": "qmt",
            "connection": "connected",
            "mode": "HUMAN_CONFIRM",
            "agent_pid": 123,
            "sdk_configured": True,
            "network_enabled": True,
            "real_order_enabled": True,
            "kill_switch": False,
        }
    elif action == "quote":
        result = {
            "symbol": command["symbol"],
            "last_price": 10.0,
            "bid_price": 9.99,
            "ask_price": 10.01,
            "bid_quantity": 100.0,
            "ask_quantity": 100.0,
            "as_of": "2026-09-06T10:00:00+08:00",
            "quality": "FRESH",
            "provenance": {"adapter": "qmt", "network": True, "simulation": False},
        }
    elif action == "account":
        result = {
            "account_id": "test-account",
            "cash": 100000.0,
            "equity": 100000.0,
            "available_cash": 100000.0,
            "as_of": "2026-09-06T10:00:00+08:00",
            "quality": "FRESH",
            "provenance": {"adapter": "qmt", "network": True, "simulation": False},
            "positions": [],
        }
    elif action in {"orders", "fills"}:
        result = []
    elif action == "submit_order":
        order = command["order"]
        result = {
            "id": "qmt-order-1",
            "client_order_id": order["client_order_id"],
            "symbol": order["symbol"],
            "side": order["side"],
            "quantity": order["quantity"],
            "limit_price": order["limit_price"],
            "order_type": "limit",
            "status": "accepted",
            "filled_quantity": 0.0,
            "avg_fill_price": None,
            "created_at": "2026-09-06T10:00:00+08:00",
            "updated_at": "2026-09-06T10:00:00+08:00",
            "provenance": {"adapter": "qmt", "network": True, "simulation": False},
        }
    else:
        result = {}
    print(json.dumps({"id": command.get("id"), "ok": True, "result": result}), flush=True)
"""


def _command() -> list[str]:
    return [sys.executable, "-u", "-c", FAKE_AGENT]


def test_external_agent_uses_json_array_and_round_trips_request(tmp_path):
    config = ExternalAgentConfig(_command(), timeout_seconds=2)
    client = ExternalQmtAgentClient(config)
    try:
        response = client.dispatch({"action": "status"})
        assert response["result"]["adapter"] == "qmt"
    finally:
        client.close()


def test_external_agent_rejects_shell_string_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("QMT_AGENT_COMMAND", "python -m app.broker.qmt_vendor_agent")
    with pytest.raises(BrokerError) as exc:
        ExternalAgentConfig.from_environment()
    assert exc.value.code == "QMT_AGENT_CONFIG_INVALID"


def test_runtime_can_read_external_qmt_but_real_order_gate_stays_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    monkeypatch.setenv("QMT_AGENT_COMMAND", json.dumps(_command()))
    monkeypatch.setenv("QMT_LIVE_ORDER_ENABLED", "true")
    runtime = BrokerRuntime(tmp_path)
    try:
        status = runtime.connect("qmt", "HUMAN_CONFIRM")
        assert status["connection"] == "connected"
        assert status["sdk_configured"] is True
        assert status["network_enabled"] is True
        assert status["real_order_enabled"] is False
        assert runtime.quote("000001.SZ")["quality"] == "FRESH"
        assert runtime.account()["quality"] == "FRESH"
        with pytest.raises(BrokerSafetyError) as exc:
            runtime.submit(OrderRequest("live-1", "000001.SZ", "buy", 100, 10, human_confirmed=True))
        assert exc.value.code == "QMT_LIVE_DISABLED"

        runtime.reconcile_snapshot()
        preflight = runtime.run_small_live_preflight("000001.SZ")
        assert preflight["status"] == "READY_FOR_REVIEW"
        confirmation = runtime.request_confirmation(
            "broker.enable_small_live",
            {"preflight_id": preflight["id"], "symbol": "000001.SZ"},
        )
        runtime.decide_confirmation(confirmation["id"], "approved", "tester")
        activated = runtime.activate_small_live(preflight["id"], confirmation["id"])
        assert activated["real_order_enabled"] is True
        submitted = runtime.submit(
            OrderRequest("live-1", "000001.SZ", "buy", 100, 10, human_confirmed=True),
        )
        assert submitted["provenance"]["simulation"] is False
    finally:
        runtime.close()
