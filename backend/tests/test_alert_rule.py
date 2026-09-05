from __future__ import annotations

from app.strategy import monitor_rules
from app.strategy.alert_rule import (
    ALERT_RULE_CONTRACT_VERSION,
    build_alert_rule_snapshot,
    next_revision,
)


def test_legacy_rule_normalizes_to_versioned_alert_rule_snapshot():
    rule = monitor_rules.normalize({
        "id": "legacy_rule",
        "name": "旧规则",
        "type": "price",
        "scope": "symbols",
        "symbols": ["A"],
        "conditions": [{"field": "close", "op": ">=", "value": 10}],
    })

    assert rule["alert_rule_contract_version"] == ALERT_RULE_CONTRACT_VERSION
    assert rule["revision"] == 1
    assert next_revision(rule) == 2

    rule["runtime_warning"] = "仅运行时字段"
    rule["watch_scope"] = {"status": "active"}
    snapshot = build_alert_rule_snapshot(rule)
    assert snapshot["id"] == "legacy_rule"
    assert snapshot["revision"] == 1
    assert "runtime_warning" not in snapshot
    assert "watch_scope" not in snapshot


def test_invalid_legacy_revision_is_repaired_before_validation():
    rule = monitor_rules.normalize({
        "id": "legacy_rule",
        "name": "旧规则",
        "type": "price",
        "scope": "symbols",
        "symbols": ["A"],
        "conditions": [{"field": "close", "op": ">=", "value": 10}],
        "revision": "old",
    })
    assert rule["revision"] == 1
    monitor_rules.validate(rule)
