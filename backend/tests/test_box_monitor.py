from datetime import date, timedelta

import polars as pl

from app.strategy.monitor import MonitorRuleEngine
from app.strategy.monitor_rules import normalize, validate


def _bars(count: int = 70, *, breakout: bool = False, volume: float = 2400.0) -> pl.DataFrame:
    start = date(2026, 1, 2)
    rows = []
    for index in range(count):
        close = 10.0 + (index % 4) * 0.05
        high = close + 0.2
        low = close - 0.2
        row_volume = 1000.0
        if breakout and index == count - 1:
            close = 10.8
            high = 11.0
            low = 10.5
            row_volume = volume
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": close - 0.05,
            "high": high,
            "low": low,
            "close": close,
            "volume": row_volume,
            "amount": row_volume * close,
        })
    return pl.DataFrame(rows)


def _rule(**overrides):
    rule = normalize({
        "id": "box_rule",
        "name": "箱体突破",
        "type": "box",
        "scope": "symbols",
        "symbols": ["000001.SZ"],
        "box_statuses": ["breakout_up"],
        "box_lookback_days": 60,
        "cooldown_seconds": 3600,
        **overrides,
    })
    validate(rule)
    return rule


def _engine(frame: pl.DataFrame, rule=None) -> MonitorRuleEngine:
    engine = MonitorRuleEngine()
    engine.set_rules([rule or _rule()])
    engine.set_history_loader(lambda _target_date, _lookback: frame)
    return engine


def test_box_monitor_emits_breakout_fields():
    frame = _bars(breakout=True)
    current = frame.tail(1).with_columns(pl.lit(0.05).alias("change_pct"))
    events = _engine(frame).evaluate(current)

    assert len(events) == 1
    event = events[0]
    assert event["source"] == "box"
    assert event["type"] == "向上突破"
    assert event["box_status"] == "breakout_up"
    assert event["box_upper"] < event["price"]
    assert event["box_volume_confirmed"] is True


def test_box_monitor_can_require_volume_confirmation():
    frame = _bars(breakout=True, volume=1100.0)
    current = frame.tail(1).with_columns(pl.lit(0.05).alias("change_pct"))
    rule = _rule(box_require_volume_confirmation=True)

    assert _engine(frame, rule).evaluate(current) == []


def test_box_monitor_reuses_cooldown_for_same_status():
    frame = _bars(breakout=True)
    current = frame.tail(1).with_columns(pl.lit(0.05).alias("change_pct"))
    engine = _engine(frame)

    assert len(engine.evaluate(current)) == 1
    assert engine.evaluate(current) == []


def test_box_monitor_rejects_invalid_status():
    rule = normalize({
        "id": "bad_box",
        "name": "错误箱体",
        "type": "box",
        "scope": "symbols",
        "symbols": ["000001.SZ"],
        "box_statuses": ["unknown"],
    })

    try:
        validate(rule)
    except ValueError as exc:
        assert "box_statuses" in str(exc)
    else:
        raise AssertionError("invalid box status should be rejected")
