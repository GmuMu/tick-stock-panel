from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import polars as pl

from app.api.stock_analysis import get_levels
from app.indicators.levels import (
    LEVEL_PRICE_BASIS_ADJUSTED,
    LEVEL_PRICE_BASIS_CANONICAL,
    LEVEL_TYPES,
    compute_levels,
    level_data_quality,
    level_price_basis,
)
from app.indicators.pipeline import compute_indicators


def _daily_bars(rows: int = 130) -> pl.DataFrame:
    records = []
    for index in range(rows):
        close = 10.0 + index * 0.08 + (index % 5) * 0.03
        records.append(
            {
                "symbol": "600000.SH",
                "date": date(2026, 1, 1) + timedelta(days=index),
                "open": close - 0.04,
                "high": close + 0.16 + (index % 3) * 0.02,
                "low": close - 0.14 - (index % 2) * 0.01,
                "close": close,
                "volume": 1000.0 + index * 20.0,
                "raw_close": close * 0.8,
                "raw_high": (close + 0.16 + (index % 3) * 0.02) * 0.8,
                "raw_low": (close - 0.14 - (index % 2) * 0.01) * 0.8,
            }
        )
    return pl.DataFrame(records)


def test_level_contract_uses_adjusted_ohlc_and_reports_fresh_quality() -> None:
    enriched = compute_indicators(_daily_bars())
    quality = level_data_quality(enriched)

    assert level_price_basis(enriched) == LEVEL_PRICE_BASIS_ADJUSTED
    assert quality.dataset == "price_levels"
    assert quality.status == "FRESH"
    assert quality.coverage_ratio == 1.0
    assert quality.usable is True
    assert compute_levels(enriched)["pivot"]


def test_raw_price_changes_do_not_change_adjusted_level_values() -> None:
    enriched = compute_indicators(_daily_bars())
    changed_raw = enriched.with_columns(
        (pl.col("raw_close") * 3).alias("raw_close"),
        (pl.col("raw_high") * 3).alias("raw_high"),
        (pl.col("raw_low") * 3).alias("raw_low"),
    )

    assert compute_levels(changed_raw) == compute_levels(enriched)


def test_level_contract_fail_closes_on_missing_or_partial_ohlc() -> None:
    enriched = compute_indicators(_daily_bars())

    missing = enriched.drop("high")
    missing_quality = level_data_quality(missing)
    assert missing_quality.status == "INVALID"
    assert missing_quality.usable is False
    assert compute_levels(missing) == {key: [] for key in LEVEL_TYPES}

    close_values = [None if index == 5 else value for index, value in enumerate(enriched["close"])]
    partial = enriched.with_columns(pl.Series("close", close_values))
    partial_quality = level_data_quality(partial)
    assert partial_quality.status == "PARTIAL"
    assert partial_quality.actual_rows == enriched.height - 1
    assert compute_levels(partial) == {key: [] for key in LEVEL_TYPES}


def test_levels_api_exposes_price_basis_and_quality() -> None:
    enriched = compute_indicators(_daily_bars())

    class Repo:
        def resolve_asset_type(self, symbol: str) -> str:
            return "stock"

        def get_daily_asset(self, asset_type, symbol, start, end):
            return enriched

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(repo=Repo()))
    )
    result = get_levels(request, "600000.SH", days=120)

    assert result["price_basis"] == LEVEL_PRICE_BASIS_ADJUSTED
    assert result["data_quality"]["status"] == "FRESH"
    assert result["data_quality"]["usable"] is True


def test_levels_api_marks_missing_data_without_fabricating_levels() -> None:
    class EmptyRepo:
        def resolve_asset_type(self, symbol: str) -> str:
            return "stock"

        def get_daily_asset(self, asset_type, symbol, start, end):
            return pl.DataFrame()

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(repo=EmptyRepo()))
    )
    result = get_levels(request, "600000.SH", days=120)

    assert result["levels"] == {key: [] for key in LEVEL_TYPES}
    assert result["price_basis"] == LEVEL_PRICE_BASIS_CANONICAL
    assert result["data_quality"]["status"] == "MISSING"
    assert result["data_quality"]["usable"] is False


def test_level_price_basis_falls_back_for_canonical_ohlc() -> None:
    frame = _daily_bars().drop(["raw_close", "raw_high", "raw_low"])

    assert level_price_basis(frame) == LEVEL_PRICE_BASIS_CANONICAL
