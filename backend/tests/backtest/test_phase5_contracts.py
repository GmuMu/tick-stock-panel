from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

import polars as pl

from app.backtest.contracts import (
    BacktestProvenance,
    BacktestValidation,
    coverage_from_labels,
)
from app.backtest.factor import FactorBacktestService, FactorConfig
from app.price_limits import market_rules_contract


def _panel(start: date, days: int) -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["600000.SH"] * days,
        "date": [start + timedelta(days=index) for index in range(days)],
        "open": [10.0 + index for index in range(days)],
        "high": [10.1 + index for index in range(days)],
        "low": [9.9 + index for index in range(days)],
        "close": [10.0 + index for index in range(days)],
        "volume": [1000.0] * days,
        "amount": [10000.0] * days,
        "turnover_rate": [1.0 + index * 0.01 for index in range(days)],
    })


class _GenerationEngine:
    def __init__(self, panel: pl.DataFrame, generation: str = "g1") -> None:
        self.panel = panel
        self.generation = generation

    def data_generation(self, _asset_type: str) -> str:
        return self.generation

    def assert_data_generation(self, _asset_type: str, expected: str | None) -> None:
        if expected != self.generation:
            raise RuntimeError("generation changed")

    def load_panel(self, symbols, start, end, columns, asset_type, expected_generation=None):
        assert expected_generation == self.generation
        del symbols, asset_type
        return self.panel.filter(
            (pl.col("date") >= start) & (pl.col("date") <= end)
        ).select([column for column in columns if column in self.panel.columns])


def test_coverage_contract_serializes_and_checks_warmup_and_forward_tail():
    coverage = coverage_from_labels(
        [
            date(2025, 12, 1),
            date(2026, 1, 5),
            date(2026, 1, 30),
        ],
        asset_type="stock",
        requested_start=date(2026, 1, 5),
        requested_end=date(2026, 1, 12),
        load_start=date(2025, 12, 1),
        load_end=date(2026, 1, 30),
        warmup_start=date(2025, 12, 1),
        simulation_end=date(2026, 1, 12),
        forward_end=date(2026, 1, 30),
        generation="g1",
    )

    assert coverage.complete is True
    assert asdict(coverage)["forward_end"] == "2026-01-30"
    assert BacktestValidation(**asdict(BacktestValidation())).to_dict()["code"] == "ok"
    assert BacktestProvenance(run_id="r").to_dict()["run_id"] == "r"


def test_factor_rejects_missing_forward_tail_when_generation_is_managed():
    start = date(2026, 1, 5)
    config = FactorConfig(
        factor_name="turnover_rate",
        symbols=None,
        start=start,
        end=start + timedelta(days=4),
        n_groups=2,
        rebalance="daily",
    )
    result = FactorBacktestService(_GenerationEngine(_panel(start, 5))).run(config)

    assert result.error is not None
    assert result.validation["code"] == "INSUFFICIENT_FORWARD_COVERAGE"
    assert result.validation["status"] == "rejected"
    assert result.data_coverage["generation"] == "g1"
    assert result.provenance["validation"]["code"] == "INSUFFICIENT_FORWARD_COVERAGE"


def test_market_rules_snapshot_distinguishes_stock_and_etf():
    stock = market_rules_contract("stock")
    etf = market_rules_contract("etf")

    assert stock["t_plus_one"] is True
    assert stock["stamp_tax_sell_only"] is True
    assert etf["t_plus_one"] is False
    assert etf["stamp_tax_sell_only"] is False
