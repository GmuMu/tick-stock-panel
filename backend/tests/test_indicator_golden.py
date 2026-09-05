"""Offline golden tests for the versioned indicator contract."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from app.indicators.pipeline import INDICATOR_COLUMNS, compute_indicators
from app.indicators.spec import INDICATOR_SPEC_VERSION

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "indicator_golden" / "indicators.json"
BASE_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "amount")


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _golden_bars(fixture: dict) -> pl.DataFrame:
    start = date.fromisoformat(fixture["start_date"])
    symbol = fixture["symbol"]
    rows = []
    for index, close in enumerate(fixture["closes"]):
        volume = 1000.0 + index * 25.0
        rows.append(
            {
                "symbol": symbol,
                "date": start + timedelta(days=index),
                "open": close - 0.05,
                "high": close + 0.2 + (index % 3) * 0.02,
                "low": close - 0.2 - (index % 2) * 0.01,
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
    return pl.DataFrame(rows)


def test_indicator_golden_fixture_is_versioned_and_column_complete() -> None:
    fixture = _fixture()

    assert fixture["spec_version"] == INDICATOR_SPEC_VERSION
    assert fixture["expected_indicator_columns"] == sorted(
        fixture["expected_indicator_columns"]
    )
    assert set(fixture["expected_indicator_columns"]) == set(INDICATOR_COLUMNS)
    assert set(fixture["expected_last"]) == set(fixture["expected_indicator_columns"])


def test_indicator_golden_values_match_at_latest_bar() -> None:
    fixture = _fixture()
    result = compute_indicators(_golden_bars(fixture))
    latest = result.tail(1).to_dicts()[0]

    for name, expected in fixture["expected_last"].items():
        assert latest[name] == pytest.approx(expected, abs=1e-12), name


def test_indicator_golden_output_columns_and_boundary_inputs() -> None:
    fixture = _fixture()
    bars = _golden_bars(fixture)
    result = compute_indicators(bars)

    assert set(result.columns) == set(BASE_COLUMNS) | set(INDICATOR_COLUMNS)
    assert result.height == len(fixture["closes"])

    empty = compute_indicators(bars.head(0))
    assert empty.is_empty()
    assert empty.columns == list(BASE_COLUMNS)

    one = bars.head(1).with_columns(pl.lit(0.0).alias("volume"))
    boundary = compute_indicators(one)
    assert boundary.height == 1
    assert boundary["prev_close"][0] is None
    assert boundary["ma5"][0] is None
    assert boundary["vol_ratio_5d"][0] is None
    assert boundary["atr_14"][0] == pytest.approx(0.4)
