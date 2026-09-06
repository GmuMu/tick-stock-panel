from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.trading_research import router


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    return TestClient(app)


def test_research_api_chain_and_idempotent_create(tmp_path):
    client = _client(tmp_path)
    thesis_payload = {
        "symbol": "000001.SZ",
        "title": "趋势延续",
        "hypothesis": "突破后维持强势",
        "evidence": ["放量"],
        "counter_evidence": ["跌破突破位"],
        "idempotency_key": "api-thesis-1",
    }
    first = client.post("/api/trading-research/theses", json=thesis_payload)
    assert first.status_code == 200
    replay = client.post(
        "/api/trading-research/theses",
        json={**thesis_payload, "symbol": "SHOULD_NOT_WRITE"},
    )
    assert replay.status_code == 200
    assert replay.json()["item"]["id"] == first.json()["item"]["id"]

    thesis_id = first.json()["item"]["id"]
    plan = client.post(
        "/api/trading-research/plans",
        json={"thesis_id": thesis_id, "symbol": "000001.SZ", "entry_price": 10},
    )
    assert plan.status_code == 200
    plan_id = plan.json()["item"]["id"]
    gate = client.post("/api/trading-research/decisions", json={"plan_id": plan_id})
    assert gate.status_code == 200
    gate_id = gate.json()["item"]["id"]
    transition = client.post(
        f"/api/trading-research/decisions/{gate_id}/transition",
        json={"status": "approved", "expected_revision": 1},
    )
    assert transition.status_code == 200
    journal = client.post(
        "/api/trading-research/journal",
        json={"plan_id": plan_id, "decision_id": gate_id, "kind": "review", "content": "通过"},
    )
    assert journal.status_code == 200
    assert client.get("/api/trading-research/summary").json()["audit_events"] == 5


def test_api_returns_conflict_for_stale_revision(tmp_path):
    client = _client(tmp_path)
    thesis = client.post(
        "/api/trading-research/theses",
        json={"symbol": "A", "title": "T", "hypothesis": "H"},
    ).json()["item"]
    response = client.patch(
        f"/api/trading-research/theses/{thesis['id']}",
        json={"title": "stale", "expected_revision": 9},
    )
    assert response.status_code == 409
