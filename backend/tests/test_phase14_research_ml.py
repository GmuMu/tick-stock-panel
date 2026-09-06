from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.research import router
from app.broker.runtime import BrokerRuntime
from app.services.transaction_store import TransactionStore


def _client(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    app.state.transaction_store = TransactionStore(tmp_path)
    return TestClient(app), app


def test_quantmind_adapter_is_local_and_traceable(tmp_path):
    client, _ = _client(tmp_path)
    adapters = client.get("/api/research/adapters").json()["items"]
    assert adapters[0]["network_enabled"] is False
    assert adapters[0]["trading_enabled"] is False

    saved = client.post("/api/research/quantmind", json={
        "artifact_id": "qm-1",
        "symbol": "000001.SZ",
        "as_of": "2026-09-06",
        "thesis": "趋势保持",
        "score": 0.82,
        "features": {"rps": 91},
    })
    assert saved.status_code == 200
    item = saved.json()["item"]
    assert item["provider"] == "quantmind"
    assert item["provenance"]["adapter"] == "local_file_handoff"
    assert len(item["fingerprint"]) == 24
    assert len(item["provenance"]) > 0

    listed = client.get("/api/research/quantmind").json()["items"]
    assert listed[0]["artifact_id"] == "qm-1"


def test_ml_signal_enters_unified_signal_only(tmp_path):
    client, app = _client(tmp_path)
    response = client.post("/api/research/ml/signals", json={
        "model_version": "model-v1",
        "symbol": "000001.SZ",
        "as_of": "2026-09-06",
        "action": "entry",
        "kind": "entry",
        "score": 0.91,
        "features": {"momentum": 1.2},
        "idempotency_key": "ml-signal-1",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["source"] == "ml"
    assert body["item"]["provenance"]["research_only"] is True
    assert body["orders_created"] == 0
    assert body["broker_calls"] == 0
    assert app.state.transaction_store.list_orders() == []

    runtime = BrokerRuntime(tmp_path)
    assert runtime.status()["real_order_enabled"] is False
