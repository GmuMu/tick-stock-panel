"""Versioned watch-scope contract and invalidation semantics."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import polars as pl
import pytest

from app.api import monitor_rules as monitor_rules_api
from app.config import settings
from app.services import watchlist
from app.strategy import monitor_rules
from app.strategy.monitor import MonitorRuleEngine
from app.strategy.watch_scope import (
    WATCH_SCOPE_CONTRACT_VERSION,
    resolve_watch_scope,
)


def _rule(**overrides) -> dict:
    rule = {
        "id": "scope_rule",
        "name": "作用域测试",
        "type": "signal",
        "asset_type": "stock",
        "scope": "symbols",
        "symbols": ["B", "A", "A"],
        "conditions": [{"field": "rsi_14", "op": "<", "value": 100}],
        "logic": "and",
        "cooldown_seconds": 3600,
        "enabled": True,
    }
    rule.update(overrides)
    return monitor_rules.normalize(rule)


def _df() -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["A", "B", "C"],
        "close": [10.0, 20.0, 30.0],
        "change_pct": [0.01, 0.02, 0.03],
        "rsi_14": [40.0, 50.0, 60.0],
    })


def test_scope_contract_normalizes_static_and_all_scopes():
    static = resolve_watch_scope(_rule())
    assert static.contract_version == WATCH_SCOPE_CONTRACT_VERSION
    assert static.status == "active"
    assert static.symbols == ("A", "B")
    assert static.source == "rule"
    assert static.to_dict()["symbols"] == ["A", "B"]

    market = resolve_watch_scope(_rule(scope="all", symbols=[]))
    assert market.status == "active"
    assert market.scope == "all"
    assert market.source == "market_universe"
    assert market.symbols == ()


def test_scope_contract_fails_closed_for_empty_or_unknown_scope():
    empty = resolve_watch_scope(_rule(symbols=[]))
    assert empty.status == "invalid"
    assert empty.reason_code == "EMPTY_SYMBOLS"

    unknown = resolve_watch_scope(_rule(scope="sector", symbols=[]))
    assert unknown.status == "invalid"
    assert unknown.reason_code == "UNSUPPORTED_SCOPE"

    with pytest.raises(ValueError, match="scope_contract_version"):
        monitor_rules.validate(_rule(scope_contract_version="2.0"))


def test_group_scope_version_tracks_membership_and_missing_group(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _, group = watchlist.create_group("核心池")
    rule = _rule(
        scope="watchlist_group",
        symbols=[],
        group_id=group["id"],
    )

    first = resolve_watch_scope(rule)
    assert first.status == "empty"
    assert first.reason_code == "EMPTY_GROUP"
    watchlist.add("A", group_id=group["id"])
    second = resolve_watch_scope(rule)
    assert second.status == "active"
    assert second.symbols == ("A",)
    assert second.source_revision is not None
    assert second.scope_version != first.scope_version
    assert resolve_watch_scope(rule).scope_version == second.scope_version

    watchlist.delete_group(group["id"])
    missing = resolve_watch_scope(rule)
    assert missing.status == "invalid"
    assert missing.reason_code == "GROUP_NOT_FOUND"
    assert missing.symbols == ()


def test_group_scope_invalidation_only_clears_removed_symbols(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _, group = watchlist.create_group("核心池")
    watchlist.add("A", group_id=group["id"])
    rule = _rule(
        scope="watchlist_group",
        symbols=[],
        group_id=group["id"],
    )

    engine = MonitorRuleEngine()
    engine.set_rules([rule])
    assert {event["symbol"] for event in engine.evaluate(_df())} == {"A"}
    assert engine.evaluate(_df()) == []

    watchlist.add("B", group_id=group["id"])
    events = engine.evaluate(_df())
    assert {event["symbol"] for event in events} == {"B"}
    assert events[0]["watch_scope"]["symbols"] == ["A", "B"]
    assert events[0]["watch_scope"]["source_revision"] is not None

    watchlist.remove_from_group("A", group["id"])
    assert engine.evaluate(_df()) == []
    watchlist.add_to_group("A", group["id"])
    events = engine.evaluate(_df())
    assert {event["symbol"] for event in events} == {"A"}


def test_api_exposes_scope_snapshot_and_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _, group = watchlist.create_group("核心池")
    req = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                repo=MagicMock(store=SimpleNamespace(data_dir=tmp_path)),
            ),
        ),
    )
    req.app.state.repo.resolve_asset_type.return_value = "stock"
    model = monitor_rules_api.RuleModel(**_rule(
        scope="watchlist_group",
        symbols=[],
        group_id=group["id"],
    ))

    response = monitor_rules_api.save_rule(model, req)
    assert response["watch_scope"]["contract_version"] == WATCH_SCOPE_CONTRACT_VERSION
    listed = monitor_rules_api.list_rules(req)
    saved = next(rule for rule in listed["rules"] if rule["id"] == "scope_rule")
    assert saved["watch_scope"]["status"] == "empty"
