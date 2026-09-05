from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"
SEQUOIA_IDS = (
    "sequoia_turtle_trade",
    "sequoia_ma_volume",
    "sequoia_high_tight_flag",
    "sequoia_limit_up_shakeout",
    "sequoia_uptrend_limit_down",
    "sequoia_rps_breakout",
)


def _panel(series_by_symbol: dict[str, list[dict]]) -> pl.DataFrame:
    rows = []
    start = date(2024, 1, 1)
    for symbol, values in series_by_symbol.items():
        for offset, values_for_day in enumerate(values):
            close = float(values_for_day["close"])
            rows.append({
                "symbol": symbol,
                "name": symbol,
                "date": start + timedelta(days=offset),
                "open": float(values_for_day.get("open", close)),
                "high": float(values_for_day.get("high", close)),
                "low": float(values_for_day.get("low", close)),
                "close": close,
                "volume": float(values_for_day.get("volume", 100.0)),
                "amount": float(values_for_day.get("amount", 100000000.0)),
            })
    return pl.DataFrame(rows)


def _signals(strategy_id: str, panel: pl.DataFrame, params: dict | None = None):
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    strategy = engine.get(strategy_id)
    fields = engine._matrix_field_columns(strategy, params=params or {})
    market = build_market_data_matrix(panel, field_columns=fields)
    return strategy.matrix_strategy.compute_signals(market, params or {})


def test_sequoia_strategies_are_registered_as_matrix_native():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    assert engine.load_errors() == []
    for strategy_id in SEQUOIA_IDS:
        strategy = engine.get(strategy_id)
        assert strategy.execution_backend == "matrix_native"
        assert strategy.matrix_strategy is not None


def test_turtle_trade_uses_previous_20_day_high_and_liquidity():
    values = [{"close": 10.0, "high": 10.2, "low": 9.8} for _ in range(20)]
    values.append({
        "open": 10.5,
        "close": 11.0,
        "high": 11.2,
        "low": 10.4,
        "amount": 110000000.0,
    })
    signals = _signals("sequoia_turtle_trade", _panel({"A": values}))
    assert signals.entry[:, 0].tolist() == [0] * 20 + [1]


def test_ma_volume_requires_cross_and_volume_expansion():
    values = [{"close": 12.0} for _ in range(15)]
    values.extend({"close": 8.0} for _ in range(5))
    values.append({"close": 30.0, "open": 29.0, "volume": 200.0})
    signals = _signals("sequoia_ma_volume", _panel({"A": values}))
    assert signals.entry[19, 0] == 0
    assert signals.entry[20, 0] == 1


def test_high_tight_flag_requires_high_range_tight_recent_range_and_shrinkage():
    values = [{"close": 15.0, "high": 20.0, "low": 10.0} for _ in range(1)]
    values.extend({"close": 17.5, "high": 18.0, "low": 17.0} for _ in range(39))
    values[-1]["volume"] = 50.0
    signals = _signals("sequoia_high_tight_flag", _panel({"A": values}))
    assert signals.entry[38, 0] == 0
    assert signals.entry[39, 0] == 1


def test_limit_up_shakeout_requires_yesterday_surge_and_today_shakeout():
    values = [
        {"close": 10.0, "volume": 100.0},
        {"close": 11.0, "volume": 100.0},
        {"open": 12.0, "close": 11.2, "high": 12.1, "low": 11.0, "volume": 250.0},
    ]
    signals = _signals("sequoia_limit_up_shakeout", _panel({"A": values}))
    assert signals.entry[2, 0] == 1


def test_uptrend_limit_down_requires_ma20_above_ma60_and_volume():
    values = [{"close": 10.0 + offset * 0.1} for offset in range(61)]
    previous_close = values[-1]["close"]
    values.append({
        "close": previous_close * 0.9,
        "open": previous_close * 0.95,
        "high": previous_close * 0.96,
        "low": previous_close * 0.89,
        "volume": 300.0,
    })
    signals = _signals("sequoia_uptrend_limit_down", _panel({"A": values}))
    assert signals.entry[60, 0] == 0
    assert signals.entry[61, 0] == 1


def test_rps_breakout_ranks_120_day_strength_cross_sectionally():
    leader = [{"close": 10.0 + offset * (190.0 / 120.0), "high": 10.5 + offset * (190.0 / 120.0)}
              for offset in range(121)]
    laggard = [{"close": 10.0, "high": 10.5} for _ in range(121)]
    signals = _signals(
        "sequoia_rps_breakout",
        _panel({"LEADER": leader, "LAGGARD": laggard}),
    )
    assert signals.entry[119, :].tolist() == [0, 0]
    assert signals.entry[120, :].tolist() == [0, 1]
    np.testing.assert_allclose(signals.score[120, :], [50.0, 100.0])


def test_sequoia_strategies_fail_closed_when_history_is_insufficient():
    panel = _panel({"A": [{"close": 10.0} for _ in range(10)]})
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    for strategy_id in SEQUOIA_IDS:
        strategy = engine.get(strategy_id)
        market = build_market_data_matrix(
            panel,
            field_columns=engine._matrix_field_columns(strategy),
        )
        signals = strategy.matrix_strategy.compute_signals(market, {})
        assert not signals.entry.any(), strategy_id
