"""Versioned alert-rule snapshots shared by persistence, evaluation and delivery.

The monitor engine still owns matching and cooldown.  This module only defines
the stable rule metadata that is copied into an alert event so later delivery
audits can explain which rule revision produced it.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ALERT_RULE_CONTRACT_VERSION = "1.0"

# Runtime-only fields must not become part of an immutable rule snapshot.
_RUNTIME_FIELDS = {"runtime_warning", "watch_scope"}


def build_alert_rule_snapshot(rule: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy of the normalized rule configuration."""
    snapshot = {
        key: deepcopy(value)
        for key, value in rule.items()
        if key not in _RUNTIME_FIELDS
    }
    snapshot.setdefault("alert_rule_contract_version", ALERT_RULE_CONTRACT_VERSION)
    snapshot.setdefault("revision", 1)
    snapshot.setdefault("updated_at", snapshot.get("created_at"))
    return snapshot


def next_revision(previous: dict[str, Any] | None) -> int:
    """Return the next positive revision for a rule being saved."""
    if not previous:
        return 1
    try:
        return max(1, int(previous.get("revision", 1))) + 1
    except (TypeError, ValueError):
        return 2
