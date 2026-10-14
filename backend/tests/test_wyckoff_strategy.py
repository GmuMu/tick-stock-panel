"""威科夫吸筹策略的区间突破、Spring 过滤和支撑退出测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def _bars(event: str | None = None) -> pl.DataFrame:
    rows = []
    start = date(2025, 1, 2)
    for index in range(31):
        close = 10.0
        open_price = 9.9
        high = 10.1
        low = 9.8
        volume = 1000.0
        if event == "spring" and index == 25:
            open_price, high, low, close, volume = 9.9, 10.0, 9.6, 9.95, 900.0
        if event == "spring_with_gap" and index == 25:
            open_price, high, low, close, volume = 9.9, 10.0, 9.6, 9.95, 900.0
        if event in {"sos", "spring"} and index == 30:
            open_price, high, low, close, volume = 10.0, 10.5, 9.95, 10.4, 1600.0
        if event == "spring_with_gap" and index == 30:
            open_price, high, low, close, volume = 10.0, 10.5, 9.95, 10.4, 1600.0
        if event == "quiet_breakout" and index == 30:
            open_price, high, low, close, volume = 10.0, 10.5, 9.95, 10.4, 1000.0
        if event == "support_break" and index == 30:
            open_price, high, low, close, volume = 9.9, 9.95, 9.4, 9.5, 1200.0
        if event == "spring_with_gap" and index == 26:
            open_price = high = low = close = volume = None
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
    return pl.DataFrame(rows)


def _signals(panel: pl.DataFrame, params: dict | None = None):
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    strategy = engine.get("wyckoff_accumulation")
    fields = engine._matrix_field_columns(strategy, params=params or {})
    market = build_market_data_matrix(panel, field_columns=fields)
    return strategy.matrix_strategy.compute_signals(market, params or {})


def test_wyckoff_sos_requires_range_breakout_and_volume_confirmation():
    signals = _signals(_bars("sos"))
    quiet = _signals(_bars("quiet_breakout"))

    assert signals.entry[-1, 0] == 1
    assert quiet.entry[-1, 0] == 0


def test_wyckoff_can_require_recent_spring_before_sos():
    with_spring = _signals(_bars("spring"), {"require_spring": True})
    without_spring = _signals(_bars("sos"), {"require_spring": True})

    assert with_spring.entry[-1, 0] == 1
    assert without_spring.entry[-1, 0] == 0


def test_spring_lookback_skips_missing_market_bars():
    signals = _signals(
        _bars("spring_with_gap"),
        {"require_spring": True, "spring_lookback": 4},
    )

    assert signals.entry[-1, 0] == 1


def test_wyckoff_exits_when_accumulation_support_breaks():
    signals = _signals(_bars("support_break"))

    assert signals.exit[-1, 0] == 1


def test_wyckoff_strategy_is_registered_as_builtin():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])

    assert engine.load_errors() == []
    strategy = engine.get("wyckoff_accumulation")
    assert strategy.meta["name"] == "威科夫吸筹突破"
    assert strategy.execution_backend == "matrix_native"
