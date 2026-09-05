"""TASK-0003 baseline smoke tests for the primary application boundaries.

These tests are intentionally offline and deterministic. They provide a small,
stable acceptance surface while the larger regression suites continue to cover
module-specific behavior.
"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl
from fastapi.testclient import TestClient

from app.backtest.engine import BacktestEngine, MatcherConfig
from app.indicators.pipeline import compute_all
from app.main import app
from app.plugins.fuyao.provider import _map_snapshot_row
from app.strategy.engine import StrategyDataContext, StrategyEngine
from app.strategy.monitor import MonitorRuleEngine


def _daily_frame(days: int = 40) -> pl.DataFrame:
    closes = [10.0 + i * 0.1 for i in range(days)]
    return pl.DataFrame(
        {
            "symbol": ["600000.SH"] * days,
            "date": [date(2026, 1, 2) + timedelta(days=i) for i in range(days)],
            "open": [value - 0.05 for value in closes],
            "high": [value + 0.1 for value in closes],
            "low": [value - 0.1 for value in closes],
            "close": closes,
            "volume": [10000.0] * days,
            "amount": [value * 10000 for value in closes],
            "raw_close": closes,
            "raw_high": [value + 0.1 for value in closes],
            "raw_low": [value - 0.1 for value in closes],
        }
    )


def test_provider_and_indicator_boundary_is_canonical() -> None:
    record = _map_snapshot_row(
        {
            "thscode": "600000.SH",
            "last_price": 10.5,
            "prev_price": 10.0,
            "price_change_ratio_pct": 5.0,
            "volume": 12345,
            "turnover": 100000.0,
        },
        fetched_ms=1780000000000,
    )

    assert record is not None
    assert record["symbol"] == "600000.SH"
    assert record["change_pct"] == 0.05
    assert record["volume"] == 123

    enriched = compute_all(_daily_frame())
    assert enriched.height == 40
    assert {"ma5", "rsi_14", "macd_dif"}.issubset(enriched.columns)
    assert enriched["ma5"][-1] == 13.7


def test_strategy_discovery_and_execution_boundary(tmp_path) -> None:
    strategy_path = tmp_path / "baseline_strategy.py"
    strategy_path.write_text(
        """import polars as pl

META = {
    "id": "baseline_strategy",
    "name": "Baseline Strategy",
    "asset_types": ["stock"],
    "timeframes": ["1d"],
}
BASIC_FILTER = {"enabled": False}
EXECUTION_BACKEND = "polars_expr"

def filter(df, params):
    return pl.col("close") >= 10.2
""",
        encoding="utf-8",
    )
    engine = StrategyEngine(strategy_dirs=[tmp_path])
    current = _daily_frame(3)

    result = engine.run(
        "baseline_strategy",
        StrategyDataContext(
            asset_type="stock",
            timeframe="1d",
            as_of=current["date"][-1],
            current=current,
        ),
    )

    assert engine.has("baseline_strategy")
    assert not engine.load_errors()
    # 普通日线策略只评估 context.as_of, 不把注入的历史窗口当作结果集。
    assert result.total == 1
    assert [row["symbol"] for row in result.rows] == ["600000.SH"]


def test_backtest_matching_boundary() -> None:
    panel = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * 3,
            "date": [date(2026, 1, 2) + timedelta(days=i) for i in range(3)],
            "open": [10.0, 11.0, 12.0],
            "high": [10.0, 11.0, 12.0],
            "low": [10.0, 11.0, 12.0],
            "close": [10.0, 11.0, 12.0],
            "volume": [10000.0] * 3,
        }
    )
    result = BacktestEngine(repo=None).simulate(
        panel,
        pl.Series("entries", [True, False, False]),
        pl.Series("exits", [False, True, False]),
        MatcherConfig(matching="close_t", fees_pct=0, slippage_bps=0),
    )

    assert len(result.trades) == 1
    assert result.trades[0].entry_price == 10.0
    assert result.trades[0].exit_price == 11.0
    assert result.trades[0].pnl_pct == 0.1


def test_monitor_evaluation_boundary_and_cooldown() -> None:
    engine = MonitorRuleEngine()
    engine.set_rules(
        [
            {
                "id": "baseline-price",
                "name": "Baseline Price",
                "type": "price",
                "scope": "symbols",
                "symbols": ["600000.SH"],
                "conditions": [{"field": "close", "op": ">=", "value": 10}],
                "logic": "and",
                "cooldown_seconds": 3600,
                "severity": "info",
                "enabled": True,
            }
        ]
    )
    quotes = pl.DataFrame(
        {"symbol": ["600000.SH"], "name": ["浦发银行"], "close": [10.5], "change_pct": [0.01]}
    )

    events = engine.evaluate(quotes)
    assert len(events) == 1
    assert events[0]["symbol"] == "600000.SH"
    assert engine.evaluate(quotes) == []


def test_api_smoke_boundary() -> None:
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert "/health" in openapi.json()["paths"]
