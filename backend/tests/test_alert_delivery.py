from __future__ import annotations

from concurrent.futures import Executor

from app.services import alert_delivery, webhook_adapter


class ImmediateExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        fn(*args, **kwargs)
        return None


def _event() -> dict:
    return {
        "ts": 1000,
        "rule_id": "r1",
        "source": "resonance",
        "type": "resonance",
        "symbol": "A",
        "message": "共振触发",
        "alert_rule": {"revision": 3},
    }


def test_delivery_records_queued_and_sent_independently(tmp_path):
    key = alert_delivery.submit(
        tmp_path,
        _event(),
        "feishu",
        lambda *_args: True,
        ("url", "title", "body", "secret"),
        ImmediateExecutor(),
    )
    rows = alert_delivery.list_recent(tmp_path)
    assert key
    assert {row["status"] for row in rows} == {"queued", "sent"}
    assert all(row["channel"] == "feishu" for row in rows)
    assert all(row["rule_revision"] == 3 for row in rows)
    assert rows[0]["queued_at"] is not None


def test_delivery_records_failure_and_skipped_reason(tmp_path):
    alert_delivery.submit(
        tmp_path,
        _event(),
        "wecom",
        lambda *_args: False,
        ("url", "title", "body"),
        ImmediateExecutor(),
    )
    alert_delivery.record_skipped(tmp_path, _event(), "system", "系统通知未启用")
    rows = alert_delivery.list_recent(tmp_path)
    statuses = {(row["channel"], row["status"]): row for row in rows}
    assert statuses[("wecom", "failed")]["error"] == "sender returned false"
    assert statuses[("system", "skipped")]["error"] == "系统通知未启用"


def test_wecom_retries_network_and_5xx_but_not_4xx(monkeypatch):
    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self.text = "failure"
            self._payload = payload

        def json(self):
            return self._payload

    calls = []
    responses = [Response(503), Response(200, {"errcode": 0})]

    def post(*_args, **_kwargs):
        calls.append(True)
        return responses.pop(0)

    monkeypatch.setattr("httpx.post", post)
    monkeypatch.setattr("time.sleep", lambda *_args: None)
    assert webhook_adapter.send_wecom("wecom-key-12345678901234567890", "t", "b") is True
    assert len(calls) == 2

    calls.clear()
    responses.extend([Response(400)])
    assert webhook_adapter.send_wecom("wecom-key-12345678901234567890", "t", "b") is False
    assert len(calls) == 1
