from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import secrets_store
from app.api.ops import router as ops_router
from app.broker.agent import QmtAgentCore
from app.broker.mock import MockBroker
from app.broker.protocol import BrokerError
from app.observability import RequestMetrics, redact_text
from app.services.backup import BackupError, create_backup, restore_backup, validate_backup


def test_backup_manifest_checksum_and_confirmed_restore(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "user_data").mkdir(parents=True)
    (data_dir / "user_data" / "preferences.json").write_text('{"version": 1}', encoding="utf-8")
    created = create_backup(data_dir, label="test")
    archive = tmp_path / "data" / "user_data" / "backups" / created["filename"]

    checked = validate_backup(archive)
    assert checked["valid"] is True
    assert checked["manifest"]["file_count"] == 1
    assert restore_backup(data_dir, archive)["dry_run"] is True

    (data_dir / "user_data" / "preferences.json").write_text('{"version": 2}', encoding="utf-8")
    restored = restore_backup(data_dir, archive, confirm=True, dry_run=False)
    assert restored["restored"] is True
    assert json.loads((data_dir / "user_data" / "preferences.json").read_text()) == {"version": 1}
    assert restored["rollback_dir"]


def test_restore_rejects_archive_outside_configured_backup_directory(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    external = tmp_path / "external.zip"
    external.write_bytes(b"not a backup")
    with pytest.raises(BackupError):
        restore_backup(data_dir, external, confirm=True, dry_run=False)


def test_metrics_are_bounded_and_secret_redaction_is_stable():
    metrics = RequestMetrics(max_routes=1)
    metrics.observe("GET", "/api/items/123", 200, 4.0, "cid-1")
    metrics.observe("POST", "/api/items/456", 500, 8.0, "cid-2")
    snapshot = metrics.snapshot()
    assert snapshot["requests_total"] == 2
    assert snapshot["server_errors"] == 1
    assert "OTHER" in snapshot["routes"]
    assert "api_key=[REDACTED]" in redact_text("api_key=super-secret")
    assert "super-secret" not in redact_text("Bearer super-secret")


def test_secret_rotation_returns_metadata_without_secret_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    item = secrets_store.rotate("tickflow_api_key", "first-secret")
    assert item["version"] == 1
    assert "first-secret" not in json.dumps(item)
    second = secrets_store.rotate("tickflow_api_key", "second-secret")
    assert second["version"] == 2
    assert secrets_store.get_tickflow_key() == "second-secret"
    assert secrets_store.list_metadata()[0]["masked"] != "second-secret"


def test_external_agent_defaults_to_read_only():
    core = QmtAgentCore(MockBroker())
    with pytest.raises(BrokerError) as exc:
        core.dispatch({
            "action": "submit_order",
            "order": {
                "client_order_id": "agent-1",
                "symbol": "000001.SZ",
                "side": "buy",
                "quantity": 100,
                "limit_price": 10,
            },
        })
    assert exc.value.code == "AGENT_PERMISSION_DENIED"


def test_ops_api_exposes_metrics_backups_and_secret_metadata(tmp_path):
    app = FastAPI()
    app.include_router(ops_router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    client = TestClient(app)

    correlation = client.get("/api/ops/metrics", headers={"X-Correlation-ID": "test-cid"})
    assert correlation.status_code == 200
    assert correlation.json()["requests_total"] >= 0

    created = client.post("/api/ops/backups", json={"label": "api"})
    assert created.status_code == 200
    listed = client.get("/api/ops/backups")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["valid"] is True

    rotated = client.post(
        "/api/ops/security/secrets/rotate",
        json={"field": "ai_api_key", "value": "api-secret"},
    )
    assert rotated.status_code == 200
    assert "api-secret" not in rotated.text
