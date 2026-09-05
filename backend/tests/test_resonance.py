from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

from app.strategy import monitor_rules
from app.strategy.alert_rule import ALERT_RULE_CONTRACT_VERSION
from app.strategy.monitor import MonitorRuleEngine
from app.strategy.resonance import (
    RESONANCE_CONTRACT_VERSION,
    advance_resonance,
)


def _rule(**overrides) -> dict:
    rule = monitor_rules.normalize({
        "id": "resonance_rule",
        "name": "共振测试",
        "type": "resonance",
        "scope": "symbols",
        "symbols": ["A"],
        "conditions": [
            {"field": "signal_alpha", "op": "truth"},
            {"field": "signal_beta", "op": "truth"},
            {"field": "signal_gamma", "op": "truth"},
        ],
        "logic": "or",
        "cooldown_seconds": 0,
        "resonance_window_seconds": 30,
        "resonance_min_signals": 2,
        "enabled": True,
    })
    rule.update(overrides)
    return rule


def _df(*, alpha: bool = False, beta: bool = False, gamma: bool = False) -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["A"],
        "name": ["测试标的"],
        "close": [10.0],
        "change_pct": [0.01],
        "signal_alpha": [alpha],
        "signal_beta": [beta],
        "signal_gamma": [gamma],
    })


def test_resonance_pending_entered_and_expired_transitions():
    pending = advance_resonance(
        None,
        rule_id="r",
        symbol="A",
        observed_signals={"signal_alpha"},
        now=100.0,
        window_seconds=30,
        min_signals=2,
        cooldown_seconds=0,
    )
    assert pending.should_trigger is False
    assert pending.state.status == "pending"
    assert pending.state.transition == "pending"
    assert pending.state.contract_version == RESONANCE_CONTRACT_VERSION

    entered = advance_resonance(
        pending.state,
        rule_id="r",
        symbol="A",
        observed_signals={"signal_beta"},
        now=110.0,
        window_seconds=30,
        min_signals=2,
        cooldown_seconds=0,
    )
    assert entered.should_trigger is True
    assert entered.state.status == "active"
    assert entered.state.transition == "entered"
    assert set(entered.state.active_signals) == {"signal_alpha", "signal_beta"}
    assert entered.state.signal_times["signal_alpha"] == 100.0

    continued = advance_resonance(
        entered.state,
        rule_id="r",
        symbol="A",
        observed_signals={"signal_beta"},
        now=111.0,
        window_seconds=30,
        min_signals=2,
        cooldown_seconds=0,
    )
    assert continued.should_trigger is False
    assert continued.state.transition == "continued"

    expired = advance_resonance(
        entered.state,
        rule_id="r",
        symbol="A",
        observed_signals=set(),
        now=141.0,
        window_seconds=30,
        min_signals=2,
        cooldown_seconds=0,
    )
    assert expired.state.status == "inactive"
    assert expired.state.transition == "expired"


def test_resonance_engine_emits_snapshot_once_and_rearms_after_window():
    engine = MonitorRuleEngine()
    engine.set_rules([_rule()])

    with patch("app.strategy.monitor.time.time", side_effect=[100.0, 110.0, 111.0, 142.0, 143.0]):
        assert engine.evaluate(_df(alpha=True)) == []
        entered = engine.evaluate(_df(beta=True))
        assert len(entered) == 1
        assert entered[0]["type"] == "resonance"
        assert entered[0]["signals"] == ["signal_alpha", "signal_beta"]
        assert entered[0]["resonance"]["transition"] == "entered"
        assert entered[0]["alert_rule"]["alert_rule_contract_version"] == ALERT_RULE_CONTRACT_VERSION
        assert entered[0]["alert_rule"]["revision"] == 1

        assert engine.evaluate(_df(beta=True)) == []
        # Both old signals have expired; a fresh pair can enter again.
        assert engine.evaluate(_df(alpha=True)) == []
        reentered = engine.evaluate(_df(beta=True))
        assert len(reentered) == 1
        assert reentered[0]["resonance"]["transition"] == "entered"


def test_resonance_cooldown_suppresses_reentry_until_it_expires():
    first = advance_resonance(
        None,
        rule_id="r",
        symbol="A",
        observed_signals={"signal_a", "signal_b"},
        now=100.0,
        window_seconds=10,
        min_signals=2,
        cooldown_seconds=100,
    )
    exited = advance_resonance(
        first.state,
        rule_id="r",
        symbol="A",
        observed_signals=set(),
        now=111.0,
        window_seconds=10,
        min_signals=2,
        cooldown_seconds=100,
    )
    suppressed = advance_resonance(
        exited.state,
        rule_id="r",
        symbol="A",
        observed_signals={"signal_a", "signal_b"},
        now=150.0,
        window_seconds=10,
        min_signals=2,
        cooldown_seconds=100,
    )
    assert suppressed.should_trigger is False
    assert suppressed.state.status == "active"

    exited_again = advance_resonance(
        suppressed.state,
        rule_id="r",
        symbol="A",
        observed_signals=set(),
        now=161.0,
        window_seconds=10,
        min_signals=2,
        cooldown_seconds=100,
    )
    reentered = advance_resonance(
        exited_again.state,
        rule_id="r",
        symbol="A",
        observed_signals={"signal_a", "signal_b"},
        now=201.0,
        window_seconds=10,
        min_signals=2,
        cooldown_seconds=100,
    )
    assert reentered.should_trigger is True


def test_resonance_validation_rejects_non_signal_conditions_and_invalid_contract():
    monitor_rules.validate(_rule())
    with pytest.raises(ValueError, match="truth"):
        monitor_rules.validate(_rule(conditions=[
            {"field": "signal_alpha", "op": "truth"},
            {"field": "close", "op": ">", "value": 10},
        ]))
    with pytest.raises(ValueError, match="resonance_contract_version"):
        monitor_rules.validate(_rule(resonance_contract_version="2.0"))
    with pytest.raises(ValueError, match="alert_rule_contract_version"):
        monitor_rules.validate(_rule(alert_rule_contract_version="2.0"))
