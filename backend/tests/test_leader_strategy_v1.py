"""龙头战法 V1 的入场触发、确认项和断板开关回归测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin.leader_strategy_v1 import MATRIX_STRATEGY
from app.strategy.engine import StrategyEngine


BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def _panel(*, include_broken_board: bool = False) -> pl.DataFrame:
    rows = []
    start = date(2024, 1, 1)
    for offset in range(75):
        if offset < 72:
            boards = 0
            limit_up = 0
        elif offset == 72:
            boards = 2
            limit_up = 1
        elif offset == 73:
            boards = 0 if include_broken_board else 3
            limit_up = 0 if include_broken_board else 1
        else:
            boards = 1 if include_broken_board else 4
            limit_up = 1
        if offset < 72:
            close = 10.0
        elif offset == 72:
            close = 11.0
        elif offset == 73 and include_broken_board:
            close = 10.5
        elif offset == 73:
            close = 12.1
        elif include_broken_board:
            close = 11.55
        else:
            close = 13.31
        rows.append(
            {
                "symbol": "000001.SZ",
                "date": start + timedelta(days=offset),
                "open": close * 0.95,
                "high": close * 1.10,
                "low": close * 0.94,
                "close": close * (1.10 if limit_up else 1.0),
                "volume": 2000.0 if limit_up else 1000.0,
                "amount": 200000.0,
                "turnover_rate": 6.0 if limit_up else 2.0,
                "consecutive_limit_ups": boards,
                "signal_limit_up": limit_up,
            }
        )
    return pl.DataFrame(rows)


def _market(panel: pl.DataFrame):
    strategy = StrategyEngine(strategy_dirs=[BUILTIN_DIR]).get("leader_strategy_v1")
    fields = StrategyEngine._matrix_field_columns(strategy, None, {})
    return build_market_data_matrix(panel, field_columns=fields)


def test_leader_strategy_v1_requires_trigger_and_two_confirmations():
    market = _market(_panel())
    signals = MATRIX_STRATEGY.compute_signals(
        market,
        {
            "require_limit_up": True,
            "min_boards": 2,
            "min_limit_count": 3,
            "min_confirmations": 2,
            "min_change": 5.0,
            "min_turnover": 5.0,
            "min_vol_ratio": 1.2,
        },
    )

    assert signals.entry[-3:, 0].tolist() == [1, 1, 1]
    assert signals.entry[:72, 0].sum() == 0


def test_leader_strategy_v1_can_include_a_broken_board_recovery():
    market = _market(_panel(include_broken_board=True))

    without_recovery = MATRIX_STRATEGY.compute_signals(
        market,
        {"include_broken_board": False, "min_confirmations": 1},
    )
    with_recovery = MATRIX_STRATEGY.compute_signals(
        market,
        {"include_broken_board": True, "min_confirmations": 1},
    )

    assert without_recovery.entry[-1, 0] == 0
    assert with_recovery.entry[-1, 0] == 1


def test_leader_strategy_v1_is_registered_as_a_builtin():
    strategy = StrategyEngine(strategy_dirs=[BUILTIN_DIR]).get("leader_strategy_v1")
    assert strategy.meta["name"] == "龙头战法 V1"
    assert strategy.execution_backend == "matrix_native"
