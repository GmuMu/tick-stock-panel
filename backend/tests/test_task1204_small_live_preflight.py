from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.broker import router
from app.broker.runtime import BrokerRuntime
from app.services.small_live_preflight import SmallLivePreflightService


def _ready_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        status=lambda: {
            "adapter": "qmt",
            "connection": "connected",
            "mode": "HUMAN_CONFIRM",
            "agent": {
                "pid": 123,
                "transport": "stdio-jsonl",
                "vendor_sdk_loaded": True,
                "isolated": True,
            },
            "sdk_configured": True,
            "network_enabled": True,
            "real_order_enabled": False,
            "kill_switch": False,
        },
        quote=lambda symbol: {
            "symbol": symbol,
            "quality": "FRESH",
            "as_of": "2026-09-06T10:00:00+08:00",
            "provenance": {"adapter": "qmt", "network": True},
        },
        account=lambda: {
            "account_id": "qmt-paper-account",
            "quality": "FRESH",
            "as_of": "2026-09-06T10:00:00+08:00",
        },
        list_reconciliations=lambda limit=1: [
            {
                "report": {
                    "status": "matched",
                    "broker_snapshot": {"quality": "FRESH"},
                },
            }
        ],
    )


def test_small_live_preflight_is_blocked_by_current_mock_only_runtime(tmp_path):
    runtime = BrokerRuntime(tmp_path)
    result = SmallLivePreflightService(runtime).run("000001.SZ")

    assert result["status"] == "BLOCKED"
    assert result["activation_allowed"] is False
    assert any(item["code"] == "QMT_SDK_UNAVAILABLE" for item in result["blocking_reasons"])
    assert any(item["code"] == "ACCOUNT_SNAPSHOT_UNAVAILABLE" for item in result["blocking_reasons"])
    assert result["real_order_enabled"] is False


def test_small_live_preflight_reaches_manual_review_only_after_external_conditions(
    tmp_path,
):
    result = SmallLivePreflightService(_ready_runtime(), tmp_path).run("000001.SZ")

    assert result["status"] == "READY_FOR_REVIEW"
    assert result["activation_allowed"] is False
    assert result["blocking_reasons"] == []
    assert any(item["code"] == "LIVE_APPROVAL_REQUIRED" for item in result["manual_review"])
    assert any(item["code"] == "SMALL_LIVE_LIMITS_REQUIRED" for item in result["manual_review"])


def test_small_live_preflight_api_persists_redacted_audit_result(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/broker/small-live/preflight",
        json={"symbol": "000001.SZ"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["activation_allowed"] is False
    assert client.get("/api/broker/small-live/preflights").json()["items"][0]["id"] == body["id"]
    assert "account_id" not in body["blocking_reasons"][0]
