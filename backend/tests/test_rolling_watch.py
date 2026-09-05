from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

from app.strategy import monitor_rules
from app.strategy.monitor import MonitorRuleEngine
from app.strategy.rolling_watch import (
    ROLLING_WATCH_CONTRACT_VERSION,
    advance_rolling_watch,
)


def _rule(**overrides) -> dict:
    rule = monitor_rules.normalize({
        "id": "rolling_rule",
        "name": "滚动观察",
        "type": "price",
        "scope": "symbols",
        "symbols": ["A"],
        "conditions": [{"field": "close", "op": ">=", "value": 10}],
        "logic": "and",
        "cooldown_seconds": 0,
        "rolling_window_seconds": 300,
        "enabled": True,
    })
    rule.update(overrides)
    return rule


def _df(close: float) -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["A"],
        "name": ["测试标的"],
        "close": [close],
        "change_pct": [0.01],
    })


def test_rolling_watch_contract_transitions_and_carries_metadata():
    first = advance_rolling_watch(
        None,
        rule_id="r",
        symbol="A",
        event_type="price",
        matched=True,
        now=100.0,
        window_seconds=300,
        cooldown_seconds=0,
    )
    assert first.should_trigger is True
    assert first.state.contract_version == ROLLING_WATCH_CONTRACT_VERSION
    assert first.state.status == "active"
    assert first.state.transition == "entered"
    assert first.state.observation_count == 1

    continued = advance_rolling_watch(
        first.state,
        rule_id="r",
        symbol="A",
        event_type="price",
        matched=True,
        now=101.0,
        window_seconds=300,
        cooldown_seconds=0,
    )
    assert continued.should_trigger is False
    assert continued.state.transition == "continued"
    assert continued.state.observation_count == 2

    exited = advance_rolling_watch(
        continued.state,
        rule_id="r",
        symbol="A",
        event_type="price",
        matched=False,
        now=102.0,
        window_seconds=300,
        cooldown_seconds=0,
    )
    assert exited.state.status == "inactive"
    assert exited.state.transition == "exited"


def test_rolling_watch_engine_dedupes_across_polls_and_rearms_after_exit():
    engine = MonitorRuleEngine()
    engine.set_rules([_rule()])

    with patch("app.strategy.monitor.time.time", side_effect=[100.0, 101.0, 102.0, 103.0]):
        first = engine.evaluate(_df(10.0))
        continued = engine.evaluate(_df(11.0))
        engine.evaluate(_df(9.0))
        reentered = engine.evaluate(_df(10.0))

    assert len(first) == 1
    assert first[0]["rolling_watch"]["transition"] == "entered"
    assert continued == []
    assert len(reentered) == 1
    assert reentered[0]["rolling_watch"]["transition"] == "entered"
    assert engine.rolling_watch_states()[("rolling_rule", "A", "price")]["status"] == "active"


def test_rolling_watch_window_expires_when_symbol_is_absent():
    engine = MonitorRuleEngine()
    engine.set_rules([_rule(rolling_window_seconds=10)])

    with patch("app.strategy.monitor.time.time", side_effect=[100.0, 111.0]):
        assert len(engine.evaluate(_df(10.0))) == 1
        # The symbol is absent for the second poll; a later matching row is a
        # new entry because the previous active state crossed its window.
        assert len(engine.evaluate(pl.DataFrame({"symbol": [], "close": []}))) == 0
        assert len(engine.evaluate(_df(10.0))) == 1


def test_rolling_watch_cooldown_suppresses_reentry_without_replaying_active_state():
    engine = MonitorRuleEngine()
    engine.set_rules([_rule(cooldown_seconds=100)])

    with patch("app.strategy.monitor.time.time", side_effect=[100.0, 101.0, 150.0, 151.0, 201.0]):
        assert len(engine.evaluate(_df(10.0))) == 1
        assert engine.evaluate(_df(9.0)) == []
        # Re-entry is within cooldown and is suppressed, but remains active.
        assert engine.evaluate(_df(10.0)) == []
        assert engine.evaluate(_df(9.0)) == []
        assert len(engine.evaluate(_df(10.0))) == 1


def test_rolling_watch_validation_contract():
    monitor_rules.validate(_rule())
    with pytest.raises(ValueError, match="rolling_window_seconds"):
        monitor_rules.validate(_rule(rolling_window_seconds=0))
    with pytest.raises(ValueError, match="rolling_watch_contract_version"):
        monitor_rules.validate(_rule(rolling_watch_contract_version="2.0"))
